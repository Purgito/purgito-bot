#!/bin/bash
# Comprueba, SOLO LEYENDO, si los datos sensibles de Purgito están en dispositivos cifrados (dm-crypt/LUKS)
# dentro de esta máquina. Es el criterio objetivo del P0 "cifrado en reposo" (docs/CIFRADO_EN_REPOSO.md):
# mientras salga algo "EN CLARO", "RESTO EN CLARO" o "PROVISIONAL", el P0 sigue ABIERTO. No cambia nada
# ni pide secretos.
#
#   sudo deploy/check_encryption_at_rest.sh       # completo (los restos bajo los montajes exigen root)
#
# Código de salida: 0 todo cifrado y verificado · 1 hay datos en claro o una clave provisional ·
# 2 no se pudo verificar algo (sin root) y por tanto NO se da por cerrado.
#
# Qué mira:
#  1. Para cada ruta sensible, el dispositivo que la respalda y si su cadena de capas (lsblk -s) incluye
#     una de tipo "crypt": datos de PostgreSQL y su WAL, secretos (.env, /etc/purgito, túnel), datos y
#     logs del bot, logs de PostgreSQL, copias locales, temporales del bot y cada swap activo.
#  2. Que el journal del sistema no sea persistente (lleva ids de Discord).
#  3. Que no queden RESTOS EN CLARO debajo de los montajes (la capa original que el `bind` oculta).
#  4. Que el volumen no conserve la clave PROVISIONAL de la migración y tenga al menos 2 ranuras.
# Limitación: si el cifrado lo hiciera el HOST (fuera de la VM) esto no lo ve; ese caso se prueba con el
# procedimiento del "canario" de la guía.
set -uo pipefail

BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PGDATA="${PGDATA:-$(sudo -n -u postgres psql -Atc 'show data_directory' 2>/dev/null || echo /var/lib/postgresql)}"
VAULT_IMG="${PV_IMG:-/var/lib/purgito-vault/vault.img}"
KEYFILE="${PV_KEYFILE:-/root/.purgito-vault-interim.key}"
ROOT_OPTIONAL="${CHECK_ROOT_OPTIONAL:-0}"
JOURNAL_DIR="${CHECK_JOURNAL_DIR:-/var/log/journal}"

rc=0
unverified=0
bad() { rc=1; }

check() { # etiqueta ruta
    local label="$1" path="$2" src chain fstype
    if [ ! -e "$path" ]; then printf '%-36s %-12s (no existe: %s)\n' "$label" "n/a" "$path"; return; fi
    if [ -b "$path" ]; then src="$path"; else src="$(findmnt -no SOURCE -T "$path" 2>/dev/null | head -1)"; fi
    src="${src%%\[*}"   # un `bind` se muestra como /dev/mapper/volumen[/subcarpeta]
    if [ -z "$src" ]; then printf '%-36s %-12s (sin dispositivo)\n' "$label" "?"; bad; return; fi
    chain="$(lsblk -nso TYPE "$src" 2>/dev/null | tr '\n' ' ')"
    fstype="$(findmnt -no FSTYPE -T "$path" 2>/dev/null | head -1)"
    if [[ "$src" == /dev/zram* ]]; then
        printf '%-36s %-12s %s\n' "$label" "RAM" "zram: swap comprimido en memoria, nunca toca el disco"
    elif [ "$fstype" = tmpfs ] || [ "$fstype" = ramfs ]; then
        printf '%-36s %-12s %s\n' "$label" "RAM" "$fstype: no persiste en disco"
    elif [[ " $chain " == *" crypt "* ]]; then
        printf '%-36s %-12s %s\n' "$label" "CIFRADO" "$src"
    else
        printf '%-36s %-12s %s [%s]\n' "$label" "EN CLARO" "$src" "$chain"; bad
    fi
}

