#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 22.04/24.04 server (run as root, from the plunge/ folder you copied to the server):
#     sudo bash deploy/setup-server.sh
# It installs Docker, turns on the firewall (SSH, 80, 443 only), automatic security updates, fail2ban, creates deploy/.env with a
# random admin key, starts the hub + lobby + HTTPS proxy, and schedules a daily backup.
# NOT tested on a real server by the author: read it, run it on a throwaway server first, and check `docker compose ps` at the end.
set -euo pipefail
cd "$(dirname "$0")/.."

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 ufw fail2ban unattended-upgrades curl
systemctl enable --now docker fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades || true

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

if [ ! -f deploy/.env ]; then
  cp deploy/.env.example deploy/.env
  key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -i "s|^PLUNGE_HUB_ADMIN=.*|PLUNGE_HUB_ADMIN=${key}|" deploy/.env
  chmod 600 deploy/.env
  echo "Created deploy/.env with a new admin key (keep it private; it is needed to feature profiles)."
fi

docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build

# daily backup at 03:15, kept 14 days
install -m 755 deploy/backup.sh /usr/local/bin/plunge-backup
( crontab -l 2>/dev/null | grep -v plunge-backup; echo "15 3 * * * /usr/local/bin/plunge-backup" ) | crontab -

echo
docker compose -f deploy/docker-compose.yml ps
echo "Next: check  https://\$(grep ^HUB_DOMAIN deploy/.env | cut -d= -f2)/health  once DNS points at this server."
