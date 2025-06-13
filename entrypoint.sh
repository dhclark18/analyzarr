#!/usr/bin/env sh
set -e

# inject real Sonarr vars into a temp file, then overwrite env.js
envsubst '${SONARR_URL} ${SONARR_API_KEY}' \
  < /usr/share/nginx/html/env.js \
  > /usr/share/nginx/html/env.tmp.js \
&& mv /usr/share/nginx/html/env.tmp.js /usr/share/nginx/html/env.js

echo ">>> env.js now reads:"
cat /usr/share/nginx/html/env.js

# start the API
python3 /app/api.py &

# start watcher in background
python3 watcher.py &

# run nginx in foreground
exec nginx -g 'daemon off;'
