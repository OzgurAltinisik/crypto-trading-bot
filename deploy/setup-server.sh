#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server (Hetzner CX22 or similar).
#
#   ssh root@SERVER_IP
#   curl -fsSLO https://raw.githubusercontent.com/OzgurAltinisik/crypto-trading-bot/main/deploy/setup-server.sh
#   less setup-server.sh            # read it first
#   bash setup-server.sh
#
# Installs Docker (official apt repo), enables the firewall (SSH, 80, 443),
# adds 2 GB swap, clones the repo to /opt/cryptobot, creates .env and a daily
# database backup. Safe to run again.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/OzgurAltinisik/crypto-trading-bot.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/cryptobot}"

if [ "$(id -u)" -ne 0 ]; then
  echo "root olarak çalıştır: sudo bash $0" >&2
  exit 1
fi

echo "==> Sistem güncelleniyor"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl git ufw unattended-upgrades sqlite3

echo "==> Docker kuruluyor"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

echo "==> Güvenlik duvarı: SSH, 80, 443"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> Swap (küçük sunucuda arayüz derlemesi için)"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Kod: $REPO_URL ($BRANCH) -> $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
mkdir -p data/backups
chown -R 1000:1000 data            # the container runs as uid 1000

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "    .env oluşturuldu (site herkese açık; davet linki istersen DASHBOARD_KEY doldur)"
fi

echo "==> Günlük veritabanı yedeği (03:15)"
chmod +x deploy/*.sh
cat > /etc/cron.d/cryptobot-backup <<EOF
15 3 * * * root $APP_DIR/deploy/backup.sh >> /var/log/cryptobot-backup.log 2>&1
EOF

IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
cat <<EOF

Kurulum tamam. Kalan adımlar:

  1. nano $APP_DIR/.env
       DOMAIN=$IP.sslip.io                  (ya da kendi domainin)
       PUBLIC_URL=https://<DOMAIN>
       SMTP_* ve MAIL_FROM                  (e-posta bildirimleri, docs/KURULUM.md)
       TELEGRAM_TOKEN=...  TELEGRAM_BOT_USERNAME=...

  2. cd $APP_DIR && docker compose up -d --build

  3. Site: https://<DOMAIN>

EOF
