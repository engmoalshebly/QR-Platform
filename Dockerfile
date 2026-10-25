# syntax=docker/dockerfile:1
# ---------- field PWA build stage ----------
# The scanner app is served by the API at /field/ (see app/main.py), so its
# production bundle must exist inside the image.
FROM node:26-alpine AS field-build

WORKDIR /build
COPY field-pwa/package.json field-pwa/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY field-pwa/ ./
RUN npm run build


# ---------- python dependency stage ----------
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---------- runtime stage ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root user with no login shell and no home-directory write access needed.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /install /usr/local

# Application code and the built field scanner.  Source files are owned by root
# and read-only for the runtime user; only the process needs no writes.
COPY app/ ./app/
# The bundled font families; copied into the writable fonts volume at API start.
COPY fonts/*-Regular.ttf fonts/*-Bold.ttf ./app/assets/fonts/
COPY --from=field-build /build/dist ./field-pwa/dist

# COPY keeps source permissions, and files in a developer checkout are often
# mode 600.  Make the code world-readable but leave it owned by root, so the
# runtime user can read it and cannot modify it.
RUN chmod -R a+rX /app \
    && mkdir -p /app/fonts /var/lib/qentry/generation \
    && chown 1000:1000 /app/fonts /var/lib/qentry/generation
# /app/fonts is the only writable path.  The compose file mounts a volume here;
# a named volume inherits this ownership, so uploads work for the runtime user.

USER 1000:1000

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health')"]

# --proxy-headers trusts X-Forwarded-* only from FORWARDED_ALLOW_IPS (set in
# docker-compose.prod.yml to the reverse proxy address).  Client IP handling in
# app/security.py also checks TRUSTED_PROXY_IPS.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--proxy-headers", "--no-server-header"]
