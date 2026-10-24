# ---- build ----
FROM --platform=$BUILDPLATFORM node:24-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# ---- runtime ----
FROM nginx:1.27-alpine

ARG COMMIT_SHA=development
ARG BUILD_TIME=unknown
ARG ACTIONS_URL=
LABEL org.opencontainers.image.title="Aegis-RAG" \
      org.opencontainers.image.revision=$COMMIT_SHA \
      org.opencontainers.image.created=$BUILD_TIME

RUN rm /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# Minimal nginx config with CSP headers
RUN cat > /etc/nginx/conf.d/app.conf <<'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000/;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

EXPOSE 80
