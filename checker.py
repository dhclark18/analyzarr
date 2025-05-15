import os
import re
import requests
from pathlib import Path

SONARR_URL = os.environ.get("SONARR_URL")
SONARR_API_KEY = os.environ.get("SONARR_API_KEY")
AUTO_REDOWNLOAD = os.environ.get("AUTO_REDOWNLOAD", "false").lower() == "true"

HEADERS = {"X-Api-Key": SONARR_API_KEY}

EPISODE_PATTERN = re.compile(r"[Ss](\d{2})[Ee](\d{2})")
TVDB_ID_PATTERN = re.compile(r"\{tvdb-(\d+)\}")
TITLE_IN_FILENAME = re.compile(r"S\d{2}E\d{2} - (.+?) \[")  # Extract title between SxxExx - ... [

def get_series_by_tvdbid(tvdbid):
    url = f"{SONARR_URL}/series"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        for series in response.json():
            if str(series.get("tvdbId")) == str(tvdbid):
                return series
    except Exception as e:
        print(f"❌ Error fetching series: {e}")
    return None

def get_episode_title(series_id, season_number, episode_number):
    url = f"{SONARR_URL}/episode"
    params = {
        "seriesId": series_id,
        "seasonNumber": season_number,
        "episodeNumber": episode_number
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        episodes = resp.json()
        if isinstance(episodes, list) and episodes:
            return episodes[0].get("title"), episodes[0].get("id")
    except Exception as e:
        print(f"❌ Error fetching episode: {e}")
    return None, None

def trigger_redownload(episode_id, season, episode):
    try:
        res = requests.post(f"{SONARR_URL}/command", headers=HEADERS, json={
            "name": "EpisodeSearch",
            "episodeIds": [episode_id]
        })
        res.raise_for_status()
        print(f"🔄 Redownload triggered for S{season:02}E{episode:02}")
    except Exception as e:
        print(f"❌ Failed to trigger redownload: {e}")

def process_file(file_path):
    print(f"📺 Checking: {file_path}")
    filename = Path(file_path).name
    parent_folder = Path(file_path).parent.parent.name

    tvdb_id_match = TVDB_ID_PATTERN.search(parent_folder)
    episode_match = EPISODE_PATTERN.search(filename)
    title_match = TITLE_IN_FILENAME.search(filename)

    if not (tvdb_id_match and episode_match and title_match):
        print(f"⚠️ Skipping due to missing metadata: {file_path}")
        return

    tvdb_id = tvdb_id_match.group(1)
    season_number = int(episode_match.group(1))
    episode_number = int(episode_match.group(2))
    filename_title = title_match.group(1).strip()

    series = get_series_by_tvdbid(tvdb_id)
    if not series:
        print(f"⚠️ No matching series found in Sonarr for tvdb-{tvdb_id}")
        return

    expected_title, episode_id = get_episode_title(series["id"], season_number, episode_number)
    if not expected_title:
        print(f"⚠️ Could not find episode title in Sonarr for S{season_number:02}E{episode_number:02}")
        return

    if expected_title.lower() != filename_title.lower():
        print(f"❌ Title mismatch:\n   Sonarr: '{expected_title}'\n   File  : '{filename_title}'")
        if AUTO_REDOWNLOAD and episode_id:
            trigger_redownload(episode_id, season_number, episode_number)
        elif not AUTO_REDOWNLOAD:
            print("ℹ️ AUTO_REDOWNLOAD is off. Not triggering redownload.")
    else:
        print(f"✅ Title match: '{expected_title}'")

def walk_directory(watched_dir="/watched"):
    for root, _, files in os.walk(watched_dir):
        for name in files:
            if name.endswith(".mkv"):
                process_file(os.path.join(root, name))

if __name__ == "__main__":
    walk_directory()
