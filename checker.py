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
SONARR_URL = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
if not SONARR_API_KEY:
    logging.error("❌ SONARR_API_KEY not set.")
    sys.exit(1)
SONARR_HEADERS = {"X-Api-Key": SONARR_API_KEY}
SONARR = requests.Session()
SONARR.headers.update(SONARR_HEADERS)

TVDB_FILTER = os.getenv("TVDB_ID")
FORCE_RUN = os.getenv("FR_RUN", "false").lower() == "true"
SPECIAL_TAG_NAME = os.getenv("SPECIAL_TAG_NAME", "problematic-title")
MISMATCH_THRESHOLD = int(os.getenv("MISMATCH_THRESHOLD", "10"))
MISMATCH_TTL_DAYS = int(os.getenv("MISMATCH_TTL_DAYS", "30"))

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
    # Only create tag-related tables; mismatch_tracking is managed by another script
    ddl_tags = """
    CREATE TABLE IF NOT EXISTS tags (
      id   SERIAL PRIMARY KEY,
      name TEXT   UNIQUE NOT NULL
    );
    """
    ddl_ep_tags = """
    CREATE TABLE IF NOT EXISTS episode_tags (
      key     TEXT NOT NULL
                REFERENCES mismatch_tracking(key)
                ON DELETE CASCADE,
      tag_id  INTEGER NOT NULL
                REFERENCES tags(id)
                ON DELETE CASCADE,
      season  INTEGER NOT NULL,
      episode INTEGER NOT NULL,
      PRIMARY KEY (key, tag_id)
    );
    """
    with psycopg2.connect(DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl_tags)
            cur.execute(ddl_ep_tags)
        conn.commit()


def purge_old_mismatches(ttl_days: int) -> None:
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


def add_tag(key: str, tag_name: str, season: int, episode: int) -> None:
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


def remove_tag(key: str, tag_name: str, season: int, episode: int) -> None:
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
        logging.error(f"DB error removing tag '{tag_name}' from {key}: {e}")

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
        r = SONARR.delete(f"{SONARR_URL}/api/v3/episodefile/{file_id}", timeout=10)
        r.raise_for_status()
        logging.info(f"🗑️ Deleted episode file ID {file_id}")
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
    # Skip if no file
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    # Fetch file metadata
    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(
            f"❌ Could not fetch file for {series['title']} "
            f"S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}: {e}"
        )
        return

    scene = epfile.get("sceneName") or ""
    m = re.search(r"[sS](\d{2})[eE](\d{2})", scene)
    if m:
        parsed_season, parsed_epnum = map(int, m.groups())
    else:
        parsed_season = episode["seasonNumber"]
        parsed_epnum = episode["episodeNumber"]

    series_norm = normalize_title(series["title"])
    key = f"series::{series_norm}::S{parsed_season:02d}E{parsed_epnum:02d}"

    # Sonarr’s expected values
    expected_season = episode["seasonNumber"]
    expected_epnum = episode["episodeNumber"]
    expected = normalize_title(episode["title"])
    actual = normalize_title(scene)

    code = f"S{expected_season:02}E{expected_epnum:02}"
    logging.info(f"\n📺 {series['title']} {code}")
    logging.info(f"🎯 Expected: {episode['title']}")
    logging.info(f"🎞️  Scene:    {scene}")

    # Optional season‐filter
    if SEASON_FILTER and expected_season not in SEASON_FILTER:
        logging.debug(
            f"⏩ Skipping {series['title']} {code}; season not in filter {SEASON_FILTER}"
        )
        return

    # On a match → remove tag
    if expected in actual:
        remove_tag(key, SPECIAL_TAG_NAME, expected_season, expected_epnum)
        logging.info(
            f"✅ Match for {series['title']} "
            f"S{expected_season:02d}E{expected_epnum:02d}; tag removed"
        )
        return

    # Check threshold without incrementing
    cnt = get_mismatch_count(key)
    if cnt >= MISMATCH_THRESHOLD:
        add_tag(key, SPECIAL_TAG_NAME, expected_season, expected_epnum)
        logging.info(
            f"⏩ Threshold reached ({cnt}) → tagged "
            f"{series['title']} S{expected_season:02d}E{expected_epnum:02d}"
        )
        return

    # Under threshold → optionally delete & re-search
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
            try:
                check_episode(s, ep)
            except Exception as e:
                logging.error(
                    f"Fatal error checking {s['title']} ep {ep.get('id')}: {e}"
                )


if __name__ == "__main__":
    init_db()
    purge_old_mismatches(MISMATCH_TTL_DAYS)
    scan_library()
