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

# --- Helpers ---
def normalize_title(title):
    if not title:
        return ""
    title = title.replace("&", "and")
    title = unicodedata.normalize("NFKD", title)
    return "".join(c for c in title if c.isalnum()).lower()

def extract_title_from_filename(name):
    match = re.search(r"S\d{2}E\d{2} - (.+?) \[", name)
    return match.group(1) if match else ""

def extract_episode_title(scene_name):
    match = re.search(r'[sS]\d{2}[eE]\d{2}((?:\.[^.]+)+)', scene_name)
    if not match:
        return None

    title_part = match.group(1)

    stopwords = [
        # Resolutions
        '240p', '360p', '480p', '540p', '720p', '1080p', '1440p', '2160p', '4320p',
        '4K', '8K',

        # Streaming services
        'NF', 'AMZN', 'HMAX', 'DSNP', 'ATVP', 'iT', 'iTunes', 'HULU', 'ParamountPlus', 'Peacock', 'MAX',

        # Quality/source
        'WEB', 'WEBRip', 'WEB-DL', 'BluRay', 'HDTV', 'DVDRip', 'CAM', 'TS', 'DVDScr',

        # Codecs/audio
        'H264', 'H265', 'x264', 'x265', 'XviD', 'DivX',
        'DD2.0', 'DD5.1', 'DDP5.1', 'AAC', 'MP3', 'FLAC',
        'TRUEHD', 'DTS', 'Atmos', 'EAC3',

        # Scene tags
        'REPACK', 'PROPER', 'EXTENDED', 'INTERNAL', 'REMUX', 'LIMITED', 'UNRATED', 'MULTi',

        # Group naming extras
        'RARBG', 'FGT', 'NTG', 'XEBEC', 'mSD', 'YIFY', 'PSA', 'ION10'
    ]

    parts = title_part.strip('.').split('.')
    title_words = []
    for word in parts:
        if word.upper() in (w.upper() for w in stopwords):
            break
        title_words.append(word)

    return ' '.join(title_words).strip()

# --- API ---
def get_series_list():
    resp = requests.get(f"{SONARR_URL}/api/v3/series", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

def get_episodes(series_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/episode?seriesId={series_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

def get_episode_file(file_id):
    resp = requests.get(f"{SONARR_URL}/api/v3/episodefile/{file_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

# --- Main Checker ---
def check_episode(series, episode):
    if not episode.get("hasFile") or not episode.get("episodeFileId"):
        return

    try:
        epfile = get_episode_file(episode["episodeFileId"])
    except Exception as e:
        logging.error(f"Failed to get file for {series['title']} S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}: {e}")
        return

    expected_title = episode.get("title")
    filename = Path(epfile.get("relativePath", "")).name
    scene_name = epfile.get("sceneName")

    file_title = extract_title_from_filename(filename)
    scene_title = extract_title_from_scene_name(scene_name or "")

    nf, ne, ns = map(normalize_title, [file_title, expected_title, scene_title])

    episode_code = f"S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}"
    logging.info(f"\n📺 {series['title']} {episode_code}")
    logging.info(f"🎯 Expected title : {expected_title}")
    logging.info(f"📁 File title     : {file_title}")
    logging.info(f"🎞️  Scene title    : {scene_title or '[unknown]'}")

    if nf != ne:
        logging.error("❌ File title does NOT match expected title.")
    else:
        logging.info("✅ File title matches expected title.")

    if scene_title:
        if ns != ne:
            logging.error("❌ Scene title does NOT match expected title.")
        else:
            logging.info("✅ Scene title matches expected title.")

# --- Entry Point ---
def scan_library():
    if not SONARR_API_KEY:
        logging.error("❌ SONARR_API_KEY environment variable is not set.")
        return

    try:
        all_series = get_series_list()
        for series in all_series:
            logging.info(f"\n=== Scanning: {series['title']} ===")
            episodes = get_episodes(series["id"])
            for episode in episodes:
                check_episode(series, episode)
    except Exception as e:
        logging.error(f"Library scan failed: {e}")

if __name__ == "__main__":
    scan_library()
