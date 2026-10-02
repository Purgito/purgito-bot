#!/bin/bash
# Self-check de backup_db.sh y restore_check.sh. Necesita una base PostgreSQL
# de pruebas (NO la de producción) y una de descarte para la restauración:
#
#   TEST_DATABASE_URL=postgresql://usuario:clave@127.0.0.1/purgito_test \
#   RESTORE_CHECK_DB=purgito_restorecheck bash deploy/backup_db_test.sh
#
# Crea una tabla `selfcheck_t` en la base de pruebas y la borra al terminar.
set -euo pipefail
cd "$(dirname "$0")"

url="${TEST_DATABASE_URL:-}"
if [ -z "$url" ]; then
    echo "SKIP: falta TEST_DATABASE_URL (base PostgreSQL de pruebas)" >&2
    exit 0
fi
export DATABASE_URL="$url"
export RESTORE_CHECK_DB="${RESTORE_CHECK_DB:-purgito_restorecheck}"

tmp=$(mktemp -d)
cleanup() {
    psql "$url" -q -c 'DROP TABLE IF EXISTS selfcheck_t' >/dev/null 2>&1 || true
    rm -rf "$tmp"
}
trap cleanup EXIT

export BACKUP_DIR="$tmp/backups"
export KEEP_LAST=2
# Aislado del entorno real: sin R2_BACKUP_BUCKET ni .env, el backup es solo local.
export ENV_FILE="$tmp/no-existe.env"
unset R2_BACKUP_BUCKET BACKUP_AGE_RECIPIENTS

if ! command -v age-keygen >/dev/null 2>&1; then
    echo "SKIP: falta age (apt install age)" >&2
    exit 0
fi
# Par de claves de prueba: la privada solo existe en este tmp.
age-keygen -o "$tmp/identity.txt" >/dev/null 2>&1
age_pub=$(age-keygen -y "$tmp/identity.txt")

psql "$url" -q -c 'DROP TABLE IF EXISTS selfcheck_t; CREATE TABLE selfcheck_t(x int); INSERT INTO selfcheck_t VALUES (1);'

bash backup_db.sh
count=$(find "$BACKUP_DIR" -name 'purgito-*.dump' | wc -l)
[ "$count" -eq 1 ] || { echo "FAIL: no se creo el backup"; exit 1; }

backup_file=$(find "$BACKUP_DIR" -name 'purgito-*.dump')
pg_restore --data-only -t selfcheck_t -f - "$backup_file" | grep -qx '1' \
    || { echo "FAIL: el backup no tiene los datos esperados"; exit 1; }

# Permisos: el backup y su carpeta son solo del dueño (llevan el corpus y los tokens de webhook)
mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
[ "$(mode "$backup_file")" = "600" ] || { echo "FAIL: el backup no es 0600"; exit 1; }
[ "$(mode "$BACKUP_DIR")" = "700" ] || { echo "FAIL: BACKUP_DIR no es 0700"; exit 1; }

# Prueba de restauración sobre el backup recién hecho (base vacía de Purgito: sin filas exigidas)
RESTORE_REQUIRE_ROWS=0 bash restore_check.sh 2>/dev/null | grep -q '^OK' \
    || { echo "FAIL: restore_check no dio OK"; exit 1; }

# restore_check debe fallar con un backup corrupto
bad="$tmp/purgito-corrupto.dump"
head -c 4096 /dev/urandom > "$bad"
if bash restore_check.sh "$bad" >/dev/null 2>&1; then
    echo "FAIL: restore_check aceptó un backup corrupto"; exit 1
fi

