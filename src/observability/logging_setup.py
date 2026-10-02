"""Configuración de logging de Purgito.

- bot.log y stderr: texto legible (mismo formato de siempre), pasado por la
  redacción de secretos.
- data/events.jsonl: eventos de aplicación, un JSON por línea.
- data/security.jsonl: eventos de seguridad (separados a propósito).

Los eventos también salen en texto legible por el logger raíz (journald y
bot.log) como ``event=<tipo> ...``; el JSON es la fuente canónica para Vector.
"""

from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler

from . import events, redaction

TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
# 5 MB x (1 + 3 backups) por archivo: tope de disco fijo y chico.
JSONL_MAX_BYTES = 5_000_000
JSONL_BACKUPS = 3


class JsonEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "purgito_event", None)
        if event is None:
            return ""
        # Los campos ya están sanitizados; scrub final por si un valor trae
        # un secreto conocido dentro de un texto más largo.
        return redaction.scrub(json.dumps(event, ensure_ascii=False, sort_keys=True))


class _CategoryFilter(logging.Filter):
    def __init__(self, category: str) -> None:
        super().__init__()
        self.category = category

    def filter(self, record: logging.LogRecord) -> bool:
        event = getattr(record, "purgito_event", None)
        return event is not None and event.get("category") == self.category


def event_paths(data_dir: str) -> dict[str, str]:
    return {
        events.CATEGORY_APP: os.path.join(data_dir, "events.jsonl"),
        events.CATEGORY_SECURITY: os.path.join(data_dir, "security.jsonl"),
    }


def setup_text_logging(data_dir: str) -> logging.Logger:
    """bot.log + stderr, en texto legible y con secretos redactados. Idempotente.
    Va a nivel de import en bot.py (igual que antes), por eso NO toca los JSONL."""
    os.makedirs(data_dir, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_purgito_configured", False):
        return logging.getLogger("bot")

    text_fmt = redaction.RedactingFormatter(TEXT_FORMAT)
    file_handler = RotatingFileHandler(
        os.path.join(data_dir, "bot.log"),
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(text_fmt)
    file_handler.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(text_fmt)
    stream_handler.setLevel(logging.INFO)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    root._purgito_configured = True  # type: ignore[attr-defined]
    return logging.getLogger("bot")


def setup_event_files(data_dir: str) -> None:
    """Handlers JSONL de eventos. Solo en el arranque real del bot (no al
    importar): así los tests que importan bot.py no escriben en data/."""
    event_logger = logging.getLogger(events.EVENT_LOGGER_NAME)
    if getattr(event_logger, "_purgito_files", False):
        return
    os.makedirs(data_dir, exist_ok=True)
    event_logger.setLevel(logging.DEBUG)  # el heartbeat va a debug
    # Los root handlers están en INFO: los eventos debug (heartbeat) solo
    # llegan al JSONL; el resto también sale en texto por journald/bot.log.
    for category, path in event_paths(data_dir).items():
        handler = RotatingFileHandler(
            path, maxBytes=JSONL_MAX_BYTES, backupCount=JSONL_BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(JsonEventFormatter())
        handler.addFilter(_CategoryFilter(category))
        event_logger.addHandler(handler)
    event_logger._purgito_files = True  # type: ignore[attr-defined]
