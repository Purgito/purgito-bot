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
#   sudo purgito-vault status             # estado y avance de la inscripción, sin cambiar nada
#   sudo purgito-vault open               # tras un reinicio: pide la contraseña, monta, arranca servicios
#   sudo purgito-vault close              # para servicios, desmonta y cierra el volumen
#
# Inscripción de TUS contraseñas (en fases; nada destructivo hasta `enroll retire`):
#   sudo purgito-vault enroll add         # 1) añade las contraseñas de desbloqueo y recuperación
#   sudo purgito-vault enroll verify      # 2) comprueba CADA una por separado, sin cerrar el volumen
#   sudo purgito-vault age-canary         # 3) prueba de acceso real a tu clave privada age (con tu PC)
#   sudo purgito-vault age-verify
#   sudo purgito-vault enroll retire --yes   # 4) respalda, retira la clave provisional, re-comprueba y
#                                            #    sube el respaldo DEFINITIVO del encabezado
#   sudo purgito-vault tang-bind          # 5) desbloqueo AUTOMÁTICO tras reinicios (Tang en el host); solo añade una ranura
#   sudo purgito-vault watchdog on        # 6) un congelamiento total reinicia la VM sola
#   sudo purgito-vault drill --yes        # 7) ensayo: cierra y reabre el volumen (web caída ~2 min)
#   sudo purgito-vault verify-recovery    # 8) lista de comprobaciones de recuperación (marca el resultado)
#
# Borrado de las copias en claro (IRREVERSIBLE; exige verify-recovery y enroll retire hechos):
#   sudo purgito-vault wipe-plaintext --plan   # qué borraría exactamente, sin tocar nada
#   sudo purgito-vault wipe-plaintext --yes
#
#   sudo purgito-vault grow +2G           # amplía el contenedor en línea (no destructivo)
#
# Preparación (la hace quien despliega, ver docs/CIFRADO_EN_REPOSO.md): install, bootstrap, migrate,
# swap-encrypt, units.
#
# Se ejecuta SOLO desde la copia de root en /opt/purgito-vault (el checkout del bot es escribible por
# el usuario del bot: alguien con acceso a ese usuario podría sustituir el script para capturar lo que
# teclees). Las contraseñas las pide cryptsetup directamente en tu terminal: no pasan por argumentos,
# variables, archivos ni logs de este script.
set -euo pipefail
umask 077

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
read -r -a SERVICES <<< "${PV_SERVICES-purgito-log-tee postgresql@18-main bot-purg studio-purg cloudflared}"
# subcarpeta-del-volumen:ruta-original[:file]
read -r -a BINDS <<< "${PV_BINDS-postgresql:/var/lib/postgresql pglog:/var/log/postgresql backups:/var/backups/purgito botdata:/home/purgito/purgito-bot/data legacy-backups:/home/purgito/purgito-bot-backups etc-purgito:/etc/purgito cloudflared:/etc/cloudflared botenv:/home/purgito/purgito-bot/.env:file}"
SKIP_UNITS="${PV_SKIP_UNITS:-0}"
ENR="$STATE/enroll"   # marcas de la inscripción (sin secretos)
MIN_FREE_GB="${PV_MIN_FREE_GB:-3}"

UNDER=""
cleanup() { if [ -n "$UNDER" ]; then umount "$UNDER" 2>/dev/null || true; rmdir "$UNDER" 2>/dev/null || true; fi; }
trap cleanup EXIT
die() { echo "ERROR: $*" >&2; exit 1; }
# Fallo "blando": en modo SOFT=1 devuelve el control (para poder revertir); si no, sale como die.
vfail() { echo "ERROR: $*" >&2; [ "${SOFT:-0}" = 1 ] || exit 1; }
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
    # Aviso de "volumen bloqueado": un mensaje de prioridad `crit` al journal cada 15 min mientras siga
    # cerrado. El agente de monitoreo existente ya convierte las entradas crit en eventos críticos: no se
    # crea ningún canal de alertas nuevo. Se omite solo (sin fallar) cuando el volumen está abierto.
    cat > /etc/systemd/system/purgito-vault-locked.service <<EOF
# Gestionado por purgito-vault.
[Unit]
Description=Aviso: el volumen cifrado de Purgito esta bloqueado
ConditionPathIsMountPoint=!$MNT
After=umbrel-monitor-agent.service

[Service]
Type=oneshot
ExecStart=/usr/bin/systemd-cat -t purgito-vault -p crit /bin/echo "PURGITO: el volumen cifrado esta BLOQUEADO (reinicio?): base de datos, bot y web caidos hasta desbloquear. Entra por SSH y ejecuta: sudo purgito-vault open"
EOF
    cat > /etc/systemd/system/purgito-vault-locked.timer <<'EOF'
# Gestionado por purgito-vault: recuerda cada 15 min que falta desbloquear (no hace nada si ya esta abierto).
[Unit]
Description=Recordatorio periodico: volumen cifrado de Purgito bloqueado

[Timer]
OnBootSec=3min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
EOF
    # Diagnóstico persistente y PROTEGIDO: copia el journal (kernel y servicios) a un archivo DENTRO del volumen
    # cifrado, con rotación diaria y 14 días de retención. Si la VM se congela, las últimas líneas ya están en
    # disco y se leen tras desbloquear. El journal sigue siendo volátil y sin reenvío: fuera del volumen no se
    # escribe nada. No incluye el contenido de los mensajes (el bot solo registra eventos).
    cat > /usr/local/sbin/purgito-log-tee <<'EOT'
#!/bin/sh
# Gestionado por purgito-vault. Copia el journal al volumen cifrado (solo corre con el volumen montado).
set -eu
MNT="${1:-/srv/purgito}"; D="$MNT/logs"; umask 077; mkdir -p "$D"
B=$(cat /proc/sys/kernel/random/boot_id); M="$D/.boot"
if [ "$(cat "$M" 2>/dev/null || true)" = "$B" ]; then A="--since=-30s"; else A="-b -n all"; echo "$B" > "$M"; fi
# shellcheck disable=SC2086
exec journalctl $A -f -o short-iso >> "$D/journal.log"
EOT
    chmod 0755 /usr/local/sbin/purgito-log-tee; chown root:root /usr/local/sbin/purgito-log-tee
    cat > /etc/systemd/system/purgito-log-tee.service <<EOF
