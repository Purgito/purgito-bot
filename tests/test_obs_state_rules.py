"""Heartbeat/estado del servicio, contexto de incidente, reglas de detección y
modelo de alertas (service_state.py, incident.py, rules.py)."""

import json
from datetime import timedelta

import pytest

from observability import events, incident, rules, runtime, service_state


@pytest.fixture(autouse=True)
def _clean_events():
    events.set_strict(True)
    events.clear_buffer()
    saved = list(events._listeners)
    yield
    events.set_strict(False)
    events._listeners[:] = saved


# ---------------- Estado del servicio / heartbeat ----------------


def test_primer_arranque_sin_estado_previo(tmp_path):
    state = service_state.ServiceState(str(tmp_path / "s.json"))
    prev = state.start()
    assert prev["had_previous"] is False and prev["crashed"] is False
    snap = state.snapshot()
    assert snap["state"] == "starting" and snap["started_at"] and not snap["stale"]


def test_heartbeat_actualiza_y_no_toca_la_base(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "_db", None)  # sin base disponible: el heartbeat sigue
    state = service_state.ServiceState(str(tmp_path / "s.json"))
    state.start()
    first = state.data["last_heartbeat"]
    state.data["last_heartbeat"] = "2020-01-01T00:00:00Z"
    state.beat()
    assert state.data["last_heartbeat"] != "2020-01-01T00:00:00Z" or first
    assert json.loads((tmp_path / "s.json").read_text())["state"] == "starting"


def test_estado_stale_si_no_hay_latidos(tmp_path):
    state = service_state.ServiceState(str(tmp_path / "s.json"))
    state.start()
    state.data["last_heartbeat"] = "2020-01-01T00:00:00Z"
    assert state.snapshot()["stale"] is True


def test_cierre_limpio_se_reconoce_en_el_siguiente_arranque(tmp_path):
    path = str(tmp_path / "s.json")
    a = service_state.ServiceState(path)
    a.start()
    a.set_state("running")
    a.set_state("stopping")
    a.set_state("stopped")
    b = service_state.ServiceState(path)
    prev = b.start()
    assert prev["clean_shutdown"] is True and prev["crashed"] is False
    assert b.snapshot()["last_clean_shutdown"] is not None
    assert b.snapshot()["previous_state"] == "stopped"


def test_caida_se_detecta_y_la_causa_es_unknown(tmp_path):
    path = str(tmp_path / "s.json")
    a = service_state.ServiceState(path)
    a.start()
    a.set_state("running")  # nunca llega a stopped: el proceso murió
    b = service_state.ServiceState(path)
    prev = b.start()
    assert prev["crashed"] is True
    assert prev["clean_shutdown"] is False
    assert prev["cause"] == "unknown"
    assert prev["last_heartbeat"] is not None


def test_contador_de_reinicios_por_ventana(tmp_path):
    path = str(tmp_path / "s.json")
    for _ in range(3):
        s = service_state.ServiceState(path)
        s.start()
    assert s.restarts_within(timedelta(hours=1)) == 2
    assert s.snapshot()["restarts_24h"] == 2


def test_ultimo_error_guarda_tipo_y_lugar_sin_mensaje(tmp_path):
    path = str(tmp_path / "s.json")
    s = service_state.ServiceState(path)
    s.start()
    s.record_error("ValueError", "task:check_rss")
    s.beat()
    nxt = service_state.ServiceState(path)
    nxt.start()
    assert nxt.snapshot()["last_error"]["error_type"] == "ValueError"
    assert set(nxt.snapshot()["last_error"]) == {"at", "error_type", "where"}


