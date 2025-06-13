#!/usr/bin/env sh
# replace ${…} placeholders in env.js at container start
envsubst '${SONARR_URL} ${SONARR_API_KEY}' \
  < /usr/share/nginx/html/env.js \
  > /usr/share/nginx/html/env.js

# launch nginx
exec nginx -g 'daemon off;'
