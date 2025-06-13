#── 1) Build React UI ───────────────────────────────────────────────
FROM node:18-alpine AS ui-builder
WORKDIR /app/frontend

# only pull in package.json for layer caching
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build
# → build output in /app/frontend/build

#── 2) Final image: Python + nginx + watcher ──────────────────────
FROM python:3.11-slim
WORKDIR /app

# install your Python deps
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# copy Python analyzer scripts & old start.sh
COPY . /app/
RUN chmod +x /app/start.sh

# install nginx & gettext (for envsubst)
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx gettext \
 && rm -rf /var/lib/apt/lists/*

# copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# copy the built React app into nginx html root
COPY --from=ui-builder /app/frontend/build /usr/share/nginx/html

# entrypoint that injects env vars + starts watcher + nginx
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80
ENTRYPOINT ["/entrypoint.sh"]
