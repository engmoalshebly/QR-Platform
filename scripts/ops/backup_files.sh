#!/usr/bin/env bash
# Encrypted backup of what the database dump does not contain:
#   * the Supabase Storage volume (invitation assets, generated files)
#   * the secrets/config directory (QENTRY_ETC_DIR)
# Same GPG recipient, directory and retention as backup_postgres.sh.
set -euo pipefail
: "${BACKUP_GPG_RECIPIENT:?set BACKUP_GPG_RECIPIENT}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STORAGE_VOLUME="${STORAGE_VOLUME:-qentry-prod_storage_data}"
ETC_DIR="${QENTRY_ETC_DIR:-/etc/qentry}"

umask 077
mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
enc() { gpg --batch --yes --trust-model always --encrypt --recipient "$BACKUP_GPG_RECIPIENT" --output "$1"; }

# Storage volume (streamed through the host; the container only reads it).
out="$BACKUP_DIR/qentry-storage-$stamp.tar.gpg"
docker run --rm -v "$STORAGE_VOLUME":/v:ro alpine:latest tar -C /v -cf - . | enc "$out.partial"
gpg --batch --quiet --decrypt "$out.partial" | tar -tf - >/dev/null
mv "$out.partial" "$out"

# Secrets / configuration.
cfg="$BACKUP_DIR/qentry-config-$stamp.tar.gpg"
tar -C "$(dirname "$ETC_DIR")" -cf - "$(basename "$ETC_DIR")" | enc "$cfg.partial"
gpg --batch --quiet --decrypt "$cfg.partial" | tar -tf - >/dev/null
mv "$cfg.partial" "$cfg"

# The database hook alone is insufficient: assets and config must leave the host too.
if [ -n "${BACKUP_OFFSITE_CMD:-}" ]; then
  bash -c "$BACKUP_OFFSITE_CMD" _ "$out"
  bash -c "$BACKUP_OFFSITE_CMD" _ "$cfg"
elif [[ "${BACKUP_ALLOW_LOCAL_ONLY:-0}" != 1 && "${BACKUP_ALLOW_LOCAL_ONLY:-0}" != true ]]; then
  echo "offsite copy is required unless local-only mode is explicit" >&2
  exit 1
fi

find "$BACKUP_DIR" -maxdepth 1 \( -name 'qentry-storage-*.tar.gpg' -o -name 'qentry-config-*.tar.gpg' \) \
  -mtime +"$BACKUP_RETENTION_DAYS" -delete
echo "files backup written: $out ($(stat -c %s "$out") B), $cfg ($(stat -c %s "$cfg") B)"
