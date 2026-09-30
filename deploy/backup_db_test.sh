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
# Aislado del entorno real: sin R2_BACKUP_BUCKET ni .env, el backup es solo local.
export ENV_FILE="$tmp/no-existe.env"
unset R2_BACKUP_BUCKET

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

# Permisos: el backup y su carpeta son solo del dueño (llevan lo mismo que bot.db)
mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
[ "$(mode "$backup_file")" = "600" ] || { echo "FAIL: el backup no es 0600"; exit 1; }
[ "$(mode "$flags_tar")" = "600" ] || { echo "FAIL: el tar de flags no es 0600"; exit 1; }
[ "$(mode "$BACKUP_DIR")" = "700" ] || { echo "FAIL: BACKUP_DIR no es 0700"; exit 1; }

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

# Sin R2_BACKUP_BUCKET el backup es solo local, y el log lo dice
rm -rf "$BACKUP_DIR"
out=$(bash backup_db.sh)
echo "$out" | grep -q 'solo local' || { echo "FAIL: no avisó que quedó solo local"; exit 1; }

# ── Subida a R2 (bucket privado). El intérprete es un stub: no hay red ni boto3.
fake_ok="$tmp/fake-python-ok"
fake_fail="$tmp/fake-python-fail"
calls="$tmp/uploader-calls.log"
printf '#!/bin/bash\nprintf "%%s\\n" "$@" >> "%s"\n' "$calls" > "$fake_ok"
printf '#!/bin/bash\necho "fallo simulado de R2" >&2\nexit 1\n' > "$fake_fail"
chmod +x "$fake_ok" "$fake_fail"

# Con el bucket configurado y la subida OK: sube el tar de flags ANTES que la base
echo "done" > "$tmp/data/.images_wiped_v2"
rm -rf "$BACKUP_DIR"; : > "$calls"
out=$(R2_BACKUP_BUCKET=purgito-backups PYTHON="$fake_ok" bash backup_db.sh)
echo "$out" | grep -q 'subido a R2 (purgito-backups)' || { echo "FAIL: no informó la subida"; exit 1; }
grep -qx 'upload' "$calls" || { echo "FAIL: no invocó el uploader"; exit 1; }
flags_line=$(grep -n 'flags.tar.gz$' "$calls" | head -1 | cut -d: -f1)
db_line=$(grep -n '\.db$' "$calls" | head -1 | cut -d: -f1)
[ -n "$flags_line" ] && [ -n "$db_line" ] && [ "$flags_line" -lt "$db_line" ] \
    || { echo "FAIL: los flags deben subirse antes que la base"; exit 1; }

# Subida fallida: error explícito, sin "OK backup", el backup local se conserva y
# NO se poda nada (tampoco los viejos, que podrían no haber llegado nunca a R2)
rm -rf "$BACKUP_DIR"; mkdir -p "$BACKUP_DIR"
old="$BACKUP_DIR/bot-19990101-000000.db"
touch "$old"; touch -d '30 days ago' "$old"
if out=$(R2_BACKUP_BUCKET=purgito-backups PYTHON="$fake_fail" bash backup_db.sh 2>&1); then
    echo "FAIL: el backup reportó éxito con la subida a R2 caída"; exit 1
fi
echo "$out" | grep -q ' OK backup -> ' && { echo "FAIL: imprimió OK pese a que la subida falló"; exit 1; }
echo "$out" | grep -q 'NO subió a R2' || { echo "FAIL: el error no dice que la subida falló"; exit 1; }
[ "$(find "$BACKUP_DIR" -name 'bot-2*.db' | wc -l)" -eq 1 ] || { echo "FAIL: el backup local no se conservó"; exit 1; }
[ -f "$old" ] || { echo "FAIL: podó un backup viejo con la subida fallida"; exit 1; }

# R2_BACKUP_BUCKET también se lee del .env (cron no lo carga)
printf 'R2_BACKUP_BUCKET="purgito-backups"  # privado\n' > "$tmp/with-bucket.env"
rm -rf "$BACKUP_DIR"
if ENV_FILE="$tmp/with-bucket.env" PYTHON="$fake_fail" bash backup_db.sh >/dev/null 2>&1; then
    echo "FAIL: no leyó R2_BACKUP_BUCKET del .env"; exit 1
fi
printf 'R2_BACKUP_BUCKET=\n' > "$tmp/empty-bucket.env"
rm -rf "$BACKUP_DIR"
ENV_FILE="$tmp/empty-bucket.env" PYTHON="$fake_fail" bash backup_db.sh >/dev/null \
    || { echo "FAIL: un bucket vacío en el .env debe dejar el backup solo local"; exit 1; }

echo "OK: backup_db.sh y restore_check.sh pasan el self-check"
