import os
import re
import json
import logging
import requests
from pathlib import Path
import unicodedata

# --- Config ---
SONARR_URL = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
TVDB_FILTER_ID = os.getenv("TVDB_FILTER_ID")
MAX_MISMATCHES = int(os.getenv("MAX_MISMATCHES", "10"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
LOG_DIR = os.getenv("LOG_PATH", "/logs")
MISMATCH_DB_PATH = os.path.join(LOG_DIR, "mismatch_db.json")

os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "scene_check.log")
MISMATCH_LOG_FILE = os.path.join(LOG_DIR, "mismatch.log")

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

mismatch_logger = logging.getLogger("mismatch_logger")
mismatch_handler = logging.FileHandler(MISMATCH_LOG_FILE, encoding="utf-8")
mismatch_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
mismatch_logger.addHandler(mismatch_handler)
mismatch_logger.setLevel(logging.INFO)

HEADERS = {"X-Api-Key": SONARR_API_KEY}

# --- Helper Functions ---
def normalize_title(title):
    if not title:
        return ""
    title = title.replace("&", "and")
    title = unicodedata.normalize("NFKD", title)
    return "".join(c for c in title if c.isalnum()).lower()

def extract_scene_title(scene_name):
    match = re.search(
        r"S\d{2}E\d{2}\.([^.]+?(?:\.[^.]+)*?)\.(?:\d{3,4}p|WEB|HDTV|NF|AMZN|DSNP|HMAX|HULU|DD|DDP|x264|h264|h265|HEVC|AAC|EAC3|BluRay|-)",
        scene_name or "",
        re.IGNORECASE
    )
    if match:
        return match.group(1).replace(".", " ").strip()
    return ""

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

def load_mismatch_db():
    if os.path.exists(MISMATCH_DB_PATH):
        with open(MISMATCH_DB_PATH, "r") as f:
            return json.load(f)
    return {}

def save_mismatch_db(db):
    with open(MISMATCH_DB_PATH, "w") as f:
        json.dump(db, f)

def check_episode(series, episode, mismatch_db):
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(f"❌ Could not fetch episode file: {e}")
        return

    scene_name = epfile.get("sceneName")
    expected_title = episode.get("title")
    scene_title = extract_scene_title(scene_name)

    ne = normalize_title(expected_title)
    ns = normalize_title(scene_title)

    episode_code = f"S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}"
    logging.info(f"\n📺 {series['title']} {episode_code}")
    logging.info(f"🎯 Expected title : {expected_title}")
    logging.info(f"🎞️  Scene title    : {scene_title or '[unknown]'}")

    episode_key = f"{series['id']}_{episode['id']}"
    mismatch_count = mismatch_db.get(episode_key, 0)

    if not scene_title:
        logging.warning("⚠️ Scene title missing; skipping comparison.")
        return

    if ne not in ns:
        logging.error("❌ Scene title does NOT match expected title.")
        mismatch_logger.info(f"{series['title']} {episode_code} - MISMATCH ({mismatch_count+1})")

        mismatch_count += 1
        mismatch_db[episode_key] = mismatch_count
        save_mismatch_db(mismatch_db)

        if mismatch_count >= MAX_MISMATCHES:
            logging.warning(f"🚫 Max mismatch count reached ({mismatch_count}), skipping deletion and rescan.")
            return

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
    else:
        logging.info("✅ Scene title matches expected title.")

# --- Main ---
def scan_library():
    if not SONARR_API_KEY:
        logging.error("❌ SONARR_API_KEY is not set.")
        return

    mismatch_db = load_mismatch_db()

    try:
        series_list = get_series_list()
        for series in series_list:
            if TVDB_FILTER_ID and str(series.get("tvdbId")) != str(TVDB_FILTER_ID):
                continue

            logging.info(f"\n=== Scanning: {series['title']} ===")
            episodes = get_episodes(series["id"])
            for episode in episodes:
                check_episode(series, episode, mismatch_db)

    except Exception as e:
        logging.error(f"Failed to scan library: {e}")

if __name__ == "__main__":
    scan_library()