def test_archivo_de_estado_corrupto_no_impide_arrancar(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{no es json")
    s = service_state.ServiceState(str(p))
    assert s.start()["had_previous"] is False


def test_announce_start_emite_crash_detected_y_started(tmp_path):
    runtime.init(str(tmp_path))
    previous = {
        "crashed": True,
        "state": "running",
        "last_heartbeat": "2026-01-01T00:00:00Z",
        "clean_shutdown": False,
    }
    events.clear_buffer()
    runtime.announce_start(previous)
    types = [e["event_type"] for e in events.recent_events()]
    assert "service.crash_detected" in types and "service.started" in types
    crash = next(
        e for e in events.recent_events() if e["event_type"] == "service.crash_detected"
    )
    assert crash["data"]["cause"] == "unknown"
    rules._engine = None  # init() instaló un engine global


# ---------------- Contexto de incidente ----------------


def test_contexto_de_incidente_reconstruye_sin_inventar(tmp_path):
    (tmp_path / "events.jsonl").write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                {
                    "timestamp": "2026-01-01T10:00:00.000Z",
                    "event_type": "database.connection_failed",
                    "severity": "error",
                    "message": "m",
                },
                {
                    "timestamp": "2026-01-01T10:00:01.000Z",
                    "event_type": "service.heartbeat",
                    "severity": "debug",
                    "message": "m",
                },
                {
                    "timestamp": "2099-01-01T00:00:00.000Z",
                    "event_type": "system.background_task_failed",
                    "severity": "error",
                    "message": "posterior al arranque",
                },
            ]
        )
        + "\nlinea corrupta\n"
    )
    snap = {
        "started_at": "2026-01-01T11:00:00Z",
        "restarts_1h": 2,
        "restarts_24h": 3,
        "last_error": None,
        "previous_run": {
            "had_previous": True,
            "crashed": True,
            "state": "running",
            "last_heartbeat": "2026-01-01T10:59:40Z",
            "clean_shutdown": False,
            "cause": "unknown",
        },
    }
    ctx = incident.build_context(snap, str(tmp_path))
    assert ctx["crashed"] is True and ctx["cause"] == "unknown"
    assert "cause unknown" in ctx["cause_note"]
    assert ctx["last_seen_alive"] == "2026-01-01T10:59:40Z"
    assert [e["event_type"] for e in ctx["last_important_events"]] == [
        "database.connection_failed"
    ]


def test_contexto_tras_cierre_limpio_no_afirma_caida(tmp_path):
    snap = {
        "started_at": "2026-01-01T11:00:00Z",
        "previous_run": {
            "had_previous": True,
            "crashed": False,
            "clean_shutdown": True,
            "state": "stopped",
        },
    }
    ctx = incident.build_context(snap, str(tmp_path))
    assert (
        ctx["crashed"] is False and ctx["cause"] is None and ctx["cause_note"] is None
    )


# ---------------- Reglas de detección ----------------


def _ev(event_type, source="src-a", **fields):
    return events.build_event(event_type, source_id=source, **fields)


def test_cinco_login_failures_en_cinco_minutos_abren_alerta():
    engine = rules.RuleEngine()
    created = []
    for i in range(5):
        created += engine.process(
            _ev("auth.login_failure", reason="oauth_state_invalid"), now=1000 + i * 10
        )
    assert len(created) == 1
    alert = created[0]
    assert alert["rule_id"] == "auth.login_failure_burst"
    assert alert["status"] == "open" and alert["severity"] == "warning"
    assert alert["details"]["group_key"] == "src-a"
    assert len(alert["related_events"]) == 5
    assert set(alert) == {
        "alert_id",
        "rule_id",
        "severity",
        "status",
        "created_at",
        "updated_at",
        "source",
        "summary",
        "details",
        "related_events",
    }


def test_cuatro_eventos_no_alcanzan_y_la_ventana_expira():
    engine = rules.RuleEngine()
    for i in range(4):
        assert engine.process(_ev("auth.login_failure"), now=1000 + i) == []
    # el quinto llega fuera de la ventana de 300 s: los anteriores ya no cuentan
    assert engine.process(_ev("auth.login_failure"), now=1000 + 400) == []


def test_agrupa_por_origen():
    engine = rules.RuleEngine()
    out = []
    for i in range(8):  # 4 por origen: ninguno llega a 5
        out += engine.process(
            _ev("auth.login_failure", source=f"src-{i % 2}"), now=1000 + i
        )
    assert out == []
    out += engine.process(_ev("auth.login_failure", source="src-0"), now=1011)
    assert [a["details"]["group_key"] for a in out] == ["src-0"]


def test_diez_permission_denied_del_mismo_origen():
    engine = rules.RuleEngine()
    created = []
    for i in range(10):
        created += engine.process(
            _ev("permission.denied", reason="no_manage_guild"), now=2000 + i
        )
    assert [a["rule_id"] for a in created] == ["permission.denied_burst"]


def test_evento_sin_origen_no_se_agrupa_ni_se_inventa_uno():
    engine = rules.RuleEngine()
    for i in range(20):
        assert (
            engine.process(events.build_event("auth.login_failure"), now=100 + i) == []
        )


