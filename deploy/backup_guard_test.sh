#!/bin/bash
# Self-check de las guardas de backup_db.sh (backup_guard.sh): exclusión mutua, intervalo mínimo,
# copia forzada con motivo y trazabilidad del origen. NO necesita PostgreSQL, age ni red, y no puede
# tocar R2: pg_dump/pg_restore son stubs, no hay R2_BACKUP_BUCKET y el .env es inexistente.
#
#   bash deploy/backup_guard_test.sh
set -euo pipefail
cd "$(dirname "$0")"
script_dir="$(pwd)"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir "$tmp/bin"
cat > "$tmp/bin/pg_dump" <<'STUB'
#!/bin/bash
# pg_dump -Fc --no-owner -f ARCHIVO
while [ $# -gt 0 ]; do [ "$1" = "-f" ] && { printf 'PGDMP-stub' > "$2"; exit 0; }; shift; done
exit 1
STUB
cat > "$tmp/bin/pg_restore" <<'STUB'
#!/bin/bash
echo "; 1; 0 1 TABLE DATA public stub owner"
STUB
chmod +x "$tmp/bin/pg_dump" "$tmp/bin/pg_restore"

export PATH="$tmp/bin:$PATH"
export BACKUP_DIR="$tmp/backups" ENV_FILE="$tmp/no-existe.env" MIN_FREE_MB=1
export PGUSER=stub PGDATABASE=stub PGHOST="$tmp"
unset R2_BACKUP_BUCKET BACKUP_AGE_RECIPIENTS DATABASE_URL TRIGGER_UNIT
export BACKUP_REQUIRE_GUARD=1

fail() { echo "FAIL: $*"; sed 's/^/   | /' "$tmp/out"; exit 1; }
run() { local rc=0; bash "$script_dir/backup_db.sh" > "$tmp/out" 2>&1 || rc=$?; echo "$rc"; }
dumps() { find "$BACKUP_DIR" -maxdepth 1 -name 'purgito-*.dump' | wc -l; }

# 1. Primera copia: corre, registra el origen y marca la copia completa.
[ "$(run)" = 0 ] || fail "la primera copia debía salir bien"
grep -q 'BACKUP ORIGEN: manual/otro' "$tmp/out" || fail "falta la línea de origen"
[ -s "$BACKUP_DIR/.last-ok" ] || fail "no marcó .last-ok"
[ "$(dumps)" = 1 ] || fail "debía haber 1 dump"

# 2. Segunda a mano, sin forzar: se omite con 75, sin crear otro dump.
sleep 1
[ "$(run)" = 75 ] || fail "la segunda copia debía omitirse (75)"
grep -q 'OMITIDO: ya hay una copia completa' "$tmp/out" || fail "falta el motivo de la omisión"
[ "$(dumps)" = 1 ] || fail "la copia omitida creó un dump"

# 3. Con motivo y --forzar (lo que escribe backup_now.sh): corre y deja usuario y motivo en el log.
printf '%s|%s|1|%s\n' "$(date +%s)" "tester" "prueba de mantenimiento" > "$BACKUP_DIR/.manual-reason"
[ "$(run)" = 0 ] || fail "la copia forzada debía salir bien"
grep -q 'MANUAL de tester: prueba de mantenimiento (forzada)' "$tmp/out" || fail "falta el rastro de la copia forzada"
[ ! -e "$BACKUP_DIR/.manual-reason" ] || fail "el motivo no se consumió"
[ "$(dumps)" = 2 ] || fail "debía haber 2 dumps"

# 4. Un motivo viejo (>5 min) no vale: se ignora, se consume y la copia se omite.
printf '%s|%s|1|%s\n' "$(( $(date +%s) - 3600 ))" "tester" "caducado" > "$BACKUP_DIR/.manual-reason"
[ "$(run)" = 75 ] || fail "un motivo caducado no debía forzar"
[ ! -e "$BACKUP_DIR/.manual-reason" ] || fail "el motivo caducado no se consumió"

# 5. Intervalo vencido (última copia de hace 13 h): vuelve a correr; el timer deja constancia.
echo $(( $(date +%s) - 13 * 3600 )) > "$BACKUP_DIR/.last-ok"
sleep 1
TRIGGER_UNIT=purgito-backup.timer bash "$script_dir/backup_db.sh" > "$tmp/out" 2>&1 || fail "pasadas 13 h debía correr"
grep -q 'BACKUP ORIGEN: timer (purgito-backup.timer)' "$tmp/out" || fail "falta el origen timer"

# 6. Exclusión mutua: con el bloqueo tomado por otra copia, esta se omite.
( exec 9> "$BACKUP_DIR/.backup.lock"; flock -x 9; sleep 5 ) &
holder=$!
sleep 1
echo $(( $(date +%s) - 13 * 3600 )) > "$BACKUP_DIR/.last-ok"
[ "$(run)" = 75 ] || fail "con otra copia en curso debía omitirse (75)"
grep -q 'OMITIDO: ya hay una copia en curso' "$tmp/out" || fail "falta el aviso de copia en curso"
kill "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true

# 8. Tope de edad local: tras un apagón largo, las copias locales viejas se eliminan (no la nueva).
unset BACKUP_REQUIRE_GUARD
touch_old() { printf 'PGDMP-stub' > "$BACKUP_DIR/$1"; chmod 600 "$BACKUP_DIR/$1"; }
touch_old purgito-20200101-000000.dump
touch_old purgito-20200102-000000.dump
sleep 1
[ "$(run)" = 0 ] || fail "la copia con copias viejas debía salir bien"
[ ! -e "$BACKUP_DIR/purgito-20200102-000000.dump" ] || fail "una copia local de 2020 sobrevivió a la poda por edad"
[ ! -e "$BACKUP_DIR/purgito-20200101-000000.dump" ] || fail "la copia local más vieja sobrevivió"
[ "$(dumps)" -ge 1 ] || fail "la copia nueva desapareció"
grep -q 'LOCAL PRUNE: borrado purgito-20200102' "$tmp/out" || fail "falta el rastro del borrado por edad"

# 7. Sin las guardas (self-check, uso local): se comporta como siempre, sin .last-ok exigido.
unset BACKUP_REQUIRE_GUARD
rm -f "$BACKUP_DIR/.last-ok"
sleep 1
[ "$(run)" = 0 ] || fail "sin guardas debía correr"
sleep 1
[ "$(run)" = 0 ] || fail "sin guardas, una segunda copia seguida debía correr"

echo "OK backup_guard_test"