echo "Cifrado en reposo (dm-crypt) -- $(date -u +%FT%TZ) -- $(hostname)"
echo "-- 1. Rutas sensibles"
check "Datos de PostgreSQL"        "$PGDATA"
check "WAL de PostgreSQL"          "$PGDATA/pg_wal"
check "Logs de PostgreSQL"         "/var/log/postgresql"
check "Secretos del bot (.env)"    "$BOT_DIR/.env"
check "Datos y logs del bot"       "$BOT_DIR/data"
check "Secretos de systemd"        "/etc/purgito"
check "Credencial del túnel"       "/etc/cloudflared"
check "Copias locales de backup"   "/var/backups/purgito"
check "Copias antiguas del bot"    "$HOME/purgito-bot-backups"
tmpdir="$(systemctl show -p Environment bot-purg 2>/dev/null | tr ' ' '\n' | sed -n 's/^\(Environment=\)\?TMPDIR=//p' | head -1)"
if [ -n "$tmpdir" ]; then check "Temporales del bot (TMPDIR)" "$tmpdir"; else check "Temporales del bot (/tmp)" "/tmp"; fi
if [ -n "$(swapon --noheadings --show=NAME 2>/dev/null)" ]; then
    while read -r sw; do check "Swap ($sw)" "$sw"; done < <(swapon --noheadings --show=NAME 2>/dev/null)
else
    printf '%-36s %-12s\n' "Swap" "sin swap"
fi

echo "-- 2. Journal del sistema"
storage="$(systemd-analyze cat-config systemd/journald.conf 2>/dev/null | sed -n 's/^Storage=//p' | tail -1)"
if [ "$storage" = volatile ] && [ -z "$(find "$JOURNAL_DIR" -type f -print -quit 2>/dev/null)" ]; then
    printf '%-36s %-12s\n' "Journal" "VOLÁTIL (RAM)"
elif [ "$storage" = volatile ]; then
    printf '%-36s %-12s %s\n' "Journal" "RESTO EN CLARO" "volátil, pero quedan archivos en $JOURNAL_DIR"; bad
else
    printf '%-36s %-12s %s\n' "Journal" "EN CLARO" "Storage=${storage:-auto}: /var/log/journal persiste en el disco"; bad
fi

echo "-- 2b. Logs de texto y volcados"
if [ "$(id -u)" = 0 ]; then
    fwd="$(systemd-analyze cat-config systemd/journald.conf 2>/dev/null | sed -n 's/^ForwardToSyslog=//p' | tail -1)"
    n="$(cat /var/log/syslog /var/log/syslog.1 2>/dev/null | grep -cE 'python\[[0-9]+\]|bot-purg|studio-purg' || true)"
    if [ "$fwd" != no ]; then
        printf '%-36s %-12s %s\n' "syslog (rsyslog)" "EN CLARO" "journald sigue reenviando los logs a /var/log/syslog"; bad
    elif [ "${n:-0}" -gt 0 ]; then
        printf '%-36s %-12s %s\n' "syslog (rsyslog)" "RESTO EN CLARO" "${n} línea(s) de servicios en /var/log/syslog*: wipe-plaintext"; bad
    else
        printf '%-36s %-12s\n' "syslog (rsyslog)" "limpio"
    fi
    if [ -n "$(find /var/crash -type f -print -quit 2>/dev/null)" ]; then
        printf '%-36s %-12s %s\n' "Volcados (/var/crash)" "RESTO EN CLARO" "hay volcados de fallos con memoria de procesos"; bad
    else
        printf '%-36s %-12s\n' "Volcados (/var/crash)" "limpio"
    fi
elif [ "$ROOT_OPTIONAL" != 1 ]; then
    printf '%-36s %-12s %s\n' "syslog y volcados" "NO COMPROBADO" "ejecuta con sudo"; unverified=1
fi

