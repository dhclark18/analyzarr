# jobs.py
"""
Simple in-process job system for Analyzarr.

Exports:
 - start_replace_job(ep_key) -> job_id
 - start_library_scan_job(run_fn, description=None) -> job_id
 - get_job(job_id) -> job dict or None
 - append_log(job_id, text)
 - update_job(job_id, **kwargs)
 - wait_for_sonarr_import(sonarr_client, series_id, season_number, episode_number,
                         episode_id=None, job_id=None, timeout=300, poll_interval=5)
 - jobs (dict)
 - jobs_lock (threading.Lock)
"""

import uuid
import time
import threading
import logging
import os
import requests
from typing import Callable, Optional

# In-memory job store
jobs = {}
jobs_lock = threading.Lock()

# Internal API base (used by some workflows if needed)
INTERNAL_API_BASE = os.environ.get("INTERNAL_API_BASE", "http://127.0.0.1:5001")

# Default timeouts / configuration (can be overridden via env)
SONARR_IMPORT_TIMEOUT = int(os.environ.get("SONARR_IMPORT_TIMEOUT", "300"))
ANALYZER_TIMEOUT = int(os.environ.get("ANALYZER_TIMEOUT", "600"))

# --- Logging helper for this module ---
logger = logging.getLogger("jobs")

# --- Low-level helpers (thread-safe using jobs_lock) ------------------------
def _with_lock(fn):
    def wrapped(*args, **kwargs):
        with jobs_lock:
            return fn(*args, **kwargs)
    return wrapped

@_with_lock
def create_job_record(job_id: str, init: dict):
    """Create or overwrite job record with `init` dict."""
    jobs[job_id] = init

def get_job(job_id: str):
    """Return job dict (caller should not mutate it directly)."""
    with jobs_lock:
        # return a shallow copy to avoid accidental mutation
        job = jobs.get(job_id)
        return dict(job) if job is not None else None

def _append_log(job_id: str, txt: str):
    """Internal append log; assumes jobs_lock already held by caller or safe to call."""
    entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {txt}"
    if job_id not in jobs:
        # fallback: create a basic system job entry (shouldn't usually happen)
        jobs[job_id] = {"status": "unknown", "progress": 0, "message": "", "log": [], "type": "system"}
    jobs[job_id].setdefault("log", []).append(entry)
    # cap logs
    if len(jobs[job_id]["log"]) > 1000:
        jobs[job_id]["log"] = jobs[job_id]["log"][-1000:]

@_with_lock
def append_log(job_id: str, txt: str):
    """Thread-safe append to a job's log."""
    _append_log(job_id, txt)

@_with_lock
def update_job(job_id: str, **kwargs):
    """
    Set keys on the job record in a thread-safe way.
    Typical kwargs: status, progress (0-100), message, type, episode_key, etc.
    """
    job = jobs.get(job_id)
    if not job:
        # create a placeholder if missing
        jobs[job_id] = {
            "status": kwargs.get("status", "unknown"),
            "progress": kwargs.get("progress", 0),
            "message": kwargs.get("message", ""),
            "log": [],
            "type": kwargs.get("type", "generic")
        }
        job = jobs[job_id]

    # update fields
    for k, v in kwargs.items():
        job[k] = v

