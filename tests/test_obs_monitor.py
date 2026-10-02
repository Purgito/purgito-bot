"""Cliente del monitor externo (observability/monitor.py): firma HMAC,
heartbeat, eventos, fallo del monitor, backoff, outbox y lifecycle. Usa un
servidor HTTP falso local: nunca contacta a Railway."""

import asyncio
import json
import logging
import time
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import bot as bot_module
import webapi
from observability import events, metrics, monitor, redaction

SECRET = "monitor-shared-secret-value-9876"
NODE = "purgito-test-01"


@pytest.fixture(autouse=True)
def _clean():
    events.set_strict(True)
    events.clear_buffer()
    saved = list(events._listeners)
    monitor.reset()
    yield
    monitor.reset()
    events.set_strict(False)
    events._listeners[:] = saved


class FakeMonitor:
    """Receptor falso: verifica la firma como lo haría purgito-monitor."""

    def __init__(self, secret=SECRET):
        self.secret = secret
        self.requests = []  # (path, headers, body, verdict)
        self.status = 200
        self.seen_ids = set()
        self.skew = monitor.MAX_SKEW_SECONDS

    async def handle(self, request):
        body = await request.read()
        ok, reason = monitor.verify_signature(
            self.secret,
            request.headers.get(monitor.HEADER_TS),
            request.headers.get(monitor.HEADER_SIG),
            body,
            max_skew=self.skew,
        )
        self.requests.append((request.path, dict(request.headers), body, reason))
        if not ok:
            return web.json_response({"error": reason}, status=401)
        return web.json_response({"ok": True}, status=self.status)

    def bodies(self, path):
        return [
            json.loads(b) for p, _, b, r in self.requests if p == path and r == "ok"
        ]


async def _serve(fake=None):
    fake = fake or FakeMonitor()
    app = web.Application()
    app.router.add_post("/v1/heartbeat", fake.handle)
    app.router.add_post("/v1/events", fake.handle)
    server = TestServer(app)
    await server.start_server()
    return fake, server


def _client(server, tmp_path, **kw):
    kw.setdefault("secret", SECRET)
    url = str(server.make_url("")).rstrip("/") if server else "http://127.0.0.1:9"
    secret = kw.pop("secret")
    return monitor.MonitorClient(url, NODE, secret, 30, str(tmp_path), **kw)


# ---------------- HMAC ----------------


def test_firma_valida():
    body = b'{"a":1}'
    ts = str(int(time.time()))
    assert monitor.verify_signature(
        SECRET, ts, monitor.sign(SECRET, ts, body), body
    ) == (True, "ok")


def test_firma_invalida_o_secreto_distinto():
    body, ts = b"{}", str(int(time.time()))
    assert (
        monitor.verify_signature(SECRET, ts, "sha256=" + "0" * 64, body)[1]
        == "bad_signature"
    )
    assert (
        monitor.verify_signature(
            "otro-secreto-123", ts, monitor.sign(SECRET, ts, body), body
        )[1]
        == "bad_signature"
    )


def test_body_modificado_invalida_la_firma():
    ts = str(int(time.time()))
    sig = monitor.sign(SECRET, ts, b'{"status":"up"}')
    assert (
        monitor.verify_signature(SECRET, ts, sig, b'{"status":"dn"}')[1]
        == "bad_signature"
    )


def test_timestamp_expirado_o_futuro():
    body = b"{}"
    old = str(int(time.time()) - 301)
    assert (
        monitor.verify_signature(SECRET, old, monitor.sign(SECRET, old, body), body)[1]
        == "timestamp_expired"
    )
    future = str(int(time.time()) + 301)
    assert (
        monitor.verify_signature(
            SECRET, future, monitor.sign(SECRET, future, body), body
        )[1]
        == "timestamp_expired"
    )
    # el timestamp está firmado: cambiarlo no revive una firma vieja
    assert (
        monitor.verify_signature(
            SECRET, str(int(time.time())), monitor.sign(SECRET, old, body), body
        )[1]
        == "bad_signature"
    )


