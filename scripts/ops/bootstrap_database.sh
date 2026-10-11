#!/usr/bin/env bash
# One-time initialisation of the self-hosted database: applies schema +
# migrations, sets the RLS application role password, creates the read-only
# backup role.  Refuses to run against a database that already has the schema.
#
#   sudo scripts/ops/bootstrap_database.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
export QENTRY_ETC_DIR="${QENTRY_ETC_DIR:-/etc/qentry}"
ENV_DIR="$QENTRY_ETC_DIR"
# Read single values instead of sourcing: env files are docker-style KEY=VALUE
# and may hold spaces (SMTP_SENDER_NAME=Qr Platform) that a shell would execute.
envval() { grep -m1 "^$1=" "$2" | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
POSTGRES_PASSWORD="$(envval POSTGRES_PASSWORD "$ENV_DIR/compose.env")"
APP_ROLE_PASSWORD="$(envval APP_ROLE_PASSWORD "$ENV_DIR/db-roles.env")"
BACKUP_ROLE_PASSWORD="$(envval BACKUP_ROLE_PASSWORD "$ENV_DIR/db-roles.env")"
[ -n "$POSTGRES_PASSWORD" ] && [ -n "$APP_ROLE_PASSWORD" ] && [ -n "$BACKUP_ROLE_PASSWORD" ] \
  || { echo "missing password(s) in $ENV_DIR" >&2; exit 1; }
PROJECT="${COMPOSE_PROJECT_NAME:-qentry-prod}"
NET="${PROJECT}_app"

c() { scripts/ops/qentry-compose.sh "$@"; }
# GoTrue must create the real auth schema (auth.users, ...) before the
# application migrations run; otherwise ci_migrate.py stubs auth.users and
# GoTrue's own migration then fails.
echo "starting database and auth..."
c up -d db auth
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$(c ps -q auth)" 2>/dev/null)" = healthy ] && break
  sleep 3
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$(c ps -q auth)")" = healthy ] \
  || { echo "auth did not become healthy; see: qentry-compose.sh logs auth" >&2; exit 1; }

existing=$(c exec -T db psql -U postgres -tAc "SELECT to_regclass('public.app_schema_migrations') IS NOT NULL")
if [ "$existing" = "t" ]; then
  echo "database already initialised; apply new migrations by hand (RUNBOOK section 3)." >&2
  exit 1
fi

# Migrations run as supabase_admin: in the Supabase image `postgres` is
# demoted (not a real superuser) and migration v52 needs GRANT ... ON PARAMETER.
# This matches the development database, where supabase_admin owns the tables.
echo "applying schema and migrations..."
docker run --rm --network "$NET" -v "$PWD:/work:ro" -w /work \
  -e MIGRATION_DATABASE_URL="postgresql://supabase_admin:${POSTGRES_PASSWORD}@db:5432/postgres" \
  -e RLS_APP_PASSWORD="$APP_ROLE_PASSWORD" \
  python:3.12-slim sh -c "pip install -q --no-cache-dir asyncpg && python scripts/migrations/ci_migrate.py"

echo "creating read-only backup role..."
# BYPASSRLS is required: pg_read_all_data does not override row-level security,
# so pg_dump would otherwise fail on RLS-protected tables (auth.audit_log_entries,
# every tenant table).  The role is read-only and cannot log in from outside.
c exec -T db psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 -v pw="$BACKUP_ROLE_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE qentry_backup LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qentry_backup') \gexec
SELECT format('ALTER ROLE qentry_backup PASSWORD %L', :'pw') \gexec
GRANT pg_read_all_data TO qentry_backup;
ALTER ROLE qentry_backup BYPASSRLS;
ALTER ROLE qentry_backup SET default_transaction_read_only = on;
SQL
echo "done. Next: scripts/ops/qentry-compose.sh up -d"
