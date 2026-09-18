"""Reliability: red de contención para excepciones no atajadas en la API.

Sin `_error_middleware`, aiohttp responde por su cuenta ante cualquier
excepción sin capturar en un handler: 500 con `Content-Type: text/plain` y
un body que no es JSON (confirmado contra un server aiohttp mínimo) -- ni
remotamente lo que el resto de esta API siempre devuelve ("Web: aiohttp
puro, solo JSON", CLAUDE.md). El dashboard (`apiFetch`) espera poder
hacerle `.json()` a cualquier respuesta de error; con un body de texto
plano eso tira una excepción de parseo en el navegador en vez de mostrar el
"Error 500" pelado que ya señalaba el hallazgo #10 de AUDITORIA_UX.md.

Mismo patrón de test que test_security_headers.py: llamar al middleware
directo con un handler fake, sin levantar el server real."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web

import webapi


def _fake_request(path="/api/algo", method="GET"):
    return SimpleNamespace(path=path, method=method)


def test_excepcion_no_atajada_da_json_500_con_error():
    async def handler(request):
        raise RuntimeError("boom")

    resp = asyncio.run(webapi._error_middleware(_fake_request(), handler))
    assert resp.status == 500
    assert resp.content_type == "application/json"
    import json

    body = json.loads(resp.body)
    assert "error" in body and body["error"]


def test_httpexception_deliberada_pasa_sin_tocar():
    """web.HTTPNotFound/HTTPFound/etc. son respuestas a propósito de un
    handler (404, redirects de /auth/*), no bugs -- no deben homogeneizarse
    al JSON genérico de error."""

    async def handler(request):
        raise web.HTTPNotFound()

    with pytest.raises(web.HTTPNotFound):
        asyncio.run(webapi._error_middleware(_fake_request(), handler))


def test_camino_feliz_no_se_toca():
    async def handler(request):
        return web.json_response({"ok": True})

    resp = asyncio.run(webapi._error_middleware(_fake_request(), handler))
    assert resp.status == 200


def test_loguea_la_excepcion_real_con_traceback(caplog):
    original = ValueError("algo específico")

    async def handler(request):
        raise original

    with caplog.at_level(logging.ERROR, logger="webapi"):
        asyncio.run(
            webapi._error_middleware(
                _fake_request(path="/api/x", method="POST"), handler
            )
        )
    rec = next(r for r in caplog.records if "no atajada" in r.getMessage())
    assert rec.exc_info[1] is original
    assert "/api/x" in rec.getMessage() and "POST" in rec.getMessage()


def test_esta_montado_en_la_app_real():
    """Que el middleware exista y funcione aislado no garantiza que esté
    conectado -- mismo chequeo que ya hace test_security_headers.py para
    los otros dos, y en el mismo orden relativo (más interno, para que su
    respuesta de error siga saliendo por CORS/cabeceras de seguridad)."""

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
        middlewares = list(webapi._runner.app.middlewares)
        assert webapi._error_middleware in middlewares
        assert middlewares.index(webapi._error_middleware) > middlewares.index(
            webapi._cors_middleware
        )
        loop.run_until_complete(webapi.stop_web_server())
    finally:
        loop.close()
        webapi.DASHBOARD_ENABLED = original