# Retención por cantidad (KEEP_LAST=2): con 1 o 2 backups no se borra nada; al
# aparecer un tercero se borra el más antiguo, sin mirar la edad. Los archivos
# que no son backups no se tocan.
count_backups() { find "$BACKUP_DIR" -maxdepth 1 -name 'purgito-*.dump*' | wc -l | tr -d ' '; }
rm -rf "$BACKUP_DIR"; mkdir -p "$BACKUP_DIR"
touch "$BACKUP_DIR/purgito-19990101-000000.dump" "$BACKUP_DIR/otro-archivo.txt"
echo x > "$BACKUP_DIR/purgito-19990101-000000.dump"
touch -d '3000 days ago' "$BACKUP_DIR/purgito-19990101-000000.dump"   # viejísimo, pero es el único previo
bash backup_db.sh >/dev/null
[ "$(count_backups)" -eq 2 ] || { echo "FAIL: con 1 previo + el nuevo (2) debía conservar ambos"; exit 1; }
[ -f "$BACKUP_DIR/purgito-19990101-000000.dump" ] || { echo "FAIL: borró un backup por viejo con solo 2 en total"; exit 1; }
sleep 1
bash backup_db.sh >/dev/null
[ "$(count_backups)" -eq 2 ] || { echo "FAIL: con 3 backups debía quedar solo 2 (KEEP_LAST=2)"; exit 1; }
[ -f "$BACKUP_DIR/purgito-19990101-000000.dump" ] && { echo "FAIL: no borró el backup más antiguo"; exit 1; }
[ -f "$BACKUP_DIR/otro-archivo.txt" ] || { echo "FAIL: la poda tocó un archivo que no es un backup"; exit 1; }
out=$(KEEP_LAST=0 bash backup_db.sh 2>&1) && { echo "FAIL: aceptó KEEP_LAST=0"; exit 1; }
echo "$out" | grep -q 'KEEP_LAST' || { echo "FAIL: el error de KEEP_LAST no lo nombra"; exit 1; }

# ── Cifrado con age: el backup queda .dump.age, no queda nada en claro, se
# descifra con la privada y restore_check lo restaura (y falla sin la clave).
rm -rf "$BACKUP_DIR"
out=$(BACKUP_AGE_RECIPIENTS="$age_pub" bash backup_db.sh)
echo "$out" | grep -q 'cifrado con age' || { echo "FAIL: no informó el cifrado"; exit 1; }
enc=$(find "$BACKUP_DIR" -name 'purgito-*.dump.age')
[ -n "$enc" ] || { echo "FAIL: no se creó el .dump.age"; exit 1; }
[ -z "$(find "$BACKUP_DIR" -type f ! -name '*.dump.age')" ] || { echo "FAIL: quedó un archivo en claro"; exit 1; }
[ "$(mode "$enc")" = "600" ] || { echo "FAIL: el cifrado no es 0600"; exit 1; }
[ "$(head -c 22 "$enc")" = "age-encryption.org/v1" ] || { echo "FAIL: no es un archivo age"; exit 1; }
AGE_IDENTITY="$tmp/identity.txt" RESTORE_REQUIRE_ROWS=0 bash restore_check.sh "$enc" 2>/dev/null | grep -q '^OK' \
    || { echo "FAIL: restore_check no restauró el backup cifrado"; exit 1; }
if RESTORE_REQUIRE_ROWS=0 bash restore_check.sh "$enc" >/dev/null 2>&1; then
    echo "FAIL: restore_check restauró un backup cifrado sin la clave"; exit 1
fi
age-keygen -o "$tmp/otra.txt" >/dev/null 2>&1
if AGE_IDENTITY="$tmp/otra.txt" RESTORE_REQUIRE_ROWS=0 bash restore_check.sh "$enc" >/dev/null 2>&1; then
    echo "FAIL: restore_check aceptó una clave equivocada"; exit 1
fi
# Con bucket y sin destinatarios: no hay backup y no se sube nada
rm -rf "$BACKUP_DIR"
if R2_BACKUP_BUCKET=purgito-backups PYTHON="$tmp/no-existe" bash backup_db.sh >/dev/null 2>&1; then
    echo "FAIL: hizo backup con bucket y sin destinatarios (subiría en claro)"; exit 1
fi
[ -z "$(find "$BACKUP_DIR" -type f 2>/dev/null)" ] || { echo "FAIL: dejó archivos"; exit 1; }

# Una base inexistente debe fallar sin dejar un .dump a medias
rm -rf "$BACKUP_DIR"
if DATABASE_URL="${url%/*}/purgito_no_existe_selfcheck" bash backup_db.sh >/dev/null 2>&1; then
    echo "FAIL: debía fallar con una base inexistente"; exit 1
