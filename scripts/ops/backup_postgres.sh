#!/usr/bin/env bash
# Encrypted logical backup of the production database.
#
# Run daily from a systemd timer on the host.  Use a dedicated read-only role
# (BACKUP_DATABASE_URL), never the application or superuser connection.
# Managed Supabase projects also keep point-in-time recovery; this script is the
# independent, offsite-copyable copy.
set -euo pipefail

# Either BACKUP_DATABASE_URL (reachable Postgres) or, for the self-hosted stack
# where the database is never published, BACKUP_DB_CONTAINER + BACKUP_ROLE_PASSWORD
# (read from /etc/qentry/db-roles.env by the systemd unit).
if [ -z "${BACKUP_DATABASE_URL:-}" ] && [ -z "${BACKUP_DB_CONTAINER:-}" ]; then
  echo "set BACKUP_DATABASE_URL or BACKUP_DB_CONTAINER" >&2; exit 1
fi
: "${BACKUP_GPG_RECIPIENT:?set BACKUP_GPG_RECIPIENT (public key id that encrypts the dump)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/qentry-$stamp.dump.gpg"
tmp="$out.partial"

dump() {
  if [ -n "${BACKUP_DB_CONTAINER:-}" ]; then
    : "${BACKUP_ROLE_PASSWORD:?set BACKUP_ROLE_PASSWORD}"
    docker exec -e PGPASSWORD="$BACKUP_ROLE_PASSWORD" "$BACKUP_DB_CONTAINER" \
      pg_dump --format=custom --no-owner --no-privileges -h 127.0.0.1 -U qentry_backup postgres
  else
    pg_dump --format=custom --no-owner --no-privileges "$BACKUP_DATABASE_URL"
  fi
}

dump \
  | gpg --batch --yes --trust-model always --encrypt --recipient "$BACKUP_GPG_RECIPIENT" \
      --output "$tmp"

# A backup only counts once its archive is readable.  Decrypt to stdout and
# list the table of contents; any corruption fails the job here.
# In container mode the client tools of the matching Postgres version live in
# the container, so verification runs there too (the host needs no client).
if [ -n "${BACKUP_DB_CONTAINER:-}" ]; then
  gpg --batch --quiet --decrypt "$tmp" | docker exec -i "$BACKUP_DB_CONTAINER" pg_restore --list > /dev/null
else
  gpg --batch --quiet --decrypt "$tmp" | pg_restore --list > /dev/null
fi
mv "$tmp" "$out"

# Offsite copy (a backup on the same disk is not a backup).  The hook receives
# the file path, e.g. BACKUP_OFFSITE_CMD='rclone copy "$1" remote:qentry-backups'.
if [ -n "${BACKUP_OFFSITE_CMD:-}" ]; then
  bash -c "$BACKUP_OFFSITE_CMD" _ "$out"
elif [ -n "${BACKUP_ALLOW_LOCAL_ONLY:-}" ]; then
  echo "note: local-only backup (BACKUP_ALLOW_LOCAL_ONLY is set; no offsite copy)"
else
  echo "WARNING: BACKUP_OFFSITE_CMD is not set; this backup exists only on this host" >&2
fi

find "$BACKUP_DIR" -maxdepth 1 -name 'qentry-*.dump.gpg' -mtime +"$BACKUP_RETENTION_DAYS" -delete

echo "backup written: $out ($(stat -c %s "$out") bytes)"
