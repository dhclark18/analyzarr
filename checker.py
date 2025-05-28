#!/usr/bin/env python3
"""

Features:
 - Pooled PostgreSQL connections (psycopg2 SimpleConnectionPool)
 - Modular SonarrClient with unified error handling, heavily based on Huntarr project
 - Reads mismatch counts from an external incrementer script
 - Tags & auto-grabs when count ≥ threshold, using keys derived from sceneName
 - Optional force-run to delete and requeue instead of tagging
"""

import os
import sys
import re
import time
import logging
import unicodedata
import argparse

import requests
from psycopg2.pool import SimpleConnectionPool

# -----------------------------------------------------------------------------
# CLI & Configuration
# -----------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Huntarr: Sonarr mismatch checker")
parser.add_argument(
    "--force-run",
    action="store_true",
    help="On mismatch, delete and requeue instead of tagging"
)
args = parser.parse_args()

DATABASE_URL       = os.getenv("DATABASE_URL") or sys.exit("❌ DATABASE_URL not set")
SONARR_URL         = os.getenv("SONARR_URL", "http://localhost:8989")
SONARR_API_KEY     = os.getenv("SONARR_API_KEY") or sys.exit("❌ SONARR_API_KEY not set")
API_TIMEOUT        = int(os.getenv("API_TIMEOUT", "10"))
VERIFY_SSL         = os.getenv("VERIFY_SSL", "true").lower() in ("1", "true", "yes")

TVDB_FILTER        = os.getenv("TVDB_ID")
SPECIAL_TAG_NAME   = os.getenv("SPECIAL_TAG_NAME", "problematic-title")
MISMATCH_THRESHOLD = int(os.getenv("MISMATCH_THRESHOLD", "5"))

_raw = os.getenv("SEASON_FILTER", "")
if _raw:
    try:
        SEASON_FILTER = {int(x.strip()) for x in _raw.split(",")}
    except ValueError:
        logging.warning(f"Ignoring invalid SEASON_FILTER='{_raw}'")
        SEASON_FILTER = set()
else:
    SEASON_FILTER = set()

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------

LOG_DIR = os.getenv("LOG_PATH", "/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "huntarr.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# -----------------------------------------------------------------------------
# Database Connection Pool
# -----------------------------------------------------------------------------

db_pool = SimpleConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)

def with_conn(fn):
    """Decorator: borrow a conn from the pool, return it when done."""
    def wrapper(*args, **kwargs):
        conn = db_pool.getconn()
        try:
            return fn(conn, *args, **kwargs)
        finally:
            db_pool.putconn(conn)
    return wrapper

# -----------------------------------------------------------------------------
# Schema Initialization
# -----------------------------------------------------------------------------

