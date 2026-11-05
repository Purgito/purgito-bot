#!/bin/bash
# Instala el runner AISLADO de backups: el bot (usuario purgito) no puede leer sus credenciales
# ni modificar el código que las usa.
#
#   sudo deploy/install_backup_runner.sh --recipient age1...            # dry-run: solo muestra
#   sudo deploy/install_backup_runner.sh --recipient age1... --apply    # instala
#   sudo deploy/install_backup_runner.sh --remove [--apply]             # desinstala lo instalado
#
# Qué crea (todo aditivo; no toca el bot, Studio, PostgreSQL de producción ni el cron):
#   - usuario de sistema `purgito_backup` (sin login, sin home);
#   - /opt/purgito-backup/   copia de ROOT (root:root) del código de backups, sacada de lo
#                            COMMITEADO en este checkout (git show), no del árbol de trabajo;
#   - /etc/purgito/backup.env  root:root 0600: configuración y, después, las credenciales de
#                            R2 de backups (las escribes tú con set_backup_credentials.sh);
#   - /var/backups/purgito   dumps cifrados, purgito_backup 0700 (el bot no puede leerlos);
#   - rol PostgreSQL `purgito_backup` de SOLO LECTURA (pg_read_all_data + CONNECT), por socket local con
#     autenticación peer: no hay contraseña de base de datos para este usuario;
#   - purgito-backup.service y .timer en /etc/systemd/system. El timer NO se habilita.
#
# Desinstalar (--remove) quita /opt/purgito-backup y las unidades, y deja el usuario, el rol,
# /etc/purgito/backup.env y /var/backups/purgito para que no se pierda ningún dump.
set -euo pipefail

RUNNER_USER="purgito_backup"
DB_NAME="purgito"   # la base endurece CONNECT para PUBLIC: hay que concederlo explícitamente
OPT="/opt/purgito-backup"
ENVF="/etc/purgito/backup.env"
BKDIR="/var/backups/purgito"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$script_dir/.." && pwd)"

recipient=""
apply=0
remove=0
while [ $# -gt 0 ]; do
    case "$1" in
        --recipient) recipient="${2:-}"; shift 2 ;;
        --apply) apply=1; shift ;;
        --remove) remove=1; shift ;;
        *) echo "argumento desconocido: $1" >&2; exit 2 ;;
    esac
done
die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "• $*"; }
run() { if [ "$apply" = 1 ]; then "$@"; else echo "   (dry-run) $*"; fi; }

[ "$(id -u)" = 0 ] || die "ejecútalo con sudo"

FILES=(
    "src/r2.py:0644"
    "src/backup_recipients.py:0644"
    "scripts/r2_backup.py:0755"
    "deploy/backup_db.sh:0755"
    "deploy/age-revoked-recipients.txt:0644"
    "deploy/set_backup_credentials.sh:0755"
    "deploy/backup_task.sh:0755"
)

if [ "$remove" = 1 ]; then
    say "desinstalar: $OPT y las unidades systemd (se conservan usuario, rol, $ENVF y $BKDIR)"
    run systemctl disable --now purgito-backup.timer 2>/dev/null || true
    run rm -rf "$OPT" /etc/systemd/system/purgito-backup.service /etc/systemd/system/purgito-backup.timer
    run systemctl daemon-reload
    [ "$apply" = 1 ] || echo "(dry-run: añade --apply)"
    exit 0
fi

[[ "$recipient" =~ ^age1[a-z0-9]{50,}$ ]] || die "falta --recipient age1... (clave PÚBLICA)"
grep -qxF -- "$recipient" "$repo/deploy/age-revoked-recipients.txt" && die "esa clave está REVOCADA"
git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || die "$repo no es un checkout de git"
rev="$(git -C "$repo" rev-parse --short HEAD)"
for f in "${FILES[@]}"; do
    git -C "$repo" cat-file -e "HEAD:${f%%:*}" 2>/dev/null || die "${f%%:*} no está commiteado en HEAD"
    if ! git -C "$repo" diff --quiet HEAD -- "${f%%:*}"; then
        die "${f%%:*} tiene cambios sin commitear: se instala lo commiteado, revisa antes"
    fi
