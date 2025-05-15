# checker.py placeholder contentimport sys
import os
import requests
import re

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
SONARR_URL = os.getenv("SONARR_URL")

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
    match = re.search(r"(.*)[. _-][sS](\\d+)[eE](\\d+)", basename)
    if not match:
        return None, None, None
    show = match.group(1).replace('.', ' ').strip()
    season = int(match.group(2))
    episode = int(match.group(3))
    return show, season, episode

def notify_sonarr(search_title):
    params = {
        "apikey": SONARR_API_KEY,
        "term": search_title
    }
    resp = requests.get(f"{SONARR_URL}/api/series/lookup", params=params)
    if resp.status_code != 200:
        print("Sonarr lookup failed:", resp.text)
        return False
    results = resp.json()
    if not results:
        print("Sonarr lookup found nothing.")
        return False
    series_id = results[0]["id"]
    search_resp = requests.post(f"{SONARR_URL}/api/command", json={
        "name": "EpisodeSearch",
        "seriesId": series_id
    }, params={"apikey": SONARR_API_KEY})
    if search_resp.status_code == 201:
        print("Triggered Sonarr search successfully.")
        return True
    else:
        print("Failed to trigger Sonarr search:", search_resp.text)
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: checker.py <filepath>")
        sys.exit(1)
    filepath = sys.argv[1]
    show, season, episode = parse_filename(filepath)
    if not show:
        print("Could not parse filename for show/season/episode.")
        sys.exit(1)
    print(f"Parsed: Show='{show}', Season={season}, Episode={episode}")
    title = get_show_episode_title(show, season, episode)
    if not title:
        print("Could not find episode title via TMDb.")
        sys.exit(1)
    print(f"TMDb episode title: {title}")
    if title.lower() not in filepath.lower():
        print("Filename mismatch detected! Triggering Sonarr search.")
        notify_sonarr(show)
    else:
        print("Filename matches episode title.")

if __name__ == "__main__":
    main()
