"""Integración HTTP de la capa de observabilidad: request ids, /health,
/health/ready, /health/details, /metrics, /internal/alerts y los eventos de
seguridad que emite webapi.py. Usa la app aiohttp real (middlewares + rutas de
verdad), con bot y base falsos."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import webapi
from observability import events, metrics, rules, runtime

TOKEN = "obs-test-token-123456"


class FakeBot:
    latency = 0.042
    guilds = [object(), object(), object()]

    def __init__(self, ready=True):
        self._ready = ready

    def is_ready(self):
        return self._ready


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    events.set_strict(True)
    events.clear_buffer()
    saved = list(events._listeners)
    runtime.reset_readiness_cache()
    monkeypatch.setattr(webapi, "OBSERVABILITY_TOKEN", TOKEN)
    ok = {"ping": True}

    async def ping():
        if not ok["ping"]:
            raise ConnectionRefusedError("postgresql://u:pgsecret99@h/db caído")

    monkeypatch.setattr(webapi, "_db_ping", ping)
    yield ok
    events.set_strict(False)
    events._listeners[:] = saved
    runtime.reset_readiness_cache()


def _app(bot=None):
    app = web.Application(
        middlewares=[webapi._observability_middleware, webapi._error_middleware]
    )
    app["bot"] = bot or FakeBot()
    app.router.add_get("/health", webapi._api_health)
    app.router.add_get("/health/ready", webapi._api_health_ready)
    app.router.add_get("/health/details", webapi._api_health_details)
    app.router.add_get("/metrics", webapi._api_metrics)
    app.router.add_get("/internal/alerts", webapi._api_internal_alerts)

    async def boom(request):
        raise RuntimeError("fallo interno con secreto pgsecret99")

    app.router.add_get("/api/boom", boom)
    return app


def _run(coro_fn, bot=None):
    async def go():
        async with TestClient(TestServer(_app(bot))) as client:
            return await coro_fn(client)

    return asyncio.run(go())


AUTH = {"Authorization": f"Bearer {TOKEN}"}


# ---------------- request id ----------------


def test_respuesta_trae_x_request_id_generado():
    async def go(c):
        r = await c.get("/health")
        return r.status, r.headers.get("X-Request-ID"), await r.json()

    status, rid, body = _run(go)
    assert status == 200 and body == {"ok": True}  # /health no cambió
    assert rid and len(rid) == 16


def test_x_request_id_entrante_valido_se_respeta_e_invalido_se_reemplaza():
    async def go(c):
        good = await c.get("/health", headers={"X-Request-ID": "trace-abcdef123456"})
        bad = await c.get("/health", headers={"X-Request-ID": "x\ty"})
        return good.headers["X-Request-ID"], bad.headers["X-Request-ID"]

    good, bad = _run(go)
    assert good == "trace-abcdef123456"
    assert bad != "x\ty" and len(bad) == 16


def test_excepcion_no_atajada_correlaciona_evento_y_respuesta():
    async def go(c):
        r = await c.get("/api/boom", headers={"X-Request-ID": "corr-0001abcd"})
        return r.status, r.headers["X-Request-ID"], await r.json()

    status, rid, body = _run(go)
    assert status == 500 and rid == "corr-0001abcd"
    assert "pgsecret99" not in json.dumps(body)
    ev = next(
        e
        for e in events.recent_events()
        if e["event_type"] == "system.unhandled_exception"
    )
    assert ev["request_id"] == "corr-0001abcd"
    assert ev["error_type"] == "RuntimeError"
    assert "pgsecret99" not in json.dumps(ev)  # ni el mensaje de la excepción


# ---------------- readiness ----------------


def test_ready_200_cuando_discord_y_base_responden():
    async def go(c):
        r = await c.get("/health/ready")
        return r.status, await r.json()

    assert _run(go) == (200, {"ready": True})


def test_ready_503_sin_detalles_y_con_evento_si_la_base_falla(_clean):
    _clean["ping"] = False

    async def go(c):
        r = await c.get("/health/ready")
        return r.status, await r.json()

    status, body = _run(go)
    assert status == 503 and body == {"ready": False}  # nada que filtrar al público
    ev = next(
        e for e in events.recent_events() if e["event_type"] == "database.health_failed"
    )
    assert ev["error_type"] == "ConnectionRefusedError"
    assert "pgsecret99" not in json.dumps(ev)


def test_ready_503_si_discord_no_esta_listo():
    async def go(c):
        return (await c.get("/health/ready")).status

    assert _run(go, bot=FakeBot(ready=False)) == 503


def test_ready_se_cachea_unos_segundos(_clean):
    calls = {"n": 0}

    async def ping():
        calls["n"] += 1

    webapi._db_ping = ping

    async def go(c):
        for _ in range(5):
            await c.get("/health/ready")

    _run(go)
    assert calls["n"] == 1


# ---------------- endpoints internos ----------------


@pytest.mark.parametrize("path", ["/health/details", "/metrics", "/internal/alerts"])
def test_internos_sin_token_configurado_no_existen(monkeypatch, path):
    monkeypatch.setattr(webapi, "OBSERVABILITY_TOKEN", "")

    async def go(c):
        return (await c.get(path, headers=AUTH)).status

    assert _run(go) == 404


@pytest.mark.parametrize("path", ["/health/details", "/metrics", "/internal/alerts"])
def test_internos_exigen_bearer_correcto(path):
    async def go(c):
        none = await c.get(path)
        bad = await c.get(path, headers={"Authorization": "Bearer otro-token-distinto"})
        ok = await c.get(path, headers=AUTH)
        return none.status, bad.status, ok.status

    assert _run(go) == (401, 401, 200)
    denied = [
        e for e in events.recent_events() if e["event_type"] == "permission.denied"
    ]
    assert len(denied) == 2 and denied[0]["reason"] == "observability_token_invalid"


@pytest.mark.parametrize("header", ["CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"])
def test_internos_no_responden_si_llegaron_por_el_proxy(header):
    async def go(c):
        r = await c.get("/metrics", headers={**AUTH, header: "198.51.100.7"})
        return r.status

    assert _run(go) == 404


def test_details_no_filtra_datos_sensibles():
    async def go(c):
        r = await c.get("/health/details", headers=AUTH)
        return await r.json(), await (
            await c.get("/health/details", headers=AUTH)
        ).text()

    body, raw = _run(go)
    assert body["ready"]["ready"] is True
    assert body["discord"] == {"latency_ms": 42, "guilds": 3}
    assert body["service"] == "purgito-bot"
    for forbidden in ("Traceback", TOKEN, "guild_id", "DISCORD_TOKEN"):
        assert forbidden not in raw


# ---------------- métricas ----------------


def test_metrics_expone_las_metricas_calculables():
    async def go(c):
        await c.get("/health")
        r = await c.get("/metrics", headers=AUTH)
        return r.status, r.headers["Content-Type"], await r.text()

    status, ctype, text = _run(go)
    assert status == 200 and ctype.startswith("text/plain")
    for name in (
        "purgito_up 1.0",
        "purgito_uptime_seconds",
        "purgito_guilds 3.0",
        "purgito_discord_latency_seconds 0.042",
        "purgito_memory_bytes",
        "purgito_http_requests_total",
        "purgito_http_request_duration_seconds_bucket",
        "purgito_errors_total",
        "purgito_command_total",
        "purgito_background_failures_total",
        "purgito_db_connection_errors_total",
    ):
        assert name in text, name
    assert 'route="/health"' in text


def test_metrics_usa_ruta_canonica_no_la_url_real():
    async def go(c):
        await c.get("/ruta/que/no/existe/12345")
        r = await c.get("/metrics", headers=AUTH)
        return await r.text()

    text = _run(go)
    assert "12345" not in text and 'route="unmatched"' in text


def test_hooks_alimentan_contadores_y_ultimo_error():
    from observability import hooks

    before = (
        metrics.REGISTRY.get_sample_value("purgito_command_total", {"result": "error"})
        or 0
    )
    hooks.command_failed("imitar", ValueError("x"))
    hooks.command_ok()
    hooks.background_failed("check_rss", RuntimeError("x"))
    assert (
        metrics.REGISTRY.get_sample_value("purgito_command_total", {"result": "error"})
        == before + 1
    )
    assert (
        metrics.REGISTRY.get_sample_value(
            "purgito_background_failures_total", {"task": "check_rss"}
        )
        >= 1
    )
    types = {e["event_type"] for e in events.recent_events()}
    assert {"discord.command_error", "system.background_task_failed"} <= types


def test_listener_de_metricas_cuenta_eventos_y_errores():
    events.add_listener(metrics.count_event)
    before = (
        metrics.REGISTRY.get_sample_value(
            "purgito_events_total",
            {"event_type": "database.connection_failed", "severity": "error"},
        )
        or 0
    )
    events.log_event("database.connection_failed")
    assert (
        metrics.REGISTRY.get_sample_value(
            "purgito_events_total",
            {"event_type": "database.connection_failed", "severity": "error"},
        )
        == before + 1
    )


def test_alertas_internas_se_listan_y_filtran(tmp_path):
    engine = rules.RuleEngine(store=rules.AlertStore(str(tmp_path / "a.json")))
    for i in range(5):
        engine.process(
            events.build_event("auth.login_failure", source_id="s1"), now=100 + i
        )
    rules._engine = engine

    async def go(c):
        all_ = await (await c.get("/internal/alerts", headers=AUTH)).json()
        resolved = await (
            await c.get("/internal/alerts?status=resolved", headers=AUTH)
        ).json()
        bad = await c.get("/internal/alerts?status=raro", headers=AUTH)
        return all_, resolved, bad.status

    try:
        all_, resolved, bad = _run(go)
    finally:
        rules._engine = None
    assert len(all_["alerts"]) == 1 and resolved["alerts"] == [] and bad == 400


# ---------------- eventos de seguridad en webapi ----------------


def test_rate_limit_emite_evento_con_origen_hasheado_y_throttle():
    store = webapi._rate_post
    store.clear()
    webapi._rate_event_last.clear()
    for _ in range(12):
        webapi._rate_ok(store, "203.0.113.50", 3)
    evs = [
        e for e in events.recent_events() if e["event_type"] == "rate_limit.triggered"
    ]
    assert len(evs) == 1  # throttle: un solo evento por ráfaga
    assert evs[0]["data"]["bucket"] == "post"
    assert "203.0.113.50" not in json.dumps(evs[0])
    assert len(evs[0]["source_id"]) == 12


def test_permission_denied_en_check_guild_access(monkeypatch):
    async def fake_manage(request, force=False):
        return [{"id": "999"}]

    async def fake_session(request):
        return {"user_id": "42"}

    monkeypatch.setattr(webapi, "_fetch_manage_guilds", fake_manage)
    monkeypatch.setattr(webapi, "get_session", fake_session)
    req = SimpleNamespace(
        headers={}, remote="198.51.100.4", method="PUT", path="/api/guilds/5/x"
    )
    resp = asyncio.run(webapi.check_guild_access(req, 5))
    assert resp.status == 403
    ev = next(
        e for e in events.recent_events() if e["event_type"] == "permission.denied"
    )
    assert (ev["guild_id"], ev["user_id"], ev["reason"]) == (
        5,
        "42",
        "not_guild_manager",
    )
    assert ev["category"] == "security" and ev["source_id"]


def test_login_failure_por_state_invalido(monkeypatch):
    class Session(dict):
        pass

    async def fake_session(request):
        s = Session()
        s["oauth_state"] = "esperado"
        return s

    monkeypatch.setattr(webapi, "get_session", fake_session)
    webapi._rate_auth_callback.clear()
    req = SimpleNamespace(
        headers={"CF-Connecting-IP": "198.51.100.9"},
        remote="127.0.0.1",
        query={"code": "c", "state": "otro"},
    )
    with pytest.raises(web.HTTPFound):
        asyncio.run(webapi._auth_callback(req))
    ev = next(
        e for e in events.recent_events() if e["event_type"] == "auth.login_failure"
    )
    assert ev["reason"] == "oauth_state_invalid" and ev["result"] == "failure"
    assert "198.51.100.9" not in json.dumps(ev)


def test_webhook_firma_invalida_emite_evento(monkeypatch):
    class Req:
        headers = {}
        remote = "198.51.100.77"

        async def read(self):
            return b"{}"

    def bad(body, headers, secret):
        raise webapi.WebhookVerificationError("firma")

    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", "whsec_test_value_1")
    monkeypatch.setattr(webapi, "validate_event", bad)
    webapi._rate_webhook_polar.clear()
    resp = asyncio.run(webapi._webhook_polar(Req()))
    assert resp.status == 403
    ev = next(
        e
        for e in events.recent_events()
        if e["event_type"] == "webhook.signature_invalid"
    )
    assert ev["endpoint"] == "/webhooks/polar" and ev["category"] == "security"


def test_webhook_sin_secreto_se_rechaza_con_evento(monkeypatch):
    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", "")
    resp = asyncio.run(webapi._webhook_polar(SimpleNamespace(headers={}, remote="x")))
    assert resp.status == 503
    ev = next(
        e for e in events.recent_events() if e["event_type"] == "webhook.rejected"
    )
    assert ev["reason"] == "secret_not_configured"


def test_accion_admin_sensible_emite_evento_y_la_comun_no(monkeypatch):
    logged = []

    async def fake_log_audit(*a):
        logged.append(a)

    async def fake_session(request):
        return {"user_id": "7", "username": "admin"}

    monkeypatch.setattr(webapi, "log_audit", fake_log_audit)
    monkeypatch.setattr(webapi, "get_session", fake_session)
    asyncio.run(webapi._log_audit(None, 11, "prefix.set", detail="?? contenido libre"))
    asyncio.run(webapi._log_audit(None, 11, "gifs.add", detail="x"))
    assert len(logged) == 2  # audit_log intacto: ambas acciones
    admin = [
        e for e in events.recent_events() if e["event_type"] == "security.admin_action"
    ]
    assert len(admin) == 1 and admin[0]["data"]["action"] == "prefix.set"
    assert "contenido libre" not in json.dumps(admin[0])


def test_sesion_revocada_emite_evento(monkeypatch):
    async def revoked(sid):
        return True

    monkeypatch.setattr(webapi, "is_session_revoked", revoked)
    ok = asyncio.run(webapi._session_logged_in({"user_id": "9", "sid": "abc"}))
    assert ok is False
    ev = next(
        e for e in events.recent_events() if e["event_type"] == "auth.session_revoked"
    )
    assert ev["user_id"] == "9"
