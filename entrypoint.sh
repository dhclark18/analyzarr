#!/usr/bin/env sh
set -e

# inject real Sonarr vars into the static env.js
envsubst '${SONARR_URL} ${SONARR_API_KEY}' \
  < /usr/share/nginx/html/env.js \
  > /usr/share/nginx/html/env.js

# kick off your existing scanner in the background
python watcher.py

# start nginx in foreground
exec nginx -g 'daemon off;'
