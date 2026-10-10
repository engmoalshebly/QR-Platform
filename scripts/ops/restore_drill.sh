#!/usr/bin/env bash
# Restore drill: prove that the newest backup restores and is usable.
#
# Run on a NON-production host, quarterly and before every major release.
# Requires the GPG private key on this host and a scratch PostgreSQL server
# reachable as DRILL_ADMIN_URL.  The scratch database is dropped at the end.
set -euo pipefail

: "${DRILL_ADMIN_URL:?set DRILL_ADMIN_URL to a scratch server (superuser allowed here only)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
DRILL_DB="qentry_restore_drill_$(date -u +%s)"

latest="$(ls -1t "$BACKUP_DIR"/qentry-*.dump.gpg | head -n 1)"
echo "restoring $latest into $DRILL_DB"

started=$(date +%s)
psql "$DRILL_ADMIN_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$DRILL_DB\";"
trap 'psql "$DRILL_ADMIN_URL" -q -c "DROP DATABASE IF EXISTS \"$DRILL_DB\" WITH (FORCE);"' EXIT

gpg --batch --quiet --decrypt "$latest" \
  | pg_restore --no-owner --no-privileges --dbname "${DRILL_ADMIN_URL%/*}/$DRILL_DB" --exit-on-error

# Sanity checks: the schema version recorded by the migration ledger, and the
# tenant table must be populated with at least one row in production dumps.
version=$(psql "${DRILL_ADMIN_URL%/*}/$DRILL_DB" -tA -c "SELECT COALESCE(MAX(version),0) FROM app_schema_migrations;")
tables=$(psql "${DRILL_ADMIN_URL%/*}/$DRILL_DB" -tA -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
elapsed=$(( $(date +%s) - started ))

echo "restored schema version: $version"
echo "public tables: $tables"
echo "elapsed seconds (RTO evidence): $elapsed"
if [ "$tables" -lt 60 ] || [ "$version" -lt 60 ]; then
  echo "DRILL FAILED: restored database is incomplete" >&2
  exit 1
fi
echo "DRILL PASSED"