echo "-- 3. Restos en claro bajo los montajes"
if [ "$(id -u)" = 0 ]; then
    under="$(mktemp -d)"; mount --bind / "$under"
    pg_mount="$(findmnt -no TARGET -T "$PGDATA" 2>/dev/null | head -1)"   # el bind es /var/lib/postgresql, no .../18/main
    for p in "${pg_mount:-$PGDATA}" /var/log/postgresql "$BOT_DIR/data" /etc/purgito /etc/cloudflared /var/backups/purgito "$HOME/purgito-bot-backups" "$BOT_DIR/.env"; do
        if findmnt -rn --mountpoint "$p" >/dev/null 2>&1; then
            if [ -d "$under$p" ] && [ -n "$(find "$under$p" -xdev -type f -size +0 -print -quit 2>/dev/null)" ]; then
                printf '%-36s %-12s %s\n' "$p" "RESTO EN CLARO" "queda contenido sin cifrar bajo el montaje (purgito-vault wipe-plaintext)"; bad
            elif [ -f "$under$p" ] && [ -s "$under$p" ]; then
                printf '%-36s %-12s %s\n' "$p" "RESTO EN CLARO" "el archivo original sigue sin sobrescribir"; bad
            else
                printf '%-36s %-12s\n' "$p" "limpio"
            fi
        fi
    done
    umount "$under"; rmdir "$under"
    # El archivo de swap sirve ahora de almacén del swap CIFRADO (contiene texto cifrado): solo es un
    # resto en claro si NO lo respalda un dispositivo cifrado.
    if [ -f /swapfile ] && ! swapon --noheadings --show=NAME 2>/dev/null | grep -qx /swapfile \
        && [ -z "$(losetup -j /swapfile 2>/dev/null)" ]; then
        if [ -s /swapfile ] && [ -n "$(head -c 1048576 /swapfile | tr -d '\0' | head -c 1)" ]; then
            # Texto cifrado de un swap cifrado anterior (clave aleatoria ya descartada) es incompresible; datos
            # en claro (texto, tablas) se comprimen. Se muestrean 3 trozos de 1 MiB.
            sz=$(stat -c %s /swapfile); worst=0
            for off in 0 $((sz/2/1048576)) $((sz/1048576-1)); do
                n=$(dd if=/swapfile bs=1M skip="$off" count=1 2>/dev/null | gzip -c | wc -c)
                [ "$n" -gt "$worst" ] || worst=$n; [ "${min:-9999999}" -le "$n" ] || min=$n
            done
            if [ "${min:-0}" -ge 1040000 ]; then
                printf '%-36s %-12s %s\n' "/swapfile" "CIFRADO*" "contenido aleatorio (almacén del swap cifrado anterior, clave descartada); *heurística por entropía"
            else
                printf '%-36s %-12s %s\n' "/swapfile" "RESTO EN CLARO" "el archivo de swap conserva datos sin sobrescribir"; bad
            fi
        fi
    fi
else
    if [ "$ROOT_OPTIONAL" = 1 ]; then printf '(omitido: sin root)\n'; else
        printf '%-36s %-12s %s\n' "Restos bajo montajes" "NO COMPROBADO" "ejecuta con sudo"; unverified=1
    fi
fi

echo "-- 4. Volumen y claves"
if [ -e "$KEYFILE" ]; then
    printf '%-36s %-12s %s\n' "Clave provisional" "PROVISIONAL" "$KEYFILE existe: el volumen se abre sin contraseña"; bad
else
    printf '%-36s %-12s\n' "Clave provisional" "eliminada"
fi
if [ -e "$VAULT_IMG" ] && [ "$(id -u)" = 0 ] && command -v cryptsetup >/dev/null; then
    slots="$(cryptsetup luksDump "$VAULT_IMG" 2>/dev/null | awk '/^Keyslots:/{f=1;next} /^[A-Z]/{f=0} f&&/^ *[0-9]+: luks2/{n++} END{print n+0}')"
    if [ "${slots:-0}" -ge 2 ]; then printf '%-36s %-12s %s ranuras\n' "Ranuras LUKS" "ok" "$slots"
    else printf '%-36s %-12s %s ranura(s): se esperan >= 2 (desbloqueo y recuperación)\n' "Ranuras LUKS" "INSUFICIENTE" "${slots:-0}"; bad; fi
fi

echo
if [ "$rc" != 0 ]; then
    echo "RESULTADO: HAY datos o claves sin proteger. El P0 de cifrado en reposo sigue ABIERTO."
    exit 1
elif [ "$unverified" != 0 ]; then
    echo "RESULTADO: lo comprobado está cifrado, pero faltó verificar restos (ejecuta con sudo). NO se da por cerrado."
    exit 2
fi
echo "RESULTADO: todo lo comprobado está en dispositivos cifrados, sin restos en claro ni clave provisional."
exit 0
