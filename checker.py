import os
import re
import requests
import logging
import unicodedata
import psycopg2
from pathlib import Path
from datetime import datetime

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
SONARR_HEADERS = {"X-Api-Key": SONARR_API_KEY}
TVDB_FILTER = os.getenv("TVDB_ID")
FORCE_RUN = os.getenv("FR_RUN", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL")
SPECIAL_TAG_NAME = os.getenv("SPECIAL_TAG_NAME", "problematic-title")

# --- DB ---
def init_db():
    db_execute("""
    CREATE TABLE IF NOT EXISTS mismatch_tracking (
      key TEXT PRIMARY KEY,
      count INTEGER NOT NULL DEFAULT 0,
      last_mismatch TIMESTAMP
    );
    """)
    
def has_exceeded_threshold(series_title: str, season: int, episode_num: int) -> bool:
    """
    Return True if the stored mismatch count for this episode key exceeds MISMATCH_THRESHOLD.
    Does not modify the database.
    """
    key = f"series::{normalize_title(series_title)}::S{season:02}E{episode_num:02}"
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count FROM mismatch_tracking WHERE key = %s",
                    (key,)
                )
                row = cur.fetchone()
        return bool(row and row[0] > MISMATCH_THRESHOLD)
    except Exception as e:
        logging.error(f"DB error checking threshold for {key}: {e}")
        return False
# --- Helpers ---
def normalize_title(text):
    if not text:
        return ""
    text = text.replace("&", "and")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isalnum()).lower()

# --- Sonarr API ---
def get_series_list():
    resp = requests.get(f"{SONARR_URL}/api/v3/series", headers=SONARR_HEADERS)
    resp.raise_for_status()
    return resp.json()

def get_episodes(series_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/episode?seriesId={series_id}", headers=SONARR_HEADERS)
    resp.raise_for_status()
    return resp.json()

def get_episode_file(file_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/episodefile/{file_id}", headers=SONARR_HEADERS)
    resp.raise_for_status()
    return resp.json()

def delete_file(file_id):
    try:
        resp = requests.delete(f"{SONARR_URL}/api/v3/episodefile/{file_id}", headers=SONARR_HEADERS)
        resp.raise_for_status()
        logging.info(f"🗑️ Deleted episode file ID {file_id}")
    except Exception as e:
        logging.error(f"Failed to delete file ID {file_id}: {e}")

def refresh_series(series_id):
    try:
        requests.post(f"{SONARR_URL}/api/v3/command", headers=SONARR_HEADERS, json={"name": "RefreshSeries", "seriesId": series_id})
        requests.post(f"{SONARR_URL}/api/v3/command", headers=SONARR_HEADERS, json={"name": "RescanSeries", "seriesId": series_id})
        logging.info(f"🔄 Refreshed/rescanned series ID {series_id}")
    except Exception as e:
        logging.error(f"Failed to refresh/rescan series {series_id}: {e}")

def search_episode(episode_id):
    try:
        requests.post(f"{SONARR_URL}/api/v3/command", headers=SONARR_HEADERS, json={"name": "EpisodeSearch", "episodeIds": [episode_id]})
        logging.info(f"🔍 Initiated search for episode ID {episode_id}")
    except Exception as e:
        logging.error(f"Failed to initiate search for episode {episode_id}: {e}")

# --- Main Logic ---
def check_episode(series, episode):
    # 1) Skip if there’s no file
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    # 2) Fetch the file metadata
    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(
            f"❌ Could not fetch episode file for "
            f"{series['title']} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}: {e}"
        )
        return

    scene_name = epfile.get("sceneName")
    if not scene_name:
        logging.warning(f"⚠️ Missing scene name for episode file {epfile.get('id')}")
        return

    # 3) Normalize titles
    expected = normalize_title(episode["title"])
    actual   = normalize_title(scene_name)
    season   = episode["seasonNumber"]
    epnum    = episode["episodeNumber"]
    code     = f"S{season:02}E{epnum:02}"

    logging.info(f"\n📺 {series['title']} {code}")
    logging.info(f"🎯 Expected title : {episode['title']}")
    logging.info(f"🎞️  Scene name     : {scene_name}")

    # 4) If it matches, nothing else to do
    if expected in actual:
        logging.info(f"✅ Scene title matches for {series['title']} {code}")
        return

    # 5) On mismatch, first check DB threshold
    if has_exceeded_threshold(series["title"], season, epnum):
        logging.info(
            f"⏩ Ignoring mismatch for {series['title']} {code} "
            f"(exceeded {MISMATCH_THRESHOLD} stored mismatches)"
        )
        return

    # 6) Finally, treat it as a “real” mismatch
    logging.error(f"❌ Scene title does NOT match expected title for {series['title']} {code}")

    if not FORCE_RUN:
        logging.info("Skipping automatic deletion/search (not in force run mode).")
        return

    # 7) Your force‐run actions
    delete_file(epfile["id"])
    refresh_series(series["id"])
    search_episode(episode["id"])

def scan_library():
    if not SONARR_API_KEY:
        logging.error("❌ SONARR_API_KEY is not set.")
        return

    try:
        series_list = get_series_list()
        for series in series_list:
            if TVDB_FILTER and str(series.get("tvdbId")) != TVDB_FILTER:
                continue
            logging.info(f"\n=== Scanning: {series['title']} ===")
            episodes = get_episodes(series["id"])
            for episode in episodes:
                check_episode(series, episode)
    except Exception as e:
        logging.error(f"Library scan failed: {e}")

if __name__ == "__main__":
    init_db()
    scan_library()
