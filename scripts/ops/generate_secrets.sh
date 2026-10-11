#!/usr/bin/env bash
# Generate /etc/qentry/{compose,app}.env for a self-hosted deployment.
#
#   sudo scripts/ops/generate_secrets.sh app.example.com supabase.example.com
#
# Refuses to overwrite existing files.  Afterwards fill in the values marked
# TODO (SMTP, super-admin e-mail) -- nothing else needs hand-editing.
set -euo pipefail
umask 077
APP_DOMAIN="${1:?usage: generate_secrets.sh <console-domain> <supabase-domain>}"
SB_DOMAIN="${2:?usage: generate_secrets.sh <console-domain> <supabase-domain>}"
OUT_DIR="${OUT_DIR:-${QENTRY_ETC_DIR:-/etc/qentry}}"
mkdir -p "$OUT_DIR"
[ ! -e "$OUT_DIR/compose.env" ] && [ ! -e "$OUT_DIR/app.env" ] || {
  echo "refusing to overwrite existing files in $OUT_DIR" >&2; exit 1; }

hex() { openssl rand -hex "$1"; }
b64() { openssl rand -base64 48 | tr -d '\n'; }

JWT_SECRET="$(hex 32)"
POSTGRES_PASSWORD="$(hex 24)"
REDIS_PASSWORD="$(hex 24)"
APP_ROLE_PASSWORD="$(hex 24)"
BACKUP_ROLE_PASSWORD="$(hex 24)"

jwt() {  # HS256 JWT signed with JWT_SECRET, role claim $1, 10 year expiry
  python3 - "$JWT_SECRET" "$1" <<'PY'
import base64, hashlib, hmac, json, sys, time
secret, role = sys.argv[1].encode(), sys.argv[2]
enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
now = int(time.time())
head = enc(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
body = enc(json.dumps({"role": role, "iss": "supabase", "iat": now, "exp": now + 10 * 365 * 86400}, separators=(",", ":")).encode())
sig = enc(hmac.new(secret, head + b"." + body, hashlib.sha256).digest())
print((head + b"." + body + b"." + sig).decode())
PY
}
ANON_KEY="$(jwt anon)"
SERVICE_ROLE_KEY="$(jwt service_role)"

cat > "$OUT_DIR/compose.env" <<EOT
QENTRY_DOMAIN=$APP_DOMAIN
SUPABASE_DOMAIN=$SB_DOMAIN
APP_URL=https://$APP_DOMAIN
QENTRY_IMAGE=qentry-api:local
LINK_GATEWAY_IMAGE=
REDIS_PASSWORD=$REDIS_PASSWORD
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
JWT_SECRET=$JWT_SECRET
ANON_KEY=$ANON_KEY
SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY
# TODO: SMTP used by the platform and by GoTrue
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_ADMIN_EMAIL=
SMTP_SENDER_NAME="Qentry"
EOT

cat > "$OUT_DIR/app.env" <<EOT
APP_ENV=production
APP_URL=https://$APP_DOMAIN
CORS_ALLOWED_ORIGINS=https://$APP_DOMAIN
TRUSTED_PROXY_IPS=172.28.20.2

SUPABASE_URL=https://$SB_DOMAIN
SUPABASE_ANON_KEY=$ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY
SUPABASE_JWT_SECRET=$JWT_SECRET
SUPABASE_JWT_ISSUER=

DATABASE_SSL=disable
DATABASE_URL=postgresql+asyncpg://postgres:$POSTGRES_PASSWORD@db:5432/postgres
DATABASE_APP_URL=postgresql+asyncpg://qentry_app:$APP_ROLE_PASSWORD@db:5432/postgres

INVITE_HMAC_SECRET=$(b64)
INVITE_HMAC_SECRET_PREV=
OTP_HMAC_SECRET=$(b64)
ORG_REQUEST_ENCRYPTION_KEY=$(b64)
METRICS_ACCESS_TOKEN=$(hex 32)

PLATFORM_ADMIN_REQUIRE_AAL2=true
# TODO: comma-separated staff e-mail(s) with break-glass access
PLATFORM_SUPERADMIN_EMAILS=

# TODO: same SMTP as compose.env
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_ADMIN_EMAIL=
SMTP_SENDER_NAME="Qentry"

# Online payments disabled: intentionally empty.
LINK_GATEWAY_API_KEY=
SENTRY_DSN=
STORAGE_BUCKET=invitations
EOT

# Passwords consumed by bootstrap_database.sh / the backup timer.
cat > "$OUT_DIR/db-roles.env" <<EOT
APP_ROLE_PASSWORD=$APP_ROLE_PASSWORD
BACKUP_ROLE_PASSWORD=$BACKUP_ROLE_PASSWORD
EOT
chmod 600 "$OUT_DIR"/*.env
echo "written: $OUT_DIR/compose.env $OUT_DIR/app.env $OUT_DIR/db-roles.env"
echo "now fill the TODO lines (SMTP, PLATFORM_SUPERADMIN_EMAILS)."
