#!/bin/bash
# Instala el vigilante de salud y saca las credenciales del monitor de la bóveda. Aditivo e idempotente.
#   sudo deploy/install_purgito_salud.sh            # dry-run
#   sudo deploy/install_purgito_salud.sh --apply
# Copia las 3 variables MONITOR_* de /etc/purgito/monitor.env (bóveda) a /etc/purgito-alertas/monitor.env
# (raíz, root 0600) SIN imprimirlas. Riesgo aceptado: ese secreto solo permite enviar eventos al monitor para
# este nodo (como el del agente, que ya está en la raíz). Revertir: deploy/install_purgito_salud.sh --revert
set -euo pipefail
mode="${1:-}"; apply=0; [ "$mode" = --apply ] && apply=1
[ "$(id -u)" = 0 ] || { echo "ejecútalo con sudo"; exit 1; }
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPT=/opt/purgito-backup/scripts; SRC=/etc/purgito/monitor.env; DST_DIR=/etc/purgito-alertas; DST=$DST_DIR/monitor.env
if [ "$mode" = --revert ]; then
    systemctl disable --now purgito-salud.timer 2>/dev/null || true
    rm -f /etc/systemd/system/purgito-salud.{service,timer} "$OPT/purgito_salud.py"
    sed -i 's#^EnvironmentFile=/etc/purgito-alertas/monitor.env#EnvironmentFile=/etc/purgito/monitor.env#' /etc/systemd/system/purgito-notify@.service
    systemctl daemon-reload; echo "revertido (las credenciales en $DST quedan: bórralas con shred -u si quieres)"; exit 0
fi
run() { if [ "$apply" = 1 ]; then "$@"; else echo "   (dry-run) $*"; fi; }
[ -d "$OPT" ] || { echo "falta $OPT"; exit 1; }
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
for f in purgito_salud.py monitor_notify.py purgito-salud.service purgito-salud.timer purgito-notify@.service; do
    git -C "$repo" show "HEAD:deploy/$f" > "$tmp/$f"
done
run install -m 0755 -o root -g root "$tmp/purgito_salud.py" "$OPT/purgito_salud.py"
run install -m 0755 -o root -g root "$tmp/monitor_notify.py" "$OPT/monitor_notify.py"
for u in purgito-salud.service purgito-salud.timer purgito-notify@.service; do
    run install -m 0644 -o root -g root "$tmp/$u" "/etc/systemd/system/$u"
done
echo "== credenciales del monitor fuera de la bóveda (valores no mostrados)"
if [ -s "$DST" ] && [ "$(grep -cE '^MONITOR_(BASE_URL|NODE_ID|SHARED_SECRET)=' "$DST")" = 3 ]; then echo "   $DST ya existe"
else
    [ -r "$SRC" ] || { echo "no puedo leer $SRC (¿bóveda abierta?)"; exit 1; }
    if [ "$apply" = 1 ]; then
        install -d -m 0700 -o root -g root "$DST_DIR"
        ( umask 077; grep -E '^(MONITOR_BASE_URL|MONITOR_NODE_ID|MONITOR_SHARED_SECRET)=' "$SRC" > "$DST" )
        [ "$(grep -c . "$DST")" = 3 ] || { echo "faltan variables en $SRC"; exit 1; }
        echo "   escrito $DST (3 variables)"
    else echo "   (dry-run) $DST <- 3 variables de $SRC"; fi
fi
echo "== purgito-backup-check: no fallar (ni avisar dos veces) con la bóveda cerrada: eso lo avisa purgito-salud"
run install -d -m 0755 /etc/systemd/system/purgito-backup-check.service.d
if [ "$apply" = 1 ]; then printf '[Unit]\nConditionPathIsMountPoint=/srv/purgito\n' > /etc/systemd/system/purgito-backup-check.service.d/10-purgito-vault.conf; fi
run systemctl daemon-reload
run systemctl enable --now purgito-salud.timer
[ "$apply" = 1 ] || echo "(dry-run: nada cambió; añade --apply)"
