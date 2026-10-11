#!/usr/bin/env bash
# Restore drill: prove that the newest backup restores and is usable.
#
# Self-contained: starts a throwaway Postgres container (same image as
# production), restores the newest backup into it, checks the schema, removes
# it.  Needs the GPG private key on this host.  Run quarterly and before major
# releases, on any host with Docker (production host is fine: nothing is shared).
#
#   BACKUP_DIR=/var/backups/qentry scripts/ops/restore_drill.sh
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
IMAGE="${DRILL_IMAGE:-public.ecr.aws/supabase/postgres:17.6.1.140}"
NAME="qentry-restore-drill-$$"

latest="$(ls -1t "$BACKUP_DIR"/qentry-*.dump.gpg | head -n 1)"
[ -n "$latest" ] || { echo "no backup found in $BACKUP_DIR" >&2; exit 1; }
echo "restoring $latest into throwaway container $NAME"

started=$(date +%s)
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$NAME" -e POSTGRES_PASSWORD=drill "$IMAGE" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -U postgres -h localhost >/dev/null 2>&1 && break
  sleep 2
done
docker exec "$NAME" pg_isready -U postgres -h localhost >/dev/null

psql_in() { docker exec -i -e PGPASSWORD=drill "$NAME" psql -h 127.0.0.1 -U supabase_admin -d restore -tA "$@"; }
docker exec -e PGPASSWORD=drill "$NAME" psql -h 127.0.0.1 -U supabase_admin -d postgres -c "CREATE DATABASE restore" >/dev/null

# Errors about pre-existing Supabase-managed objects are expected; a non-zero
# count of *data* errors is judged by the checks below.
gpg --batch --quiet --decrypt "$latest" \
  | docker exec -i -e PGPASSWORD=drill "$NAME" pg_restore -h 127.0.0.1 -U supabase_admin -d restore \
      --no-owner --no-privileges 2>&1 | grep -vE 'already exists|must be owner' || true

version=$(psql_in -c "SELECT COALESCE(MAX(version),0) FROM app_schema_migrations;")
tables=$(psql_in -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
plans=$(psql_in -c "SELECT count(*) FROM plans;")
elapsed=$(( $(date +%s) - started ))

echo "restored schema version: $version"
echo "public tables: $tables"
echo "plans: $plans"
echo "elapsed seconds (RTO evidence): $elapsed"
if [ "$tables" -lt 60 ] || [ "$version" -lt 60 ] || [ "$plans" -lt 1 ]; then
  echo "DRILL FAILED: restored database is incomplete" >&2
  exit 1
fi
echo "DRILL PASSED"
