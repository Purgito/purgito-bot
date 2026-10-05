"""Pegamento: arranca la capa de observabilidad y arma las respuestas de salud.

``init`` se llama una vez, lo más temprano posible en bot.py. Todo lo demás
es opcional y tolerante a fallos: si algo de acá se rompe, el bot sigue.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from typing import Awaitable, Callable

from . import events, incident, logging_setup, metrics, rules, service_state

log = logging.getLogger(__name__)

_data_dir: str | None = None
_listener_installed = False


def init(data_dir: str) -> dict:
    """Configura logging, estado del servicio y motor de reglas. Devuelve el
    resumen del proceso anterior (``previous_run``)."""
    global _data_dir, _listener_installed
    _data_dir = data_dir
    logging_setup.setup_text_logging(data_dir)
    logging_setup.setup_event_files(data_dir)
    state = service_state.init(data_dir)
    rules.init(data_dir)
    if not _listener_installed:
        events.add_listener(metrics.count_event)
        _listener_installed = True
    return state.start()


def data_dir() -> str | None:
    return _data_dir


def announce_start(previous: dict) -> None:
    """Emite service.started (+ service.crash_detected si corresponde).
    Va DESPUÉS de init para que las reglas ya estén escuchando."""
    state = service_state.get()
    snap = state.snapshot() if state else {}
    if previous.get("crashed"):
        events.log_event(
            "service.crash_detected",
            reason="previous_process_did_not_shut_down_cleanly",
            previous_state=previous.get("state"),
            last_seen_alive=previous.get("last_heartbeat"),
            cause="unknown",
        )
    events.log_event(
        "service.started",
        restarts_1h=snap.get("restarts_1h", 0),
        restarts_24h=snap.get("restarts_24h", 0),
        previous_clean_shutdown=previous.get("clean_shutdown"),
    )


# ---------------- Salud ----------------

_READY_CACHE_TTL = 5.0
_ready_cache: tuple[float, dict] | None = None


async def readiness(
    bot, db_ping: Callable[[], Awaitable[None]], *, timeout: float = 2.0
) -> dict:
    """Chequeo barato: Discord conectado + un SELECT 1 con timeout. Cacheado 5 s
    para que un monitor agresivo (o un atacante) no se traduzca en carga."""
    global _ready_cache
    now = time.monotonic()
    if _ready_cache and now - _ready_cache[0] < _READY_CACHE_TTL:
        return _ready_cache[1]
    discord_ok = bool(bot is not None and bot.is_ready())
    db_ok = True
    try:
        await asyncio.wait_for(db_ping(), timeout=timeout)
    except Exception as exc:
        db_ok = False
        metrics.DB_CONNECTION_ERRORS.inc()
        events.log_event(
            "database.health_failed",
            error_type=type(exc).__name__,
            reason="readiness_ping_failed",
        )
    result = {"ready": discord_ok and db_ok, "discord": discord_ok, "database": db_ok}
    _ready_cache = (now, result)
    metrics.READY.set(1 if result["ready"] else 0)
    return result


def reset_readiness_cache() -> None:
    global _ready_cache
    _ready_cache = None


def details(bot, ready: dict) -> dict:
    """Diagnóstico para quien administra (endpoint protegido). Sin datos de
    usuarios, sin stack traces, sin ids de guild."""
    state = service_state.get()
    snap = state.snapshot() if state else {}
    engine = rules.get()
    latency = getattr(bot, "latency", float("nan"))
    return {
        "service": events.SERVICE,
        "environment": events.environment(),
        "ready": ready,
        "state": {k: v for k, v in snap.items() if k != "previous_run"},
        "discord": {
            "latency_ms": round(latency * 1000)
            if latency == latency and latency != float("inf")
            else None,
            "guilds": len(bot.guilds) if bot is not None else None,
        },
        "memory_bytes": metrics.process_memory_bytes(),
        "alerts": {
            "open": engine.store.open_count() if engine else 0,
        },
        "incident": incident.build_context(snap, _data_dir or ".") if snap else None,
    }


# ---------------- Autenticación de endpoints internos ----------------

_PROXY_HEADERS = ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP", "Forwarded")


def internal_access(headers, token: str) -> str:
    """'ok' | 'disabled' | 'proxied' | 'denied'.

    - disabled: no hay OBSERVABILITY_TOKEN -> los endpoints no existen (404).
    - proxied: la request llegó por nginx/Cloudflare -> 404; estos endpoints
      son solo para acceso directo a 127.0.0.1 (collector local / SSH / Tailscale).
    - denied: falta el Bearer o es incorrecto.
    """
    if not token:
        return "disabled"
    if any(headers.get(h) for h in _PROXY_HEADERS):
        return "proxied"
    auth = headers.get("Authorization", "")
    supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if supplied and hmac.compare_digest(supplied.encode(), token.encode()):
        return "ok"
    return "denied"