# Gestionado por purgito-vault.
[Unit]
Description=Diagnostico: copia del journal al volumen cifrado (retencion 14 dias)
ConditionPathIsMountPoint=$MNT

[Service]
Type=simple
ExecStart=/usr/local/sbin/purgito-log-tee $MNT
Restart=on-failure
RestartSec=5
Nice=10
EOF
    cat > /etc/logrotate.d/purgito-journal <<EOF
# Gestionado por purgito-vault: retención limitada del diagnóstico (dentro del volumen cifrado).
$MNT/logs/journal.log {
    daily
    rotate 14
    maxsize 100M
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su root root
}
EOF
    mkdir -p /etc/systemd/system/sysstat-collect.timer.d
    cat > /etc/systemd/system/sysstat-collect.timer.d/10-purgito-1min.conf <<'EOF'
# Gestionado por purgito-vault: muestras de CPU/memoria/disco cada minuto (solo números, sin datos privados).
[Timer]
OnCalendar=
OnCalendar=*:*:00
EOF
    systemctl daemon-reload
    systemctl enable --now purgito-vault-locked.timer >/dev/null 2>&1 || true
    systemctl restart systemd-journald
    say "unidades, aviso de bloqueo y journald (volátil) configurados"
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
        if [ "${1:-}" = "--auto" ]; then
            marked tang-bound || die "el desbloqueo automático no está activado (purgito-vault tang-bind)"
            local i; for i in $(seq 1 60); do
                timeout 25 clevis luks unlock -d "$IMG" -n "$MAPPER" >/dev/null 2>&1 && break
                [ "$i" = 1 ] && say "esperando al servidor Tang del host..."
                sleep 15
            done
            is_open || die "Tang no respondió en ~15 min: desbloquea a mano con la contraseña (purgito-vault open)"
            mark auto-open-ok; mark drill-ok
        elif [ "${1:-}" = "--keyfile" ]; then
            [ -e "$KEYFILE" ] || die "no hay clave provisional (ya se hizo 'enroll'): usa la contraseña"
            cryptsetup open --key-file "$KEYFILE" "$IMG" "$MAPPER"
        else
            [ -t 0 ] || die "hace falta una terminal para teclear la contraseña (entra por SSH)"
            echo "Contraseña de DESBLOQUEO del volumen de Purgito (o la de recuperación):" >&2
            cryptsetup open "$IMG" "$MAPPER" || die "contraseña incorrecta o volumen dañado"
            mark drill-ok   # desbloqueo real con contraseña tecleada: cuenta como ensayo de recuperación
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
    if is_mounted; then
        local pct; pct=$(df --output=pcent "$MNT" | tail -1 | tr -dc 0-9)
        echo "uso:           $(df -h --output=used,size,pcent "$MNT" | tail -1 | xargs)   $( [ "$pct" -ge 75 ] && echo "<- AMPLIAR: purgito-vault grow +2G" )"
    fi
    if [ -e "$IMG" ]; then
        echo "ranuras LUKS:  $(slots_list "$IMG" | wc -l)  ($(slots_list "$IMG" | tr '\n' ' '))"
        [ -e "$KEYFILE" ] && echo "CLAVE PROVISIONAL: presente (ranura $(cat "$STATE/interim-keyslot" 2>/dev/null || echo ?)); falta 'enroll retire'" || echo "clave provisional: retirada"
    fi
    echo "inscripción:   añadidas: $(marked slot-unlock && echo desbloqueo) $(marked slot-recovery && echo recuperación) | comprobadas: $(marked verified-unlock && echo desbloqueo) $(marked verified-recovery && echo recuperación) | clave age: $(marked age-verified && echo ok || echo pendiente) | retirada: $(marked retired && echo sí || echo no) | ensayo de apertura: $(marked drill-ok && echo sí || echo pendiente) | recuperación verificada: $(marked recovery-verified && echo sí || echo no)"
    echo "desbloqueo auto: $(marked tang-bound && echo "Tang (ranura $(tang_slot)); último arranque automático: $(cat "$ENR/auto-open-ok" 2>/dev/null || echo nunca)" || echo "no activado (manual con contraseña)")   | watchdog: $([ -e /etc/systemd/system.conf.d/10-purgito-watchdog.conf ] && echo activo || echo no)   | diagnóstico: $(systemctl is-active purgito-log-tee 2>/dev/null || true)"
    local b
    for b in "${BINDS[@]}"; do split_bind "$b"; printf '  %-40s %s\n' "$BDST" "$(is_mp "$BDST" && echo "en el volumen" || echo "EN CLARO (sin superponer)")"; done
}

# ── inscripción de contraseñas, en fases ────────────────────────────────────────────────────────
slots_list() { cryptsetup luksDump "$1" 2>/dev/null | awk '/^Keyslots:/{f=1;next} /^[A-Z]/{f=0} f&&/^ *[0-9]+: luks2/{gsub(":","",$1);print $1}'; }
mark()   { mkdir -p "$ENR"; chmod 0700 "$ENR"; date -u +%FT%TZ > "$ENR/$1"; }
marked() { [ -e "$ENR/$1" ]; }
slot_of(){ cat "$ENR/slot-$1" 2>/dev/null; }
tang_slot() { cat "$ENR/slot-tang" 2>/dev/null || true; }
# Ranuras "de contraseña" (sin la de Tang): lo que comprueban enroll, verify-recovery y wipe-plaintext.
core_slots() { local t; t="$(tang_slot)"; slots_list "$IMG" | sort | { if [ -n "$t" ]; then grep -vx "$t" || true; else cat; fi; } | tr '\n' ' '; }
# Ensayo (sandbox): contraseñas simuladas con archivos. SOLO con PV_SKIP_GUARD=1; nunca en producción.
rh()     { [ "${PV_SKIP_GUARD:-0}" = 1 ] && [ -n "${PV_REHEARSAL_KEYS:-}" ]; }
need_tty() { rh || [ -t 0 ] || die "hace falta una terminal interactiva (entra por SSH; NO lo ejecutes desde un asistente)"; }

