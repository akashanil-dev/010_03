#!/usr/bin/env bash
# One-time setup of TallyTime on a fresh Oracle Cloud Ampere VM (Ubuntu 24.04, ARM64). Run as root:
#
#     sudo bash deploy/setup.sh
#
# Safe to run again: it skips what is already done. See DEPLOY.md for the steps around it.
set -euo pipefail

DOMAIN=${DOMAIN:-tallytime.akashanil.dev}
REPO=${REPO:-https://github.com/akashanil-dev/010_03.git}
APP=/opt/tallytime
MODEL=${MODEL:-granite4:micro}

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
[ "$(id -u)" = 0 ] || { echo "Run as root: sudo bash deploy/setup.sh"; exit 1; }

say "System packages and automatic security updates"
apt-get update -q
apt-get install -y -q git curl sqlite3 fail2ban unattended-upgrades iptables-persistent \
  debian-keyring debian-archive-keyring apt-transport-https libgl1 libglib2.0-0
dpkg-reconfigure -f noninteractive unattended-upgrades

say "Firewall: open HTTP and HTTPS (Oracle's Ubuntu images block them in iptables)"
for port in 80 443; do
  iptables -C INPUT -p tcp --dport $port -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -p tcp --dport $port -m conntrack --ctstate NEW -j ACCEPT
done
iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p udp --dport 443 -j ACCEPT   # HTTP/3
netfilter-persistent save

say "Caddy (HTTPS reverse proxy)"
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

say "Ollama and the Granite model (listens on 127.0.0.1 only)"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/tallytime.conf <<EOF
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_KEEP_ALIVE=24h"
Environment="OLLAMA_NUM_PARALLEL=1"
EOF
systemctl daemon-reload
systemctl enable --now ollama
sleep 3
ollama pull "$MODEL"

say "App user, code and Python environment"
id tallytime >/dev/null 2>&1 || useradd --system --create-home --home-dir "$APP" --shell /usr/sbin/nologin tallytime
if [ ! -d "$APP/.git" ]; then
  sudo -u tallytime git clone "$REPO" "$APP/src.tmp"
  sudo -u tallytime bash -c "shopt -s dotglob; mv $APP/src.tmp/* $APP/ && rmdir $APP/src.tmp"
fi
sudo -u tallytime mkdir -p "$APP/data" "$APP/.cache"
if [ ! -x "$APP/.local/bin/uv" ]; then
  sudo -u tallytime bash -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
fi
UV="$APP/.local/bin/uv"
cd "$APP"
sudo -u tallytime "$UV" venv --python 3.12 .venv
sudo -u tallytime "$UV" pip install --python .venv/bin/python \
  --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match -r requirements.txt
sudo -u tallytime HOME="$APP" .venv/bin/docling-tools models download
# OCR downloads its models on first use; do it now, while the environment is still writable
sudo -u tallytime HOME="$APP" .venv/bin/python -c \
  "from pathlib import Path; from app.parsing import to_markdown; to_markdown(Path('data/demo/mixed/03_packing_list_photo.jpg'))"

say "Configuration (.env)"
if [ ! -f "$APP/.env" ]; then
  sudo -u tallytime cp .env.example .env
  KEYS=$(sudo -u tallytime .venv/bin/python -m app.notify keys)
  sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=https://$DOMAIN|" .env
  sed -i "s|^VAPID_PUBLIC_KEY=.*|$(echo "$KEYS" | grep PUBLIC)|; s|^VAPID_PRIVATE_KEY=.*|$(echo "$KEYS" | grep PRIVATE)|" .env
  chmod 600 .env
  echo "Created $APP/.env with push keys. Fill in the email (Oracle Email Delivery) and Turnstile settings before going live."
fi

say "Services"
sed "s/tallytime.akashanil.dev/$DOMAIN/" deploy/Caddyfile > /etc/caddy/Caddyfile
mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy
cp deploy/tallytime-web.service deploy/tallytime-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tallytime-worker tallytime-web
systemctl reload caddy || systemctl restart caddy

say "Pre-reading the demo shipments in the background, so demos are instant (about an hour)"
sudo -u tallytime HOME="$APP" nohup .venv/bin/python -m app.pipeline data/demo/*/* > "$APP/data/demo-cache.log" 2>&1 &

say "Logs kept 30 days; nightly account-only backup"
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nMaxRetentionSec=30day\n' > /etc/systemd/journald.conf.d/tallytime.conf
systemctl restart systemd-journald
echo "15 2 * * * root $APP/deploy/backup.sh" > /etc/cron.d/tallytime-backup

say "Done"
echo "Check:  curl -s https://$DOMAIN/healthz"
echo "Logs:   journalctl -u tallytime-web -u tallytime-worker -f"