fi
[ -z "$(find "$BACKUP_DIR" -name 'purgito-*.dump' 2>/dev/null)" ] || { echo "FAIL: dejó un .dump a medias"; exit 1; }

# Sin DATABASE_URL (ni en el entorno ni en el .env) falla con un mensaje claro
out=$(DATABASE_URL='' bash backup_db.sh 2>&1) && { echo "FAIL: debía fallar sin DATABASE_URL"; exit 1; }
echo "$out" | grep -q 'falta DATABASE_URL' || { echo "FAIL: el error no menciona DATABASE_URL"; exit 1; }

# DATABASE_URL también se lee del .env (cron no lo carga)
printf 'DATABASE_URL="%s"  # prod\n' "$url" > "$tmp/with-db.env"
rm -rf "$BACKUP_DIR"
DATABASE_URL='' ENV_FILE="$tmp/with-db.env" bash backup_db.sh >/dev/null \
    || { echo "FAIL: no leyó DATABASE_URL del .env"; exit 1; }

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

# Con el bucket configurado y la subida OK: sube el dump
rm -rf "$BACKUP_DIR"; : > "$calls"
out=$(R2_BACKUP_BUCKET=purgito-backups BACKUP_AGE_RECIPIENTS="$age_pub" PYTHON="$fake_ok" bash backup_db.sh)
echo "$out" | grep -q 'subido a R2 (purgito-backups)' || { echo "FAIL: no informó la subida"; exit 1; }
grep -qx 'upload' "$calls" || { echo "FAIL: no invocó el uploader"; exit 1; }
grep -q 'purgito-.*\.dump\.age$' "$calls" || { echo "FAIL: no subió el dump cifrado"; exit 1; }

# Subida fallida: error explícito, sin "OK backup", el backup local se conserva y
# NO se poda nada (tampoco los viejos, que podrían no haber llegado nunca a R2)
rm -rf "$BACKUP_DIR"; mkdir -p "$BACKUP_DIR"
old="$BACKUP_DIR/purgito-19990101-000000.dump"
touch "$old"; touch -d '30 days ago' "$old"
if out=$(R2_BACKUP_BUCKET=purgito-backups BACKUP_AGE_RECIPIENTS="$age_pub" PYTHON="$fake_fail" bash backup_db.sh 2>&1); then
    echo "FAIL: el backup reportó éxito con la subida a R2 caída"; exit 1
fi
echo "$out" | grep -q ' OK backup -> ' && { echo "FAIL: imprimió OK pese a que la subida falló"; exit 1; }
echo "$out" | grep -q 'NO subió a R2' || { echo "FAIL: el error no dice que la subida falló"; exit 1; }
[ "$(find "$BACKUP_DIR" -name 'purgito-2*.dump.age' | wc -l)" -eq 1 ] || { echo "FAIL: el backup local no se conservó"; exit 1; }
[ -f "$old" ] || { echo "FAIL: podó un backup viejo con la subida fallida"; exit 1; }

# R2_BACKUP_BUCKET también se lee del .env
printf 'DATABASE_URL=%s\nR2_BACKUP_BUCKET="purgito-backups"  # privado\n' "$url" > "$tmp/with-bucket.env"
rm -rf "$BACKUP_DIR"
if DATABASE_URL='' BACKUP_AGE_RECIPIENTS="$age_pub" ENV_FILE="$tmp/with-bucket.env" PYTHON="$fake_fail" bash backup_db.sh >/dev/null 2>&1; then
    echo "FAIL: no leyó R2_BACKUP_BUCKET del .env"; exit 1
fi
printf 'DATABASE_URL=%s\nR2_BACKUP_BUCKET=\n' "$url" > "$tmp/empty-bucket.env"
rm -rf "$BACKUP_DIR"
DATABASE_URL='' ENV_FILE="$tmp/empty-bucket.env" PYTHON="$fake_fail" bash backup_db.sh >/dev/null \
    || { echo "FAIL: un bucket vacío en el .env debe dejar el backup solo local"; exit 1; }

echo "OK: backup_db.sh y restore_check.sh pasan el self-check"
