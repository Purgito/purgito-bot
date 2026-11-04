#!/bin/bash
# Genera el unit de systemd del panel de Studio a partir de deploy/studio-purg.service.template,
# reemplazando {{DEPLOY_USER}} y {{DEPLOY_PATH}}. Escribe a stdout: no toca /etc/systemd/system.
#
# Uso:
#   deploy/render_studio_service.sh <usuario> </ruta/al/checkout> > /tmp/studio-purg.service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/studio-purg.service.template"

DEPLOY_USER="${1:-${DEPLOY_USER:-}}"
DEPLOY_PATH="${2:-${DEPLOY_PATH:-}}"

if [ -z "$DEPLOY_USER" ] || [ -z "$DEPLOY_PATH" ]; then
    echo "Uso: $0 <usuario> </ruta/al/checkout>" >&2
    exit 1
fi
DEPLOY_PATH="${DEPLOY_PATH%/}"

if [ ! -f "$TEMPLATE" ]; then
    echo "No se encontró la plantilla: $TEMPLATE" >&2
    exit 1
fi

sed \
    -e "s|{{DEPLOY_USER}}|$DEPLOY_USER|g" \
    -e "s|{{DEPLOY_PATH}}|$DEPLOY_PATH|g" \
    "$TEMPLATE"
