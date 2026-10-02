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
WARN=0

ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
skip() { echo "  ⏭️  $1 (omitido: $2)"; SKIP=$((SKIP+1)); }
# Aviso que no cuenta como falla: algo a resolver, pero el bot anda así.
warn() { echo "  ⚠️  $1"; WARN=$((WARN+1)); }

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

    # Un nombre repetido en .env y en limits.env/urls.env: manda el versionado
    # (src/config.py load_env_files), así que el del .env es un resto que
    # confunde. Solo nombres, nunca valores.
    dup_names=""
    for versioned in limits.env urls.env; do
        if [ -f "$REPO_DIR/$versioned" ]; then
            dup_names+="$(comm -12 \
                <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$ENV_FILE" | tr -d '=' | sort -u) \
                <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$REPO_DIR/$versioned" | tr -d '=' | sort -u) \
                | tr '\n' ' ')"
        fi
    done
    if [ -n "$dup_names" ]; then
        warn ".env repite variables de limits.env/urls.env (manda el archivo versionado, borrarlas del .env): $dup_names"
    else
        ok ".env no repite variables de limits.env ni urls.env"
    fi

    # Variables obligatorias: DISCORD_TOKEN y DATABASE_URL (hardcoded acá -- son
    # las únicas que no tienen default y no están en la lista del dashboard, así que no hay una lista en
    # el código de la que extraerla) + lo que src/config.py declara como
    # obligatorio para el dashboard (bloque `_missing = [...]` en config.py:
    # se parsea de ahí en vez de hardcodearlo para no desactualizarse el día
    # que se agregue una variable nueva a esa lista).
    CONFIG_PY="$REPO_DIR/src/config.py"
    required_vars=(DISCORD_TOKEN DATABASE_URL)
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

    # La clave de la cookie de sesión sale de sha256(SESSION_SECRET): un secreto
    # corto deja forjar sesiones (ver MIN_SESSION_KEY_LENGTH en config.py).
    secret_value="$(grep -E "^SESSION_SECRET=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-)"
    if [ -n "$secret_value" ]; then
        if [ "${#secret_value}" -ge 32 ]; then
            ok "SESSION_SECRET tiene 32 caracteres o más"
        else
            bad "SESSION_SECRET tiene menos de 32 caracteres -- generar uno nuevo: python3 -c \"import secrets; print(secrets.token_hex(32))\" (desloguea a todos una vez)"
        fi
    fi

    # R2 es opcional, pero a medias no sirve. Son tres buckets: imágenes y GIFs
    # (públicos: nombre + URL pública) y backups (PRIVADO: solo nombre, sin URL).
    env_val() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-; }
    if [ -z "$(env_val R2_ENDPOINT_URL)" ] && [ -z "$(env_val R2_ACCESS_KEY_ID)" ] && [ -z "$(env_val R2_SECRET_ACCESS_KEY)" ]; then
        skip "variables de R2" "sin credenciales R2 en .env (los GIFs/imágenes se guardan con su URL original y los backups quedan solo en local)"
    else
        for var in R2_ENDPOINT_URL R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_IMAGES_BUCKET R2_IMAGES_PUBLIC_URL R2_GIFS_BUCKET R2_GIFS_PUBLIC_URL; do
            if [ -n "$(env_val "$var")" ]; then
                ok "$var presente en .env"
            elif [ -n "$(env_val R2_BUCKET_NAME)" ] && [ -n "$(env_val R2_PUBLIC_URL)" ] && [[ "$var" == R2_IMAGES_* || "$var" == R2_GIFS_* ]]; then
                warn "$var vacía: cae en el fallback R2_BUCKET_NAME/R2_PUBLIC_URL (esquema de un solo bucket, transitorio -- DEPLOY.md § Migrar a tres buckets de R2)"
            else
                bad "$var falta o está vacía en .env"
            fi
        done
        if [ -n "$(env_val R2_BACKUP_BUCKET)" ]; then
            ok "R2_BACKUP_BUCKET presente en .env (los backups se suben al bucket privado)"
        else
            warn "R2_BACKUP_BUCKET vacía: deploy/backup_db.sh deja los backups solo en local"
        fi
        if [ -n "$(env_val R2_BUCKET_NAME)" ] || [ -n "$(env_val R2_PUBLIC_URL)" ]; then
            warn "R2_BUCKET_NAME / R2_PUBLIC_URL siguen en .env: borrarlas cuando termine la migración (DEPLOY.md § Migrar a tres buckets de R2)"
        else
            ok "sin variables R2 del esquema viejo (R2_BUCKET_NAME / R2_PUBLIC_URL)"
        fi
    fi
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

