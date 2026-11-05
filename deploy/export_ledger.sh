#!/bin/bash
# Exporta el registro de eliminaciones/exclusiones (cifrado con age) a R2 y poda las
# instantáneas vencidas (más de 15 días; siempre quedan las 3 últimas).
# Pensado para cron, cada hora (NO instalado por defecto; ver docs/POSTGRES.md
# § Registro de eliminaciones):
#   7 * * * * /home/purgito/purgito-bot/deploy/export_ledger.sh >> /home/purgito/purgito-bot-backups/ledger.log 2>&1
set -euo pipefail
umask 077
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$script_dir/../.venv/bin/python}"
"$PYTHON" "$script_dir/../scripts/export_privacy_ledger.py"
"$PYTHON" "$script_dir/../scripts/r2_backup.py" prune-ledger --apply
