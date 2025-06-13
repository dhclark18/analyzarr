#!/usr/bin/env sh
set -e

echo ">>> Injecting SONARR_URL=${SONARR_URL}"
envsubst '${SONARR_URL} ${SONARR_API_KEY}' \
  < /usr/share/nginx/html/env.js \
  > /usr/share/nginx/html/env.js

echo ">>> env.js now reads:"
cat /usr/share/nginx/html/env.js

# background your watcher:
python watcher.py &

# finally, run nginx
exec nginx -g 'daemon off;'
