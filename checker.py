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
MISMATCH_THRESHOLD = int(os.getenv("MISMATCH_THRESHOLD", "10"))
# --- DB ---
def db_execute(sql, params=None, fetch=False):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        if fetch:
            return cur.fetchall()
        conn.commit()
        
def init_db():
    db_execute("""
    CREATE TABLE IF NOT EXISTS mismatch_tracking (
      key TEXT PRIMARY KEY,
      count INTEGER NOT NULL DEFAULT 0,
      last_mismatch TIMESTAMP
    );
    """)
    
def db_connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, connect_timeout=5)
    logger.info(f"🔍 LOG: DB connection established")

def db_execute(sql, params=None, fetch=False):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        if fetch:
            return cur.fetchall()
        conn.commit()
        
def get_mismatch_count(key: str) -> int:
    """
    Return the stored mismatch count for this key, or 0 if none.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count FROM mismatch_tracking WHERE key = %s",
                    (key,)
                )
                row = cur.fetchone()
        return row[0] if row else 0
    except Exception as e:
        logging.error(f"DB error fetching mismatch count for {key}: {e}")
        return 0
        
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

    # 3) Normalize titles and build the key
    expected = normalize_title(episode["title"])
    actual   = normalize_title(scene_name)
    season   = episode["seasonNumber"]
    epnum    = episode["episodeNumber"]
    code     = f"S{season:02}E{epnum:02}"

    # key uses normalized series title plus season/episode
    series_norm = normalize_title(series["title"])
    key = f"{series_norm}:{season:02d}:{epnum:02d}"

    logging.info(f"\n📺 {series['title']} {code}")
    logging.info(f"🎯 Expected title : {episode['title']}")
    logging.info(f"🎞️  Scene name     : {scene_name}")

    # 4) If it matches, nothing else to do
    if expected in actual:
        logging.info(f"✅ Scene title matches for {series['title']} {code}")
        return

    # 5) Read the stored count; if over threshold, ignore
    current_count = get_mismatch_count(key)
    if current_count >= MISMATCH_THRESHOLD:
        logging.info(
            f"⏩ Ignoring mismatch for {series['title']} {code} "
            f"(count={current_count} ≥ {MISMATCH_THRESHOLD})"
        )
        return

    # 6) Check for special‐tag ignore
    if should_ignore_episode_file(epfile["id"]):
        logging.info("⏩ Ignored due to special tag.")
        return

    # 7) Legitimate mismatch under threshold → proceed
    logging.error(f"❌ Scene title does NOT match expected title for {series['title']} {code}")

    if not FORCE_RUN:
        logging.info("Skipping automatic deletion/search (not in force run mode).")
        return

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
    scan_library()
