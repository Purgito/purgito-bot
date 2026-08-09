"""Test de POST /api/server/{guild_id}/settings/reacciones (_api_reacciones_post):
a diferencia de frases/packs/triggers/embed templates, reaction_pool no tenía
ninguna cuota ni rate limit -- barrido final de la Sección 8 de la auditoría
de seguridad.

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
    def __init__(self, guild_id=_GUILD, emoji="😀"):
        self._body = {"emoji": emoji}
        self.match_info = {"guild_id": str(guild_id)}
        self.headers = {}
        self.remote = "1.2.3.4"

    async def json(self):
        return self._body


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
    monkeypatch.setattr(webapi, "_rate_post", webapi.LRUDict(64))


def _run(request):
    return asyncio.run(webapi._api_reacciones_post(request))


def test_agrega_una_reaccion_al_pool(memory_db):
    resp = _run(FakeRequest(emoji="🎉"))
    assert resp.status == 200

    pool = asyncio.run(db.list_reaction_pool(_GUILD))
    assert [r["emoji_text"] for r in pool] == ["🎉"]


def test_respeta_el_rate_limit(memory_db):
    for i in range(5):
        resp = _run(FakeRequest(emoji=f"emoji{i}"))
        assert resp.status == 200

    resp = _run(FakeRequest(emoji="uno_de_mas"))
    assert resp.status == 429
