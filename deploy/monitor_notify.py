#!/usr/bin/python3 -I
"""Avisa a Purgito Monitor (el mismo backend que ya vigila a Purgito) de que falló una unidad de respaldo.

Lo lanza systemd con OnFailure= (purgito-notify@.service, como root); NO corre dentro del runner aislado de
backups: el secreto de ingesta del monitor vive en /etc/purgito/monitor.env (root:root 0600) y el runner no lo ve.
Usa el contrato de POST /v1/events (HMAC, ver umbrel-monitor/docs/CONTRACT.md §2 y §4): un evento
`system.warning` con severidad `critical`, que el monitor convierte en incidente y alerta de Discord.

    monitor_notify.py UNIDAD [--prueba]

El mensaje solo lleva el nombre de la unidad y un texto fijo: ni datos de personas ni secretos.
Variables (de monitor.env): MONITOR_BASE_URL, MONITOR_NODE_ID, MONITOR_SHARED_SECRET.
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

REASONS = {
    "purgito-backup.service": ("backup_failed", "El backup diario de la base falló"),
    "purgito-ledger.service": ("ledger_export_failed", "La exportación del registro de eliminaciones falló"),
    "purgito-backup-check.service": ("backup_stale", "No hay un backup o un registro de privacidad recientes"),
}


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def main(argv: list[str]) -> int:
    if not argv:
        print("uso: monitor_notify.py UNIDAD [--prueba]", file=sys.stderr)
        return 2
    unit, test = argv[0], "--prueba" in argv[1:]
    base = os.environ.get("MONITOR_BASE_URL", "").strip().rstrip("/")
    node = os.environ.get("MONITOR_NODE_ID", "").strip()
    secret = "".join(os.environ.get("MONITOR_SHARED_SECRET", "").split())
    if not (base.startswith("https://") and node and secret):
        print("monitor_notify: falta MONITOR_BASE_URL (https), MONITOR_NODE_ID o MONITOR_SHARED_SECRET", file=sys.stderr)
        return 2
    reason, text = REASONS.get(unit, ("unit_failed", "Una unidad de respaldo falló"))
    host = os.uname().nodename
    message = (f"PRUEBA de alerta de respaldos (sin incidencia real): {unit}" if test else f"{text}: {unit} en {host}") + "."
    event = {
        "event_id": uuid.uuid4().hex,
        "node_id": node,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "system.warning",
        "severity": "critical",
        "service": "purgito",
        "message": message,
        "reason": reason,
        "metadata": {"unit": unit, "source": "systemd-onfailure", "test": test},
    }
    body = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode()
    last = "sin respuesta"
    for attempt in range(1, 4):
        ts = str(int(time.time()))
        req = urllib.request.Request(
            base + "/v1/events",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Purgito-Timestamp": ts,
                "X-Purgito-Signature": sign(secret, ts, body),
                "User-Agent": "purgito-backup-notify",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"monitor_notify: evento {event['event_id'][:8]} entregado (HTTP {resp.status})")
                return 0
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (408, 425, 429) and e.code < 500:
                break  # el monitor lo rechazó (firma, nodo, payload): reintentar no sirve
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = type(e).__name__
        time.sleep(2 * attempt)
    print(f"monitor_notify: NO se pudo avisar al monitor ({last})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