def test_secreto_ausente_o_cabeceras_faltantes():
    ts = str(int(time.time()))
    assert (
        monitor.verify_signature("", ts, monitor.sign("", ts, b"{}"), b"{}")[1]
        == "secret_missing"
    )
    assert monitor.verify_signature(SECRET, None, "x", b"{}")[1] == "missing_headers"
    assert monitor.verify_signature(SECRET, ts, None, b"{}")[1] == "missing_headers"
    assert monitor.verify_signature(SECRET, "no-num", "x", b"{}")[1] == "bad_timestamp"


# ---------------- Heartbeat ----------------


def test_heartbeat_firmado_y_pequeno(tmp_path):
    async def go():
        fake, server = await _serve()

        async def ping():
            return None

        bot = SimpleNamespace(latency=0.05)
        c = _client(server, tmp_path, bot=bot, db_ping=ping, version="abc1234")
        before = (
            metrics.REGISTRY.get_sample_value("purgito_monitor_last_success_timestamp")
            or 0
        )
        ok = await c.send_heartbeat()
        await c.stop()
        await server.close()
        return ok, fake, before

    ok, fake, before = asyncio.run(go())
    assert ok and fake.requests[0][3] == "ok"
    hb = fake.bodies("/v1/heartbeat")[0]
    assert {
        "node_id",
        "timestamp",
        "started_at",
        "uptime_seconds",
        "service",
        "status",
    } <= set(hb)
    assert hb["node_id"] == NODE and hb["service"] == "purgito" and hb["status"] == "up"
    assert (
        hb["discord_latency_ms"] == 50
        and hb["postgres_status"] == "ok"
        and hb["version"] == "abc1234"
    )
    assert hb["disk_free_bytes"] > 0
    assert len(fake.requests[0][2]) < 600  # pequeño
    raw = fake.requests[0][2].decode()
    for forbidden in (SECRET, "token", "cookie", "content", "corpus", "username"):
        assert (
            forbidden not in raw.lower()
            or forbidden == "token"
            and "token" not in raw.lower()
        )
    assert (
        metrics.REGISTRY.get_sample_value("purgito_monitor_last_success_timestamp")
        > before
    )


def test_heartbeat_reporta_postgres_caido(tmp_path):
    async def go():
        fake, server = await _serve()

        async def ping():
            raise ConnectionRefusedError("postgresql://u:pw@h/db")

        c = _client(server, tmp_path, db_ping=ping)
        await c.send_heartbeat()
        await c.stop()
        await server.close()
        return fake

    hb = asyncio.run(go()).bodies("/v1/heartbeat")[0]
    assert hb["postgres_status"] == "down" and "postgres_latency_ms" not in hb
    assert "pw" not in json.dumps(hb)


# ---------------- Eventos ----------------


def test_evento_se_envia_firmado_con_schema(tmp_path):
    async def go():
        fake, server = await _serve()
        c = _client(server, tmp_path)
        ev = c.make_event(
            "system.warning", "warning", "algo pasó", {"task": "check_rss"}
        )
        assert c.enqueue(ev)
        sent = await c.process_outbox_once()
        await c.stop()
        await server.close()
        return fake, ev, sent

    fake, ev, sent = asyncio.run(go())
    assert sent == 1
    got = fake.bodies("/v1/events")[0]
    assert got == ev
    assert set(got) == {
        "event_id",
        "node_id",
        "timestamp",
        "event_type",
        "severity",
        "service",
        "message",
        "metadata",
    }
    assert got["node_id"] == NODE and got["service"] == "purgito"


def test_tipo_de_evento_no_soportado(tmp_path):
    c = _client(None, tmp_path)
    with pytest.raises(ValueError):
        c.make_event("inventado.algo", "info", "x")


def test_deduplicacion_por_event_id(tmp_path):
    c = _client(None, tmp_path)
    ev = c.make_event("service.started", "info", "x")
    assert c.enqueue(ev) is True
    assert c.enqueue(dict(ev)) is False
    assert len(c.outbox) == 1


