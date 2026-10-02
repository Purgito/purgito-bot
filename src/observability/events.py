"""Modelo de eventos estructurados de Purgito.

Un evento es un dict plano y estable (``schema`` = 1) con:

  timestamp, event_id, event_type, category, severity, service, environment,
  host, message                      -> siempre
  guild_id, user_id, channel_id, request_id, endpoint, method, status,
  duration_ms, error_type, result, reason, source_id, rule_id
                                     -> cuando corresponde (top-level)
  data                               -> cualquier otro campo, anidado

Los campos nuevos van a ``data`` primero y se promueven a top-level solo si
hacen falta en todos lados: así un consumidor (Vector, un SIEM) nunca se rompe
por un campo que no conocía.

``log_event`` NUNCA lanza en producción: observabilidad no puede tumbar el bot.
En tests ``set_strict(True)`` convierte los tipos no registrados en error.

Los eventos NO llevan contenido de mensajes ni corpus (ver redaction.py).
"""

from __future__ import annotations

import collections
import contextlib
import contextvars
import hashlib
import hmac
import logging
import os
import re
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

from . import redaction

SCHEMA_VERSION = 1
SERVICE = "purgito-bot"

SEVERITIES = ("debug", "info", "warning", "error", "critical")
_SEVERITY_LEVEL = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}
_SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITIES)}

CATEGORY_APP = "app"
CATEGORY_SECURITY = "security"

EVENT_LOGGER_NAME = "purgito.event"
_event_log = logging.getLogger(EVENT_LOGGER_NAME)


@dataclass(frozen=True)
class EventSpec:
    category: str
    severity: str
    description: str


def _app(severity: str, description: str) -> EventSpec:
    return EventSpec(CATEGORY_APP, severity, description)


def _sec(severity: str, description: str) -> EventSpec:
    return EventSpec(CATEGORY_SECURITY, severity, description)


# Taxonomía: SOLO tipos que algún punto del código emite de verdad. Los
# prefijos system/service/discord/database/auth/permission/webhook/rate_limit/
# security/deployment están reservados; sumar un tipo = sumarlo acá y emitirlo.
EVENT_TYPES: dict[str, EventSpec] = {
    # service.* -- ciclo de vida del proceso
    "service.started": _app("info", "El proceso terminó de arrancar"),
    "service.stopping": _app("info", "Apagado intencional en curso (SIGTERM/SIGINT)"),
    "service.stopped": _app("info", "Apagado intencional completado"),
    "service.crash_detected": _app(
        "error", "El arranque encontró que el proceso anterior no cerró limpio"
    ),
    "service.heartbeat": _app("debug", "Latido periódico del proceso"),
    # system.*
    "system.unhandled_exception": _app(
        "error", "Excepción no atajada en un handler HTTP"
    ),
    "system.background_task_failed": _app("error", "Falló una tarea en segundo plano"),
    # discord.*
    "discord.ready": _app("info", "Conectado a Discord (on_ready)"),
    "discord.disconnected": _app("warning", "Se perdió la conexión con Discord"),
    "discord.command_error": _app("error", "Un comando terminó con error inesperado"),
    # database.*
    "database.connection_failed": _app("error", "No se pudo conectar a PostgreSQL"),
    "database.health_failed": _app("error", "El chequeo de readiness de la base falló"),
    # auth.* (seguridad)
    "auth.login_success": _sec("info", "Login OAuth2 completado"),
    "auth.login_failure": _sec("warning", "Login OAuth2 fallido"),
    "auth.logout": _sec("info", "Logout; sesión revocada"),
    "auth.session_revoked": _sec("warning", "Se usó una sesión ya revocada"),
    # permission.* (seguridad)
    "permission.denied": _sec("warning", "Acceso denegado a un recurso"),
    # webhook.* (seguridad)
    "webhook.signature_invalid": _sec("warning", "Webhook con firma inválida"),
    "webhook.rejected": _sec("warning", "Webhook rechazado (config o payload)"),
    # rate_limit.* (seguridad)
    "rate_limit.triggered": _sec("warning", "Un cliente superó un rate limit"),
    # security.*
    "security.admin_action": _sec(
        "info", "Acción administrativa sensible en el dashboard"
    ),
    "security.alert_opened": _sec("warning", "Una regla de detección abrió una alerta"),
    # deployment.*
    "deployment.runbook_executed": _app("info", "Se ejecutó un runbook allowlisted"),
}

# Campos que viven en el top-level del evento (además de los obligatorios).
STANDARD_FIELDS = frozenset(
    {
        "guild_id",
        "user_id",
        "channel_id",
        "request_id",
        "endpoint",
        "method",
        "status",
        "duration_ms",
        "error_type",
        "result",
        "reason",
        "source_id",
        "rule_id",
    }
)
REQUIRED_FIELDS = (
    "schema",
    "timestamp",
    "event_id",
    "event_type",
    "category",
    "severity",
    "service",
    "environment",
    "host",
    "message",
)

_strict = False
_HOST = socket.gethostname()


def set_strict(value: bool) -> None:
    global _strict
    _strict = value


def environment() -> str:
    return os.environ.get("PURGITO_ENV", "production").strip() or "production"


# ---------------- Correlación ----------------

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "purgito_request_id", default=None
)
_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def accept_request_id(candidate: str | None) -> str:
    """Un X-Request-ID entrante solo se respeta si tiene forma segura (evita
    inyección de saltos de línea/ruido en los logs); si no, se genera uno."""
    if candidate and _REQUEST_ID_OK.match(candidate):
        return candidate
    return new_request_id()


