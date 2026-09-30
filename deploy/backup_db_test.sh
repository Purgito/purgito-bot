#!/bin/bash
# Self-check de backup_db.sh y restore_check.sh, sin datos reales. Correr a mano:
#   bash deploy/backup_db_test.sh
set -euo pipefail
cd "$(dirname "$0")"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir "$tmp/data"
export DB_SRC="$tmp/data/bot.db"
export BACKUP_DIR="$tmp/backups"
export RETENTION_DAYS=14

sqlite3 "$DB_SRC" "CREATE TABLE t(x); INSERT INTO t VALUES (1);"
echo "done" > "$tmp/data/.images_wiped_v2"
touch "$tmp/data/.gitkeep"

bash backup_db.sh
count=$(find "$BACKUP_DIR" -name 'bot-*.db' | wc -l)
[ "$count" -eq 1 ] || { echo "FAIL: no se creo el backup"; exit 1; }

backup_file=$(find "$BACKUP_DIR" -name 'bot-*.db')
rows=$(sqlite3 "$backup_file" "SELECT x FROM t;")
[ "$rows" = "1" ] || { echo "FAIL: el backup no tiene los datos esperados"; exit 1; }

# Flags: entra .images_wiped_v2, no .gitkeep
flags_tar=$(find "$BACKUP_DIR" -name 'bot-*.flags.tar.gz')
[ -n "$flags_tar" ] || { echo "FAIL: no se creo el tar de flags"; exit 1; }
listing=$(tar -tzf "$flags_tar")
echo "$listing" | grep -qx '.images_wiped_v2' || { echo "FAIL: falta el flag en el tar"; exit 1; }
echo "$listing" | grep -q 'gitkeep' && { echo "FAIL: .gitkeep no debe entrar al tar"; exit 1; }

# Prueba de restauración sobre el backup recién hecho
bash restore_check.sh | grep -q '^OK' || { echo "FAIL: restore_check no dio OK"; exit 1; }

# restore_check debe fallar con un backup corrupto
bad="$tmp/bot-corrupto.db"
head -c 4096 /dev/urandom > "$bad"
if bash restore_check.sh "$bad" >/dev/null 2>&1; then
    echo "FAIL: restore_check aceptó un backup corrupto"; exit 1
fi

# Sin flags no debe crear el tar
rm "$tmp/data/.images_wiped_v2"
rm -rf "$BACKUP_DIR"
bash backup_db.sh
[ -z "$(find "$BACKUP_DIR" -name 'bot-*.flags.tar.gz')" ] || { echo "FAIL: creó un tar de flags vacío"; exit 1; }

# Poda de backups viejos (db y tar)
old="$BACKUP_DIR/bot-19990101-000000.db"
old_tar="$BACKUP_DIR/bot-19990101-000000.flags.tar.gz"
touch "$old" "$old_tar"
touch -d '30 days ago' "$old" "$old_tar"
bash backup_db.sh
[ -f "$old" ] && { echo "FAIL: no podo el backup viejo"; exit 1; }
[ -f "$old_tar" ] && { echo "FAIL: no podo el tar viejo"; exit 1; }

# Un origen inexistente debe fallar sin dejar un .db a medias
rm -rf "$BACKUP_DIR"
if DB_SRC="$tmp/data/no-existe/bot.db" bash backup_db.sh >/dev/null 2>&1; then
    echo "FAIL: debía fallar con origen inexistente"; exit 1
fi
[ -z "$(find "$BACKUP_DIR" -name 'bot-*.db' 2>/dev/null)" ] || { echo "FAIL: dejó un .db a medias"; exit 1; }

echo "OK: backup_db.sh y restore_check.sh pasan el self-check"
