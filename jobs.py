# jobs.py
import uuid
import time
import threading
import requests
import os
import subprocess

jobs = {}
jobs_lock = threading.Lock()

SONARR_URL = os.environ.get("SONARR_URL")
SONARR_API = os.environ.get("SONARR_API_KEY")
# If your Flask app is running in the same container on port 80, use http://localhost
# If you use another internal port, set INTERNAL_API_BASE (e.g. http://127.0.0.1:5000)
INTERNAL_API_BASE = os.environ.get("INTERNAL_API_BASE", "http://127.0.0.1:80")

def _with_lock(fn):
    def wrapped(*args, **kwargs):
        with jobs_lock:
            return fn(*args, **kwargs)
    return wrapped

@_with_lock
def create_job_record(job_id, init):
    jobs[job_id] = init

def start_replace_job(ep_key):
    """
    Start a background job that:
      1) Calls your existing synchronous replace endpoint via internal HTTP POST
      2) Polls Sonarr history for an import event for the episode_id
      3) Calls analyzer.py with --series-id and optional --season when import found
    Returns job_id immediately.
    """
    job_id = str(uuid.uuid4())
    create_job_record(job_id, {
        "status": "queued",
        "progress": 0,
        "message": "Queued",
        "log": [],
        "episode_key": ep_key
    })
    t = threading.Thread(target=_job_worker, args=(job_id, ep_key), daemon=True)
    t.start()
    return job_id

def get_job(job_id):
    with jobs_lock:
        return jobs.get(job_id)

def _append_log(job_id, txt):
    with jobs_lock:
        entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {txt}"
        jobs[job_id]["log"].append(entry)
        if len(jobs[job_id]["log"]) > 200:
            jobs[job_id]["log"] = jobs[job_id]["log"][-200:]

def _set(job_id, **kwargs):
    with jobs_lock:
        jobs[job_id].update(kwargs)

