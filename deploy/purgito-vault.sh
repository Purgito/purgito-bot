#!/bin/bash
# purgito-vault: volumen cifrado (LUKS2) para todo lo sensible de Purgito.
#
# Qué es: un contenedor LUKS2 en un archivo (esta VM tiene un solo disco virtual, y así no se toca el
# disco actual) que se monta en /srv/purgito. Las rutas sensibles se SUPERPONEN con montajes `bind`
# desde ese volumen, de modo que PostgreSQL (con su WAL), los secretos, las copias locales, los logs y
# los temporales viven cifrados sin cambiar ninguna configuración. El contenido original queda DEBAJO
# del montaje (es la marcha atrás) hasta que `wipe-plaintext` lo sobrescribe.
#
# Sin el volumen abierto (p. ej. tras un reinicio) PostgreSQL, el bot, Studio, el túnel y los backups
# NO arrancan (ConditionPathIsMountPoint): la web queda caída hasta que alguien teclee la contraseña.
# Ese es el precio de que una snapshot o copia del disco no sirva de nada sin ella.
#
#   sudo purgito-vault status             # estado, sin cambiar nada
#   sudo purgito-vault open               # tras un reinicio: pide la contraseña, monta, arranca servicios
#   sudo purgito-vault close              # para servicios, desmonta y cierra el volumen
#   sudo purgito-vault enroll             # (una vez) pone TUS contraseñas, quita la clave provisional,
#                                         #   respalda el encabezado cifrado con age y lo sube a R2
#   sudo purgito-vault wipe-plaintext --yes   # sobrescribe y borra lo que quedó en claro debajo
#
# Preparación (la hace quien despliega, ver docs/CIFRADO_EN_REPOSO.md): install, bootstrap, migrate,
# swap-encrypt, journal-volatile.
#
# Se ejecuta SOLO desde la copia de root en /opt/purgito-vault (el checkout del bot es escribible por
# el usuario del bot: alguien con acceso a ese usuario podría sustituir el script para capturar lo que
# teclees). Las contraseñas las pide cryptsetup directamente en tu terminal: no pasan por argumentos,
# variables, archivos ni logs de este script.
set -euo pipefail
umask 077

# Configuracion de root (/etc/purgito-vault.conf): fija PV_IMG (dispositivo del volumen, p. ej. una particion
# /dev/disk/by-partuuid/...). Solo se lee si es de root y no escribible por otros.
CONF="${PV_CONF:-/etc/purgito-vault.conf}"
if [ -f "$CONF" ] && [ "$(stat -c %U "$CONF")" = root ] && [ -z "$(find "$CONF" -perm /022 2>/dev/null)" ]; then
    # shellcheck disable=SC1090
    . "$CONF"
fi

IMG="${PV_IMG:-/var/lib/purgito-vault/vault.img}"
SIZE="${PV_SIZE:-8G}"
MAPPER="${PV_MAPPER:-purgito-vault}"
MNT="${PV_MNT:-/srv/purgito}"
STATE="${PV_STATE:-/var/lib/purgito-vault}"
KEYFILE="${PV_KEYFILE:-/root/.purgito-vault-interim.key}"
INSTALL_DIR="${PV_INSTALL_DIR:-/opt/purgito-vault}"
BACKUP_ENV="${PV_BACKUP_ENV:-/etc/purgito/backup.env}"
SWAPFILE="${PV_SWAPFILE:-/swapfile}"
# Servicios que dependen del volumen. Orden de arranque; al cerrar se invierte.
read -r -a SERVICES <<< "${PV_SERVICES-postgresql@18-main bot-purg studio-purg cloudflared}"
# subcarpeta-del-volumen:ruta-original[:file]
read -r -a BINDS <<< "${PV_BINDS-postgresql:/var/lib/postgresql pglog:/var/log/postgresql backups:/var/backups/purgito botdata:/home/purgito/purgito-bot/data legacy-backups:/home/purgito/purgito-bot-backups etc-purgito:/etc/purgito cloudflared:/etc/cloudflared botenv:/home/purgito/purgito-bot/.env:file}"
SKIP_UNITS="${PV_SKIP_UNITS:-0}"
MIN_FREE_GB="${PV_MIN_FREE_GB:-3}"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "== $*" >&2; }
need_root() { [ "$(id -u)" = 0 ] || die "ejecútalo con sudo"; }

