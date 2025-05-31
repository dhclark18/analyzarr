#!/usr/bin/env python3
"""

Features:
 - Pooled PostgreSQL connections (psycopg2 SimpleConnectionPool)
 - Modular SonarrClient with unified error handling, heavily based on Huntarr project
 - Reads mismatch counts from an external incrementer script
 - Tags episode as matched or porblematic
"""

import os
import sys
import re
import time
import logging
import unicodedata
from requests.exceptions import ReadTimeout, RequestException
import requests
from psycopg2.pool import SimpleConnectionPool
from rapidfuzz.fuzz import token_sort_ratio
from word2number import w2n

# -----------------------------------------------------------------------------
# CLI & Configuration
# -----------------------------------------------------------------------------

DATABASE_URL       = os.getenv("DATABASE_URL") or sys.exit("❌ DATABASE_URL not set")
SONARR_URL         = os.getenv("SONARR_URL", "http://localhost:8989")
SONARR_API_KEY     = os.getenv("SONARR_API_KEY") or sys.exit("❌ SONARR_API_KEY not set")
API_TIMEOUT        = int(os.getenv("API_TIMEOUT", "10"))
TVDB_FILTER        = os.getenv("TVDB_ID")
LOG_LEVEL          = os.getenv("LOG_LEVEL")
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
LOG_FILE = os.path.join(LOG_DIR, "analyzer.log")

# Read LOG_LEVEL from env (default to "INFO" if not set)
level_name = os.getenv("LOG_LEVEL", "INFO").upper()

# Convert the string name to an actual logging level (int), defaulting to INFO if unrecognized
numeric_level = getattr(logging, level_name, logging.INFO)

logging.basicConfig(
    level=numeric_level,
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
    cur = conn.cursor()

    # 1) episodes must exist before anything references it
    cur.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
          key            TEXT PRIMARY KEY,
          code           TEXT NOT NULL,
          series_title   TEXT NOT NULL,
          expected_title TEXT NOT NULL,
          actual_title   TEXT NOT NULL,
          confidence     TEXT NOT NULL
        );
    """)

    # 2) tags (no dependencies)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tags (
          id   SERIAL PRIMARY KEY,
          name TEXT UNIQUE NOT NULL
        );
    """)

    # 3) episode_tags references both episodes and tags
    cur.execute("""
        CREATE TABLE IF NOT EXISTS episode_tags (
          episode_key TEXT NOT NULL
            REFERENCES episodes(key) ON DELETE CASCADE,
          tag_id      INTEGER NOT NULL
            REFERENCES tags(id) ON DELETE CASCADE,
          PRIMARY KEY (episode_key, tag_id)
        );
    """)

    conn.commit()
    cur.close()

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

def ensure_tag(conn, tag_name: str) -> int:
    """
    Make sure a tag with name=tag_name exists in `tags`.
    Return its id (creating the row if needed).
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO tags (name)
            VALUES (%s)
            ON CONFLICT (name) DO NOTHING
            RETURNING id
        """, (tag_name,))
        row = cur.fetchone()
        if row:
            return row[0]

        # If it already existed, fetch its id
        cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
        return cur.fetchone()[0]

@with_conn
def add_tag(conn, episode_key: str, tag_name: str) -> bool:
    """
    Attach tag_name to episode_key.
    Returns True if a new episode_tags row was created.
    """
    tag_id = ensure_tag(conn, tag_name)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO episode_tags (episode_key, tag_id)
            VALUES (%s, %s)
            ON CONFLICT (episode_key, tag_id) DO NOTHING
        """, (episode_key, tag_id))
        inserted = cur.rowcount > 0

    conn.commit()
    return inserted

@with_conn
def remove_tag(conn, episode_key: str, tag_name: str) -> bool:
    """
    Remove the given tag from an episode.
    Returns True if a row was deleted, False otherwise.
    """
    with conn.cursor() as cur:
        # Attempt to delete via a sub‐select on tags.name
        cur.execute("""
            DELETE FROM episode_tags
             WHERE episode_key = %s
               AND tag_id = (
                   SELECT id FROM tags WHERE name = %s
               )
        """, (episode_key, tag_name))
        deleted = cur.rowcount > 0

    conn.commit()
    return deleted

@with_conn
def insert_episode(
    conn,
    key: str,
    series_title: str,
    code: str,
    expected_title: str,
    actual_title: str,
    confidence: float
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO episodes
              (key, series_title, code, expected_title, actual_title, confidence)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE
              SET actual_title   = EXCLUDED.actual_title,
                  confidence     = EXCLUDED.confidence
            """,
            (key, series_title, code, expected_title, actual_title, confidence)
        )
    conn.commit()