luks_add_role() { # rol
    if rh; then cryptsetup luksAddKey --key-file "$KEYFILE" --new-keyfile "$PV_REHEARSAL_KEYS/$1.key" "$IMG"
    else cryptsetup luksAddKey --key-file "$KEYFILE" "$IMG"; fi
}
luks_test_slot() { # rol ranura  (la contraseña tiene que abrir ESA ranura)
    if rh; then cryptsetup open --test-passphrase --key-slot "$2" --key-file "$PV_REHEARSAL_KEYS/$1.key" "$IMG"
    else cryptsetup open --test-passphrase --key-slot "$2" "$IMG"; fi
}
luks_kill_slot() { # ranura
    if rh; then cryptsetup luksKillSlot --key-file "$PV_REHEARSAL_KEYS/unlock.key" "$IMG" "$1"
    else cryptsetup luksKillSlot "$IMG" "$1"; fi
}

enroll_add() {
    [ -e "$KEYFILE" ] || die "ya no hay clave provisional: la inscripción terminó"
    is_open && is_mounted || die "abre antes el volumen: purgito-vault open --keyfile"
    local roles=("$@"); [ ${#roles[@]} -gt 0 ] || roles=(unlock recovery)
    cat >&2 <<'EOF'

Elige DOS contraseñas DISTINTAS y largas (generadas en tu gestor, p. ej. Proton Pass):
  unlock   = la que teclearás tras cada reinicio.
  recovery = solo para emergencias; guárdala además OFFLINE (papel en lugar seguro).
Esta fase SOLO AÑADE: la clave provisional sigue funcionando y no se borra nada.
EOF
    local r before after new
    for r in "${roles[@]}"; do
        [[ "$r" == unlock || "$r" == recovery ]] || die "rol desconocido: $r (unlock | recovery)"
        if marked "slot-$r"; then say "$r ya estaba añadida (ranura $(slot_of "$r"))"; continue; fi
        before="$(slots_list "$IMG" | sort)"
        echo "--- Contraseña de $r (te la pedirá dos veces) ---" >&2
        luks_add_role "$r"
        after="$(slots_list "$IMG" | sort)"
        new="$(comm -13 <(echo "$before") <(echo "$after"))"
        [ "$(echo "$new" | wc -w)" = 1 ] || die "no pude identificar la ranura nueva (antes: $before | después: $after)"
        echo "$new" > "$ENR/slot-$r" 2>/dev/null || { mkdir -p "$ENR"; echo "$new" > "$ENR/slot-$r"; }
        rm -f "$ENR/verified-$r" "$ENR/age-verified"
        say "$r añadida en la ranura $new"
    done
    say "siguiente: sudo purgito-vault enroll verify"
}

enroll_verify() {
    is_open && is_mounted || die "el volumen debe estar abierto (se comprueba SIN cerrarlo)"
    local roles=("$@"); [ ${#roles[@]} -gt 0 ] || roles=(unlock recovery)
    local r slot other
    for r in "${roles[@]}"; do
        marked "slot-$r" || { vfail "falta añadir la contraseña de $r (enroll add $r)"; return 1; }
        slot="$(slot_of "$r")"
        echo "--- Teclea la contraseña de $r: debe abrir la ranura $slot ---" >&2
        luks_test_slot "$r" "$slot" || { vfail "esa contraseña NO abre la ranura $slot. No se cambió nada."; return 1; }
        if [ "$r" = recovery ]; then
            other="$(slot_of unlock)"
            echo "--- Comprobación cruzada: teclea OTRA VEZ la de recuperación; NO debe abrir la ranura de desbloqueo ($other) ---" >&2
            if luks_test_slot recovery "$other" 2>/dev/null; then
                vfail "la contraseña de recuperación abre también la de desbloqueo: son IGUALES. Elige otra (quita la ranura $slot y repite)."; return 1
            fi
        fi
        core_slots > "$ENR/verified-$r.tmp"; mv "$ENR/verified-$r.tmp" "$ENR/verified-$r"
        say "contraseña de $r comprobada (ranura $slot); el volumen sigue abierto"
    done
}

# ── prueba de acceso real a la clave privada age, sin que la clave toque el servidor ─────────────
age_recipient() {
    local r; r="$(awk -F= '$1=="BACKUP_AGE_RECIPIENTS"{print $2}' "$BACKUP_ENV")"
    [[ "$r" =~ ^age1[a-z0-9]{50,}$ ]] || die "BACKUP_AGE_RECIPIENTS no es una clave age válida en $BACKUP_ENV"
    echo "$r"
}

cmd_age_canary() {
    need_root; guard_install_dir; mkdir -p "$ENR"; chmod 0700 "$ENR"
    local rcp token out home dest; rcp="$(age_recipient)"
    token="$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    out="$STATE/age-canary.age"
    printf 'purgito-age-canary:%s\n' "$token" | age -r "$rcp" -o "$out"
    echo "$token" > "$ENR/age-token"; rm -f "$ENR/age-verified"
    dest="$out"
    if [ -n "${SUDO_USER:-}" ] && ! rh; then
        home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
        install -m 0644 -o "$SUDO_USER" -g "$(id -gn "$SUDO_USER")" "$out" "$home/purgito-age-canary.age"; dest="$home/purgito-age-canary.age"
    fi
    cat >&2 <<EOF

Archivo de prueba creado: $dest  (cifrado con tu clave PÚBLICA; no contiene nada secreto)
En TU PC, con tu clave PRIVADA age (la de Proton Pass / copia offline):
    scp ${SUDO_USER:-usuario}@<la-vm>:purgito-age-canary.age .
    age -d -i TU-CLAVE-PRIVADA.txt purgito-age-canary.age
Debe imprimir:  purgito-age-canary:<24 caracteres>.   Copia esos 24 caracteres y ejecuta:
    sudo purgito-vault age-verify
(La clave privada NO se copia al servidor en ningún momento.)
EOF
}

cmd_age_verify() {
    need_root; guard_install_dir
    marked age-token 2>/dev/null || [ -e "$ENR/age-token" ] || die "primero: purgito-vault age-canary"
    local got want; want="$(cat "$ENR/age-token")"
    if rh; then got="${PV_REHEARSAL_AGE_TOKEN:-}"; else read -r -p "Valor descifrado (24 caracteres): " got; fi
    [ "$got" = "$want" ] || die "no coincide: no se acredita el acceso a la clave privada age"
    mark age-verified; shred -u "$ENR/age-token" 2>/dev/null || rm -f "$ENR/age-token"
    [ -n "${SUDO_USER:-}" ] && rm -f "$(getent passwd "$SUDO_USER" | cut -d: -f6)/purgito-age-canary.age"
    say "acceso a la clave privada age acreditado"
}

# ── respaldo del encabezado LUKS ────────────────────────────────────────────────────────────────
# header_make DESTINO_RAW: copia el encabezado actual y comprueba que es un encabezado LUKS2 válido.
header_make() {
    cryptsetup luksHeaderBackup "$IMG" --header-backup-file "$1"
    cryptsetup luksDump "$1" >/dev/null 2>&1 || die "el respaldo del encabezado no es un LUKS válido"
}

# header_seal RAW ETIQUETA [--upload]: cifra con age (+ lista de ranuras al lado) y sube a R2 si se pide.
header_seal() {
    local raw="$1" tag="$2" upload="${3:-}" rcp stamp out
    rcp="$(age_recipient)"; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    out="$STATE/luks-header-$tag-$stamp.img.age"
    age -r "$rcp" -o "$out" "$raw"
    [ "$(head -c 21 "$out")" = "age-encryption.org/v1" ] || die "el respaldo cifrado no tiene formato age"
    slots_list "$raw" | sort | tr '\n' ' ' > "$out.slots"
    HDR_OUT="$out"
    say "encabezado ($tag) cifrado con age: $out"
    [ "$upload" = "--upload" ] || return 0
    rh && { say "(ensayo: no se sube a R2)"; return 0; }
    local stage="/run/purgito-vault-stage" base; base="$(basename "$out")"
    mkdir -p "$stage"; chmod 0750 "$stage"; chown root:purgito_backup "$stage" 2>/dev/null || true
    install -m 0640 -o root -g purgito_backup "$out" "$stage/$base"
    if systemd-run --quiet --wait --pipe -p User=purgito_backup -p EnvironmentFile="$BACKUP_ENV" \
        /bin/bash -c '"$PYTHON" -I /opt/purgito-backup/scripts/r2_backup.py upload "$1"' _ "$stage/$base"; then
        rm -rf "$stage"; echo "gen2/$base" > "$ENR/final-header-uploaded"; say "subido a R2 y verificado (gen2/$base)"
    else
        rm -rf "$stage"; die "no se pudo subir el encabezado a R2; la clave provisional NO se destruyó. Reintenta: purgito-vault header-backup"
    fi
}

cmd_header_backup() { # manual, solo tras retirar la provisional
    need_root; guard_install_dir
    [ ! -e "$KEYFILE" ] || marked key-revoked || die "la clave provisional sigue activa: un respaldo ahora la contendría. Termina con 'enroll retire'."
    local raw; raw="$(mktemp)"; header_make "$raw"; header_seal "$raw" final --upload; shred -u "$raw"
}

enroll_retire() {
    [ "${1:-}" = "--yes" ] || {
        cat >&2 <<'EOF'
'enroll retire' hace, en este orden (y se detiene si algo falla, sin destruir lo anterior):
  1. respalda el encabezado ACTUAL (aún con la clave provisional) como red de seguridad local;
  2. retira la clave provisional del volumen (te pedirá una de tus contraseñas);
  3. comprueba que la clave provisional YA NO abre el volumen;
  4. te hace teclear de nuevo ambas contraseñas para confirmar que siguen funcionando;
     (si 3 o 4 fallan, restaura el encabezado del paso 1 y todo queda como estaba);
  5. hace el respaldo DEFINITIVO del encabezado (sin la provisional), lo valida y lo sube a R2;
  6. solo entonces destruye el archivo de la clave provisional y el respaldo previo.
Si el paso 5 falla (p. ej. sin red), repite este mismo comando: reanuda desde el paso 5.
Repite con --yes para ejecutarlo.
EOF
        exit 2
    }
    is_open && is_mounted || die "el volumen debe estar abierto"
    local r su sr cur interim pre="$STATE/prerevoke.hdr"
    su="$(slot_of unlock)"; sr="$(slot_of recovery)"; interim="$(cat "$STATE/interim-keyslot" 2>/dev/null || echo 0)"
    if ! marked key-revoked; then
        for r in slot-unlock slot-recovery verified-unlock verified-recovery age-verified; do marked "$r" || die "falta un paso previo: $r (mira 'purgito-vault status')"; done
        [ -e "$KEYFILE" ] || die "la clave provisional ya no existe"
        cur="$(slots_list "$IMG" | sort | tr '\n' ' ')"
        [ "$cur" = "$(printf '%s\n' "$interim" "$su" "$sr" | sort | tr '\n' ' ')" ] || die "las ranuras no son las esperadas (provisional $interim, desbloqueo $su, recuperación $sr; hay: $cur)"
        for r in unlock recovery; do [ "$(cat "$ENR/verified-$r")" = "$cur" ] || die "la comprobación de $r es anterior a un cambio de ranuras: repite 'enroll verify'"; done

        header_make "$pre"; header_seal "$pre" prerevoke   # solo local
        say "1/6 red de seguridad creada ($pre); se conserva hasta el final"
        echo "--- 2/6 Retirar la clave provisional (ranura $interim): teclea una de tus contraseñas ---" >&2
        luks_kill_slot "$interim" || die "no se retiró nada (contraseña incorrecta); el encabezado no cambió"
        say "3/6 comprobando que la provisional ya no abre"
        if cryptsetup open --test-passphrase --key-file "$KEYFILE" "$IMG" 2>/dev/null; then
            cryptsetup luksHeaderRestore "$IMG" --header-backup-file "$pre" --batch-mode
            die "la provisional SIGUE abriendo: se restauró el encabezado anterior, nada cambió"
        fi
        say "4/6 re-comprobando tus contraseñas con el encabezado nuevo"
        rm -f "$ENR/verified-unlock" "$ENR/verified-recovery"
        if ! SOFT=1 enroll_verify unlock recovery; then
            cryptsetup luksHeaderRestore "$IMG" --header-backup-file "$pre" --batch-mode || true
            die "falló la re-comprobación: se restauró el encabezado anterior (la provisional vuelve a funcionar). Revisa y repite."
        fi
        mark key-revoked
    else
        say "reanudando: la provisional ya estaba revocada y las contraseñas comprobadas"
    fi
    cur="$(slots_list "$IMG" | sort | tr '\n' ' ')"
    [ "$cur" = "$(printf '%s\n' "$su" "$sr" | sort | tr '\n' ' ')" ] || die "tras revocar deberían quedar exactamente las ranuras $su y $sr (hay: $cur)"
    say "5/6 respaldo definitivo del encabezado"
    local final; final="$(mktemp)"; header_make "$final"
    [ "$(slots_list "$final" | sort | tr '\n' ' ')" = "$cur" ] || { shred -u "$final"; die "el respaldo definitivo no tiene exactamente las dos ranuras nuevas"; }
    if [ -e "$KEYFILE" ] && cryptsetup open --test-passphrase --header "$final" --key-file "$KEYFILE" "$IMG" 2>/dev/null; then
        shred -u "$final"; die "el respaldo definitivo AÚN permitiría usar la clave provisional: no se publica"
    fi
    header_seal "$final" final --upload; shred -u "$final"
    say "6/6 destruyendo la clave provisional y el respaldo previo"
    [ -e "$KEYFILE" ] && shred -u "$KEYFILE"
    rm -f "$STATE/interim-keyslot"
    [ -e "$pre" ] && shred -u "$pre"
    find "$STATE" -maxdepth 1 -name 'luks-header-prerevoke-*' -exec shred -u {} + 2>/dev/null || true
    rm -f "$STATE"/luks-header-prerevoke-*.slots
    mark retired
    say "clave provisional retirada. Siguiente: sudo purgito-vault verify-recovery"
}

cmd_enroll() {
    need_root; guard_install_dir
    local sub="${1:-}"; shift || true
    case "$sub" in
        add)    need_tty; enroll_add "$@" ;;
        verify) need_tty; enroll_verify "$@" ;;
        retire) need_tty; enroll_retire "$@" ;;
        *) die "uso: enroll add | enroll verify | enroll retire --yes   (ver 'purgito-vault' sin argumentos)" ;;
    esac
}

