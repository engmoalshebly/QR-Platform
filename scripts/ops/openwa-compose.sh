#!/usr/bin/env bash
# Manage the private OpenWA deployment with the same secrets directory as Qentry.
set -euo pipefail
cd "$(dirname "$0")/../.."
export QENTRY_ETC_DIR="${QENTRY_ETC_DIR:-/etc/qentry}"
openwa_env_file="${OPENWA_COMPOSE_ENV:-$QENTRY_ETC_DIR/openwa.env}"
[ -r "$openwa_env_file" ] || { echo "cannot read private OpenWA environment" >&2; exit 1; }
exec docker compose --env-file "$openwa_env_file" -p openwa-prod \
  -f OpenWA/docker-compose.yml -f OpenWA/docker-compose.internal.yml --profile postgres "$@"
