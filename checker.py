import os
import re
import time
import json
import requests
from urllib.parse import quote_plus

WATCH_DIR = os.getenv("WATCH_DIR", "/watched")
TVDB_API_KEY = os.getenv("TVDB_API_KEY")
TVDB_PIN = os.getenv("TVDB_PIN")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

_tvdb_token = None
_tvdb_token_expiry = 0  # Unix timestamp


def get_tvdb_token(force_refresh=False):
    global _tvdb_token, _tvdb_token_expiry
    if not force_refresh and _tvdb_token and time.time() < _tvdb_token_expiry:
        return _tvdb_token

    print("🔐 Requesting new TVDB token...")
    url = "https://api4.thetvdb.com/v4/login"
    payload = {
        "apikey": TVDB_API_KEY,
        "pin": TVDB_PIN
    }
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()["data"]
    _tvdb_token = data["token"]
    _tvdb_token_expiry = time.time() + 23.5 * 3600
    return _tvdb_token


def get_tvdb_show_id(show_name):
    # Remove year like (2005) and special characters
    clean_name = re.sub(r"\s*\(\d{4}\)", "", show_name).strip()
    clean_name = re.sub(r"[!]", "", clean_name)

    url = f"https://api4.thetvdb.com/v4/search?query={quote_plus(clean_name)}"
    headers = {"Authorization": f"Bearer {get_tvdb_token()}"}
    resp = requests.get(url, headers=headers)

    if resp.status_code == 401:
        print("🔄 Token expired or invalid, refreshing...")
        headers["Authorization"] = f"Bearer {get_tvdb_token(force_refresh=True)}"
        resp = requests.get(url, headers=headers)

    if resp.status_code != 200:
        print(f"❌ TVDB search failed: {resp.status_code}")
        return None

    data = resp.json().get("data", [])
    if not data:
        print(f"❌ Could not find show ID for {show_name}")
        return None

    return data[0].get("tvdb_id")


def get_episode_title(tvdb_id, season, episode):
    url = f"https://api4.thetvdb.com/v4/series/{tvdb_id}/episodes/default?season={season}&episodeNumber={episode}"
    headers = {"Authorization": f"Bearer {get_tvdb_token()}"}
    resp = requests.get(url, headers=headers)

    if resp.status_code == 401:
        headers["Authorization"] = f"Bearer {get_tvdb_token(force_refresh=True)}"
        resp = requests.get(url, headers=headers)

    if resp.status_code != 200:
        print(f"❌ Failed to get episode title: {resp.status_code}")
        return None

    return resp.json().get("data", {}).get("name")


def parse_episode_info(filename):
    match = re.search(r"S(\d{2})E(\d{2})", filename, re.IGNORECASE)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def extract_show_name(filename):
    match = re.search(r"^(.*?)(?:\s*-\s*S\d{2}E\d{2})", filename)
    return match.group(1).strip() if match else None


def scan_directory():
    print(f"📁 Scanning directory: {WATCH_DIR}")
    for fname in os.listdir(WATCH_DIR):
        if not fname.lower().endswith((".mkv", ".mp4", ".avi")):
            continue

        show_name = extract_show_name(fname)
        if not show_name:
            print(f"⚠️ Could not extract show name from: {fname}")
            continue

        season, episode = parse_episode_info(fname)
        if season is None:
            print(f"⚠️ Could not parse episode from: {fname}")
            continue

        show_id = get_tvdb_show_id(show_name)
        if not show_id:
            continue

        expected_title = get_episode_title(show_id, season, episode)
        if not expected_title:
            print(f"⚠️ Could not fetch episode title for {show_name} S{season:02d}E{episode:02d}")
            continue

        if expected_title.lower() not in fname.lower():
            print(f"❌ Title mismatch: {fname}")
            print(f"   ⟶ Expected episode title: {expected_title}")
            if not DRY_RUN:
                trigger_redownload(show_name, season, episode)
        else:
            print(f"✅ Title matches: {fname}")


def trigger_redownload(show_name, season, episode):
    headers = {"X-Api-Key": SONARR_API_KEY}
    print(f"🔁 Triggering redownload via Sonarr: {show_name} S{season:02d}E{episode:02d}")

    # Step 1: Get series ID from Sonarr
    try:
        series_resp = requests.get(f"{SONARR_URL}/api/v3/series", headers=headers)
        series_resp.raise_for_status()
        series_list = series_resp.json()
        series = next((s for s in series_list if show_name.lower() in s["title"].lower()), None)

        if not series:
            print(f"❌ Could not find show '{show_name}' in Sonarr")
            return

        # Step 2: Trigger episode search
        payload = {
            "name": "EpisodeSearch",
            "seriesId": series["id"],
            "episodeIds": []
        }

        # Find episode ID
        eps_resp = requests.get(f"{SONARR_URL}/api/v3/episode?seriesId={series['id']}", headers=headers)
        eps_resp.raise_for_status()
        episodes = eps_resp.json()
        for ep in episodes:
            if ep["seasonNumber"] == season and ep["episodeNumber"] == episode:
                payload["episodeIds"].append(ep["id"])
                break

        if not payload["episodeIds"]:
            print(f"❌ Could not find episode {season}x{episode} in Sonarr")
            return

        post_resp = requests.post(f"{SONARR_URL}/api/v3/command", headers=headers, json=payload)
        post_resp.raise_for_status()
        print(f"✅ Redownload triggered in Sonarr for {show_name} S{season:02d}E{episode:02d}")

    except requests.RequestException as e:
        print(f"❌ Failed to contact Sonarr: {e}")


if __name__ == "__main__":
    scan_directory()
