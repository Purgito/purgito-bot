"""Sube, lista y baja backups de la base (pg_dump) del bucket PRIVADO de R2 (R2_BACKUP_BUCKET).

Lo invoca deploy/backup_db.sh después de generar y verificar el backup local; a
mano sirve para traer un backup a una instancia nueva (ver DEPLOY.md § "Restaurar
desde un backup"). No lo usa el bot.

    python scripts/r2_backup.py upload purgito-X.dump
    python scripts/r2_backup.py list
    python scripts/r2_backup.py prune [--keep 2] [--apply]   # retención de R2: los N más recientes
    python scripts/r2_backup.py prune-gfs [--daily 7 --weekly 2 --max-age-days 14] [--apply]
    python scripts/r2_backup.py check [--max-age-hours 36]    # ¿el último backup es reciente?
    python scripts/r2_backup.py prune-ledger [--max-age-days 15] [--apply]
    python scripts/r2_backup.py preflight                    # solo lectura: ¿es seguro correr un backup?
    python scripts/r2_backup.py access-check                 # solo lectura: ¿los tokens están separados?
    python scripts/r2_backup.py media-check                  # solo lectura: ¿el token de imágenes/GIFs funciona y no ve los backups?
    python scripts/r2_backup.py download latest --dest ~/restore
    python scripts/r2_backup.py download purgito-20261001-031700.dump --dest ~/restore

`upload` sube los archivos EN EL ORDEN en que se pasan y corta en el primer
error. Sale con código distinto de 0 si algo no quedó en R2 -- a propósito: un
backup que solo existe en el disco de la instancia no cuenta como hecho.

`download` deja cada archivo con permisos 0600 (llevan el corpus y los tokens
de webhook). Nunca pisa nada fuera de --dest. Los backups de la época SQLite
(`bot-<fecha>.db` + `bot-<fecha>.flags.tar.gz`) se siguen pudiendo bajar por
nombre; `latest` elige solo entre los `purgito-*.dump[.age]`.

`upload` rechaza todo archivo que no sea un cifrado de age (cabecera
`age-encryption.org/v1`): en R2 no entran dumps en claro. `download` baja el
archivo tal cual (cifrado); descifrarlo es `age -d -i <clave-privada>` y la
clave privada no vive en el servidor (ver docs/POSTGRES.md § Backups cifrados).

Carga solo el .env del repo (no `config`): tiene que andar desde cron, sin el
resto de la configuración del bot.
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Con el runner aislado (/opt/purgito-backup) no hay .env del bot ni python-dotenv: las
# variables llegan por EnvironmentFile de systemd. Se carga el .env solo si existe y se puede
# leer (en el checkout del bot, como siempre).
try:
    from dotenv import load_dotenv  # noqa: E402

    _dotenv = os.path.join(ROOT, ".env")
    if os.access(_dotenv, os.R_OK):
        load_dotenv(_dotenv)
except ImportError:  # pragma: no cover - depende del entorno
    pass

import r2  # noqa: E402


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


AGE_MAGIC = b"age-encryption.org/v1"


def _is_age_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(AGE_MAGIC)) == AGE_MAGIC
    except OSError:
        return False


def cmd_upload(args) -> int:
    for path in args.files:
        if not os.path.isfile(path):
            _err(f"no existe {path}")
            return 1
    # El bucket de backups solo recibe archivos cifrados con age: un dump en
    # claro (corpus de mensajes y tokens de webhook) nunca sale de la máquina.
    for path in args.files:
        if not _is_age_file(path):
            _err(
                f"{path} no es un archivo cifrado con age: no se sube un backup en claro "
                "(deploy/backup_db.sh lo cifra con BACKUP_AGE_RECIPIENTS)"
            )
            return 1
    try:
        for path in args.files:
            key = r2.upload_backup_file_sync(path)
            size = os.path.getsize(path)
            print(f"OK subido {key} ({size} bytes) al bucket de backups")
    except r2.BackupError as e:
        _err(str(e))
        return 1
    return 0


def cmd_list(_args) -> int:
    try:
        backups = r2.list_backups_sync()
    except r2.BackupError as e:
        _err(str(e))
        return 1
    for key, size, modified in backups:
        print(f"{key}\t{size}\t{modified}")
    if not backups:
        print("(el bucket de backups está vacío)", file=sys.stderr)
    return 0


# Política de retención: se conservan como MÁXIMO los KEEP_LAST backups más
# recientes (el último y el anterior). La edad no cuenta: con backups semanales
# eso son, como mucho, 14 días de historia. Mismo valor que KEEP_LAST de
# deploy/backup_db.sh, que poda el disco con la misma regla.
DEFAULT_KEEP_LAST = 2
BACKUP_PREFIX = "purgito-"
BACKUP_SUFFIXES = (".dump", ".dump.age")


def valid_backups(backups, prefix: str = BACKUP_PREFIX) -> list[str]:
    """Keys de los backups válidos, del más viejo al más nuevo: `purgito-*.dump[.age]`
    con contenido. Los nombres llevan la fecha (`purgito-YYYYMMDD-HHMMSS`), así que
    el orden alfabético es el cronológico. Todo lo demás (otros archivos, objetos
    vacíos) ni cuenta como backup ni se borra."""
    return sorted(
        key
        for key, size, _modified in backups
        if key.startswith(prefix) and key.endswith(BACKUP_SUFFIXES) and size > 0
    )


def prune_plan(backups, keep: int = DEFAULT_KEEP_LAST, prefix: str = BACKUP_PREFIX):
    """(válidos, conservados, a borrar). Conserva exactamente los `keep` más
    recientes: con 1 o 2 backups no borra nada, con 3 o más borra el resto."""
    if keep < 1:
        raise ValueError("keep tiene que ser >= 1: nunca se poda hasta dejar 0 backups")
    valid = valid_backups(backups, prefix)
    kept = valid[-keep:]
    return valid, kept, valid[: len(valid) - len(kept)]


class PrunePlanError(Exception):
    """El plan de poda no es seguro (p. ej. el backup más nuevo es demasiado viejo)."""


DEFAULT_KEEP_DAILY = 7
DEFAULT_KEEP_WEEKLY = 2
DEFAULT_MAX_AGE_DAYS = 14


def backup_time(key: str):
    """Fecha (UTC) que lleva el nombre `purgito-YYYYMMDD-HHMMSS[.dump[.age]]`, o None."""
    from datetime import datetime, timezone

    m = re.match(r"purgito-(\d{8})-(\d{6})\.", key)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def prune_plan_gfs(
    backups,
    now,
    daily: int = DEFAULT_KEEP_DAILY,
    weekly: int = DEFAULT_KEEP_WEEKLY,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    prefix: str = BACKUP_PREFIX,
):
    """(válidos, conservados, a borrar) con la retención de la política de privacidad:

    - diarios: el backup más reciente de cada uno de los últimos `daily` días UTC;
    - semanales: el backup de los últimos `weekly` domingos (UTC);
    - todo con menos de `max_age_days` días: lo más viejo se borra siempre;
    - el backup más nuevo nunca se borra.

    Falla (PrunePlanError) en vez de borrar si el más nuevo ya supera `max_age_days`
    o si algún parámetro es inválido: si los backups dejaron de salir, podar sería
    quedarse sin ninguno. Los `purgito-*` con nombre sin fecha parseable no se tocan."""
    from datetime import timedelta

    if daily < 1 or weekly < 0 or max_age_days < 1:
        raise ValueError("daily >= 1, weekly >= 0 y max_age_days >= 1")
    if daily > max_age_days:
        raise ValueError("daily no puede ser mayor que max_age_days")
    valid = valid_backups(backups, prefix)
    dated = {k: backup_time(k) for k in valid}
    undated = [k for k, t in dated.items() if t is None]
    stamped = sorted((k for k, t in dated.items() if t is not None), key=dated.get)
    if not stamped:
        return valid, list(valid), []
    cap = timedelta(days=max_age_days)
    if now - dated[stamped[-1]] >= cap:
        raise PrunePlanError(
            f"el backup más nuevo ({stamped[-1]}) tiene {max_age_days} días o más: "
            "no se poda nada (¿dejaron de salir los backups?)"
        )
    kept = {stamped[-1]}
    today = now.date()
    for i in range(daily):
        day = today - timedelta(days=i)
        same = [k for k in stamped if dated[k].date() == day]
        if same:
            kept.add(same[-1])
    sundays = []
    for k in reversed(stamped):
        if dated[k].weekday() == 6 and now - dated[k] < cap:
            if all(dated[k].date() != dated[x].date() for x in sundays):
                sundays.append(k)
    kept.update(sundays[:weekly])
    victims = [k for k in stamped if k not in kept]
    return valid, sorted(kept | set(undated)), victims


LEDGER_PREFIX = "ledger/"
DEFAULT_LEDGER_MAX_AGE_DAYS = 15
LEDGER_KEEP_NEWEST = 3


def ledger_time(key: str):
    from datetime import datetime, timezone

    m = re.match(r"ledger/privacy-ledger-(\d{8}T\d{6})Z\.jsonl\.age$", key)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def prune_plan_ledger(
    backups,
    now,
    max_age_days: int = DEFAULT_LEDGER_MAX_AGE_DAYS,
    keep_newest: int = LEDGER_KEEP_NEWEST,
):
    """Instantáneas `ledger/privacy-ledger-*.jsonl.age` a borrar: las de más de
    `max_age_days` días, salvo las `keep_newest` más recientes (siempre quedan)."""
    from datetime import timedelta

    keys = sorted(
        (k for k, size, _m in backups if ledger_time(k) is not None and size > 0),
        key=ledger_time,
    )
    protected = set(keys[-keep_newest:]) if keep_newest > 0 else set()
    cap = timedelta(days=max_age_days)
    victims = [k for k in keys if k not in protected and now - ledger_time(k) >= cap]
    return keys, [k for k in keys if k not in victims], victims


def _log(msg: str) -> None:
    from datetime import datetime

    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}")


def cmd_prune(args) -> int:
    """Retención de los backups de R2 sin depender del dashboard de Cloudflare."""
    if args.keep < 1:
        _err("--keep tiene que ser >= 1: nunca se poda hasta dejar 0 backups")
        return 1
    try:
        valid, kept, victims = prune_plan(
            r2.list_backups_sync(), args.keep, args.prefix
        )
        _log(
            f"R2 PRUNE: {len(valid)} backup(s) válido(s) en R2; "
            f"política: conservar los {args.keep} más recientes"
        )
        for key in kept:
            _log(f"R2 PRUNE: conservo {key}")
        for key in victims:
            if args.apply:
                r2.delete_backup_sync(key)
                _log(f"R2 PRUNE: borrado {key}")
            else:
                _log(f"R2 PRUNE: borraría {key} (dry-run, sin --apply)")
    except r2.BackupError as e:
        _err(str(e))
        return 1
    verb = "borrados" if args.apply else "a borrar"
    _log(f"R2 PRUNE: {len(kept)} conservado(s), {len(victims)} {verb}")
    return 0


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def cmd_prune_gfs(args) -> int:
    """Retención diaria + semanal con tope de edad (política de privacidad)."""
    try:
        valid, kept, victims = prune_plan_gfs(
            r2.list_backups_sync(),
            _now(),
            args.daily,
            args.weekly,
            args.max_age_days,
            args.prefix,
        )
    except (ValueError, PrunePlanError) as e:
        _err(str(e))
        return 1
    except r2.BackupError as e:
        _err(str(e))
        return 1
    _log(
        f"R2 PRUNE-GFS: {len(valid)} backup(s) válido(s); política: {args.daily} diarios "
        f"+ {args.weekly} semanales, máximo {args.max_age_days} días"
    )
    for key in kept:
        _log(f"R2 PRUNE-GFS: conservo {key}")
    failed = 0
    for key in victims:
        if not args.apply:
            _log(f"R2 PRUNE-GFS: borraría {key} (dry-run, sin --apply)")
            continue
        try:
            r2.delete_backup_sync(key)
            _log(f"R2 PRUNE-GFS: borrado {key}")
        except r2.BackupError as e:
            _err(str(e))
            failed += 1
    _log(
        f"R2 PRUNE-GFS: {len(kept)} conservado(s), {len(victims)} a borrar, {failed} fallo(s)"
    )
    return 1 if failed else 0


def cmd_check(args) -> int:
    """Sale 1 si no hay backup válido o el más reciente tiene más de --max-age-hours."""
    from datetime import timedelta

    try:
        valid = valid_backups(r2.list_backups_sync(), args.prefix)
    except r2.BackupError as e:
        _err(str(e))
        return 1
    stamped = [(backup_time(k), k) for k in valid if backup_time(k)]
    if not stamped:
        _err("no hay ningún backup válido con fecha en el bucket de backups")
        return 1
    when, key = max(stamped)
    age = _now() - when
    print(f"último backup: {key} ({age.total_seconds() / 3600:.1f} h)")
    if age > timedelta(hours=args.max_age_hours):
        _err(f"el último backup tiene más de {args.max_age_hours} h")
        return 1
    return 0


def cmd_prune_ledger(args) -> int:
    try:
        keys, kept, victims = prune_plan_ledger(
            r2.list_backups_sync(), _now(), args.max_age_days
        )
    except r2.BackupError as e:
        _err(str(e))
        return 1
    _log(
        f"R2 PRUNE-LEDGER: {len(keys)} instantánea(s); máximo {args.max_age_days} días"
    )
    failed = 0
    for key in victims:
        if not args.apply:
            _log(f"R2 PRUNE-LEDGER: borraría {key} (dry-run, sin --apply)")
            continue
        try:
            r2.delete_backup_sync(key)
            _log(f"R2 PRUNE-LEDGER: borrado {key}")
        except r2.BackupError as e:
            _err(str(e))
            failed += 1
    return 1 if failed else 0


def cmd_preflight(args) -> int:
    """Comprobación de SOLO LECTURA antes del primer backup (o tras cambiar la
    configuración). No sube ni borra nada. Falla (1) si algo no es seguro:
      - el prefijo de la generación no es gen<N>/ con N >= 2;
      - los destinatarios age faltan, no son age1... o están revocados;
      - la retención no es coherente con la política de privacidad;
      - alguna poda tocaría un objeto de fuera de la generación vigente."""
    import backup_recipients

    problems = []
    try:
        prefix = r2.backup_prefix()
        bucket = r2.bucket_for(r2.BACKUPS)
        if not bucket:
            raise r2.BackupError("falta R2_BACKUP_BUCKET")
    except r2.BackupError as e:
        _err(str(e))
        return 1
    print(f"bucket: {bucket} | generación vigente: {prefix}")
    try:
        recipients = backup_recipients.parse_recipients(
            os.getenv("BACKUP_AGE_RECIPIENTS", "")
        )
        print(
            f"destinatarios age: {len(recipients)} "
            f"({', '.join(backup_recipients.short(x) for x in recipients)}), ninguno revocado"
        )
    except ValueError as e:
        problems.append(str(e))
    if not (1 <= args.daily <= args.max_age_days and args.weekly >= 0):
        problems.append("retención incoherente (daily/weekly/max-age-days)")
    elif args.max_age_days > 14:
        problems.append(
            f"max-age-days={args.max_age_days}: la política de privacidad promete menos de 14 días"
        )
    print(
        f"retención en R2: {args.daily} diarios + {args.weekly} domingos, "
        f"menos de {args.max_age_days} días"
    )
    try:
        everything = r2.list_all_keys_readonly_sync()
        mine = {k for k, _s, _m in r2.list_backups_sync()}
        outside = [k for k, _s, _m in everything if not k.startswith(prefix)]
        print(
            f"objetos en el bucket: {len(everything)} | de la generación vigente: "
            f"{len(mine)} | históricos (fuera del prefijo, intocables): {len(outside)}"
        )
        _valid, _kept, victims = prune_plan_gfs(
            r2.list_backups_sync(),
            _now(),
            args.daily,
            args.weekly,
            args.max_age_days,
            args.prefix,
        )
        _keys, _kl, ledger_victims = prune_plan_ledger(r2.list_backups_sync(), _now())
        planned = [prefix + k for k in [*victims, *ledger_victims]]
        stray = [k for k in planned if not k.startswith(prefix) or k in set(outside)]
        print(
            f"la poda borraría {len(planned)} objeto(s) de la generación vigente y "
            f"{len(stray)} del histórico"
        )
        if stray:
            problems.append("una poda tocaría objetos históricos")
    except (r2.BackupError, PrunePlanError) as e:
        problems.append(str(e))
    for p in problems:
        _err(p)
    print("PREFLIGHT: OK" if not problems else "PREFLIGHT: FALLÓ")
    return 1 if problems else 0


def _can_list(client, bucket: str) -> bool:
    """True si el token puede listar el bucket; False si R2 responde que no tiene
    permiso. Cualquier otro error se propaga (no es una respuesta sobre permisos)."""
    from botocore.exceptions import ClientError

    try:
        client.list_objects_v2(Bucket=bucket, MaxKeys=1)
        return True
    except ClientError as e:
        code = str(e.response.get("Error", {}).get("Code", ""))
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in ("AccessDenied", "403", "Forbidden") or status == 403:
            return False
        raise


def cmd_media_check(args) -> int:
    """Solo lectura (ListObjectsV2 de 1 elemento): el token de imágenes/GIFs (R2_ACCESS_KEY_ID)
    tiene que poder listar sus dos buckets y NO el de backups. No necesita las credenciales de
    backups, así que se puede usar antes de tenerlas."""
    client = r2.get_client()
    images, gifs, backups = (
        r2.bucket_for(r2.IMAGES),
        r2.bucket_for(r2.GIFS),
        r2.bucket_for(r2.BACKUPS),
    )
    if client is None or not images or not gifs:
        _err(
            "faltan R2_ENDPOINT_URL, R2_ACCESS_KEY_ID/SECRET o los buckets de imágenes/GIFs"
        )
        return 1
    problems = []
    for bucket, expected in ((images, True), (gifs, True), (backups, False)):
        if not bucket:
            continue
        try:
            got = _can_list(client, bucket)
        except Exception as e:  # noqa: BLE001 - se informa, no se adivina
            problems.append(f"{bucket}: error inesperado ({type(e).__name__})")
            continue
        print(
            f"token de imágenes/GIFs -> {bucket:<18} {'puede' if got else 'no puede'} listar "
            f"(esperado: {'sí' if expected else 'no'}) {'OK' if got == expected else 'FALLO'}"
        )
        if got != expected:
            problems.append(
                f"el token de imágenes/GIFs {'no puede' if not got else 'puede'} listar {bucket}"
            )
    for p in problems:
        _err(p)
    print("MEDIA-CHECK: OK" if not problems else "MEDIA-CHECK: FALLÓ")
    return 1 if problems else 0


def cmd_access_check(args) -> int:
    """Solo lectura (un ListObjectsV2 de 1 elemento por par token/bucket): comprueba que
    el token de backups SOLO ve el bucket de backups y que el de imágenes/GIFs NO ve el
    de backups. Mientras comparten acceso sale con 1 y lo dice.

    --backup-only: solo las comprobaciones del token de backups (es lo único que ve el
    runner aislado; el lado de imágenes/GIFs lo comprueba `media-check` en el bot)."""
    backups = r2.bucket_for(r2.BACKUPS)
    images = r2.bucket_for(r2.IMAGES)
    gifs = r2.bucket_for(r2.GIFS)
    bk_client = r2.get_backup_client()
    img_client = None if args.backup_only else r2.get_client()
    if (
        not backups
        or bk_client is None
        or (img_client is None and not args.backup_only)
    ):
        _err("faltan credenciales (R2_BACKUP_* y/o R2_ACCESS_KEY_ID) o buckets")
        return 1
    problems = []
    if (
        not args.backup_only
        and os.getenv("R2_BACKUP_ACCESS_KEY_ID", "").strip()
        == os.getenv("R2_ACCESS_KEY_ID", "").strip()
    ):
        problems.append(
            "R2_BACKUP_ACCESS_KEY_ID es el mismo token que R2_ACCESS_KEY_ID"
        )
    checks = [
        ("token de backups", bk_client, backups, True),
        ("token de backups", bk_client, images, False),
        ("token de backups", bk_client, gifs, False),
    ]
    if not args.backup_only:
        checks += [
            ("token de imágenes/GIFs", img_client, backups, False),
            ("token de imágenes/GIFs", img_client, images, True),
            ("token de imágenes/GIFs", img_client, gifs, True),
        ]
    for who, client, bucket, expected in checks:
        if not bucket:
            continue
        try:
            got = _can_list(client, bucket)
        except Exception as e:  # noqa: BLE001 - se informa, no se adivina
            problems.append(
                f"{who} sobre {bucket}: error inesperado ({type(e).__name__})"
            )
            continue
        verdict = "OK" if got == expected else "FALLO"
        print(
            f"{who:<24} -> {bucket:<18} {'puede' if got else 'no puede'} listar "
            f"(esperado: {'sí' if expected else 'no'}) {verdict}"
        )
        if got != expected:
            problems.append(
                f"{who} {'no puede' if not got else 'puede'} listar {bucket}"
            )
    for p in problems:
        _err(p)
    print("ACCESS-CHECK: OK" if not problems else "ACCESS-CHECK: FALLÓ")
    return 1 if problems else 0


def cmd_head(args) -> int:
    """Solo lectura: HEAD de un objeto de la generación vigente (tamaño, fecha, sha256 que
    guardó la subida)."""
    try:
        key = r2._backup_relative_key(args.name)
        client, bucket = r2._backup_client_and_bucket()
        head = client.head_object(Bucket=bucket, Key=r2.backup_prefix() + key)
    except r2.BackupError as e:
        _err(str(e))
        return 1
    except Exception as e:  # noqa: BLE001
        _err(f"no se pudo leer {args.name}: {type(e).__name__}")
        return 1
    print(f"ubicación: {bucket}/{r2.backup_prefix()}{key}")
    print(f"tamaño:    {head.get('ContentLength')} bytes")
    print(f"fecha:     {head.get('LastModified')}")
    print(f"sha256:    {(head.get('Metadata') or {}).get('sha256', '(sin metadato)')}")
    return 0


def _flags_key_for(key: str) -> str | None:
    return key[: -len(".db")] + ".flags.tar.gz" if key.endswith(".db") else None


def cmd_download(args) -> int:
    try:
        listing = {key for key, _size, _mod in r2.list_backups_sync()}
        key = args.name
        if key == "latest":
            dbs = sorted(
                k
                for k in listing
                if k.startswith("purgito-") and k.endswith((".dump", ".dump.age"))
            )
            if not dbs:
                _err("no hay ningún purgito-*.dump[.age] en el bucket de backups")
                return 1
            key = dbs[-1]
        elif key not in listing:
            _err(
                f"{key} no está en el bucket de backups (python scripts/r2_backup.py list)"
            )
            return 1
        os.makedirs(args.dest, mode=0o700, exist_ok=True)
        wanted = [key]
        flags_key = _flags_key_for(key)
        if flags_key and flags_key in listing:
            wanted.append(flags_key)
        for name in wanted:
            # basename: la key viene del bucket, pero nunca se la deja escapar de --dest
            target = os.path.join(args.dest, os.path.basename(name))
            r2.download_backup_sync(name, target)
            print(f"OK bajado {name} -> {target}")
    except r2.BackupError as e:
        _err(str(e))
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="sube archivos al bucket de backups")
    up.add_argument("files", nargs="+", help="archivos, en el orden en que se suben")
    up.set_defaults(func=cmd_upload)

    ls = sub.add_parser("list", help="lista los backups del bucket")
    ls.set_defaults(func=cmd_list)

    pr = sub.add_parser(
        "prune",
        help="deja en R2 solo los N backups más recientes (dry-run sin --apply)",
    )
    pr.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP_LAST,
        help=f"cuántos backups se conservan, los más recientes (default: {DEFAULT_KEEP_LAST})",
    )
    pr.add_argument(
        "--prefix",
        default=BACKUP_PREFIX,
        help=f"solo cuenta y poda keys con este prefijo (default: {BACKUP_PREFIX})",
    )
    pr.add_argument("--apply", action="store_true", help="borra de verdad")
    pr.set_defaults(func=cmd_prune)

    pg = sub.add_parser(
        "prune-gfs",
        help="retención diaria+semanal con tope de edad (dry-run sin --apply)",
    )
    pg.add_argument("--daily", type=int, default=DEFAULT_KEEP_DAILY)
    pg.add_argument("--weekly", type=int, default=DEFAULT_KEEP_WEEKLY)
    pg.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    pg.add_argument("--prefix", default=BACKUP_PREFIX)
    pg.add_argument("--apply", action="store_true", help="borra de verdad")
    pg.set_defaults(func=cmd_prune_gfs)

    ck = sub.add_parser(
        "check", help="falla si el último backup es más viejo que N horas"
    )
    ck.add_argument("--max-age-hours", type=int, default=36)
    ck.add_argument("--prefix", default=BACKUP_PREFIX)
    ck.set_defaults(func=cmd_check)

    pl = sub.add_parser(
        "prune-ledger",
        help="borra instantáneas del registro de eliminaciones vencidas (dry-run sin --apply)",
    )
    pl.add_argument("--max-age-days", type=int, default=DEFAULT_LEDGER_MAX_AGE_DAYS)
    pl.add_argument("--apply", action="store_true", help="borra de verdad")
    pl.set_defaults(func=cmd_prune_ledger)

    pf = sub.add_parser(
        "preflight", help="comprobación de solo lectura antes de correr backups"
    )
    pf.add_argument("--daily", type=int, default=DEFAULT_KEEP_DAILY)
    pf.add_argument("--weekly", type=int, default=DEFAULT_KEEP_WEEKLY)
    pf.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    pf.add_argument("--prefix", default=BACKUP_PREFIX)
    pf.set_defaults(func=cmd_preflight)

    mc = sub.add_parser(
        "media-check",
        help="comprueba (solo lectura) el token de imágenes/GIFs y que no ve los backups",
    )
    mc.set_defaults(func=cmd_media_check)

    ac = sub.add_parser(
        "access-check",
        help="comprueba (solo lectura) que los tokens de R2 están separados",
    )
    ac.add_argument(
        "--backup-only",
        action="store_true",
        help="solo el token de backups (no usa R2_ACCESS_KEY_ID)",
    )
    ac.set_defaults(func=cmd_access_check)

    hd = sub.add_parser(
        "head",
        help="tamaño y sha256 (metadato de la subida) de un objeto de la generación vigente",
    )
    hd.add_argument(
        "name", help="key relativa, p. ej. purgito-20261105-203045.dump.age"
    )
    hd.set_defaults(func=cmd_head)

    dl = sub.add_parser("download", help="baja un backup (y su tar de flags)")
    dl.add_argument("name", help="key del backup, o 'latest' para el más reciente")
    dl.add_argument("--dest", default=".", help="carpeta de destino (default: .)")
    dl.set_defaults(func=cmd_download)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
