"""Capa de observabilidad: modelo de eventos, schema, redacción de secretos y
correlation ids (src/observability/events.py, redaction.py, logging_setup.py)."""

import json
import logging
import os
import re
import traceback

import pytest

from observability import events, logging_setup, redaction

VALORES_FICTICIOS = {
    "DISCORD_TOKEN": "MTIzNDU2Nzg5MDEyMzQ1Njc4.GabcDE.abcdefghijklmnopqrstuvwxyz123456",
    "POLAR_ACCESS_TOKEN": "polar_oat_ZZZZsupersecretvalue0001",
    "SESSION_SECRET": "session-secret-value-xyz-0002",
    "POLAR_WEBHOOK_SECRET": "whsec_webhooksecretvalue0003",
    "DATABASE_URL": "postgresql://purgito:pgpassword0004@127.0.0.1:5432/purgito",
    "OBSERVABILITY_TOKEN": "obs-token-value-0005",
}


@pytest.fixture(autouse=True)
def _clean_events(monkeypatch):
    events.set_strict(True)
    events.clear_buffer()
    saved = list(events._listeners)
    yield
    events.set_strict(False)
    events._listeners[:] = saved


@pytest.fixture
def env_ficticio(monkeypatch):
    for k, v in VALORES_FICTICIOS.items():
        monkeypatch.setenv(k, v)
    return VALORES_FICTICIOS


@pytest.fixture
def event_files(tmp_path):
    """Instala los handlers JSONL en un directorio temporal y los quita después."""
    logger = logging.getLogger(events.EVENT_LOGGER_NAME)
    before = list(logger.handlers)
    logger._purgito_files = False
    logging_setup.setup_event_files(str(tmp_path))
    yield tmp_path
    for h in list(logger.handlers):
        if h not in before:
            logger.removeHandler(h)
            h.close()
    logger._purgito_files = False


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------- Creación y schema ----------------


def test_evento_tiene_todos_los_campos_obligatorios():
    e = events.log_event("service.started", restarts_1h=0)
    assert events.validate_event(e) == []
    for name in events.REQUIRED_FIELDS:
        assert e[name]
    assert e["timestamp"].endswith("Z")
    assert e["service"] == "purgito-bot"
    assert e["category"] == "app"


def test_campos_estandar_van_al_top_level_y_el_resto_a_data():
    e = events.log_event(
        "permission.denied",
        guild_id=1,
        user_id=2,
        reason="x",
        endpoint="/api/x",
        algo_nuevo="valor",
        vacio=None,
    )
    assert (e["guild_id"], e["user_id"], e["reason"], e["endpoint"]) == (
        1,
        2,
        "x",
        "/api/x",
    )
    assert e["data"] == {"algo_nuevo": "valor"}  # None se descarta
    assert events.validate_event(e) == []


def test_severidad_por_defecto_y_override():
    assert events.log_event("auth.login_failure")["severity"] == "warning"
    assert (
        events.log_event("auth.login_failure", severity="critical")["severity"]
        == "critical"
    )


def test_tipo_no_registrado_falla_en_strict_y_se_marca_en_produccion():
    with pytest.raises(ValueError):
        events.log_event("inventado.algo")
    events.set_strict(False)
    e = events.log_event("inventado.algo")
    assert e["data"]["schema_warning"] == "unregistered_event_type"


def test_severidad_invalida_en_strict():
    with pytest.raises(ValueError):
        events.log_event("service.started", severity="catastrofe")


def test_log_event_nunca_rompe_al_llamador_si_un_listener_explota():
    events.set_strict(False)

    def boom(_e):
        raise RuntimeError("listener roto")

    events.add_listener(boom)
    assert events.log_event("service.started") is not None


def test_validate_event_detecta_problemas():
    e = events.build_event("service.started")
    e.pop("host")
    e["campo_raro"] = 1
    e["timestamp"] = "2026-01-01T00:00:00+02:00"
    problems = events.validate_event(e)
    assert "falta host" in problems
    assert any("campo_raro" in p for p in problems)
    assert any("UTC" in p for p in problems)


