#!/usr/bin/env bash
# Restore only into a disposable, network-isolated database. Never writes production.
set -euo pipefail
umask 077
BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
IMAGE="${DRILL_IMAGE:-public.ecr.aws/supabase/postgres:17.6.1.140}"
NAME="qentry-restore-drill-$$"
MIN_VERSION="${DRILL_MIN_VERSION:-60}"
[[ "$MIN_VERSION" =~ ^[0-9]+$ ]] || { echo 'invalid DRILL_MIN_VERSION' >&2; exit 1; }
latest="${DRILL_BACKUP_FILE:-}"
if [ -z "$latest" ]; then
  latest="$(python3 - "$BACKUP_DIR" <<'PY'
from pathlib import Path
import sys
files=list(Path(sys.argv[1]).glob('qentry-*.dump.gpg'))
print(max(files,key=lambda p:p.stat().st_mtime) if files else '')
PY
)"
fi
[ -n "$latest" ] && [ -r "$latest" ] || { echo 'no readable database backup found' >&2; exit 1; }
work="$(mktemp -d "${DRILL_WORK_ROOT:-$BACKUP_DIR}/.restore-drill-XXXXXXXX")"
cleanup() {
  if [ "${DRILL_KEEP_CONTAINER:-0}" != 1 ]; then docker rm -f "$NAME" >/dev/null 2>&1 || true; fi
  rm -rf -- "$work"
}
trap cleanup EXIT
started=$(date +%s)
# Decryption failure cannot be hidden by a later successful SQL query.
gpg --batch --quiet --output "$work/database.dump" --decrypt "$latest" 2>"$work/decrypt.log" || { echo 'DRILL FAILED: decryption failed' >&2; exit 1; }
docker run -d --name "$NAME" --network none -e POSTGRES_PASSWORD=drill "$IMAGE" > /dev/null
for _ in $(seq 1 60); do
  if docker exec "$NAME" pg_isready -U postgres -h localhost >/dev/null 2>&1; then break; fi
  sleep 2
done
docker exec "$NAME" pg_isready -U postgres -h localhost >/dev/null
# Supabase's image provisions the platform roles; public PostgreSQL fixtures may not.
admin="${DRILL_DB_ADMIN:-supabase_admin}"
psql_admin() { docker exec -i -e PGPASSWORD=drill "$NAME" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$admin" -d "$1" "${@:2}"; }
psql_admin postgres -c 'CREATE DATABASE restore' > /dev/null
psql_admin restore -c "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='qentry_app') THEN CREATE ROLE qentry_app NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='qentry_backup') THEN CREATE ROLE qentry_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS; END IF; END \$\$;" > /dev/null
# Fresh target + exit-on-error: schema/data failures are never filtered or ignored.
if ! docker exec -i -e PGPASSWORD=drill "$NAME" pg_restore -h 127.0.0.1 -U "$admin" -d restore --no-owner --exit-on-error < "$work/database.dump" > "$work/restore.log" 2>&1; then
  echo 'DRILL FAILED: pg_restore rejected the archive; no production changes' >&2
  if [ -n "${DRILL_ERROR_LOG:-}" ]; then cp "$work/restore.log" "$DRILL_ERROR_LOG"; chmod 600 "$DRILL_ERROR_LOG"; fi
  exit 1
fi
version="$(psql_admin restore -tAc 'SELECT COALESCE(MAX(version),0) FROM app_schema_migrations;')"
tables="$(psql_admin restore -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
plans="$(psql_admin restore -tAc 'SELECT count(*) FROM plans;')"
if [ "$tables" -lt 60 ] || [ "$version" -lt "$MIN_VERSION" ] || [ "$plans" -lt 1 ]; then
  echo 'DRILL FAILED: restored schema or baseline data is incomplete' >&2; exit 1
fi
if [ "$MIN_VERSION" -ge 83 ]; then
  required="$(psql_admin restore -tAc "SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('generation_operations','generation_imports','generation_import_rows','generation_uploads','generation_upload_rows','generation_storage_objects','generation_artifacts','generation_artifact_items') AND relrowsecurity AND relforcerowsecurity;")"
  [ "$required" -eq 8 ] || { echo 'DRILL FAILED: missing generation RLS tables' >&2; exit 1; }
fi
app_acl="$(psql_admin restore -tAc "SELECT has_table_privilege('qentry_app','public.invitations','SELECT');")"
if [ "${DRILL_REQUIRE_APP_ACL:-1}" = 1 ] && [ "$app_acl" != t ]; then
  echo 'DRILL FAILED: archive did not restore application privileges' >&2; exit 1
fi
artifact_manifest="0:"
if [ "$version" -ge 79 ]; then
  artifact_manifest="$(psql_admin restore -tAc "SELECT count(*)||':'||md5(COALESCE(string_agg(storage_path||':'||byte_size||':'||sha256,'|' ORDER BY storage_path),'')) FROM generation_artifacts WHERE status='verified';")"
fi
elapsed=$(( $(date +%s)-started ))
python3 - "$version" "$tables" "$plans" "$elapsed" "$NAME" "${DRILL_REPORT:-}" "$app_acl" "$artifact_manifest" <<'PY'
import json,sys
from pathlib import Path
r=dict(result='passed',schema_version=int(sys.argv[1]),public_tables=int(sys.argv[2]),plans=int(sys.argv[3]),restore_seconds=int(sys.argv[4]),container=sys.argv[5],production_modified=False,application_select_privilege_restored=sys.argv[7]=='t')
r['verified_artifacts']=int(sys.argv[8].split(':',1)[0])
r['artifact_metadata_fingerprint']=sys.argv[8].split(':',1)[1]
if sys.argv[6]: Path(sys.argv[6]).write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r))
PY