done
command -v age >/dev/null && command -v pg_dump >/dev/null || die "faltan age o pg_dump"
/usr/bin/python3 -c "import boto3, requests" 2>/dev/null || die "el python3 del sistema necesita boto3 y requests"
systemctl is-active --quiet postgresql@18-main || die "PostgreSQL 18 no está activo"
endpoint="$(sed -n -E 's/^[[:space:]]*R2_ENDPOINT_URL[[:space:]]*=[[:space:]]*"?([^"#[:space:]]+)"?.*$/\1/p' "$repo/.env" | tail -n 1)"
[ -n "$endpoint" ] || die "no encuentro R2_ENDPOINT_URL (no secreto) en $repo/.env"

echo "Instalando el runner aislado desde $repo @ $rev (dry-run: $([ "$apply" = 1 ] && echo no || echo sí))"

say "usuario de sistema $RUNNER_USER"
if getent passwd "$RUNNER_USER" >/dev/null; then echo "   ya existe"; else
    run useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$RUNNER_USER"
fi

say "código de root en $OPT (de HEAD=$rev)"
run install -d -m 0755 -o root -g root "$OPT" "$OPT/src" "$OPT/scripts" "$OPT/deploy"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
for f in "${FILES[@]}"; do
    path="${f%%:*}"; mode="${f##*:}"
    if [ "$apply" = 1 ]; then
        git -C "$repo" show "HEAD:$path" > "$tmpdir/blob"
        install -m "$mode" -o root -g root "$tmpdir/blob" "$OPT/$path"
        # Lo instalado tiene que ser byte a byte lo commiteado.
        [ "$(sha256sum < "$tmpdir/blob")" = "$(sha256sum < "$OPT/$path")" ] || die "$OPT/$path no coincide con HEAD:$path"
    else
        echo "   (dry-run) HEAD:$path -> $OPT/$path ($mode, root)"
    fi
done
run sh -c "echo '$rev' > '$OPT/VERSION'"

say "directorio de dumps $BKDIR ($RUNNER_USER 0700)"
run install -d -m 0700 -o "$RUNNER_USER" -g "$RUNNER_USER" "$BKDIR"

say "$ENVF (root:root 0600) sin credenciales"
if [ -e "$ENVF" ]; then echo "   ya existe: no se toca (para cambiar la configuración edítalo a mano)"; else
    if [ "$apply" = 1 ]; then
        install -d -m 0755 -o root -g root /etc/purgito
        ( umask 077
          cat > "$ENVF" <<ENV
# Configuración del backup aislado (generación 2). root:root 0600; la carga systemd.
# Las dos credenciales R2_BACKUP_* se añaden con: sudo $OPT/deploy/set_backup_credentials.sh
R2_ENDPOINT_URL=$endpoint
R2_BACKUP_BUCKET=purgito-backups
R2_BACKUP_PREFIX=gen2/
R2_IMAGES_BUCKET=purgito-images
R2_GIFS_BUCKET=purgito-gifs
BACKUP_AGE_RECIPIENTS=$recipient
BACKUP_DIR=$BKDIR
PYTHON=/usr/bin/python3
PGUSER=$RUNNER_USER
PGHOST=/var/run/postgresql
PGDATABASE=purgito
KEEP_LAST=2
MIN_FREE_MB=400
# Primer backup manual: no poda nada. Quitar esta línea al activar la poda automática.
SKIP_PRUNE=1
ENV
        )
        chown root:root "$ENVF"; chmod 600 "$ENVF"
    else echo "   (dry-run) crear $ENVF con endpoint, bucket, prefijo gen2/, clave pública y SKIP_PRUNE=1"; fi
fi

say "rol PostgreSQL $RUNNER_USER (solo lectura, peer por socket local)"
sql="DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='$RUNNER_USER') THEN CREATE ROLE $RUNNER_USER LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 2; END IF; END \$\$; GRANT pg_read_all_data TO $RUNNER_USER; GRANT CONNECT ON DATABASE $DB_NAME TO $RUNNER_USER;"
if [ "$apply" = 1 ]; then sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 -c "$sql"; else echo "   (dry-run) CREATE ROLE $RUNNER_USER LOGIN ...; GRANT pg_read_all_data; GRANT CONNECT ON DATABASE $DB_NAME"; fi

say "unidades systemd (el timer NO se habilita)"
run install -m 0644 -o root -g root "$repo/deploy/purgito-backup.service" /etc/systemd/system/purgito-backup.service
run install -m 0644 -o root -g root "$repo/deploy/purgito-backup.timer" /etc/systemd/system/purgito-backup.timer
run systemctl daemon-reload

[ "$apply" = 1 ] || echo "(dry-run: no se cambió nada; añade --apply)"
[ "$apply" = 0 ] || echo "Hecho. Siguiente: sudo $OPT/deploy/set_backup_credentials.sh"
