#!/usr/bin/env python3
import os
import re
import requests
from pathlib import Path

# Base config
raw_url = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_URL = raw_url + "/api/v3" if not raw_url.endswith("/api/v3") else raw_url
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
AUTO_REDOWNLOAD = os.getenv("AUTO_REDOWNLOAD", "false").lower() == "true"

if not SONARR_API_KEY:
    print("❌ SONARR_API_KEY environment variable not set")
    exit(1)

HEADERS = {"X-Api-Key": SONARR_API_KEY}

# Regex patterns
EPISODE_PATTERN = re.compile(r"[Ss](\d{2})[Ee](\d{2})")
TVDB_ID_PATTERN = re.compile(r"\{tvdb-(\d+)\}")
TITLE_IN_FILENAME = re.compile(r"S\d{2}E\d{2} - (.+?) \[")  # Capture title before [

def get_series_by_tvdbid(tvdbid):
    url = f"{SONARR_URL}/series"
    try:
        resp = requests.get(url, headers=HEADERS)
        resp.raise_for_status()
        for series in resp.json():
            if str(series.get("tvdbId")) == str(tvdbid):
                return series
    except Exception as e:
        print(f"❌ Error fetching series: {e}")
    return None

def get_episode_by_number(series_id, season_number, episode_number):
    url = f"{SONARR_URL}/episode?seriesId={series_id}"
    try:
        resp = requests.get(url, headers=HEADERS)
        resp.raise_for_status()
        for ep in resp.json():
            if ep["seasonNumber"] == season_number and ep["episodeNumber"] == episode_number:
                return ep["title"], ep["id"]
    except Exception as e:
        print(f"❌ Error fetching episode list: {e}")
    return None, None

def trigger_redownload(episode_id, season, episode):
    try:
        res = requests.post(f"{SONARR_URL}/command", headers=HEADERS, json={
            "name": "EpisodeSearch",
            "episodeIds": [episode_id]
        })
        res.raise_for_status()
        print(f"🔄 Redownload triggered for S{season:02}E{episode:02}")
    except Exception as e:
        print(f"❌ Failed to trigger redownload: {e}")

def process_file(file_path):
    print(f"📺 Checking: {file_path}")
    filename = Path(file_path).name
    parent_folder = Path(file_path).parent.parent.name

    tvdb_id_match = TVDB_ID_PATTERN.search(parent_folder)
    episode_match = EPISODE_PATTERN.search(filename)
    title_match = TITLE_IN_FILENAME.search(filename)

    if not (tvdb_id_match and episode_match and title_match):
        print(f"⚠️ Skipping due to missing metadata: {file_path}")
        return

    tvdb_id = tvdb_id_match.group(1)
    season_number = int(episode_match.group(1))
    episode_number = int(episode_match.group(2))
    filename_title = title_match.group(1).strip()

    series = get_series_by_tvdbid(tvdb_id)
    if not series:
        print(f"⚠️ No matching series found in Sonarr for tvdb-{tvdb_id}")
        return

    expected_title, episode_id = get_episode_by_number(series["id"], season_number, episode_number)
    if not expected_title:
        print(f"⚠️ Could not find episode title in Sonarr for S{season_number:02}E{episode_number:02}")
        return

    if filename_title.lower() != expected_title.lower():
        print(f"❌ Title mismatch:\n   Sonarr: '{expected_title}'\n   File  : '{filename_title}'")
        if AUTO_REDOWNLOAD and episode_id:
            trigger_redownload(episode_id, season_number, episode_number)
        elif not AUTO_REDOWNLOAD:
            print("ℹ️ AUTO_REDOWNLOAD is off. Not triggering redownload.")
    else:
        print(f"✅ Title match: '{expected_title}'")

def walk_directory(watched_dir="/watched"):
    for root, _, files in os.walk(watched_dir):
        for name in files:
            if name.endswith((".mkv", ".mp4", ".avi")):
                process_file(os.path.join(root, name))

if __name__ == "__main__":
    walk_directory()
