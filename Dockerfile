#── Stage 1: Build React UI ───────────────────────────────────────
FROM node:18-slim AS ui-builder
WORKDIR /app/frontend

# Install JS dependencies
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

# Copy React source and build
COPY frontend/ ./
RUN npm run build    # outputs to /app/frontend/build

#── Stage 2: Final image with Python watcher + nginx ───────────────
FROM python:3.11-slim
WORKDIR /app

# Install Python requirements for your watcher
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy your Python watcher scripts
COPY *.py ./
# (Add extra COPY lines here for any modules or directories)

# Install nginx & gettext for envsubst
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx gettext \
 && rm -rf /var/lib/apt/lists/*

# Remove any default vhosts
RUN rm -f /etc/nginx/sites-enabled/default \
       /etc/nginx/conf.d/default.conf

# Copy custom nginx config (SPA routing)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Override default html with React build
RUN rm -rf /usr/share/nginx/html/*
COPY --from=ui-builder /app/frontend/build/ /usr/share/nginx/html/

# Copy entrypoint (injects env, runs watcher, then nginx)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose nginx port
EXPOSE 80

# Launch entrypoint
ENTRYPOINT ["/entrypoint.sh"]
