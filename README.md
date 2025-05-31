# Analyzarr

This Docker-based tool verifies that downloaded episode filenames match official titles (via TVDb). The webpage provides a detailed breakdown of each episode so you can see exactly which episodes are potentially problematic. This was created becuase every so often a string of episodes (typically after a multi-part episode) would be offset due to the various episode numberings some shows have. This will catch those situations in addition to random incorrectly labeled nzb files.  

## Features

- Auto-checks episode filenames against TVDb
- Creates database containing various parameters for each episode.
- Uses database to create webpage that cleanly organizes everything by series and provides detailed information about each episode to help determine if episodes need redownloading.
- Supports real-time directory watching.
- Ability to only scan specific series and seasons.
- Fuzzy matching to determine if episode titles match expected title.
- Customizable END_MARKERS to help improve accuracy. Highly recommend adding a few extra words that commonly come right after the episode titles but cannot be named or hard coded for various reasons.
- Purge button to remove deleted episodes or series from the database.

## Requirements

- Only guarenteed to work with usenet files right now. Use with torrent files is untested.    
  
## Setup

1. Create new docker stack using provided docker-compose.yml and modify variables as needed (including END_MARKERS).
2. Run stack for first time.
3. Go to http://[your ip address]:5000 to see problematic episodes. Could take a couple of seconds to fully scan library depending on size. 

## Disclaimer

This is a work in progress. I have no formal coding training and used AI to help. Its mainly a fun project. Use at your own risk. Feel free to provide feedback. 
