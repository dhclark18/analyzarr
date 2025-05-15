#!/bin/bash

DOWNLOAD_PATH="$1"
NZB_NAME="$2"
STATUS="$3"

COOLDOWN_SECONDS=300
LOCK_DIR="/tmp/sabnzbd_checker_locks"
DOCKER_IMAGE="tv-episode-checker"
TMDB_API_KEY="your_tmdb_api_key"
SONARR_API_KEY="your_sonarr_api_key"
SONARR_URL="http://your-sonarr:8989"

mkdir -p "$LOCK_DIR"

LOCK_FILE="${LOCK_DIR}/${NZB_NAME}.lock"
now=$(date +%s)
last_run=0

if [ -f "$LOCK_FILE" ]; then
  last_run=$(cat "$LOCK_FILE")
fi

delta=$((now - last_run))

if [ "$delta" -lt "$COOLDOWN_SECONDS" ]; then
  echo "[Checker] Skipping '$NZB_NAME' — ran ${delta}s ago (< ${COOLDOWN_SECONDS}s)"
  exit 0
fi

echo "$now" > "$LOCK_FILE"
echo "[Checker] Triggered for: $NZB_NAME"
echo "[Checker] Download Path: $DOWNLOAD_PATH"
echo "[Checker] Status: $STATUS"

find "$DOWNLOAD_PATH" -type f \( -iname "*.mkv" -o -iname "*.mp4" -o -iname "*.avi" \) | while read -r FILE
do
  echo "[Checker] Checking file: $FILE"
  docker run --rm \
    -e TMDB_API_KEY="$TMDB_API_KEY" \
    -e SONARR_API_KEY="$SONARR_API_KEY" \
    -e SONARR_URL="$SONARR_URL" \
    -v "$FILE":"$FILE":ro \
    "$DOCKER_IMAGE" "$FILE"
done

exit 0
