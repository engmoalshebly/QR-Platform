#!/usr/bin/env bash
# Upload an encrypted archive, verify its remote SHA-256, then publish atomically.
set -euo pipefail
umask 077
: "${BACKUP_SSH_HOST:?set a verified SSH config alias}"
: "${BACKUP_SSH_DIR:?set an absolute remote backup directory}"
source_file="${1:?encrypted backup file required}"
[[ "$BACKUP_SSH_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9_.@-]*$ ]] || { echo 'invalid SSH host alias' >&2; exit 2; }
[[ "$BACKUP_SSH_DIR" =~ ^/[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+)*$ ]] && [[ "/$BACKUP_SSH_DIR/" != *'/../'* ]] && [[ "/$BACKUP_SSH_DIR/" != *'/./'* ]] || { echo 'invalid remote directory' >&2; exit 2; }
name="$(basename -- "$source_file")"
[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*\.gpg$ ]] && [[ "$name" != *'..'* ]] && [ -f "$source_file" ] || { echo 'only encrypted archive files may be uploaded' >&2; exit 2; }
checksum="$(sha256sum -- "$source_file")"; checksum="${checksum%% *}"
ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15)
# The validated destination contains no shell metacharacters. Preserve partial
# files on transport failure for diagnosis; never expose them under final names.
ssh "${ssh_options[@]}" "$BACKUP_SSH_HOST" "umask 077; mkdir -p '$BACKUP_SSH_DIR' && chmod 700 '$BACKUP_SSH_DIR' && cat > '$BACKUP_SSH_DIR/$name.partial'" < "$source_file"
remote="$(ssh "${ssh_options[@]}" "$BACKUP_SSH_HOST" "sha256sum '$BACKUP_SSH_DIR/$name.partial'")"
[ "${remote%% *}" = "$checksum" ] || { echo 'offsite checksum verification failed' >&2; exit 1; }
ssh "${ssh_options[@]}" "$BACKUP_SSH_HOST" "if [ -e '$BACKUP_SSH_DIR/$name' ]; then test \"\$(sha256sum '$BACKUP_SSH_DIR/$name' | cut -d' ' -f1)\" = '$checksum' && rm '$BACKUP_SSH_DIR/$name.partial'; else mv '$BACKUP_SSH_DIR/$name.partial' '$BACKUP_SSH_DIR/$name'; fi"
echo 'offsite encrypted archive verified'
