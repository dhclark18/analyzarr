# watcher.py
import os
import time
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler
from jobs import start_library_scan_job, append_log, update_job

# ─── Read watch paths from environment variables ───────────────────────────
WATCH_PATHS = os.environ.get("WATCH_PATHS", "/media/tv").split(":")  # use ":" as delimiter
WATCH_PATHS = [p for p in WATCH_PATHS if os.path.exists(p)]

if not WATCH_PATHS:
    print("No valid watch paths exist. Exiting.")
    exit(1)

def run_library_scan(job_id, append_log, update_job):
    try:
        append_log(job_id, "Starting library scan...")
        for i, path in enumerate(WATCH_PATHS):
            append_log(job_id, f"Scanning {path}...")
            time.sleep(2)  # simulate scan delay
            update_job(job_id, progress=5 + int((i + 1) / len(WATCH_PATHS) * 80))
        append_log(job_id, "Library scan finished successfully")
    except Exception as e:
        append_log(job_id, f"Error during scan: {e}")
        update_job(job_id, status="error", message="Scan failed")


class WatcherHandler(FileSystemEventHandler):
    def on_created(self, event):
        self.trigger_scan(event)
    def on_deleted(self, event):
        self.trigger_scan(event)
    def on_modified(self, event):
        self.trigger_scan(event)

    def trigger_scan(self, event):
        append_log("system", f"Detected change: {event.src_path}")
        job_id = start_library_scan_job(run_library_scan, description=f"Scan triggered by change: {event.src_path}")
        append_log(job_id, f"Library scan job {job_id} enqueued")


if __name__ == "__main__":
    observer = Observer()
    handler = WatcherHandler()
    for path in WATCH_PATHS:
        observer.schedule(handler, path, recursive=True)
        append_log("system", f"Watching {path}")

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
