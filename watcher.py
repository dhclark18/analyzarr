import os
import time
import subprocess
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = os.getenv("WATCH_DIR", "/watched")
COOLDOWN_SECONDS = int(os.getenv("CHECK_COOLDOWN", "60"))
CHECK_COMMAND = ["python", "checker.py"]

# --- Logging ---
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
        self.trigger_check()

    def on_modified(self, event):
        self.trigger_check()

    def trigger_check(self):
        global last_run
        now = time.time()
        if now - last_run > COOLDOWN_SECONDS:
            logging.info("🔁 Change detected — running checker...")
            try:
                subprocess.run(CHECK_COMMAND, check=True)
                last_run = time.time()
            except subprocess.CalledProcessError as e:
                logging.error(f"Checker failed: {e}")
        else:
            logging.info("⏳ Cooldown active, skipping check.")

def main():
    logging.info("🚀 Running checker on startup...")
    subprocess.run(CHECK_COMMAND)

    logging.info(f"👀 Watching directory: {WATCH_DIR}")
    event_handler = ChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
