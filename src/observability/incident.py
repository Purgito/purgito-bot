"""Contexto de incidente: qué se sabe de cómo terminó el proceso anterior.

Reconstruye, SIN inventar, lo que el archivo de estado y los JSONL permiten:
cuándo estuvo vivo por última vez, si cerró limpio, último error y últimos
eventos relevantes. Si no hay forma de saber la causa, dice ``unknown``.
"""

from __future__ import annotations

import json
import os

from . import events

_TAIL_BYTES = 128 * 1024


def _tail_events(
    path: str, before: str | None, limit: int, min_severity: str
) -> list[dict]:
    floor = events.SEVERITIES.index(min_severity)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - _TAIL_BYTES))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue  # primera línea cortada por el seek, o línea corrupta
        if not isinstance(e, dict) or e.get("severity") not in events.SEVERITIES:
            continue
        if events.SEVERITIES.index(e["severity"]) < floor:
            continue
        if before and str(e.get("timestamp", "")) >= before:
            continue
        out.append(
            {
                k: e[k]
                for k in (
                    "timestamp",
                    "event_type",
                    "severity",
                    "message",
                    "error_type",
                    "reason",
                )
                if k in e
            }
        )
    return out[-limit:]


def build_context(state_snapshot: dict, data_dir: str, limit: int = 20) -> dict:
    """Contexto del arranque actual respecto del anterior."""
    prev = state_snapshot.get("previous_run") or {}
    started_at = state_snapshot.get("started_at")
    recent = []
    for name in ("events.jsonl", "security.jsonl"):
        recent += _tail_events(
            os.path.join(data_dir, name), started_at, limit, "warning"
        )
    recent.sort(key=lambda e: e.get("timestamp", ""))
    crashed = bool(prev.get("crashed"))
    return {
        "had_previous_run": bool(prev.get("had_previous")),
        "previous_state": prev.get("state"),
        "previous_started_at": prev.get("started_at"),
        "last_seen_alive": prev.get("last_heartbeat"),
        "clean_shutdown": prev.get("clean_shutdown"),
        "crashed": crashed,
        "cause": prev.get("cause") if crashed else None,
        "cause_note": (
            "cause unknown: el proceso anterior no registró un cierre limpio"
            if crashed
            else None
        ),
        "under_systemd": bool(os.environ.get("INVOCATION_ID")),
        "restarts_1h": state_snapshot.get("restarts_1h"),
        "restarts_24h": state_snapshot.get("restarts_24h"),
        "last_error": state_snapshot.get("last_error"),
        "last_important_events": recent[-limit:],
    }
