#!/bin/bash
# Verificación de SOLO LECTURA del despliegue coordinado de privacidad (ver docs/DESPLIEGUE_PRIVACIDAD.md).
#
#   sudo deploy/verify_privacy_release.sh pre    # antes: informa qué falta (siempre sale 0)
#   sudo deploy/verify_privacy_release.sh post   # después: sale 1 si algo falta
#   sudo deploy/verify_privacy_release.sh post --web   # además comprueba la landing pública (red)
#
# No escribe nada, no sube, no borra, no imprime valores sensibles (solo conteos y nombres).
set -uo pipefail
mode="${1:-pre}"; web="${2:-}"
[ "$mode" = "pre" ] || [ "$mode" = "post" ] || { echo "uso: verify_privacy_release.sh pre|post [--web]" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "ERROR: ejecútalo con sudo (lee logs de nginx y estado de systemd)" >&2; exit 2; }
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
missing=0
check() { # check "descripción" comando...
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then echo "   OK     $desc"; else echo "   FALTA  $desc"; missing=$((missing + 1)); fi
}

echo "== nginx"
check "formato de log 'purgito' cargado" bash -c "nginx -T 2>/dev/null | grep -q 'log_format purgito'"
check "access_log usa el formato 'purgito'" bash -c "nginx -T 2>/dev/null | grep -E '^[[:space:]]*access_log[[:space:]]+/var/log/nginx/access.log[[:space:]]+purgito'"
check "access.log activo sin code=/state= en la query" bash -c "! grep -q -E '[?&](code|state|access_token|id_token|refresh_token)=' /var/log/nginx/access.log"

echo "== logs históricos"
shopt -s nullglob
hist=(/var/log/nginx/access.log.* /var/log/nginx/error.log.* "$repo"/data/bot.log.*)
check "sin valores OAuth/sensibles en logs rotados (nginx y bot)" bash -c "python3 -I '$repo/scripts/scrub_oauth_logs.py' ${hist[*]:-/dev/null} | grep -q 'ensayo' && exit 1 || exit 0"

echo "== bot (retención de logs)"
check "el bot se reinició DESPUÉS de la última edición de logging_setup.py" bash -c "[ \$(date -d \"\$(systemctl show bot-purg -p ActiveEnterTimestamp --value)\" +%s) -ge \$(stat -c %Y '$repo/src/observability/logging_setup.py') ]"
check "events/security.jsonl sin líneas de más de 31 días" python3 -I - "$repo/data" <<'PY'
import sys, os, re, datetime as d
base = sys.argv[1]; lim = d.datetime.now(d.timezone.utc) - d.timedelta(days=31)
for n in os.listdir(base):
    if re.match(r"(events|security)\.jsonl", n):
        for line in open(os.path.join(base, n), errors="replace"):
            m = re.search(r'"timestamp": "(\d{4}-\d{2}-\d{2})T', line)
            if m and d.datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=d.timezone.utc) < lim:
                sys.exit(1)
PY

echo "== backups"
check "guardas instaladas en el runner" test -x /opt/purgito-backup/deploy/backup_guard.sh
check "purgito-backup.service con BACKUP_REQUIRE_GUARD=1" bash -c "systemctl show purgito-backup.service -p Environment | grep -q BACKUP_REQUIRE_GUARD=1"
for u in purgito-backup purgito-ledger purgito-backup-check purgito-vault-watch; do
    check "$u.timer habilitado" systemctl is-enabled --quiet "$u.timer"
done
check "ningún dump local de más de 13 días" bash -c "[ -z \"\$(find /var/backups/purgito -maxdepth 1 -name 'purgito-*.dump*' -mtime +13 -print -quit)\" ]"

if [ "$web" = "--web" ]; then
    echo "== landing pública"
    for u in es/privacidad en/privacy es/terminos en/terms es/reembolsos en/refunds; do
        check "https://purgito.app/$u con la versión del 7 nov 2026" bash -c "curl -fsS --max-time 15 https://purgito.app/$u/ | grep -q -E '7 de noviembre de 2026|November 7, 2026'"
    done
fi

echo
if [ "$missing" -eq 0 ]; then echo "TODO OK ($mode)"; exit 0; fi
echo "$missing comprobación(es) pendientes ($mode)"
[ "$mode" = "pre" ] && exit 0 || exit 1
