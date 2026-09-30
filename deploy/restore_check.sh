#!/bin/bash
# Prueba de restauración: toma el backup más reciente de BACKUP_DIR (o el
# archivo que pases como primer argumento), lo restaura en un directorio
# temporal y comprueba que se puede abrir. NO toca data/ ni el bot en
# marcha -- es seguro correrlo en cualquier momento.
#
#   deploy/restore_check.sh                 # último backup de BACKUP_DIR
#   deploy/restore_check.sh /ruta/bot-X.db  # uno puntual
#
# Verifica: integrity_check, que la base tenga tablas y, si existe el
# bot-<fecha>.flags.tar.gz hermano, que el tar se pueda leer. Sale con
# código != 0 si algo falla. Correrlo cada tanto (o desde cron con alerta)
# es lo que distingue "tengo backups" de "mis backups se pueden restaurar".
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/purgito-bot-backups}"

if [ "$#" -ge 1 ]; then
    backup="$1"
else
    backup="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'bot-*.db' 2>/dev/null | sort | tail -n 1)"
fi

if [ -z "${backup:-}" ] || [ ! -f "$backup" ]; then
    echo "FAIL: no hay backup que verificar (BACKUP_DIR=$BACKUP_DIR)" >&2
    exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

restored="$tmp/bot.db"
sqlite3 "$restored" ".restore '$backup'"

check="$(sqlite3 "$restored" "PRAGMA integrity_check;")"
if [ "$check" != "ok" ]; then
    echo "FAIL: integrity_check de $backup: $check" >&2
    exit 1
fi

tables="$(sqlite3 "$restored" "SELECT count(*) FROM sqlite_master WHERE type='table';")"
if [ "$tables" -lt 1 ]; then
    echo "FAIL: $backup no tiene tablas" >&2
    exit 1
fi

flags_tar="${backup%.db}.flags.tar.gz"
flags_msg="sin flags"
if [ -f "$flags_tar" ]; then
    tar -tzf "$flags_tar" >/dev/null || { echo "FAIL: no se puede leer $flags_tar" >&2; exit 1; }
    flags_msg="flags ok"
fi

echo "OK: $backup se restaura bien ($tables tablas, $flags_msg)"
