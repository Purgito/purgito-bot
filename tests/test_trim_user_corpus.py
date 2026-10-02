"""Tests de trim_user_corpus_if_needed (db.py): el límite y el DELETE deben
ser por autor, no por guild — un autor muy activo no debe desplazar el
corpus de otros autores del mismo servidor (mismo patrón de bug que
trim_corpus_if_needed, ver tests/test_trim_corpus.py). Usa una DB SQLite
en memoria inyectada en db._db, sin tocar data/bot.db (que está trackeada
en git)."""

import asyncio

import pgdb  # noqa: F401
import pg_support
import pytest

import db

_GUILD = 1
_AUTHOR_A = 10
_AUTHOR_B = 20


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    monkeypatch.setenv("MAX_USER_CORPUS_MESSAGES_PER_GUILD_FREE", "3")
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> pgdb.Database:
    conn = await pg_support.connect()
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _insert_n(conn, guild_id, author_id, n, start=0):
    for i in range(start, start + n):
        await conn.execute(
            "INSERT INTO user_corpus (guild_id, author_id, author_name, message_id, content) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                guild_id,
                author_id,
                "user",
                guild_id * 1_000_000 + author_id * 1000 + i,
                f"msg{i}",
            ),
        )
    await conn.commit()


async def _count(conn, guild_id, author_id):
    cur = await conn.execute(
        "SELECT COUNT(*) FROM user_corpus WHERE guild_id=? AND author_id=?",
        (guild_id, author_id),
    )
    return (await cur.fetchone())[0]


def test_trim_is_per_author_not_per_guild(memory_db):
    """Autor A por debajo del límite no debe perder mensajes cuando el autor B
    (mismo guild) se pasa del límite y se recorta."""

    async def run():
        await _insert_n(memory_db, _GUILD, _AUTHOR_A, 3)  # en el límite (3)
        await _insert_n(memory_db, _GUILD, _AUTHOR_B, 5)  # se pasa del límite (3)
        await db.trim_user_corpus_if_needed(_GUILD, _AUTHOR_B)
        assert await _count(memory_db, _GUILD, _AUTHOR_A) == 3, (
            "el trim del autor B no debe tocar los mensajes del autor A"
        )
        assert await _count(memory_db, _GUILD, _AUTHOR_B) == 3

    asyncio.run(run())


def test_trim_deletes_oldest_first(memory_db):
    async def run():
        await _insert_n(memory_db, _GUILD, _AUTHOR_A, 5)
        await db.trim_user_corpus_if_needed(_GUILD, _AUTHOR_A)
        cur = await memory_db.execute(
            "SELECT message_id FROM user_corpus WHERE guild_id=? AND author_id=? ORDER BY id",
            (_GUILD, _AUTHOR_A),
        )
        remaining = [r[0] async for r in cur]
        # se insertaron msg0..msg4 (ids ascendentes); deben quedar los 3 más nuevos
        assert remaining == [
            _GUILD * 1_000_000 + _AUTHOR_A * 1000 + i for i in (2, 3, 4)
        ]

    asyncio.run(run())


def test_insert_or_ignore_prevents_duplicates(memory_db):
    """UNIQUE(guild_id, message_id) + INSERT OR IGNORE: reinsertar el mismo
    message_id no debe crear una fila duplicada (aunque cambie el autor)."""

    async def run():
        for _ in range(3):
            await memory_db.execute(
                "INSERT OR IGNORE INTO user_corpus (guild_id, author_id, author_name, message_id, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (_GUILD, _AUTHOR_A, "user", 999, "hola"),
            )
        await memory_db.commit()
        assert await _count(memory_db, _GUILD, _AUTHOR_A) == 1

    asyncio.run(run())
