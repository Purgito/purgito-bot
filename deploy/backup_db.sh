#!/bin/bash
# Backup diario de data/bot.db + subida al bucket privado de R2 + poda de
# backups viejos.
# Usa `sqlite3 .backup` (no `cp`) porque la base corre en modo WAL: copiar el
# archivo mientras el bot escribe puede capturar un estado inconsistente
# entre bot.db/bot.db-wal. Ver DEPLOY.md § "Backups de data/bot.db".
#
# Cada corrida deja en BACKUP_DIR:
#   bot-<fecha>.db              la base, verificada con PRAGMA integrity_check
#   bot-<fecha>.flags.tar.gz    los flags de migración sueltos de data/
#                               (.images_wiped_v2, etc.), solo si existen --
#                               viven fuera de bot.db y sin ellos un restore
#                               vuelve a correr migraciones destructivas
#                               (ver docs/PORTABILITY.md § 2).
# Un backup que no pasa la verificación se borra y la corrida falla.
#
# Subida a R2 (bucket R2_BACKUP_BUCKET, PRIVADO -- sin URL pública): se intenta
# si R2_BACKUP_BUCKET está definida en el entorno o en el .env del repo (cron no
# carga el .env, así que se lee de ahí). Sube el tar de flags ANTES que la base:
# una base en el bucket siempre tiene sus flags al lado. Con el bucket
# configurado, una subida que falla hace fallar la corrida (código 1) y NO se
# poda nada: el backup local queda donde está, y también los anteriores, que
# podrían ser los únicos que nunca llegaron a R2. Sin R2_BACKUP_BUCKET el
# backup queda solo en local y el log lo dice.
#
# Variables (todas opcionales):
#   DB_SRC, BACKUP_DIR, RETENTION_DAYS   origen, destino local y días de retención local
#   ENV_FILE                             .env del que leer R2_BACKUP_BUCKET (default: el del repo)
#   PYTHON                               intérprete con boto3 (default: el .venv del repo)
set -euo pipefail

# Los backups llevan lo mismo que bot.db (mensajes, tokens de webhook): solo el
# usuario que corre el cron los puede leer.
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_SRC="${DB_SRC:-$script_dir/../data/bot.db}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/purgito-bot-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
ENV_FILE="${ENV_FILE:-$script_dir/../.env}"
PYTHON="${PYTHON:-$script_dir/../.venv/bin/python}"
UPLOADER="$script_dir/../scripts/r2_backup.py"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
dest="$BACKUP_DIR/bot-$stamp.db"
flags_tar="$BACKUP_DIR/bot-$stamp.flags.tar.gz"
data_dir="$(dirname "$DB_SRC")"

# Nombre del bucket de backups: entorno primero, .env después. Se lee solo esa
# línea (nada de `source .env`: ejecutaría cualquier cosa que haya en el archivo).
backup_bucket="${R2_BACKUP_BUCKET:-}"
if [ -z "$backup_bucket" ] && [ -f "$ENV_FILE" ]; then
    backup_bucket="$(sed -n -E 's/^[[:space:]]*(export[[:space:]]+)?R2_BACKUP_BUCKET[[:space:]]*=(.*)$/\2/p' "$ENV_FILE" \
        | tail -n 1 \
        | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//' \
            -e 's/^"(.*)"$/\1/' -e "s/^'(.*)'\$/\\1/")"
fi

if ! sqlite3 "$DB_SRC" ".backup '$dest'"; then
    rm -f "$dest"
    echo "$(date -Is) ERROR backup failed (src=$DB_SRC)" >&2
    exit 1
fi

check="$(sqlite3 "$dest" "PRAGMA integrity_check;" 2>&1 || true)"
if [ "$check" != "ok" ]; then
    rm -f "$dest"
    echo "$(date -Is) ERROR backup no pasó integrity_check: $check" >&2
    exit 1
fi

# Flags: archivos ocultos de data/ (menos .gitkeep). Sin ninguno, no se crea
# el tar.
flags=()
while IFS= read -r -d '' f; do
    flags+=("$(basename "$f")")
done < <(find "$data_dir" -maxdepth 1 -type f -name '.*' ! -name '.gitkeep' -print0)

if [ "${#flags[@]}" -gt 0 ]; then
    tar -czf "$flags_tar" -C "$data_dir" "${flags[@]}"
fi

# Subida a R2. Desde acá el backup local ya es válido: si la subida falla se
# sale con error SIN tocar nada -- ni este backup ni los viejos (la poda de más
# abajo no corre).
remote="solo local: R2_BACKUP_BUCKET sin configurar"
if [ -n "$backup_bucket" ]; then
    upload_files=()
    if [ "${#flags[@]}" -gt 0 ]; then
        upload_files+=("$flags_tar")
    fi
    upload_files+=("$dest")
    if ! "$PYTHON" "$UPLOADER" upload "${upload_files[@]}"; then
        echo "$(date -Is) ERROR backup local OK ($dest) pero NO subió a R2 (bucket $backup_bucket): se conserva todo y no se poda nada" >&2
        exit 1
    fi
    remote="subido a R2 ($backup_bucket)"
fi

echo "$(date -Is) OK backup -> $dest (integrity_check ok, ${#flags[@]} flags, $remote)"
find "$BACKUP_DIR" -type f \( -name 'bot-*.db' -o -name 'bot-*.flags.tar.gz' \) \
    -mtime "+$RETENTION_DAYS" -delete