# ── desbloqueo automático por red: Clevis + Tang (servidor en el host) ──────────────────────────
# Tang no guarda ninguna clave utilizable: la VM la RECONSTRUYE al arrancar hablando con el servidor del host
# (solo responde a esta VM). Una copia del disco o de la imagen no abre el volumen sin ese servidor, que
# vive en el host y fuera de las copias de Umbrel. La ranura de Tang es ADICIONAL: tus dos contraseñas
# siguen abriendo el volumen aunque Tang no exista.
TANG_URL="${PV_TANG_URL:-http://10.203.0.1:7500}"
TANG_THP_FILE="${PV_TANG_THP_FILE:-$STATE/tang.thp}"

tang_unit_write() {
    [ "$SKIP_UNITS" = 1 ] && return 0
    cat > /etc/systemd/system/purgito-vault-auto.service <<EOF
# Gestionado por purgito-vault (tang-bind). Tras un reinicio abre el volumen pidiendo la clave al servidor Tang
# del host. Si Tang no responde en ~15 min no hace nada: queda el aviso crítico y el desbloqueo manual.
[Unit]
Description=Desbloqueo automatico del volumen cifrado de Purgito (Tang en el host)
Wants=network-online.target
After=network-online.target
ConditionPathIsMountPoint=!$MNT
ConditionPathExists=$ENR/tang-bound

[Service]
Type=oneshot
ExecStart=$INSTALL_DIR/purgito-vault open --auto
TimeoutStartSec=20min

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload; systemctl enable purgito-vault-auto.service >/dev/null 2>&1 || true
}

