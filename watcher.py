#!/usr/bin/env python3
import os
import time
import subprocess
import logging
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver as Observer  # Use polling for NFS

WATCH_DIR = os.getenv("WATCH_DIR", "/watched")
COOLDOWN_SECONDS = int(os.getenv("CHECK_COOLDOWN", "60"))
CHECK_COMMAND = ["python", "checker.py"]

# --- Logging setup ---
LOG_DIR = os.getenv("LOG_PATH", "/logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "watcher.log")),
        logging.StreamHandler()
    ]
)

last_run = 0

class ChangeHandler(FileSystemEventHandler):
    def on_created(self, event):
        logging.info(f"📁 Created: {event.src_path}")
        self.trigger_check()

    def on_modified(self, event):
        logging.info(f"✏️ Modified: {event.src_path}")
        self.trigger_check()

    def on_moved(self, event):
        logging.info(f"🔀 Moved: {event.src_path} → {event.dest_path}")
        self.trigger_check()

    def on_deleted(self, event):
        logging.info(f"❌ Deleted: {event.src_path}")
        self.trigger_check()

    def trigger_check(self):
        global last_run
        now = time.time()
        if now - last_run > COOLDOWN_SECONDS:
            logging.info("🔁 Change detected — running checker...")
            try:
                subprocess.run(CHECK_COMMAND, check=True)
                last_run = now
            except subprocess.CalledProcessError as e:
                logging.error(f"Checker failed: {e}")
        else:
            logging.info("⏳ Cooldown active, skipping check.")

def main():
    # Run a check once at startup
    logging.info("🚀 Running checker on startup...")
    try:
        subprocess.run(CHECK_COMMAND, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Initial checker run failed: {e}")

    logging.info(f"👀 Watching directory (via polling): {WATCH_DIR}")
    event_handler = ChangeHandler()
    observer = Observer(timeout=1)  # Poll every 1 second
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
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
