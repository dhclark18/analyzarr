# One-liner

This Docker-based tool verifies that downloaded TV episode filenames match official titles (via TVDb) and triggers Sonarr to re-download them if they don’t.

## Features

- Auto-checks TV episode filenames against TVDb
- Triggers Sonarr redownload via its API
- Supports real-time directory watching

## Requirements
- Sonarr file name format must be {Series TitleYear} - S{season:00}E{episode:00} - {Episode CleanTitle} [{...}]
- Only works with Sabnzbd currently because it requires a prequeue script specifically designed for Sabnzbd
  
## Setup

1. Download 
