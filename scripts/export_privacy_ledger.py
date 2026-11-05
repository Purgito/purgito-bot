"""Exporta, cifrada con age, la instantánea del registro de eliminaciones y exclusiones.

Es la copia del registro de privacidad que sobrevive a perder la base principal y el
servidor: se sube al bucket PRIVADO de backups (prefijo `ledger/`) con el token de
backups. Qué contiene y cuánto dura cada cosa: src/privacy_ledger.py y docs/PRIVACY.md.

    .venv/bin/python scripts/export_privacy_ledger.py            # exporta y sube
    .venv/bin/python scripts/export_privacy_ledger.py --dry-run  # solo cuenta, no escribe nada
    .venv/bin/python scripts/export_privacy_ledger.py --no-upload

Pensado para cron (cada hora, ver docs/POSTGRES.md § Registro de eliminaciones).
Nunca escribe la instantánea en claro fuera de un temporal 0600 que borra siempre, y
se niega a exportar sin BACKUP_AGE_RECIPIENTS. Sale con código distinto de 0 si algo
falla, y avisa a BACKUP_ALERT_WEBHOOK si está definido (sin datos en el mensaje).

Carga solo el .env del repo (no `config`), como r2_backup.py: tiene que andar desde cron.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

try:  # el runner aislado no tiene python-dotenv ni .env: el entorno lo da systemd
    from dotenv import load_dotenv  # noqa: E402

    if os.access(os.path.join(ROOT, ".env"), os.R_OK):
        load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:  # pragma: no cover - depende del entorno
    pass

import backup_recipients  # noqa: E402
import privacy_ledger  # noqa: E402
import r2  # noqa: E402

KEEP_LOCAL = 3


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _log(msg: str) -> None:
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}")


def parse_recipients(raw: str) -> list[str]:
    return backup_recipients.parse_recipients(raw)


def encrypt(plain_path: str, out_path: str, recipients: list[str], age: str) -> None:
    cmd = [age]
    for r in recipients:
        cmd += ["-r", r]
    cmd += ["-o", out_path, plain_path]
    subprocess.run(cmd, check=True, capture_output=True)
    with open(out_path, "rb") as f:
        head = f.read(4096)
    if not head.startswith(b"age-encryption.org/v1") or head.count(
        b"-> X25519 "
    ) != len(recipients):
        raise RuntimeError("el archivo cifrado no pasó la verificación de cabecera age")


def prune_local(directory: str, keep: int = KEEP_LOCAL) -> None:
    names = sorted(
        n
        for n in os.listdir(directory)
        if n.startswith("privacy-ledger-") and n.endswith(".jsonl.age")
    )
    for n in names[:-keep] if keep > 0 else names:
        os.unlink(os.path.join(directory, n))


def _alert() -> None:
    url = os.getenv("BACKUP_ALERT_WEBHOOK", "").strip()
    if not url:
        return
    import json
    import urllib.request

    body = json.dumps(
        {"content": "⚠️ Falló la exportación del registro de privacidad de Purgito."}
    ).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def _query(sql: str) -> list[list[str]]:
    """Filas de una consulta de SOLO LECTURA con `psql --csv` (sin drivers de Python).
    Conexión: DATABASE_URL si está; si no, el entorno libpq (PGUSER/PGHOST/PGDATABASE), que
    es como se conecta el runner aislado (rol de solo lectura, socket local, sin contraseña)."""
    cmd = ["psql", "-X", "-q", "--csv", "-t", "-v", "ON_ERROR_STOP=1"]
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        cmd.append(url)
    elif not (os.getenv("PGUSER") and os.getenv("PGDATABASE")):
        raise RuntimeError("falta DATABASE_URL o PGUSER+PGDATABASE")
    cmd += ["-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        # psql puede nombrar la tabla o el usuario; nunca la contraseña (no viaja en argv)
        raise RuntimeError(f"psql falló: {proc.stderr.strip().splitlines()[-1][:160]}")
    import csv
    import io

    return [row for row in csv.reader(io.StringIO(proc.stdout)) if row]


def run(args) -> int:
    now = datetime.now(timezone.utc)
    now_text = now.strftime("%Y-%m-%d %H:%M:%S")
    records = privacy_ledger.snapshot_from_rows(
        _query(privacy_ledger.USERS_SQL.format(now=f"'{now_text}'")),
        _query(privacy_ledger.GUILDS_SQL.format(now=f"'{now_text}'")),
        _query(privacy_ledger.EXCLUSIONS_SQL),
        now,
        _query(privacy_ledger.REQUESTS_SQL),
    )
    text = privacy_ledger.dumps(records)
    privacy_ledger.loads(text)  # lo que se exporta tiene que poder leerse de vuelta
    counts = records[-1]["counts"]
    _log(
        f"LEDGER: {counts['user_tombstone']} lápida(s) de usuario, "
        f"{counts['guild_tombstone']} de servidor, {counts['exclusion']} exclusión(es), "
        f"{counts['deletion_request']} solicitud(es) abierta(s)"
    )
    if args.dry_run:
        return 0
    recipients = parse_recipients(os.getenv("BACKUP_AGE_RECIPIENTS", ""))
    backup_dir = os.getenv("BACKUP_DIR") or os.path.join(
        os.path.expanduser("~"), "purgito-bot-backups"
    )
    ledger_dir = os.path.join(backup_dir, "ledger")
    os.makedirs(ledger_dir, mode=0o700, exist_ok=True)
    os.chmod(ledger_dir, 0o700)
    stamp = now.strftime("%Y%m%dT%H%M%S")
    name = f"privacy-ledger-{stamp}Z.jsonl.age"
    dest = os.path.join(ledger_dir, name)
    fd, plain = tempfile.mkstemp(prefix=".ledger-", suffix=".plain", dir=ledger_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        encrypt(plain, dest + ".partial", recipients, args.age)
        os.replace(dest + ".partial", dest)
    finally:
        if os.path.exists(plain):
            os.unlink(plain)
        if os.path.exists(dest + ".partial"):
            os.unlink(dest + ".partial")
    os.chmod(dest, 0o600)
    _log(f"LEDGER: cifrado {name} ({os.path.getsize(dest)} bytes)")
    prune_local(ledger_dir)
    if args.no_upload:
        return 0
    key = r2.upload_backup_file_sync(dest, key=f"ledger/{name}")
    _log(f"LEDGER: subido {key} a R2 (tamaño verificado)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--dry-run", action="store_true", help="solo cuenta; no escribe ni sube"
    )
    ap.add_argument("--no-upload", action="store_true", help="solo deja la copia local")
    ap.add_argument("--age", default=os.getenv("AGE", "age"), help="binario de age")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except Exception as e:
        detail = re.sub(r"://[^@\s]+@", "://<oculto>@", str(e))
        _err(f"{type(e).__name__}: {detail}")
        _alert()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
