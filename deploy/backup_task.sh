#!/bin/bash
# Ejecuta un subcomando de SOLO LECTURA de r2_backup.py con las credenciales de backups, como
# el usuario aislado del runner (purgito_backup), sin que los secretos pasen por tu shell:
#
#   sudo /opt/purgito-backup/deploy/backup_task.sh preflight | access-check | list | check
#   sudo /opt/purgito-backup/deploy/backup_task.sh head <purgito-AAAAMMDD-HHMMSS.dump.age>
#
# systemd (root) carga /etc/purgito/backup.env y lanza el proceso con el mismo endurecimiento
# que purgito-backup.service. Solo admite estos subcomandos: ninguno sube, borra ni poda.
set -euo pipefail

cmd="${1:-}"
case "$cmd" in
    preflight|list|check) args=("$cmd") ;;
    access-check)         args=(access-check --backup-only) ;;
    head)                 [ -n "${2:-}" ] || { echo "uso: backup_task.sh head <nombre>" >&2; exit 2; }
                          args=(head "$2") ;;
    *) echo "uso: backup_task.sh preflight | access-check | list | check | head <nombre>" >&2; exit 2 ;;
esac
[ "$(id -u)" = "0" ] || { echo "ERROR: ejecútalo con sudo" >&2; exit 1; }

exec systemd-run --quiet --wait --pipe --collect \
    -p User=purgito_backup -p Group=purgito_backup \
    -p EnvironmentFile=/etc/purgito/backup.env \
    -p NoNewPrivileges=yes -p PrivateTmp=yes -p PrivateDevices=yes \
    -p ProtectSystem=strict -p ProtectHome=yes -p ReadWritePaths=/var/backups/purgito \
    -p ProtectProc=invisible -p ProcSubset=pid -p CapabilityBoundingSet= \
    -p "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" -p UMask=0077 \
    /usr/bin/python3 -I /opt/purgito-backup/scripts/r2_backup.py "${args[@]}"
