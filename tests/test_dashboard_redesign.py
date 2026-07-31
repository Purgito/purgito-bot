"""Tests del rediseño del dashboard: helpers de DB (chat_channels,
guild_bot_style, updates_channel_id, stats por canal) y el flujo de entrada al
panel (/servers redirige a /es/perfil salvo en el flujo de share; el locale del
login viaja por whitelist). DB en memoria inyectada en db._db, mismo patrón que
test_trim_corpus.py."""

import asyncio

import aiosqlite
import pytest

import db
import webapi

_GUILD = 1


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    # Columna que init_db agrega por ALTER (no está en el CREATE, igual que locale).
    await conn.execute("ALTER TABLE settings ADD COLUMN updates_channel_id INTEGER")
    await conn.commit()
    return conn


def test_chat_channels_roundtrip(memory_db):
    async def run():
        assert await db.list_chat_channels(_GUILD) == []
        assert await db.add_chat_channel(_GUILD, 10) is True
        assert await db.add_chat_channel(_GUILD, 10) is False  # duplicado
        assert await db.add_chat_channel(_GUILD, 20) is True
        assert await db.list_chat_channels(_GUILD) == [10, 20]
        assert await db.remove_chat_channel(_GUILD, 10) is True
        assert await db.remove_chat_channel(_GUILD, 10) is False
        assert await db.list_chat_channels(_GUILD) == [20]

    asyncio.run(run())


def test_set_chat_enabled_preserves_channel(memory_db):
    async def run():
        await db.set_chat_mode(_GUILD, True, 555)
        await db.set_chat_enabled(_GUILD, False)
        settings = await db.get_chat_settings(_GUILD)
        assert settings["enabled"] is False
        assert settings["channel_id"] == 555

    asyncio.run(run())


def test_bot_style_roundtrip(memory_db):
    async def run():
        assert await db.get_bot_style(_GUILD) == {
            "nick": None, "avatar_url": None, "banner_url": None,
        }
        await db.set_bot_style(_GUILD, "Purgi", "https://r2/av.png", None)
        style = await db.get_bot_style(_GUILD)
        assert style["nick"] == "Purgi"
        assert style["avatar_url"] == "https://r2/av.png"
        assert style["banner_url"] is None

    asyncio.run(run())


def test_updates_channel(memory_db):
    async def run():
        assert await db.get_updates_channel(_GUILD) is None
        await db.set_updates_channel(_GUILD, 42)
        assert await db.get_updates_channel(_GUILD) == 42
        await db.set_updates_channel(_GUILD, None)
        assert await db.get_updates_channel(_GUILD) is None

    asyncio.run(run())


def test_count_corpus_by_channel_orders_desc(memory_db):
    async def run():
        for chan, n in ((10, 1), (20, 3)):
            for i in range(n):
                await memory_db.execute(
                    "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
                    "VALUES (?, ?, ?, ?)",
                    (_GUILD, chan, chan * 100 + i, f"m{i}"),
                )
        await memory_db.commit()
        rows = await db.count_corpus_by_channel(_GUILD)
        assert rows == [
            {"channel_id": 20, "count": 3},
            {"channel_id": 10, "count": 1},
        ]

    asyncio.run(run())


# ---------------- Flujo de entrada al panel ----------------
#
# El selector viejo (/servers) dejó de ser la entrada: la landing y el
# post-login mandan a /es/perfil. /servers sobrevive solo para /share/{id},
# que necesita elegir servidor antes de abrir el editor de embeds.


class _FakeRequest:
    def __init__(self, query=None):
        self.query = query or {}


def test_servers_redirects_to_perfil_without_share():
    with pytest.raises(webapi.web.HTTPFound) as exc:
        asyncio.run(webapi._servers_page(_FakeRequest()))
    assert exc.value.location == "/es/perfil"


def test_servers_keeps_selector_for_share_flow(monkeypatch):
    async def fake_get_session(request):
        return {"username": "fram", "avatar_url": "a"}

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    resp = asyncio.run(webapi._servers_page(_FakeRequest({"share": "abc12345"})))
    assert resp.status == 200
    assert "selector-page" in resp.text


# El locale del login viaja por whitelist, igual que ?from=landing: un valor
# arbitrario nunca debe convertirse en destino del redirect (open redirect).


def _run_login(monkeypatch, query):
    session = {}

    async def fake_get_session(request):
        return session

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    with pytest.raises(webapi.web.HTTPFound):
        asyncio.run(webapi._auth_login(_FakeRequest(query)))
    return session


def test_login_stores_whitelisted_locale(monkeypatch):
    session = _run_login(monkeypatch, {"from": "landing", "locale": "de"})
    assert session["post_login_locale"] == "de"


def test_login_rejects_arbitrary_locale(monkeypatch):
    session = _run_login(
        monkeypatch, {"from": "landing", "locale": "https://evil.com"}
    )
    assert session["post_login_locale"] == ""