def test_reintento_conserva_el_mismo_event_id(tmp_path):
    async def go():
        fake, server = await _serve()
        fake.status = 503
        now = [time.time()]
        c = _client(server, tmp_path, clock=lambda: now[0])
        ev = c.make_event("security.alert", "warning", "x")
        c.enqueue(ev)
        assert await c.process_outbox_once() == 0  # 503 -> retry
        assert await c.process_outbox_once() == 0  # aún no toca (backoff)
        assert len(fake.requests) == 1
        now[0] += 6  # pasó el backoff de 5 s
        fake.status = 200
        assert await c.process_outbox_once() == 1
        await c.stop()
        await server.close()
        return fake, ev

    fake, ev = asyncio.run(go())
    ids = [json.loads(b)["event_id"] for _, _, b, _ in fake.requests]
    assert ids == [ev["event_id"], ev["event_id"]]


def test_evento_rechazado_con_4xx_se_descarta_sin_reintentar(tmp_path, caplog):
    async def go():
        fake, server = await _serve(FakeMonitor(secret="otro-secreto-distinto"))
        c = _client(server, tmp_path)  # firma con SECRET != el del receptor
        c.enqueue(c.make_event("service.started", "info", "x"))
        with caplog.at_level(logging.WARNING):
            await c.process_outbox_once()
        n = len(c.outbox)
        await c.stop()
        await server.close()
        return n, fake

    n, fake = asyncio.run(go())
    assert n == 0 and len(fake.requests) == 1 and fake.requests[0][3] == "bad_signature"
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "rejected" in text and SECRET not in text


def test_maximo_de_intentos_descarta(tmp_path):
    async def go():
        fake, server = await _serve()
        fake.status = 500
        fake.skew = 10**9  # el reloj de este test avanza horas
        now = [time.time()]
        c = _client(server, tmp_path, clock=lambda: now[0])
        c.enqueue(c.make_event("security.alert", "warning", "x"))
        for _ in range(monitor.MAX_ATTEMPTS[True] + 2):
            await c.process_outbox_once()
            now[0] += 400
        left = len(c.outbox)
        await c.stop()
        await server.close()
        return left, len(fake.requests)

    left, n = asyncio.run(go())
    assert left == 0 and n == monitor.MAX_ATTEMPTS[True]


# ---------------- Monitor caído ----------------


def test_monitor_apagado_no_rompe_ni_llena_el_log(tmp_path, caplog):
    async def go():
        c = _client(None, tmp_path)  # puerto 9: conexión rechazada
        c.enqueue(c.make_event("database.failure", "error", "x"))
        with caplog.at_level(logging.DEBUG):
            results = [await c.send_heartbeat() for _ in range(6)]
            await c.process_outbox_once()
        await c.stop()
        return results, c

    results, c = asyncio.run(go())
    assert results == [False] * 6
    assert c.failures >= 6
    warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name == monitor.log.name
    ]
    assert len(warnings) == 1 and "monitor unreachable" in warnings[0].getMessage()
    assert all(
        r.exc_info is None for r in caplog.records if r.name == monitor.log.name
    )  # sin tracebacks
    assert (
        metrics.REGISTRY.get_sample_value(
            "purgito_monitor_send_errors_total", {"kind": "heartbeat"}
        )
        >= 6
    )


def test_recuperacion_se_loguea_una_vez(tmp_path, caplog):
    async def go():
        fake, server = await _serve()
        c = _client(server, tmp_path)
        c.failures = 3
        with caplog.at_level(logging.INFO):
            await c.send_heartbeat()
        await c.stop()
        await server.close()
        return c

    c = asyncio.run(go())
    assert c.failures == 0
    assert any("reachable again" in r.getMessage() for r in caplog.records)


def test_backoff_exponencial_con_tope():
    assert [monitor.backoff_delay(n) for n in (1, 2, 3, 4)] == [5, 10, 20, 40]
    assert monitor.backoff_delay(50) == monitor.BACKOFF_CAP
    assert monitor.backoff_delay(0) == 5


