#!/usr/bin/env bash
# Local monitor: public readiness, container health, disk space, last backup age.
# On a problem it e-mails the platform admin through the same SMTP account the
# platform uses (at most once per ALERT_COOLDOWN_MIN minutes per problem set).
set -uo pipefail
ETC="${QENTRY_ETC_DIR:-/etc/qentry}"
URL="${HEALTH_URL:-}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/qentry}"
DISK_LIMIT="${DISK_LIMIT_PERCENT:-85}"
BACKUP_MAX_AGE_H="${BACKUP_MAX_AGE_HOURS:-13}"
COOLDOWN="${ALERT_COOLDOWN_MIN:-360}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/qentry-healthcheck"
mkdir -p "$STATE"
envval() { grep -m1 "^$1=" "$2" | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
[ -n "$URL" ] || URL="https://$(envval QENTRY_DOMAIN "$ETC/compose.env")/health/ready"

problems=()
code=$(curl -s -o /tmp/qentry-ready.$$ -m 20 -w '%{http_code}' "$URL" || true)
[ "$code" = 200 ] || problems+=("readiness $URL returned HTTP ${code:-none}: $(head -c 200 /tmp/qentry-ready.$$ 2>/dev/null)")
rm -f /tmp/qentry-ready.$$

bad=$(docker ps -a --filter name=qentry-prod- --format '{{.Names}} {{.Status}}' | grep -vE 'Up .*(healthy)?\)?$' | grep -E 'unhealthy|Exited|Restarting|Created' || true)
[ -z "$bad" ] || problems+=("containers: $(echo "$bad" | tr '\n' ';')")

used=$(df --output=pcent / | tail -1 | tr -dc '0-9')
[ "$used" -lt "$DISK_LIMIT" ] || problems+=("disk usage ${used}% (limit ${DISK_LIMIT}%)")

if [ -d "$BACKUP_DIR" ]; then
  newest=$(find "$BACKUP_DIR" -maxdepth 1 -name 'qentry-*.dump.gpg' -printf '%T@\n' | sort -n | tail -1)
  if [ -z "$newest" ]; then problems+=("no database backup found in $BACKUP_DIR")
  else age=$(( ($(date +%s) - ${newest%.*}) / 3600 )); [ "$age" -lt "$BACKUP_MAX_AGE_H" ] || problems+=("latest backup is ${age}h old")
  fi
fi

if [ ${#problems[@]} -eq 0 ]; then rm -f "$STATE/last_alert"; echo "ok"; exit 0; fi
msg=$(printf '%s\n' "${problems[@]}")
echo "PROBLEMS:"; echo "$msg"

sig=$(echo "$msg" | sha256sum | cut -c1-16)
now=$(date +%s)
if [ -f "$STATE/last_alert" ]; then
  read -r last_sig last_ts < "$STATE/last_alert"
  [ "$last_sig" = "$sig" ] && [ $(( (now - last_ts) / 60 )) -lt "$COOLDOWN" ] && exit 1
fi
APP_ENV_FILE="$ETC/app.env" ALERT_BODY="$msg" python3 - <<'PY' && echo "$sig $now" > "$STATE/last_alert"
import os, smtplib, ssl
from email.message import EmailMessage
def val(k):
    for l in open(os.environ["APP_ENV_FILE"]):
        if l.startswith(k + "="): return l.split("=", 1)[1].strip().strip('"')
    return ""
to = val("PLATFORM_SUPERADMIN_EMAILS").split(",")[0].strip()
m = EmailMessage()
m["From"], m["To"], m["Subject"] = val("SMTP_USER"), to, "[Qentry] production alert"
m.set_content(os.environ["ALERT_BODY"])
with smtplib.SMTP(val("SMTP_HOST"), int(val("SMTP_PORT") or 587), timeout=20) as s:
    s.starttls(context=ssl.create_default_context()); s.login(val("SMTP_USER"), val("SMTP_PASS")); s.send_message(m)
print("alert sent to", to)
PY
exit 1
