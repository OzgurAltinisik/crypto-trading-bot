#!/usr/bin/env bash
# Pull the latest code and restart: bash deploy/update.sh
# Bot state lives in ./data, so open positions survive the restart.
set -euo pipefail
cd "$(dirname "$0")/.."

./deploy/backup.sh
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
