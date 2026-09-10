"""Prefijo de comandos configurable por guild: símbolo custom (default "!",
tabla settings.custom_prefix) + prefijo de palabra fijo ("purgito ", de
config.BOT_TRIGGER_NAME). Cubre db.py, bot.py:get_prefix y el endpoint
GET/PUT /settings/prefix de webapi.py.

Mismo patrón que test_lifecycle.py / test_updates_relay.py: DB SQLite en
memoria inyectada en db._db, sin tocar data/bot.db.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiosqlite
import discord
import pytest

import bot as bot_module
import db
import webapi
from config import BOT_TRIGGER_NAME


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


# ── db.py: get_guild_prefix / set_guild_prefix ───────────────────────────────


def test_get_guild_prefix_default_es_none(memory_db):
    assert asyncio.run(db.get_guild_prefix(1)) is None


def test_set_guild_prefix_roundtrip(memory_db):
    asyncio.run(db.set_guild_prefix(1, "$"))
    assert asyncio.run(db.get_guild_prefix(1)) == "$"


def test_set_guild_prefix_none_resetea_a_default(memory_db):
    asyncio.run(db.set_guild_prefix(1, "$"))
    asyncio.run(db.set_guild_prefix(1, None))
    assert asyncio.run(db.get_guild_prefix(1)) is None


def test_set_guild_prefix_no_pisa_otros_guilds(memory_db):
    asyncio.run(db.set_guild_prefix(1, "$"))
    assert asyncio.run(db.get_guild_prefix(2)) is None


# ── bot.py: get_prefix ────────────────────────────────────────────────────────


def _fake_message(guild_id):
    guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    return MagicMock(spec=discord.Message, guild=guild)


def test_get_prefix_default_sin_custom(memory_db):
    msg = _fake_message(1)
    prefixes = asyncio.run(bot_module.get_prefix(bot_module.bot, msg))
    assert prefixes == ["!", f"{BOT_TRIGGER_NAME} "]


def test_get_prefix_usa_el_custom_del_guild(memory_db):
    asyncio.run(db.set_guild_prefix(1, "$"))
    msg = _fake_message(1)
    prefixes = asyncio.run(bot_module.get_prefix(bot_module.bot, msg))
    assert prefixes == ["$", f"{BOT_TRIGGER_NAME} "]


def test_get_prefix_no_mezcla_prefijos_entre_guilds(memory_db):
    asyncio.run(db.set_guild_prefix(1, "$"))
    msg_otro_guild = _fake_message(2)
    prefixes = asyncio.run(bot_module.get_prefix(bot_module.bot, msg_otro_guild))
    assert prefixes == ["!", f"{BOT_TRIGGER_NAME} "]


def test_get_prefix_sin_guild_usa_default(memory_db):
    """DM: no hay guild_id para resolver un custom_prefix."""
    msg = _fake_message(None)
    prefixes = asyncio.run(bot_module.get_prefix(bot_module.bot, msg))
    assert prefixes == ["!", f"{BOT_TRIGGER_NAME} "]


# ── webapi.py: GET/PUT /settings/prefix ──────────────────────────────────────


class FakeRequest:
    def __init__(self, body=None, guild_id="100"):
        self._body = body
        self.match_info = {"guild_id": guild_id}
        self.headers = {"Content-Type": "application/json"}
        self.remote = "1.2.3.4"

    async def json(self):
        return self._body


@pytest.fixture(autouse=True)
def sesion_api(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": "777", "username": "admin"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: SimpleNamespace(id=gid))
    monkeypatch.setattr(webapi, "_rate_post", webapi.LRUDict(64))
    monkeypatch.setattr(webapi, "_rate_guild_api_write", webapi.LRUDict(64))


def test_api_prefix_get_default(memory_db):
    resp = asyncio.run(webapi._api_prefix_get(FakeRequest(guild_id="100")))
    assert resp.status == 200
    body = _json(resp)
    assert body == {
        "prefix": "!",
        "is_custom": False,
        "default_prefix": "!",
        "max_length": db.MAX_CUSTOM_PREFIX_LENGTH,
    }


def test_api_prefix_put_guarda_y_get_lo_refleja(memory_db):
    resp = asyncio.run(
        webapi._api_prefix_put(FakeRequest({"prefix": "$"}, guild_id="100"))
    )
    assert resp.status == 200
    assert _json(resp)["prefix"] == "$"
    assert asyncio.run(db.get_guild_prefix(100)) == "$"

    resp_get = asyncio.run(webapi._api_prefix_get(FakeRequest(guild_id="100")))
    body = _json(resp_get)
    assert body["prefix"] == "$"
    assert body["is_custom"] is True


def test_api_prefix_put_null_resetea_al_default(memory_db):
    asyncio.run(db.set_guild_prefix(100, "$"))
    resp = asyncio.run(
        webapi._api_prefix_put(FakeRequest({"prefix": None}, guild_id="100"))
    )
    assert resp.status == 200
    assert _json(resp)["prefix"] == "!"
    assert asyncio.run(db.get_guild_prefix(100)) is None


def test_api_prefix_put_rechaza_prefijo_vacio_tras_strip(memory_db):
    resp = asyncio.run(
        webapi._api_prefix_put(FakeRequest({"prefix": "   "}, guild_id="100"))
    )
    assert resp.status == 400


def test_api_prefix_put_rechaza_espacios_internos(memory_db):
    resp = asyncio.run(
        webapi._api_prefix_put(FakeRequest({"prefix": "p g"}, guild_id="100"))
    )
    assert resp.status == 400


def test_api_prefix_put_rechaza_prefijo_demasiado_largo(memory_db):
    largo = "!" * (db.MAX_CUSTOM_PREFIX_LENGTH + 1)
    resp = asyncio.run(
        webapi._api_prefix_put(FakeRequest({"prefix": largo}, guild_id="100"))
    )
    assert resp.status == 400
    assert asyncio.run(db.get_guild_prefix(100)) is None


def _json(resp):
    return json.loads(resp.body)
