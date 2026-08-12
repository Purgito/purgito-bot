"""_cors_middleware: refleja el origin solo si es confiable, nunca junto al
comodín "*", y sigue funcionando cuando el handler termina en un redirect."""

import asyncio
from types import SimpleNamespace

from aiohttp import web

import webapi


def _fake_request(path="/api/algo", method="GET", origin=""):
    headers = {"Origin": origin} if origin else {}
    return SimpleNamespace(path=path, method=method, headers=headers)


def _run(handler, **kwargs):
    return asyncio.run(webapi._cors_middleware(_fake_request(**kwargs), handler))


def _ok(request):
    async def _inner(request):
        return web.json_response({"ok": True})

    return _inner


def test_origin_confiable_recibe_eco_mas_credentials_y_vary():
    original = webapi.DASHBOARD_ENABLED
    webapi.DASHBOARD_ENABLED = True
    try:
        resp = _run(_ok(None), origin=webapi.DASHBOARD_BASE_URL)
        assert resp.headers["Access-Control-Allow-Origin"] == webapi.DASHBOARD_BASE_URL
        assert resp.headers["Access-Control-Allow-Credentials"] == "true"
        # Auditoría sección 12: sin esto, un caché compartido (Cloudflare)
        # podría guardar la respuesta armada para un origin y servirla tal
        # cual a otro origin distinto.
        assert resp.headers["Vary"] == "Origin"
    finally:
        webapi.DASHBOARD_ENABLED = original


def test_origin_no_confiable_no_recibe_credentials_ni_wildcard():
    original = webapi.DASHBOARD_ENABLED
    webapi.DASHBOARD_ENABLED = True
    try:
        resp = _run(_ok(None), origin="https://evil.example")
        assert "Access-Control-Allow-Origin" not in resp.headers
        assert "Access-Control-Allow-Credentials" not in resp.headers
    finally:
        webapi.DASHBOARD_ENABLED = original


def test_substring_del_origin_confiable_no_alcanza():
    """origin == DASHBOARD_BASE_URL es comparación exacta -- un origin que
    solo contiene el dominio confiable como substring no tiene que pasar."""
    original = webapi.DASHBOARD_ENABLED
    webapi.DASHBOARD_ENABLED = True
    try:
        evil = f"{webapi.DASHBOARD_BASE_URL}.evil.example"
        resp = _run(_ok(None), origin=evil)
        assert "Access-Control-Allow-Origin" not in resp.headers
    finally:
        webapi.DASHBOARD_ENABLED = original


def test_get_publico_usa_wildcard_sin_credentials():
    resp = _run(_ok(None), path="/health", origin="https://cualquier-cosa.example")
    assert resp.headers["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in resp.headers


def test_cubre_tambien_un_handler_que_hace_raise_httpfound():
    """Auditoría sección 12: mismo bug que en _security_headers_middleware --
    `raise web.HTTPFound(...)` se saltaba el `resp = await handler(...)` y
    la respuesta salía sin cabeceras CORS."""
    original = webapi.DASHBOARD_ENABLED
    webapi.DASHBOARD_ENABLED = True
    try:

        async def handler(request):
            raise web.HTTPFound("/otro-lado")

        resp = _run(handler, origin=webapi.DASHBOARD_BASE_URL)
        assert resp.status == 302
        assert resp.headers["Access-Control-Allow-Origin"] == webapi.DASHBOARD_BASE_URL
    finally:
        webapi.DASHBOARD_ENABLED = original
