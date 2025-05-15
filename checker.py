import os
import re
import requests

# Sonarr config
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "your_api_key_here")
SONARR_URL = os.getenv("SONARR_URL", "http://localhost:8989/api/v3")
AUTO_REDOWNLOAD = os.getenv("AUTO_REDOWNLOAD", "false").lower() in ("1", "true", "yes")

HEADERS = {
    "X-Api-Key": SONARR_API_KEY
}

def get_series_by_tvdbid(tvdbid):
    try:
        resp = requests.get(f"{SONARR_URL}/series", headers=HEADERS)
        resp.raise_for_status()
        for series in resp.json():
            if str(series.get("tvdbId")) == str(tvdbid):
                return series
    except Exception as e:
        print(f"❌ Error fetching series: {e}")
    return None

def get_episode(series_id, season_num, episode_num):
    try:
        resp = requests.get(
            f"{SONARR_URL}/episode?seriesId={series_id}",
            headers=HEADERS
        )
        resp.raise_for_status()
        for ep in resp.json():
            if ep["seasonNumber"] == season_num and ep["episodeNumber"] == episode_num:
                return ep
    except Exception as e:
        print(f"❌ Error fetching episode: {e}")
    return None

def request_redownload(episode_id):
    try:
        resp = requests.post(
            f"{SONARR_URL}/command",
            json={
                "name": "EpisodeSearch",
                "episodeIds": [episode_id]
            },
            headers=HEADERS
        )
        resp.raise_for_status()
        print("🔁 Requested redownload from Sonarr")
    except Exception as e:
        print(f"❌ Failed to request redownload: {e}")

def extract_info_from_path(filepath):
    match = re.search(r"\{tvdb-(\d+)\}", filepath)
    tvdbid = match.group(1) if match else None

    match = re.search(r"S(\d{2})E(\d{2})", filepath, re.IGNORECASE)
    if not match:
        return None, None, None, None
    season_num = int(match.group(1))
    episode_num = int(match.group(2))

    # Attempt to extract title
    title_match = re.search(r"- S\d{2}E\d{2} - (.+?)\[", filepath)
    filename_title = title_match.group(1).strip() if title_match else None

    return tvdbid, season_num, episode_num, filename_title

def walk_and_check(root_dir):
    for dirpath, _, filenames in os.walk(root_dir):
        for file in filenames:
            if not file.lower().endswith((".mkv", ".mp4")):
                continue

            full_path = os.path.join(dirpath, file)
            print(f"\n📺 Checking: {full_path}")

            tvdbid, season, episode, found_title = extract_info_from_path(full_path)
            if not all([tvdbid, season, episode]):
                print("⚠️ Could not extract episode info from filename.")
                continue

            series = get_series_by_tvdbid(tvdbid)
            if not series:
                print(f"⚠️ No matching series found in Sonarr for tvdb-{tvdbid}")
                continue

            episode_data = get_episode(series["id"], season, episode)
            if not episode_data:
                print(f"⚠️ Episode S{season:02d}E{episode:02d} not found in Sonarr.")
                continue

            expected_title = episode_data["title"]
            if found_title and expected_title.lower() not in found_title.lower():
                print(f"❌ Mismatch: filename has \"{found_title}\" but Sonarr says \"{expected_title}\"")
                if AUTO_REDOWNLOAD:
                    request_redownload(episode_data["id"])
                else:
                    print("🚫 AUTO_REDOWNLOAD is off; not requesting redownload")
            else:
                print(f"✅ Title matched: {expected_title}")

if __name__ == "__main__":
    root_directory = "/watched"
    walk_and_check(root_directory)
