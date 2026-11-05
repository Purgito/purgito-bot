#!/bin/bash
# Escribe en el .env las credenciales R2 de IMÁGENES y GIFs (token "Purgito Media"),
# pidiéndolas por teclado SIN eco. Los valores no pasan por argumentos de línea de
# comandos (no salen en `ps`), no se guardan en el historial de la shell, no se imprimen
# y no se copian a ningún otro archivo.
#
#   deploy/set_media_credentials.sh
#
# Solo cambia R2_ACCESS_KEY_ID y R2_SECRET_ACCESS_KEY (el resto del .env queda igual y
# conserva sus permisos). Las credenciales de BACKUPS no van al .env: el bot lee el .env
# entero en su entorno; ver deploy/backup_manual.sh.
#
# Después hay que reiniciar bot-purg (el cliente de R2 se crea una vez al primer uso).
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$script_dir/../.env}"
[ -f "$ENV_FILE" ] || { echo "ERROR: no existe $ENV_FILE" >&2; exit 1; }
[ -w "$ENV_FILE" ] || { echo "ERROR: $ENV_FILE no es escribible por este usuario" >&2; exit 1; }
mode="$(stat -c %a "$ENV_FILE")"
[ "$mode" = "600" ] || { echo "ERROR: $ENV_FILE tiene permisos $mode (debe ser 600). No se cambió nada." >&2; exit 1; }

IFS= read -rsp "R2_ACCESS_KEY_ID (token Media): " key_id; echo >&2
IFS= read -rsp "R2_SECRET_ACCESS_KEY (token Media): " secret; echo >&2

# Formato de un token de R2 (id de 32 y secreto de 64 caracteres alfanuméricos). Solo se
# informa la longitud, nunca el contenido.
if [[ ! "$key_id" =~ ^[A-Za-z0-9]{32}$ ]]; then
    echo "ERROR: R2_ACCESS_KEY_ID no tiene el formato esperado (32 caracteres alfanuméricos; recibidos: ${#key_id}). No se cambió nada." >&2
    exit 1
fi
if [[ ! "$secret" =~ ^[A-Za-z0-9]{64}$ ]]; then
    echo "ERROR: R2_SECRET_ACCESS_KEY no tiene el formato esperado (64 caracteres alfanuméricos; recibidos: ${#secret}). No se cambió nada." >&2
    exit 1
fi

tmp="$(mktemp "$ENV_FILE.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
chmod --reference="$ENV_FILE" "$tmp"
# Los valores viajan por el entorno del proceso awk, no por sus argumentos.
NEW_ID="$key_id" NEW_SECRET="$secret" awk '
    /^[[:space:]]*(export[[:space:]]+)?R2_ACCESS_KEY_ID[[:space:]]*=/ {
        if (!id) { print "R2_ACCESS_KEY_ID=" ENVIRON["NEW_ID"]; id = 1 } ; next }
    /^[[:space:]]*(export[[:space:]]+)?R2_SECRET_ACCESS_KEY[[:space:]]*=/ {
        if (!sec) { print "R2_SECRET_ACCESS_KEY=" ENVIRON["NEW_SECRET"]; sec = 1 } ; next }
    { print }
    END {
        if (!id) print "R2_ACCESS_KEY_ID=" ENVIRON["NEW_ID"]
        if (!sec) print "R2_SECRET_ACCESS_KEY=" ENVIRON["NEW_SECRET"]
    }' "$ENV_FILE" > "$tmp"
unset key_id secret
mv "$tmp" "$ENV_FILE"
trap - EXIT
echo "OK: R2_ACCESS_KEY_ID (32) y R2_SECRET_ACCESS_KEY (64) actualizadas en $ENV_FILE (permisos $(stat -c %a "$ENV_FILE"))." >&2
echo "Siguiente: ~/purgito-bot/.venv/bin/python scripts/r2_backup.py media-check   y luego reiniciar bot-purg." >&2
