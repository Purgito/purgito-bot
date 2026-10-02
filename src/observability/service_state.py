"""Estado del servicio y heartbeat -- sin PostgreSQL.

Un JSON chico (data/service_state.json) que el propio proceso reescribe de
forma atómica cada ``HEARTBEAT_INTERVAL`` segundos. Es lo que permite saber
"el bot sigue ejecutándose" aunque la base esté caída, y reconstruir qué pasó
si el proceso murió.

Se complementa (no se duplica) con ``lifecycle_state`` de PostgreSQL: esa
tabla sigue siendo la fuente del aviso "Purgito volvió" en Discord; este
archivo agrega lo que la tabla no puede dar cuando la base falla (heartbeat,
contador de reinicios, último error).

Estados: starting -> running -> stopping -> stopped. Si al arrancar el estado
anterior NO es ``stopped``, el proceso previo murió sin cerrar limpio.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

from . import events

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # segundos
# Cada cuántos heartbeats se emite además un evento service.heartbeat.
HEARTBEAT_EVENT_EVERY = 20  # = cada 10 min
# Sin latido durante este tiempo, el estado se considera "stale" (proceso colgado o muerto).
STALE_AFTER = HEARTBEAT_INTERVAL * 3
_MAX_STARTS_KEPT = 50

_PROCESS_START_MONOTONIC = time.monotonic()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ServiceState:
    def __init__(self, path: str) -> None:
        self.path = path
        self.data: dict = {}
        self._beats = 0
        self._task: asyncio.Task | None = None

    # ---- persistencia ----
    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self) -> None:
        """Escritura atómica (tmp + rename): un corte a mitad no deja un JSON roto."""
        try:
            directory = os.path.dirname(self.path) or "."
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".service_state.")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("No se pudo escribir %s", self.path, exc_info=True)

    # ---- ciclo de vida ----
    def start(self) -> dict:
        """Marca el arranque. Devuelve el resumen del proceso anterior (ver
        ``previous``): lo que se sabe de cómo terminó, sin inventar la causa."""
        prev = self._read()
        prev_state = prev.get("state")
        last_beat = prev.get("last_heartbeat")
        crashed = bool(prev) and prev_state not in ("stopped", None)
        now = _now()
        starts = [s for s in prev.get("starts", []) if _parse(s)][-_MAX_STARTS_KEPT:]
        starts.append(_iso(now))

        previous = {
            "had_previous": bool(prev),
            "state": prev_state,
            "started_at": prev.get("started_at"),
            "last_heartbeat": last_beat,
            "clean_shutdown": prev_state == "stopped" if prev else None,
            "crashed": crashed,
            "cause": "unknown" if crashed else None,
        }
        self.data = {
            "service": events.SERVICE,
            "pid": os.getpid(),
            "state": "starting",
            "previous_state": prev_state,
            "started_at": _iso(now),
            "last_heartbeat": _iso(now),
            "last_clean_shutdown": (
                prev.get("stopped_at")
                if prev_state == "stopped"
                else prev.get("last_clean_shutdown")
            ),
            "last_error": prev.get("last_error"),
            "starts": starts,
            "previous_run": previous,
        }
        self._write()
        return previous

    def set_state(self, state: str) -> None:
        self.data["previous_state"] = self.data.get("state")
        self.data["state"] = state
        if state == "stopped":
            self.data["stopped_at"] = _iso()
            self.data["last_clean_shutdown"] = self.data["stopped_at"]
        self.data["last_heartbeat"] = _iso()
        self._write()

    def record_error(self, error_type: str, where: str) -> None:
        """Último error importante. Solo tipo y lugar: nunca el mensaje crudo."""
        self.data["last_error"] = {
            "at": _iso(),
            "error_type": error_type,
            "where": where,
        }

    def beat(self) -> None:
        self.data["last_heartbeat"] = _iso()
        self._beats += 1
        self._write()
        if self._beats % HEARTBEAT_EVENT_EVERY == 0:
            events.log_event("service.heartbeat", uptime_seconds=self.uptime_seconds())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                self.beat()
            except Exception:
                log.exception("Falló el heartbeat")

    def start_heartbeat(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop_heartbeat(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    # ---- consulta ----
    def uptime_seconds(self) -> int:
        return int(time.monotonic() - _PROCESS_START_MONOTONIC)

    def restarts_within(self, window: timedelta) -> int:
        """Arranques del proceso (incluido el actual) dentro de la ventana, menos uno."""
        cutoff = _now() - window
        n = sum(
            1 for s in self.data.get("starts", []) if (_parse(s) or cutoff) >= cutoff
        )
        return max(0, n - 1)

    def snapshot(self) -> dict:
        beat = _parse(self.data.get("last_heartbeat"))
        age = (_now() - beat).total_seconds() if beat else None
        return {
            "state": self.data.get("state"),
            "previous_state": self.data.get("previous_state"),
            "started_at": self.data.get("started_at"),
            "last_heartbeat": self.data.get("last_heartbeat"),
            "heartbeat_age_seconds": round(age, 1) if age is not None else None,
            "stale": age is None or age > STALE_AFTER,
            "uptime_seconds": self.uptime_seconds(),
            "last_clean_shutdown": self.data.get("last_clean_shutdown"),
            "last_error": self.data.get("last_error"),
            "restarts_1h": self.restarts_within(timedelta(hours=1)),
            "restarts_24h": self.restarts_within(timedelta(hours=24)),
            "previous_run": self.data.get("previous_run"),
        }


_state: ServiceState | None = None


def init(data_dir: str) -> ServiceState:
    global _state
    _state = ServiceState(os.path.join(data_dir, "service_state.json"))
    return _state


def get() -> ServiceState | None:
    return _state
