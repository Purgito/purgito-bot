"""Redacción de secretos: última barrera antes de que algo llegue a un log.

Dos capas, ambas aplicadas al TEXTO ya formateado (así cubre también
tracebacks y excepciones con el secreto dentro del mensaje):

1. Valores conocidos: los secretos reales de config/entorno, por coincidencia
   exacta (no importa el formato en que aparezcan).
2. Patrones: formas reconocibles de credenciales (token de Discord, URL de
   PostgreSQL con contraseña, Bearer, clave privada age, cookie de sesión).

Y a nivel de campo, `sanitize_fields` descarta o enmascara claves sensibles y
las que podrían traer contenido de usuarios (mensajes, corpus).
"""

from __future__ import annotations

import logging
import os
import re

REDACTED = "[REDACTED]"

# Variables de entorno cuyo VALOR nunca debe aparecer en un log.
_SECRET_ENV_NAMES = (
    "DISCORD_TOKEN",
    "DISCORD_CLIENT_SECRET",
    "SESSION_SECRET",
    "POLAR_ACCESS_TOKEN",
    "POLAR_WEBHOOK_SECRET",
    "GROQ_API_KEY",
    "TWITCH_CLIENT_SECRET",
    "R2_SECRET_ACCESS_KEY",
    "R2_IMAGES_SECRET_ACCESS_KEY",
    "R2_GIFS_SECRET_ACCESS_KEY",
    "R2_BACKUP_SECRET_ACCESS_KEY",
    "OBSERVABILITY_TOKEN",
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "BACKUP_AGE_IDENTITY",
)
# Un valor demasiado corto ("1", "dev") redactaría medio log sin proteger nada.
_MIN_SECRET_LEN = 8

_extra_secrets: set[str] = set()

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # postgresql://user:password@host/db  ->  conserva usuario y host.
    (
        re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s@]+:)[^@\s]+(@)", re.I),
        r"\1" + REDACTED + r"\2",
    ),
    # Token de bot de Discord: base64(id).timestamp.hmac
    (
        re.compile(r"\b[MNO][A-Za-z\d_-]{23,27}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}\b"),
        REDACTED,
    ),
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    (re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]+"), REDACTED),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.S,
        ),
        REDACTED,
    ),
    # Cookie de sesión y cabeceras de auth que se cuelan en un repr/dict.
    (re.compile(r"(PURGITO_SESSION=)[^;\s'\"]+"), r"\1" + REDACTED),
    (
        re.compile(
            r"(?i)((?:access_token|refresh_token|client_secret|password|passwd|"
            r"authorization|secret|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&}]+"
        ),
        r"\1" + REDACTED,
    ),
)

# Claves de campo de evento que jamás se guardan con su valor. Lo de mensajes
# y corpus: estos eventos no llevan contenido de usuarios (ver SECURITY_EVENTS.md).
_SENSITIVE_KEY = re.compile(
    r"(token|secret|password|passwd|cookie|authorization|api[_-]?key|private|"
    r"credential|dsn|database_url|session_id|signature)",
    re.I,
)
_CONTENT_KEY = re.compile(
    r"^(content|message_content|text|body|corpus|clean_content|payload|prompt)$", re.I
)


def register_secret(value: str | None) -> None:
    """Agrega un secreto en tiempo de ejecución (p. ej. uno generado al vuelo)."""
    if value and len(value) >= _MIN_SECRET_LEN:
        _extra_secrets.add(value)


def _known_secrets() -> list[str]:
    values = {
        v
        for name in _SECRET_ENV_NAMES
        if (v := os.environ.get(name)) and len(v) >= _MIN_SECRET_LEN
    }
    values |= _extra_secrets
    # Más largos primero: si uno contiene a otro, se enmascara el entero.
    return sorted(values, key=len, reverse=True)


def scrub(text: str) -> str:
    """Devuelve `text` sin secretos conocidos ni credenciales reconocibles."""
    if not text:
        return text
    for secret in _known_secrets():
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def sanitize_value(value):
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return sanitize_fields(value)
    if isinstance(value, (list, tuple, set)):
        return [sanitize_value(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return scrub(str(value))


def sanitize_fields(fields: dict) -> dict:
    """Copia de `fields` con claves sensibles enmascaradas, claves de contenido
    descartadas y los valores restantes pasados por `scrub`."""
    out: dict = {}
    for key, value in fields.items():
        skey = str(key)
        if _CONTENT_KEY.match(skey):
            continue
        if _SENSITIVE_KEY.search(skey):
            out[skey] = REDACTED
            continue
        out[skey] = sanitize_value(value)
    return out


class RedactingFormatter(logging.Formatter):
    """Formatter que pasa el texto final (mensaje + traceback) por `scrub`."""

    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))
