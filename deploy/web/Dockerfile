# syntax=docker/dockerfile:1
# Edge image: Caddy + the built management console.
# Build context is the repository root; secrets are excluded by the
# neighbouring Dockerfile.dockerignore (the root .dockerignore drops frontend/).
FROM node:22-alpine AS console-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Same-origin API: the browser calls /api/v1 on the console's own domain.
ENV VITE_API_URL=/api/v1
RUN npm run build

FROM caddy:2.8-alpine
COPY --from=console-build /build/dist /srv/console
