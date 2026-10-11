#!/usr/bin/env bash
# Entry point for the scheduled backup (database dump + storage + config).
# Reads /etc/qentry (or QENTRY_ETC_DIR) and ${QENTRY_ETC_DIR}/backup.env.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
export QENTRY_ETC_DIR="${QENTRY_ETC_DIR:-/etc/qentry}"
envval() { grep -m1 "^$1=" "$2" | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
# shellcheck disable=SC1090
[ -r "$QENTRY_ETC_DIR/backup.env" ] && { set -a; . "$QENTRY_ETC_DIR/backup.env"; set +a; }
export BACKUP_ROLE_PASSWORD="$(envval BACKUP_ROLE_PASSWORD "$QENTRY_ETC_DIR/db-roles.env")"
export BACKUP_DB_CONTAINER="${BACKUP_DB_CONTAINER:-qentry-prod-db-1}"
"$here/backup_postgres.sh"
"$here/backup_files.sh"
