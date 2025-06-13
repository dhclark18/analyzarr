#── 1) Build React in a Node image ───────────────────────────────
FROM node:18-alpine AS ui-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build
# build output is in /app/frontend/build

#── 2) Final image, based on your existing analyzarr base ────────
# Replace `python:3.11-slim` with whatever your analyzarr image used.
FROM python:3.11-slim AS final
WORKDIR /app

# install nginx & gettext for envsubst
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx gettext \
 && rm -rf /var/lib/apt/lists/*

# copy your existing analyzarr scripts (they run however you’ve been running them)
COPY analyzarr-main/ /app/

# copy the React build into nginx html dir
COPY --from=ui-builder /app/frontend/build /usr/share/nginx/html

# nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# entrypoint to inject env and start nginx
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
