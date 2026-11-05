#!/bin/bash
# Escribe en el .env del bot las credenciales de los avisos por Gmail del Centro de Privacidad
# (PRIVACY_ALERT_SMTP_USER, PRIVACY_ALERT_SMTP_PASSWORD y, opcional, PRIVACY_ALERT_TO), pidiéndolas
# por teclado SIN eco. Los valores no pasan por argumentos (no salen en `ps`), no van al historial,
# no se imprimen y no se copian a ningún otro sitio; solo se muestran sus LONGITUDES.
#
#   deploy/set_privacy_alert_credentials.sh        # como el usuario del bot (dueño del .env)
#
# La contraseña es una "contraseña de aplicación" de Google (Cuenta > Seguridad > Verificación en
# dos pasos > Contraseñas de aplicaciones), NO la contraseña de la cuenta. Usa preferiblemente una
# cuenta dedicada: este .env también lo lee el bot. Cambia solo esas variables; el resto queda igual.
# Después hay que reiniciar bot-purg para que las lea.
set -euo pipefail
umask 077

ENV_FILE="${ENV_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env}"
die() { echo "ERROR: $*" >&2; exit 1; }
[ -f "$ENV_FILE" ] && [ -w "$ENV_FILE" ] || die "no puedo escribir $ENV_FILE (¿eres el usuario del bot?)"

IFS= read -rsp "PRIVACY_ALERT_SMTP_USER (cuenta Gmail que envía): " user; echo >&2
IFS= read -rsp "PRIVACY_ALERT_SMTP_PASSWORD (contraseña de aplicación): " pass; echo >&2
IFS= read -rsp "PRIVACY_ALERT_TO (destinatario; vacío = la misma cuenta): " to; echo >&2

[[ "$user" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "el usuario no parece un correo. No se cambió nada."
pass="${pass// /}"   # Google las muestra en bloques separados por espacios
[[ "$pass" =~ ^[A-Za-z0-9]{16}$ ]] || die "la contraseña de aplicación son 16 letras/números. No se cambió nada."
if [ -n "$to" ]; then
    [[ "$to" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "el destinatario no parece un correo. No se cambió nada."
fi

tmp="$(mktemp "$ENV_FILE.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
NEW_USER="$user" NEW_PASS="$pass" NEW_TO="$to" awk '
    /^PRIVACY_ALERT_SMTP_USER=/     { next }
    /^PRIVACY_ALERT_SMTP_PASSWORD=/ { next }
    /^PRIVACY_ALERT_TO=/            { next }
    { print }
    END {
        print "PRIVACY_ALERT_SMTP_USER=" ENVIRON["NEW_USER"]
        print "PRIVACY_ALERT_SMTP_PASSWORD=" ENVIRON["NEW_PASS"]
        if (ENVIRON["NEW_TO"] != "") print "PRIVACY_ALERT_TO=" ENVIRON["NEW_TO"]
    }' "$ENV_FILE" > "$tmp"
chmod --reference="$ENV_FILE" "$tmp"
mv "$tmp" "$ENV_FILE"; trap - EXIT
echo "OK: guardado en $ENV_FILE ($(stat -c '%U:%G %a' "$ENV_FILE")): usuario ${#user} car., contraseña ${#pass} car., destinatario ${#to} car." >&2
echo "Reinicia el bot para aplicar: sudo systemctl restart bot-purg" >&2
