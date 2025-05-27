#!/usr/bin/env python3
import os
import re
import sys
import requests
import logging
import unicodedata
import psycopg2
from datetime import datetime, timedelta

# --- Validate environment ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not set.", file=sys.stderr)
    sys.exit(1)

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
if not SONARR_API_KEY:
    logging.error("❌ SONARR_API_KEY not set.")
    sys.exit(1)
SONARR = requests.Session()
SONARR.headers.update({"X-Api-Key": SONARR_API_KEY})

TVDB_FILTER        = os.getenv("TVDB_ID")
FORCE_RUN          = os.getenv("FR_RUN", "false").lower() == "true"
SPECIAL_TAG_NAME   = os.getenv("SPECIAL_TAG_NAME", "problematic-title")
MISMATCH_THRESHOLD = int(os.getenv("MISMATCH_THRESHOLD", "5"))
MISMATCH_TTL_DAYS  = int(os.getenv("MISMATCH_TTL_DAYS", "30"))

# Optional season filter
_raw = os.getenv("SEASON_FILTER")
if _raw:
    try:
        SEASON_FILTER = [int(x.strip()) for x in _raw.split(",")]
    except ValueError:
        logging.warning(f"Invalid SEASON_FILTER '{_raw}', ignoring.")
        SEASON_FILTER = None
else:
    SEASON_FILTER = None

# --- DB Init & Maintenance ---
def init_db():
    ddl_mismatch = """
    CREATE TABLE IF NOT EXISTS mismatch_tracking (
      key           TEXT PRIMARY KEY,
      count         INTEGER NOT NULL DEFAULT 0,
      last_mismatch TIMESTAMP
    );
    """
    ddl_tags = """
    CREATE TABLE IF NOT EXISTS tags (
      id   SERIAL PRIMARY KEY,
      name TEXT   UNIQUE NOT NULL
    );
    """
    ddl_ep_tags = """
    CREATE TABLE IF NOT EXISTS episode_tags (
      key           TEXT NOT NULL REFERENCES mismatch_tracking(key) ON DELETE CASCADE,
      tag_id        INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
      code          TEXT NOT NULL,
      series_title  TEXT NOT NULL,
      PRIMARY KEY (key, tag_id)
    );
    """
    alter_ep_tags = """
    ALTER TABLE episode_tags
      ADD COLUMN IF NOT EXISTS series_title TEXT NOT NULL DEFAULT '';
    """

    with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl_mismatch)
            cur.execute(ddl_tags)
            cur.execute(ddl_ep_tags)
            cur.execute(alter_ep_tags)
        conn.commit()

# --- Mismatch Count ---
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

def delete_mismatch_record(key: str) -> None:
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM mismatch_tracking WHERE key = %s", (key,))
            conn.commit()
        logging.info(f"🗑️ Deleted mismatch record for {key}")
    except Exception as e:
        logging.error(f"DB error deleting mismatch record {key}: {e}")

# --- Tag Helpers ---
def ensure_tag(conn, tag_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tags (name) VALUES (%s) ON CONFLICT DO NOTHING",
            (tag_name,)
        )
        cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
        return cur.fetchone()[0]

def add_tag(key: str, tag_name: str, code: str, series_title: str) -> None:
    """
    Add a tag for this key and episode code (e.g., S01E02).
    """
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            tag_id = ensure_tag(conn, tag_name)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO episode_tags (key, tag_id, code, series_title)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (key, tag_id) DO NOTHING
                    """,
                    (key, tag_id, code, series_title)
                )
                inserted = cur.rowcount
            conn.commit()
        if inserted:
            logging.info(f"🏷️ Tagged {key} {code} with '{tag_name}' ({series_title})")
        else:
            logging.debug(f"⚠️ Episode {key} already tagged with '{tag_name}'")
    except Exception as e:
        logging.error(f"DB error adding tag '{tag_name}' to {key} {code}: {e}")

def remove_tag(key: str, tag_name: str, code: str, series_title: str) -> None:
    """
    Remove the tag for this key and episode code (e.g., S01E02).
    """
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM episode_tags et
                      USING tags t
                     WHERE et.tag_id       = t.id
                       AND et.key          = %s
                       AND t.name          = %s
                       AND et.code         = %s
                       AND et.series_title = %s
                    """,
                    (key, tag_name, code, series_title)
                )
            conn.commit()
        logging.info(f"❎ Removed tag '{tag_name}' for {key} {code} ({series_title})")
    except Exception as e:
        logging.error(f"DB error removing tag '{tag_name}' from {key} {code}: {e}")

# --- Utils & Sonarr API ---
def normalize_title(text: str) -> str:
    if not text:
        return ""
    text = text.replace("&", "and")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isalnum()).lower()

def get_series_list() -> list:
    r = SONARR.get(f"{SONARR_URL}/api/v3/series", timeout=10)
    r.raise_for_status()
    return r.json()

