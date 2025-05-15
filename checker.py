import os
import re
import json
import requests
from pathlib import Path

SONARR_URL = os.environ.get("SONARR_URL")  # e.g., http://sonarr.local:8989/api/v3
SONARR_API_KEY = os.environ.get("SONARR_API_KEY")
AUTO_REDOWNLOAD = os.environ.get("AUTO_REDOWNLOAD", "false").lower() == "true"

HEADERS = {"X-Api-Key": SONARR_API_KEY}

EPISODE_PATTERN = re.compile(r"[Ss](\d+)[Ee](\d+)")
TVDB_ID_PATTERN = re.compile(r"\{tvdb-(\d+)\}")

def get_series_by_tvdbid(tvdbid):
    url = f"{SONARR_URL}/series"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        series_list = response.json()
        for series in series_list:
            if str(series.get("tvdbId")) == str(tvdbid):
                return series
    except Exception as e:
        print(f"❌ Error fetching series: {e}")
    return None
    
def get_episode_title(series_id, season_number, episode_number):
    url = f"{SONARR_URL}/episode"
    params = {
        "seriesId": series_id,           # Must be an integer ID like 123
        "seasonNumber": season_number,
        "episodeNumber": episode_number
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        episodes = resp.json()
        if isinstance(episodes, list) and episodes:
            return episodes[0].get("title")
    except Exception as e:
        print(f"❌ Error fetching episode: {e}")
    return None
    
def process_file(file_path):
    print(f"📺 Checking: {file_path}")
    filename = Path(file_path).name
    parent_folder = Path(file_path).parent.parent.name  # should contain the tvdb ID

    tvdb_id_match = TVDB_ID_PATTERN.search(parent_folder)
    episode_match = EPISODE_PATTERN.search(filename)

    if not tvdb_id_match or not episode_match:
        print(f"⚠️ Skipping due to missing metadata: {file_path}")
        return

    tvdb_id = tvdb_id_match.group(1)
    season_number = int(episode_match.group(1))
    episode_number = int(episode_match.group(2))

    series = get_series_by_tvdbid(tvdb_id)
    if not series:
        print(f"⚠️ No matching series found in Sonarr for tvdb-{tvdb_id}")
        return

    expected_title = get_episode_title(series, season_number, episode_number)
    if not expected_title:
        print(f"⚠️ Could not find episode title in Sonarr for S{season_number:02d}E{episode_number:02d}")
        return

    expected_title_normalized = re.sub(r"\W+", "", expected_title).lower()
    filename_normalized = re.sub(r"\W+", "", filename).lower()

    if expected_title_normalized in filename_normalized:
        print(f"✅ Title match: {expected_title}")
    else:
        print(f"❌ Title mismatch. Expected: {expected_title}")
        if AUTO_REDOWNLOAD:
            print("♻️ Triggering redownload via Sonarr...")
            try:
                ep_id = next(ep["id"] for ep in requests.get(f"{SONARR_URL}/episode", headers=HEADERS).json()
                             if ep["seriesId"] == series["id"]
                             and ep["seasonNumber"] == season_number
                             and ep["episodeNumber"] == episode_number)
                res = requests.post(f"{SONARR_URL}/command", headers=HEADERS, json={
                    "name": "EpisodeSearch",
                    "episodeIds": [ep_id]
                })
                res.raise_for_status()
                print("🚀 Redownload triggered.")
            except Exception as e:
                print(f"❌ Failed to trigger redownload: {e}")

def walk_directory(watched_dir="/watched"):
    for root, _, files in os.walk(watched_dir):
        for name in files:
            if name.endswith(".mkv"):
                process_file(os.path.join(root, name))

if __name__ == "__main__":
    walk_directory()
