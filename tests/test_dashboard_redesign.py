"""Tests de los helpers de DB del rediseño del dashboard (chat_channels,
guild_bot_style, updates_channel_id, stats por canal). DB en memoria inyectada
en db._db, mismo patrón que test_trim_corpus.py."""

import asyncio

import aiosqlite
import pytest

import db

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
