#!/bin/bash
# Backup de la base PostgreSQL de Purgito (pg_dump) + subida al bucket privado
# de R2 + poda. Ver DEPLOY.md § "Backups".
#
# Frecuencia: diaria (cron, 03:17 UTC). Retención, separada para el disco y R2:
#   - disco local: los KEEP_LAST=2 más recientes (el disco es chico).
#   - R2: R2_KEEP_DAILY=7 diarios + R2_KEEP_WEEKLY=2 (domingos), nada de
#     BACKUP_MAX_AGE_DAYS=14 días o más: es lo que promete la política de
#     privacidad (docs/PRIVACY.md). Ver `r2_backup.py prune-gfs`.
# Si el backup falla se avisa por BACKUP_ALERT_WEBHOOK (webhook de Discord, opcional).
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
# Disco: se niega a empezar (y a cifrar) si no quedan MIN_FREE_MB (400) libres tras el
# backup, para no dejar sin espacio a PostgreSQL, que vive en el mismo filesystem.
#
# Variables (todas opcionales):
#   DATABASE_URL                         postgresql://usuario:clave@host:5432/base (default: la del .env)
#   BACKUP_DIR                           destino local
#   KEEP_LAST                            cuántos backups se conservan en el DISCO (default: 2, mínimo 1)
#   R2_KEEP_DAILY / R2_KEEP_WEEKLY       retención en R2: diarios y domingos (default: 7 y 2)
#   BACKUP_MAX_AGE_DAYS                  antigüedad máxima en R2 (default: 14; la de la política de privacidad)
#   SKIP_PRUNE=1                         no poda nada (ni R2 ni disco); solo para el primer backup manual
#   MIN_FREE_MB / BACKUP_EST_MB          reserva de disco que debe quedar libre (default 400) y estimación del dump sin backups previos (150)
#   BACKUP_ALERT_WEBHOOK                 webhook de Discord al que avisar si el backup falla (default: el del .env)
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
R2_KEEP_DAILY="${R2_KEEP_DAILY:-7}"
R2_KEEP_WEEKLY="${R2_KEEP_WEEKLY:-2}"
BACKUP_MAX_AGE_DAYS="${BACKUP_MAX_AGE_DAYS:-14}"
# Reserva de disco: tras el backup tienen que quedar libres al menos MIN_FREE_MB en el
# filesystem. PostgreSQL vive en el mismo disco: si el backup lo llenara, la base podría
# caerse al no poder escribir WAL. BACKUP_EST_MB estima el dump si aún no hay backups.
# SKIP_PRUNE=1: no poda nada (ni en R2 ni en el disco). Para el primer backup manual.
SKIP_PRUNE="${SKIP_PRUNE:-0}"
MIN_FREE_MB="${MIN_FREE_MB:-400}"
BACKUP_EST_MB="${BACKUP_EST_MB:-150}"
PYTHON="${PYTHON:-$script_dir/../.venv/bin/python}"
AGE="${AGE:-age}"
REVOKED_RECIPIENTS="$script_dir/age-revoked-recipients.txt"
UPLOADER="$script_dir/../scripts/r2_backup.py"

log() { echo "$(date -Is) $*"; }

# MB libres en el filesystem de $1.
free_mb() { df -Pm "$1" | awk 'NR==2 {print $4}'; }

env_value() {
    [ -f "$ENV_FILE" ] || return 0
    sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=(.*)\$/\\2/p" "$ENV_FILE" \
        | tail -n 1 \
        | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//' \
            -e 's/^"(.*)"$/\1/' -e "s/^'(.*)'\$/\\1/"
}

plain=""
partial=""
alert_url="${BACKUP_ALERT_WEBHOOK:-}"
[ -n "$alert_url" ] || alert_url="$(env_value BACKUP_ALERT_WEBHOOK)"

