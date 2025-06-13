#── Stage 1: Build React UI ────────────────────────────────────────
FROM node:18-alpine AS ui-builder
WORKDIR /app/frontend

# Install JS deps
COPY frontend/package.json ./
RUN npm install

# Build the production bundle
COPY frontend/ ./
RUN npm run build   # outputs into /app/frontend/build

#── Stage 2: Final image with Python watcher + nginx ─────────────
FROM python:3.11-slim
WORKDIR /app

# 1) Install Python requirements for your watcher
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ENV LOG_PATH=/logs
ENV WATCH_DIR=/watched

# 2) Bring in Python watcher scripts from root directory
COPY *.py ./

# 3) Install nginx & gettext (for envsubst)
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx gettext \
 && rm -rf /var/lib/apt/lists/*
RUN rm -f /etc/nginx/sites-enabled/default

# 4) Copy nginx config (SPA routing)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 5) Remove default nginx files, then copy the React build
RUN rm -rf /usr/share/nginx/html/*
COPY --from=ui-builder /app/frontend/build/ /usr/share/nginx/html/

# 6) Copy unified entrypoint (injects env, runs watcher, launches nginx)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose the nginx port (mapped to your choice in compose)
EXPOSE 80

# Kick off entrypoint
ENTRYPOINT ["/entrypoint.sh"]
