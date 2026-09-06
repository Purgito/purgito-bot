#!/bin/bash
# Chequeos post-deploy para un servidor nuevo (o después de tocar systemd/nginx
# en uno existente). No repara nada -- solo informa qué falta. Pensado para
# correr ANTES de dar por terminada una migración (ver MIGRATION.md) y
# después de cualquier cambio a deploy/bot-purg.service.template o a la
# config de nginx.
#
# No aborta en el primer error: corre todos los chequeos y al final imprime
# un resumen de qué pasó y qué falló. Exit code 0 solo si todo pasó (los
# SKIP -- checks que no aplican en este entorno, ej. sin nginx local -- no
# cuentan como falla).
#
# Uso:
#   deploy/preflight_check.sh
#   REPO_DIR=/home/ubuntu/purgito-bot SERVICE_NAME=bot-purg deploy/preflight_check.sh
set -uo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SERVICE_NAME="${SERVICE_NAME:-bot-purg}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/etc/nginx/conf.d}"
HEALTH_HOST="${HEALTH_HOST:-purgito.app}"

PASS=0
FAIL=0
SKIP=0

ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
skip() { echo "  ⏭️  $1 (omitido: $2)"; SKIP=$((SKIP+1)); }

section() { echo; echo "── $1 ──"; }

# ─────────────────────────────────────────────────────────────────────────
section "1. .env"

ENV_FILE="$REPO_DIR/.env"

if [ -d "$ENV_FILE" ]; then
    bad ".env es un directorio, no un archivo (ver PORTABILITY.md / problema conocido de setup manual: mkdir en vez de touch/cp)"
elif [ ! -f "$ENV_FILE" ]; then
    bad ".env no existe en $REPO_DIR -- copiar .env.example y completarlo"
else
    ok ".env existe y es un archivo regular"

    # Variables obligatorias: DISCORD_TOKEN (hardcoded acá -- es la única var
    # que src/config.py lee sin ningún default, así que no hay una lista en
    # el código de la que extraerla) + lo que src/config.py declara como
    # obligatorio para el dashboard (bloque `_missing = [...]` en config.py:
    # se parsea de ahí en vez de hardcodearlo para no desactualizarse el día
    # que se agregue una variable nueva a esa lista).
    CONFIG_PY="$REPO_DIR/src/config.py"
    required_vars=(DISCORD_TOKEN)
    if [ -f "$CONFIG_PY" ]; then
        while IFS= read -r var; do
            required_vars+=("$var")
        done < <(sed -n '/_missing = \[/,/^\s*\]/p' "$CONFIG_PY" | grep -oE '"[A-Z_]+"' | tr -d '"')
    else
        skip "leer variables obligatorias del dashboard desde config.py" "no se encontró $CONFIG_PY"
    fi

    for var in "${required_vars[@]}"; do
        value="$(grep -E "^${var}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-)"
        if [ -z "$value" ]; then
            bad "$var falta o está vacía en .env"
        else
            ok "$var presente en .env"
        fi
    done
fi

# ─────────────────────────────────────────────────────────────────────────
section "2. Dependencias del sistema"

if which gifsicle >/dev/null 2>&1; then
    ok "gifsicle instalado ($(gifsicle --version | head -n1))"
else
    bad "gifsicle no encontrado -- los GIFs se subirán a R2 sin comprimir (degrada con gracia, pero revisar si es intencional)"
fi

VENV_PY="$REPO_DIR/.venv/bin/python"
if [ -x "$VENV_PY" ]; then
    ok "venv tiene un python ejecutable ($($VENV_PY --version 2>&1))"
else
    bad "$VENV_PY no existe o no es ejecutable -- correr: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

# ─────────────────────────────────────────────────────────────────────────
section "3. systemd"

if ! which systemctl >/dev/null 2>&1; then
    skip "estado de $SERVICE_NAME" "systemctl no disponible en este entorno"