# Aviso de fallo: sin secretos en el mensaje (host y fecha, nada más). Un webhook
# caído o mal puesto no cambia el resultado del backup.
alert() {
    [ -n "$alert_url" ] || return 0
    command -v curl >/dev/null 2>&1 || return 0
    curl -fsS --max-time 10 -H 'Content-Type: application/json' \
        -d "{\"content\": \"⚠️ Backup de Purgito FALLÓ en $(hostname) ($(date -u +%Y-%m-%dT%H:%MZ)). Revisa ~/purgito-bot-backups/backup.log\"}" \
        "$alert_url" >/dev/null 2>&1 || true
}
on_exit() {
    local rc=$?
    trap - EXIT
    rm -f "$plain" "$partial" 2>/dev/null || true
    [ "$rc" -eq 0 ] || alert
    exit "$rc"
}
trap on_exit EXIT

if [[ ! "$KEEP_LAST" =~ ^[1-9][0-9]*$ ]]; then
    echo "$(date -Is) ERROR KEEP_LAST='$KEEP_LAST' no es válido: tiene que ser un entero >= 1 (default 2). No se hizo backup." >&2
    exit 1
fi
for v in R2_KEEP_DAILY BACKUP_MAX_AGE_DAYS MIN_FREE_MB BACKUP_EST_MB; do
    if [[ ! "${!v}" =~ ^[1-9][0-9]*$ ]]; then
        echo "$(date -Is) ERROR $v='${!v}' no es válido: entero >= 1. No se hizo backup." >&2
        exit 1
    fi
done
if [[ ! "$R2_KEEP_WEEKLY" =~ ^[0-9]+$ ]] || [ "$R2_KEEP_DAILY" -gt "$BACKUP_MAX_AGE_DAYS" ]; then
    echo "$(date -Is) ERROR R2_KEEP_WEEKLY debe ser entero >= 0 y R2_KEEP_DAILY no puede superar BACKUP_MAX_AGE_DAYS. No se hizo backup." >&2
    exit 1
fi
if [ -n "${RETENTION_DAYS:-}" ]; then
    echo "$(date -Is) AVISO RETENTION_DAYS ya no se usa: la retención es por cantidad (KEEP_LAST=$KEEP_LAST), no por edad" >&2
fi

# Lee UNA variable del .env sin ejecutarlo (nada de `source .env`).
database_url="${DATABASE_URL:-}"
[ -n "$database_url" ] || database_url="$(env_value DATABASE_URL)"
if [ -z "$database_url" ] && [ -n "${PGUSER:-}" ] && [ -n "${PGDATABASE:-}" ]; then
    # Entorno libpq (PGUSER/PGHOST/PGDATABASE): es el caso del runner aislado, que se
    # conecta por el socket local con un rol de solo lectura (peer, sin contraseña).
    export PGHOST="${PGHOST:-/var/run/postgresql}"
elif [ -z "$database_url" ]; then
    echo "$(date -Is) ERROR falta DATABASE_URL (entorno o $ENV_FILE) o PGUSER+PGDATABASE" >&2
    exit 1
else
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
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
plain="$BACKUP_DIR/.purgito-$stamp.dump.plain"
dest="$BACKUP_DIR/purgito-$stamp.dump.age"
partial="$dest.partial"
# Nada en claro (ni a medias) sobrevive a esta corrida, salga como salga.

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
    # Claves revocadas (generación 1: su clave privada se perdió): un backup cifrado
    # con ellas no se podría restaurar. Sin la lista no se sabe: se niega.
    if [ ! -r "$REVOKED_RECIPIENTS" ]; then
        echo "$(date -Is) ERROR falta $REVOKED_RECIPIENTS: no se puede comprobar que la clave no esté revocada. No se hizo backup." >&2
        exit 1
    fi
    if grep -qxF -- "$r" "$REVOKED_RECIPIENTS"; then
        echo "$(date -Is) ERROR BACKUP_AGE_RECIPIENTS contiene una clave REVOCADA (age-revoked-recipients.txt): su clave privada no existe. No se hizo backup." >&2
        exit 1
    fi
    age_args+=(-r "$r")
    n_recipients=$((n_recipients + 1))
