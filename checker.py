import os
import re
import requests
import time

WATCHED_DIR = "/watched"
API_KEY = os.getenv("TVDB_API_KEY")
USER_TOKEN = os.getenv("TVDB_USER_TOKEN")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

BASE_URL = "https://api4.thetvdb.com/v4"
TOKEN_CACHE = {"token": None, "expires": 0}

def get_token():
    if TOKEN_CACHE["token"] and TOKEN_CACHE["expires"] > time.time():
        return TOKEN_CACHE["token"]

    print("🔐 Requesting new TVDB token...")
    headers = {"Content-Type": "application/json"}
    data = {"apikey": API_KEY, "user_token": USER_TOKEN}
    response = requests.post(f"{BASE_URL}/login", json=data, headers=headers)
    response.raise_for_status()
    token = response.json()["data"]["token"]
    TOKEN_CACHE["token"] = token
    TOKEN_CACHE["expires"] = time.time() + 86400
    return token

def get_episode_title(show_id, season_num, episode_num):
    headers = {"Authorization": f"Bearer {get_token()}"}
    url = f"{BASE_URL}/series/{show_id}/episodes/default/{season_num}/{episode_num}"
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return None
    return response.json()["data"]["name"]

def extract_info_from_filename(filename):
    match = re.search(r"S(\d{2})E(\d{2})\s*-\s*(.*?)\s*(\[|$)", filename, re.IGNORECASE)
    if not match:
        return None
    season = int(match.group(1))
    episode = int(match.group(2))
    title_part = match.group(3)
    return season, episode, title_part

def check_files():
    print(f"📁 Scanning directory: {WATCHED_DIR}")
    mismatched_count = 0
    matched_count = 0

    for root, _, files in os.walk(WATCHED_DIR):
        for file in files:
            if not file.lower().endswith((".mkv", ".mp4", ".avi")):
                continue
            full_path = os.path.join(root, file)
            print(f"📺 Running checker on: {full_path}")

            season_episode_info = extract_info_from_filename(file)
            if not season_episode_info:
                print("⚠️ Skipped (no SxxExx match):", file)
                continue

            season, episode, filename_title = season_episode_info
            parent_folder = os.path.basename(os.path.dirname(full_path))
            series_folder = os.path.basename(os.path.dirname(os.path.dirname(full_path)))
            series_match = re.match(r"(.*?)\s*\((\d{4})\)?\s*\{tvdb-(\d+)\}", series_folder)
            if not series_match:
                print(f"⚠️ Could not extract show info from folder name: {series_folder}")
                continue

            series_name, year_hint, tvdb_id = series_match.groups()
            episode_title = get_episode_title(tvdb_id, season, episode)
            if not episode_title:
                print(f"⚠️ Could not fetch episode title for S{season:02}E{episode:02}")
                continue

            if episode_title.lower() in filename_title.lower():
                print(f"✅ Title match: '{episode_title}' in '{filename_title}'")
                matched_count += 1
            else:
                print(f"❌ Title mismatch: Expected '{episode_title}', Found '{filename_title}'")
                mismatched_count += 1
                if not DRY_RUN:
                    print(f"🛠️ Would trigger redownload for: {file}")
                else:
                    print(f"🔍 DRY RUN: Skipping redownload for: {file}")

    print(f"🔎 Scan complete: {matched_count} matched, {mismatched_count} mismatched")

if __name__ == "__main__":
    check_files()
