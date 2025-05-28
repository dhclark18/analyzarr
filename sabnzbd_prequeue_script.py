#!/usr/bin/env python3
import os
import sys
import re
import unicodedata
import logging
from datetime import datetime
import requests
import psycopg2
import warnings

# === Suppress warnings and HTTP logs ===
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("requests").setLevel(logging.CRITICAL)

# === CONFIG & LOGGING ===
LOG_FILE           = os.getenv("LOG_FILE", "/tmp/sabnzbd_prequeue_script.log")         # don't mess with
DATABASE_URL       = os.getenv("DATABASE_URL", "[postgres db url]")                    # fill in db url
MISMATCH_THRESHOLD = int(os.getenv("MISMATCH_THRESHOLD", "3"))                         # needs to match value in analyzer.py
MOVIE_CATEGORY     = os.getenv("MOVIE_CATEGORY", "movies")                             # don't mess with
SONARR_URL         = os.getenv("SONARR_URL", "http://[sonarr_ip]:8989").rstrip("/")    # fill in sonarr ip address
SONARR_API_KEY     = os.getenv("SONARR_API_KEY", "[sonarr api key]")                   # fill in sonarr api key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")]
)
logger = logging.getLogger(__name__)
HEADERS = {"X-Api-Key": SONARR_API_KEY}


# === DB HELPERS ===
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

def db_query(sql, params=None):
    rows = db_execute(sql, params, fetch=True)
    return rows[0] if rows else None


# === SCHEMA INIT ===
def init_db():
    db_execute("""
    CREATE TABLE IF NOT EXISTS mismatch_tracking (
      key TEXT PRIMARY KEY,
      count INTEGER NOT NULL DEFAULT 0,
      last_mismatch TIMESTAMP
    );
    """)


# === MISMATCH COUNTER ===
def get_count(key):
    row = db_query("SELECT count FROM mismatch_tracking WHERE key=%s", (key,))
    return row[0] if row else 0

def inc_count(key):
    now = datetime.utcnow()
    db_execute(
      """
      INSERT INTO mismatch_tracking (key, count, last_mismatch)
      VALUES (%s, 1, %s)
      ON CONFLICT (key) DO
        UPDATE SET count = mismatch_tracking.count + 1,
                   last_mismatch = EXCLUDED.last_mismatch;
      """,
      (key, now)
    )
    return get_count(key)

def reset_count(key):
    db_execute("UPDATE mismatch_tracking SET count = 0 WHERE key=%s", (key,))


# === UTILITIES ===
def normalize(text):
    clean = unicodedata.normalize("NFKD", text or "").replace("&","and")
    return "".join(c for c in clean if c.isalnum()).lower()

def respond(code):
    print(code)
    sys.exit(0)


# === MAIN LOGIC ===
def main():
    if len(sys.argv) < 4:
        logger.error("Not enough arguments")
        sys.exit(1)

    nzbname, _, category = sys.argv[1:4]

    # skip movies
    if category.lower() == MOVIE_CATEGORY.lower():
        return respond("1")

    # extract series+SxxExx
    m = re.search(r"(.+?)[ ._\-]+[sS](\d{2})[eE](\d{2})", nzbname)
    if not m:
        return respond("1")

    series_raw, season, episode = m.groups()
    key = f"series::{normalize(series_raw)}::S{season}E{episode}"

    # ensure our table exists
    init_db()

    # fetch Sonarr series list
    try:
        r = requests.get(f"{SONARR_URL}/api/v3/series", headers=HEADERS)
        r.raise_for_status()
        series_list = r.json()
    except Exception:
        return respond("1")

    # find matching show
    show = next(
      (s for s in series_list
       if normalize(s.get("title","")) == normalize(series_raw)),
      None
    )
    if not show:
        return respond("1")

    # fetch episodes metadata
    try:
        r = requests.get(f"{SONARR_URL}/api/v3/episode?seriesId={show['id']}", headers=HEADERS)
        r.raise_for_status()
        episodes = r.json()
    except Exception:
        return respond("1")

    ep = next(
      (e for e in episodes
       if e.get("seasonNumber")==int(season)
          and e.get("episodeNumber")==int(episode)),
      None
    )
    if not ep:
        return respond("1")

    expected = ep.get("title","")

    # on a successful title‐match → reset counter & accept
    if normalize(expected) in normalize(nzbname):
        reset_count(key)
        logger.info(f"Matching logic: expected='{expected}' -> nzbname='{nzbname}'")
        logger.info(f"🔍 Match successful")
        return respond("1")

    # if we've already hit the threshold, just accept until a match resets it
    if get_count(key) >= MISMATCH_THRESHOLD:
        logger.info(f"Threshold reached for {key} ({get_count(key)} mismatches) — accepting until next match")
        return respond("1")

    # otherwise → bump counter & reject
    new_count = inc_count(key)
    logger.info(f"Mismatch #{new_count} for {key}")
    return respond("2")


if __name__ == "__main__":
    main()