# Prueba SIN cerrar nada: Tang debe devolver la clave de la ranura y esa clave debe abrir ESA ranura.
tang_check() {
    local slot; slot="$(tang_slot)"; [ -n "$slot" ] || return 1
    timeout 25 clevis luks pass -d "$IMG" -s "$slot" 2>/dev/null | cryptsetup open --test-passphrase --key-slot "$slot" --key-file - "$IMG" 2>/dev/null
}

cmd_tang_test() {
    need_root; guard_install_dir
    marked tang-bound || die "el desbloqueo automático no está activado"
    local t0 t1; t0=$(date +%s%N)
    if tang_check; then t1=$(date +%s%N); say "OK: Tang respondió y la clave abre la ranura $(tang_slot) ($(( (t1-t0)/1000000 )) ms)"
    else die "FALLO: Tang no responde o la clave no abre la ranura (¿contenedor purgito-tang parado en el host?)"; fi
}

cmd_tang_bind() {
    need_root; guard_install_dir; need_tty
    command -v clevis >/dev/null || die "falta clevis (apt install clevis clevis-luks)"
    is_open && is_mounted || die "el volumen debe estar abierto"
    [ ! -e "$KEYFILE" ] && marked retired || die "termina antes la inscripción (enroll retire): con la clave provisional presente no se añade nada"
    ! marked tang-bound || die "ya está enlazado (purgito-vault tang-unbind lo quita)"
    local thp; thp="${PV_TANG_THP:-$(cat "$TANG_THP_FILE" 2>/dev/null || true)}"
    [ -n "$thp" ] || die "falta la huella (thumbprint) de la clave de firma de Tang en $TANG_THP_FILE"
    curl -fsS -m 8 -o /dev/null "$TANG_URL/adv" || die "Tang no responde en $TANG_URL (¿contenedor purgito-tang en el host?)"
    local before after new cfg; cfg="{\"url\":\"$TANG_URL\",\"thp\":\"$thp\"}"
    before="$(slots_list "$IMG" | sort)"
    echo "--- Teclea tu contraseña de DESBLOQUEO para autorizar el enlace con Tang (solo AÑADE una ranura) ---" >&2
    if rh; then clevis luks bind -d "$IMG" -k "$PV_REHEARSAL_KEYS/unlock.key" -y tang "$cfg"; else clevis luks bind -d "$IMG" -y tang "$cfg"; fi
    after="$(slots_list "$IMG" | sort)"; new="$(comm -13 <(echo "$before") <(echo "$after"))"
    [ "$(echo "$new" | wc -w)" = 1 ] || die "no pude identificar la ranura nueva de Tang (antes: $before | después: $after)"
    mkdir -p "$ENR"; echo "$new" > "$ENR/slot-tang"
    if ! tang_check; then
        rm -f "$ENR/slot-tang"
        if rh; then cryptsetup luksKillSlot --key-file "$PV_REHEARSAL_KEYS/unlock.key" "$IMG" "$new"; else echo "--- La comprobación falló: se retira la ranura nueva; teclea tu contraseña de DESBLOQUEO ---" >&2; cryptsetup luksKillSlot "$IMG" "$new"; fi
        die "Tang respondió pero la clave no abre la ranura: se retiró la ranura nueva, nada más cambió"
    fi
    mark tang-bound; tang_unit_write
    say "Tang enlazado (ranura $new) y comprobado. Tus dos contraseñas NO cambiaron."
    local raw; raw="$(mktemp)"; header_make "$raw"; header_seal "$raw" final --upload; shred -u "$raw"
    say "respaldo del encabezado actualizado (incluye la ranura de Tang)"
    say "siguiente: sudo purgito-vault watchdog on   (y luego: sudo purgito-vault drill --yes)"
}

