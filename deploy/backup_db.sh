#!/bin/bash
# Backup diario de data/bot.db + poda de backups viejos.
# Usa `sqlite3 .backup` (no `cp`) porque la base corre en modo WAL: copiar el
# archivo mientras el bot escribe puede capturar un estado inconsistente
# entre bot.db/bot.db-wal. Ver DEPLOY.md § "Backups de data/bot.db".
set -euo pipefail

DB_SRC="${DB_SRC:-/home/opc/purgito-bot/data/bot.db}"
BACKUP_DIR="${BACKUP_DIR:-/home/opc/purgito-bot-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
dest="$BACKUP_DIR/bot-$(date +%Y%m%d-%H%M%S).db"

if sqlite3 "$DB_SRC" ".backup '$dest'"; then
    echo "$(date -Is) OK backup -> $dest"
    find "$BACKUP_DIR" -name 'bot-*.db' -mtime "+$RETENTION_DAYS" -delete
else
    echo "$(date -Is) ERROR backup failed (src=$DB_SRC)" >&2
    exit 1
fi