def test_taxonomia_coincide_con_el_codigo():
    """Cada tipo registrado lo emite algún punto del código, y cada tipo que el
    código emite está registrado: nada de eventos fantasma en el catálogo."""
    root = os.path.dirname(os.path.dirname(__file__))
    pattern = re.compile(
        r"(?:log_event|\.security|security)\(\s*[\"']([a-z_]+\.[a-z_]+)[\"']"
        r"|event=([a-z_]+\.[a-z_]+)"
    )
    emitted = set()
    for base in ("src", os.path.join("deploy", "runbooks")):
        for dirpath, _d, files in os.walk(os.path.join(root, base)):
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(dirpath, f), encoding="utf-8").read()
                    for m in pattern.finditer(text):
                        emitted.add(m.group(1) or m.group(2))
    emitted = {e for e in emitted if "." in e}
    registered = set(events.EVENT_TYPES)
    assert emitted <= registered, f"emitidos sin registrar: {emitted - registered}"
    assert registered <= emitted, f"registrados sin emisor: {registered - emitted}"


def test_categoria_de_cada_tipo_es_valida():
    for name, spec in events.EVENT_TYPES.items():
        assert spec.category in (events.CATEGORY_APP, events.CATEGORY_SECURITY), name
        assert spec.severity in events.SEVERITIES, name
        assert name.split(".")[0] in {
            "system",
            "service",
            "discord",
            "auth",
            "permission",
            "database",
            "webhook",
            "rate_limit",
            "security",
            "deployment",
        }, name


# ---------------- Archivos JSONL / separación app vs seguridad ----------------


def test_eventos_de_seguridad_y_de_app_van_a_archivos_distintos(event_files):
    events.log_event("service.started")
    events.log_event("permission.denied", reason="no_manage_guild", user_id=7)
    app = _read_jsonl(event_files / "events.jsonl")
    sec = _read_jsonl(event_files / "security.jsonl")
    assert [e["event_type"] for e in app] == ["service.started"]
    assert [e["event_type"] for e in sec] == ["permission.denied"]
    for e in app + sec:
        assert events.validate_event(e) == []


def test_heartbeat_es_debug_y_solo_va_al_jsonl(event_files, caplog):
    with caplog.at_level(logging.INFO):
        events.log_event("service.heartbeat", uptime_seconds=5)
    assert (
        _read_jsonl(event_files / "events.jsonl")[0]["event_type"]
        == "service.heartbeat"
    )
    assert not [r for r in caplog.records if "service.heartbeat" in r.getMessage()]


def test_linea_legible_para_journald(event_files, caplog):
    with caplog.at_level(logging.INFO):
        events.log_event("auth.login_failure", reason="oauth_state_invalid")
    line = next(
        r.getMessage() for r in caplog.records if r.name == events.EVENT_LOGGER_NAME
    )
    assert line.startswith("event=auth.login_failure")
    assert "reason=oauth_state_invalid" in line


# ---------------- Redacción de secretos ----------------


def test_secretos_conocidos_no_aparecen_en_el_evento(env_ficticio, event_files):
    leak = " ".join(env_ficticio.values())
    events.log_event(
        "database.connection_failed",
        message=f"fallo con {leak}",
        reason=f"dsn={env_ficticio['DATABASE_URL']}",
        detalle={"anidado": env_ficticio["POLAR_ACCESS_TOKEN"]},
        lista=[env_ficticio["SESSION_SECRET"]],
    )
    blob = (event_files / "events.jsonl").read_text()
    for value in env_ficticio.values():
        assert value not in blob
    assert "pgpassword0004" not in blob
    assert redaction.REDACTED in blob


