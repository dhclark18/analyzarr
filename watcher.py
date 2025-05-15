import os
import time
import subprocess
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_PATH = os.getenv("WATCH_PATH", "/watched")
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "30"))

changed_files = set()
cooldown_timer = None
lock = threading.Lock()

def run_checker(filepath):
    if filepath.lower().endswith(VIDEO_EXTENSIONS):
        print(f"📺 Running checker on: {filepath}")
        subprocess.run(["python3", "/app/checker.py", filepath])

def initial_scan():
    print("🔍 Running initial scan...")
    for root, _, files in os.walk(WATCH_PATH):
        for f in files:
            full_path = os.path.join(root, f)
            run_checker(full_path)
    print("✅ Initial scan complete.\n")

def process_changed_files():
    global cooldown_timer
    with lock:
        files_to_process = list(changed_files)
        changed_files.clear()
        cooldown_timer = None
    print(f"⏱️ Cooldown ended. Processing {len(files_to_process)} file(s)...")
    for f in files_to_process:
        run_checker(f)

def debounce_file(filepath):
    global cooldown_timer
    with lock:
        changed_files.add(filepath)
        if cooldown_timer:
            cooldown_timer.cancel()
        cooldown_timer = threading.Timer(COOLDOWN_SECONDS, process_changed_files)
        cooldown_timer.start()

class WatchHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(VIDEO_EXTENSIONS):
            debounce_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.lower().endswith(VIDEO_EXTENSIONS):
            debounce_file(event.src_path)

def main():
    if not os.path.exists(WATCH_PATH):
        print(f"❌ Watch path does not exist: {WATCH_PATH}")
        return

    initial_scan()

    print(f"👀 Watching for changes in: {WATCH_PATH}")
    observer = Observer()
    observer.schedule(WatchHandler(), path=WATCH_PATH, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stopping watcher...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
