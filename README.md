# TV Episode Filename Checker

This Docker-based tool verifies that downloaded TV episode filenames match official titles (via TMDb) and triggers Sonarr to re-download them if they don’t.

## Features

- Auto-checks TV episode filenames against TMDb
- Triggers Sonarr redownload via its API
- Supports real-time directory watching
- SABnzbd post-processing script with cooldown

## Setup

1. Fill in API keys and Sonarr URL in:
   - `docker-compose.yml`
   - `sabnzbd_docker_checker.sh`

2. Build the image:
   ```bash
   docker-compose build
