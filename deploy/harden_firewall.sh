#!/bin/bash
# Firewall (UFW) para el servidor de Purgito. Necesita sudo. Idempotente.
#
#   sudo deploy/harden_firewall.sh [subred_privada_del_proveedor]    # default: 10.203.0.0/24
#
# Política: todo lo entrante cerrado, salvo
#   - la interfaz tailscale0 (SSH y administración por Tailscale),
#   - SSH desde la red privada del proveedor (consola/respaldo),
#   - UDP 41641 (conexiones directas de Tailscale).
# Nada de 80/443: nginx solo recibe tráfico de cloudflared por loopback (que UFW
# no filtra), y PostgreSQL (5432) y la API (8080) solo escuchan en 127.0.0.1.
#
# ⚠️ Riesgo de quedarse fuera: antes de activar se programa un `ufw disable`
# automático en 15 minutos (unidad ufw-safety-revert). Abre OTRA sesión SSH
# nueva; si entra, cancela el aviso con
#   sudo systemctl stop ufw-safety-revert.timer
# El script NO lo cancela por ti.
set -euo pipefail

lan="${1:-10.203.0.0/24}"

ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0 comment 'Tailscale (SSH y admin)'
ufw allow from "$lan" to any port 22 proto tcp comment 'SSH desde la red privada del proveedor'
ufw allow 41641/udp comment 'Tailscale conexiones directas'

if ! ufw status | grep -q '^Status: active'; then
    systemd-run --on-active=900 --unit=ufw-safety-revert /usr/sbin/ufw --force disable
    ufw --force enable
    echo "UFW activo. Prueba una sesión SSH nueva y luego: sudo systemctl stop ufw-safety-revert.timer"
fi
ufw status verbose