cmd_tang_unbind() {
    need_root; guard_install_dir
    marked tang-bound || die "no hay desbloqueo automático"
    local slot; slot="$(tang_slot)"
    [ "$(core_slots | wc -w)" = 2 ] || die "no se quita la ranura de Tang si no están las dos de contraseña"
    if [ "$SKIP_UNITS" != 1 ]; then systemctl disable purgito-vault-auto.service >/dev/null 2>&1 || true; rm -f /etc/systemd/system/purgito-vault-auto.service; fi
    clevis luks unbind -d "$IMG" -s "$slot" -f || die "no se pudo quitar la ranura $slot"
    rm -f "$ENR/slot-tang" "$ENR/tang-bound"; [ "$SKIP_UNITS" = 1 ] || systemctl daemon-reload
    local raw; raw="$(mktemp)"; header_make "$raw"; header_seal "$raw" final --upload; shred -u "$raw"
    say "desbloqueo automático retirado; el volumen solo abre con contraseña"
}

# ── ensayo de reinicio del volumen (cierra y reabre; la web cae ~2 min) ─────────────────────────
cmd_drill() {
    need_root; guard_install_dir
    marked retired || die "primero 'enroll retire'"
    [ "${1:-}" = "--yes" ] || die "esto CIERRA el volumen unos 2 min (PostgreSQL, bot y web caídos). Repite con --yes"
    say "ensayo: cierro y reabro el volumen"
    cmd_close
    if marked tang-bound; then cmd_open --auto; else need_tty; cmd_open; fi
    mark drill-ok; say "ensayo correcto; siguiente: sudo purgito-vault verify-recovery"
}

# ── watchdog: un congelamiento total reinicia la VM sola (solo tiene sentido con desbloqueo automático) ──
cmd_watchdog() {
    need_root; guard_install_dir
    case "${1:-status}" in
        on)
            marked tang-bound || [ "${2:-}" = "--force" ] || die "activa antes tang-bind: un reinicio por watchdog dejaría el volumen cerrado hasta que lo abras a mano"
            echo iTCO_wdt > /etc/modules-load.d/purgito-watchdog.conf
            modprobe iTCO_wdt; [ -e /dev/watchdog0 ] || die "no hay /dev/watchdog0 (iTCO_wdt no inició): no se activa nada"
            mkdir -p /etc/systemd/system.conf.d
            printf '# Gestionado por purgito-vault\n[Manager]\nRuntimeWatchdogSec=120s\nWatchdogDevice=/dev/watchdog0\nRebootWatchdogSec=10min\n' > /etc/systemd/system.conf.d/10-purgito-watchdog.conf
            printf '# Gestionado por purgito-vault: un fallo del kernel reinicia la VM (traza en la consola serie del host)\nkernel.panic = 30\nkernel.panic_on_oops = 1\nkernel.softlockup_panic = 1\n' > /etc/sysctl.d/90-purgito-hang.conf
            sysctl -q --system; systemctl daemon-reexec
            say "watchdog activo: si la VM deja de alimentarlo 120 s, se reinicia sola (y Tang desbloquea el volumen)" ;;
        off)
            rm -f /etc/systemd/system.conf.d/10-purgito-watchdog.conf /etc/sysctl.d/90-purgito-hang.conf /etc/modules-load.d/purgito-watchdog.conf
            sysctl -w kernel.panic=0 kernel.panic_on_oops=0 kernel.softlockup_panic=0 >/dev/null; systemctl daemon-reexec
            say "watchdog desactivado (el módulo sigue cargado hasta el próximo reinicio, sin alimentarse)" ;;
        status) echo "watchdog: $([ -e /etc/systemd/system.conf.d/10-purgito-watchdog.conf ] && echo activo || echo no) | systemd: $(systemctl show -p RuntimeWatchdogUSec --value)" ;;
        *) die "uso: watchdog on | off | status" ;;
    esac
}