# Que el venv exista no garantiza que TODO lo que el código importa esté
# instalado ahí: si requirements.txt suma una dependencia nueva (ej.
# imageio-ffmpeg en la Fase 4 de cogs/imagefx.py) y el deploy corre
# "git pull" + restart sin "pip install -r requirements.txt" antes, el bot
# carga bien varias extensiones y recién explota al llegar a la que use la
# dependencia faltante -- ModuleNotFoundError, systemd reinicia en loop
# (ver troubleshooting en DEPLOY.md). Probar de importar cada extensión de
# bot.py:EXTENSIONS (+ webapi, que bot.py también importa al arrancar) acá
# lo detecta ANTES del restart, no después mirando journalctl.
BOT_PY="$REPO_DIR/src/bot.py"
if [ ! -x "$VENV_PY" ]; then
    skip "import de extensiones y webapi" "no hay venv todavía para probar"
elif [ ! -f "$BOT_PY" ]; then
    skip "import de extensiones y webapi" "no se encontró $BOT_PY"
else
    modules=(webapi)
    while IFS= read -r ext; do
        modules+=("$ext")
    done < <(sed -n '/^EXTENSIONS = \[/,/^\]/p' "$BOT_PY" | grep -oE '"[a-zA-Z0-9_.]+"' | tr -d '"')

    for mod in "${modules[@]}"; do
        import_err="$("$VENV_PY" -c "
import sys
sys.path.insert(0, '$REPO_DIR/src')
import importlib
importlib.import_module('$mod')
" 2>&1)"
        if [ $? -eq 0 ]; then
            ok "'$mod' importa sin errores"
        else
            bad "'$mod' falla al importar -- probablemente falta 'pip install -r requirements.txt' tras un cambio a requirements.txt:"
            echo "$import_err" | tail -n 5 | sed 's/^/       /'
        fi
    done
fi

# src/config.py arma ANNOUNCEMENTS_TIMEZONE con zoneinfo.ZoneInfo() al nivel
# de módulo -- si el sistema no tiene los datos de esa zona horaria (tzdata),
# el import de config.py revienta con ZoneInfoNotFoundError y el bot no
# arranca, antes de que exista logging que lo explique. Ubuntu y Oracle Linux
# traen tzdata por defecto, pero una imagen mínima o un container no
# necesariamente -- ver docs/PORTABILITY.md sobre "containers" como posible
# cambio de arquitectura futuro.
TZ_VALUE="$(grep -E '^ANNOUNCEMENTS_TIMEZONE=' "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-)"
TZ_VALUE="${TZ_VALUE:-America/Santiago}"
if [ -x "$VENV_PY" ]; then
    if "$VENV_PY" -c "from zoneinfo import ZoneInfo; ZoneInfo('$TZ_VALUE')" >/dev/null 2>&1; then
        ok "tzdata tiene la zona horaria '$TZ_VALUE' (ANNOUNCEMENTS_TIMEZONE)"
    else
        bad "falta tzdata para '$TZ_VALUE' (ANNOUNCEMENTS_TIMEZONE) -- src/config.py no importa sin esto, el bot no arranca. Instalar el paquete tzdata del sistema (o 'pip install tzdata' en el venv)"
    fi
else
    skip "tzdata para '$TZ_VALUE' (ANNOUNCEMENTS_TIMEZONE)" "no hay venv todavía para probar con zoneinfo"
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
        local code attempt
        # 3 intentos con 1s de espera entre medio -- correr esto justo
        # después de un restart (systemctl restart + nginx todavía
        # arrancando el upstream) puede dar un 000/502 transitorio que no
        # es un fallo real, solo timing.
        for attempt in 1 2 3; do
            code="$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $HEALTH_HOST" "http://localhost${path}" 2>/dev/null)"
            [ "$code" = "$want" ] && break
            [ "$attempt" -lt 3 ] && sleep 1
        done
        if [ "$code" = "$want" ]; then
            ok "$path -> $code"
        else
            bad "$path -> $code (esperado $want, tras 3 intentos)"
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
    # server_name -- ya pasó dos veces. NO se puede buscar "cualquier
    # corchete" -- `listen [::]:80;` (IPv6) es sintaxis nginx legítima y
    # daba falso positivo. Se busca específicamente la firma de un link
    # markdown pegado: "](http" o "](https".
    matches="$(grep -rnHE '\]\(https?' "$NGINX_CONF_DIR"/*.conf 2>/dev/null)"
    if [ -z "$matches" ]; then
        ok "sin restos de autolinking (\"](http...\") en $NGINX_CONF_DIR/*.conf"
    else
        bad "restos de autolinking encontrados en config de nginx (link markdown pegado al copiar una URL):"
        echo "$matches" | sed 's/^/       /'
    fi
