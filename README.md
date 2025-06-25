# Analyzarr

This Docker-based tool verifies that downloaded episode filenames match official titles (via TVDb). Presents results on a webpage so you can see exactly which episodes are potentially problematic. This was created becuase every so often a string of episodes (typically after a multi-part episode) would be offset due to the various episode numberings some shows have. This will catch those situations in addition to random incorrectly labeled nzb files.  

## Features

- Auto-checks episode filenames against TVDb
- Creates database containing various parameters for each episode.
- Web GUI that presents rich statistics, details, and provides user with ability to control aspects of library.
- Supports real-time directory watching.
- Ability to only scan specific series and seasons.
- Fuzzy matching to determine if episode titles match expected title.
- Detailed information about each episode file.
- Breakdown of analyzarr logic for each episode

## Requirements

- Only guarenteed to work with usenet files right now. Use with torrent files is untested.    
  
## Setup

1. Create new docker stack using provided docker-compose.yml and modify variables as needed (including END_MARKERS).
2. Run stack for first time.
3. Go to http://[your ip address]:3030 (or whatever you specified in the docker compose) to access web GUI. Could take a couple of seconds to fully scan library depending on size. 

## Disclaimer

This is a work in progress. I have no formal coding training and used AI to help. Its mainly a fun project. Use at your own risk. Feel free to provide feedback. 
