"""Tests del endpoint del playground (Fase 7):
POST /api/server/{guild_id}/chat/playground.

simulate_message en sí ya se prueba en test_chat_playground.py -- acá solo
la parte de webapi.py: validación del body, resolución del canal y del
autor (Member real si se puede, placeholder si no), y que el resultado de
simulate_message se devuelve tal cual.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import webapi

_GUILD = 123
_USER_ID = "999888777"
_USERNAME = "Frambuesa"


class FakeGuild:
    def __init__(self, channels=None, members=None):
        self._channels = channels or {}
        self._members = members or {}

    def get_channel(self, channel_id):
        return self._channels.get(channel_id)

    def get_member(self, user_id):
        return self._members.get(user_id)


class FakeRequest:
    def __init__(self, guild_id=_GUILD, body=None):
        self._body = body
        self.match_info = {"guild_id": str(guild_id)}
        self.headers = {}
        self.remote = "1.2.3.4"

    async def json(self):
        if self._body is None:
            raise ValueError("sin body")
        return self._body


@pytest.fixture
def fake_guild(monkeypatch):
    guild = FakeGuild(channels={10: SimpleNamespace(id=10, name="general")})

    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": _USERNAME}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: guild)
    monkeypatch.setattr(webapi, "_rate_playground", webapi.LRUDict(64))
    return guild


def _run(request):
    return asyncio.run(webapi._api_chat_playground_post(request))


def _json(resp):
    return json.loads(resp.body)


def test_body_invalido_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body=None))
    assert resp.status == 400


def test_mensaje_vacio_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body={"message": "   ", "channel_id": "10"}))
    assert resp.status == 400


def test_channel_id_invalido_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "no-es-un-id"}))
    assert resp.status == 400


def test_canal_inexistente_en_el_guild_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "999"}))
    assert resp.status == 400


def test_devuelve_el_resultado_de_simulate_message_tal_cual(fake_guild, monkeypatch):
    captured = {}

    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        captured.update(
            guild_id=guild_id,
            channel_id=channel_id,
            content=content,
            author=author,
            channel=channel,
            guild=guild,
        )
        return {"would_respond": True, "reason": "markov", "text": "hola"}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    resp = _run(FakeRequest(body={"message": "hola bot", "channel_id": "10"}))

    assert resp.status == 200
    assert _json(resp) == {"would_respond": True, "reason": "markov", "text": "hola"}
    assert captured["guild_id"] == _GUILD
    assert captured["channel_id"] == 10
    assert captured["content"] == "hola bot"
    assert captured["channel"] is fake_guild._channels[10]
    assert captured["guild"] is fake_guild


def test_usa_el_member_real_como_autor_si_esta_en_cache(fake_guild, monkeypatch):
    member = SimpleNamespace(mention=f"<@{_USER_ID}>", display_name="Frambuesa real")
    fake_guild._members[int(_USER_ID)] = member

    captured = {}

    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        captured["author"] = author
        return {"would_respond": False, "reason": "sin_corpus_suficiente", "text": None}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))

    assert captured["author"] is member


def test_respeta_el_rate_limit(fake_guild, monkeypatch):
    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        return {"would_respond": False, "reason": "sin_corpus_suficiente", "text": None}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    for _ in range(20):
        resp = _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))
        assert resp.status == 200

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))
    assert resp.status == 429


def test_usa_un_placeholder_si_no_hay_member_en_cache(fake_guild, monkeypatch):
    captured = {}

    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        captured["author"] = author
        return {"would_respond": False, "reason": "sin_corpus_suficiente", "text": None}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))

    author = captured["author"]
    assert author.mention == f"<@{_USER_ID}>"
    assert author.display_name == _USERNAME
