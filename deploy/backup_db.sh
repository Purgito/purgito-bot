#!/bin/bash
# Backup diario de data/bot.db + poda de backups viejos.
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
set -euo pipefail

# Los backups llevan lo mismo que bot.db (mensajes, tokens de webhook): solo el
# usuario que corre el cron los puede leer.
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_SRC="${DB_SRC:-$script_dir/../data/bot.db}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/purgito-bot-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
dest="$BACKUP_DIR/bot-$stamp.db"
data_dir="$(dirname "$DB_SRC")"

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
    tar -czf "$BACKUP_DIR/bot-$stamp.flags.tar.gz" -C "$data_dir" "${flags[@]}"
fi

echo "$(date -Is) OK backup -> $dest (integrity_check ok, ${#flags[@]} flags)"
find "$BACKUP_DIR" -type f \( -name 'bot-*.db' -o -name 'bot-*.flags.tar.gz' \) \
    -mtime "+$RETENTION_DAYS" -delete