def test_nunca_se_sigue_redirects(tmp_path):
    async def go():
        async def redirect(request):
            raise web.HTTPFound("http://127.0.0.1:9/robo")

        app = web.Application()
        app.router.add_post("/v1/heartbeat", redirect)
        server = TestServer(app)
        await server.start_server()
        c = _client(server, tmp_path)
        ok = await c.send_heartbeat()
        await c.stop()
        await server.close()
        return ok

    assert asyncio.run(go()) is False


# ---------------- Outbox ----------------


def test_outbox_persiste_solo_criticos_y_se_recarga(tmp_path):
    c = _client(None, tmp_path)
    crit = c.make_event("service.crash", "error", "x")
    minor = c.make_event("system.warning", "warning", "y")
    c.enqueue(crit)
    c.enqueue(minor)
    path = tmp_path / "monitor" / "outbox.jsonl"
    assert [
        json.loads(line)["event"]["event_id"] for line in path.read_text().splitlines()
    ] == [crit["event_id"]]
    c2 = _client(None, tmp_path)
    assert [i["event"]["event_id"] for i in c2.outbox.items] == [crit["event_id"]]


def test_outbox_se_borra_tras_confirmar_entrega(tmp_path):
    async def go():
        fake, server = await _serve()
        c = _client(server, tmp_path)
        c.enqueue(c.make_event("service.crash", "error", "x"))
        assert (tmp_path / "monitor" / "outbox.jsonl").exists()
        await c.process_outbox_once()
        await c.stop()
        await server.close()

    asyncio.run(go())
    assert not (tmp_path / "monitor" / "outbox.jsonl").exists()


def test_outbox_expira_y_respeta_limites(tmp_path):
    c = _client(None, tmp_path)
    old = c.make_event("service.crash", "error", "viejo")
    c.outbox.add(old, True, now=time.time() - monitor.CRITICAL_TTL - 10)
    c.outbox.prune(time.time())
    assert len(c.outbox) == 0  # expirado
    for i in range(monitor.OUTBOX_MAX_ITEMS + 30):
        c.enqueue(c.make_event("system.warning", "warning", f"m{i}"))
    assert len(c.outbox) <= monitor.OUTBOX_MAX_ITEMS
    big = _client(None, tmp_path / "big")
    for i in range(400):
        big.enqueue(big.make_event("security.alert", "warning", "x" * 2000))
    assert (
        tmp_path / "big" / "monitor" / "outbox.jsonl"
    ).stat().st_size <= monitor.OUTBOX_MAX_BYTES * 1.2


# ---------------- Mapeo de eventos internos ----------------


def test_listener_mapea_y_no_filtra_ids_personales(tmp_path):
    c = _client(None, tmp_path)
    events.add_listener(c.on_event)
    events.log_event(
        "database.connection_failed",
        error_type="OSError",
        reason="init_db",
        user_id=5,
        guild_id=6,
    )
    events.log_event("permission.denied", reason="x")  # no se mapea
    events.log_event("auth.login_failure", source_id="abc")  # no se mapea
    got = [i["event"] for i in c.outbox.items]
    assert [e["event_type"] for e in got] == ["database.failure"]
    assert got[0]["metadata"]["error_type"] == "OSError"
    assert "user_id" not in json.dumps(got[0]) and "guild_id" not in json.dumps(got[0])


def test_listener_cubre_shutdown_alerta_y_warning(tmp_path):
    c = _client(None, tmp_path)
    events.add_listener(c.on_event)
    events.log_event("service.stopping", signal="SIGTERM")
    events.log_event("security.alert_opened", rule_id="r1")
    events.log_event("system.background_task_failed", task="t")
    types = [i["event"]["event_type"] for i in c.outbox.items]
    assert types == ["service.shutdown", "security.alert", "system.warning"]


