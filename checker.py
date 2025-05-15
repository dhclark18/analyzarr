import sys
import os
import requests
import re
import string

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
SONARR_URL = os.getenv("SONARR_URL")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

def get_show_episode_title(show_name, season, episode):
    url = f"https://api.themoviedb.org/3/search/tv?api_key={TMDB_API_KEY}&query={show_name}"
    resp = requests.get(url)
    data = resp.json()
    if not data.get("results"):
        return None
    show_id = data["results"][0]["id"]
    ep_url = f"https://api.themoviedb.org/3/tv/{show_id}/season/{season}/episode/{episode}?api_key={TMDB_API_KEY}"
    ep_resp = requests.get(ep_url)
    ep_data = ep_resp.json()
    return ep_data.get("name")

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
    params = {
        "apikey": SONARR_API_KEY,
        "term": search_title
    }
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

    tmdb_title = get_show_episode_title(show, season, episode)
    if not tmdb_title:
        print("Could not get episode title from TMDb.")
        sys.exit(1)

    file_title = extract_clean_title_from_filename(filepath)
    if not file_title:
        print("Could not extract episode title from filename.")
        sys.exit(1)

    cleaned_tmdb = clean_title(tmdb_title)
    cleaned_file = clean_title(file_title)

    if cleaned_tmdb == cleaned_file:
        print(f"✅ MATCH: {os.path.basename(filepath)} == \"{tmdb_title}\"")
    else:
        print(f"❌ MISMATCH: {os.path.basename(filepath)} ≠ \"{tmdb_title}\"")
        if DRY_RUN:
            print("🧪 DRY RUN MODE: Not triggering Sonarr.")
        else:
            print("🔁 Triggering Sonarr redownload...")
            success = notify_sonarr(show)
            if success:
                print("✅ Sonarr search triggered.")
            else:
                print("❌ Failed to trigger Sonarr.")

if __name__ == "__main__":
    main()
