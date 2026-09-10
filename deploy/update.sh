#!/usr/bin/env bash
# Deploy a new version: pull, install, rebuild the frontend, restart. Run on the server:
#   cd /opt/registrar && bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
backend/.venv/bin/pip install -q -r backend/requirements.txt
(cd frontend && npm ci --silent && npm run build)
sudo systemctl restart registrar
sleep 3
curl -fsS http://127.0.0.1:8000/api/health && echo " restarted"
