#!/bin/bash
# Genera el unit de systemd real a partir de deploy/bot-purg.service.template,
# reemplazando {{DEPLOY_USER}} y {{DEPLOY_PATH}}. Escribe a stdout -- no toca
# /etc/systemd/system/ directamente, así se puede revisar antes de copiar.
#
# Uso:
#   deploy/render_service.sh <usuario> </ruta/al/checkout> > /tmp/bot-purg.service
#   deploy/render_service.sh > /tmp/bot-purg.service   # usa DEPLOY_USER/DEPLOY_PATH del entorno
#
# Ejemplo real (AWS, 2026-09-05):
#   deploy/render_service.sh ubuntu /home/ubuntu/purgito-bot > /tmp/bot-purg.service
#   sudo cp /tmp/bot-purg.service /etc/systemd/system/bot-purg.service
#   sudo systemctl daemon-reload && sudo systemctl restart bot-purg
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/bot-purg.service.template"

DEPLOY_USER="${1:-${DEPLOY_USER:-}}"
DEPLOY_PATH="${2:-${DEPLOY_PATH:-}}"

if [ -z "$DEPLOY_USER" ] || [ -z "$DEPLOY_PATH" ]; then
    echo "Uso: $0 <usuario> </ruta/al/checkout>" >&2
    echo "     (o exportar DEPLOY_USER y DEPLOY_PATH antes de llamar sin argumentos)" >&2
    exit 1
fi

# Sin barra final -- el template ya la agrega donde hace falta
# (WorkingDirectory, ExecStart, ReadOnlyPaths/ReadWritePaths comentados).
DEPLOY_PATH="${DEPLOY_PATH%/}"

if [ ! -f "$TEMPLATE" ]; then
    echo "No se encontró la plantilla: $TEMPLATE" >&2
    exit 1
fi

sed \
    -e "s|{{DEPLOY_USER}}|$DEPLOY_USER|g" \
    -e "s|{{DEPLOY_PATH}}|$DEPLOY_PATH|g" \
    "$TEMPLATE"
