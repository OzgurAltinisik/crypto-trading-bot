#!/usr/bin/env bash
# Consistent copy of data/bot.db into data/backups/, keeping the last 14 days.
# Runs daily from cron (see setup-server.sh) and before every update.
set -euo pipefail
cd "$(dirname "$0")/.."

DB=data/bot.db
[ -f "$DB" ] || { echo "$(date -Is) no database yet"; exit 0; }
mkdir -p data/backups
OUT="data/backups/bot-$(date +%F).db"
sqlite3 "$DB" ".backup '$OUT'"          # safe while the engine is writing (WAL)
find data/backups -name 'bot-*.db' -mtime +14 -delete
echo "$(date -Is) backup -> $OUT ($(du -h "$OUT" | cut -f1))"
