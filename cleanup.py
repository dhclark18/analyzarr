#!/usr/bin/env python3
"""
cleanup.py

Fetches every Sonarr series, then for each series fetches its episodes.
Builds a single set of “live” keys (series::<normalized>::SxxExx) and
issues one bulk DELETE to remove any database rows not in that set.
"""

import os
import sys
import re
import unicodedata
import logging
import requests
from psycopg2.pool import SimpleConnectionPool
from psycopg2 import sql
from word2number import w2n

# ─── Configuration ─────────────────────────────────────────────────────────────

DATABASE_URL   = os.getenv("DATABASE_URL") or sys.exit("❌ DATABASE_URL not set")
SONARR_URL     = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY") or sys.exit("❌ SONARR_API_KEY not set")
API_TIMEOUT    = int(os.getenv("API_TIMEOUT", "10"))

# ─── Logging Setup ─────────────────────────────────────────────────────────────

LOG_DIR = os.getenv("LOG_PATH", "/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "cleanup.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)

# ─── Database Connection Pool ─────────────────────────────────────────────────

try:
    db_pool = SimpleConnectionPool(minconn=1, maxconn=5, dsn=DATABASE_URL)
except Exception as e:
    logging.critical(f"❌ Failed to create DB pool: {e}", exc_info=True)
    sys.exit(1)

def with_conn(fn):
    """Decorator: borrow a conn from the pool, return it when done."""
    def wrapper(*args, **kwargs):
        conn = db_pool.getconn()
        try:
            return fn(conn, *args, **kwargs)
        finally:
            db_pool.putconn(conn)
    return wrapper

# ─── Sonarr API Client ────────────────────────────────────────────────────────

class SonarrClient:
    def __init__(self, base_url, api_key, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout
        self.session  = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "User-Agent": "cleanup-script"
        })

    def request(self, endpoint, method="GET", json_data=None, params=None):
        url = f"{self.base_url}/api/v3/{endpoint.lstrip('/')}"
        try:
            resp = self.session.request(
                method, url,
                json=json_data,
                params=params,
                timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json() if resp.content else []
        except Exception:
            logging.exception(f"🚨 Sonarr API error on {method} {endpoint} {params or ''}")
            return None

    def get(self, endpoint, params=None):
        return self.request(endpoint, "GET", params=params)

# ─── Utility: Normalize Series Titles ─────────────────────────────────────────

# 1) A pattern matching all English number-words we care about
_NUMWORD = (
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|million"
)

# 2) Build a regex that grabs one or more of those, allowing hyphens or spaces
NUM_RE = re.compile(
    rf"(?i)\b(?:{_NUMWORD})(?:[ \-](?:{_NUMWORD}))*\b"
)

def collapse_numbers(text: str) -> str:
    """
    Replace each contiguous run of pure number-words with its digit equivalent,
    leaving all other words (like "Candles") intact.
    """
    def _repl(match):
        phrase = match.group(0)
        try:
            return str(w2n.word_to_num(phrase))
        except ValueError:
            return phrase  # fallback, shouldn’t happen

    return NUM_RE.sub(_repl, text)

def normalize_title(text: str) -> str:
    if not text:
        return ""
    text = text.replace("&", "and")
    # collapse spelled-out numbers
    text = collapse_numbers(text)
    # collapse Pt/Part → digits
    text = re.sub(r'(?i)\b(?:pt|part)[\.#]?\s*(\d+)\b', r'\1', text)
    # strip non-alphanumerics
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isalnum()).lower()

# ─── Cleanup Logic (per‐series) ────────────────────────────────────────────────

@with_conn
def cleanup_deleted(conn, sonarr_client: SonarrClient):
    """
    1) Fetch all series once.
    2) For each series, fetch episodes via GET /episode?seriesId=<id>.
    3) Build a Python set of all “live” keys.
    4) DELETE FROM episodes WHERE key NOT IN (<all_live_keys>).
    """
    cur = conn.cursor()

    # 1) Fetch all series from Sonarr:
    all_series = sonarr_client.get("series")
    if all_series is None:
        logging.error("❌ Failed to fetch series from Sonarr; aborting cleanup.")
        return

    # Build a seriesId → normalized_title map
    series_map = {}
    for s in all_series:
        sid = s.get("id")
        title = s.get("title", "")
        if sid is None:
            continue
        norm = normalize_title(title)
        series_map[sid] = norm

    # 2) For each series, fetch its episodes and accumulate keys
    live_keys = set()
    for sid, norm_title in series_map.items():
        params = {"seriesId": sid}
        eps = sonarr_client.get("episode", params=params)
        if eps is None:
            logging.warning(f"❌ Skipping seriesId={sid} (could not fetch episodes).")
            continue

        for ep in eps:
            season = ep.get("seasonNumber")
            epnum  = ep.get("episodeNumber")
            if season is None or epnum is None:
                continue
            key = f"series::{norm_title}::S{season:02d}E{epnum:02d}"
            live_keys.add(key)

    # 3) If no live keys found, delete everything
    if not live_keys:
        logging.info("🗑️ No episodes returned from Sonarr; purging all episodes.")
        cur.execute("DELETE FROM episodes;")
        conn.commit()
        cur.close()
        return

    # 4) Bulk delete any episodes not in live_keys
    placeholders = ",".join(["%s"] * len(live_keys))
    delete_sql = sql.SQL("""
        DELETE FROM episodes
         WHERE key NOT IN ({keys});
    """).format(keys=sql.SQL(placeholders))

    logging.info(f"🗑️ Deleting any episodes not in Sonarr (live count = {len(live_keys)})...")
    cur.execute(delete_sql, tuple(live_keys))
    conn.commit()
    cur.close()
    logging.info("✅ Cleanup complete.")

# ─── Entrypoint ───────────────────────────────────────────────────────────────

def main():
    try:
        sonarr = SonarrClient(SONARR_URL, SONARR_API_KEY, timeout=API_TIMEOUT)
    except Exception:
        logging.critical("❌ Couldn’t create Sonarr client", exc_info=True)
        sys.exit(1)

    try:
        logging.info("🔄 Starting cleanup pass (per‐series fallback)")
        cleanup_deleted(sonarr)
    except Exception:
        logging.critical("❌ cleanup_deleted() encountered an error", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
