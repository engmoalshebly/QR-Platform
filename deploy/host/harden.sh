#!/usr/bin/env bash
# Host hardening for the Qentry server.  Run once as root:  sudo deploy/host/harden.sh
# Idempotent.  Keeps your current SSH session safe: password login is only
# disabled when the invoking user already has an authorised key, and sshd is
# validated before reload.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
ADMIN_USER="${SUDO_USER:-}"
SSH_PORTS="${SSH_PORTS:-22 954}"

apt-get update -qq
apt-get install -y -qq ufw fail2ban unattended-upgrades

# --- SSH --------------------------------------------------------------------
if [ -n "$ADMIN_USER" ] && [ -s "/home/$ADMIN_USER/.ssh/authorized_keys" ]; then
  cat > /etc/ssh/sshd_config.d/10-qentry-hardening.conf <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
CONF
  # cloud-init may ship a drop-in that sorts earlier and wins
  sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf 2>/dev/null || true
  sshd -t
  systemctl reload ssh
  echo "ssh: key-only, root login disabled (keep this session open and test a new one!)"
else
  echo "ssh: SKIPPED (no authorized_keys for '${ADMIN_USER:-<unknown>}'; refusing to lock you out)" >&2
fi

# --- fail2ban ---------------------------------------------------------------
cat > /etc/fail2ban/jail.d/qentry.local <<CONF
[sshd]
enabled = true
port = ${SSH_PORTS// /,}
maxretry = 4
findtime = 10m
bantime = 1h
CONF
systemctl enable --now fail2ban
systemctl restart fail2ban

# --- firewall ---------------------------------------------------------------
ufw default deny incoming
ufw default allow outgoing
for p in $SSH_PORTS; do ufw allow "$p"/tcp; done
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
# Docker bypasses ufw for published ports.  The production stack publishes only
# 80/443 (Caddy); anything else on 0.0.0.0 is a defect, so list it:
echo "--- ports listening on all interfaces (expect only ${SSH_PORTS}, 80, 443):"
ss -tlnH | awk '$4 !~ /^(127\.|\[::1\])/ {print $4}' | sort -u

# --- unattended security updates -------------------------------------------
dpkg-reconfigure -f noninteractive unattended-upgrades

# --- docker log rotation (so logs can never fill the disk again) -----------
if [ ! -s /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json <<'CONF'
{ "log-driver": "json-file", "log-opts": { "max-size": "50m", "max-file": "3" } }
CONF
  echo "docker daemon.json written; restart docker in a maintenance window"
fi
echo "hardening complete"
