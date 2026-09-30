"""Defensa en profundidad contra CSRF: `_csrf_origin_middleware` exige que toda
escritura (POST/PUT/PATCH/DELETE) de un navegador venga de una página nuestra.

La cookie de sesión ya es SameSite=Lax y los endpoints con cuerpo JSON ya
rechazan los Content-Type "simples" de un <form> (`_json_body`), pero los
endpoints de escritura sin cuerpo JSON (vaciar el corpus, bloquear un GIF,
cerrar sesión...) dependían solo de SameSite -- que no frena a un sitio del
mismo sitio (la cookie es Domain=.purgito.app, la comparte cualquier
subdominio) ni a un navegador que lo ignore."""

import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import webapi

_PANEL = "https://purgito.app"
_LANDING = "https://www.purgito.app"


@pytest.fixture(autouse=True)
def _origenes(monkeypatch):
    monkeypatch.setattr(webapi, "DASHBOARD_BASE_URL", _PANEL)
    monkeypatch.setattr(webapi, "LANDING_ORIGINS", frozenset({_LANDING}))


def _req(headers=None, method="POST", path="/api/server/1/settings/corpus/amnesia"):
    return SimpleNamespace(headers=headers or {}, method=method, path=path)


# ── _origin_allowed ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "headers, esperado",
    [
        ({"Origin": _PANEL}, True),
        ({"Origin": _PANEL + "/"}, True),
        ({"Origin": _LANDING}, True),
        ({"Origin": "https://evil.example"}, False),
        ({"Origin": "https://purgito.app.evil.example"}, False),
        ({"Origin": "http://purgito.app"}, False),  # otro esquema = otro origen
        ({"Origin": "https://sub.purgito.app"}, False),  # mismo sitio, otro origen
        ({"Origin": "null"}, False),
        # Con Origin manda Origin, aunque Sec-Fetch-Site diga lo contrario.
        ({"Origin": "https://evil.example", "Sec-Fetch-Site": "same-origin"}, False),
        ({"Origin": _PANEL, "Sec-Fetch-Site": "cross-site"}, True),
        # Sin Origin decide Sec-Fetch-Site.
        ({"Sec-Fetch-Site": "same-origin"}, True),
        ({"Sec-Fetch-Site": "none"}, True),
        ({"Sec-Fetch-Site": "same-site"}, False),
        ({"Sec-Fetch-Site": "cross-site"}, False),
        # Ningún header: no hay navegador (curl, script) -> igual exige la cookie.
        ({}, True),
    ],
)
def test_origin_allowed(headers, esperado):
    assert webapi._origin_allowed(_req(headers)) is esperado


# ── el middleware ────────────────────────────────────────────────────────────


async def _ok(request):
    return web.json_response({"ok": True})


def _run_middleware(request):
    return asyncio.run(webapi._csrf_origin_middleware(request, _ok))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_bloquea_escrituras_de_un_origen_ajeno(method):
    resp = _run_middleware(_req({"Origin": "https://evil.example"}, method=method))
    assert resp.status == 403
    assert resp.content_type == "application/json"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_deja_pasar_escrituras_del_propio_panel(method):
    assert _run_middleware(_req({"Origin": _PANEL}, method=method)).status == 200


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_nunca_toca_lecturas_ni_preflight(method):
    resp = _run_middleware(_req({"Origin": "https://evil.example"}, method=method))
    assert resp.status == 200


def test_el_webhook_de_polar_queda_exento():
    """Polar le pega server-to-server, sin navegador: aunque alguien le mande un
    Origin cualquiera, el chequeo no se mete (la firma es su autenticación)."""
    req = _req({"Origin": "https://evil.example"}, path="/webhooks/polar")
    assert _run_middleware(req).status == 200


def test_el_logout_tambien_esta_cubierto():
    req = _req({"Origin": "https://evil.example"}, path="/auth/logout")
    assert _run_middleware(req).status == 403


# ── contra un servidor real ──────────────────────────────────────────────────


def _request_real(headers, method="POST", path="/api/x"):
    async def run():
        app = web.Application(middlewares=[webapi._csrf_origin_middleware])
        app.router.add_route("*", "/api/x", _ok)
        app.router.add_route("*", "/webhooks/polar", _ok)
        async with TestClient(TestServer(app)) as client:
            resp = await client.request(method, path, headers=headers)
            return resp.status, await resp.json()

    return asyncio.run(run())


def test_servidor_real_origen_ajeno_403():
    status, body = _request_real({"Origin": "https://evil.example"})
    assert status == 403
    assert body == {"error": "origen no permitido"}


def test_servidor_real_origen_propio_200():
    assert _request_real({"Origin": _PANEL})[0] == 200


def test_servidor_real_cross_site_sin_origin_403():
    assert _request_real({"Sec-Fetch-Site": "cross-site"})[0] == 403


def test_servidor_real_webhook_exento():
    status, _ = _request_real(
        {"Origin": "https://evil.example"}, path="/webhooks/polar"
    )
    assert status == 200


# ── conectado en la app real ─────────────────────────────────────────────────


def test_esta_montado_en_la_app_real_entre_cors_y_el_error_middleware():
    """Que exista y funcione aislado no garantiza que start_web_server lo
    monte. Va DESPUÉS de CORS (su 403 sale con las cabeceras de seguridad y
    CORS como cualquier otra respuesta) y ANTES del error middleware."""

    class _FakeBot:
        guilds: list = []

        def get_guild(self, guild_id):
            return None

    original_enabled = webapi.DASHBOARD_ENABLED
    original_runner = webapi._runner
    webapi.DASHBOARD_ENABLED = False
    webapi._runner = None

    async def run():
        await webapi.start_web_server(_FakeBot())
        try:
            return list(webapi._runner.app.middlewares)
        finally:
            await webapi.stop_web_server()

    try:
        middlewares = asyncio.run(run())
    finally:
        webapi.DASHBOARD_ENABLED = original_enabled
        webapi._runner = original_runner

    assert webapi._csrf_origin_middleware in middlewares
    assert middlewares.index(webapi._csrf_origin_middleware) > middlewares.index(
        webapi._cors_middleware
    )
    assert middlewares.index(webapi._csrf_origin_middleware) < middlewares.index(
        webapi._error_middleware
    )
