import os, time, subprocess, logging
from jobs import start_library_scan_job
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver as Observer

WATCH_DIR = os.getenv("WATCH_DIR", "/watched")
COOLDOWN_SECONDS = int(os.getenv("CHECK_COOLDOWN", "60"))
CHECK_COMMAND = ["python3", "analyzer.py"]

LOG_DIR = os.getenv("LOG_PATH", "/logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(os.path.join(LOG_DIR, "watcher.log")), logging.StreamHandler()]
)

last_run = 0

class ChangeHandler(FileSystemEventHandler):
    def trigger_check(self, ignore_cooldown=False):
        global last_run
        now = time.time()
        if ignore_cooldown or (now - last_run) > COOLDOWN_SECONDS:
            last_run = now
            job_id = start_library_scan_job()
            logging.info(f"🔁 Change detected — running analyzer (job {job_id})...")
            update_job(job_id, status="running")
            try:
                subprocess.run(CHECK_COMMAND, check=True)
                update_job(job_id, status="done", progress=100, message="Library scan complete")
            except subprocess.CalledProcessError as e:
                logging.error(f"Analyzer failed: {e}")
                update_job(job_id, status="error", message=str(e))
        else:
            logging.info("⏳ Cooldown active, skipping check.")

    def on_created(self, event):
        if event.is_directory: return
        logging.info(f"📁 Created: {event.src_path}")
        self.trigger_check(ignore_cooldown=True)

    def on_modified(self, event):
        if event.is_directory: return
        logging.info(f"✏️ Modified: {event.src_path}")
        self.trigger_check()

    def on_moved(self, event):
        if event.is_directory: return
        logging.info(f"🔀 Moved: {event.src_path} → {event.dest_path}")
        self.trigger_check(ignore_cooldown=True)

    def on_deleted(self, event):
        if event.is_directory: return
        logging.info(f"❌ Deleted: {event.src_path}")
        self.trigger_check()

def main():
    logging.info("🚀 Running analyzer on startup...")
    handler = ChangeHandler()
    observer = Observer(timeout=1)
    observer.schedule(handler, WATCH_DIR, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        logging.info("🛑 Stopping watcher…")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
