# ── build ─────────────────────────────────────────────────────
FROM node:18-alpine AS builder
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# ── runtime ───────────────────────────────────────────────────
FROM nginx:alpine
COPY --from=builder /app/build /usr/share/nginx/html
COPY entrypoint.sh /entrypoint.sh

RUN apk add --no-cache gettext \
 && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