def get_episodes(series_id: int) -> list:
    r = SONARR.get(f"{SONARR_URL}/api/v3/episode?seriesId={series_id}", timeout=10)
    r.raise_for_status()
    return r.json()

def get_episode_file(file_id: int) -> dict:
    r = SONARR.get(f"{SONARR_URL}/api/v3/episodefile/{file_id}", timeout=10)
    r.raise_for_status()
    return r.json()

def delete_file(file_id: int) -> None:
    try:
        r = SONARR.delete(f"{SONARR_URL}/api/v3/episodefile/{file_id}", timeout=30)
        r.raise_for_status()
        logging.info(f"🗑️ Deleted episode file ID {file_id}")
    except requests.exceptions.ReadTimeout:
        logging.warning(f"Timeout deleting file ID {file_id}; verifying deletion status")
        try:
            resp = SONARR.get(f"{SONARR_URL}/api/v3/episodefile/{file_id}", timeout=10)
            if resp.status_code == 404:
                logging.info(f"🗑️ Deletion of file ID {file_id} confirmed after timeout")
            else:
                logging.error(f"❌ File ID {file_id} still present (status {resp.status_code})")
        except Exception as e:
            logging.error(f"Error verifying deletion for file ID {file_id}: {e}")
    except Exception as e:
        logging.error(f"Failed to delete file ID {file_id}: {e}")

def refresh_series(series_id: int) -> None:
    for cmd in ("RefreshSeries", "RescanSeries"):
        try:
            SONARR.post(
                f"{SONARR_URL}/api/v3/command",
                json={"name": cmd, "seriesId": series_id},
                timeout=10
            ).raise_for_status()
        except Exception as e:
            logging.error(f"Failed to {cmd} for series {series_id}: {e}")
    logging.info(f"🔄 Refreshed series ID {series_id}")

def search_episode(episode_id: int) -> None:
    try:
        SONARR.post(
            f"{SONARR_URL}/api/v3/command",
            json={"name": "EpisodeSearch", "episodeIds": [episode_id]},
            timeout=10
        ).raise_for_status()
        logging.info(f"🔍 Searched for episode ID {episode_id}")
    except Exception as e:
        logging.error(f"Failed to search for episode {episode_id}: {e}")

# --- Main Logic ---
def check_episode(series: dict, episode: dict) -> None:
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(
            f"❌ Could not fetch file for {series['title']} "
            f"S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}: {e}"
        )
        return

    # first try Sonarr's sceneName, then fall back to the recorded file name
    raw = (
        epfile.get("sceneName")
        or epfile.get("relativePath")
        or epfile.get("path")
        or ""
    )
    scene = os.path.basename(raw)
    m = re.search(r"[sS](\d{2})[eE](\d{2})", scene)
    if m:
        parsed_season, parsed_epnum = map(int, m.groups())
    else:
        parsed_season = episode["seasonNumber"]
        parsed_epnum = episode["episodeNumber"]

    series_norm = normalize_title(series["title"])
    expected_season = episode["seasonNumber"]
    expected_epnum  = episode["episodeNumber"]
    expected        = normalize_title(episode["title"])
    actual          = normalize_title(scene)
    key             = f"series::{series_norm}::S{expected_season:02d}E{expected_epnum:02d}"
    code            = f"S{expected_season:02}E{expected_epnum:02}"
    # use Sonarr’s original, nicely-formatted title
    nice_title = series["title"]

    logging.info(f"\n📺 {series['title']} {code}")
    logging.info(f"🎯 Expected: {episode['title']}")
    logging.info(f"🎞️ Scene:    {scene}")

    if expected in actual:
        remove_tag(key, SPECIAL_TAG_NAME, code, nice_title)
        logging.info(f"✅ Match for {series['title']} {code}; tag removed")
        return

    cnt = get_mismatch_count(key)
    if cnt >= MISMATCH_THRESHOLD:
        add_tag(key, SPECIAL_TAG_NAME, code, nice_title)
        logging.info(f"⏩ Threshold reached ({cnt}) → tagged {series['title']} {code}")
        return

    logging.error(f"❌ Mismatch for {code} (count={cnt})")
    if not FORCE_RUN:
        logging.info("Skipping actions (not force-run).")
        return

    delete_file(epfile.get("id"))
    refresh_series(series.get("id"))
    search_episode(episode.get("id"))

def scan_library() -> None:
    for s in get_series_list():
        if TVDB_FILTER and str(s.get("tvdbId")) != TVDB_FILTER:
            continue
        logging.info(f"\n=== Scanning {s['title']} ===")
        for ep in get_episodes(s["id"]):
            season = ep.get("seasonNumber")
            if SEASON_FILTER and season not in SEASON_FILTER:
                logging.debug(f"⏩ Skipping S{season:02d} for {s['title']} (filter={SEASON_FILTER})")
                continue
            try:
                check_episode(s, ep)
            except Exception as e:
                logging.error(f"Fatal error checking {s['title']} ep {ep.get('id')}: {e}")

if __name__ == "__main__":
    init_db()
    scan_library()