def _job_worker(job_id, ep_key):
    try:
        _set(job_id, status="running", progress=5, message="Triggering replacement...")
        _append_log(job_id, f"Job started for episode key={ep_key}")

        # Step 1: Trigger your existing synchronous replace endpoint via internal POST
        try:
            url = INTERNAL_API_BASE.rstrip("/") + "/api/episodes/replace"
            _append_log(job_id, f"POST {url} (internal)")
            r = requests.post(url, json={"key": ep_key}, timeout=30)
            try:
                r.raise_for_status()
            except Exception as e:
                _append_log(job_id, f"Replace endpoint returned error: {r.status_code} {r.text}")
                _set(job_id, status="error", message="Replace endpoint failed")
                return
            _append_log(job_id, f"Replace endpoint returned: {r.status_code}")
            _set(job_id, progress=20, message="Replace triggered. Waiting for Sonarr import...")
        except Exception as e:
            _append_log(job_id, f"Failed to call internal replace endpoint: {e}")
            _set(job_id, status="error", message="Internal replace failed")
            return

        # Step 2: Look up the episode's series_id and episode_id from DB (call your API to avoid db import)
        try:
            # call an internal API that returns series_id and episode_id for this key
            url = INTERNAL_API_BASE.rstrip("/") + "/api/episodes/get_by_key"
            _append_log(job_id, f"Fetching episode metadata: {url}")
            r = requests.get(url, params={"key": ep_key}, timeout=10)
            r.raise_for_status()
            meta = r.json()
            series_id = meta.get("series_id")
            episode_id = meta.get("episode_id")
            code = meta.get("code")
            _append_log(job_id, f"Episode meta: series_id={series_id} episode_id={episode_id} code={code}")
            if series_id is None or episode_id is None:
                _append_log(job_id, "Missing series_id or episode_id in metadata response.")
                _set(job_id, status="error", message="Missing series/episode IDs")
                return
        except Exception as e:
            _append_log(job_id, f"Failed to fetch episode metadata: {e}")
            _set(job_id, status="error", message="Failed to fetch episode metadata")
            return

        # Step 3: Poll Sonarr history until import is detected for this episode_id
        if not SONARR_URL or not SONARR_API:
            _append_log(job_id, "SONARR_URL or SONARR_API_KEY not set; will not poll Sonarr. Running analyzer directly.")
            found = True
        else:
            _append_log(job_id, f"Polling Sonarr history for episode_id={episode_id}")
            found = False
            timeout = int(os.environ.get("SONARR_IMPORT_TIMEOUT", "300"))  # seconds
            poll_interval = 4
            elapsed = 0
            while elapsed < timeout:
                try:
                    hist_url = SONARR_URL.rstrip("/") + "/api/v3/history"
                    res = requests.get(hist_url, params={"apikey": SONARR_API, "pageSize": 50}, timeout=10)
                    res.raise_for_status()
                    entries = res.json()
                    # Each entry typically has "eventType" and either "episode" or "episodes" in data
                    for e in entries:
                        # Event types include: "grab", "download", "import", etc. We'll check for an import or rename.
                        # Some installs include 'episode' key (single) or 'episodes' list. We'll search.
                        data = e.get("data") or {}
                        # check episodes list
                        eps = []
                        if isinstance(data.get("episodes"), list):
                            eps = data.get("episodes")
                        elif isinstance(data.get("episode"), dict):
                            eps = [data.get("episode")]
                        # episodes entries might have "id"
                        for ep in eps:
                            # Sonarr history episode objects have "id" == episodeId
                            if ep and (ep.get("id") == episode_id or ep.get("episodeId") == episode_id):
                                _append_log(job_id, f"Found Sonarr history event id={e.get('id')} eventType={e.get('eventType')}")
                                # accept eventType that indicates import; we'll accept any event showing the episode present
                                found = True
                                break
                        if found:
                            break
                except Exception as e:
                    _append_log(job_id, f"Sonarr history poll error: {e}")
                if found:
                    break
                time.sleep(poll_interval)
                elapsed += poll_interval
                _set(job_id, progress=20 + int(elapsed / max(1, int(timeout)) * 50), message=f"Waiting for Sonarr import... {elapsed}s")
            if not found:
                _append_log(job_id, f"Timed out waiting for Sonarr import after {elapsed}s")
                # We'll still attempt analyzer, but mark in log.
                _set(job_id, message="Timed out waiting for Sonarr import; running analyzer anyway", progress=80)

        # Step 4: Run analyzer (the same way your replace_endpoint did)
        _set(job_id, message="Running analyzer...", progress=85)
        _append_log(job_id, "Launching analyzer.py")
        try:
            # Call analyzer as you currently do; keep cwd safe
            # Adjust "python3" if your container needs a different interpreter
            # If analyzer accepts --series-id and optionally --season, follow same logic
            cmd = ["python3", "/app/analyzer.py", "--series-id", str(series_id)]
            # optional season parsing from code S##E##
            if code:
                import re
                m = re.match(r"S(\d{2})E\d{2}", code or "")
                if m:
                    season_num = int(m.group(1))
                    cmd += ["--season", str(season_num)]
            _append_log(job_id, f"Analyzer command: {' '.join(cmd)}")
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.environ.get("ANALYZER_TIMEOUT", "600")))
            _append_log(job_id, f"Analyzer stdout: {p.stdout[:2000]}")
            if p.returncode != 0:
                _append_log(job_id, f"Analyzer returned rc={p.returncode} stderr: {p.stderr[:2000]}")
                _set(job_id, status="error", message="Analyzer failed", progress=95)
                return
            _append_log(job_id, "Analyzer finished successfully.")
            _set(job_id, progress=100, message="Complete")
            _set(job_id, status="done")
        except Exception as e:
            _append_log(job_id, f"Failed to run analyzer: {e}")
            _set(job_id, status="error", message="Analyzer failed")
    except Exception as e:
        _append_log(job_id, f"Unhandled job error: {e}")
        _set(job_id, status="error", message="Unhandled error")

def start_library_scan_job():
    """
    Start a background job that runs the analyzer on the whole library.
    Returns job_id immediately.
    """
    job_id = str(uuid.uuid4())
    create_job_record(job_id, {
        "status": "queued",
        "progress": 0,
        "message": "Queued library scan",
        "log": [],
        "type": "library_scan"
    })

    def _worker():
        try:
            _set(job_id, status="running", progress=5, message="Running library scan...")
            _append_log(job_id, "Launching analyzer for full library")
            cmd = ["python3", "/app/analyzer.py"]  # full library scan
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.environ.get("ANALYZER_TIMEOUT", "3600")))
            _append_log(job_id, f"Analyzer stdout: {p.stdout[:2000]}")
            if p.returncode != 0:
                _append_log(job_id, f"Analyzer returned rc={p.returncode} stderr: {p.stderr[:2000]}")
                _set(job_id, status="error", message="Library scan failed", progress=95)
                return
            _append_log(job_id, "Library scan finished successfully.")
            _set(job_id, progress=100, message="Library scan complete")
            _set(job_id, status="done")
        except Exception as e:
            _append_log(job_id, f"Library scan failed: {e}")
            _set(job_id, status="error", message="Library scan failed")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return job_id