# -----------------------------------------------------------------------------
# Sonarr API Client
# -----------------------------------------------------------------------------

class SonarrClient:
    def __init__(self, base_url, api_key, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout
        self.session  = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "User-Agent": "analyzer"
        })

    def request(self, endpoint, method="GET", json_data=None):
        url = f"{self.base_url}/api/v3/{endpoint.lstrip('/')}"
        try:
            resp = self.session.request(
                method, url,
                json=json_data,
                timeout=self.timeout
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
# Special words to tell extract_scene_title that we have reached the end of the title (if any)
_raw_markers = os.getenv("END_MARKERS", 
    "1080p,720p,2160p,480p,"
    "remux,hdtv,"
    "dts,ddp51,ac3,vc1,x264,h264,hevc,"
    "nf,dsnp,btn,kenobi,asmofuscated"
)

# Split on commas, strip whitespace, and lowercase each token
END_MARKERS = {
    token.strip().lower()
    for token in _raw_markers.split(",")
    if token.strip()
}

def collapse_numbers(text: str) -> str:
    """
    Replace each contiguous run of pure number-words with its digit equivalent,
    leaving all other words intact.
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

def has_episode_numbers(title: str) -> bool:
    return bool(re.search(r'[sS]\d{1,2}[eE]\d{1,2}', title) or re.search(r'\d{1,2}x\d{1,2}', title))
 
def has_season_episode(scene_name: str) -> bool:
    return bool(re.search(r"(?i)[sS]\d{2}[eE]\d{2}", scene_name))
 
def is_missing_title(scene_name: str, expected_title: str) -> bool:
    """
    Return True if there was no real title between SxxEyy and the metadata,
    or if the only token is a numeric year/number that doesn’t match the expected or is just "Part X".
    """
    raw = extract_scene_title(scene_name).strip()
    expected_norm = normalize_title(expected_title)

    logging.debug(f"is_missing_title: raw extracted = {raw!r}, expected_norm = {expected_norm!r}")

    # 1) Nothing at all
    if not raw:
        return True

    # 2) Pure digits in the raw:
    if raw.isdigit():
        # 2a) expected is also digits and they match → not missing
        if expected_norm.isdigit() and raw == expected_norm:
            return False
        # 2b) otherwise → missing
        return True
    
    # 3) “PartX” (any casing) should also count as “missing”
    if re.match(r'(?i)^part\d+$', raw):
        return True

    # 4) Otherwise, assume there's a real title word
    return False

def compute_confidence(expected_title: str, scene_name: str) -> float:
    # 1) Normalize expected
    norm_expected = normalize_title(expected_title)

    # 2) Extract just the title portion from the scene file name
    raw_scene_title = extract_scene_title(scene_name)
    norm_extracted_scene = normalize_title(raw_scene_title)
    norm_scene = normalize_title(scene_name)

    logging.debug(f"Raw scene: {raw_scene_title!r}")
    logging.debug(f"Normalized expected: {norm_expected!r}")
    logging.debug(f"Normalized extracted scene  : {norm_extracted_scene!r}")
    logging.debug(f"Normalized scene  : {norm_scene!r}")
    logging.debug(f"Substring match?  : {norm_expected in norm_scene}")
    
    # ───── Substring override ─────
    # If the normalized expected title literally appears in the normalized scene title, 
    # it’s a perfect match.
    if norm_expected in norm_scene:
        return 1.0

    # 3) No SxxEyy → no confidence
    if not has_season_episode(scene_name):
        logging.debug(f"No SXXEXX format")
        return 0.0

    # 4) Season match but no title words → base for missing title
    if is_missing_title(scene_name, expected_title):
        logging.debug(f"Missing title")
        return 0.8

    # 5) Season match + title present → exponentially penalize mismatch
    #    e.g. base_conf=0.8, exponent=3
    title_score = token_sort_ratio(norm_expected, norm_extracted_scene) / 100.0
    base_conf   = 0.8
    exp         = 1
    conf = base_conf * (title_score ** exp)
    logging.debug(f"Score  : {conf}")
    return round(conf, 2)

def extract_scene_title(scene_name: str) -> str:
    """
    Splits on dots/hyphens/underscores/whitespace, finds the SxxEyy token,
    then returns the tokens after it up until a known marker.

    *New:* First, collapse any "Season <num> Ep <num>" (in any case/spacing)
      into the single phrase "Episode <num>" so it normalizes correctly.
    """
    # ── Step 0: collapse "Season X Ep Y" into "Episode Y" ───────────────────
    # This handles things like "Season.11.Ep.13" or "season11ep13".
    # The pattern is case‐insensitive:
    scene_name = re.sub(
        r"(?i)\bSeason[.\s-_]*\d+[.\s-_]*Ep[.\s-_]*(\d+)\b",
        r"Episode \1",
        scene_name
    )

    # ── Step 1: split on ., -, _, or whitespace ─────────────────────────────
    tokens = re.split(r"[.\-_\s]+", scene_name)

    # ── Step 2: find the SxxEyy token ──────────────────────────────────────
    for i, tok in enumerate(tokens):
        if re.match(r"(?i)^S\d{2}E\d{2}$", tok):
            # ── Step 3: collect everything after SxxEyy until a known marker ─
            title_parts = []
            for w in tokens[i+1:]:
                low = w.lower()
                # stop on resolution or any end‐marker (e.g. "720p", "bluray", etc.)
                if low in END_MARKERS or re.match(r"^\d{3,4}p$", low):
                    break

                # accept TitleCase (first letter uppercase, rest lowercase)
                if not (len(w) > 1 and w[0].isupper() and w[1:].islower()):
                    continue

                title_parts.append(w)

            # ── Step 4: re‐join with spaces and return ────────────────────────
            return " ".join(title_parts)

    # Fallback: if no SxxEyy found, just replace separators with spaces
    return re.sub(r"[.\-_]+", " ", scene_name)
 
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
        parsed_season = ep["seasonNumber"]
        parsed_epnum  = ep["episodeNumber"]

    key  = f"series::{normalize_title(series['title'])}::S{parsed_season:02d}E{parsed_epnum:02d}"
    code = f"S{parsed_season:02d}E{parsed_epnum:02d}"
    nice = series["title"]

    expected_title = ep["title"]
    expected_norm = normalize_title(expected_title)
    actual_norm   = normalize_title(scene)

    logging.info(f"\n📺 {nice} {code}")
    logging.info(f"🎯 Expected: {ep['title']}")
    logging.info(f"🎞️ Scene:    {scene}")
    logging.debug(f"Normalized expected (main): {expected_norm!r}")
    logging.debug(f"Normalized scene (main)  : {actual_norm!r}")
    logging.debug(f"Substring match? (main)  : {expected_norm in actual_norm}")
    
    confidence = compute_confidence(expected_title, scene)
    
    insert_episode(
        key, nice, code, expected_title, scene, confidence
    )

    # On match: check for and add matched tag
    if confidence >= 0.5:
        if add_tag(key, "matched"):
            remove_tag(key, "problematic-episode")
            logging.info(f"✅ Tagged {nice} {code} as matched")
        else:
            logging.info(f"✅ ‘matched’ tag already present for {nice} {code}")
        return

    # On mismatch
    if confidence < 0.5:
        if add_tag(key, "problematic-episode"):
            remove_tag(key, "matched")
            logging.info(f"⏩ Tagging mismatched")
        else:
            logging.info(f"⏩ Already tagged {nice} {code}; skipping")
        return


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
# Entrypoint
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        init_db()
        sonarr = SonarrClient(SONARR_URL, SONARR_API_KEY, timeout=API_TIMEOUT)
        scan_library(sonarr)
    except Exception:
        logging.critical("💥 Unhandled exception, shutting down", exc_info=True)
        sys.exit(1)
