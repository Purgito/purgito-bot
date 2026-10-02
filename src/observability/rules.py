"""Reglas de detección y modelo de alertas.

Solo DETECTA y CATALOGA: no bloquea usuarios, no ejecuta comandos, no responde
automáticamente. Las reglas son datos (``Rule``); el motor mantiene ventanas
deslizantes en memoria sobre el stream de eventos.

Alerta (modelo estable para el control plane externo):
  alert_id, rule_id, severity, status (open|acknowledged|resolved),
  created_at, updated_at, source, summary, details, related_events

Mientras una alerta de (regla, grupo) siga open/acknowledged, nuevas
coincidencias la ACTUALIZAN en vez de crear otra (sin tormenta de alertas).
Se persiste en data/alerts.json (atómico, tope ``MAX_ALERTS``).
"""

from __future__ import annotations

import collections
import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import events

log = logging.getLogger(__name__)

STATUSES = ("open", "acknowledged", "resolved")
MAX_ALERTS = 200
MAX_RELATED = 10


@dataclass(frozen=True)
class Rule:
    rule_id: str
    description: str
    severity: str
    event_types: tuple[str, ...]
    count: int
    window_seconds: int
    # Campo del evento por el que se agrupa (p. ej. "source_id"); None = global.
    group_by: str | None = None
    # Igualdades exactas requeridas (campo -> valor). Busca en top-level y en data.
    where: dict = field(default_factory=dict)
    # Mínimos numéricos requeridos (campo -> valor).
    min_fields: dict = field(default_factory=dict)


RULES: tuple[Rule, ...] = (
    Rule(
        "auth.login_failure_burst",
        "5 login failures en 5 minutos desde el mismo origen",
        "warning",
        ("auth.login_failure",),
        5,
        300,
        group_by="source_id",
    ),
    Rule(
        "permission.denied_burst",
        "10 permission.denied en 5 minutos desde el mismo origen",
        "warning",
        ("permission.denied",),
        10,
        300,
        group_by="source_id",
    ),
    Rule(
        "webhook.signature_invalid_burst",
        "3 webhooks con firma inválida en 10 minutos desde el mismo origen",
        "warning",
        ("webhook.signature_invalid",),
        3,
        600,
        group_by="source_id",
    ),
    Rule(
        "rate_limit.flood",
        "20 rate limits en 5 minutos desde el mismo origen",
        "warning",
        ("rate_limit.triggered",),
        20,
        300,
        group_by="source_id",
    ),
    Rule(
        "service.restart_loop",
        "El servicio arrancó 3 o más veces en la última hora",
        "error",
        ("service.started",),
        1,
        1,
        min_fields={"restarts_1h": 3},
    ),
    Rule(
        "service.crash_detected",
        "El arranque detectó que el proceso anterior no cerró limpio",
        "error",
        ("service.crash_detected",),
        1,
        1,
    ),
    Rule(
        "database.connection_failed_repeated",
        "3 fallos de conexión a la base en 5 minutos",
        "error",
        ("database.connection_failed", "database.health_failed"),
        3,
        300,
    ),
    Rule(
        "background.task_failed_repeated",
        "5 fallos de tareas en segundo plano en 10 minutos",
        "error",
        ("system.background_task_failed",),
        5,
        600,
    ),
)


def _event_field(event: dict, name: str):
    if name in event:
        return event[name]
    return (event.get("data") or {}).get(name)


def _epoch(event: dict, now: float | None) -> float:
    if now is not None:
        return now
    try:
        ts = event["timestamp"].replace("Z", "+00:00")
        return datetime.fromisoformat(ts).timestamp()
    except (KeyError, ValueError, AttributeError):
        return datetime.now(timezone.utc).timestamp()


def _compact(event: dict) -> dict:
    out = {
        k: event[k]
        for k in ("event_id", "timestamp", "event_type", "reason", "request_id")
        if k in event
    }
    return out


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


class AlertStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self.alerts: list[dict] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.alerts = data[-MAX_ALERTS:]
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        if not self.path:
            return
        try:
            fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(self.path) or ".", prefix=".alerts."
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.alerts, f, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("No se pudo guardar %s", self.path, exc_info=True)

    def find_active(self, rule_id: str, group_key: str | None) -> dict | None:
        for alert in reversed(self.alerts):
            if (
                alert["rule_id"] == rule_id
                and alert["details"].get("group_key") == group_key
                and alert["status"] != "resolved"
            ):
                return alert
        return None

    def create(self, rule: Rule, group_key, matched: list[dict], reason: str) -> dict:
        now = _iso_now()
        alert = {
            "alert_id": uuid.uuid4().hex[:16],
            "rule_id": rule.rule_id,
            "severity": rule.severity,
            "status": "open",
            "created_at": now,
            "updated_at": now,
            "source": f"{events.SERVICE}@{events._HOST}",
            "summary": rule.description,
            "details": {
                "reason": reason,
                "group_key": group_key,
                "window_seconds": rule.window_seconds,
                "threshold": rule.count,
                "match_count": len(matched),
            },
            "related_events": matched[-MAX_RELATED:],
        }
        with self._lock:
            self.alerts.append(alert)
            self.alerts = self.alerts[-MAX_ALERTS:]
            self._save()
        return alert

    def touch(self, alert: dict, matched: list[dict]) -> None:
        with self._lock:
            alert["updated_at"] = _iso_now()
            alert["details"]["match_count"] = alert["details"].get("match_count", 0) + 1
            alert["related_events"] = (alert["related_events"] + matched[-1:])[
                -MAX_RELATED:
            ]
            self._save()

    def set_status(self, alert_id: str, status: str) -> dict | None:
        if status not in STATUSES:
            raise ValueError(f"status inválido: {status!r}")
        with self._lock:
            for alert in self.alerts:
                if alert["alert_id"] == alert_id:
                    alert["status"] = status
                    alert["updated_at"] = _iso_now()
                    self._save()
                    return alert
        return None

    def acknowledge(self, alert_id: str) -> dict | None:
        return self.set_status(alert_id, "acknowledged")

    def resolve(self, alert_id: str) -> dict | None:
        return self.set_status(alert_id, "resolved")

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            items = [a for a in self.alerts if status is None or a["status"] == status]
        return list(reversed(items))

    def open_count(self) -> int:
        return sum(1 for a in self.alerts if a["status"] == "open")


class RuleEngine:
    def __init__(self, rules=RULES, store: AlertStore | None = None) -> None:
        self.rules = tuple(rules)
        self.store = store or AlertStore()
        # (rule_id, group_key) -> deque[(epoch, compact_event)]
        self._windows: dict[tuple, collections.deque] = {}

    def _matches(self, rule: Rule, event: dict) -> bool:
        if event["event_type"] not in rule.event_types:
            return False
        for name, expected in rule.where.items():
            if _event_field(event, name) != expected:
                return False
        for name, minimum in rule.min_fields.items():
            value = _event_field(event, name)
            if not isinstance(value, (int, float)) or value < minimum:
                return False
        return True

    def process(self, event: dict, now: float | None = None) -> list[dict]:
        """Evalúa un evento; devuelve las alertas CREADAS por este evento."""
        created: list[dict] = []
        t = _epoch(event, now)
        for rule in self.rules:
            if not self._matches(rule, event):
                continue
            group_key = None
            if rule.group_by:
                group_key = _event_field(event, rule.group_by)
                if group_key is None:
                    continue  # sin origen no se puede agrupar; no se inventa uno
            window = self._windows.setdefault(
                (rule.rule_id, group_key), collections.deque()
            )
            window.append((t, _compact(event)))
            while window and t - window[0][0] > rule.window_seconds:
                window.popleft()
            if len(window) < rule.count:
                continue
            matched = [item for _, item in window]
            active = self.store.find_active(rule.rule_id, group_key)
            if active is not None:
                self.store.touch(active, matched)
                continue
            reason = (
                f"{len(matched)} eventos {'/'.join(rule.event_types)} en "
                f"{rule.window_seconds}s"
                + (f" ({rule.group_by}={group_key})" if group_key else "")
            )
            alert = self.store.create(rule, group_key, matched, reason)
            created.append(alert)
            window.clear()
            events.log_event(
                "security.alert_opened",
                severity=rule.severity,
                message=f"Alerta {rule.rule_id}: {reason}",
                rule_id=rule.rule_id,
                alert_id=alert["alert_id"],
            )
        return created

    def on_event(self, event: dict) -> None:
        self.process(event)


_engine: RuleEngine | None = None


def init(data_dir: str) -> RuleEngine:
    global _engine
    if _engine is not None:
        events.remove_listener(_engine.on_event)
    _engine = RuleEngine(store=AlertStore(os.path.join(data_dir, "alerts.json")))
    events.add_listener(_engine.on_event)
    return _engine


def get() -> RuleEngine | None:
    return _engine
