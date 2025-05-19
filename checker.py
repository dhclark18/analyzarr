import os
import re
import json
import requests
from pathlib import Path
import unicodedata
import logging

# --- Logging Setup ---
LOG_DIR = os.getenv("LOG_PATH", "/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "scene_check.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# --- Config ---
SONARR_URL = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
HEADERS = {"X-Api-Key": SONARR_API_KEY}

MAX_MISMATCH_THRESHOLD = int(os.getenv("MAX_MISMATCH_THRESHOLD", 10))
MISMATCH_DB_PATH = os.getenv("MISMATCH_DB_PATH", "/data/mismatch_counts.json")
LIMIT_SERIES_TVDBID = os.getenv("LIMIT_SERIES_TVDBID")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


if os.path.exists(MISMATCH_DB_PATH):
    with open(MISMATCH_DB_PATH, "r") as f:
        mismatch_db = json.load(f)
else:
    mismatch_db = {}

def save_mismatch_db():
    with open(MISMATCH_DB_PATH, "w") as f:
        json.dump(mismatch_db, f)

# --- Helpers ---
def normalize_title(title):
    if not title:
        return ""
    title = title.replace("&", "and")
    title = unicodedata.normalize("NFKD", title)
    return "".join(c for c in title if c.isalnum()).lower()

# --- API Access ---
def get_series_list():
    resp = requests.get(f"{SONARR_URL}/api/v3/series", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

def get_episodes(series_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/episode?seriesId={series_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

def get_episode_file(file_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/episodefile/{file_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

# --- Main Check ---
def check_episode(series, episode):
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(f"Failed to get file for {series['title']} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}: {e}")
        return

    expected_title = episode.get("title")
    scene_name = epfile.get("sceneName")
    episode_code = f"S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}"
    episode_key = f"{series['tvdbId']}_{episode_code}"
    mismatch_count = mismatch_db.get(episode_key, 0)

    logging.info(f"\n📺 {series['title']} {episode_code}")
    logging.info(f"🎯 Expected title : {expected_title}")
    logging.info(f"🎞️  Scene title    : {scene_name or '[unknown]'}")

    if mismatch_count >= MAX_MISMATCH_THRESHOLD:
        logging.warning(f"⚠️  Mismatch threshold reached ({mismatch_count}) — skipping.")
        return

    ne = normalize_title(expected_title)
    ns = normalize_title(scene_name or "")

    if ne not in ns:
    logging.error("❌ Scene title does NOT match expected title.")
    mismatch_count += 1
    mismatch_db[episode_key] = mismatch_count
    save_mismatch_db()

    if DRY_RUN:
        logging.warning("🧪 DRY RUN: Would delete mismatched file.")
    else:
        try:
            os.remove(epfile.get("path"))
            logging.warning("🗑️  Deleted mismatched file.")
        except Exception as e:
            logging.error(f"Failed to delete file: {e}")

    if DRY_RUN:
        logging.info("🧪 DRY RUN: Would trigger Sonarr rescan/refresh/search.")
    else:
        try:
            requests.post(f"{SONARR_URL}/api/v3/command", headers=HEADERS, json={"name": "RescanSeries", "seriesId": series["id"]})
            requests.post(f"{SONARR_URL}/api/v3/command", headers=HEADERS, json={"name": "RefreshSeries", "seriesId": series["id"]})
            requests.post(f"{SONARR_URL}/api/v3/command", headers=HEADERS, json={"name": "EpisodeSearch", "episodeIds": [episode["id"]]})
            logging.info("🔁 Triggered rescan, refresh, and episode search.")
        except Exception as e:
            logging.error(f"Failed to trigger Sonarr commands: {e}")

# --- Entry Point ---
def scan_library():
    if not SONARR_API_KEY:
        logging.error("❌ SONARR_API_KEY environment variable is not set.")
        return

    try:
        all_series = get_series_list()
        for series in all_series:
            if LIMIT_SERIES_TVDBID and str(series["tvdbId"]) != LIMIT_SERIES_TVDBID:
                continue

            logging.info(f"\n=== Scanning: {series['title']} ===")
            episodes = get_episodes(series["id"])
            for episode in episodes:
                check_episode(series, episode)
    except Exception as e:
        logging.error(f"Library scan failed: {e}")

if __name__ == "__main__":
    scan_library()

