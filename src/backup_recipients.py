"""Validación de las claves públicas age con las que se cifran los backups.

Un backup cifrado con una clave cuya privada no existe o no se controla no sirve y es
peor que no tenerlo (parece hecho). Por eso, además del formato, se rechazan las claves
revocadas de deploy/age-revoked-recipients.txt (la misma lista que lee backup_db.sh).
"""

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVOKED_FILE = os.path.join(_ROOT, "deploy", "age-revoked-recipients.txt")
_PUBKEY = re.compile(r"^age1[a-z0-9]{50,}$")


def load_revoked(path: str = REVOKED_FILE) -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return {
                line.strip()
                for line in f
                if line.strip() and not line.lstrip().startswith("#")
            }
    except OSError as e:
        # Sin la lista no se puede garantizar nada: se niega, no se asume vacía.
        raise ValueError(f"no se pudo leer {path}: {e}") from e


def parse_recipients(raw: str, revoked: set[str] | None = None) -> list[str]:
    """Lista de destinatarios válidos, sin repetidos. ValueError si no hay ninguno,
    si alguno no parece age1... o si alguno está revocado."""
    recipients = list(dict.fromkeys((raw or "").replace(",", " ").split()))
    if not recipients:
        raise ValueError(
            "falta BACKUP_AGE_RECIPIENTS: nunca se cifra con nada ni se sube en claro"
        )
    revoked = load_revoked() if revoked is None else revoked
    for r in recipients:
        if not _PUBKEY.match(r):
            raise ValueError("BACKUP_AGE_RECIPIENTS: una clave no parece age1...")
        if r in revoked:
            raise ValueError(
                "BACKUP_AGE_RECIPIENTS contiene una clave REVOCADA "
                "(deploy/age-revoked-recipients.txt): su clave privada no existe"
            )
    return recipients


def short(recipient: str) -> str:
    """Forma corta para mostrar en logs (la clave es pública, pero no hace falta entera)."""
    return f"{recipient[:10]}…{recipient[-6:]}"
