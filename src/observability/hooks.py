"""Puntos de enganche finos para el resto del código.

Cada función es segura de llamar desde cualquier lado: nunca lanza y no
importa nada del bot (sin ciclos de import).
"""

from __future__ import annotations

import logging

from . import events, metrics, service_state

log = logging.getLogger(__name__)


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.debug("hook de observabilidad falló", exc_info=True)

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@_safe
def background_failed(task: str, error: BaseException) -> None:
    metrics.BACKGROUND_FAILURES.labels(task).inc()
    events.log_event(
        "system.background_task_failed",
        task=task,
        error_type=type(error).__name__,
    )
    state = service_state.get()
    if state:
        state.record_error(type(error).__name__, f"task:{task}")


@_safe
def command_ok() -> None:
    metrics.COMMANDS.labels("ok").inc()


@_safe
def command_failed(command: str, error: BaseException) -> None:
    metrics.COMMANDS.labels("error").inc()
    events.log_event(
        "discord.command_error",
        command=command,
        error_type=type(error).__name__,
    )
    state = service_state.get()
    if state:
        state.record_error(type(error).__name__, f"command:{command}")


@_safe
def db_connection_failed(error: BaseException, where: str) -> None:
    metrics.DB_CONNECTION_ERRORS.inc()
    events.log_event(
        "database.connection_failed",
        error_type=type(error).__name__,
        reason=where,
    )
    state = service_state.get()
    if state:
        state.record_error(type(error).__name__, f"database:{where}")


@_safe
def security(event_type: str, **fields) -> None:
    """Atajo para emitir un evento de seguridad desde webapi."""
    events.log_event(event_type, **fields)
