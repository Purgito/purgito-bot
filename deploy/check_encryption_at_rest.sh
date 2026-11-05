#!/bin/bash
# Comprueba, SOLO LEYENDO, si los datos de Purgito están en un dispositivo cifrado (dm-crypt/LUKS)
# dentro de esta máquina. Es el criterio objetivo del P0 "cifrado en reposo" (docs/CIFRADO_EN_REPOSO.md):
# mientras salga algún "EN CLARO", el P0 sigue abierto. No cambia nada, no pide secretos.
#
#   deploy/check_encryption_at_rest.sh            # informe legible; código 0 solo si TODO está cifrado
#
# Qué mira: el dispositivo que respalda cada ruta y si en su cadena de capas (lsblk -s) hay una de
# tipo "crypt". Rutas: datos de PostgreSQL, secretos (.env y /etc/purgito), copias locales, archivo de
# intercambio (swap) y el checkout del bot. Limitación: si el cifrado lo hace el HOST (fuera de la VM)
# esto no lo ve; ese caso se prueba con el procedimiento de "canario" de la guía.
set -uo pipefail

BOT_DIR="${BOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PGDATA="${PGDATA:-$(sudo -n -u postgres psql -Atc 'show data_directory' 2>/dev/null || echo /var/lib/postgresql)}"

rc=0
check() {
    local label="$1" path="$2" src chain
    if [ ! -e "$path" ]; then printf '%-34s %-9s (no existe: %s)\n' "$label" "n/a" "$path"; return; fi
    src="$(findmnt -no SOURCE -T "$path" 2>/dev/null | head -1)"
    if [ -z "$src" ]; then printf '%-34s %-9s (sin dispositivo)\n' "$label" "?"; rc=1; return; fi
    chain="$(lsblk -nso TYPE "$src" 2>/dev/null | tr '\n' ' ')"
    if [[ " $chain " == *" crypt "* ]]; then
        printf '%-34s %-9s %s [%s]\n' "$label" "CIFRADO" "$src" "$chain"
    else
        printf '%-34s %-9s %s [%s]\n' "$label" "EN CLARO" "$src" "$chain"
        rc=1
    fi
}

echo "Cifrado en reposo (dm-crypt) -- $(date -u +%FT%TZ) -- $(hostname)"
check "Datos de PostgreSQL"       "$PGDATA"
check "Secretos del bot (.env)"   "$BOT_DIR/.env"
check "Secretos de systemd"       "/etc/purgito"
check "Copias locales de backup"  "/var/backups/purgito"
check "Raíz del sistema"          "/"
if swapon --noheadings --show=NAME 2>/dev/null | grep -q .; then
    while read -r sw; do check "Swap ($sw)" "$sw"; done < <(swapon --noheadings --show=NAME 2>/dev/null)
else
    printf '%-34s %-9s\n' "Swap" "sin swap"
fi
echo
if [ "$rc" = 0 ]; then
    echo "RESULTADO: todo lo comprobado está en dispositivos cifrados."
else
    echo "RESULTADO: HAY datos en claro. El P0 de cifrado en reposo sigue ABIERTO."
fi
exit "$rc"
