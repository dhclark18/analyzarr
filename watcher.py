import time
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from subprocess import run

WATCH_DIR = "/watched"
CHECKER_SCRIPT = "/app/checker.py"
COOLDOWN_SECONDS = 10

last_event_time = 0
cooldown_timer = None

def run_checker():
    print("📁 Scanning directory:", WATCH_DIR)
    run(["python3", CHECKER_SCRIPT])

class ChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        global last_event_time, cooldown_timer
        now = time.time()
        last_event_time = now

        if cooldown_timer and cooldown_timer.is_alive():
            return

        def cooldown_worker():
            while time.time() - last_event_time < COOLDOWN_SECONDS:
                time.sleep(1)
            run_checker()

        cooldown_timer = threading.Thread(target=cooldown_worker)
        cooldown_timer.start()

if __name__ == "__main__":
    print("🚀 Watcher starting up...")
    run_checker()

    event_handler = ChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, path=WATCH_DIR, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
