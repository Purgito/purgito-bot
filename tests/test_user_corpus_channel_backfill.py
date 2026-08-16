"""Tests de backfill_user_corpus_channel_id (db.py): retro-poblado de
user_corpus.channel_id cruzando por (guild_id, message_id) contra
corpus_messages. Base de trazabilidad para el eventual Right to be
Forgotten individual -- ver docs/superpowers/specs/2026-08-15-nsfw-learning-block-design.md
punto 4. Usa una DB SQLite en memoria inyectada en db._db, sin tocar
data/bot.db (que está trackeada en git)."""

import asyncio

import aiosqlite
import pytest

import db

_GUILD_A = 1
_GUILD_B = 2
_AUTHOR_A = 10
_AUTHOR_B = 20
_CHANNEL_1 = 100
_CHANNEL_2 = 200


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    # user_corpus nace sin channel_id en el schema base; init_db() la suma
    # con ALTER TABLE -- replicarlo acá para no depender de init_db() (que
    # abre una conexión real a DB_PATH) en tests de solo memoria.
    await conn.execute("ALTER TABLE user_corpus ADD COLUMN channel_id INTEGER")
    await conn.commit()
    return conn


async def _insert_corpus_message(conn, guild_id, channel_id, message_id, content="c"):
    await conn.execute(
        "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
        "VALUES (?, ?, ?, ?)",
        (guild_id, channel_id, message_id, content),
    )
    await conn.commit()


async def _insert_user_corpus(
    conn, guild_id, author_id, message_id, content="c", author_name="user"
):
    await conn.execute(
        "INSERT INTO user_corpus (guild_id, author_id, author_name, message_id, content) "
        "VALUES (?, ?, ?, ?, ?)",
        (guild_id, author_id, author_name, message_id, content),
    )
    await conn.commit()


async def _channel_id_of(conn, guild_id, message_id):
    cur = await conn.execute(
        "SELECT channel_id FROM user_corpus WHERE guild_id=? AND message_id IS ?",
        (guild_id, message_id),
    )
    row = await cur.fetchone()
    return row[0] if row else None


def test_matches_by_guild_and_message_id(memory_db):
    async def run():
        await _insert_corpus_message(memory_db, _GUILD_A, _CHANNEL_1, 1)
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_A, 1)
        report = await db.backfill_user_corpus_channel_id()
        assert await _channel_id_of(memory_db, _GUILD_A, 1) == _CHANNEL_1
        assert report["total"] == 1
        assert report["traceable"] == 1
        assert report["unknown"] == 0

    asyncio.run(run())


def test_unmatched_message_id_stays_null(memory_db):
    async def run():
        # message_id 999 nunca llegó a corpus_messages (p.ej. se recortó por
        # trim_corpus_if_needed) -- no hay con qué cruzar.
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_A, 999)
        report = await db.backfill_user_corpus_channel_id()
        assert await _channel_id_of(memory_db, _GUILD_A, 999) is None
        assert report["total"] == 1
        assert report["traceable"] == 0
        assert report["unknown"] == 1
        assert report["unmatched"] == 1
        assert report["no_message_id"] == 0

    asyncio.run(run())


def test_same_message_id_different_guilds_does_not_cross(memory_db):
    async def run():
        await _insert_corpus_message(memory_db, _GUILD_A, _CHANNEL_1, 42)
        await _insert_corpus_message(memory_db, _GUILD_B, _CHANNEL_2, 42)
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_A, 42)
        await _insert_user_corpus(memory_db, _GUILD_B, _AUTHOR_B, 42)
        await db.backfill_user_corpus_channel_id()
        assert await _channel_id_of(memory_db, _GUILD_A, 42) == _CHANNEL_1
        assert await _channel_id_of(memory_db, _GUILD_B, 42) == _CHANNEL_2

    asyncio.run(run())


def test_multiple_authors_isolated_correctly(memory_db):
    async def run():
        await _insert_corpus_message(memory_db, _GUILD_A, _CHANNEL_1, 1)
        await _insert_corpus_message(memory_db, _GUILD_A, _CHANNEL_2, 2)
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_A, 1)
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_B, 2)
        await db.backfill_user_corpus_channel_id()
        assert await _channel_id_of(memory_db, _GUILD_A, 1) == _CHANNEL_1
        assert await _channel_id_of(memory_db, _GUILD_A, 2) == _CHANNEL_2

    asyncio.run(run())


def test_running_twice_is_idempotent(memory_db):
    async def run():
        await _insert_corpus_message(memory_db, _GUILD_A, _CHANNEL_1, 1)
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_A, 1)
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_B, 999)  # sin match

        report1 = await db.backfill_user_corpus_channel_id()
        report2 = await db.backfill_user_corpus_channel_id()

        assert report1 == report2
        assert await _channel_id_of(memory_db, _GUILD_A, 1) == _CHANNEL_1
        assert await _channel_id_of(memory_db, _GUILD_A, 999) is None

        cur = await memory_db.execute("SELECT COUNT(*) FROM user_corpus")
        assert (await cur.fetchone())[0] == 2, (
            "correrla dos veces no debe duplicar filas"
        )

    asyncio.run(run())


def test_existing_content_and_authors_untouched(memory_db):
    """La migración no debe tocar ninguna columna salvo channel_id."""

    async def run():
        await _insert_corpus_message(memory_db, _GUILD_A, _CHANNEL_1, 1)
        await _insert_user_corpus(
            memory_db,
            _GUILD_A,
            _AUTHOR_A,
            1,
            content="hola mundo",
            author_name="Fulano",
        )
        await db.backfill_user_corpus_channel_id()
        cur = await memory_db.execute(
            "SELECT author_id, author_name, content FROM user_corpus "
            "WHERE guild_id=? AND message_id=?",
            (_GUILD_A, 1),
        )
        row = await cur.fetchone()
        assert row == (_AUTHOR_A, "Fulano", "hola mundo")

    asyncio.run(run())


def test_row_without_message_id_stays_null_and_is_reported_separately(memory_db):
    async def run():
        await _insert_user_corpus(memory_db, _GUILD_A, _AUTHOR_A, None)
        report = await db.backfill_user_corpus_channel_id()
        assert await _channel_id_of(memory_db, _GUILD_A, None) is None
        assert report["no_message_id"] == 1
        assert report["unmatched"] == 0
        assert report["unknown"] == 1

    asyncio.run(run())