done

if [ "$n_recipients" -eq 0 ] && [ -n "$backup_bucket" ]; then
    echo "$(date -Is) ERROR hay R2_BACKUP_BUCKET pero no BACKUP_AGE_RECIPIENTS: nunca se sube un dump en claro. No se hizo backup." >&2
    exit 1
fi

# Espacio: el dump en claro y el cifrado conviven un instante (2 x tamaño del dump). El
# tamaño se estima con el backup más reciente del disco (o BACKUP_EST_MB si no hay).
last_backup="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'purgito-*.dump.age' -printf '%T@ %s\n' 2>/dev/null | sort -rn | awk 'NR==1 {print $2}')"
if [ -n "$last_backup" ]; then est_mb=$(( (last_backup + 1048575) / 1048576 )); else est_mb="$BACKUP_EST_MB"; fi
need_mb=$(( est_mb * 2 + MIN_FREE_MB ))
have_mb="$(free_mb "$BACKUP_DIR")"
if [ "$have_mb" -lt "$need_mb" ]; then
    echo "$(date -Is) ERROR espacio insuficiente en $BACKUP_DIR: libres ${have_mb} MB, hacen falta ${need_mb} MB (2 x ${est_mb} MB del dump + ${MIN_FREE_MB} MB de reserva para PostgreSQL). No se hizo backup." >&2
    exit 1
fi

log "BACKUP START (db=$PGDATABASE host=$PGHOST, retención: los $KEEP_LAST más recientes; libres ${have_mb} MB)"
# nice: que el volcado no le quite CPU al bot. pg_dump solo lee la base; si algo lo mata
# (falta de disco, señal), no deja nada a medias en PostgreSQL y el trap borra los temporales.
NICE=()
command -v nice >/dev/null 2>&1 && NICE=(nice -n 10)
if ! "${NICE[@]}" pg_dump -Fc --no-owner -f "$plain"; then
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
    plain_mb=$(( ($(stat -c %s "$plain") + 1048575) / 1048576 ))
    have_mb="$(free_mb "$BACKUP_DIR")"
    if [ "$have_mb" -lt $(( plain_mb + MIN_FREE_MB )) ]; then
        echo "$(date -Is) ERROR sin espacio para cifrar: libres ${have_mb} MB, hacen falta ${plain_mb} MB + ${MIN_FREE_MB} MB de reserva. Se borra el dump en claro y no se hizo backup." >&2
        exit 1
    fi
    if ! "${NICE[@]}" "$AGE" "${age_args[@]}" -o "$partial" "$plain"; then
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
    # Retención en R2: diarios + domingos con tope de edad (no depende de una
    # regla de lifecycle del dashboard; el tope de 14 días lo cumple el propio script). Un fallo se avisa y hace fallar la corrida, pero
    # el backup de hoy ya está hecho y subido.
    if [ "$SKIP_PRUNE" = "1" ]; then
        log "R2 PRUNE OMITIDO (SKIP_PRUNE=1): no se borra nada en R2"
    elif ! "$PYTHON" "$UPLOADER" prune-gfs --daily "$R2_KEEP_DAILY" --weekly "$R2_KEEP_WEEKLY" --max-age-days "$BACKUP_MAX_AGE_DAYS" --apply; then
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
if [ "$SKIP_PRUNE" = "1" ]; then
    log "LOCAL PRUNE OMITIDO (SKIP_PRUNE=1): no se borra nada en el disco"
else
    prune_local "$KEEP_LAST"
fi

log "BACKUP COMPLETE: OK backup -> $dest (pg_restore --list ok, $tables tablas con datos, $state, $remote)"
[ "$prune_failed" -eq 0 ] || exit 1
