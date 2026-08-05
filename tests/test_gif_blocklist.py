"""Tests del bloqueo permanente de GIFs por guild (gif_blocklist en db.py):
block_gif borra el GIF ahora y save_gif_url lo rechaza para siempre en ESE
guild si se vuelve a compartir -- ver el docstring de is_gif_blocked para la
limitación conocida de los GIFs sin content_hash (tenor/giphy): el bloqueo
por url exacta no cubre la misma animación bajo una url distinta.

Usa una DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db.
"""

import asyncio

import aiosqlite
import pytest

import db

_GUILD = 1
_OTHER_GUILD = 2


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)

    conn.deleted_keys = []
    conn.deleted_urls = []

    async def _fake_delete_key(key):
        conn.deleted_keys.append(key)

    async def _fake_delete_url(url):
        conn.deleted_urls.append(url)

    monkeypatch.setattr(db.r2, "delete_key", _fake_delete_key)
    monkeypatch.setattr(db.r2, "delete_url", _fake_delete_url)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _insert_gif_with_object(conn, guild_id, url, content_hash, r2_key):
    await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (guild_id, url, content_hash),
    )
    await conn.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
        "VALUES (?, ?, 1, 100)",
        (content_hash, r2_key),
    )
    await conn.commit()


def test_block_deletes_row_and_releases_r2_reference(memory_db):
    async def run():
        await _insert_gif_with_object(
            memory_db,
            _GUILD,
            "https://pub.example/gifs/aa/hash1.gif",
            "hash1",
            "gifs/aa/hash1.gif",
        )

        await db.block_gif(_GUILD, "hash1", "https://pub.example/gifs/aa/hash1.gif")

        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=?", (_GUILD,)
        )
        assert (await cur.fetchone())[0] == 0
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM gif_objects WHERE content_hash=?", ("hash1",)
        )
        assert (await cur.fetchone())[0] == 0
        assert memory_db.deleted_keys == ["gifs/aa/hash1.gif"]

    asyncio.run(run())


def test_blocked_by_content_hash_rejects_new_url_same_content(memory_db):
    """Re-share: mismo content_hash, url nueva -- el veto sigue matcheando
    aunque la url puntual bloqueada ya no exista."""

    async def run():
        await _insert_gif_with_object(
            memory_db,
            _GUILD,
            "https://pub.example/gifs/aa/hash1.gif",
            "hash1",
            "gifs/aa/hash1.gif",
        )
        await db.block_gif(_GUILD, "hash1", "https://pub.example/gifs/aa/hash1.gif")

        inserted, _ = await db.save_gif_url(
            _GUILD, "https://pub.example/gifs/aa/hash1-otra.gif", content_hash="hash1"
        )
        assert inserted is False
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=?", (_GUILD,)
        )
        assert (await cur.fetchone())[0] == 0

    asyncio.run(run())


def test_blocked_by_url_rejects_exact_url_but_not_a_different_one(memory_db):
    """Limitación conocida: sin content_hash (tenor/giphy) el bloqueo solo
    cubre la url exacta -- la misma animación bajo otra url se cuela."""

    async def run():
        await db.block_gif(_GUILD, None, "https://tenor.com/view/foo-123")

        same_url = await db.save_gif_url(_GUILD, "https://tenor.com/view/foo-123")
        assert same_url[0] is False

        different_url = await db.save_gif_url(_GUILD, "https://tenor.com/view/bar-456")
        assert different_url[0] is True

    asyncio.run(run())


def test_unblock_allows_resaving(memory_db):
    async def run():
        await db.block_gif(_GUILD, None, "https://tenor.com/view/foo-123")
        blocked = await db.save_gif_url(_GUILD, "https://tenor.com/view/foo-123")
        assert blocked[0] is False

        deleted = await db.unblock_gif(_GUILD, None, "https://tenor.com/view/foo-123")
        assert deleted is True

        after_unblock = await db.save_gif_url(_GUILD, "https://tenor.com/view/foo-123")
        assert after_unblock[0] is True

    asyncio.run(run())


def test_block_is_scoped_per_guild(memory_db):
    async def run():
        await _insert_gif_with_object(
            memory_db,
            _GUILD,
            "https://pub.example/gifs/aa/hash1.gif",
            "hash1",
            "gifs/aa/hash1.gif",
        )
        await db.block_gif(_GUILD, "hash1", "https://pub.example/gifs/aa/hash1.gif")

        # Mismo content_hash, guild distinto: bloquearlo en uno no afecta al otro.
        inserted, _ = await db.save_gif_url(
            _OTHER_GUILD,
            "https://pub.example/gifs/aa/hash1.gif",
            content_hash="hash1",
        )
        assert inserted is True
        assert await db.is_gif_blocked(_OTHER_GUILD, "hash1", "") is False
        assert await db.is_gif_blocked(_GUILD, "hash1", "") is True

    asyncio.run(run())


def test_list_blocked_gifs_returns_only_this_guild(memory_db):
    async def run():
        await db.block_gif(_GUILD, None, "https://tenor.com/view/foo-123")
        await db.block_gif(_OTHER_GUILD, None, "https://tenor.com/view/bar-456")

        blocked = await db.list_blocked_gifs(_GUILD)
        assert [b["url"] for b in blocked] == ["https://tenor.com/view/foo-123"]

    asyncio.run(run())
