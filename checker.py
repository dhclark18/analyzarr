#!/usr/bin/env python3
import os
import re
import requests
import logging
import unicodedata
import psycopg2
from datetime import datetime, timedelta

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
MISMATCH_TTL_DAYS  = int(os.getenv("MISMATCH_TTL_DAYS", "30"))

# --- DB Init & Maintenance ---
def init_db():
    ddl = """
    CREATE TABLE IF NOT EXISTS mismatch_tracking (
      key           TEXT PRIMARY KEY,
      count         INTEGER NOT NULL DEFAULT 0,
      last_mismatch TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tags (
      id   SERIAL PRIMARY KEY,
      name TEXT   UNIQUE NOT NULL
    );
    -- episode_tags now carries season & episode explicitly
    CREATE TABLE IF NOT EXISTS episode_tags (
      key     TEXT NOT NULL REFERENCES mismatch_tracking(key),
      tag_id  INTEGER NOT NULL REFERENCES tags(id),
      season  INTEGER NOT NULL,
      episode INTEGER NOT NULL,
      PRIMARY KEY (key, tag_id)
    );
    """
    with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()

def purge_old_mismatches(ttl_days: int):
    cutoff = datetime.utcnow() - timedelta(days=ttl_days)
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM mismatch_tracking WHERE last_mismatch < %s",
                    (cutoff,)
                )
                deleted = cur.rowcount
            conn.commit()
        logging.info(f"🗑️ Purged {deleted} old mismatch records (> {ttl_days} days)")
    except Exception as e:
        logging.error(f"DB error purging old mismatches: {e}")

# --- Tag Helpers (key-based) ---
def ensure_tag(conn, tag_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tags (name) VALUES (%s) ON CONFLICT DO NOTHING",
            (tag_name,)
        )
        cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
        return cur.fetchone()[0]

def add_tag(key: str, tag_name: str, season: int, episode: int):
    """
    Tag this key for a specific season/episode.
    """
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            tag_id = ensure_tag(conn, tag_name)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO episode_tags (key, tag_id, season, episode)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (key, tag_id) DO NOTHING
                    """,
                    (key, tag_id, season, episode)
                )
            conn.commit()
        logging.info(f"🏷️ Tagged {key} (S{season:02}E{episode:02}) with '{tag_name}'")
    except Exception as e:
        logging.error(f"DB error adding tag '{tag_name}' to {key}: {e}")

def remove_tag(key: str, tag_name: str, season: int, episode: int):
    """
    Remove the tag for this key *and* the given season/episode.
    """
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM episode_tags et
                      USING tags t
                     WHERE et.tag_id = t.id
                       AND et.key = %s
                       AND t.name = %s
                       AND et.season = %s
                       AND et.episode = %s
                    """,
                    (key, tag_name, season, episode)
                )
            conn.commit()
        logging.info(f"❎ Removed tag '{tag_name}' for {key} S{season:02d}E{episode:02d}")
    except Exception as e:
        logging.error(f"DB error removing tag '{tag_name}' from {key} S{season:02d}E{episode:02d}: {e}")

# --- Mismatch‐Tracking Helpers ---
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

def delete_mismatch_record(key: str):
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM mismatch_tracking WHERE key = %s", (key,))
            conn.commit()
        logging.info(f"🗑️ Deleted mismatch record for {key}")
    except Exception as e:
        logging.error(f"DB error deleting mismatch record {key}: {e}")

# --- Utils & Sonarr API ---
def normalize_title(text):
    if not text:
        return ""
    text = text.replace("&", "and")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isalnum()).lower()

def get_series_list():
    r = requests.get(f"{SONARR_URL}/api/v3/series", headers=SONARR_HEADERS)
    r.raise_for_status(); return r.json()

def get_episodes(series_id):
    r = requests.get(f"{SONARR_URL}/api/v3/episode?seriesId={series_id}", headers=SONARR_HEADERS)
    r.raise_for_status(); return r.json()

def get_episode_file(file_id):
    r = requests.get(f"{SONARR_URL}/api/v3/episodefile/{file_id}", headers=SONARR_HEADERS)
    r.raise_for_status(); return r.json()

