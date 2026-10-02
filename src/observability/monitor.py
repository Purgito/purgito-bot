"""Cliente del monitor externo (purgito-monitor, en Railway).

Dirección ÚNICA: Purgito -> monitor (heartbeat y eventos importantes). Este
módulo no recibe ni ejecuta nada que venga del monitor: la respuesta HTTP solo
se mira por su status. El monitor además sondea GET /health por su cuenta.

Garantías de diseño:
- Opcional: sin configuración completa, `from_config` devuelve None y nada corre.
- Nunca bloquea una operación principal: `on_event`/`enqueue` solo agregan a una
  cola en memoria; el envío ocurre en dos tareas de fondo propias.
- Falla barato: timeouts de 2/3 s, sin redirects, backoff exponencial con tope,
  un WARNING al caer y otro cada 10 min como máximo (nunca tracebacks en loop).
- Entrega best-effort. Solo los eventos críticos se guardan en un spool acotado
  (data/monitor/outbox.jsonl) para sobrevivir un reinicio.

Autenticación: HMAC-SHA256 sobre ``f"{timestamp}.{body}"`` con
MONITOR_SHARED_SECRET; cabeceras X-Purgito-Timestamp (unix, segundos) y
X-Purgito-Signature (``sha256=<hex>``). `verify_signature` es la referencia que
el receptor debe implementar.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp

from . import events, metrics, redaction

log = logging.getLogger(__name__)

SERVICE_NAME = "purgito"
HEADER_TS = "X-Purgito-Timestamp"
HEADER_SIG = "X-Purgito-Signature"
MAX_SKEW_SECONDS = 300

NODE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SUPPORTED_EVENT_TYPES = (
    "service.started",
    "service.shutdown",
    "service.restart",
    "service.crash",
    "database.failure",
    "security.alert",
    "system.warning",
)
# Eventos que vale la pena conservar en disco si el monitor no responde.
CRITICAL_TYPES = frozenset(
    {"service.restart", "service.crash", "database.failure", "security.alert"}
)

# Mapeo evento interno -> evento del monitor. service.started/restart/crash los
# emite `announce_lifecycle` (usa lifecycle_state), no el listener.
_INTERNAL_MAP = {
    "service.stopping": "service.shutdown",
    "database.connection_failed": "database.failure",
    "database.health_failed": "database.failure",
    "security.alert_opened": "security.alert",
    "system.background_task_failed": "system.warning",
}
# Mínimo entre dos eventos del mismo tipo hacia el monitor (anti-ruido).
_THROTTLE_SECONDS = {"database.failure": 60.0, "system.warning": 300.0}
# Campos internos que no viajan (ids de personas/servidores no hacen falta).
_DROP_FIELDS = {"user_id", "guild_id", "channel_id", "source_id"}

HTTP_TOTAL_TIMEOUT = 3.0
HTTP_CONNECT_TIMEOUT = 2.0
BACKOFF_BASE = 5.0
BACKOFF_CAP = 300.0
WARN_EVERY_SECONDS = 600.0
MAX_ATTEMPTS = {True: 20, False: 5}  # por criticidad
NONCRITICAL_TTL = 600.0
CRITICAL_TTL = 24 * 3600.0
OUTBOX_MAX_ITEMS = 100
OUTBOX_MAX_BYTES = 256 * 1024


# ---------------- Firma ----------------


def sign(secret: str, timestamp: str | int, body: bytes) -> str:
    mac = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"sha256={mac}"


def verify_signature(
    secret: str,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    *,
    now: float | None = None,
    max_skew: int = MAX_SKEW_SECONDS,
) -> tuple[bool, str]:
    """Referencia para el receptor. Devuelve (ok, motivo)."""
    if not secret:
        return False, "secret_missing"
    if not timestamp or not signature:
        return False, "missing_headers"
    try:
        ts = int(timestamp)
    except ValueError:
        return False, "bad_timestamp"
    if abs((now if now is not None else time.time()) - ts) > max_skew:
        return False, "timestamp_expired"
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        return False, "bad_signature"
    return True, "ok"


def backoff_delay(
    failures: int, base: float = BACKOFF_BASE, cap: float = BACKOFF_CAP
) -> float:
    """Espera tras `failures` fallos consecutivos (>=1): base, 2·base, … tope."""
    return min(cap, base * (2 ** max(0, failures - 1)))


def _iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _dumps(payload: dict) -> bytes:
    return json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode()


# ---------------- Spool ----------------


class Outbox:
    """Cola de eventos pendientes. Todo vive en memoria; los críticos se
    persisten (archivo atómico, 0600) con tope de cantidad, bytes y edad."""

    def __init__(self, path: str | None) -> None:
        self.path = path
        self.items: list[dict] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                        if isinstance(item.get("event"), dict) and item["event"].get(
                            "event_id"
                        ):
                            item.update(critical=True, attempts=0, next_attempt=0.0)
                            self.items.append(item)
                    except ValueError:
                        continue
        except OSError:
            return
        self.prune()

    def _persist(self) -> None:
        if not self.path:
            return
        critical = [
            {"event": i["event"], "added_at": i["added_at"]}
            for i in self.items
            if i["critical"]
        ]
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            if not critical:
                if os.path.exists(self.path):
                    os.remove(self.path)
                return
            fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(self.path), prefix=".outbox."
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for entry in critical:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        except OSError:
            log.debug("No se pudo persistir el outbox del monitor", exc_info=True)

    def prune(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            keep = [
                i
                for i in self.items
                if now - i["added_at"]
                < (CRITICAL_TTL if i["critical"] else NONCRITICAL_TTL)
            ]
            # Tope de cantidad: se descartan primero los no críticos, más viejos primero.
            while len(keep) > OUTBOX_MAX_ITEMS:
                victim = next((i for i in keep if not i["critical"]), keep[0])
                keep.remove(victim)

            # Tope de bytes (solo lo que se persiste).
            def size() -> int:
                return sum(len(_dumps(i["event"])) + 32 for i in keep if i["critical"])

            while size() > OUTBOX_MAX_BYTES:
                victim = next((i for i in keep if i["critical"]), None)
                if victim is None:
                    break
                keep.remove(victim)
            changed = len(keep) != len(self.items)
            self.items = keep
            if changed:
                self._persist()

    def add(self, event: dict, critical: bool, now: float | None = None) -> bool:
        """False si el event_id ya estaba (deduplicación local)."""
        with self._lock:
            if any(i["event"]["event_id"] == event["event_id"] for i in self.items):
                return False
            self.items.append(
                {
                    "event": event,
                    "critical": critical,
                    "added_at": now if now is not None else time.time(),
                    "attempts": 0,
                    "next_attempt": 0.0,
                }
            )
            if critical:
                self._persist()
        self.prune(now)
        return True

    def remove(self, event_id: str) -> None:
        with self._lock:
            before = len(self.items)
            removed = [i for i in self.items if i["event"]["event_id"] == event_id]
            self.items = [i for i in self.items if i["event"]["event_id"] != event_id]
            if len(self.items) != before and any(i["critical"] for i in removed):
                self._persist()

    def next_due(self, now: float) -> dict | None:
        with self._lock:
            for item in self.items:
                if item["next_attempt"] <= now:
                    return item
        return None

    def __len__(self) -> int:
        return len(self.items)


# ---------------- Cliente ----------------


class MonitorClient:
    def __init__(
        self,
        base_url: str,
        node_id: str,
        secret: str,
        interval: int = 30,
        data_dir: str | None = None,
        *,
        started_at: str | None = None,
        db_ping=None,
        bot=None,
        version: str | None = None,
        clock=time.time,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.node_id = node_id
        self._secret = secret
        self.interval = interval
        self.data_dir = data_dir or "."
        self.started_at = started_at or _iso()
        self.db_ping = db_ping
        self.bot = bot
        self.version = version
        self.clock = clock
        self.outbox = Outbox(
            os.path.join(data_dir, "monitor", "outbox.jsonl") if data_dir else None
        )
        self.failures = 0  # fallos consecutivos (cualquier tipo de envío)
        self.last_success: float | None = None
        self._last_warn = 0.0
        self._last_sent_type: dict[str, float] = {}
        self._session: aiohttp.ClientSession | None = None
        self._tasks: list[asyncio.Task] = []
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._start_mono = time.monotonic()
        redaction.register_secret(secret)

    # ---- transporte ----
    def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=HTTP_TOTAL_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT
                )
            )
        return self._session

    async def _post(self, path: str, payload: dict) -> tuple[str, int | None]:
        """('ok'|'retry'|'reject', status). Nunca lanza."""
        body = _dumps(payload)
        ts = str(int(self.clock()))
        headers = {
            "Content-Type": "application/json",
            HEADER_TS: ts,
            HEADER_SIG: sign(self._secret, ts, body),
            "User-Agent": "purgito-node",
        }
        try:
            async with self._session_get().post(
                self.base_url + path, data=body, headers=headers, allow_redirects=False
            ) as resp:
                status = resp.status
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            self._note_failure(f"{type(exc).__name__}")
            return "retry", None
        except Exception as exc:  # defensivo: el monitor jamás rompe a Purgito
            self._note_failure(f"{type(exc).__name__}")
            return "retry", None
        if 200 <= status < 300:
            self._note_success()
            return "ok", status
        if status in (408, 425, 429) or status >= 500:
            self._note_failure(f"HTTP {status}")
            return "retry", status
        # 4xx: el monitor rechazó la request (firma, node_id, payload). Reintentar no sirve.
        self._note_failure(f"HTTP {status}", reject=True)
        return "reject", status

    def _note_success(self) -> None:
        if self.failures:
            log.info(
                "monitor reachable again after %d failed attempt(s)", self.failures
            )
        self.failures = 0
        self.last_success = self.clock()
        self._last_warn = 0.0
        metrics.MONITOR_LAST_SUCCESS.set(self.last_success)

    def _note_failure(self, reason: str, reject: bool = False) -> None:
        self.failures += 1
        now = time.monotonic()
        if self.failures == 1 or now - self._last_warn >= WARN_EVERY_SECONDS:
            self._last_warn = now
            if reject:
                log.warning(
                    "monitor rejected the request (%s); check MONITOR_NODE_ID / "
                    "MONITOR_SHARED_SECRET (consecutive failures: %d)",
                    reason,
                    self.failures,
                )
            else:
                log.warning(
                    "monitor unreachable (%s); retrying with backoff (consecutive failures: %d)",
                    reason,
                    self.failures,
                )

    # ---- heartbeat ----
    async def build_heartbeat(self) -> dict:
        hb: dict = {
            "node_id": self.node_id,
            "timestamp": _iso(self.clock()),
            "started_at": self.started_at,
            "uptime_seconds": int(time.monotonic() - self._start_mono),
            "service": SERVICE_NAME,
            "status": "up",
        }
        latency = getattr(self.bot, "latency", None)
        if (
            isinstance(latency, float)
            and latency == latency
            and latency != float("inf")
        ):
            hb["discord_latency_ms"] = round(latency * 1000)
        if self.db_ping is not None:
            t0 = time.perf_counter()
            try:
                await asyncio.wait_for(self.db_ping(), timeout=1.0)
                hb["postgres_status"] = "ok"
                hb["postgres_latency_ms"] = round((time.perf_counter() - t0) * 1000)
            except Exception:
                hb["postgres_status"] = "down"
        rss = metrics.process_memory_bytes()
        if rss is not None:
            hb["memory_rss_bytes"] = rss
        try:
            hb["disk_free_bytes"] = shutil.disk_usage(self.data_dir).free
        except OSError:
            pass
        if self.version:
            hb["version"] = self.version
        return hb

    async def send_heartbeat(self) -> bool:
        result, _ = await self._post("/v1/heartbeat", await self.build_heartbeat())
        if result != "ok":
            metrics.MONITOR_SEND_ERRORS.labels("heartbeat").inc()
        return result == "ok"

    async def _heartbeat_loop(self) -> None:
        while True:
            await self.send_heartbeat()
            delay = (
                self.interval
                if self.failures == 0
                else max(self.interval, backoff_delay(self.failures))
            )
            await asyncio.sleep(delay)

    # ---- eventos ----
    def make_event(
        self, event_type: str, severity: str, message: str, metadata: dict | None = None
    ) -> dict:
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValueError(f"event_type no soportado por el monitor: {event_type!r}")
        return {
            "event_id": uuid.uuid4().hex,
            "node_id": self.node_id,
            "timestamp": _iso(self.clock()),
            "event_type": event_type,
            "severity": severity,
            "service": SERVICE_NAME,
            "message": redaction.scrub(message),
            "metadata": redaction.sanitize_fields(metadata or {}),
        }

    def enqueue(self, event: dict) -> bool:
        """No bloquea: agrega al outbox y despierta al sender. Thread-safe."""
        critical = event["event_type"] in CRITICAL_TYPES or event["severity"] in (
            "error",
            "critical",
        )
        added = self.outbox.add(event, critical, now=self.clock())
        if added and self._loop is not None and self._wake is not None:
            try:
                self._loop.call_soon_threadsafe(self._wake.set)
            except RuntimeError:  # loop cerrado
                pass
        return added

    def on_event(self, event: dict) -> None:
        """Listener de eventos internos (observability.events)."""
        mapped = _INTERNAL_MAP.get(event["event_type"])
        if mapped is None:
            return
        gap = _THROTTLE_SECONDS.get(mapped)
        now = time.monotonic()
        if gap is not None:
            last = self._last_sent_type.get(mapped)
            if last is not None and now - last < gap:
                return
            self._last_sent_type[mapped] = now
        metadata = {
            k: v for k, v in (event.get("data") or {}).items() if k not in _DROP_FIELDS
        }
        for key in ("reason", "error_type", "rule_id", "request_id"):
            if key in event:
                metadata[key] = event[key]
        severity = event["severity"] if event["severity"] != "debug" else "info"
        try:
            self.enqueue(self.make_event(mapped, severity, event["message"], metadata))
        except Exception:
            log.debug("No se pudo encolar el evento para el monitor", exc_info=True)

    def announce_lifecycle(
        self,
        previous_shutdown: str,
        *,
        last_seen_alive: str | None = None,
        restarts_1h: int = 0,
    ) -> None:
        """Evento de arranque. `previous_shutdown`: clean | unexpected | none.

        unexpected significa SOLO que el proceso anterior desapareció sin
        shutdown limpio; la causa se desconoce y no se afirma ninguna.
        """
        meta = {"previous_shutdown": previous_shutdown}
        if previous_shutdown == "unexpected":
            meta["cause"] = "unknown"
            if last_seen_alive:
                meta["last_seen_alive"] = last_seen_alive
            self.enqueue(
                self.make_event(
                    "service.restart",
                    "warning",
                    "Purgito arrancó; el proceso anterior desapareció sin shutdown limpio (causa desconocida)",
                    meta,
                )
            )
        else:
            self.enqueue(
                self.make_event("service.started", "info", "Purgito arrancó", meta)
            )
        if restarts_1h >= 3:
            self.enqueue(
                self.make_event(
                    "service.crash",
                    "error",
                    f"{restarts_1h} reinicios en la última hora",
                    {**meta, "restarts_1h": restarts_1h},
                )
            )

    async def process_outbox_once(self) -> int:
        """Intenta enviar lo que esté listo. Devuelve cuántos eventos entregó.
        Corta en el primer fallo (si el monitor está caído, no se insiste)."""
        self.outbox.prune(self.clock())
        sent = 0
        while (item := self.outbox.next_due(self.clock())) is not None:
            result, _ = await self._post("/v1/events", item["event"])
            if result == "ok":
                self.outbox.remove(item["event"]["event_id"])
                metrics.MONITOR_EVENTS_SENT.inc()
                sent += 1
                continue
            metrics.MONITOR_SEND_ERRORS.labels("event").inc()
            item["attempts"] += 1
            if result == "reject" or item["attempts"] >= MAX_ATTEMPTS[item["critical"]]:
                self.outbox.remove(item["event"]["event_id"])
                continue
            item["next_attempt"] = self.clock() + backoff_delay(item["attempts"])
            break
        return sent

    async def _event_loop(self) -> None:
        assert self._wake is not None
        while True:
            await self.process_outbox_once()
            self._wake.clear()
            wait = 5.0
            if len(self.outbox):
                due = min(i["next_attempt"] for i in self.outbox.items)
                wait = max(1.0, min(due - self.clock(), BACKOFF_CAP))
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    # ---- ciclo de vida ----
    def start(self) -> None:
        if self._tasks:
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._tasks = [
            self._loop.create_task(self._heartbeat_loop(), name="monitor-heartbeat"),
            self._loop.create_task(self._event_loop(), name="monitor-events"),
        ]

    async def flush(self, timeout: float = 2.0) -> None:
        """Entrega best-effort acotada (apagado). Nunca lanza ni excede `timeout`."""
        try:
            await asyncio.wait_for(self.process_outbox_once(), timeout=timeout)
        except Exception:
            pass

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        if self._session is not None and not self._session.closed:
            await self._session.close()


# ---------------- Construcción desde config ----------------


async def default_db_ping() -> None:
    import db

    database = await db.get_db()
    async with database.execute("SELECT 1") as cur:
        await cur.fetchone()


def detect_version(root: str) -> str | None:
    """Commit corto del checkout (informativo). None si no se puede leer."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        value = out.stdout.strip()
        return (
            value
            if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{4,40}", value)
            else None
        )
    except Exception:
        return None


