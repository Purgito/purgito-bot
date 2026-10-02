#!/bin/bash
# Comprobación de la postura de seguridad del servidor (solo lectura). Sale con
# código 1 si algo está mal. Correrla después de cualquier cambio de red, de
# backups o de permisos:
#
#   deploy/security_check.sh
#
# Comprueba: PostgreSQL (5432) y la API (8080) solo en loopback; permisos de
# .env y de los backups; que los backups locales estén cifrados y que la clave
# PRIVADA de age no esté en este servidor; BACKUP_AGE_RECIPIENTS configurada;
# UFW activo y pg_hba.conf sin `trust` (estos dos necesitan sudo sin contraseña;
# si no se puede, se informa SKIP).
#
# Variables (para tests): SS_OUTPUT (salida de `ss -lntu` ya capturada),
# ENV_FILE, BACKUP_DIR, SEARCH_HOME (dónde buscar claves privadas age).
set -uo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$script_dir/../.env}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/purgito-bot-backups}"
SEARCH_HOME="${SEARCH_HOME:-$HOME}"

fails=0
ok() { echo "OK    $*"; }
fail() { echo "FAIL  $*"; fails=$((fails + 1)); }
skip() { echo "SKIP  $*"; }
mode() { stat -c '%a' "$1" 2>/dev/null; }

# 1. Puertos internos solo en loopback
if [ -n "${SS_OUTPUT:-}" ]; then ss_out="$SS_OUTPUT"; else ss_out="$(ss -lntu 2>/dev/null)"; fi
exposed=""
while read -r _ _ _ _ local _; do
    port="${local##*:}"
    addr="${local%:*}"
    case "$port" in
        5432 | 8080)
            case "$addr" in
                127.* | "[::1]" | "::1") ;;
                *) exposed="$exposed $local" ;;
            esac
            ;;
    esac
done <<<"$ss_out"
if [ -z "$exposed" ]; then
    ok "5432 (PostgreSQL) y 8080 (API) solo escuchan en loopback"
else
    fail "puerto(s) interno(s) expuesto(s):$exposed"
fi

# 2. Permisos
if [ -f "$ENV_FILE" ]; then
    [ "$(mode "$ENV_FILE")" = "600" ] && ok ".env es 0600" || fail ".env tiene permisos $(mode "$ENV_FILE") (debe ser 600)"
else
    skip "no hay .env en $ENV_FILE"
fi
if [ -d "$BACKUP_DIR" ]; then
    [ "$(mode "$BACKUP_DIR")" = "700" ] && ok "BACKUP_DIR es 0700" || fail "BACKUP_DIR tiene permisos $(mode "$BACKUP_DIR") (debe ser 700)"
    loose="$(find "$BACKUP_DIR" -type f -perm /077 2>/dev/null | head -5)"
    [ -z "$loose" ] && ok "los archivos de BACKUP_DIR no son legibles por otros" || fail "archivos de backup con permisos de más: $(echo "$loose" | xargs -n1 basename | tr '\n' ' ')"
    plain="$(find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'purgito-*.dump' -o -name '.purgito-*.plain' \) 2>/dev/null | head -5)"
    [ -z "$plain" ] && ok "no hay dumps en claro en BACKUP_DIR" || fail "dump(s) sin cifrar en BACKUP_DIR: $(echo "$plain" | xargs -n1 basename | tr '\n' ' ')"
else
    skip "no hay BACKUP_DIR ($BACKUP_DIR)"
fi

# 3. La clave privada de age no vive aquí
priv="$(grep -rIlE --max-count=1 'AGE-SECRET-KEY-1[A-Z0-9]{50,}' "$SEARCH_HOME" --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules 2>/dev/null | head -3)"
if [ -z "$priv" ]; then
    ok "no hay claves privadas age en $SEARCH_HOME"
else
    fail "clave privada age en el servidor ($(echo "$priv" | xargs -n1 basename | tr '\n' ' ')): cópiala fuera del servidor y bórrala con shred -u"
fi

# 4. Destinatarios de age configurados
if [ -f "$ENV_FILE" ]; then
    if grep -qE '^[[:space:]]*BACKUP_AGE_RECIPIENTS=age1[a-z0-9]{50,}' "$ENV_FILE"; then
        ok "BACKUP_AGE_RECIPIENTS configurada"
    else
        fail "falta BACKUP_AGE_RECIPIENTS en .env: los backups no se pueden cifrar ni subir a R2"
    fi
fi

# 5. UFW y pg_hba (necesitan privilegios)
if [ -z "${SS_OUTPUT:-}" ]; then
    if ufw_out="$(sudo -n ufw status 2>/dev/null)"; then
        grep -q '^Status: active' <<<"$ufw_out" && ok "UFW activo" || fail "UFW inactivo"
    else
        skip "UFW: hace falta sudo sin contraseña"
    fi
    if hba="$(sudo -n cat /etc/postgresql/*/main/pg_hba.conf 2>/dev/null)"; then
        if grep -vE '^\s*#|^\s*$' <<<"$hba" | grep -qwE 'trust'; then
            fail "pg_hba.conf tiene reglas 'trust'"
        else
            ok "pg_hba.conf sin reglas 'trust'"
        fi
    else
        skip "pg_hba.conf: hace falta sudo sin contraseña"
    fi
fi

if [ "$fails" -eq 0 ]; then
    echo "TODO OK"
    exit 0
fi
echo "$fails comprobación(es) fallida(s)"
exit 1
