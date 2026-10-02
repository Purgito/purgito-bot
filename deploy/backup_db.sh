#!/bin/bash
# Backup de la base PostgreSQL de Purgito (pg_dump) + subida al bucket privado
# de R2 + poda. Ver DEPLOY.md § "Backups".
#
# Frecuencia: semanal (cron, domingo 03:17 UTC). Retención: como MÁXIMO
# KEEP_LAST=2 backups, el más reciente y el anterior, tanto en el disco local
# como en R2. No depende de la edad: al aparecer un tercero se borra el más
# antiguo. Con 1 o 2 backups no se borra nada.
#
# Cada corrida deja en BACKUP_DIR:
#   purgito-<fecha>.dump.age   pg_dump en formato custom (-Fc) CIFRADO con age
#                              (https://age-encryption.org) para la(s) clave(s)
#                              pública(s) de BACKUP_AGE_RECIPIENTS. Se descifra
#                              con `age -d -i <clave-privada>` y se restaura con
#                              pg_restore. La clave privada NO vive en este
#                              servidor: aquí solo está la pública.
# El dump en claro solo existe un instante en un archivo temporal 0600 dentro de
# BACKUP_DIR (0700) y se borra siempre, también si la corrida falla.
# Un backup que no pasa la verificación (pg_restore --list legible y con datos de
# tablas, antes de cifrar; cabecera age con un destinatario por cada clave,
# después) se borra y la corrida falla.
#
# Sin BACKUP_AGE_RECIPIENTS: si hay R2_BACKUP_BUCKET la corrida FALLA (nunca se
# sube un dump en claro); sin bucket queda un purgito-<fecha>.dump en claro 0600
# solo local y el log lo avisa.
#
# Subida a R2 (bucket R2_BACKUP_BUCKET, PRIVADO -- sin URL pública): se intenta
# si R2_BACKUP_BUCKET está definida en el entorno o en el .env del repo (cron no
# carga el .env, así que se lee de ahí). Con el bucket configurado, una subida
# que falla hace fallar la corrida (código 1) y NO se poda nada: el backup local
# queda donde está, y también los anteriores, que podrían ser los únicos que
# nunca llegaron a R2. Sin R2_BACKUP_BUCKET el backup queda solo en local y el
# log lo dice.
#
# Variables (todas opcionales):
#   DATABASE_URL                         postgresql://usuario:clave@host:5432/base (default: la del .env)
#   BACKUP_DIR                           destino local
#   KEEP_LAST                            cuántos backups se conservan, local y R2 (default: 2, mínimo 1)
#   ENV_FILE                             .env del que leer DATABASE_URL y R2_BACKUP_BUCKET (default: el del repo)
#   BACKUP_AGE_RECIPIENTS                claves públicas age (age1...), separadas por espacio o coma (default: la del .env)
#   PYTHON                               intérprete con boto3 (default: el .venv del repo)
#   AGE                                  binario de age (default: age)
set -euo pipefail

# Los backups llevan el contenido de los mensajes aprendidos y los tokens de
# webhook: solo el usuario que corre el cron los puede leer.
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$HOME/purgito-bot-backups}"
KEEP_LAST="${KEEP_LAST:-2}"
ENV_FILE="${ENV_FILE:-$script_dir/../.env}"
PYTHON="${PYTHON:-$script_dir/../.venv/bin/python}"
AGE="${AGE:-age}"
UPLOADER="$script_dir/../scripts/r2_backup.py"

log() { echo "$(date -Is) $*"; }

if [[ ! "$KEEP_LAST" =~ ^[1-9][0-9]*$ ]]; then
    echo "$(date -Is) ERROR KEEP_LAST='$KEEP_LAST' no es válido: tiene que ser un entero >= 1 (default 2). No se hizo backup." >&2
    exit 1
fi
if [ -n "${RETENTION_DAYS:-}" ]; then
    echo "$(date -Is) AVISO RETENTION_DAYS ya no se usa: la retención es por cantidad (KEEP_LAST=$KEEP_LAST), no por edad" >&2
fi

