"""Métricas Prometheus (prometheus_client, Apache-2.0).

Registro PROPIO (no el global): no arrastra los collectors de plataforma ni
nada que no se haya decidido. Solo se exponen métricas que se pueden calcular
de forma fiable -- ver docs/OBSERVABILITY.md para la lista y su origen.

Cardinalidad acotada: las etiquetas son rutas canónicas (patrón, no URL real),
nombres de comando de un conjunto cerrado, y nunca ids de guild/usuario.
"""

from __future__ import annotations

import time

import prometheus_client

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.exposition import CONTENT_TYPE_LATEST

# Sin las series *_created: duplican la cardinalidad sin aportar nada acá.
prometheus_client.disable_created_metrics()

REGISTRY = CollectorRegistry(auto_describe=True)

_START = time.monotonic()

UP = Gauge("purgito_up", "1 si el proceso del bot está ejecutándose", registry=REGISTRY)
UPTIME = Gauge(
    "purgito_uptime_seconds",
    "Segundos desde el arranque del proceso",
    registry=REGISTRY,
)
DISCORD_LATENCY = Gauge(
    "purgito_discord_latency_seconds",
    "Latencia del gateway de Discord (NaN antes del primer heartbeat)",
    registry=REGISTRY,
)
GUILDS = Gauge("purgito_guilds", "Servidores en los que está el bot", registry=REGISTRY)
MEMORY = Gauge(
    "purgito_memory_bytes",
    "RSS del proceso (leído de /proc/self/status)",
    registry=REGISTRY,
)
READY = Gauge(
    "purgito_ready",
    "1 si el bot está conectado a Discord y la base responde",
    registry=REGISTRY,
)
HEARTBEAT_AGE = Gauge(
    "purgito_heartbeat_age_seconds",
    "Segundos desde el último heartbeat escrito",
    registry=REGISTRY,
)

ERRORS = Counter(
    "purgito_errors_total",
    "Errores no esperados, por origen",
    ["source"],
    registry=REGISTRY,
)
COMMANDS = Counter(
    "purgito_command_total",
    "Comandos ejecutados, por resultado (ok/error)",
    ["result"],
    registry=REGISTRY,
)
BACKGROUND_FAILURES = Counter(
    "purgito_background_failures_total",
    "Fallos de tareas en segundo plano, por tarea",
    ["task"],
    registry=REGISTRY,
)
DB_CONNECTION_ERRORS = Counter(
    "purgito_db_connection_errors_total",
    "Fallos de conexión/chequeo a PostgreSQL",
    registry=REGISTRY,
)
HTTP_REQUESTS = Counter(
    "purgito_http_requests_total",
    "Requests HTTP de la API, por método, ruta canónica y clase de status",
    ["method", "route", "status_class"],
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "purgito_http_request_duration_seconds",
    "Duración de requests HTTP de la API",
    ["route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=REGISTRY,
)
EVENTS = Counter(
    "purgito_events_total",
    "Eventos estructurados emitidos, por tipo y severidad",
    ["event_type", "severity"],
    registry=REGISTRY,
)
ALERTS_OPEN = Gauge(
    "purgito_alerts_open", "Alertas de detección abiertas", registry=REGISTRY
)


def process_memory_bytes() -> int | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def refresh_gauges(
    bot=None, state=None, alerts_open: int | None = None, ready=None
) -> None:
    """Actualiza los gauges calculados justo antes de servir /metrics."""
    UP.set(1)
    UPTIME.set(time.monotonic() - _START)
    mem = process_memory_bytes()
    if mem is not None:
        MEMORY.set(mem)
    if bot is not None:
        latency = bot.latency
        DISCORD_LATENCY.set(latency if latency == latency else float("nan"))
        GUILDS.set(len(bot.guilds))
    if state is not None:
        age = state.snapshot()["heartbeat_age_seconds"]
        if age is not None:
            HEARTBEAT_AGE.set(age)
    if alerts_open is not None:
        ALERTS_OPEN.set(alerts_open)
    if ready is not None:
        READY.set(1 if ready else 0)


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def count_event(event: dict) -> None:
    """Listener de eventos: cuenta por tipo/severidad (tipos cerrados -> cardinalidad fija)."""
    from .events import EVENT_TYPES

    etype = (
        event["event_type"] if event["event_type"] in EVENT_TYPES else "unregistered"
    )
    EVENTS.labels(etype, event["severity"]).inc()
    if event["severity"] in ("error", "critical"):
        ERRORS.labels(event["event_type"].split(".")[0]).inc()
