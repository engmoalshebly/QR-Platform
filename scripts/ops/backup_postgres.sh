#!/usr/bin/env bash
# Encrypted logical backup of the production database.
#
# Run daily from a systemd timer on the host.  Use a dedicated read-only role
# (BACKUP_DATABASE_URL), never the application or superuser connection.
# Managed Supabase projects also keep point-in-time recovery; this script is the
# independent, offsite-copyable copy.
set -euo pipefail

: "${BACKUP_DATABASE_URL:?set BACKUP_DATABASE_URL to the read-only backup role}"
: "${BACKUP_GPG_RECIPIENT:?set BACKUP_GPG_RECIPIENT (public key id that encrypts the dump)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

umask 077
mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/qentry-$stamp.dump.gpg"
tmp="$out.partial"

pg_dump --format=custom --no-owner --no-privileges "$BACKUP_DATABASE_URL" \
  | gpg --batch --yes --trust-model always --encrypt --recipient "$BACKUP_GPG_RECIPIENT" \
      --output "$tmp"

# A backup only counts once its archive is readable.  Decrypt to stdout and
# list the table of contents; any corruption fails the job here.
gpg --batch --quiet --decrypt "$tmp" | pg_restore --list > /dev/null
mv "$tmp" "$out"

find "$BACKUP_DIR" -maxdepth 1 -name 'qentry-*.dump.gpg' -mtime +"$BACKUP_RETENTION_DAYS" -delete

echo "backup written: $out ($(stat -c %s "$out") bytes)"
