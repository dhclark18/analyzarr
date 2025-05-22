#!/usr/bin/env python3
import os
import re
import requests
import logging
import unicodedata
import psycopg2
from pathlib import Path

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
SONARR_URL         = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY     = os.getenv("SONARR_API_KEY")
SONARR_HEADERS     = {"X-Api-Key": SONARR_API_KEY}
TVDB_FILTER        = os.getenv("TVDB_ID")
FORCE_RUN          = os.getenv("FR_RUN", "false").lower() == "true"
DATABASE_URL       = os.getenv("DATABASE_URL")
SPECIAL_TAG_NAME   = os.getenv("SPECIAL_TAG_NAME", "problematic-title")
MISMATCH_THRESHOLD = int(os.getenv("MISMATCH_THRESHOLD", "10"))

# Optional season filter: comma-sep list of ints, or empty/None to disable
_raw = os.getenv("SEASON_FILTER")
if _raw:
    try:
        SEASON_FILTER = [int(x.strip()) for x in _raw.split(",")]
    except ValueError:
        logging.warning(f"Invalid SEASON_FILTER '{_raw}', ignoring.")
        SEASON_FILTER = None
else:
    SEASON_FILTER = None

# --- DB Init & Tag Helpers ---
def init_db():
    ddl = """
    CREATE TABLE IF NOT EXISTS mismatch_tracking (
      key TEXT PRIMARY KEY,
      count INTEGER NOT NULL DEFAULT 0,
      last_mismatch TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tags (
      id SERIAL PRIMARY KEY,
      name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS episode_tags (
      episode_file_id INTEGER NOT NULL,
      tag_id INTEGER NOT NULL REFERENCES tags(id),
      PRIMARY KEY (episode_file_id, tag_id)
    );
    """
    with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()

def ensure_tag(conn, tag_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tags (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (tag_name,)
        )
        cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
        return cur.fetchone()[0]

def add_tag(episode_file_id: int, tag_name: str):
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            tag_id = ensure_tag(conn, tag_name)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO episode_tags (episode_file_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (episode_file_id, tag_id)
                )
            conn.commit()
        logging.info(f"🏷️  Tagged file {episode_file_id} with '{tag_name}'")
    except Exception as e:
        logging.error(f"DB error adding tag '{tag_name}' to file {episode_file_id}: {e}")

def remove_tag(episode_file_id: int, tag_name: str):
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM episode_tags et
                      USING tags t
                     WHERE et.tag_id = t.id
                       AND et.episode_file_id = %s
                       AND t.name = %s
                    """,
                    (episode_file_id, tag_name)
                )
            conn.commit()
        logging.info(f"❎ Removed tag '{tag_name}' from file {episode_file_id}")
    except Exception as e:
        logging.error(f"DB error removing tag '{tag_name}' from file {episode_file_id}: {e}")

# --- DB Helper (read-only) ---
def get_mismatch_count(key: str) -> int:
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count FROM mismatch_tracking WHERE key = %s", (key,))
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
        for cmd in ("RefreshSeries", "RescanSeries"):
            requests.post(
                f"{SONARR_URL}/api/v3/command",
                headers=SONARR_HEADERS,
                json={"name": cmd, "seriesId": series_id}
            )
        logging.info(f"🔄 Refreshed/rescanned series ID {series_id}")
    except Exception as e:
        logging.error(f"Failed to refresh/rescan series {series_id}: {e}")

def search_episode(episode_id):
    try:
        requests.post(
            f"{SONARR_URL}/api/v3/command",
            headers=SONARR_HEADERS,
            json={"name": "EpisodeSearch", "episodeIds": [episode_id]}
        )
        logging.info(f"🔍 Initiated search for episode ID {episode_id}")
    except Exception as e:
        logging.error(f"Failed to initiate search for episode {episode_id}: {e}")

# --- Main Logic ---
def check_episode(series, episode):
    # 1) Skip if no file
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    # 2) Fetch file metadata
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
        logging.warning(f"⚠️ Missing scene name for file {epfile.get('id')}")
        return

    # 3) Extract season & episode from sceneName via regex
    m = re.search(r"[sS](\d{2})[eE](\d{2})", scene_name)
    if m:
        season, epnum = map(int, m.groups())
    else:
        season = episode["seasonNumber"]
        epnum  = episode["episodeNumber"]

    code        = f"S{season:02}E{epnum:02}"
    series_norm = normalize_title(series["title"])
    key         = f"series::{series_norm}::S{season:02d}E{epnum:02d}"
    expected    = normalize_title(episode["title"])
    actual      = normalize_title(scene_name)

    # 3a) Optional season‐filter
    if SEASON_FILTER and season not in SEASON_FILTER:
        logging.debug(f"⏩ Skipping {series['title']} {code}; season not in filter {SEASON_FILTER}")
        return

    logging.info(f"\n📺 {series['title']} {code}")
    logging.info(f"🎯 Expected title : {episode['title']}")
    logging.info(f"🎞️  Scene name     : {scene_name}")

    # 4) On match → remove tag & done
    if expected in actual:
        remove_tag(epfile["id"], SPECIAL_TAG_NAME)
        logging.info(f"✅ Match for {series['title']} {code}; tag removed")
        return

    # 5) On mismatch → check count
    current_count = get_mismatch_count(key)
    if current_count >= MISMATCH_THRESHOLD:
        add_tag(epfile["id"], SPECIAL_TAG_NAME)
        logging.info(
            f"⏩ Threshold reached ({current_count}) → tagged file {epfile['id']} and skipping"
        )
        return

    # 6) Under threshold & no special tag → proceed
    logging.error(f"❌ Scene title mismatch for {series['title']} {code} (count={current_count})")
    if not FORCE_RUN:
        logging.info("Skipping deletion/search (not force-run).")
        return

    delete_file(epfile["id"])
    refresh_series(series["id"])
    search_episode(episode["id"])

def scan_library():
    if not SONARR_API_KEY:
        logging.error("❌ SONARR_API_KEY is not set.")
        return

    for series in get_series_list():
        if TVDB_FILTER and str(series.get("tvdbId")) != TVDB_FILTER:
            continue
        logging.info(f"\n=== Scanning: {series['title']} ===")
        for episode in get_episodes(series["id"]):
            check_episode(series, episode)

if __name__ == "__main__":
    init_db()
    scan_library()
