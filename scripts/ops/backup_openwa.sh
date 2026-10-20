#!/usr/bin/env bash
# Encrypted OpenWA database + authentication volume backup. Main SQLite is
# snapshotted through VACUUM INTO rather than archiving a live database file.
set -euo pipefail
: "${BACKUP_GPG_RECIPIENT:?set BACKUP_GPG_RECIPIENT}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
OPENWA_API_CONTAINER="${OPENWA_API_CONTAINER:-openwa-api}"
OPENWA_DB_CONTAINER="${OPENWA_DB_CONTAINER:-openwa-postgres}"
if ! docker inspect "$OPENWA_API_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
  echo "OpenWA not running; skipping its backup"
  exit 0
fi
umask 077
mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
db_out="$BACKUP_DIR/openwa-$stamp.dump.gpg"
data_out="$BACKUP_DIR/openwa-data-$stamp.tar.gpg"
enc() { gpg --batch --yes --trust-model always --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "$1"; }
docker exec "$OPENWA_DB_CONTAINER" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --format=custom --no-owner --no-privileges -h 127.0.0.1 -U "$POSTGRES_USER" "$POSTGRES_DB"' | enc "$db_out.partial"
gpg --batch --quiet --decrypt "$db_out.partial" | docker exec -i "$OPENWA_DB_CONTAINER" pg_restore --list >/dev/null
mv "$db_out.partial" "$db_out"
docker exec "$OPENWA_API_CONTAINER" node -e '
const fs=require("fs"), sqlite3=require("sqlite3");
const target="/tmp/openwa-main.snapshot";
if(fs.existsSync(target))fs.unlinkSync(target);
const db=new sqlite3.Database("/app/data/main.sqlite",sqlite3.OPEN_READONLY);
db.run("VACUUM INTO '\''"+target+"'\''",error=>db.close(()=>{if(error){console.error("SQLite backup failed");process.exit(1)}}));'
trap 'docker exec "$OPENWA_API_CONTAINER" rm -f /tmp/openwa-main.snapshot >/dev/null 2>&1 || true' EXIT
docker exec "$OPENWA_API_CONTAINER" tar --exclude=./main.sqlite --exclude='./main.sqlite-*' --transform='s|^openwa-main.snapshot$|main.sqlite|' -C /app/data -cf - . -C /tmp openwa-main.snapshot | enc "$data_out.partial"
gpg --batch --quiet --decrypt "$data_out.partial" | tar -tf - >/dev/null
mv "$data_out.partial" "$data_out"
if [ -n "${BACKUP_OFFSITE_CMD:-}" ]; then
  bash -c "$BACKUP_OFFSITE_CMD" _ "$db_out"
  bash -c "$BACKUP_OFFSITE_CMD" _ "$data_out"
fi
find "$BACKUP_DIR" -maxdepth 1 \( -name 'openwa-*.dump.gpg' -o -name 'openwa-data-*.tar.gpg' \) -mtime +"$BACKUP_RETENTION_DAYS" -delete
echo "OpenWA encrypted database and session backups verified"
