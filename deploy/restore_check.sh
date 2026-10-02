#!/bin/bash
# Prueba de restauración: toma el backup más reciente de BACKUP_DIR (o el
# archivo que pases como primer argumento) y lo restaura en una base de
# descarte (<base>_restorecheck), nunca en la real. Es seguro correrlo en
# cualquier momento: no toca la base de producción ni el bot en marcha.
#
#   deploy/restore_check.sh                       # último backup de BACKUP_DIR
#   deploy/restore_check.sh /ruta/purgito-X.dump[.age]   # uno puntual
#   deploy/restore_check.sh r2:latest             # baja el último de R2 y lo prueba
#   deploy/restore_check.sh r2:purgito-X.dump.age # uno puntual de R2
#
# Los backups .dump.age están cifrados: hace falta la clave PRIVADA, que no vive
# en el servidor de producción. Pásala con AGE_IDENTITY=/ruta/a/la/clave.txt
# (cópiala temporalmente a donde corras la prueba; en un entorno de prueba, no en
# producción). El descifrado va a un directorio temporal 0700 que se borra al
# terminar, salga como salga.
#
# Verifica que pg_restore lo cargue sin errores, que existan las tablas y que
# la suma de filas no sea 0 (con RESTORE_REQUIRE_ROWS=0 se acepta una base vacía,
# para el self-check). Sale con código != 0 si algo falla. Correrlo cada tanto
# es lo que distingue "tengo backups" de "mis backups se pueden restaurar".
#
# La base de descarte tiene que existir y ser del mismo usuario (se crea una
# vez, ver DEPLOY.md § "Restaurar"): CREATE DATABASE <base>_restorecheck OWNER <usuario>.
# Variables: DATABASE_URL (default: la del .env), RESTORE_CHECK_DB (nombre de la
# base de descarte), BACKUP_DIR, ENV_FILE.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$HOME/purgito-bot-backups}"
ENV_FILE="${ENV_FILE:-$script_dir/../.env}"

env_value() {
    [ -f "$ENV_FILE" ] || return 0
    sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=(.*)\$/\\2/p" "$ENV_FILE" | tail -n 1 \
        | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//' \
            -e 's/^"(.*)"$/\1/' -e "s/^'(.*)'\$/\\1/"
}

umask 077
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
PYTHON="${PYTHON:-$script_dir/../.venv/bin/python}"
AGE="${AGE:-age}"

if [ "$#" -ge 1 ] && [[ "$1" == r2:* ]]; then
    name="${1#r2:}"
    if ! "$PYTHON" "$script_dir/../scripts/r2_backup.py" download "$name" --dest "$workdir" >&2; then
        echo "FAIL: no se pudo bajar $name de R2" >&2
        exit 1
    fi
    backup="$(find "$workdir" -maxdepth 1 -type f \( -name 'purgito-*.dump' -o -name 'purgito-*.dump.age' \) | sort | tail -n 1)"
elif [ "$#" -ge 1 ]; then
    backup="$1"
else
    backup="$(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'purgito-*.dump' -o -name 'purgito-*.dump.age' \) 2>/dev/null | sort | tail -n 1)"
fi
if [ -z "${backup:-}" ] || [ ! -f "$backup" ]; then
    echo "FAIL: no hay backup que verificar (BACKUP_DIR=$BACKUP_DIR)" >&2
    exit 1
fi

# Cifrado con age: se descifra a un temporal (0600 en $workdir 0700).
original="$backup"
if [[ "$backup" == *.age ]]; then
    if [ -z "${AGE_IDENTITY:-}" ] || [ ! -f "$AGE_IDENTITY" ]; then
        echo "FAIL: $backup está cifrado: falta AGE_IDENTITY=/ruta/a/la/clave-privada.txt" >&2
        exit 1
    fi
    if ! "$AGE" -d -i "$AGE_IDENTITY" -o "$workdir/restore.dump" "$backup" 2>/dev/null; then
        echo "FAIL: no se pudo descifrar $backup con esa clave" >&2
        exit 1
    fi
    backup="$workdir/restore.dump"
fi

database_url="${DATABASE_URL:-}"
[ -n "$database_url" ] || database_url="$(env_value DATABASE_URL)"
re='^postgres(ql)?://([^:@/]+)(:([^@]*))?@([^:/]+)(:([0-9]+))?/([^?]+)'
if [[ ! "$database_url" =~ $re ]]; then
    echo "FAIL: falta DATABASE_URL con la forma postgresql://usuario:clave@host:puerto/base" >&2
    exit 1
fi
export PGUSER="${BASH_REMATCH[2]}"
PGPASSWORD="$(printf '%b' "${BASH_REMATCH[4]//%/\\x}")"
export PGPASSWORD
export PGHOST="${BASH_REMATCH[5]}"
export PGPORT="${BASH_REMATCH[7]:-5432}"
scratch="${RESTORE_CHECK_DB:-${BASH_REMATCH[8]}_restorecheck}"
export PGDATABASE="$scratch"

if [ "$scratch" = "${BASH_REMATCH[8]}" ]; then
    echo "FAIL: la base de descarte no puede ser la real" >&2
    exit 1
fi

# 1. Estructura legible
if ! pg_restore --list "$backup" >/dev/null 2>&1; then
    echo "FAIL: pg_restore no puede leer $backup" >&2
    exit 1
fi

# 2. Restauración real sobre la base de descarte (la deja limpia antes)
PGOPTIONS='-c client_min_messages=warning' psql -v ON_ERROR_STOP=1 -q -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;' >/dev/null
if ! pg_restore --no-owner --exit-on-error -d "$scratch" "$backup" >/dev/null 2>&1; then
    echo "FAIL: pg_restore falló restaurando $backup en $scratch" >&2
    exit 1
fi

tables="$(psql -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [ "$tables" -lt 1 ]; then
    echo "FAIL: $backup no tiene tablas" >&2
    exit 1
fi
# Conteo real (no la estimación de pg_stat) de las tablas que importan
core="$(psql -At -c "SELECT (SELECT count(*) FROM settings) + (SELECT count(*) FROM corpus_messages)" 2>/dev/null || echo 0)"
if [ "${RESTORE_REQUIRE_ROWS:-1}" = "1" ] && [ "$core" -lt 1 ]; then
    echo "FAIL: $backup se restauró pero settings/corpus_messages están vacías" >&2
    exit 1
fi

echo "OK: $original se restaura bien en $scratch ($tables tablas, $core filas en settings+corpus_messages)"
PGOPTIONS='-c client_min_messages=warning' psql -v ON_ERROR_STOP=1 -q -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;' >/dev/null