def delete_file(file_id):
    try:
        r = requests.delete(f"{SONARR_URL}/api/v3/episodefile/{file_id}", headers=SONARR_HEADERS)
        r.raise_for_status()
        logging.info(f"🗑️ Deleted episode file ID {file_id}")
    except Exception as e:
        logging.error(f"Failed to delete file ID {file_id}: {e}")

def refresh_series(series_id):
    for cmd in ("RefreshSeries", "RescanSeries"):
        try:
            requests.post(
                f"{SONARR_URL}/api/v3/command",
                headers=SONARR_HEADERS,
                json={"name": cmd, "seriesId": series_id}
            ).raise_for_status()
        except Exception as e:
            logging.error(f"Failed to {cmd} for series {series_id}: {e}")
    logging.info(f"🔄 Refreshed series ID {series_id}")

def search_episode(episode_id):
    try:
        requests.post(
            f"{SONARR_URL}/api/v3/command",
            headers=SONARR_HEADERS,
            json={"name": "EpisodeSearch", "episodeIds": [episode_id]}
        ).raise_for_status()
        logging.info(f"🔍 Searched for episode ID {episode_id}")
    except Exception as e:
        logging.error(f"Failed to search for episode {episode_id}: {e}")

# --- Main Logic ---
def check_episode(series, episode):
    # Skip if no file
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    # Fetch file metadata
    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(
            f"❌ Could not fetch file for "
            f"{series['title']} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}: {e}"
        )
        return

    scene = epfile.get("sceneName") or ""
    m = re.search(r"[sS](\d{2})[eE](\d{2})", scene)
    if m:
        parsed_season, parsed_epnum = map(int, m.groups())
    else:
        parsed_season = episode["seasonNumber"]
        parsed_epnum  = episode["episodeNumber"]

    series_norm = normalize_title(series["title"])
    key = f"series::{series_norm}::S{parsed_season:02d}E{parsed_epnum:02d}"

    # 2) Grab Sonarr’s “official” season/episode for tagging
    expected_season = episode["seasonNumber"]
    expected_epnum  = episode["episodeNumber"]

    code      = f"S{season:02}E{epnum:02}"
    series_n  = normalize_title(series["title"])
    expected  = normalize_title(episode["title"])
    actual    = normalize_title(scene)

    logging.info(f"\n📺 {series['title']} {code}")
    logging.info(f"🎯 Expected: {episode['title']}")
    logging.info(f"🎞️  Scene:    {scene}")

     # On a real match → remove tag using Sonarr’s expected values
    if normalize_title(episode["title"]) in normalize_title(scene_name):
        remove_tag(key, SPECIAL_TAG_NAME, expected_season, expected_epnum)
        logging.info(
            f"✅ Match for {series['title']} "
            f"S{expected_season:02d}E{expected_epnum:02d}; tag removed"
        )
        return

   # On threshold → tag using Sonarr’s expected values
    cnt = get_mismatch_count(key)
    if cnt >= MISMATCH_THRESHOLD:
        add_tag(key, SPECIAL_TAG_NAME, expected_season, expected_epnum)
        logging.info(
            f"⏩ Threshold reached ({cnt}) → tagged "
            f"{series['title']} S{expected_season:02d}E{expected_epnum:02d}"
        )
        return

    # Under threshold → proceed
    logging.error(f"❌ Mismatch for {code} (count={cnt})")
    if not FORCE_RUN:
        logging.info("Skipping actions (not force-run).")
        return

    delete_file(epfile["id"])
    refresh_series(series["id"])
    search_episode(episode["id"])

def scan_library():
    if not SONARR_API_KEY:
        logging.error("❌ SONARR_API_KEY not set.")
        return
    for s in get_series_list():
        if TVDB_FILTER and str(s.get("tvdbId")) != TVDB_FILTER:
            continue
        logging.info(f"\n=== Scanning {s['title']} ===")
        for ep in get_episodes(s["id"]):
            check_episode(s, ep)

if __name__ == "__main__":
    init_db()
    purge_old_mismatches(MISMATCH_TTL_DAYS)
    scan_library()
