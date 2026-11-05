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

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import pgsync  # noqa: E402
import privacy_ledger  # noqa: E402
import r2  # noqa: E402

AGE_PUBKEY = re.compile(r"^age1[a-z0-9]{50,}$")
KEEP_LOCAL = 3


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _log(msg: str) -> None:
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}")


def parse_recipients(raw: str) -> list[str]:
    recipients = raw.replace(",", " ").split()
    if not recipients:
        raise ValueError(
            "falta BACKUP_AGE_RECIPIENTS: nunca se exporta el registro en claro"
        )
    for r in recipients:
        if not AGE_PUBKEY.match(r):
            raise ValueError("BACKUP_AGE_RECIPIENTS: una clave no parece age1...")
    return recipients


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


def run(args) -> int:
    now = datetime.now(timezone.utc)
    conn = pgsync.connect(os.getenv("DATABASE_URL"))
    try:
        records = privacy_ledger.build_snapshot(conn, now)
    finally:
        conn.close()
    text = privacy_ledger.dumps(records)
    privacy_ledger.loads(text)  # lo que se exporta tiene que poder leerse de vuelta
    counts = records[-1]["counts"]
    _log(
        f"LEDGER: {counts['user_tombstone']} lápida(s) de usuario, "
        f"{counts['guild_tombstone']} de servidor, {counts['exclusion']} exclusión(es)"
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
