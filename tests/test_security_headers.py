"""El middleware de cabeceras de seguridad tiene que cubrir toda respuesta,
incluidas las de error y las que ya pasaron por CORS."""

import asyncio
from types import SimpleNamespace

from aiohttp import web

import webapi


def _fake_request(path="/otra-cosa", method="POST"):
    return SimpleNamespace(path=path, method=method)


def _run_middleware(status=200, request=None):
    async def handler(request):
        return web.json_response({"ok": True}, status=status)

    return asyncio.run(
        webapi._security_headers_middleware(request or _fake_request(), handler)
    )


def test_agrega_las_cinco_cabeceras():
    resp = _run_middleware()
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["Content-Security-Policy"] == (
        f"default-src 'none'; style-src '{webapi._AUTH_ERROR_STYLE_HASH}'; "
        "frame-ancestors 'none'"
    )
    assert resp.headers["Server"] == "Purgito"


def test_no_filtra_la_version_real_de_python_ni_de_aiohttp():
    """Auditoría sección 12: aiohttp pone Server: Python/x.y aiohttp/x.y con
    headers.setdefault(...) -- solo pisa si el header ya está seteado. Sin
    este middleware seteándolo primero, cada respuesta (incluidas las de
    error) anuncia versiones exactas: reconocimiento gratis para un
    atacante, nada de valor para el usuario real."""
    from aiohttp.http import SERVER_SOFTWARE

    resp = _run_middleware()
    assert resp.headers["Server"] != SERVER_SOFTWARE
    assert "Python/" not in resp.headers["Server"]
    assert "aiohttp/" not in resp.headers["Server"]


def test_tambien_cubre_respuestas_de_error():
    resp = _run_middleware(status=404)
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_cubre_tambien_un_handler_que_hace_raise_httpfound():
    """Auditoría sección 12: web.HTTPFound/HTTPException son excepciones Y
    Response a la vez. `raise web.HTTPFound(...)` -- TODO /auth/login,
    /auth/callback y /auth/logout -- se propagaba por encima de
    `resp = await handler(request)` en vez de pasar por esa línea, así que
    salía sin ninguna de las cabeceras de abajo (Server real de aiohttp
    incluido). Confirmado antes del fix con un servidor aiohttp mínimo."""

    async def handler(request):
        raise web.HTTPFound("/otro-lado")

    resp = asyncio.run(webapi._security_headers_middleware(_fake_request(), handler))
    assert resp.status == 302
    assert resp.headers["Location"] == "/otro-lado"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Server"] == "Purgito"


def test_no_cachea_gets_de_api_por_default():
    """Auditoría sección 12: GET /api/server/{guild_id}/... es config o
    stats por sesión, y hay Cloudflare delante -- sin esto la mayoría de
    esos ~25 endpoints (todos menos /api/me y /api/me/guilds, que ya lo
    seteaban a mano) quedan a merced de la política de caché default del
    proxy."""
    resp = _run_middleware(
        request=_fake_request(path="/api/server/1/stats", method="GET")
    )
    assert resp.headers["Cache-Control"] == "no-store"


def test_no_toca_cache_control_fuera_de_api_get():
    resp = _run_middleware(request=_fake_request(path="/health", method="GET"))
    assert "Cache-Control" not in resp.headers


def test_no_pisa_un_cache_control_mas_especifico():
    async def handler(request):
        return web.json_response({"ok": True}, headers={"Cache-Control": "max-age=60"})

    resp = asyncio.run(
        webapi._security_headers_middleware(
            _fake_request(path="/api/status", method="GET"), handler
        )
    )
    assert resp.headers["Cache-Control"] == "max-age=60"


def test_esta_montado_en_la_app_real():
    """No alcanza con que exista la función: tiene que estar en la lista de
    middlewares que arma start_web_server, o nunca se ejecuta."""

    class _FakeBot:
        guilds: list = []

        def get_guild(self, guild_id):
            return None

    original = webapi.DASHBOARD_ENABLED
    webapi.DASHBOARD_ENABLED = False
    webapi._runner = None
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(webapi.start_web_server(_FakeBot()))
        assert webapi._security_headers_middleware in webapi._runner.app.middlewares
        loop.run_until_complete(webapi.stop_web_server())
    finally:
        loop.close()
        webapi.DASHBOARD_ENABLED = original
