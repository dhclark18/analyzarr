import os
import sys
import requests
import re
import string
import time

# TVDB token cache
_tvdb_token = None
_tvdb_token_expiry = 0  # Unix timestamp

TVDB_API_KEY = os.getenv("TVDB_API_KEY")
TVDB_PIN = os.getenv("TVDB_PIN")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
SONARR_URL = os.getenv("SONARR_URL")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

def get_tvdb_token():
    global _tvdb_token, _tvdb_token_expiry
    if _tvdb_token and time.time() < _tvdb_token_expiry:
        return _tvdb_token

    print("🔐 Requesting new TVDB token...")
    url = "https://api4.thetvdb.com/v4/login"
    resp = requests.post(url, json={"apikey": TVDB_API_KEY, "pin": TVDB_PIN})
    resp.raise_for_status()
    data = resp.json()["data"]
    _tvdb_token = data["token"]
    _tvdb_token_expiry = time.time() + 23.5 * 3600  # 23.5 hours for buffer
    return _tvdb_token

def get_show_id(show_name, token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get("https://api4.thetvdb.com/v4/search", params={"query": show_name}, headers=headers)
    resp.raise_for_status()
    results = resp.json().get("data", [])
    if not results:
        return None
    return results[0]["tvdb_id"]

def get_episode_title(series_id, season, episode, token):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api4.thetvdb.com/v4/series/{series_id}/episodes/default"
    params = {"season": season, "episodeNumber": episode}
    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return None
    return data[0].get("name")

def parse_filename(filename):
    basename = os.path.basename(filename)
    match = re.search(r"(.*?)[. _-][sS](\d+)[eE](\d+)", basename)
    if not match:
        return None, None, None
    show = match.group(1).replace('.', ' ').replace('_', ' ').strip()
    season = int(match.group(2))
    episode = int(match.group(3))
    return show, season, episode

def extract_clean_title_from_filename(filename):
    basename = os.path.basename(filename)
    match = re.search(r"S\d{2}E\d{2}\s*-\s*(.*?)\s*(\[|$)", basename)
    if match:
        return match.group(1).strip()
    return None

def clean_title(title):
    return ''.join(c for c in title.lower() if c in string.ascii_lowercase + string.digits)

def notify_sonarr(search_title):
    params = {"apikey": SONARR_API_KEY, "term": search_title}
    resp = requests.get(f"{SONARR_URL}/api/series/lookup", params=params)
    if resp.status_code != 200 or not resp.json():
        print("Sonarr lookup failed or returned nothing.")
        return False
    series_id = resp.json()[0]["id"]
    search_resp = requests.post(f"{SONARR_URL}/api/command", json={
        "name": "EpisodeSearch",
        "seriesId": series_id
    }, params={"apikey": SONARR_API_KEY})
    return search_resp.status_code == 201

def main():
    if len(sys.argv) < 2:
        print("Usage: checker.py <filepath>")
        sys.exit(1)
    filepath = sys.argv[1]
    show, season, episode = parse_filename(filepath)
    if not show:
        print("Could not parse filename for show/season/episode.")
        sys.exit(1)

    try:
        token = get_tvdb_token()
        show_id = get_show_id(show, token)
        if not show_id:
            print(f"Could not find show ID for {show}")
            sys.exit(1)

        tvdb_title = get_episode_title(show_id, season, episode, token)
        if not tvdb_title:
            print(f"Could not find episode title for {show} S{season}E{episode}")
            sys.exit(1)

        file_title = extract_clean_title_from_filename(filepath)
        if not file_title:
            print("Could not extract episode title from filename.")
            sys.exit(1)

        cleaned_tvdb = clean_title(tvdb_title)
        cleaned_file = clean_title(file_title)

        if cleaned_tvdb == cleaned_file:
            print(f"✅ MATCH: {os.path.basename(filepath)} == \"{tvdb_title}\"")
        else:
            print(f"❌ MISMATCH: {os.path.basename(filepath)} ≠ \"{tvdb_title}\"")
            if DRY_RUN:
                print("🧪 DRY RUN MODE: Not triggering Sonarr.")
            else:
                print("🔁 Triggering Sonarr redownload...")
                if notify_sonarr(show):
                    print("✅ Sonarr search triggered.")
                else:
                    print("❌ Failed to trigger Sonarr.")
    except Exception as e:
        print(f"⚠️ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