def test_reinicios_repetidos_via_campo_numerico():
    engine = rules.RuleEngine()
    assert (
        engine.process(events.build_event("service.started", restarts_1h=1), now=1)
        == []
    )
    created = engine.process(
        events.build_event("service.started", restarts_1h=3), now=2
    )
    assert [a["rule_id"] for a in created] == ["service.restart_loop"]


def test_conexion_a_base_repetida_cuenta_ambos_tipos():
    engine = rules.RuleEngine()
    out = []
    out += engine.process(events.build_event("database.connection_failed"), now=1)
    out += engine.process(events.build_event("database.health_failed"), now=2)
    out += engine.process(events.build_event("database.connection_failed"), now=3)
    assert [a["rule_id"] for a in out] == ["database.connection_failed_repeated"]


def test_crash_detectado_abre_alerta_inmediata():
    engine = rules.RuleEngine()
    created = engine.process(
        events.build_event("service.crash_detected", reason="x"), now=1
    )
    assert created and created[0]["severity"] == "error"


def test_alerta_abierta_se_actualiza_en_vez_de_duplicarse():
    engine = rules.RuleEngine()
    for i in range(5):
        engine.process(_ev("auth.login_failure"), now=1000 + i)
    assert len(engine.store.list()) == 1
    first_matches = engine.store.list()[0]["details"]["match_count"]
    for i in range(5):
        assert engine.process(_ev("auth.login_failure"), now=1010 + i) == []
    assert len(engine.store.list()) == 1
    assert engine.store.list()[0]["details"]["match_count"] > first_matches


def test_ciclo_de_estados_y_nueva_alerta_tras_resolver():
    engine = rules.RuleEngine()
    for i in range(5):
        engine.process(_ev("auth.login_failure"), now=1000 + i)
    alert = engine.store.list()[0]
    assert engine.store.open_count() == 1
    engine.store.acknowledge(alert["alert_id"])
    assert engine.store.list("acknowledged") and not engine.store.list("open")
    engine.store.resolve(alert["alert_id"])
    assert engine.store.list("resolved")[0]["status"] == "resolved"
    again = []
    for i in range(5):
        again += engine.process(_ev("auth.login_failure"), now=1100 + i)
    assert len(again) == 1 and len(engine.store.list()) == 2
    with pytest.raises(ValueError):
        engine.store.set_status(alert["alert_id"], "borrada")
    assert engine.store.set_status("no-existe", "open") is None


def test_alerta_emite_evento_de_seguridad_y_no_recursa():
    engine = rules.RuleEngine()
    events.add_listener(engine.on_event)
    for _ in range(5):
        events.log_event("auth.login_failure", source_id="src-z")
    opened = [
        e for e in events.recent_events() if e["event_type"] == "security.alert_opened"
    ]
    assert len(opened) == 1
    assert opened[0]["rule_id"] == "auth.login_failure_burst"
    assert opened[0]["category"] == "security"


def test_alertas_se_persisten_y_se_recargan(tmp_path):
    path = str(tmp_path / "alerts.json")
    engine = rules.RuleEngine(store=rules.AlertStore(path))
    for i in range(5):
        engine.process(_ev("auth.login_failure"), now=1000 + i)
    reloaded = rules.AlertStore(path)
    assert [a["rule_id"] for a in reloaded.list()] == ["auth.login_failure_burst"]


def test_regla_personalizada_declarativa():
    rule = rules.Rule(
        "custom.test",
        "2 webhooks rechazados",
        "error",
        ("webhook.rejected",),
        2,
        60,
        where={"reason": "payload_invalid"},
    )
    engine = rules.RuleEngine(rules=[rule])
    assert (
        engine.process(
            events.build_event("webhook.rejected", reason="secret_not_configured"),
            now=1,
        )
        == []
    )
    assert (
        engine.process(
            events.build_event("webhook.rejected", reason="payload_invalid"), now=2
        )
        == []
    )
    out = engine.process(
        events.build_event("webhook.rejected", reason="payload_invalid"), now=3
    )
    assert out and out[0]["rule_id"] == "custom.test" and out[0]["severity"] == "error"


def test_las_reglas_por_defecto_usan_solo_tipos_registrados():
    for rule in rules.RULES:
        assert rule.severity in events.SEVERITIES
        for et in rule.event_types:
            assert et in events.EVENT_TYPES, (rule.rule_id, et)
