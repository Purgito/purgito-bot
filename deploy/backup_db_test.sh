#!/bin/bash
# Self-check de backup_db.sh, sin datos reales. Correr a mano:
#   bash deploy/backup_db_test.sh
set -euo pipefail
cd "$(dirname "$0")"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export DB_SRC="$tmp/bot.db"
export BACKUP_DIR="$tmp/backups"
export RETENTION_DAYS=14

sqlite3 "$DB_SRC" "CREATE TABLE t(x); INSERT INTO t VALUES (1);"

bash backup_db.sh
count=$(find "$BACKUP_DIR" -name 'bot-*.db' | wc -l)
[ "$count" -eq 1 ] || { echo "FAIL: no se creo el backup"; exit 1; }

backup_file=$(find "$BACKUP_DIR" -name 'bot-*.db')
rows=$(sqlite3 "$backup_file" "SELECT x FROM t;")
[ "$rows" = "1" ] || { echo "FAIL: el backup no tiene los datos esperados"; exit 1; }

old="$BACKUP_DIR/bot-19990101-000000.db"
touch -d '30 days ago' "$old"
bash backup_db.sh
[ -f "$old" ] && { echo "FAIL: no podo el backup viejo"; exit 1; }

echo "OK: backup_db.sh pasa el self-check"