fi

# ─────────────────────────────────────────────────────────────────────────
section "6. PostgreSQL"

DB_URL="$(grep -E "^DATABASE_URL=" "$REPO_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2-)"
pg_re='^postgres(ql)?://([^:@/]+)(:([^@]*))?@([^:/]+)(:([0-9]+))?/([^?]+)'
if [ -z "$DB_URL" ]; then
    skip "conexión a PostgreSQL" "DATABASE_URL no está en .env (ya reportado arriba)"
elif [[ ! "$DB_URL" =~ $pg_re ]]; then
    bad "DATABASE_URL no tiene la forma postgresql://usuario:clave@host:puerto/base"
elif ! command -v psql >/dev/null 2>&1; then
    skip "conexión a PostgreSQL" "falta el cliente psql (apt install postgresql-client)"
else
    PGUSER="${BASH_REMATCH[2]}"
    PGPASSWORD="$(printf '%b' "${BASH_REMATCH[4]//%/\\x}")"
    PGHOST="${BASH_REMATCH[5]}"
    PGPORT="${BASH_REMATCH[7]:-5432}"
    PGDATABASE="${BASH_REMATCH[8]}"
    export PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE

    if [ "$PGUSER" = "postgres" ]; then
        warn "DATABASE_URL usa el superusuario postgres: crear un usuario dedicado (DEPLOY.md § PostgreSQL)"
    else
        ok "DATABASE_URL usa un usuario dedicado ($PGUSER), no postgres"
    fi

    case "$PGHOST" in
        127.0.0.1|localhost|::1)
            if systemctl is-active --quiet postgresql 2>/dev/null; then
                ok "servicio postgresql activo"
            else
                bad "servicio postgresql no está activo (sudo systemctl enable --now postgresql)"
            fi
            if systemctl cat "$SERVICE_NAME" 2>/dev/null | grep -q 'postgresql.service'; then
                ok "el unit $SERVICE_NAME espera a postgresql.service (After=/Wants=)"
            else
                warn "el unit $SERVICE_NAME no menciona postgresql.service: tras un reinicio del servidor el bot puede arrancar antes que la base (regenerar el unit con deploy/render_service.sh)"
            fi
            ;;
    esac

    if [ "$(psql -Atc 'SELECT 1' 2>/dev/null)" = "1" ]; then
        ok "conecta a $PGDATABASE en $PGHOST:$PGPORT como $PGUSER"
        tables="$(psql -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null)"
        if [ "${tables:-0}" -ge 40 ]; then
            ok "esquema aplicado ($tables tablas en public)"
        else
            bad "la base tiene ${tables:-0} tablas: faltan las de Purgito (arrancar el bot una vez las crea, o ver DEPLOY.md § Preparar una base nueva)"
        fi
        case "$(psql -Atc "SELECT rolsuper FROM pg_roles WHERE rolname=current_user" 2>/dev/null)" in
            f) ok "el usuario de la app no es superusuario" ;;
            t) warn "el usuario de la app es superusuario de PostgreSQL: bajarle los privilegios" ;;
        esac
    else
        bad "no se pudo conectar a PostgreSQL con DATABASE_URL (host=$PGHOST puerto=$PGPORT base=$PGDATABASE usuario=$PGUSER)"
    fi
    unset PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE
fi

if [ -f "$REPO_DIR/data/bot.db" ]; then
    warn "data/bot.db (SQLite vieja) sigue en disco: el bot ya no la usa; conservarla como rollback hasta dar la migración por buena (DEPLOY.md § Rollback a SQLite)"
fi

# ─────────────────────────────────────────────────────────────────────────
echo
echo "── Resumen ──"
echo "  $PASS pasaron, $FAIL fallaron, $SKIP omitidos, $WARN avisos"

if [ "$FAIL" -gt 0 ]; then
    echo "  Resultado: FALLÓ -- revisar los ❌ de arriba antes de dar por terminado el deploy."
    exit 1
fi
echo "  Resultado: OK"
exit 0