@with_conn
def init_db(conn):
    """
    Ensure only the tagging tables exist; mismatch counts are managed externally.
    """
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS tags (
          id   SERIAL PRIMARY KEY,
          name TEXT   UNIQUE NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS episode_tags (
          key           TEXT NOT NULL,
          tag_id        INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
          code          TEXT NOT NULL,
          series_title  TEXT NOT NULL,
          PRIMARY KEY (key, tag_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS mismatch_tracking (
          key           TEXT PRIMARY KEY,
          count         INTEGER NOT NULL DEFAULT 0,
          last_mismatch TIMESTAMP
        );
        """,
    ]
    with conn.cursor() as cur:
        for stmt in ddl:
            cur.execute(stmt)
    conn.commit()
    logging.info("✅ Database schema (tags) ensured")

# -----------------------------------------------------------------------------
# Mismatch Count Reader
# -----------------------------------------------------------------------------

@with_conn
def get_mismatch_count(conn, key: str) -> int:
    """Read the pre-incremented mismatch count for this key."""
    with conn.cursor() as cur:
        cur.execute("SELECT count FROM mismatch_tracking WHERE key = %s", (key,))
        row = cur.fetchone()
    return row[0] if row else 0

# -----------------------------------------------------------------------------
# Tag Helpers
# -----------------------------------------------------------------------------

@with_conn
def ensure_tag(conn, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tags (name) VALUES (%s) ON CONFLICT DO NOTHING",
            (name,)
        )
        cur.execute("SELECT id FROM tags WHERE name = %s", (name,))
        return cur.fetchone()[0]

@with_conn
def add_tag(conn, key: str, tag_name: str, code: str, series_title: str) -> bool:
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
        inserted = cur.rowcount == 1
    conn.commit()
    return inserted

@with_conn
def remove_tag(conn, key: str, tag_name: str, code: str, series_title: str) -> bool:
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
        deleted = cur.rowcount == 1
    conn.commit()
    return deleted

# -----------------------------------------------------------------------------
# Sonarr API Client
# -----------------------------------------------------------------------------

class SonarrClient:
    def __init__(self, base_url, api_key, timeout=10, verify_ssl=True):
        self.base_url   = base_url.rstrip("/")
        self.timeout    = timeout
        self.verify_ssl = verify_ssl
        self.session    = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "User-Agent": "checker"
        })

    def request(self, endpoint, method="GET", json_data=None):
        url = f"{self.base_url}/api/v3/{endpoint.lstrip('/')}"
        try:
            resp = self.session.request(
                method, url,
                json=json_data,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except Exception:
            logging.exception(f"🚨 Sonarr API error on {method} {endpoint}")
            return None

    def get(self, endpoint):
        return self.request(endpoint, "GET")

    def post(self, endpoint, data=None):
        return self.request(endpoint, "POST", json_data=data)

    def delete(self, endpoint):
        return self.request(endpoint, "DELETE")

# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

def normalize_title(text: str) -> str:
    if not text:
        return ""
    text = text.replace("&", "and")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isalnum()).lower()

# -----------------------------------------------------------------------------
# Core Logic
# -----------------------------------------------------------------------------

def check_episode(client: SonarrClient, series: dict, ep: dict):
    if not ep.get("hasFile") or not ep.get("episodeFileId"):
        return

    epfile = client.get(f"episodefile/{ep['episodeFileId']}")
    if epfile is None:
        logging.error(f"❌ Failed to fetch file metadata for {series['title']} ep {ep['id']}")
        return

    raw   = epfile.get("sceneName") or epfile.get("relativePath") or epfile.get("path") or ""
    scene = os.path.basename(raw)

    # parse season/episode from sceneName to build the same key as the incrementer
    m = re.search(r"[sS](\d{2})[eE](\d{2})", scene)
    if m:
        parsed_season, parsed_epnum = map(int, m.groups())
    else:
        # fallback to the Sonarr‐expected numbers
        parsed_season   = ep["seasonNumber"]
        parsed_epnum    = ep["episodeNumber"]

    key  = f"series::{normalize_title(series['title'])}::S{parsed_season:02d}E{parsed_epnum:02d}"
    code = f"S{parsed_season:02d}E{parsed_epnum:02d}"
    nice = series["title"]

    expected_norm = normalize_title(ep["title"])
    actual_norm   = normalize_title(scene)

    logging.info(f"\n📺 {nice} {code}")
    logging.info(f"🎯 Expected: {ep['title']}")
    logging.info(f"🎞️ Scene:    {scene}")

    # On match: remove any existing tag
    if expected_norm in actual_norm:
        if remove_tag(key, SPECIAL_TAG_NAME, code, nice):
            logging.info(f"✅ Match for {nice} {code}; tag removed")
        return

    # On mismatch: fetch external count using the parsed key
    count = get_mismatch_count(key)
    logging.error(f"❌ Mismatch for {code} (external count={count})")

    if count >= MISMATCH_THRESHOLD:
        # Tag & grab best NZB once
        if add_tag(key, SPECIAL_TAG_NAME, code, nice):
            logging.info(f"⏩ Count ≥ {MISMATCH_THRESHOLD}, tagging & grabbing best NZB")
            grab_best_nzb(client, series["id"], ep["id"])
        else:
            logging.info(f"⏩ Already tagged {nice} {code}; skipping grab")

    elif args.force_run:
        # Immediate delete/requeue if forced
        logging.info("⚡ Force-run: deleting file and re-searching")
        delete_episode_file(client, epfile["id"])
        refresh_series(client, series["id"])
        search_episode(client, ep["id"])

def scan_library(client: SonarrClient):
    for series in client.get("series") or []:
        if TVDB_FILTER and str(series.get("tvdbId")) != TVDB_FILTER:
            continue
        logging.info(f"\n=== Scanning {series['title']} ===")
        for ep in client.get(f"episode?seriesId={series['id']}") or []:
            if SEASON_FILTER and ep["seasonNumber"] not in SEASON_FILTER:
                continue
            try:
                check_episode(client, series, ep)
            except Exception:
                logging.exception(f"Fatal error checking {series['title']} ep {ep.get('id')}")

# -----------------------------------------------------------------------------
# Sonarr Actions
# -----------------------------------------------------------------------------

def delete_episode_file(client: SonarrClient, file_id: int):
    client.delete(f"episodefile/{file_id}")
    logging.info(f"🗑️ Deleted episode file ID {file_id}")

def refresh_series(client: SonarrClient, series_id: int):
    for cmd in ("RefreshSeries", "RescanSeries"):
        client.post("command", {"name": cmd, "seriesId": series_id})
    logging.info(f"🔄 Refreshed series ID {series_id}")

def search_episode(client: SonarrClient, episode_id: int):
    client.post("command", {"name": "EpisodeSearch", "episodeIds": [episode_id]})
    logging.info(f"🔍 Searched for episode ID {episode_id}")

def grab_best_nzb(client: SonarrClient, series_id: int, episode_id: int, wait: int = 5):
    cmd = client.post("command", {"name": "EpisodeSearch", "episodeIds": [episode_id]})
    if not cmd or "id" not in cmd:
        logging.error("Failed to start EpisodeSearch")
        return

    time.sleep(wait)
    releases = client.get(f"release?episodeId={episode_id}") or []
    candidates = [r for r in releases if r.get("seriesId") == series_id]
    if not candidates:
        logging.warning("No releases found to pick from")
        return

    best = max(candidates, key=lambda r: r.get("customFormatScore", 0))
    if not best.get("downloadUrl"):
        logging.error("Best release has no downloadUrl")
        return

    payload = {
        "title":       best.get("title"),
        "downloadUrl": best["downloadUrl"],
        "protocol":    best.get("protocol"),
        "publishDate": best.get("publishDate")
    }
    pushed = client.post("release/push", payload)
    if pushed is not None:
        logging.info(f"⬇️ Queued '{best.get('title')}' via release/push")
    else:
        logging.error("Failed to push release into Sonarr")

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        init_db()
        sonarr = SonarrClient(SONARR_URL, SONARR_API_KEY,
                              timeout=API_TIMEOUT, verify_ssl=VERIFY_SSL)
        scan_library(sonarr)
    except Exception:
        logging.critical("💥 Unhandled exception, shutting down", exc_info=True)
        sys.exit(1)
