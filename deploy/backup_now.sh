#!/bin/bash
# Lanza una copia de la base A MANO, con motivo y trazabilidad (ver deploy/backup_guard.sh).
#
#   sudo /opt/purgito-backup/deploy/backup_now.sh "motivo"             # solo si la última copia tiene >= 12 h
#   sudo /opt/purgito-backup/deploy/backup_now.sh "motivo" --forzar    # aunque haya una reciente
#
# Esto SUBE a R2 un dump nuevo (~62 MB) que no se podrá borrar hasta pasados 6 días (Bucket Lock).
# Para PROBAR scripts no uses esto: deploy/backup_db_test.sh y deploy/backup_guard_test.sh no tocan
# R2. El motivo queda en /var/backups/purgito/backup.log junto con tu usuario.
set -euo pipefail

reason="${1:-}"
force="${2:-}"
BKDIR="${BKDIR:-/var/backups/purgito}"
[ -n "$reason" ] || { echo "uso: backup_now.sh \"motivo\" [--forzar]" >&2; exit 2; }
[ -z "$force" ] || [ "$force" = "--forzar" ] || { echo "argumento desconocido: $force" >&2; exit 2; }
[ "$(id -u)" = "0" ] || { echo "ERROR: ejecútalo con sudo" >&2; exit 1; }
[ "${#reason}" -le 200 ] || { echo "ERROR: el motivo es demasiado largo (máx. 200)" >&2; exit 2; }
reason="${reason//|/-}"; reason="${reason//$'\n'/ }"

f="$BKDIR/.manual-reason"
( umask 077; printf '%s|%s|%s|%s\n' "$(date +%s)" "${SUDO_USER:-root}" "$([ "$force" = "--forzar" ] && echo 1 || echo 0)" "$reason" > "$f" )
chown purgito_backup:purgito_backup "$f" 2>/dev/null || true
systemctl start purgito-backup.service
echo "---- últimas líneas de $BKDIR/backup.log"
tail -n 6 "$BKDIR/backup.log" | cut -c1-200