else
    status="$(systemctl is-active "$SERVICE_NAME" 2>/dev/null)"
    if [ "$status" = "active" ]; then
        ok "systemctl status $SERVICE_NAME: active (running)"
    else
        bad "systemctl status $SERVICE_NAME: '$status' (esperado: active) -- ver: journalctl -u $SERVICE_NAME -n 50"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────
section "4. HTTP local (vía nginx, Host: $HEALTH_HOST)"

if ! which curl >/dev/null 2>&1; then
    skip "chequeos HTTP" "curl no disponible en este entorno"
else
    check_http() {
        local path="$1" want="$2"
        local code
        code="$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $HEALTH_HOST" "http://localhost${path}" 2>/dev/null)"
        if [ "$code" = "$want" ]; then
            ok "$path -> $code"
        else
            bad "$path -> $code (esperado $want)"
        fi
    }
    check_http "/health" "200"
    check_http "/" "200"
    check_http "/es/" "200"
fi

# ─────────────────────────────────────────────────────────────────────────
section "5. Config de nginx"

if [ ! -d "$NGINX_CONF_DIR" ]; then
    skip "búsqueda de corchetes/paréntesis sueltos" "no existe $NGINX_CONF_DIR en este entorno"
else
    # Autolinking al copiar URLs con "www." desde un visor de markdown puede
    # dejar restos tipo [www.purgito.app](http://www.purgito.app) pegados en
    # server_name -- ya pasó dos veces. Un .conf válido no debería tener
    # corchetes en ningún lado.
    matches="$(grep -rnHE '\[|\]' "$NGINX_CONF_DIR"/*.conf 2>/dev/null)"
    if [ -z "$matches" ]; then
        ok "sin corchetes sueltos en $NGINX_CONF_DIR/*.conf"
    else
        bad "corchetes encontrados en config de nginx (restos de autolinking al copiar URLs):"
        echo "$matches" | sed 's/^/       /'
    fi
fi

# ─────────────────────────────────────────────────────────────────────────
section "6. Flags de migración de datos (data/)"

DB_FILE="$REPO_DIR/data/bot.db"
FLAG_IMAGES="$REPO_DIR/data/.images_wiped_v2"
FLAG_SPLIT="$REPO_DIR/data/.chat_channels_split_v1"

if [ ! -f "$DB_FILE" ]; then
    skip "flags de migración" "todavía no existe data/bot.db (instalación nueva, nada que verificar)"
else
    missing_flags=()
    [ -f "$FLAG_IMAGES" ] || missing_flags+=(".images_wiped_v2")
    [ -f "$FLAG_SPLIT" ] || missing_flags+=(".chat_channels_split_v1")

    if [ "${#missing_flags[@]}" -eq 0 ]; then
        ok "data/bot.db tiene sus flags de migración al lado (.images_wiped_v2, .chat_channels_split_v1)"
    else
        bad "data/bot.db existe pero falta(n): ${missing_flags[*]} (ver docs/PORTABILITY.md § 2)"
        echo "       Si este bot.db viene de un backup/restore de otro servidor (migración,"
        echo "       recuperación de desastre), el próximo arranque del bot puede volver a"
        echo "       correr una migración de una sola vez que se creía ya aplicada -- en"
        echo "       particular, .images_wiped_v2 ausente dispara un DELETE FROM corpus_images"
        echo "       de nuevo, sin preguntar. Copiá esos dos archivos junto con bot.db antes de"
        echo "       arrancar el bot."
        echo "       Si en cambio esto es una instalación nueva de cero (bot.db recién creado,"
        echo "       sin guilds ni corpus todavía), es esperado y no hay nada que perder --"
        echo "       podés ignorar este ❌ con confianza en ese caso puntual."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────
echo
echo "── Resumen ──"
echo "  $PASS pasaron, $FAIL fallaron, $SKIP omitidos"

if [ "$FAIL" -gt 0 ]; then
    echo "  Resultado: FALLÓ -- revisar los ❌ de arriba antes de dar por terminado el deploy."
    exit 1
fi
echo "  Resultado: OK"
exit 0
