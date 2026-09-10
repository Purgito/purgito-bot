"""Circuit breaker para aislar fallos del proveedor TTS primario (TikTok)."""

import asyncio
import logging
import time
from enum import Enum

from tts.errors import CircuitBreakerOpenError

log = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Implementa el patrón Circuit Breaker para un proveedor.

    - CLOSED: Operación normal. Si ocurren `failure_threshold` fallos consecutivos, pasa a OPEN.
    - OPEN: Rechaza llamadas durante `reset_timeout` segundos con CircuitBreakerOpenError.
      Cumplido el timeout, pasa a HALF_OPEN.
    - HALF_OPEN: Permite una solicitud de prueba (probe). Si tiene éxito, pasa a CLOSED;
      si falla, vuelve a OPEN.
    """

    def __init__(
        self,
        name: str = "tiktok",
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.reset_timeout = max(0.01, float(reset_timeout))
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = time.monotonic()
        self._lock = asyncio.Lock()
        self._probe_in_flight = False

    async def check_available(self) -> None:
        """Verifica si el circuito permite una llamada.

        Si está ABIERTO y el tiempo de enfriamiento no ha pasado, lanza CircuitBreakerOpenError.
        Si pasó el tiempo, transiciona a HALF_OPEN para una llamada de prueba.
        """
        async with self._lock:
            now = time.monotonic()
            if self.state == CircuitState.OPEN:
                if now - self.last_state_change >= self.reset_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.last_state_change = now
                    self._probe_in_flight = True
                    log.info(
                        "Circuit breaker [%s]: transición a HALF_OPEN para prueba de recuperación",
                        self.name,
                    )
                    return
                remaining = max(
                    0.0, self.reset_timeout - (now - self.last_state_change)
                )
                raise CircuitBreakerOpenError(
                    f"Circuit breaker [{self.name}] está OPEN ({remaining:.1f}s restantes)"
                )

            if self.state == CircuitState.HALF_OPEN:
                if not self._probe_in_flight:
                    self._probe_in_flight = True
                    return
                # Otra solicitud concurrente mientras la prueba está en vuelo
                raise CircuitBreakerOpenError(
                    f"Circuit breaker [{self.name}] está en HALF_OPEN probando recuperación"
                )

            # CLOSED
            return

    async def record_success(self) -> None:
        """Registra un llamado exitoso."""
        async with self._lock:
            prev_state = self.state
            self.failure_count = 0
            self._probe_in_flight = False
            self.state = CircuitState.CLOSED
            if prev_state != CircuitState.CLOSED:
                self.last_state_change = time.monotonic()
                log.info(
                    "Circuit breaker [%s]: proveedor recuperado, circuito CLOSED",
                    self.name,
                )

    async def record_failure(self) -> None:
        """Registra un fallo relevante del proveedor."""
        async with self._lock:
            self._probe_in_flight = False
            self.failure_count += 1
            now = time.monotonic()

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.last_state_change = now
                log.warning(
                    "Circuit breaker [%s]: llamada de prueba falló, volviendo a OPEN por %.0fs",
                    self.name,
                    self.reset_timeout,
                )
                return

            if self.state == CircuitState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self.last_state_change = now
                    log.warning(
                        "Circuit breaker [%s]: %d fallos consecutivos detectados. Circuito OPEN por %.0fs",
                        self.name,
                        self.failure_count,
                        self.reset_timeout,
                    )

    def is_open(self) -> bool:
        """Indica si actualmente el circuito rechazaría llamadas."""
        if self.state == CircuitState.CLOSED:
            return False
        if self.state == CircuitState.OPEN:
            return (time.monotonic() - self.last_state_change) < self.reset_timeout
        return self._probe_in_flight

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "reset_timeout": self.reset_timeout,
            "is_open": self.is_open(),
        }
