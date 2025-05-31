#!/usr/bin/env python3
"""
cleanup.py

Standalone cleanup script that removes any episode rows from Postgres when:
  • Sonarr no longer returns them at all, OR
  • Sonarr returns them but `hasFile=False`.

We reuse the SonarrClient from analyzer.py, so all HTTP logic is shared.
"""

import os
import sys
import logging
import unicodedata
import re

from psycopg2.pool import SimpleConnectionPool
from psycopg2 import sql

# ─── Import the shared SonarrClient from analyzer.py ─────────────────────────
# Make sure analyzer.py is in the same directory (or on PYTHONPATH).
from analyzer import SonarrClient

# ─── Configuration ───────────────────────────────────────────────────────────
DATABASE_URL   = os.getenv("DATABASE_URL") or sys.exit("❌ DATABASE_URL not set")
SONARR_URL     = os.getenv("SONARR_URL", "http://localhost:8989").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY") or sys.exit("❌ SONARR_API_KEY not set")
API_TIMEOUT    = int(os.getenv("API_TIMEOUT", "10"))

# ─── Logging Setup ───────────────────────────────────────────────────────────
LOG_DIR = os.getenv("LOG_PATH", "/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "cleanup.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
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

# ─── Utility: Normalize Series Titles ─────────────────────────────────────────
def normalize_title(text: str) -> str:
    """
    Lowercase, strip non-alphanumerics to normalize a series title.
    """
    if not text:
        return ""
    text = text.replace("&", "and")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isalnum()).lower()

# End‐of‐title markers (lowercase) used for extraction logic (if needed)
END_MARKERS = {
    "1080p", "720p", "2160p", "480p",
    "remux","bluray","web-dl","webrip","hdrip","hdtv",
    "dts","ddp51","ac3","vc1","x264","h264","hevc",
    "amzn","nf","max","dsnp","btn","kenobi","asmofuscated"
}

def extract_scene_title(scene_name: str) -> str:
    """
    Collapse “Season X Ep Y” → “Episode Y”, then split on separators,
    find SxxEyy, and collect title‐tokens (TitleCase or digits) until an end‐marker.
    """
    # 1) Collapse "Season <digits> Ep <digits>" → "Episode <digits>"
    scene_name = re.sub(
        r"(?i)\bSeason[.\s_-]*\d+[.\s_-]*Ep[.\s_-]*(\d+)\b",
        r"Episode \1",
        scene_name
    )

    # 2) Split on ., -, _, or whitespace
    tokens = re.split(r"[.\-_\s]+", scene_name)

    # 3) Find the SxxEyy token
    for i, tok in enumerate(tokens):
        if re.match(r"(?i)^S\d{2}E\d{2}$", tok):
            title_parts = []
            # 4) Collect tokens after SxxEyy until a marker
            for w in tokens[i+1:]:
                low = w.lower()
                # Stop on resolution or any end‐marker
                if low in END_MARKERS or re.match(r"^\d{3,4}p$", low):
                    break

                # Accept TitleCase (e.g. "Episode") or pure digits (e.g. "13")
                if (len(w) > 1 and w[0].isupper() and w[1:].islower()) or w.isdigit():
                    title_parts.append(w)
                    continue

            # 5) Join with spaces and return
            return " ".join(title_parts)

    # Fallback: return entire name with separators replaced by spaces
    return re.sub(r"[.\-_]+", " ", scene_name)

# ─── Cleanup Logic (uses SonarrClient from analyzer) ─────────────────────────
@with_conn
def cleanup_deleted(conn, sonarr_client: SonarrClient):
    """
    1) Fetch all series from Sonarr (GET /series).
    2) For each series, fetch its episodes (GET /episode?seriesId=<id>).
         Only keep episodes where hasFile == True (and episodeFileId exists).
    3) Build a Python set of all “live” keys: "series::<normalized_title>::SxxExx".
    4) DELETE FROM episodes WHERE key NOT IN (live_keys).
    """
    cur = conn.cursor()

    # 1) Fetch all series from Sonarr:
    all_series = sonarr_client.get("series")
    if all_series is None:
        logging.error("❌ Failed to fetch series from Sonarr; aborting cleanup.")
        return

    # Build a map: { seriesId: normalized_series_title, … }
    series_map = {}
    for s in all_series:
        sid = s.get("id")
        title = s.get("title", "")
        if sid is None:
            continue
        series_map[sid] = normalize_title(title)

    # 2) For each series, fetch episodes and only keep hasFile=True
    live_keys = set()
    for sid, norm_title in series_map.items():
        # Instead of sonarr_client.get("episode", params={"seriesId": sid}),
        # we embed the querystring directly in the endpoint:
        eps = sonarr_client.get(f"episode?seriesId={sid}") or []
        if eps is None:
            logging.warning(f"❌ Skipping seriesId={sid} (could not fetch episodes).")
            continue

        for ep in eps:
            # Skip any episode without a file
            if not ep.get("hasFile") or not ep.get("episodeFileId"):
                continue
            season = ep.get("seasonNumber")
            epnum  = ep.get("episodeNumber")
            if season is None or epnum is None:
                continue
            key = f"series::{norm_title}::S{season:02d}E{epnum:02d}"
            live_keys.add(key)

    # 3) Optional debug: list DB keys that are not in live_keys
    cur.execute("SELECT key FROM episodes;")
    db_keys = {row[0] for row in cur.fetchall()}
    to_delete = db_keys - live_keys
    if to_delete:
        logging.info("Keys in DB but no corresponding file in Sonarr (to be deleted):")
        for k in sorted(to_delete):
            logging.info("   ✂️  %s", k)
    else:
        logging.info("No orphaned keys found; DB is in sync.")

    # 4) Bulk‐delete any episodes not in live_keys
    if not live_keys:
        logging.info("🗑️ No keepable episodes found—purging entire episodes table.")
        cur.execute("DELETE FROM episodes;")
        conn.commit()
        cur.close()
        return

    placeholders = ",".join(["%s"] * len(live_keys))
    delete_sql = sql.SQL("""
        DELETE FROM episodes
         WHERE key NOT IN ({keys});
    """).format(keys=sql.SQL(placeholders))

    logging.info(f"🗑️ Deleting {len(to_delete)} orphaned rows …")
    cur.execute(delete_sql, tuple(live_keys))
    conn.commit()
    cur.close()
    logging.info("✅ Cleanup complete.")

# ─── Entrypoint ───────────────────────────────────────────────────────────────
def main():
    try:
        sonarr_client = SonarrClient(SONARR_URL, SONARR_API_KEY, timeout=API_TIMEOUT)
    except Exception:
        logging.critical("❌ Couldn’t create Sonarr client", exc_info=True)
        sys.exit(1)

    try:
        logging.info("🔄 Running cleanup (filtering out any episodes with hasFile=False)")
        cleanup_deleted(sonarr_client)
    except Exception:
        logging.critical("❌ cleanup_deleted() encountered an error", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
