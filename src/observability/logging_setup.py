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
import re
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler

from . import events, redaction

TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
# Tope de disco chico (5 MB por segmento) y, sobre todo, tope de EDAD: los registros de eventos,
# de seguridad y de texto llevan, entre otros, el identificador derivado de la IP (`source_id`),
# que es un dato personal; ningún segmento sobrevive más de LOG_RETENTION_DAYS (+ lo que dure el
# segmento en curso, como mucho un día). Ver docs/PRIVACY.md.
JSONL_MAX_BYTES = 5_000_000
DEFAULT_LOG_RETENTION_DAYS = 30
_SEGMENT_SUFFIX = "%Y-%m-%d_%H%M%S"
_SEGMENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{6})(-\d+)?$")


def log_retention_days() -> int:
    """LOG_RETENTION_DAYS del entorno (entero >= 1) o el valor por defecto."""
    raw = os.environ.get("LOG_RETENTION_DAYS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) >= 1 else DEFAULT_LOG_RETENTION_DAYS


class RetainedFileHandler(TimedRotatingFileHandler):
    """Archivo que rota a medianoche UTC (o al llegar a `max_bytes`) y borra los segmentos
    con más de `retention_days` días. A diferencia de `RotatingFileHandler`, el plazo de
    conservación lo fija el tiempo y no el volumen de logs."""

    def __init__(
        self, path: str, retention_days: int, max_bytes: int = JSONL_MAX_BYTES
    ):
        super().__init__(
            path, when="midnight", utc=True, backupCount=1_000_000, encoding="utf-8"
        )
        self.retention_days = retention_days
        self.max_bytes = max_bytes
        self.suffix = _SEGMENT_SUFFIX
        self.extMatch = _SEGMENT_RE
        self.namer = self._unique_name

    @staticmethod
    def _unique_name(name: str) -> str:
        if not os.path.exists(name):
            return name
        n = 1
        while os.path.exists(f"{name}-{n}"):
            n += 1
        return f"{name}-{n}"

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if super().shouldRollover(record):
            return True
        if self.max_bytes and self.stream is not None:
            self.stream.seek(0, os.SEEK_END)
            return self.stream.tell() + len(self.format(record)) + 1 >= self.max_bytes
        return False

    def getFilesToDelete(self) -> list[str]:
        dirname, base = os.path.split(self.baseFilename)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        out = []
        for name in os.listdir(dirname):
            m = (
                _SEGMENT_RE.match(name[len(base) + 1 :])
                if name.startswith(base + ".")
                else None
            )
            if not m:
                continue
            when = datetime.strptime(m.group(1), _SEGMENT_SUFFIX).replace(
                tzinfo=timezone.utc
            )
            if when < cutoff:
                out.append(os.path.join(dirname, name))
        return out


_LINE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")
_JSON_TS = re.compile(r'"timestamp": "(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})')


def _line_time(line: str) -> datetime | None:
    m = _LINE_TS.match(line) or _JSON_TS.search(line[:400])
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def trim_old_lines(path: str, retention_days: int, now: datetime | None = None) -> int:
    """Quita de un log heredado (aún sin segmentos por fecha) las líneas más viejas que el
    plazo; las que no traen fecha (continuación de un traceback) se conservan. Devuelve
    cuántas quitó. Solo se llama antes de abrir el archivo para escribir."""
    if not os.path.isfile(path):
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    keep, dropped = [], 0
    for line in lines:
        when = _line_time(line)
        if when is not None and when < cutoff:
            dropped += 1
        else:
            keep.append(line)
    if dropped:
        tmp = path + ".trim"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(keep)
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
        os.replace(tmp, path)
    return dropped


def trim_legacy_logs(path: str, retention_days: int) -> None:
    """`path` y sus copias numeradas del esquema anterior (`path.1`, `path.2`, …)."""
    trim_old_lines(path, retention_days)
    dirname, base = os.path.split(path)
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    for name in os.listdir(dirname or "."):
        if name.startswith(base + ".") and name[len(base) + 1 :].isdigit():
            full = os.path.join(dirname, name)
            if os.path.getmtime(full) < cutoff:
                os.unlink(full)
            else:
                trim_old_lines(full, retention_days)


class QueryStringFilter(logging.Filter):
    """Quita las query strings del access log de aiohttp (`aiohttp.access`): la del callback
    OAuth lleva `?code=…&state=…` y la del Referer puede llevar parámetros del usuario."""

    _QUERY = re.compile(r'\?[^\s"]*')

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "aiohttp.access" and isinstance(record.msg, str):
            record.msg = self._QUERY.sub("?-", record.msg)
        return True


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
    days = log_retention_days()
    bot_log = os.path.join(data_dir, "bot.log")
    trim_legacy_logs(
        bot_log, days
    )  # antes de abrirlo: lo heredado también respeta el plazo
    file_handler = RetainedFileHandler(bot_log, days)
    file_handler.setFormatter(text_fmt)
    file_handler.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(text_fmt)
    stream_handler.setLevel(logging.INFO)
    for handler in (file_handler, stream_handler):
        handler.addFilter(QueryStringFilter())
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
    days = log_retention_days()
    for category, path in event_paths(data_dir).items():
        trim_legacy_logs(path, days)  # antes de abrirlo para escribir
        handler = RetainedFileHandler(path, days)
        handler.setFormatter(JsonEventFormatter())
        handler.addFilter(_CategoryFilter(category))
        event_logger.addHandler(handler)
    event_logger._purgito_files = True  # type: ignore[attr-defined]