def test_throttle_evita_ruido_repetido(tmp_path):
    c = _client(None, tmp_path)
    events.add_listener(c.on_event)
    for _ in range(20):
        events.log_event("database.health_failed", error_type="X")
        events.log_event("system.background_task_failed", task="t")
    types = sorted(i["event"]["event_type"] for i in c.outbox.items)
    assert types == ["database.failure", "system.warning"]


# ---------------- Lifecycle ----------------


def test_arranque_limpio_envia_service_started(tmp_path):
    c = _client(None, tmp_path)
    c.announce_lifecycle("clean")
    ev = c.outbox.items[0]["event"]
    assert (
        ev["event_type"] == "service.started"
        and ev["metadata"]["previous_shutdown"] == "clean"
    )
    assert len(c.outbox) == 1


def test_primer_arranque(tmp_path):
    c = _client(None, tmp_path)
    c.announce_lifecycle("none")
    assert c.outbox.items[0]["event"]["metadata"]["previous_shutdown"] == "none"


def test_arranque_inesperado_no_inventa_la_causa(tmp_path):
    c = _client(None, tmp_path)
    c.announce_lifecycle("unexpected", last_seen_alive="2026-10-02T10:00:00Z")
    ev = c.outbox.items[0]["event"]
    assert ev["event_type"] == "service.restart" and ev["severity"] == "warning"
    assert ev["metadata"] == {
        "previous_shutdown": "unexpected",
        "cause": "unknown",
        "last_seen_alive": "2026-10-02T10:00:00Z",
    }
    assert "postgres" not in ev["message"].lower() and "desconocida" in ev["message"]
    assert (tmp_path / "monitor" / "outbox.jsonl").exists()  # es crítico


def test_reinicios_repetidos_agregan_service_crash(tmp_path):
    c = _client(None, tmp_path)
    c.announce_lifecycle("unexpected", restarts_1h=3)
    assert [i["event"]["event_type"] for i in c.outbox.items] == [
        "service.restart",
        "service.crash",
    ]


def test_report_lifecycle_deriva_previous_shutdown(monkeypatch):
    async def notice(_c):
        return None

    async def set_state(clean_shutdown):
        return None

    def run(prev, run_info):
        async def get_state():
            return prev

        monkeypatch.setattr(bot_module, "get_lifecycle_state", get_state)
        monkeypatch.setattr(bot_module, "set_lifecycle_state", set_state)
        monkeypatch.setattr(bot_module, "_send_lifecycle_notice", notice)
        monkeypatch.setattr(bot_module, "_lifecycle_reported", False)
        monkeypatch.setattr(bot_module, "_previous_run", run_info)
        monkeypatch.setattr(bot_module, "_previous_shutdown", "none")
        asyncio.run(bot_module._report_lifecycle())
        return bot_module._previous_shutdown

    now = "2026-10-02T10:00:00+00:00"
    assert run({"clean_shutdown": True, "updated_at": now}, {}) == "clean"
    assert run({"clean_shutdown": False, "updated_at": now}, {}) == "unexpected"
    assert run(None, {}) == "none"
    assert run(None, {"had_previous": True, "crashed": False}) == "clean"
    assert (
        run({"clean_shutdown": True, "updated_at": now}, {"crashed": True})
        == "unexpected"
    )


# ---------------- Configuración ----------------


@pytest.mark.parametrize(
    "url,node,secret,expected_ok",
    [
        ("https://mon.up.railway.app", "purgito-prod-01", SECRET, True),
        ("http://127.0.0.1:9000", "n1", SECRET, True),
        ("http://mon.example.com", "n1", SECRET, False),
        ("https://mon.example.com", "", SECRET, False),
        ("https://mon.example.com", "n 1;x", SECRET, False),
        ("https://mon.example.com", "n1", "", False),
        ("", "n1", SECRET, False),
        ("ftp://mon.example.com", "n1", SECRET, False),
    ],
)
def test_config_problem(url, node, secret, expected_ok):
    problem = monitor.config_problem(url, node, secret)
    assert (problem is None) is expected_ok
    assert SECRET not in (problem or "")


