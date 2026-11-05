#!/bin/bash
# Escribe en /etc/purgito/backup.env las credenciales R2 de BACKUPS (token "Purgito Backups"),
# pidiéndolas por teclado SIN eco. Ese archivo es root:root 0600: ni el bot ni el usuario
# del runner de backups pueden leerlo; solo systemd (EnvironmentFile=) lo carga al lanzar
# el servicio. Los valores no pasan por argumentos (no salen en `ps`), no van al historial,
# no se imprimen y no se copian a ningún otro sitio.
#
#   sudo /opt/purgito-backup/deploy/set_backup_credentials.sh             # las 2 credenciales de R2
#   sudo /opt/purgito-backup/deploy/set_backup_credentials.sh --webhook   # el webhook de alertas de Discord
#
# Se ejecuta SOLO desde la copia de root en /opt/purgito-backup: el script del checkout del
# bot es escribible por el usuario del bot, y alguien con acceso a ese usuario podría
# sustituirlo para capturar lo que escribas. Cambia solo R2_BACKUP_ACCESS_KEY_ID y
# R2_BACKUP_SECRET_ACCESS_KEY; el resto del archivo queda igual.
set -euo pipefail
umask 077

ENV_FILE="${ENV_FILE:-/etc/purgito/backup.env}"
die() { echo "ERROR: $*" >&2; exit 1; }

if [ "$ENV_FILE" = "/etc/purgito/backup.env" ]; then
    [ "$(id -u)" = "0" ] || die "ejecútalo con sudo"
    self="$(readlink -f "${BASH_SOURCE[0]}")"
    case "$self" in
        /opt/purgito-backup/deploy/*) ;;
        *) die "ejecútalo desde /opt/purgito-backup/deploy/ (copia de root), no desde el checkout del bot" ;;
    esac
    [ "$(stat -c %U "$self")" = "root" ] && [ -z "$(find "$self" -perm /022 2>/dev/null)" ] \
        || die "$self no es de root o es escribible por otros: no se continúa"
fi
[ -f "$ENV_FILE" ] || die "no existe $ENV_FILE (lo crea deploy/install_backup_runner.sh)"

if [ "${1:-}" = "--webhook" ]; then
    IFS= read -rsp "BACKUP_ALERT_WEBHOOK (URL del webhook de Discord): " hook; echo >&2
    if [[ ! "$hook" =~ ^https://(discord|discordapp)\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+$ ]]; then
        die "no parece una URL de webhook de Discord (https://discord.com/api/webhooks/<id>/<token>). No se cambió nada."
    fi
    tmp="$(mktemp "$ENV_FILE.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    NEW_HOOK="$hook" awk '
        /^BACKUP_ALERT_WEBHOOK=/ { if (!h) { print "BACKUP_ALERT_WEBHOOK=" ENVIRON["NEW_HOOK"]; h = 1 } ; next }
        { print }
        END { if (!h) print "BACKUP_ALERT_WEBHOOK=" ENVIRON["NEW_HOOK"] }' "$ENV_FILE" > "$tmp"
    unset hook
    if [ "$(id -u)" = "0" ]; then chown root:root "$tmp"; fi
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
    trap - EXIT
    echo "OK: BACKUP_ALERT_WEBHOOK guardado en $ENV_FILE ($(stat -c '%U:%G %a' "$ENV_FILE"))." >&2
    exit 0
fi

IFS= read -rsp "R2_BACKUP_ACCESS_KEY_ID (token Backups): " key_id; echo >&2
IFS= read -rsp "R2_BACKUP_SECRET_ACCESS_KEY (token Backups): " secret; echo >&2

if [[ ! "$key_id" =~ ^[A-Za-z0-9]{32}$ ]]; then
    die "R2_BACKUP_ACCESS_KEY_ID no tiene el formato esperado (32 alfanuméricos; recibidos: ${#key_id}). No se cambió nada."
fi
if [[ ! "$secret" =~ ^[A-Za-z0-9]{64}$ ]]; then
    die "R2_BACKUP_SECRET_ACCESS_KEY no tiene el formato esperado (64 alfanuméricos; recibidos: ${#secret}). No se cambió nada."
fi

tmp="$(mktemp "$ENV_FILE.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
NEW_ID="$key_id" NEW_SECRET="$secret" awk '
    /^R2_BACKUP_ACCESS_KEY_ID=/ { if (!id) { print "R2_BACKUP_ACCESS_KEY_ID=" ENVIRON["NEW_ID"]; id = 1 } ; next }
    /^R2_BACKUP_SECRET_ACCESS_KEY=/ { if (!sec) { print "R2_BACKUP_SECRET_ACCESS_KEY=" ENVIRON["NEW_SECRET"]; sec = 1 } ; next }
    { print }
    END {
        if (!id) print "R2_BACKUP_ACCESS_KEY_ID=" ENVIRON["NEW_ID"]
        if (!sec) print "R2_BACKUP_SECRET_ACCESS_KEY=" ENVIRON["NEW_SECRET"]
    }' "$ENV_FILE" > "$tmp"
unset key_id secret
if [ "$(id -u)" = "0" ]; then chown root:root "$tmp"; fi
chmod 600 "$tmp"
mv "$tmp" "$ENV_FILE"
trap - EXIT
echo "OK: R2_BACKUP_ACCESS_KEY_ID (32) y R2_BACKUP_SECRET_ACCESS_KEY (64) guardadas en $ENV_FILE ($(stat -c '%U:%G %a' "$ENV_FILE"))." >&2
