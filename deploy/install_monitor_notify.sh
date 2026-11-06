#!/bin/bash
# Conecta los respaldos con Purgito Monitor (OnFailure -> evento critical -> alerta de Discord). Aditivo e idempotente.
#   sudo deploy/install_monitor_notify.sh            # dry-run
#   sudo deploy/install_monitor_notify.sh --apply    # instala
# Crea /etc/purgito/monitor.env (root:root 0600) con MONITOR_BASE_URL/NODE_ID/SHARED_SECRET tomados del .env del bot SIN
# imprimirlos; el runner de backups no puede leerlo. No toca los timers ni el código del bot.
set -euo pipefail
apply=0; [ "${1:-}" = "--apply" ] && apply=1
[ "$(id -u)" = 0 ] || { echo "ejecútalo con sudo"; exit 1; }
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPT=/opt/purgito-backup; ENVF=/etc/purgito/monitor.env; BOTENV="${BOT_ENV:-$repo/.env}"
run() { if [ "$apply" = 1 ]; then "$@"; else echo "   (dry-run) $*"; fi; }
[ -d "$OPT/scripts" ] || { echo "falta $OPT: instala antes el runner de backups"; exit 1; }
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo "== script y unidad (de HEAD)"
git -C "$repo" show HEAD:deploy/monitor_notify.py > "$tmp/n.py"
git -C "$repo" show 'HEAD:deploy/purgito-notify@.service' > "$tmp/u.service"
run install -m 0755 -o root -g root "$tmp/n.py" "$OPT/scripts/monitor_notify.py"
run install -m 0644 -o root -g root "$tmp/u.service" '/etc/systemd/system/purgito-notify@.service'
echo "== OnFailure en las tres unidades"
for u in purgito-backup purgito-ledger purgito-backup-check; do
    run install -d -m 0755 "/etc/systemd/system/$u.service.d"
    if [ "$apply" = 1 ]; then printf '[Unit]\nOnFailure=purgito-notify@%%n.service\n' > "/etc/systemd/system/$u.service.d/20-purgito-notify.conf"; chmod 0644 "/etc/systemd/system/$u.service.d/20-purgito-notify.conf"
    else echo "   (dry-run) $u.service.d/20-purgito-notify.conf"; fi
done
echo "== credenciales del monitor (root 0600, valores no mostrados)"
if [ -s "$ENVF" ] && grep -q '^MONITOR_SHARED_SECRET=' "$ENVF"; then echo "   $ENVF ya existe"; else
    [ -r "$BOTENV" ] || { echo "no puedo leer $BOTENV"; exit 1; }
    if [ "$apply" = 1 ]; then
        ( umask 077; grep -E '^(MONITOR_BASE_URL|MONITOR_NODE_ID|MONITOR_SHARED_SECRET)=' "$BOTENV" > "$ENVF"; chown root:root "$ENVF"; chmod 0600 "$ENVF" )
        [ "$(grep -c . "$ENVF")" = 3 ] || { echo "el .env del bot no tiene las tres variables del monitor"; exit 1; }
        echo "   escrito $ENVF (3 variables)"
    else echo "   (dry-run) $ENVF <- 3 variables MONITOR_* del .env del bot"; fi
fi
run systemctl daemon-reload
[ "$apply" = 1 ] || echo "(dry-run: nada cambió; añade --apply)"
