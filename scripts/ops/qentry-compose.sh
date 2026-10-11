#!/usr/bin/env bash
# Run docker compose for the production stack with the right env file.
#   scripts/ops/qentry-compose.sh up -d
#   scripts/ops/qentry-compose.sh -f deploy/docker-compose.build.yml build
set -euo pipefail
cd "$(dirname "$0")/../.."
# Secrets directory: /etc/qentry (root-owned) by default; override for a
# non-root install.  The compose file reads the same variable.
export QENTRY_ETC_DIR="${QENTRY_ETC_DIR:-/etc/qentry}"
ENV_FILE="${QENTRY_COMPOSE_ENV:-$QENTRY_ETC_DIR/compose.env}"
[ -r "$ENV_FILE" ] || { echo "cannot read $ENV_FILE (run with sudo, or set QENTRY_COMPOSE_ENV)" >&2; exit 1; }
files=(-f docker-compose.prod.yml)
args=()
while [ $# -gt 0 ]; do
  if [ "$1" = "-f" ]; then files+=(-f "$2"); shift 2; else args+=("$1"); shift; fi
done
exec docker compose --env-file "$ENV_FILE" "${files[@]}" "${args[@]}"
