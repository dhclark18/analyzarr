# jobs.py
import uuid
import time
import threading
import subprocess
import requests
import os

jobs = {}
jobs_lock = threading.Lock()

SONARR_URL = os.environ.get("SONARR_URL")
SONARR_API = os.environ.get("SONARR_API_KEY")
INTERNAL_API_BASE = os.environ.get("INTERNAL_API_BASE", "http://127.0.0.1:80")


def _with_lock(fn):
    def wrapped(*args, **kwargs):
        with jobs_lock:
            return fn(*args, **kwargs)
    return wrapped


@_with_lock
def create_job_record(job_id, init):
    jobs[job_id] = init


@_with_lock
def update_job(job_id, **kwargs):
    if job_id in jobs:
        jobs[job_id].update(kwargs)


@_with_lock
def append_log(job_id, txt):
    if job_id in jobs:
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {txt}"
        jobs[job_id]["log"].append(entry)
        if len(jobs[job_id]["log"]) > 200:
            jobs[job_id]["log"] = jobs[job_id]["log"][-200:]


def get_job(job_id):
    with jobs_lock:
        return jobs.get(job_id)


# ─── Replace Job ───────────────────────────────
def start_replace_job(ep_key):
    job_id = str(uuid.uuid4())
    create_job_record(job_id, {
        "status": "queued",
        "progress": 0,
        "message": "Queued",
        "log": [],
        "episode_key": ep_key,
        "type": "replace"
    })
    threading.Thread(target=_replace_worker, args=(job_id, ep_key), daemon=True).start()
    return job_id


def _replace_worker(job_id, ep_key):
    try:
        update_job(job_id, status="running", progress=5, message="Triggering replacement...")
        append_log(job_id, f"Starting replace job for episode {ep_key}")

        # Trigger internal replace endpoint
        url = INTERNAL_API_BASE.rstrip("/") + "/api/episodes/replace"
        append_log(job_id, f"POST {url}")
        r = requests.post(url, json={"key": ep_key}, timeout=30)
        if r.status_code >= 400:
            append_log(job_id, f"Replace endpoint error: {r.status_code} {r.text}")
            update_job(job_id, status="error", message="Replace endpoint failed")
            return
        update_job(job_id, progress=20, message="Replace triggered")

        # Fetch episode metadata
        url = INTERNAL_API_BASE.rstrip("/") + "/api/episodes/get_by_key"
        r = requests.get(url, params={"key": ep_key}, timeout=10)
        r.raise_for_status()
        meta = r.json()
        series_id = meta.get("series_id")
        episode_id = meta.get("episode_id")
        code = meta.get("code")

        if not series_id or not episode_id:
            append_log(job_id, "Missing series_id or episode_id")
            update_job(job_id, status="error", message="Missing episode metadata")
            return

        # Poll Sonarr for import event
        if SONARR_URL and SONARR_API:
            append_log(job_id, "Polling Sonarr history for import...")
            found = False
            timeout = int(os.environ.get("SONARR_IMPORT_TIMEOUT", "300"))
            poll_interval = 4
            elapsed = 0
            while elapsed < timeout:
                try:
                    hist_url = SONARR_URL.rstrip("/") + "/api/v3/history"
                    res = requests.get(hist_url, params={"apikey": SONARR_API, "pageSize": 50}, timeout=10)
                    res.raise_for_status()
                    entries = res.json()
                    for e in entries:
                        data = e.get("data") or {}
                        eps = data.get("episodes") or ([data.get("episode")] if data.get("episode") else [])
                        for ep in eps:
                            if ep and (ep.get("id") == episode_id or ep.get("episodeId") == episode_id):
                                append_log(job_id, f"Found Sonarr import event id={e.get('id')}")
                                found = True
                                break
                        if found: break
                except Exception as e:
                    append_log(job_id, f"Sonarr poll error: {e}")
                if found: break
                time.sleep(poll_interval)
                elapsed += poll_interval
                update_job(job_id, progress=20 + int(elapsed / max(1, timeout) * 50),
                           message=f"Waiting for Sonarr import {elapsed}s")

            if not found:
                append_log(job_id, f"Sonarr import timeout after {elapsed}s")
                update_job(job_id, message="Timeout, running analyzer anyway", progress=80)

        # Run analyzer
        update_job(job_id, progress=85, message="Running analyzer...")
        import re
        cmd = ["python3", "/app/analyzer.py", "--series-id", str(series_id)]
        if code:
            m = re.match(r"S(\d{2})E\d{2}", code or "")
            if m:
                cmd += ["--season", str(int(m.group(1)))]
        append_log(job_id, f"Analyzer cmd: {' '.join(cmd)}")
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.environ.get("ANALYZER_TIMEOUT", "600")))
        append_log(job_id, f"Analyzer stdout: {p.stdout[:2000]}")
        if p.returncode != 0:
            append_log(job_id, f"Analyzer returned {p.returncode} stderr: {p.stderr[:2000]}")
            update_job(job_id, status="error", progress=95, message="Analyzer failed")
            return

        append_log(job_id, "Analyzer finished successfully")
        update_job(job_id, progress=100, status="done", message="Complete")

    except Exception as e:
        append_log(job_id, f"Unhandled job error: {e}")
        update_job(job_id, status="error", message="Unhandled error")


# ─── Library Scan Job ───────────────────────────────
def start_library_scan_job(scan_function, description="Library scan"):
    """
    scan_function: callable to run for scanning the library
    Returns job_id immediately.
    """
    job_id = str(uuid.uuid4())
    create_job_record(job_id, {
        "status": "queued",
        "progress": 0,
        "message": description,
        "log": [],
        "episode_key": None,
        "type": "library_scan"
    })
    threading.Thread(target=_library_scan_worker, args=(job_id, scan_function), daemon=True).start()
    return job_id


def _library_scan_worker(job_id, scan_function):
    try:
        update_job(job_id, status="running", progress=5)
        append_log(job_id, "Library scan started")
        scan_function(job_id, append_log, update_job)
        append_log(job_id, "Library scan finished")
        update_job(job_id, progress=100, status="done", message="Complete")
    except Exception as e:
        append_log(job_id, f"Library scan error: {e}")
        update_job(job_id, status="error", message="Scan failed")