# ── lista de comprobaciones de recuperación (no cambia nada salvo la marca final) ────────────────
cmd_verify_recovery() {
    need_root; guard_install_dir
    local ok=1 cur full
    chk() { if [ "$1" = 1 ]; then printf '  [ok]  %s\n' "$2"; else printf '  [FALTA] %s\n' "$2"; ok=0; fi; }
    echo "Comprobaciones de recuperación:" >&2
    cur="$(core_slots)"; full="$(slots_list "$IMG" | sort | tr '\n' ' ')"
    chk "$([ ! -e "$KEYFILE" ] && marked retired && echo 1 || echo 0)" "clave provisional retirada y destruida (enroll retire)"
    chk "$([ "$(core_slots | wc -w)" = 2 ] && echo 1 || echo 0)" "el volumen tiene exactamente 2 ranuras de contraseña (desbloqueo y recuperación; la de Tang aparte)"
    chk "$(marked verified-unlock && [ "$(cat "$ENR/verified-unlock" 2>/dev/null)" = "$cur" ] && echo 1 || echo 0)" "contraseña de desbloqueo comprobada contra el encabezado actual"
    chk "$(marked verified-recovery && [ "$(cat "$ENR/verified-recovery" 2>/dev/null)" = "$cur" ] && echo 1 || echo 0)" "contraseña de recuperación comprobada contra el encabezado actual"
    chk "$(marked age-verified && echo 1 || echo 0)" "acceso real a la clave privada age acreditado (age-canary / age-verify)"
    local fh; fh="$(ls -1t "$STATE"/luks-header-final-*.img.age 2>/dev/null | head -1 || true)"
    chk "$([ -n "$fh" ] && [ "$(cat "$fh.slots" 2>/dev/null)" = "$full" ] && echo 1 || echo 0)" "respaldo definitivo del encabezado, con las ranuras actuales y sin la provisional"
    chk "$(marked final-header-uploaded && echo 1 || { rh && echo 1 || echo 0; })" "respaldo del encabezado subido y verificado en R2"
    local dump_ok=0
    if rh; then dump_ok=1; else
        local last; last="$(systemd-run --quiet --wait --pipe -p User=purgito_backup -p EnvironmentFile="$BACKUP_ENV" /bin/bash -c '"$PYTHON" -I /opt/purgito-backup/scripts/r2_backup.py list' 2>/dev/null | awk -F'\t' '$1 ~ /^purgito-.*dump\.age$/ {print $3}' | sort | tail -1)"
        [ -n "$last" ] && [ "$(( $(date +%s) - $(date -d "$last" +%s) ))" -lt 129600 ] && dump_ok=1
    fi
    chk "$dump_ok" "hay un dump cifrado en R2 de menos de 36 h (ruta de recuperación de los datos)"
    chk "$(marked drill-ok && marked retired && [ "$ENR/drill-ok" -nt "$ENR/retired" ] && echo 1 || echo 0)" "ensayo real: cerrar y abrir el volumen tecleando la contraseña DESPUÉS de retirar la provisional (aviso: ~2 min sin web)"
    if [ "$ok" = 1 ]; then mark recovery-verified; say "recuperación VERIFICADA: ya se puede hacer wipe-plaintext"; else rm -f "$ENR/recovery-verified"; die "recuperación NO verificada: completa lo que falta"; fi
}