def test_secretos_no_aparecen_en_los_logs_de_texto(env_ficticio, caplog):
    """RedactingFormatter: mensaje y traceback pasan por scrub."""
    fmt = redaction.RedactingFormatter(logging_setup.TEXT_FORMAT)
    try:
        raise RuntimeError(f"auth falló con {env_ficticio['DISCORD_TOKEN']}")
    except RuntimeError:
        rec = logging.LogRecord(
            "x",
            logging.ERROR,
            __file__,
            1,
            f"url {env_ficticio['DATABASE_URL']} y {env_ficticio['POLAR_WEBHOOK_SECRET']}",
            None,
            __import__("sys").exc_info(),
        )
    out = fmt.format(rec)
    for value in env_ficticio.values():
        assert value not in out
    assert "pgpassword0004" not in out
    assert "Traceback" in out  # el traceback sigue estando, sin el secreto


def test_claves_sensibles_y_contenido_se_descartan(env_ficticio):
    e = events.log_event(
        "webhook.rejected",
        password="hunter2hunter2",
        access_token="abc",
        cookie="PURGITO_SESSION=zzzzzzzz",
        content="mensaje privado del usuario",
        message_content="otro mensaje",
        corpus="frase del corpus",
        reason="payload_invalid",
    )
    blob = json.dumps(e)
    assert "hunter2hunter2" not in blob
    assert "mensaje privado" not in blob and "frase del corpus" not in blob
    assert "zzzzzzzz" not in blob
    assert e["reason"] == "payload_invalid"


@pytest.mark.parametrize(
    "text",
    [
        "conn postgresql://u:p4ssw0rdlargo@db/x fin",
        "header Authorization: Bearer abcdefgh12345678",
        "age AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ",
        "cookie PURGITO_SESSION=gAAAAABmZZZZZZZZZZZZZZ; path=/",
        "client_secret=abcdef0123456789",
        "token MTIzNDU2Nzg5MDEyMzQ1Njc4.GabcDE.abcdefghijklmnopqrstuvwxyz1",
    ],
)
def test_patrones_de_credenciales_se_redactan(text):
    out = redaction.scrub(text)
    assert redaction.REDACTED in out
    for fragment in (
        "p4ssw0rdlargo",
        "abcdefgh12345678",
        "QQQQQQQQ",
        "gAAAAABm",
        "abcdef0123456789",
        "abcdefghijklmnopqrstuvwxyz1",
    ):
        assert fragment not in out


def test_valores_cortos_no_redactan_medio_log(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "dev")
    assert redaction.scrub("el dev server en modo dev") == "el dev server en modo dev"


def test_traceback_formateado_no_filtra_el_secreto(env_ficticio):
    try:
        raise ValueError(env_ficticio["SESSION_SECRET"])
    except ValueError:
        tb = traceback.format_exc()
    assert env_ficticio["SESSION_SECRET"] not in redaction.scrub(tb)


# ---------------- Correlation ids ----------------


def test_request_id_se_propaga_a_los_eventos():
    with events.request_scope("req-abcdef12") as rid:
        e1 = events.log_event("permission.denied")
        e2 = events.log_event("auth.login_failure")
    assert e1["request_id"] == e2["request_id"] == rid == "req-abcdef12"
    assert "request_id" not in events.log_event("service.started")


def test_request_id_explicito_gana_al_del_contexto():
    with events.request_scope("ctx-request-1"):
        e = events.log_event("permission.denied", request_id="otro-id-123")
    assert e["request_id"] == "otro-id-123"


@pytest.mark.parametrize(
    "bad", [None, "", "corto", "con espacios y\nsalto", "a" * 100, "x;y;z;w;q;r"]
)
def test_request_id_entrante_inseguro_se_reemplaza(bad):
    rid = events.accept_request_id(bad)
    assert re.fullmatch(r"[0-9a-f]{16}", rid)


def test_request_id_entrante_valido_se_respeta():
    assert events.accept_request_id("abc-DEF_12345678") == "abc-DEF_12345678"


def test_source_id_estable_y_no_reversible(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "unsecreto-largo-1")
    a = events.source_id("203.0.113.5")
    assert a == events.source_id("203.0.113.5") != events.source_id("203.0.113.6")
    assert "203" not in a and len(a) == 12
    assert events.source_id(None) is None
