#!/usr/bin/env python3
"""

Features:
 - Pooled PostgreSQL connections (psycopg2 SimpleConnectionPool)
 - Modular SonarrClient with unified error handling, heavily based on Huntarr project
 - Reads mismatch counts from an external incrementer script
 - Tags episode as matched or problematic
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
import psycopg2.extras
from guessit import guessit
import argparse

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
          key               TEXT    PRIMARY KEY,
          code              TEXT    NOT NULL,
          series_title      TEXT    NOT NULL,
          expected_title    TEXT    NOT NULL,
          actual_title      TEXT    NOT NULL,
          confidence        REAL    NOT NULL DEFAULT 0.0,
          norm_scene        TEXT    NOT NULL DEFAULT '',
          norm_expected     TEXT    NOT NULL DEFAULT '',
          norm_extracted    TEXT    NOT NULL DEFAULT '',
          substring_override BOOLEAN NOT NULL DEFAULT FALSE,
          missing_title     BOOLEAN NOT NULL DEFAULT FALSE,
          series_id         INTEGER NOT NULL,
          episode_id        INTEGER NOT NULL,
          release_group     TEXT    NOT NULL DEFAULT '',
          media_info        JSONB   NOT NULL DEFAULT '{}'::jsonb
        );
    """)

    # 2) tags (no dependencies)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tags (
          id   SERIAL PRIMARY KEY,
          name TEXT   UNIQUE NOT NULL
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
    confidence: float,
    norm_scene: str,
    norm_expected: str,
    norm_extracted: str,
    substring_override: bool,
    missing_title: bool,
    series_id: int,
    episode_id: int,
    release_group: str,
    media_info: dict
):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO episodes (
                key,
                series_title,
                code,
                expected_title,
                actual_title,
                confidence,
                norm_scene,
                norm_expected,
                norm_extracted,
                substring_override,
                missing_title,
                series_id,
                episode_id,
                release_group,
                media_info
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (key) DO UPDATE SET
                actual_title       = EXCLUDED.actual_title,
                confidence         = EXCLUDED.confidence,
                norm_scene         = EXCLUDED.norm_scene,
                norm_expected      = EXCLUDED.norm_expected,
                norm_extracted     = EXCLUDED.norm_extracted,
                substring_override = EXCLUDED.substring_override,
                missing_title      = EXCLUDED.missing_title,
                series_id          = EXCLUDED.series_id,
                episode_id         = EXCLUDED.episode_id,
                release_group      = EXCLUDED.release_group,
                media_info         = EXCLUDED.media_info;
        """, (
            key,
            series_title,
            code,
            expected_title,
            actual_title,
            confidence,
            norm_scene,
            norm_expected,
            norm_extracted,
            substring_override,
            missing_title,
            series_id,
            episode_id,
            release_group,
            psycopg2.extras.Json(media_info)
        ))
    conn.commit()

@with_conn 
def has_override_tag(conn, key: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM episode_tags et
            JOIN tags t ON et.tag_id = t.id
            WHERE et.episode_key = %s AND t.name = 'override'
        """, (key,))
        return cur.fetchone() is not None  
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

# Matches:
#  • S01E02 or s1e2       (1–2 digits for both)
#  • 1x02 or 01x2         (1–2 digits for both, case-insensitive)
#  • Season 1 Episode 2   (any spacing, case-insensitive)
_HAS_EPISODE_RE = re.compile(
    r'(?i)(?:'
      r'S\d{1,2}E\d{1,2}'           # S01E02
      r'|\d{1,2}x\d{1,2}'           # 1x02
      r'|\bSeason\s*\d+\s*Episode\s*\d+\b'  # Season 1 Episode 2
    r')'
)

def has_season_episode(scene_name: str) -> bool:
    """
    Return True if the scene_name contains any recognized season/episode marker:
      - SxxEyy
      - MxN
      - Season <num> Episode <num>
    """
    return bool(_HAS_EPISODE_RE.search(scene_name))
 
def is_missing_title(scene_name: str) -> bool:
    """True if extract_scene_title returns no episode title."""
    return not bool(extract_scene_title(scene_name))

