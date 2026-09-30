"""Las subidas del dashboard (imágenes de embeds, archivos de Layout V2) tienen
topes propios de 8 y 10 MB, pero la app corre con el client_max_size default
de aiohttp (1 MiB) -- y `request.read()` lo aplica siempre. Resultado antes
del fix: cualquier archivo entre 1 MiB y el tope propio fallaba con un 413 en
texto plano de aiohttp, no el JSON que el dashboard espera.

A diferencia de los tests que llaman al handler con un FakeRequest, estos
levantan un servidor aiohttp de verdad con el client_max_size DEFAULT: es lo
único que reproduce el bug (un FakeRequest nunca aplica ese tope)."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import webapi

_PNG = b"\x89PNG\r\n\x1a\n"
_MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _cableado(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": "42", "sid": None}

    async def fake_check_access(request, guild_id):
        return None

    async def fake_store_upload(data, guild_id, ext):
        return "https://cdn.test/x.png"

    async def fake_record(guild_id, url):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_access)
    monkeypatch.setattr(webapi, "_session_logged_in", _siempre_logueado)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, gid: object())
    monkeypatch.setattr(webapi.r2, "available", lambda: True)
    monkeypatch.setattr(webapi, "_store_upload", fake_store_upload)
    monkeypatch.setattr(webapi, "record_uploaded_image", fake_record)
    monkeypatch.setattr(webapi, "_rate_upload", webapi.LRUDict(64))
    monkeypatch.setattr(webapi, "_rate_guild_api_write", webapi.LRUDict(64))
    monkeypatch.setattr(webapi, "_pending_layout_files", {})
    monkeypatch.setattr(webapi, "MAX_LAYOUT_FILE_UPLOAD_BYTES", 10 * _MB)


async def _siempre_logueado(session):
    return True


def _post(path: str, body: bytes):
    async def run():
        app = web.Application()  # client_max_size default: 1 MiB, como start_web_server
        app.router.add_post(
            "/api/server/{guild_id}/embeds/upload", webapi._api_embeds_upload
        )
        app.router.add_post(
            "/api/server/{guild_id}/embeds/upload-file/{filename}",
            webapi._api_layout_file_upload,
        )
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(path, data=body)
            try:
                payload = await resp.json()
            except Exception:
                payload = None
            return resp.status, resp.content_type, payload

    return asyncio.run(run())


def test_la_app_real_sigue_con_el_tope_global_de_1_mib():
    """El fix NO sube el límite global (protege a /webhooks/polar y al resto de
    los endpoints JSON): el tope propio vive solo en los dos handlers de subida."""
    assert web.Application()._client_max_size == 1024**2


def test_imagen_de_3_mb_se_acepta():
    status, ctype, payload = _post(
        "/api/server/1/embeds/upload", _PNG + b"\0" * (3 * _MB)
    )
    assert status == 200, payload
    assert payload == {"url": "https://cdn.test/x.png"}


def test_imagen_justo_en_el_tope_se_acepta():
    status, _, payload = _post(
        "/api/server/1/embeds/upload", _PNG + b"\0" * (8 * _MB - 8)
    )
    assert status == 200, payload


def test_imagen_sobre_el_tope_da_413_en_json():
    status, ctype, payload = _post(
        "/api/server/1/embeds/upload", _PNG + b"\0" * (9 * _MB)
    )
    assert status == 413
    assert ctype == "application/json"
    assert "8 MB" in payload["error"]


def test_imagen_chica_sigue_funcionando():
    status, _, payload = _post("/api/server/1/embeds/upload", _PNG + b"\0" * 100)
    assert status == 200, payload


def test_archivo_de_layout_de_5_mb_se_acepta():
    status, _, payload = _post(
        "/api/server/1/embeds/upload-file/informe.pdf", b"%PDF" + b"\0" * (5 * _MB)
    )
    assert status == 200, payload
    assert payload["filename"] == "informe.pdf"
    assert payload["upload_id"]
    assert len(webapi._pending_layout_files) == 1


def test_archivo_de_layout_sobre_el_tope_da_413_en_json():
    status, ctype, payload = _post(
        "/api/server/1/embeds/upload-file/informe.pdf", b"\0" * (11 * _MB)
    )
    assert status == 413
    assert ctype == "application/json"
    assert "10 MB" in payload["error"]
    assert webapi._pending_layout_files == {}


def test_cuerpo_vacio_sigue_dando_400():
    status, _, payload = _post("/api/server/1/embeds/upload", b"")
    assert status == 400
    assert payload["error"] == "archivo vacío"
