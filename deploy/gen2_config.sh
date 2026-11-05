#!/bin/bash
# Pasa la configuración de backups a la generación 2 (clave age nueva + prefijo gen2/)
# tocando SOLO dos variables del .env, con vuelta atrás.
#
#   deploy/gen2_config.sh status
#   deploy/gen2_config.sh apply <age1...>         # dry-run: muestra qué cambiaría
#   deploy/gen2_config.sh apply <age1...> --yes   # lo aplica
#   deploy/gen2_config.sh revert [--yes]          # restaura las dos líneas anteriores
#
# Variables que toca: BACKUP_AGE_RECIPIENTS y R2_BACKUP_PREFIX (ninguna es secreta: una es
# una clave PÚBLICA). Las líneas anteriores se guardan en $STATE_FILE (0600) antes de
# cambiar nada. Nunca imprime ni copia ninguna otra línea del .env. NO toca las
# credenciales R2_BACKUP_ACCESS_KEY_ID / R2_BACKUP_SECRET_ACCESS_KEY: esas las pones tú
# directamente en el .env.
#
# Ojo: la clave anterior está en age-revoked-recipients.txt, así que "revertir" devuelve el
# .env a como estaba, pero backup_db.sh seguirá negándose a cifrar con ella (a propósito).
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$script_dir/../.env}"
STATE_FILE="${STATE_FILE:-$HOME/purgito-bot-backups/gen2-config.previous}"
REVOKED="$script_dir/age-revoked-recipients.txt"
PREFIX_VALUE="gen2/"
KEYS=(BACKUP_AGE_RECIPIENTS R2_BACKUP_PREFIX)

die() { echo "ERROR: $*" >&2; exit 1; }

# Última línea activa de la variable $1 en el .env (vacío si no está).
current_line() {
    grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE" | tail -n 1 || true
}
short() { local v="${1#*=}"; [ "${#v}" -gt 20 ] && echo "${v:0:10}…${v: -6}" || echo "$v"; }
# Valor abreviado de una línea, o el texto $2 si está vacía.
show() { if [ -n "$1" ]; then short "$1"; else echo "$2"; fi; }

# Reescribe el .env sin las líneas de KEYS y con las líneas de "$@" al final.
rewrite_env() {
    local tmp
    tmp="$(mktemp "$ENV_FILE.XXXXXX")"
    chmod --reference="$ENV_FILE" "$tmp"
    awk -v k1="${KEYS[0]}" -v k2="${KEYS[1]}" '
        $0 ~ "^[[:space:]]*(export[[:space:]]+)?(" k1 "|" k2 ")[[:space:]]*=" { next }
        { print }' "$ENV_FILE" > "$tmp"
    local line
    for line in "$@"; do [ -z "$line" ] || printf '%s\n' "$line" >> "$tmp"; done
    mv "$tmp" "$ENV_FILE"
}

cmd="${1:-status}"
[ -f "$ENV_FILE" ] || die "no existe $ENV_FILE"

case "$cmd" in
status)
    for k in "${KEYS[@]}"; do
        line="$(current_line "$k")"
        if [ -n "$line" ]; then echo "$k = $(short "$line")"; else echo "$k = (no definida)"; fi
    done
    [ -f "$STATE_FILE" ] && echo "estado guardado: $STATE_FILE" || echo "estado guardado: ninguno (no se ha aplicado)"
    ;;
apply)
    new="${2:-}"
    yes="${3:-}"
    [[ "$new" =~ ^age1[a-z0-9]{50,}$ ]] || die "uso: gen2_config.sh apply <clave pública age1...> [--yes]"
    [ -r "$REVOKED" ] || die "falta $REVOKED"
    if grep -qxF -- "$new" "$REVOKED"; then die "esa clave está REVOCADA"; fi
    [ ! -e "$STATE_FILE" ] || die "ya hay un cambio aplicado ($STATE_FILE): ejecuta revert antes"
    old_rec="$(current_line BACKUP_AGE_RECIPIENTS)"
    old_pre="$(current_line R2_BACKUP_PREFIX)"
    echo "BACKUP_AGE_RECIPIENTS: $(show "$old_rec" "(no definida)")  ->  $(short "x=$new")"
    echo "R2_BACKUP_PREFIX:      $(show "$old_pre" "(no definida)")  ->  $PREFIX_VALUE"
    if [ "$yes" != "--yes" ]; then
        echo "(dry-run: no se cambió nada; añade --yes para aplicar)"
        exit 0
    fi
    mkdir -p "$(dirname "$STATE_FILE")"
    {
        echo "# gen2_config.sh $(date -Is): líneas ANTERIORES del .env (no secretas)"
        echo "recipients<<${old_rec}"
        echo "prefix<<${old_pre}"
    } > "$STATE_FILE"
    chmod 600 "$STATE_FILE"
    rewrite_env "BACKUP_AGE_RECIPIENTS=$new" "R2_BACKUP_PREFIX=$PREFIX_VALUE"
    echo "aplicado. Para volver atrás: deploy/gen2_config.sh revert --yes"
    ;;
revert)
    [ -f "$STATE_FILE" ] || die "no hay nada que revertir ($STATE_FILE no existe)"
    old_rec="$(sed -n 's/^recipients<<//p' "$STATE_FILE")"
    old_pre="$(sed -n 's/^prefix<<//p' "$STATE_FILE")"
    echo "se restaurará: $(show "$old_rec" "(sin BACKUP_AGE_RECIPIENTS)") | $(show "$old_pre" "(sin R2_BACKUP_PREFIX)")"
    if [ "${2:-}" != "--yes" ]; then
        echo "(dry-run: no se cambió nada; añade --yes para revertir)"
        exit 0
    fi
    rewrite_env "$old_rec" "$old_pre"
    mv "$STATE_FILE" "$STATE_FILE.reverted-$(date +%Y%m%d%H%M%S)"
    echo "revertido."
    ;;
*)
    die "uso: gen2_config.sh status | apply <age1...> [--yes] | revert [--yes]"
    ;;
esac