def compute_confidence(expected_title: str, scene_name: str) -> float:
    # 1) Normalize expected
    norm_expected = normalize_title(expected_title)

    # 2) Extract just the title portion from the scene file name
    raw_scene_title = extract_scene_title(scene_name)
    norm_extracted_scene = normalize_title(raw_scene_title)
    
    # 3) However use the entire normalized scene name to do the comparison for perfect matches   
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
    if is_missing_title(scene_name):
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
    Use guessit to pull out the *episode* title (not the show title).
    """
    info = guessit(scene_name, {"type": "episode"})
    # 'episode_title' holds things like "The Son Also Draws"
    return (info.get("episode_title") or "").strip()
 
def delete_episode_file(client: SonarrClient, file_id: int):
    """
    Delete the given episode file, with extended timeout and post-delete verification.
    """
    url = f"{client.base_url}/api/v3/episodefile/{file_id}"
    # we’ll use a tuple (connect_timeout, read_timeout)
    timeout = (client.timeout, client.timeout * 3)

    try:
        resp = client.session.delete(url, timeout=timeout)
        resp.raise_for_status()
        logging.info(f"🗑️ Deleted episode file ID {file_id}")
    except ReadTimeout:
        logging.warning(f"⌛ Timeout deleting file ID {file_id}; verifying deletion…")
        try:
            check = client.session.get(url, timeout=(client.timeout, client.timeout))
            if check.status_code == 404:
                logging.info(f"✅ Deletion of file ID {file_id} confirmed after timeout")
            else:
                logging.error(f"❌ File ID {file_id} still present (status {check.status_code})")
        except RequestException as e:
            logging.error(f"❌ Error verifying deletion of {file_id}: {e}")
    except RequestException as e:
        logging.exception(f"❌ Failed to delete file ID {file_id}: {e}")
     
def grab_best_nzb(client: SonarrClient, series_id: int, episode_id: int, wait: int = 5, confidence_threshold: float = 0.6):
    """
    1) Run EpisodeSearch in Sonarr to refresh indexer results.
    2) Fetch top 25 releases for this episode.
    3) Compute confidence against the expected title.
    4) Keep only those exceeding a confidence threshold.
    5) Among those, pick the one with the highest customFormatScore.
    6) Delete any existing file for this episode.
    7) Push the selected release back to Sonarr.
    """
    import time

    append = logging.info

    # Step 1: trigger Sonarr search
    cmd = client.post("command", {"name": "EpisodeSearch", "episodeIds": [episode_id]})
    if not cmd or "id" not in cmd:
        append("❌ Failed to start EpisodeSearch command")
        return

    append(f"🔍 EpisodeSearch started (id={cmd['id']}) for episode {episode_id}")
    time.sleep(wait)

    # Step 2: get candidate releases
    releases = client.get(f"release?episodeId={episode_id}") or []
    candidates = [r for r in releases if r.get("mappedSeriesId") == series_id]
    if not candidates:
        append("⚠️ No releases found for this episode")
        return

    # Step 3: sort and take top 25
    candidates.sort(key=lambda r: r.get("customFormatScore", 0), reverse=True)
    top_candidates = candidates[:25]
    append(f"📦 Evaluating {len(top_candidates)} candidates by confidence and score")

    # Step 4: get expected title
    ep_details = client.get(f"episode/{episode_id}") or {}
    expected_title = ep_details.get("title", "")
    if not expected_title:
        append(f"❌ Could not fetch expected title for episode {episode_id}")
        return

    # Compute confidence for each
    scored = []
    for r in top_candidates:
        title = r.get("title", "")
        conf = compute_confidence(expected_title, title)
        r["_confidence"] = conf
        scored.append(r)
        append(f"🔹 '{title[:80]}' → confidence {conf:.2f}, score {r.get('customFormatScore',0)}")

    # Step 5: filter by threshold and pick best by customFormatScore
    valid = [r for r in scored if r["_confidence"] >= confidence_threshold]
    if not valid:
        append(f"⚠️ No candidate exceeded confidence threshold {confidence_threshold}")
        valid = scored  # fallback to all if nothing passes

    valid.sort(key=lambda r: (r["_confidence"], r.get("customFormatScore", 0)), reverse=True)
    best = valid[0]
    best_title = best.get("title")
    best_conf = best.get("_confidence")
    best_score = best.get("customFormatScore")

    append(f"🏆 Selected '{best_title}' (confidence={best_conf:.2f}, score={best_score})")

    # Step 6: delete existing episode file
    ep = client.get(f"episode/{episode_id}") or {}
    file_id = ep.get("episodeFileId")
    if file_id:
        try:
            delete_episode_file(client, file_id)
        except Exception:
            logging.exception(f"Failed to delete existing file {file_id}")

    # Step 7: push chosen release
    dl_url = best.get("downloadUrl")
    if not dl_url:
        append("❌ Selected candidate has no download URL")
        return

    payload = {
        "title": best_title,
        "downloadUrl": dl_url,
        "protocol": best.get("protocol"),
        "publishDate": best.get("publishDate"),
    }
    result = client.post("release/push", payload)
    if result is not None:
        append(f"⬇️ Queued '{best_title}' for download via Sonarr (confidence {best_conf:.2f})")
    else:
        append("❌ Failed to push NZB into Sonarr")
   
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
    parsed_season = ep["seasonNumber"]
    parsed_epnum  = ep["episodeNumber"]

    key  = f"series::{normalize_title(series['title'])}::S{parsed_season:02d}E{parsed_epnum:02d}"
    code = f"S{parsed_season:02d}E{parsed_epnum:02d}"
    nice = series["title"]
    
    # 1) Normalize expected
    expected_title = ep["title"]
    norm_expected = normalize_title(expected_title)

    # 2) Extract just the title portion from the scene file name
    raw_scene_title = extract_scene_title(scene)
    norm_extracted = normalize_title(raw_scene_title)

    norm_scene = normalize_title(scene)
    substring_override = (norm_expected in norm_extracted)
    missing_title      = is_missing_title(scene)
    
    release_group = epfile.get("releaseGroup", "")
    media_info    = epfile.get("mediaInfo", {}) 
    
    logging.info(f"\n📺 {nice} {code}")
    logging.info(f"🎯 Expected: {ep['title']}")
    logging.info(f"🎞️ Scene:    {scene}")

    # Skip matching logic if episode has override tag 
    if has_override_tag(key):
        logger.info(f"🛑 Skipping {key} — manually overridden")
        return
     
    confidence = compute_confidence(expected_title, scene)
    
    insert_episode(
        key, nice, code, expected_title, scene, confidence, norm_scene, norm_expected, norm_extracted, substring_override, missing_title, series["id"], ep["id"], release_group, media_info
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


def scan_library(client: SonarrClient, series_id: int = None, season: int = None):
    """
    If series_id is provided, only scan that show.
    If season is provided, restrict to that season.
    Otherwise, scan the entire Sonarr library.
    """
    series_list = []
    if series_id:
        series = client.get(f"series/{series_id}")
        if not series:
            logging.error(f"❌ No series found for ID {series_id}")
            return
        series_list = [series]
    else:
        series_list = client.get("series") or []

    for series in series_list:
        if TVDB_FILTER and str(series.get("tvdbId")) != TVDB_FILTER:
            continue

        logging.info(f"\n=== Scanning {series['title']} ===")

        episodes = client.get(f"episode?seriesId={series['id']}") or []

        for ep in episodes:
            # apply filters if needed
            if season and ep["seasonNumber"] != season:
                continue
            if SEASON_FILTER and ep["seasonNumber"] not in SEASON_FILTER:
                continue

            try:
                check_episode(client, series, ep)
            except Exception:
                logging.exception(f"Fatal error checking {series['title']} ep {ep.get('id')}")


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Analyze Sonarr library or a single show/season")
    parser.add_argument("--series-id", type=int, help="Sonarr series ID to scan")
    parser.add_argument("--season", type=int, help="Season number to scan (optional)")
    return parser.parse_args()
 
if __name__ == "__main__":
    try:
        args = parse_args()
        init_db()
        sonarr = SonarrClient(SONARR_URL, SONARR_API_KEY, timeout=API_TIMEOUT)
        scan_library(sonarr, series_id=args.series_id, season=args.season)
    except Exception:
        logging.critical("💥 Unhandled exception, shutting down", exc_info=True)
        sys.exit(1)
