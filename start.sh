#!/usr/bin/env sh
set -e

# kick off your existing scanner in the background
python watcher.py &

# then run the Flask UI in the foreground
python webapp.py
