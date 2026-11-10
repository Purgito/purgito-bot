#!/bin/bash
# Enlaza el vault LUKS con el servidor Tang del host (Clevis) en UNA ranura nueva, y activa el desbloqueo
# automático. INTERACTIVO: Clevis pide la contraseña PRINCIPAL del vault (la teclea el titular; nunca pasa por
# argumentos, archivos ni logs). No toca las ranuras existentes (contraseña principal y de recuperación).
#   sudo deploy/purgito-tang-enroll.sh <huella-tang>      # huella = contenido de ~/purgito-tang.thp en el host
# Revertir: sudo deploy/purgito-tang-enroll.sh --quitar   (desactiva el servicio y mata SOLO la ranura de Clevis)
# Probado antes en el laboratorio (~/purgito-lab): bind = PBKDF2 (1000 it.), sin Argon2, <500 MB de RAM.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "ejecútalo con sudo"; exit 1; }
CONF=/etc/purgito-vault.conf; [ -r "$CONF" ] && . "$CONF"
IMG="${PV_IMG:?falta PV_IMG}"; TOOL=/opt/purgito-vault/purgito-vault
URL="${PV_TANG_URL:-http://10.203.0.1:7500}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
slots() { cryptsetup luksDump --dump-json-metadata "$IMG" | python3 -I -c '
import json,sys; m=json.load(sys.stdin); print(" ".join(sorted(m["keyslots"])))'; }
tang_slots() { cryptsetup luksDump --dump-json-metadata "$IMG" | python3 -I -c '
import json,sys; m=json.load(sys.stdin)
print(" ".join(s for t in m.get("tokens",{}).values() if t.get("type")=="clevis" for s in t.get("keyslots",[])))'; }

if [ "${1:-}" = --quitar ]; then
    systemctl disable --now purgito-vault-auto.service 2>/dev/null || true
    for s in $(tang_slots); do
        echo "Se va a eliminar SOLO la ranura de Clevis $s (te pedirá una contraseña válida)."
        cryptsetup luksKillSlot "$IMG" "$s"
    done
    rm -f /etc/systemd/system/purgito-vault-auto.service; systemctl daemon-reload
    echo "desbloqueo automático retirado; ranuras ahora: $(slots)"; exit 0
fi

THP="${1:?uso: $0 <huella-de-tang>   (en el host: cat ~/purgito-tang.thp)}"
[[ "$THP" =~ ^[A-Za-z0-9_-]{43}$ ]] || { echo "huella no válida"; exit 1; }
[ -x "$TOOL" ] || { echo "falta $TOOL"; exit 1; }
[ -z "$(tang_slots)" ] || { echo "ya hay una ranura de Clevis ($(tang_slots)): nada que hacer (usa --quitar para rehacer)"; exit 1; }

echo "== 1. Tang responde y su huella es la fijada"
adv="$(curl -fsS -m 5 "$URL/adv")" || { echo "Tang no responde en $URL"; exit 1; }
[ -n "$adv" ] || { echo "respuesta vacía"; exit 1; }
echo "== 2. Memoria y copia previa del encabezado (cifrada con age, a R2)"
free -m | sed -n 2p
"$TOOL" header-backup
before="$(slots)"; echo "ranuras antes: $before"
echo "== 3. Enlazar (te pedirá la contraseña PRINCIPAL del vault)"
clevis luks bind -d "$IMG" tang "{\"url\":\"$URL\",\"thp\":\"$THP\"}"
echo "== 4. Verificación"
after="$(slots)"; echo "ranuras después: $after"
for s in $before; do grep -qw "$s" <<<"$after" || { echo "ERROR: desapareció la ranura $s"; exit 1; }; done
new="$(tang_slots)"; [ -n "$new" ] || { echo "ERROR: no hay ranura de Clevis"; exit 1; }
cryptsetup luksDump "$IMG" | sed -n "/^  $new: luks2/,/AF stripes/p" | grep -E "PBKDF|Iterations|Memory"
"$TOOL" tang-test
echo "== 5. Copia del encabezado ya con la ranura nueva + servicio de desbloqueo automático"
"$TOOL" header-backup
install -m 0644 -o root -g root "$repo/deploy/purgito-vault-auto.service" /etc/systemd/system/purgito-vault-auto.service
systemctl daemon-reload; systemctl enable purgito-vault-auto.service
echo "LISTO. Ranura de Clevis: $new. Servicio habilitado (no actúa con el vault abierto). Siguiente: ensayo de reinicio de la VM."