# ── amplía el contenedor en línea ───────────────────────────────────────────────────────────────
cmd_grow() {
    need_root; guard_install_dir
    local arg="${1:-}"; [ -n "$arg" ] || die "uso: purgito-vault grow +2G   (o un tamaño total, p. ej. 10G)"
    is_open && is_mounted || die "el volumen debe estar abierto y montado"
    local cur target add; cur=$(stat -c %s "$IMG")
    if [[ "$arg" == +* ]]; then add=$(numfmt --from=iec "${arg#+}"); target=$((cur + add)); else target=$(numfmt --from=iec "$arg"); fi
    [ "$target" -gt "$cur" ] || die "el nuevo tamaño debe ser mayor que el actual ($(numfmt --to=iec "$cur"))"
    local avail; avail=$(df -B1 --output=avail "$(dirname "$IMG")" | tail -1)
    [ "$avail" -gt $(( (target - cur) + MIN_FREE_GB*1024*1024*1024 )) ] || die "la raíz quedaría con menos de $MIN_FREE_GB GiB libres"
    local loopdev; loopdev="$(losetup -j "$IMG" | cut -d: -f1 | head -1)"
    [ -n "$loopdev" ] || die "no encuentro el dispositivo loop de $IMG"
    say "ampliando $(numfmt --to=iec "$cur") -> $(numfmt --to=iec "$target")"
    fallocate -l "$target" "$IMG"
    losetup -c "$loopdev"
    cryptsetup resize "$MAPPER"
    resize2fs "/dev/mapper/$MAPPER" >/dev/null
    df -h "$MNT" | tail -1 >&2
    say "ampliado en línea; no se interrumpió ningún servicio"
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
# Qué toca: SOLO la "capa de abajo" de cada ruta superpuesta (lo que hay en el disco normal, oculto por el
# montaje), vista a través de un segundo montaje de `/`. Nunca el contenido del volumen cifrado: por cada
# ruta se comprueba que la capa de abajo y la ruta activa están en DISPOSITIVOS DISTINTOS y, si no, se
# omite. Incluye archivos ocultos (find los recorre todos), enlaces y demás entradas no-directorio.
# Qué NO hace: no garantiza borrar bloques viejos de archivos reescritos o borrados antes (espacio libre),
# ni copias en snapshots del disco virtual del host, ni en R2; en ext4 un `shred` sobrescribe los bloques
# actuales pero los nombres pueden quedar en el journal. Ver docs/CIFRADO_EN_REPOSO.md § Limitaciones.
wipe_scan() { # imprime por ruta: tipo, entradas, bytes, ocultos, hardlinks, dispersos
    local under="$1" b dev_under dev_active
    for b in "${BINDS[@]}"; do
        split_bind "$b"
        if ! is_mp "$BDST"; then printf '%-44s NO superpuesto: se omite\n' "$BDST"; continue; fi
        if [ ! -e "$under$BDST" ]; then printf '%-44s sin capa de abajo\n' "$BDST"; continue; fi
        dev_under="$(stat -c %d "$under$BDST")"; dev_active="$(stat -c %d "$BDST")"
        if [ "$dev_under" = "$dev_active" ]; then printf '%-44s PELIGRO: misma unidad que la ruta activa: se omite\n' "$BDST"; continue; fi
        local files=0 bytes=0 hidden=0 links=0 sparse=0 other=0
        if [ -d "$under$BDST" ]; then
            files=$(find "$under$BDST" -xdev -type f | wc -l)
            bytes=$(find "$under$BDST" -xdev -type f -printf '%s\n' | awk '{s+=$1} END{print s+0}')
            hidden=$(find "$under$BDST" -xdev -name '.*' ! -type d | wc -l)
            links=$(find "$under$BDST" -xdev -type f -links +1 | wc -l)
            sparse=$(find "$under$BDST" -xdev -type f -printf '%S %p\n' | awk '$1+0<0.9{n++} END{print n+0}')
            other=$(find "$under$BDST" -xdev ! -type f ! -type d | wc -l)
        elif [ -f "$under$BDST" ]; then files=1; bytes=$(stat -c %s "$under$BDST"); fi
        printf '%-44s archivos=%-6s %8s MiB  ocultos=%s  hardlinks=%s  dispersos=%s  no-regulares=%s\n' \
            "$BDST" "$files" "$((bytes/1048576))" "$hidden" "$links" "$sparse" "$other"
    done
}

wipe_gate() { # $1 = --sin-ensayo (opcional)
    [ ! -e "$KEYFILE" ] || die "aún existe la clave provisional: termina 'enroll retire'"
    marked retired || die "falta 'enroll retire'"
    marked recovery-verified || die "la recuperación NO está verificada: ejecuta 'purgito-vault verify-recovery' (y completa lo que falte)"
    [ "$(core_slots | wc -w)" = 2 ] || die "el volumen no tiene exactamente 2 ranuras de contraseña"
    marked age-verified || die "falta acreditar la clave privada age"
    if [ "${1:-}" != "--sin-ensayo" ]; then marked drill-ok && [ "$ENR/drill-ok" -nt "$ENR/retired" ] || die "falta el ensayo real de apertura con contraseña tras retirar la provisional"; fi
}

cmd_wipe() {
    need_root; guard_install_dir
    is_open && is_mounted || die "el volumen debe estar abierto"
    local under; under="$(mktemp -d)"; mount --bind / "$under"; UNDER="$under"
    if [ "${1:-}" = "--plan" ]; then
        echo "PLAN (no se cambia nada). Capa en claro que se sobrescribiría y borraría:" >&2
        wipe_scan "$under"
        cat >&2 <<'EOF'

No se tocan: el contenido del volumen cifrado, rutas no listadas arriba, el swap (ya en ceros),
ni nada en R2. Límites: bloques de versiones antiguas de archivos o borrados anteriores (espacio libre)
y copias en snapshots del disco virtual NO se pueden garantizar desde dentro de la VM.
EOF
        return 0
    fi
    [ "${1:-}" = "--yes" ] || [ "${2:-}" = "--yes" ] || die "esto es IRREVERSIBLE. Revisa 'wipe-plaintext --plan' y repite con --yes"
    wipe_gate "${1:-}"
    local b n=0 dev_under dev_active
    for b in "${BINDS[@]}"; do
        split_bind "$b"
        is_mp "$BDST" || { say "$BDST no está superpuesto: se omite"; continue; }
        dev_under="$(stat -c %d "$under$BDST" 2>/dev/null || echo x)"; dev_active="$(stat -c %d "$BDST")"
        [ "$dev_under" != "$dev_active" ] || { say "AVISO: $BDST: capa de abajo y activa comparten unidad; se omite por seguridad"; continue; }
        if [ "$BKIND" = file ]; then
            if [ -f "$under$BDST" ]; then
                # Es punto de montaje: no se puede renombrar ni borrar (EBUSY); se sobrescribe en el sitio.
                shred -n 1 -z "$under$BDST"; : > "$under$BDST"; n=$((n+1))
            fi
        elif [ -d "$under$BDST" ]; then
            find "$under$BDST" -xdev -type f -exec shred -n 1 -z -u {} + 2>/dev/null || true
            find "$under$BDST" -xdev -mindepth 1 ! -type d -delete 2>/dev/null || true   # enlaces, sockets, etc.
            find "$under$BDST" -xdev -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true
            n=$((n+1))
        fi
        say "sobrescrito el contenido en claro de $BDST"
    done
    cmd_wipe_logs
    if [ "$SKIP_UNITS" != 1 ]; then fstrim -v / 2>&1 | sed 's/^/== fstrim: /' >&2 || true; fi   # best effort: avisa al disco virtual de los bloques libres
    say "listo ($n rutas). Comprueba con: deploy/check_encryption_at_rest.sh"
}

case "${1:-}" in
    install)         shift; cmd_install "$@" ;;
    bootstrap)       shift; cmd_bootstrap "$@" ;;
    sync)            shift; cmd_sync "$@" ;;
    units)           shift; cmd_units "$@" ;;
    swap-encrypt)    shift; cmd_swap_encrypt "$@" ;;
    migrate)         shift; cmd_migrate "$@" ;;
    open)            shift; cmd_open "$@" ;;
    close)           shift; cmd_close "$@" ;;
    status)          shift; cmd_status "$@" ;;
    enroll)          shift; cmd_enroll "$@" ;;
    age-canary)      shift; cmd_age_canary "$@" ;;
    age-verify)      shift; cmd_age_verify "$@" ;;
    header-backup)   shift; cmd_header_backup "$@" ;;
    verify-recovery) shift; cmd_verify_recovery "$@" ;;
    tang-bind)       shift; cmd_tang_bind "$@" ;;
    tang-unbind)     shift; cmd_tang_unbind "$@" ;;
    tang-test)       shift; cmd_tang_test "$@" ;;
    drill)           shift; cmd_drill "$@" ;;
    watchdog)        shift; cmd_watchdog "$@" ;;
    grow)            shift; cmd_grow "$@" ;;
    wipe-logs)       shift; cmd_wipe_logs "$@" ;;
    wipe-plaintext)  shift; cmd_wipe "$@" ;;
    *) sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