def test_desactivado_no_hace_nada(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "MONITOR_ENABLED", False)
    assert monitor.from_config(str(tmp_path)) is None and monitor.get() is None
    bot_module._start_monitor()  # no lanza
    assert not (tmp_path / "monitor").exists()


def test_config_invalida_se_desactiva_y_avisa_sin_secreto(
    monkeypatch, tmp_path, caplog
):
    import config

    monkeypatch.setattr(config, "MONITOR_ENABLED", True)
    monkeypatch.setattr(config, "MONITOR_BASE_URL", "http://publico.example.com")
    monkeypatch.setattr(config, "MONITOR_NODE_ID", "n1")
    monkeypatch.setattr(config, "MONITOR_SHARED_SECRET", SECRET)
    with caplog.at_level(logging.WARNING):
        assert monitor.from_config(str(tmp_path)) is None
    assert "https" in caplog.text and SECRET not in caplog.text


def test_config_valida_crea_cliente_y_registra_listener(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "MONITOR_ENABLED", True)
    monkeypatch.setattr(config, "MONITOR_BASE_URL", "https://mon.example.com/")
    monkeypatch.setattr(config, "MONITOR_NODE_ID", "purgito-prod-01")
    monkeypatch.setattr(config, "MONITOR_SHARED_SECRET", SECRET)
    c = monitor.from_config(str(tmp_path))
    assert (
        c is monitor.get()
        and c.base_url == "https://mon.example.com"
        and c.node_id == "purgito-prod-01"
    )
    assert c.on_event in events._listeners


# ---------------- Secretos ----------------


def test_el_secreto_nunca_aparece_en_logs_ni_eventos(tmp_path, caplog):
    c = _client(None, tmp_path)
    fmt = redaction.RedactingFormatter("%(message)s")
    rec = logging.LogRecord(
        "x", logging.ERROR, __file__, 1, f"falló con {SECRET}", None, None
    )
    assert SECRET not in fmt.format(rec)
    ev = c.make_event(
        "system.warning",
        "warning",
        f"msg {SECRET}",
        {"password": "x", "detail": SECRET},
    )
    assert SECRET not in json.dumps(ev)

    async def go():
        with caplog.at_level(logging.DEBUG):
            await c.send_heartbeat()

    asyncio.run(go())
    assert SECRET not in caplog.text


# ---------------- Ciclo completo en segundo plano ----------------


def test_start_stop_envia_heartbeat_y_evento_sin_bloquear(tmp_path):
    async def go():
        fake, server = await _serve()
        c = _client(server, tmp_path)
        c.interval = 0.05
        c.start()
        t0 = time.perf_counter()
        c.enqueue(c.make_event("service.started", "info", "x"))  # no bloquea
        assert time.perf_counter() - t0 < 0.05
        for _ in range(100):
            await asyncio.sleep(0.05)
            if fake.bodies("/v1/heartbeat") and fake.bodies("/v1/events"):
                break
        await c.stop()
        await server.close()
        return fake

    fake = asyncio.run(go())
    assert fake.bodies("/v1/heartbeat") and fake.bodies("/v1/events")


def test_flush_respeta_el_timeout_con_monitor_lento(tmp_path):
    async def go():
        async def slow(request):
            await asyncio.sleep(10)

        app = web.Application()
        app.router.add_post("/v1/events", slow)
        server = TestServer(app)
        await server.start_server()
        c = _client(server, tmp_path)
        c.enqueue(c.make_event("service.shutdown", "info", "x"))
        t0 = time.perf_counter()
        await c.flush(timeout=0.3)
        elapsed = time.perf_counter() - t0
        await c.stop()
        await server.close()
        return elapsed

    assert asyncio.run(go()) < 1.5


# ---------------- /health ----------------


def test_health_liviano_sin_cache_y_sin_datos():
    resp = asyncio.run(webapi._api_health(SimpleNamespace()))
    body = json.loads(resp.body)
    assert resp.status == 200 and body["status"] == "ok" and body["ok"] is True
    assert resp.headers["Cache-Control"] == "no-store"
    assert set(body) == {"ok", "status"}