# Seguridad de la copia en ejecución: la de root en /opt, no la del checkout.
guard_install_dir() {
    [ "${PV_SKIP_GUARD:-0}" = 1 ] && return 0
    local self; self="$(readlink -f "${BASH_SOURCE[0]}")"
    case "$self" in
        "$INSTALL_DIR"/*) ;;
        *) die "ejecútalo desde $INSTALL_DIR (copia de root), no desde el checkout. Instálalo con: sudo deploy/purgito-vault.sh install" ;;
    esac
    [ "$(stat -c %U "$self")" = root ] && [ -z "$(find "$self" -perm /022 2>/dev/null)" ] \
        || die "$self no es de root o es escribible por otros"
}

is_open()    { [ -e "/dev/mapper/$MAPPER" ]; }
is_mounted() { is_mp "$MNT"; }
# `mountpoint` no sirve con archivos (binds de un .env): findmnt sí.
is_mp()      { findmnt -rn --mountpoint "$1" >/dev/null 2>&1; }

split_bind() { # "sub:dst[:file]" -> BSUB BDST BKIND
    BSUB="${1%%:*}"; local rest="${1#*:}"; BDST="${rest%%:*}"
    if [[ "$rest" == *:file ]]; then BKIND=file; else BKIND=dir; fi
}

mount_vault() {
    is_open || die "el volumen no está abierto"
    mkdir -p "$MNT"
    is_mounted || mount "/dev/mapper/$MAPPER" "$MNT"
}

mount_binds() {
    local b
    for b in "${BINDS[@]}"; do
        split_bind "$b"
        local src="$MNT/$BSUB"
        is_mp "$BDST" && continue
        if [ "$BKIND" = file ]; then
            [ -f "$src/$(basename "$BDST")" ] || die "falta $src/$(basename "$BDST") en el volumen"
            [ -e "$BDST" ] || : > "$BDST"
            mount --bind "$src/$(basename "$BDST")" "$BDST"
        else
            [ -d "$src" ] || die "falta $src en el volumen"
            mkdir -p "$BDST"
            mount --bind "$src" "$BDST"
        fi
    done
}

umount_binds() {
    local i b
    for ((i=${#BINDS[@]}-1; i>=0; i--)); do
        b="${BINDS[$i]}"; split_bind "$b"
        if is_mp "$BDST"; then umount "$BDST" || die "no se pudo desmontar $BDST (¿en uso?)"; fi
    done
}

start_services() {
    local s
    [ "$SKIP_UNITS" = 1 ] && return 0
    for s in "${SERVICES[@]}"; do systemctl start "$s"; done
}

stop_services() {
    local i
    [ "$SKIP_UNITS" = 1 ] && return 0
    for ((i=${#SERVICES[@]}-1; i>=0; i--)); do systemctl stop "${SERVICES[$i]}" || true; done
}

# ── install ────────────────────────────────────────────────────────────────────────────────────
cmd_install() {
    need_root
    local here; here="$(readlink -f "${BASH_SOURCE[0]}")"
    mkdir -p "$INSTALL_DIR"; chown root:root "$INSTALL_DIR"; chmod 0755 "$INSTALL_DIR"
    install -m 0755 -o root -g root "$here" "$INSTALL_DIR/purgito-vault"
    ln -sfn "$INSTALL_DIR/purgito-vault" /usr/local/sbin/purgito-vault
    cmp -s "$here" "$INSTALL_DIR/purgito-vault" || die "la copia instalada no coincide byte a byte"
    say "instalado en $INSTALL_DIR/purgito-vault (y enlace /usr/local/sbin/purgito-vault)"
}

# ── bootstrap: crea el contenedor (aditivo, no toca nada existente) ─────────────────────────────
cmd_bootstrap() {
    need_root; guard_install_dir
    command -v cryptsetup >/dev/null || die "falta cryptsetup"
    mkdir -p "$(dirname "$IMG")" "$STATE"; chmod 0700 "$(dirname "$IMG")" "$STATE"
    if [ -e "$IMG" ]; then
        say "ya existe $IMG: no se vuelve a formatear"
    else
        local avail need; avail=$(df -B1 --output=avail "$(dirname "$IMG")" | tail -1)
        need=$(numfmt --from=iec "$SIZE")
        [ "$avail" -gt $((need + MIN_FREE_GB*1024*1024*1024)) ] || die "espacio insuficiente: se necesitan $SIZE más $MIN_FREE_GB GiB libres"
        say "reservando $SIZE en $IMG"
        fallocate -l "$SIZE" "$IMG"; chmod 0600 "$IMG"
        # Clave PROVISIONAL, solo para poder migrar sin tu contraseña. Se elimina en `enroll`.
        if [ ! -e "$KEYFILE" ]; then head -c 64 /dev/urandom > "$KEYFILE"; chmod 0400 "$KEYFILE"; fi
        say "formateando LUKS2 (aes-xts, argon2id 256 MiB: la VM tiene poca RAM)"
        cryptsetup luksFormat --type luks2 --cipher aes-xts-plain64 --key-size 512 --hash sha256 \
            --pbkdf argon2id --pbkdf-memory 262144 --pbkdf-parallel 1 --iter-time 2000 \
            --batch-mode --key-file "$KEYFILE" "$IMG"
        echo 0 > "$STATE/interim-keyslot"
    fi
    if ! is_open; then
        [ -e "$KEYFILE" ] || die "el volumen ya existe pero está cerrado y no hay clave provisional: usa 'open'"
        cryptsetup open --key-file "$KEYFILE" "$IMG" "$MAPPER"
    fi
    if ! blkid "/dev/mapper/$MAPPER" >/dev/null 2>&1; then
        say "creando ext4"
        mkfs.ext4 -q -L purgito-vault "/dev/mapper/$MAPPER"
    fi
    mount_vault
    local b
    for b in "${BINDS[@]}"; do
        split_bind "$b"
        if [ "$BKIND" = file ]; then mkdir -p "$MNT/$BSUB"; chmod 0700 "$MNT/$BSUB"; else mkdir -p "$MNT/$BSUB"; fi
    done
    mkdir -p "$MNT/tmp"; chmod 1777 "$MNT/tmp"
    say "volumen listo en $MNT"
}

# ── sync: copia (rsync) lo existente al volumen ─────────────────────────────────────────────────
cmd_sync() {
    need_root; guard_install_dir; mount_vault
    local b src
    for b in "${BINDS[@]}"; do
        split_bind "$b"
        # Si ya está superpuesto, la fuente real es la capa de abajo: no se vuelve a sincronizar.
        if is_mp "$BDST"; then say "$BDST ya está en el volumen"; continue; fi
        src="$BDST"
        if [ "$BKIND" = file ]; then
            [ -f "$src" ] || { say "no existe $src (se omite)"; continue; }
            install -m "$(stat -c %a "$src")" -o "$(stat -c %U "$src")" -g "$(stat -c %G "$src")" "$src" "$MNT/$BSUB/$(basename "$src")"
        else
            [ -d "$src" ] || { say "no existe $src (se omite)"; continue; }
            rsync -aHAX --numeric-ids --delete "$src/" "$MNT/$BSUB/"
        fi
        say "copiado $src -> $MNT/$BSUB"
    done
}

# ── units: servicios condicionados al volumen, no reiniciar en bucle si la guardia lo rechaza ───
cmd_units() {
    need_root; guard_install_dir
    [ "$SKIP_UNITS" = 1 ] && { say "(unidades omitidas)"; return 0; }
    local u d
    for u in postgresql@18-main.service postgresql.service bot-purg.service studio-purg.service cloudflared.service purgito-backup.service purgito-ledger.service; do
        systemctl cat "$u" >/dev/null 2>&1 || { say "no existe $u (se omite)"; continue; }
        d="/etc/systemd/system/$u.d"; mkdir -p "$d"
        cat > "$d/10-purgito-vault.conf" <<EOF
# Gestionado por purgito-vault: sin el volumen cifrado abierto este servicio NO arranca (ni falla).
[Unit]
ConditionPathIsMountPoint=$MNT
EOF
    done
    mkdir -p /etc/systemd/system/bot-purg.service.d
    cat > /etc/systemd/system/bot-purg.service.d/20-purgito-privacy.conf <<EOF
# Gestionado por purgito-vault.
# 78 = la guardia de privacidad rechazó el arranque (base restaurada sin reconciliar): no reintentar.
# (Los temporales del bot van a /tmp, que es tmpfs: RAM, no disco.)
[Service]
RestartPreventExitStatus=78
EOF
    mkdir -p /etc/systemd/journald.conf.d
    cat > /etc/systemd/journald.conf.d/zz-purgito-volatile.conf <<'EOF'
# Gestionado por purgito-vault: los logs del sistema llevan ids de Discord y no pueden quedar en un
# disco sin cifrar; se guardan solo en RAM (se pierden al reiniciar).
[Journal]
Storage=volatile
RuntimeMaxUse=64M
# rsyslog copia el journal a /var/log/syslog (en la raíz, sin cifrar): se corta el reenvío.
ForwardToSyslog=no
EOF
    systemctl daemon-reload
    systemctl restart systemd-journald
    say "unidades y journald (volátil) configurados"
}

# ── swap cifrado con clave aleatoria por arranque (no depende del volumen) ──────────────────────
cmd_swap_encrypt() {
    need_root; guard_install_dir
    [ -f "$SWAPFILE" ] || die "no existe $SWAPFILE"
    local mem_avail; mem_avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
    local swap_used; swap_used=$(swapon --noheadings --bytes --show=NAME,USED | awk -v f="$SWAPFILE" '$1==f{print int($2/1048576)}')
    swap_used="${swap_used:-0}"
    [ "$mem_avail" -gt $((swap_used + 200)) ] || die "RAM disponible (${mem_avail} MiB) insuficiente para vaciar el swap (${swap_used} MiB): para antes los servicios"
    local size; size=$(stat -c %s "$SWAPFILE")
    swapoff "$SWAPFILE" 2>/dev/null || true
    say "sobrescribiendo con ceros el swap en claro ($((size/1048576)) MiB)"
    dd if=/dev/zero of="$SWAPFILE" bs=1M count=$((size/1048576)) conv=notrunc status=none
    cat > /etc/systemd/system/purgito-cryptswap.service <<EOF
# Gestionado por purgito-vault: swap cifrado con una clave aleatoria nueva en cada arranque.
[Unit]
Description=Swap cifrado (clave aleatoria por arranque)
DefaultDependencies=no
Before=swap.target
After=systemd-modules-load.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/cryptsetup open --type plain --cipher aes-xts-plain64 --key-size 512 --key-file /dev/urandom $SWAPFILE purgito-cryptswap
ExecStart=/sbin/mkswap -q /dev/mapper/purgito-cryptswap
ExecStart=/sbin/swapon /dev/mapper/purgito-cryptswap
ExecStop=/sbin/swapoff /dev/mapper/purgito-cryptswap
ExecStop=/sbin/cryptsetup close purgito-cryptswap

[Install]
WantedBy=swap.target
EOF
    systemctl daemon-reload
    # Quitar el swap en claro de fstab (queda comentado, no borrado).
    if grep -qE "^[^#]*[[:space:]]swap[[:space:]]" /etc/fstab; then
        cp -a /etc/fstab "$STATE/fstab.pre-cryptswap"
        sed -i -E 's|^([^#].*[[:space:]]swap[[:space:]].*)$|# purgito-vault: swap en claro desactivado, ver purgito-cryptswap.service\n# \1|' /etc/fstab
    fi
    systemctl enable --now purgito-cryptswap.service
    swapon --show
    say "swap cifrado activo"
}

# ── migrate: orquesta la migración (el contenido original queda debajo, intacto) ────────────────
cmd_migrate() {
    need_root; guard_install_dir
    [ "${1:-}" = "--yes" ] || die "migrate para PostgreSQL, el bot, Studio y el túnel unos minutos. Repite con --yes"
    is_open && is_mounted || die "el volumen debe estar abierto y montado (bootstrap)"
    say "1/5 parando servicios"; stop_services
    say "2/5 copia final al volumen"; cmd_sync
    say "3/5 montando el volumen sobre las rutas originales"; mount_binds
    say "4/5 comprobando que lo copiado es idéntico"
    local b
    for b in "${BINDS[@]}"; do
        split_bind "$b"
        [ "$BKIND" = dir ] || continue
        # Con el bind puesto, `/` ve el volumen; la capa original se compara montando la raíz aparte.
        local under; under="$(mktemp -d)"; mount --bind / "$under"
        if [ -d "$under$BDST" ] && [ -n "$(ls -A "$under$BDST" 2>/dev/null)" ]; then
            diff -rq "$under$BDST" "$BDST" >/dev/null 2>&1 || { umount "$under"; rmdir "$under"; die "difiere: $BDST"; }
        fi
        umount "$under"; rmdir "$under"
    done
    say "5/5 unidades y arranque"; cmd_units; start_services
    say "migración terminada. Lo original sigue debajo, en claro, hasta 'wipe-plaintext'."
}

# ── open / close ────────────────────────────────────────────────────────────────────────────────
cmd_open() {
    need_root; guard_install_dir
    if ! is_open; then
        if [ "${1:-}" = "--keyfile" ]; then
            [ -e "$KEYFILE" ] || die "no hay clave provisional (ya se hizo 'enroll'): usa la contraseña"
            cryptsetup open --key-file "$KEYFILE" "$IMG" "$MAPPER"
        else
            [ -t 0 ] || die "hace falta una terminal para teclear la contraseña (entra por SSH)"
            echo "Contraseña de DESBLOQUEO del volumen de Purgito (o la de recuperación):" >&2
            cryptsetup open "$IMG" "$MAPPER" || die "contraseña incorrecta o volumen dañado"
        fi
    fi
    mount_vault; mount_binds; start_services
    say "volumen abierto y servicios arrancados"
}

cmd_close() {
    need_root; guard_install_dir
    stop_services; umount_binds
    is_mounted && umount "$MNT"
    is_open && cryptsetup close "$MAPPER"
    say "volumen cerrado: PostgreSQL, bot, Studio y túnel detenidos"
}

# ── status ─────────────────────────────────────────────────────────────────────────────────────
cmd_status() {
    need_root
    echo "imagen:        $( [ -e "$IMG" ] && echo "$IMG ($(du -h --apparent-size "$IMG" | cut -f1))" || echo "NO existe" )"
    echo "abierto:       $(is_open && echo sí || echo no)    montado: $(is_mounted && echo sí || echo no)"
    if [ -e "$IMG" ]; then
        local slots; slots=$(cryptsetup luksDump "$IMG" 2>/dev/null | awk '/^Keyslots:/{f=1;next} /^[A-Z]/{f=0} f&&/^ *[0-9]+: luks2/{n++} END{print n+0}')
        echo "ranuras LUKS:  $slots"
        [ -e "$KEYFILE" ] && echo "CLAVE PROVISIONAL: presente en $KEYFILE (falta 'enroll')" || echo "clave provisional: eliminada"
    fi
    local b
    for b in "${BINDS[@]}"; do split_bind "$b"; printf '  %-40s %s\n' "$BDST" "$(is_mp "$BDST" && echo "en el volumen" || echo "EN CLARO (sin superponer)")"; done
}

# ── enroll: contraseñas del titular, sin clave provisional, encabezado respaldado ───────────────
cmd_enroll() {
    need_root; guard_install_dir
    die "'enroll' esta deshabilitado: el volumen v2 (LUKS2 directo sobre particion) se configura por fases con cryptsetup (ver docs/CIFRADO_EN_REPOSO.md)"
    [ -t 0 ] || die "hace falta una terminal interactiva (entra por SSH; NO lo ejecutes desde un asistente)"
    [ -e "$KEYFILE" ] || die "no hay clave provisional: ya se hizo 'enroll'"
    is_open && is_mounted || die "abre antes el volumen: purgito-vault open --keyfile"
    local slot; slot="$(cat "$STATE/interim-keyslot" 2>/dev/null || echo 0)"
    cat >&2 <<'EOF'

Vas a elegir DOS contraseñas distintas y largas (generadas en tu gestor, p. ej. Proton Pass):
  1) de DESBLOQUEO: la que teclearás tras cada reinicio.
  2) de RECUPERACIÓN: solo para emergencias; guárdala además OFFLINE (papel en lugar seguro).
Nada de esto se escribe en el servidor. Si las pierdes, el volumen y los datos son IRRECUPERABLES
(los respaldos cifrados en R2 siguen funcionando con la clave age, que es independiente).
EOF
    echo "--- Contraseña de DESBLOQUEO (te la pedirá dos veces) ---" >&2
    cryptsetup luksAddKey --key-file "$KEYFILE" "$IMG"
    echo "--- Contraseña de RECUPERACIÓN (distinta; dos veces) ---" >&2
    cryptsetup luksAddKey --key-file "$KEYFILE" "$IMG"
    echo "--- Comprobación: teclea la de DESBLOQUEO ---" >&2
    cryptsetup open --test-passphrase "$IMG" || die "no funcionó; no se quitó la clave provisional"
    echo "--- Comprobación: teclea la de RECUPERACIÓN ---" >&2
    cryptsetup open --test-passphrase "$IMG" || die "no funcionó; no se quitó la clave provisional"
    echo "--- Quitar la clave provisional (teclea cualquiera de las dos) ---" >&2
    cryptsetup luksKillSlot "$IMG" "$slot"
    if cryptsetup open --test-passphrase --key-file "$KEYFILE" "$IMG" 2>/dev/null; then
        die "la clave provisional SIGUE abriendo el volumen; no se borra el archivo"
    fi
    shred -u "$KEYFILE"; rm -f "$STATE/interim-keyslot"
    say "clave provisional destruida; el volumen solo abre con tus contraseñas"
    cmd_header_backup
}

# Respaldo del encabezado LUKS DESPUÉS de fijar las ranuras (uno anterior restauraría la clave provisional).
cmd_header_backup() {
    need_root
    [ -r "$BACKUP_ENV" ] || die "no puedo leer $BACKUP_ENV (¿volumen abierto?)"
    local recipient; recipient="$(awk -F= '$1=="BACKUP_AGE_RECIPIENTS"{print $2}' "$BACKUP_ENV")"
    [[ "$recipient" =~ ^age1[a-z0-9]{50,}$ ]] || die "BACKUP_AGE_RECIPIENTS no es una clave age válida"
    mkdir -p "$STATE"; chmod 0700 "$STATE"
    local stamp out tmp; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    out="$STATE/luks-header-$stamp.img.age"; tmp="$(mktemp -u /root/.pv-hdr.XXXXXX)"  # -u: cryptsetup exige que el archivo NO exista
    cryptsetup luksHeaderBackup "$IMG" --header-backup-file "$tmp"
    age -r "$recipient" -o "$out" "$tmp"; shred -u "$tmp"
    say "encabezado cifrado con age: $out"
    if [ -x /opt/purgito-backup/scripts/r2_backup.py ] && command -v systemd-run >/dev/null; then
        local stage="/run/purgito-vault-stage"; mkdir -p "$stage"; chmod 0750 "$stage"
        chown root:purgito_backup "$stage" 2>/dev/null || true
        install -m 0640 -o root -g purgito_backup "$out" "$stage/$(basename "$out")"
        if systemd-run --quiet --wait --pipe -p User=purgito_backup -p EnvironmentFile="$BACKUP_ENV" \
            /bin/bash -c '"$PYTHON" -I /opt/purgito-backup/scripts/r2_backup.py upload "$1"' _ "$stage/$(basename "$out")"; then
            say "subido a R2 (gen2/$(basename "$out"))"
        else
            say "AVISO: no se pudo subir a R2; descarga/copia $out por otra vía"
        fi
        rm -rf "$stage"
    fi
}

# Logs viejos en claro (syslog y rotados, volcados de fallos, journal persistente anterior): llevan ids
# de Discord y no dependen de la clave del volumen, así que se pueden sobrescribir en cuanto journald es
# volátil y ya no reenvía a syslog. Nunca en modo ensayo.
cmd_wipe_logs() {
    need_root; guard_install_dir
    [ "$SKIP_UNITS" != 1 ] || { say "(modo ensayo: no se tocan logs del sistema)"; return 0; }
    [ -f /etc/systemd/journald.conf.d/zz-purgito-volatile.conf ] || die "journald aún no es volátil: ejecuta 'units' primero"
    systemctl restart systemd-journald
    if [ -d /var/log/journal ]; then
        find /var/log/journal -type f -exec shred -n 1 -z -u {} + 2>/dev/null || true
        say "journal persistente anterior sobrescrito"
    fi
    if ls /var/log/syslog* >/dev/null 2>&1; then
        local f
        for f in /var/log/syslog*; do shred -n 1 -z "$f" 2>/dev/null || true; done
        rm -f /var/log/syslog.[0-9]*
        : > /var/log/syslog
        systemctl restart rsyslog 2>/dev/null || true
        say "syslog y rotados sobrescritos"
    fi
    if ls /var/crash/* >/dev/null 2>&1; then
        find /var/crash -type f -exec shred -n 1 -z -u {} + 2>/dev/null || true
        say "volcados en /var/crash sobrescritos"
    fi
}

# ── wipe-plaintext: sobrescribe lo que quedó EN CLARO debajo de los montajes ─────────────────────
cmd_wipe() {
    need_root; guard_install_dir
    [ "${1:-}" = "--yes" ] || die "esto sobrescribe y BORRA lo que quedó en claro debajo de los montajes (no afecta al volumen). Repite con --yes"
    [ ! -e "$KEYFILE" ] || die "aún existe la clave provisional: haz primero 'enroll' (y comprueba el desbloqueo)"
    is_open && is_mounted || die "el volumen debe estar abierto"
    local under; under="$(mktemp -d)"; mount --bind / "$under"
    local b n=0
    for b in "${BINDS[@]}"; do
        split_bind "$b"
        is_mp "$BDST" || { say "$BDST no está superpuesto: se omite"; continue; }
        if [ "$BKIND" = file ]; then
            if [ -f "$under$BDST" ]; then
                # Es punto de montaje: no se puede renombrar ni borrar (EBUSY); se sobrescribe en el sitio.
                shred -n 1 -z "$under$BDST"; : > "$under$BDST"; n=$((n+1))
            fi
        elif [ -d "$under$BDST" ]; then
            find "$under$BDST" -xdev -type f -exec shred -n 1 -z -u {} + 2>/dev/null || true
            find "$under$BDST" -xdev -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true
            n=$((n+1))
        fi
        say "sobrescrito el contenido en claro de $BDST"
    done
    umount "$under"; rmdir "$under"
    cmd_wipe_logs
    if [ -f "$SWAPFILE" ] && ! swapon --noheadings --show=NAME | grep -qx "$SWAPFILE"; then
        say "el swap en claro ya está sobrescrito con ceros (swap-encrypt)"
    fi
    say "listo ($n rutas). Comprueba con: deploy/check_encryption_at_rest.sh"
}

case "${1:-}" in
    install)        shift; cmd_install "$@" ;;
    bootstrap)      shift; cmd_bootstrap "$@" ;;
    sync)           shift; cmd_sync "$@" ;;
    units)          shift; cmd_units "$@" ;;
    swap-encrypt)   shift; cmd_swap_encrypt "$@" ;;
    migrate)        shift; cmd_migrate "$@" ;;
    open)           shift; cmd_open "$@" ;;
    close)          shift; cmd_close "$@" ;;
    status)         shift; cmd_status "$@" ;;
    enroll)         shift; cmd_enroll "$@" ;;
    header-backup)  shift; cmd_header_backup "$@" ;;
    wipe-logs)      shift; cmd_wipe_logs "$@" ;;
    wipe-plaintext) shift; cmd_wipe "$@" ;;
    *) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
