#!/usr/bin/env bash
# First-time setup on an Ubuntu EC2 host. Run as the ubuntu user from the repo root after `git clone`:
#   sudo bash deploy/setup.sh
# Re-running is safe; use deploy/update.sh for later releases.
set -euo pipefail

APP_DIR=/opt/registrar
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== system packages"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip ca-certificates curl git rsync
if ! command -v node >/dev/null || [ "$(node -v | cut -c2-3)" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "== app directory $APP_DIR"
mkdir -p "$APP_DIR"
if [ "$REPO_DIR" != "$APP_DIR" ]; then
  rsync -a --delete --exclude .git --exclude node_modules --exclude .venv --exclude 'backend/.env' --exclude 'backend/data' "$REPO_DIR"/ "$APP_DIR"/
fi
chown -R ubuntu:ubuntu "$APP_DIR"

echo "== backend"
cd "$APP_DIR/backend"
sudo -u ubuntu python3 -m venv .venv
sudo -u ubuntu .venv/bin/pip install --upgrade pip
sudo -u ubuntu .venv/bin/pip install -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  echo "!! Created backend/.env from the example. Fill in GEMINI_API_KEY, STORAGE_BACKEND=s3, S3_BUCKET, AWS keys, then: sudo systemctl restart registrar"
fi

echo "== frontend build"
cd "$APP_DIR/frontend"
sudo -u ubuntu npm ci
sudo -u ubuntu npm run build

echo "== service"
cp "$APP_DIR/deploy/registrar.service" /etc/systemd/system/registrar.service
systemctl daemon-reload
systemctl enable registrar
systemctl restart registrar
sleep 3
systemctl --no-pager status registrar | head -5
curl -fsS http://127.0.0.1:8000/api/health && echo
echo "== done. Open http://$(curl -fsS http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}'):8000"