_client: MonitorClient | None = None


def get() -> MonitorClient | None:
    return _client


def config_problem(base_url: str, node_id: str, secret: str) -> str | None:
    """Motivo por el que la config NO es usable (None = usable). Sin secretos."""
    if not base_url or not node_id or not secret:
        return "faltan MONITOR_BASE_URL / MONITOR_NODE_ID / MONITOR_SHARED_SECRET"
    if not NODE_ID_RE.match(node_id):
        return "MONITOR_NODE_ID inválido (usa [A-Za-z0-9._-], máx. 64)"
    parsed = urlparse(base_url)
    if parsed.scheme == "https" and parsed.hostname:
        return None
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return None  # solo loopback (desarrollo/tests)
    return "MONITOR_BASE_URL debe ser https:// (http solo para loopback)"


def from_config(data_dir: str, bot=None, db_ping=None) -> MonitorClient | None:
    """Crea el cliente global si MONITOR_ENABLED y la config es válida."""
    global _client
    import config

    if not config.MONITOR_ENABLED:
        return None
    problem = config_problem(
        config.MONITOR_BASE_URL, config.MONITOR_NODE_ID, config.MONITOR_SHARED_SECRET
    )
    if problem:
        log.warning("Monitor externo desactivado: %s", problem)
        return None
    _client = MonitorClient(
        config.MONITOR_BASE_URL,
        config.MONITOR_NODE_ID,
        config.MONITOR_SHARED_SECRET,
        config.MONITOR_HEARTBEAT_INTERVAL,
        data_dir,
        bot=bot,
        db_ping=db_ping,
    )
    events.add_listener(_client.on_event)
    return _client


def reset() -> None:
    """Para tests: quita el cliente global y su listener."""
    global _client
    if _client is not None:
        events.remove_listener(_client.on_event)
    _client = None
