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

logger.basicConfig(
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
def should_ignore_episode_file(episode_file_id):
    logger.debug(f"🔍 IGNORE-CHECK start for episode_file_id={episode_file_id}")
    if not DATABASE_URL:
        logger.warning("🔍 IGNORE-CHECK: DATABASE_URL not set")
        return False

    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        logger.debug("🔍 IGNORE-CHECK: DB connected")
    except Exception as e:
        logger.error(f"🔍 IGNORE-CHECK: DB connect failed: {e}")
        return False

    try:
        cur = conn.cursor()
        # Dump all tags for this file
        cur.execute("""
            SELECT et.episode_file_id, et.tag_id, t.name
              FROM episode_tags et
              JOIN tags t ON et.tag_id = t.id
             WHERE et.episode_file_id = %s
        """, (episode_file_id,))
        all_rows = cur.fetchall()
        logger.debug(f"🔍 IGNORE-CHECK: All tags on this file: {all_rows}")

        # Now specifically look for the special tag
        cur.execute("""
            SELECT 1
              FROM episode_tags et
              JOIN tags t ON et.tag_id = t.id
             WHERE et.episode_file_id = %s
               AND t.name = %s
        """, (episode_file_id, SPECIAL_TAG_NAME))
        found = cur.fetchone() is not None
        logger.debug(f"🔍 IGNORE-CHECK: Found '{SPECIAL_TAG_NAME}'? {found}")

        cur.close()
        conn.close()
        return found

    except Exception as e:
        logger.error(f"🔍 IGNORE-CHECK: query error: {e}")
        conn.close()
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
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(f"❌ Could not fetch episode file for {series['title']} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}: {e}")
        return

    scene_name = epfile.get("sceneName")
    if not scene_name:
        logging.warning(f"⚠️ Missing scene name for episode file {epfile.get('id')}")
        return

    expected = normalize_title(episode["title"])
    scene = normalize_title(scene_name)

    episode_code = f"S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}"
    logging.info(f"\n📺 {series['title']} {episode_code}")
    logging.info(f"🎯 Expected title : {episode['title']}")
    logging.info(f"🎞️  Scene name     : {scene_name}")

    if expected not in scene:
        if should_ignore_episode_file(epfile["id"]):
            logging.info("⏩ Ignored due to special tag.")
            return

        logging.error("❌ Scene title does NOT match expected title.")

        if not FORCE_RUN:
            logging.info("Skipping automatic deletion/search (not in force run mode).")
            return

        delete_file(epfile["id"])
        refresh_series(series["id"])
        search_episode(episode["id"])
    else:
        logging.info("✅ Scene title matches expected title.")

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
    scan_library()
