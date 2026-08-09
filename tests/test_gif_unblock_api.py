"""Test del endpoint DELETE /api/server/{guild_id}/settings/gifs/blocked/{key}
(_api_server_gifs_unblock): a diferencia de sus hermanos (block/delete de
gifs, que ya pasan por _gif_block_impl/_gif_delete_impl con _rate_ok), este
no tenía ningún límite -- Sección 8 de la auditoría de seguridad.

DB en memoria vía executescript(db.SCHEMA), mismo patrón que
test_corpus_import_amnesia_api.py.
"""

import asyncio

import aiosqlite
import pytest

import db
import webapi

_GUILD = 123
_USER_ID = "999888777"


class FakeRequest:
    def __init__(self, guild_id=_GUILD, key="somehash"):
        self.match_info = {"guild_id": str(guild_id), "key": key}
        self.headers = {}
        self.remote = "1.2.3.4"


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


@pytest.fixture(autouse=True)
def allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": "Frambuesa"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: object())
    monkeypatch.setattr(webapi, "_rate_delete", webapi.LRUDict(64))


def _run(request):
    return asyncio.run(webapi._api_server_gifs_unblock(request))


def test_unblock_respeta_el_rate_limit(memory_db):
    for _ in range(3):
        resp = _run(FakeRequest())
        assert resp.status == 200

    resp = _run(FakeRequest())
    assert resp.status == 429


def test_unblock_borra_por_content_hash(memory_db):
    asyncio.run(db.block_gif(_GUILD, "hash1", "https://pub.example/gif.gif"))

    resp = _run(FakeRequest(key="hash1"))

    assert resp.status == 200
    assert asyncio.run(db.is_gif_blocked(_GUILD, "hash1", "")) is False
