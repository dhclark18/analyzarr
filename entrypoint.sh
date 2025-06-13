#!/usr/bin/env sh
set -e

# inject real Sonarr vars into the static env.js
envsubst '${SONARR_URL} ${SONARR_API_KEY}' \
  < /usr/share/nginx/html/env.js \
  > /usr/share/nginx/html/env.js

# start nginx in foreground
exec nginx -g 'daemon off;'

# kick off your existing scanner in the background
python watcher.py