def get_request_id() -> str | None:
    return _request_id.get()


@contextlib.contextmanager
def request_scope(request_id: str | None = None) -> Iterator[str]:
    rid = request_id or new_request_id()
    token = _request_id.set(rid)
    try:
        yield rid
    finally:
        _request_id.reset(token)


def bind_request_id(request_id: str) -> contextvars.Token:
    return _request_id.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id.reset(token)


def source_id(ip: str | None) -> str | None:
    """Identificador estable pero NO reversible de un origen. Permite agrupar
    "10 permission.denied desde el mismo origen" sin guardar la IP cruda."""
    if not ip:
        return None
    key = (os.environ.get("SESSION_SECRET") or "purgito").encode()
    return hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()[:12]


# ---------------- Buffer en memoria + listeners ----------------

_BUFFER_SIZE = 1000
_buffer: collections.deque[dict] = collections.deque(maxlen=_BUFFER_SIZE)
_buffer_lock = threading.Lock()
_listeners: list[Callable[[dict], None]] = []


def add_listener(fn: Callable[[dict], None]) -> None:
    if fn not in _listeners:
        _listeners.append(fn)


def remove_listener(fn: Callable[[dict], None]) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def recent_events(
    limit: int = 100, *, min_severity: str = "debug", category: str | None = None
) -> list[dict]:
    floor = _SEVERITY_RANK[min_severity]
    with _buffer_lock:
        items = list(_buffer)
    out = [
        e
        for e in items
        if _SEVERITY_RANK.get(e["severity"], 0) >= floor
        and (category is None or e["category"] == category)
    ]
    return out[-limit:]


def clear_buffer() -> None:
    with _buffer_lock:
        _buffer.clear()


# ---------------- Emisión ----------------


def build_event(
    event_type: str,
    *,
    severity: str | None = None,
    message: str | None = None,
    **fields,
) -> dict:
    spec = EVENT_TYPES.get(event_type)
    if spec is None and _strict:
        raise ValueError(f"event_type no registrado: {event_type!r}")
    sev = severity or (spec.severity if spec else "info")
    if sev not in _SEVERITY_RANK:
        if _strict:
            raise ValueError(f"severity inválida: {sev!r}")
        sev = "info"

    fields = redaction.sanitize_fields(fields)
    event: dict = {
        "schema": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "event_id": uuid.uuid4().hex[:16],
        "event_type": event_type,
        "category": spec.category if spec else CATEGORY_APP,
        "severity": sev,
        "service": SERVICE,
        "environment": environment(),
        "host": _HOST,
        "message": redaction.scrub(
            message or (spec.description if spec else event_type)
        ),
    }
    if "request_id" not in fields and (rid := get_request_id()):
        fields["request_id"] = rid
    data: dict = {}
    for key, value in fields.items():
        if value is None:
            continue
        if key in STANDARD_FIELDS:
            event[key] = value
        else:
            data[key] = value
    if spec is None:
        data["schema_warning"] = "unregistered_event_type"
    if data:
        event["data"] = data
    return event


def human_line(event: dict) -> str:
    """Línea legible para journald/bot.log: ``event=<tipo> k=v ... msg``."""
    parts = [f"event={event['event_type']}"]
    for key in sorted(STANDARD_FIELDS):
        if key in event:
            parts.append(f"{key}={event[key]}")
    for key, value in event.get("data", {}).items():
        parts.append(f"{key}={value}")
    return " ".join(parts) + f" | {event['message']}"


def log_event(
    event_type: str,
    *,
    severity: str | None = None,
    message: str | None = None,
    **fields,
) -> dict | None:
    """Registra un evento estructurado. Devuelve el evento (o None si falló)."""
    try:
        event = build_event(event_type, severity=severity, message=message, **fields)
    except ValueError:
        raise
    except Exception:  # observabilidad nunca debe romper al llamador
        logging.getLogger(__name__).exception("No se pudo construir el evento")
        return None
    try:
        with _buffer_lock:
            _buffer.append(event)
        _event_log.log(
            _SEVERITY_LEVEL[event["severity"]],
            human_line(event),
            extra={"purgito_event": event},
        )
        for listener in list(_listeners):
            try:
                listener(event)
            except Exception:
                logging.getLogger(__name__).exception("Listener de eventos falló")
    except Exception:
        logging.getLogger(__name__).exception("No se pudo emitir el evento")
    return event


def validate_event(event: dict) -> list[str]:
    """Lista de problemas del evento contra el schema (vacía = válido)."""
    problems = [f"falta {name}" for name in REQUIRED_FIELDS if name not in event]
    if event.get("schema") != SCHEMA_VERSION:
        problems.append("schema desconocido")
    if event.get("severity") not in _SEVERITY_RANK:
        problems.append("severity inválida")
    if event.get("category") not in (CATEGORY_APP, CATEGORY_SECURITY):
        problems.append("category inválida")
    ts = str(event.get("timestamp", ""))
    if not ts.endswith("Z"):
        problems.append("timestamp no es UTC (debe terminar en Z)")
    allowed = set(REQUIRED_FIELDS) | STANDARD_FIELDS | {"data"}
    problems += [f"campo fuera de schema: {k}" for k in event if k not in allowed]
    return problems
