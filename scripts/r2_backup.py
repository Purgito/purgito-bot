"""Sube, lista y baja backups de bot.db del bucket PRIVADO de R2 (R2_BACKUP_BUCKET).

Lo invoca deploy/backup_db.sh después de generar y verificar el backup local; a
mano sirve para traer un backup a una instancia nueva (ver DEPLOY.md § "Restaurar
desde un backup"). No lo usa el bot.

    python scripts/r2_backup.py upload bot-X.flags.tar.gz bot-X.db
    python scripts/r2_backup.py list
    python scripts/r2_backup.py download latest --dest ~/restore
    python scripts/r2_backup.py download bot-20260812-031700.db --dest ~/restore

`upload` sube los archivos EN EL ORDEN en que se pasan y corta en el primer
error: backup_db.sh pasa el tar de flags antes que la base, así que un
`bot-<fecha>.db` en el bucket siempre tiene su `bot-<fecha>.flags.tar.gz` al
lado. Sale con código distinto de 0 si algo no quedó en R2 -- a propósito: un
backup que solo existe en el disco de la instancia no cuenta como hecho.

`download` deja cada archivo con permisos 0600 (llevan lo mismo que bot.db) y,
al bajar una base, baja también su tar de flags si está en el bucket. Nunca pisa
nada fuera de --dest.

Carga solo el .env del repo (no `config`): tiene que andar desde cron, sin el
resto de la configuración del bot.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import r2  # noqa: E402


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def cmd_upload(args) -> int:
    for path in args.files:
        if not os.path.isfile(path):
            _err(f"no existe {path}")
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


def _flags_key_for(key: str) -> str | None:
    return key[: -len(".db")] + ".flags.tar.gz" if key.endswith(".db") else None


def cmd_download(args) -> int:
    try:
        listing = {key for key, _size, _mod in r2.list_backups_sync()}
        key = args.name
        if key == "latest":
            dbs = sorted(
                k for k in listing if k.startswith("bot-") and k.endswith(".db")
            )
            if not dbs:
                _err("no hay ningún bot-*.db en el bucket de backups")
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

    dl = sub.add_parser("download", help="baja un backup (y su tar de flags)")
    dl.add_argument("name", help="key del backup, o 'latest' para el más reciente")
    dl.add_argument("--dest", default=".", help="carpeta de destino (default: .)")
    dl.set_defaults(func=cmd_download)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