def poll_sonarr_command(command_id, max_wait=120):
    """Poll Sonarr for completion or rejection."""
    start = time.time()
    while time.time() - start < max_wait:
        r = requests.get(
            f"{SONARR_URL}/api/v3/command/{command_id}",
            headers={"X-Api-Key": SONARR_API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        state = data.get("state")
        status = data.get("status")
        error = data.get("errorMessage")

        if state == "completed" and not error and status == "completed":
            return {"status": "done", "message": "Sonarr import completed"}

        if error or status == "failed":
            return {"status": "error", "message": error or "Sonarr command failed"}

        time.sleep(2)

    return {"status": "error", "message": "Sonarr import timed out"}
 
# --- Job creators ----------------------------------------------------------
def _new_job_id() -> str:
    return str(uuid.uuid4())

def start_replace_job(episode_key: str) -> str:
    """
    Create a replace job record and return job_id. This function does NOT run
    the replace logic itself — the caller (e.g. api.py) typically spawns the
    thread that executes the job (so the job_func can capture local vars).
    """
    job_id = _new_job_id()
    create_job_record(job_id, {
        "status": "queued",
        "progress": 0,
        "message": "Queued",
        "log": [],
        "episode_key": episode_key,
        "type": "replace"
    })
    return job_id

def start_library_scan_job(run_fn: Callable[[str, Callable, Callable], None], description: Optional[str] = None) -> str:
    """
    Start a library_scan job that runs `run_fn(job_id, append_log, update_job)`.
    This function DOES spawn a thread and runs run_fn in background.
    Returns job_id immediately.
    """
    job_id = _new_job_id()
    create_job_record(job_id, {
        "status": "queued",
        "progress": 0,
        "message": description or "Queued library scan",
        "log": [],
        "type": "library_scan"
    })

    def _worker():
        try:
            append_log(job_id, "Starting library scan job")
            update_job(job_id, status="running", progress=5)
            # run_fn should take (job_id, append_log, update_job)
            try:
                run_fn(job_id, append_log, update_job)
                update_job(job_id, status="done", progress=100, message="Library scan complete")
                append_log(job_id, "Library scan finished")
            except Exception as e:
                append_log(job_id, f"Library scan error: {e}")
                update_job(job_id, status="error", message=str(e))
        except Exception:
            logger.exception("Unhandled exception in library scan worker")
            update_job(job_id, status="error", message="Unhandled exception in worker")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return job_id

# --- Sonarr import waiter --------------------------------------------------
def wait_for_sonarr_import(
    sonarr_client,
    series_id: int,
    season_number: int,
    episode_number: int,
    episode_id: Optional[int] = None,
    job_id: Optional[str] = None,
    timeout: int = SONARR_IMPORT_TIMEOUT,
    poll_interval: int = 5
) -> bool:
    """
    Poll Sonarr until the requested episode shows hasFile=True.
    - Tries /episode/{episode_id} if episode_id provided (fast/direct)
    - Falls back to /episode?seriesId={series_id} and matches season/episode
    - Updates job progress/log if job_id is given.
    - Returns True if import detected; raises TimeoutError on timeout.
    """
    start = time.time()
    if job_id:
        append_log(job_id, f"Waiting for Sonarr import of S{season_number:02}E{episode_number:02}...")
        update_job(job_id, status="running", progress=50, message="Waiting for Sonarr import")

    while True:
        try:
            # 1) Try episode/{id} endpoint first
            if episode_id:
                try:
                    ep = sonarr_client.get(f"episode/{episode_id}")
                except Exception as e:
                    ep = None
                    append_log(job_id or "system", f"Sonarr episode/{episode_id} check failed: {e}")
                if isinstance(ep, dict) and ep.get("hasFile"):
                    if job_id:
                        append_log(job_id, f"Detected imported file via episode/{episode_id}")
                        update_job(job_id, progress=90, message="Episode imported")
                    return True

            # 2) Fallback: query episodes by series and look for the matching S/E
            episodes = sonarr_client.get(f"episode?seriesId={series_id}") or []
            found_match_entry = False
            for e in episodes:
                snum = e.get("seasonNumber")
                en   = e.get("episodeNumber")
                if snum == season_number and en == episode_number:
                    found_match_entry = True
                    if e.get("hasFile"):
                        if job_id:
                            append_log(job_id, f"Detected imported file for S{season_number:02}E{episode_number:02} in series listing")
                            update_job(job_id, progress=90, message="Episode imported")
                        return True
                    else:
                        # entry exists but no file yet — keep waiting
                        if job_id:
                            append_log(job_id, f"Found S{season_number:02}E{episode_number:02} but no file yet (will keep polling)")
                    break

            if not found_match_entry:
                # no episode entry found; log and keep polling
                if job_id:
                    append_log(job_id, f"No episode entry for S{season_number:02}E{episode_number:02} found in Sonarr yet")

        except Exception as exc:
            # Sonarr or network error; log and retry until timeout
            logger.exception("Error while polling Sonarr for import")
            if job_id:
                append_log(job_id, f"Sonarr poll error: {exc}")

        # Timeout check
        elapsed = time.time() - start
        if elapsed > timeout:
            msg = f"Timeout waiting for S{season_number:02}E{episode_number:02} after {timeout}s"
            if job_id:
                append_log(job_id, msg)
                update_job(job_id, status="error", message="Timed out waiting for Sonarr import")
            raise TimeoutError(msg)

        time.sleep(poll_interval)

# --- Utilities useful for debugging / tests --------------------------------
def list_running_jobs():
    with jobs_lock:
        return [dict(j) for j in jobs.values() if j.get("status") == "running"]

# If module is run directly, print a tiny status summary
if __name__ == "__main__":
    print("Jobs module loaded. Current jobs:")
    with jobs_lock:
        for k, v in jobs.items():
            print(k, v.get("status"), v.get("message"))

