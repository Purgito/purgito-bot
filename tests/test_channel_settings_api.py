"""Tests de los endpoints de overrides por canal
(/api/guilds/{guild_id}/channels/{channel_id}/settings).

Mismo patrón que test_youtube_webapi.py / test_audit_log.py: handlers
llamados directo, DB en memoria real (no mocks de db.py), get_session/
check_guild_access/_bot_guild parcheados para que guild_api deje pasar.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import db
import webapi

_GUILD = 123
_CHANNEL = 10
_USER_ID = "999888777"
_USERNAME = "Frambuesa"


class FakeRequest:
    def __init__(self, guild_id=_GUILD, channel_id=_CHANNEL, body=None):
        self._body = body
        self.match_info = {
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
        }

    async def json(self):
        if self._body is None:
            raise ValueError("sin body")
        return self._body


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    """DB de archivo real por test (no memoria + SCHEMA a mano): las columnas
    de settings que resuelve get_effective_chat_settings salen de ALTER TABLE
    en init_db(), no del CREATE TABLE base -- ver test_chat_config.py."""
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


@pytest.fixture(autouse=True)
def allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": _USERNAME}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(
        webapi,
        "_bot_guild",
        lambda request, guild_id: SimpleNamespace(get_channel=lambda cid: None),
    )


def _run(handler, request):
    return asyncio.run(handler(request))


def _json(resp):
    return json.loads(resp.body)


# ── GET ──────────────────────────────────────────────────────────────────────


def test_get_sin_overrides_devuelve_los_defaults_del_servidor(memory_db):
    resp = _run(webapi._api_channel_settings_get, FakeRequest())

    assert resp.status == 200
    body = _json(resp)
    assert body["effective"]["reaction_probability"] == db.DEFAULT_REACTION_PROBABILITY
    assert body["overrides"] == dict.fromkeys(db.CHAT_TUNABLES)
    assert "reaction_probability" in body["limits"]


def test_get_channel_id_invalido_devuelve_400(memory_db):
    resp = _run(
        webapi._api_channel_settings_get,
        FakeRequest(channel_id="no-es-un-id"),
    )
    assert resp.status == 400


# ── PUT ──────────────────────────────────────────────────────────────────────


def test_put_guarda_override_y_el_get_lo_refleja(memory_db):
    put_resp = _run(
        webapi._api_channel_settings_put,
        FakeRequest(body={"reaction_probability": 0.9}),
    )
    assert put_resp.status == 200
    assert _json(put_resp)["saved"] == {"reaction_probability": 0.9}

    get_resp = _run(webapi._api_channel_settings_get, FakeRequest())
    body = _json(get_resp)
    assert body["overrides"]["reaction_probability"] == 0.9
    assert body["effective"]["reaction_probability"] == 0.9
    # El resto sigue en default, no lo arrastró el override parcial.
    assert body["overrides"]["gif_response_probability"] is None


def test_put_con_null_borra_el_override(memory_db):
    _run(
        webapi._api_channel_settings_put,
        FakeRequest(body={"reaction_probability": 0.9}),
    )

    resp = _run(
        webapi._api_channel_settings_put,
        FakeRequest(body={"reaction_probability": None}),
    )

    assert resp.status == 200
    assert _json(resp)["saved"] == {"reaction_probability": None}
    overrides = asyncio.run(db.get_channel_tunables(_GUILD, _CHANNEL))
    assert overrides["reaction_probability"] is None


def test_put_recorta_valores_fuera_de_rango(memory_db):
    resp = _run(
        webapi._api_channel_settings_put,
        FakeRequest(body={"auto_generate_probability": 5.0}),
    )
    assert _json(resp)["saved"]["auto_generate_probability"] == 1.0


def test_put_campo_desconocido_devuelve_400(memory_db):
    resp = _run(
        webapi._api_channel_settings_put,
        FakeRequest(body={"algo_que_no_existe": 1}),
    )
    assert resp.status == 400


def test_put_body_invalido_devuelve_400(memory_db):
    resp = _run(webapi._api_channel_settings_put, FakeRequest(body=None))
    assert resp.status == 400


def test_put_sin_valores_validos_devuelve_400(memory_db):
    resp = _run(
        webapi._api_channel_settings_put,
        FakeRequest(body={"reaction_probability": "no soy un número"}),
    )
    assert resp.status == 400


def test_put_channel_id_invalido_devuelve_400(memory_db):
    resp = _run(
        webapi._api_channel_settings_put,
        FakeRequest(channel_id="no-es-un-id", body={"reaction_probability": 0.5}),
    )
    assert resp.status == 400


def test_put_loguea_en_el_audit_log_con_el_user_id_de_la_sesion(memory_db):
    _run(
        webapi._api_channel_settings_put,
        FakeRequest(body={"reaction_probability": 0.9}),
    )

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["action"] == "channel_settings.update"
    assert entries[0]["user_id"] == int(_USER_ID)
    assert str(_CHANNEL) in entries[0]["detail"]


def test_overrides_de_un_canal_no_afectan_a_otro(memory_db):
    _run(
        webapi._api_channel_settings_put,
        FakeRequest(channel_id=10, body={"reaction_probability": 0.9}),
    )

    otro = _run(webapi._api_channel_settings_get, FakeRequest(channel_id=20))
    assert _json(otro)["overrides"]["reaction_probability"] is None
