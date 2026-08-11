"""El middleware de cabeceras de seguridad tiene que cubrir toda respuesta,
incluidas las de error y las que ya pasaron por CORS."""

import asyncio

from aiohttp import web

import webapi


def _run_middleware(status=200):
    async def handler(request):
        return web.json_response({"ok": True}, status=status)

    return asyncio.run(webapi._security_headers_middleware(None, handler))


def test_agrega_las_cinco_cabeceras():
    resp = _run_middleware()
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
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
