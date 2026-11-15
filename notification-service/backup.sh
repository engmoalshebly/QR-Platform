#!/usr/bin/env bash
# Consistent SQLite backup, encrypted before it reaches host storage.
set -euo pipefail
: "${BACKUP_GPG_RECIPIENT:?Set the GPG backup recipient}"
umask 077
backup_dir="${NOTIFY_BACKUP_DIR:-$HOME/.qentry/backups}"
mkdir -p "$backup_dir"
backup_file="$backup_dir/notifications-$(date -u +%Y%m%dT%H%M%SZ).sqlite.gpg"
trap 'rm -f "$backup_file.partial"' EXIT
docker exec -i notification-gateway-notification-api-1 python - <<'PY' | gpg --batch --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "$backup_file.partial"
import os,sqlite3,sys,tempfile
source=sqlite3.connect(os.environ.get('NOTIFY_DB','/data/notifications.sqlite'))
with tempfile.TemporaryDirectory() as directory:
    path=directory+'/snapshot.sqlite'
    target=sqlite3.connect(path)
    source.backup(target)
    if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Backup integrity failed')
    target.close()
    with open(path,'rb') as f:
        while chunk:=f.read(65536): sys.stdout.buffer.write(chunk)
source.close()
PY
mv "$backup_file.partial" "$backup_file"
printf 'Encrypted backup saved: %s\n' "$backup_file"