# Lee UNA variable del .env sin ejecutarlo (nada de `source .env`).
env_value() {
    [ -f "$ENV_FILE" ] || return 0
    sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=(.*)\$/\\2/p" "$ENV_FILE" \
        | tail -n 1 \
        | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//' \
            -e 's/^"(.*)"$/\1/' -e "s/^'(.*)'\$/\\1/"
}

database_url="${DATABASE_URL:-}"
[ -n "$database_url" ] || database_url="$(env_value DATABASE_URL)"
if [ -z "$database_url" ]; then
    echo "$(date -Is) ERROR falta DATABASE_URL (entorno o $ENV_FILE)" >&2
    exit 1
fi

# postgresql://user:clave@host:puerto/base -> variables PG* (la clave no viaja en
# la línea de comandos, donde `ps` la mostraría).
re='^postgres(ql)?://([^:@/]+)(:([^@]*))?@([^:/]+)(:([0-9]+))?/([^?]+)'
if [[ ! "$database_url" =~ $re ]]; then
    echo "$(date -Is) ERROR DATABASE_URL no tiene la forma postgresql://usuario:clave@host:puerto/base" >&2
    exit 1
fi
export PGUSER="${BASH_REMATCH[2]}"
PGPASSWORD="$(printf '%b' "${BASH_REMATCH[4]//%/\\x}")"
export PGPASSWORD
export PGHOST="${BASH_REMATCH[5]}"
export PGPORT="${BASH_REMATCH[7]:-5432}"
export PGDATABASE="${BASH_REMATCH[8]}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
plain="$BACKUP_DIR/.purgito-$stamp.dump.plain"
dest="$BACKUP_DIR/purgito-$stamp.dump.age"
partial="$dest.partial"
# Nada en claro (ni a medias) sobrevive a esta corrida, salga como salga.
trap 'rm -f "$plain" "$partial"' EXIT

backup_bucket="${R2_BACKUP_BUCKET:-}"
[ -n "$backup_bucket" ] || backup_bucket="$(env_value R2_BACKUP_BUCKET)"

recipients="${BACKUP_AGE_RECIPIENTS:-}"
[ -n "$recipients" ] || recipients="$(env_value BACKUP_AGE_RECIPIENTS)"
recipients="${recipients//,/ }"
age_args=()
n_recipients=0
for r in $recipients; do
    if [[ ! "$r" =~ ^age1[a-z0-9]{50,}$ ]]; then
        echo "$(date -Is) ERROR BACKUP_AGE_RECIPIENTS: '$r' no parece una clave pública age (age1...)" >&2
        exit 1
    fi
    age_args+=(-r "$r")
    n_recipients=$((n_recipients + 1))
done

if [ "$n_recipients" -eq 0 ] && [ -n "$backup_bucket" ]; then
    echo "$(date -Is) ERROR hay R2_BACKUP_BUCKET pero no BACKUP_AGE_RECIPIENTS: nunca se sube un dump en claro. No se hizo backup." >&2
    exit 1
fi

log "BACKUP START (db=$PGDATABASE host=$PGHOST, retención: los $KEEP_LAST más recientes)"
if ! pg_dump -Fc --no-owner -f "$plain"; then
    echo "$(date -Is) ERROR backup failed (db=$PGDATABASE host=$PGHOST)" >&2
    exit 1
fi
log "DUMP CREATED ($(stat -c %s "$plain") bytes, formato custom, solo temporal 0600)"

# Verificación del dump en claro: se tiene que poder listar y traer datos de tablas.
if ! listing="$(pg_restore --list "$plain" 2>&1)" || ! grep -q ' TABLE DATA ' <<<"$listing"; then
    echo "$(date -Is) ERROR backup no pasó la verificación de pg_restore --list" >&2
    exit 1
fi
tables="$(grep -c ' TABLE DATA ' <<<"$listing")"
log "DUMP VERIFIED (pg_restore --list ok, $tables tablas con datos)"

if [ "$n_recipients" -gt 0 ]; then
    if ! "$AGE" "${age_args[@]}" -o "$partial" "$plain"; then
        echo "$(date -Is) ERROR no se pudo cifrar el backup con age" >&2
        exit 1
    fi
    # Verificación del cifrado: cabecera age y una estrofa por destinatario.
    stanzas="$(head -c 4096 "$partial" | grep -a -c '^-> X25519 ' || true)"
    if [ "$(head -c 22 "$partial")" != "age-encryption.org/v1" ] || [ "$stanzas" -ne "$n_recipients" ] \
        || [ "$(stat -c %s "$partial")" -le "$(stat -c %s "$plain")" ]; then
        echo "$(date -Is) ERROR el archivo cifrado no pasó la verificación (cabecera/destinatarios/tamaño)" >&2
        exit 1
    fi
    mv "$partial" "$dest"
    rm -f "$plain"
    log "ENCRYPTED ($(basename "$dest"), $(stat -c %s "$dest") bytes, age, $n_recipients destinatario(s); el dump en claro ya se borró)"
    state="cifrado con age ($n_recipients destinatario(s))"
else
    dest="$BACKUP_DIR/purgito-$stamp.dump"
    mv "$plain" "$dest"
    state="SIN CIFRAR (sin BACKUP_AGE_RECIPIENTS), solo local"
fi
chmod 600 "$dest"

# Subida a R2. Desde acá el backup local ya es válido: si la subida falla se
# sale con error SIN tocar nada -- ni este backup ni los viejos (las podas de más
# abajo no corren). r2_backup.py rechaza cualquier archivo que no sea age y, tras
# subir, comprueba en R2 que el objeto quedó del mismo tamaño que el local.
prune_failed=0
remote="solo local: R2_BACKUP_BUCKET sin configurar"
if [ -n "$backup_bucket" ]; then
    if ! "$PYTHON" "$UPLOADER" upload "$dest"; then
        echo "$(date -Is) ERROR backup local OK ($dest) pero NO subió a R2 (bucket $backup_bucket): se conserva todo y no se poda nada" >&2
        exit 1
    fi
    remote="subido a R2 ($backup_bucket)"
    log "UPLOADED ($(basename "$dest") en R2, bucket $backup_bucket, tamaño verificado)"
    # Retención en R2: los KEEP_LAST más recientes (no depende de una regla de
    # lifecycle del dashboard). Un fallo se avisa y hace fallar la corrida, pero
    # el backup de hoy ya está hecho y subido.
    if ! "$PYTHON" "$UPLOADER" prune --keep "$KEEP_LAST" --apply; then
        echo "$(date -Is) ERROR no se pudo podar los backups viejos de R2 (el backup de hoy sí se subió)" >&2
        prune_failed=1
    fi
fi

# Retención local: los KEEP_LAST backups más recientes (purgito-*.dump[.age] con
# contenido). Los nombres llevan la fecha, así que el orden alfabético es el
# cronológico. Con KEEP_LAST o menos backups no se borra nada. No toca nada más
# de BACKUP_DIR (backups de rollback, .bak, el log).
prune_local() {
    local keep="$1" f n i kept=0 deleted=0
    local -a found=()
    while IFS= read -r f; do
        found+=("$f")
    done < <(
        shopt -s nullglob
        for f in "$BACKUP_DIR"/purgito-*.dump "$BACKUP_DIR"/purgito-*.dump.age; do
            [ -s "$f" ] && basename "$f"
        done | LC_ALL=C sort
    )
    n=${#found[@]}
    log "LOCAL PRUNE: $n backup(s) válido(s) en $BACKUP_DIR; política: conservar los $keep más recientes"
    for ((i = 0; i < n; i++)); do
        if [ "$i" -ge $((n - keep)) ]; then
            log "LOCAL PRUNE: conservo ${found[$i]}"
            kept=$((kept + 1))
        else
            rm -f -- "$BACKUP_DIR/${found[$i]}"
            log "LOCAL PRUNE: borrado ${found[$i]}"
            deleted=$((deleted + 1))
        fi
    done
    log "LOCAL PRUNE: $kept conservado(s), $deleted borrado(s)"
}
prune_local "$KEEP_LAST"

log "BACKUP COMPLETE: OK backup -> $dest (pg_restore --list ok, $tables tablas con datos, $state, $remote)"
[ "$prune_failed" -eq 0 ] || exit 1
