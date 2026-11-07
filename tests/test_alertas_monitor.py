"""Alertas hacia Purgito Monitor: plazos de privacidad (cliente del bot) y fallos de respaldo (OnFailure)."""

import asyncio
import importlib.util
import json
import pathlib
import re
from unittest.mock import patch

from cogs import privacy as privacy_cog
from observability import events as obs_events
from observability import monitor as obs_monitor

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "monitor_notify", _ROOT / "deploy" / "monitor_notify.py"
)
monitor_notify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(monitor_notify)


def test_los_avisos_de_privacidad_viajan_al_monitor_como_system_warning_critico():
    seen = []
    obs_events.add_listener(seen.append)
    try:
        for kind, sev in (
            ("failed", "error"),
            ("due_soon", "warning"),
            ("overdue", "critical"),
        ):
            alert = {
                "id": 12,
                "kind": kind,
                "status": "failed",
                "created_at": "x",
                "due_at": "2026-12-01 00:00:00",
                "attempts": 2,
            }
            assert asyncio.run(privacy_cog._send_alert(alert)) is True
    finally:
        obs_events.remove_listener(seen.append)
    ev = [e for e in seen if e["event_type"].startswith("privacy.request_")]
    assert [e["severity"] for e in ev] == ["error", "warning", "critical"]
    for e in ev:
        assert "#12" in e["message"] and "user" not in json.dumps(e).lower().replace(
            "user_corpus", ""
        )
        assert obs_monitor._INTERNAL_MAP[e["event_type"]] == "system.warning"
        assert (
            obs_monitor.MonitorClient.make_event
        )  # el tipo mapeado es de los que el monitor acepta
        assert (
            obs_monitor._INTERNAL_MAP[e["event_type"]]
            in obs_monitor.SUPPORTED_EVENT_TYPES
        )


def test_el_aviso_de_derechos_vencidos_esta_en_la_taxonomia_y_mapeado():
    assert obs_events.EVENT_TYPES["privacy.rights_overdue"].severity == "critical"
    assert obs_monitor._INTERNAL_MAP["privacy.rights_overdue"] == "system.warning"


def test_monitor_notify_firma_igual_que_el_cliente_del_bot_y_cumple_el_contrato(
    monkeypatch,
):
    assert monitor_notify.sign("s3cret", "1700000000", b"{}") == obs_monitor.sign(
        "s3cret", "1700000000", b"{}"
    )
    sent = {}

    class _Resp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        sent["url"], sent["body"], sent["headers"] = (
            req.full_url,
            req.data,
            {k.lower(): v for k, v in req.header_items()},
        )
        return _Resp()

    monkeypatch.setenv("MONITOR_BASE_URL", "https://monitor.example")
    monkeypatch.setenv("MONITOR_NODE_ID", "purgito-prod-01")
    monkeypatch.setenv("MONITOR_SHARED_SECRET", "s3cret")
    with patch.object(monitor_notify.urllib.request, "urlopen", fake_urlopen):
        assert monitor_notify.main(["purgito-backup.service"]) == 0
    ev = json.loads(sent["body"])
    assert sent["url"] == "https://monitor.example/v1/events"
    assert (
        ev["event_type"] == "system.warning"
        and ev["severity"] == "critical"
        and ev["reason"] == "backup_failed"
    )
    assert (
        re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", ev["event_id"])
        and 1 <= len(ev["message"]) <= 1024
    )
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", ev["service"])
    ts = sent["headers"]["x-purgito-timestamp"]
    assert sent["headers"]["x-purgito-signature"] == obs_monitor.sign(
        "s3cret", ts, sent["body"]
    )
    assert b"s3cret" not in sent["body"]


def test_monitor_notify_sin_https_o_sin_secreto_no_envia(monkeypatch, capsys):
    monkeypatch.setenv("MONITOR_BASE_URL", "http://inseguro.example")
    monkeypatch.setenv("MONITOR_NODE_ID", "n")
    monkeypatch.setenv("MONITOR_SHARED_SECRET", "x")
    assert monitor_notify.main(["purgito-ledger.service"]) == 2
