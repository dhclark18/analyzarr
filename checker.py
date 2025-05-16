import os
import re
import requests
from pathlib import Path
import unicodedata
import logging

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
HEADERS = {"X-Api-Key": SONARR_API_KEY}

# --- Normalization ---
def normalize_title(title):
    if not title:
        return ""
    title = title.replace("&", "and")
    title = unicodedata.normalize("NFKD", title)
    return "".join(c for c in title if c.isalnum()).lower()

# --- API ---
def get_series_by_tvdbid(tvdb_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/series", headers=HEADERS)
    resp.raise_for_status()
    for series in resp.json():
        if series.get("tvdbId") == int(tvdb_id):
            return series
    return None

def get_episode(series_id, season, episode):
    resp = requests.get(f"{SONARR_URL}/api/v3/episode?seriesId={series_id}", headers=HEADERS)
    resp.raise_for_status()
    for ep in resp.json():
        if ep["seasonNumber"] == season and ep["episodeNumber"] == episode:
            return ep
    return None

def get_episode_file(episode_file_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/episodefile/{episode_file_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

# --- Title extraction ---
def extract_title_from_filename(name):
    match = re.search(r"S\d{2}E\d{2} - (.+?) \[", name)
    return match.group(1) if match else ""

def extract_title_from_scene_name(scene_name):
    match = re.search(
        r"S\d{2}E\d{2}\.([^.]+(?:\.[^.]+)*?)\.(?:\d{3,4}x\d{3,4}|\[|WEB|HDTV|NF|AMZN|DSNP|DD|DDP|x264|h264|h265|HEVC|AAC|EAC3|-)",
        scene_name,
        re.IGNORECASE
    )
    if match:
        return match.group(1).replace(".", " ").strip()
    return ""

# --- Main Logic ---
def compare_titles(tvdb_id, season, episode):
    series = get_series_by_tvdbid(tvdb_id)
    if not series:
        logging.error(f"Series with tvdbId {tvdb_id} not found.")
        return

    episode_info = get_episode(series["id"], season, episode)
    if not episode_info:
        logging.error(f"Episode S{season:02}E{episode:02} not found.")
        return

    if not episode_info.get("hasFile"):
        logging.warning(f"Episode S{season:02}E{episode:02} has no file.")
        return

    episode_file = get_episode_file(episode_info["episodeFileId"])
    scene_name = episode_file.get("sceneName")
    relative_path = Path(episode_file.get("relativePath", "")).name
    expected_title = episode_info.get("title")

    title_from_filename = extract_title_from_filename(relative_path)
    title_from_scene = extract_title_from_scene_name(scene_name or "")

    logging.info(f"\n📺 {series['title']} S{season:02}E{episode:02}")
    logging.info(f"🎯 Expected title : {expected_title}")
    logging.info(f"📁 File title     : {title_from_filename}")
    logging.info(f"🎞️  Scene title    : {title_from_scene or '[unknown]'}")

    nf, ne, ns = map(normalize_title, [title_from_filename, expected_title, title_from_scene])

    if nf != ne:
        logging.error("File title does NOT match expected title.")
    else:
        logging.info("File title matches expected title.")

    if ns and ns != ne:
        logging.error("Scene title does NOT match expected title.")
    elif ns:
        logging.info("Scene title matches expected title.")

# --- Entry Point ---
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        print("Usage: python checker.py <tvdbId> <season> <episode>")
        sys.exit(1)

    if not SONARR_API_KEY:
        logging.error("SONARR_API_KEY environment variable is not set.")
        sys.exit(1)

    tvdb_id = int(sys.argv[1])
    season = int(sys.argv[2])
    episode = int(sys.argv[3])

    compare_titles(tvdb_id, season, episode)
