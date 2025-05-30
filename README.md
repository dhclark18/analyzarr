# Analyzarr

This Docker-based tool verifies that downloaded filenames match official titles (via TVDb) and triggers Sonarr to re-download them if they don’t. It also creates a database to view problematic episodes for manual intervention. 

## Features

- Auto-checks episode filenames against TVDb
- Attempts 3 times to find nzb with correct title. Afterwards it flags the episode as problematic and just requests the nzb release with the highest custom format. Once an episode is flagged as problematic it won't be tocuhed by the matching software.
- Creates database of problematic episodes for you to manually intervene.
- Uses database to create webpage depicting all the tv series in your library and which ones have problematic episodes.
- Supports real-time directory watching.
- Supports FORCED_RUN mode. When false it will just verify that downloaded episodes' filename match official titles without triggering a deletion and redownload.

## Requirements
- Only works with custom Sabnzbd currently because it requires a prequeue script specifically designed for Sabnzbd and psycopg2.
  
## Setup

1. Download sabnzbd_prequeue_script.py and edit variables.
2. Set up Sabnzbd to use script as a prequeue script.
3. Build custom Sabznbd so it has psycopg2.
4. Create new docker stack using provided docker-compose.yml and modify variables as needed.
5. Run stack for first time
6. Restart stack (issue with database not being initialized on first run)
7. Go to http://[your ip address]:5000 to see problematic episodes.
8. Enjoy. I recommend trying it out on one season in a series since this could trigger a large deletion and download if ran on entire library.

## Disclaimer
This is a work in progress. I am a novice coder with no formal training and this was created with the help of AI. Its mainly a fun project because I noticed sometimes Sonarr would get a mislabeled nzb and I wouldnt find out until I tried to play it in Plex. Use at your own risk. Feel free to provide feedback. 
