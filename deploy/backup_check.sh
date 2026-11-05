#!/bin/bash
# Vigilancia "dead-man": avisa si NO hay un backup reciente (el cron/timer no corrió o falló en
# silencio) o si el registro de eliminaciones dejó de exportarse. Solo lee R2. Lo lanza
# purgito-backup-check.timer (cada 6 h). El aviso va a BACKUP_ALERT_WEBHOOK, sin datos ni secretos.
set -uo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-/usr/bin/python3}"
R2B="$script_dir/../scripts/r2_backup.py"

alert() {
    [ -n "${BACKUP_ALERT_WEBHOOK:-}" ] || return 0
    command -v curl >/dev/null 2>&1 || return 0
    curl -fsS --max-time 10 -H 'Content-Type: application/json' \
        -d "{\"content\": \"⚠️ Purgito: $1 (verificado $(date -u +%Y-%m-%dT%H:%MZ) en $(hostname))\"}" \
        "$BACKUP_ALERT_WEBHOOK" >/dev/null 2>&1 || true
}

rc=0
if ! "$PYTHON" -I "$R2B" check --max-age-hours "${CHECK_BACKUP_MAX_HOURS:-36}"; then
    alert "no hay un backup de la base de las últimas ${CHECK_BACKUP_MAX_HOURS:-36} h"
    rc=1
fi
if ! "$PYTHON" -I "$R2B" check --ledger --max-age-hours "${CHECK_LEDGER_MAX_HOURS:-3}"; then
    alert "no hay una instantánea del registro de privacidad de las últimas ${CHECK_LEDGER_MAX_HOURS:-3} h"
    rc=1
fi
exit "$rc"
