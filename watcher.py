import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess

WATCH_PATH = os.getenv("WATCH_PATH", "/watched")

class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        filename = event.src_path
        print(f"New file detected: {filename}")
        if filename.lower().endswith((".mkv", ".mp4", ".avi", ".nzb")):
            subprocess.run(["python", "checker.py", filename])

if __name__ == "__main__":
    observer = Observer()
    observer.schedule(NewFileHandler(), WATCH_PATH, recursive=True)
    print(f"Watching for new files in {WATCH_PATH}...")
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
