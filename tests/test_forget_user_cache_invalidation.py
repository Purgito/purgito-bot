"""Tests de generation.forget_user: la capa fuera de db.py que junta
db.delete_user_data() con generation.reset_guild_caches() por cada guild
afectado -- incluso si el autor solo tenía filas UNKNOWN en ese guild. Ver
docstring de forget_user en generation.py.

Usa una DB SQLite en memoria inyectada en db._db (no toca data/bot.db) y
puebla a mano los caches en memoria de generation.py para comprobar que se
invalidan de verdad, no solo que el reporte de borrado sea correcto."""

import asyncio

import aiosqlite
import pytest

import db
import generation

_GUILD_A = 1
_GUILD_B = 2
_GUILD_UNTOUCHED = 3
_AUTHOR_A = 10
_CHANNEL_1 = 100


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.execute("ALTER TABLE user_corpus ADD COLUMN channel_id INTEGER")
    await conn.commit()
    return conn


async def _seed(conn, guild_id, author_id, message_id, with_corpus_message=True):
    if with_corpus_message:
        await conn.execute(
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
            "VALUES (?, ?, ?, ?)",
            (guild_id, _CHANNEL_1, message_id, "c"),
        )
    await conn.execute(
        "INSERT INTO user_corpus (guild_id, author_id, author_name, channel_id, message_id, content) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            guild_id,
            author_id,
            "user",
            _CHANNEL_1 if with_corpus_message else None,
            message_id,
            "c",
        ),
    )
    await conn.commit()


@pytest.fixture(autouse=True)
def _clean_generation_caches():
    """generation._markov_cache etc. son globales de módulo: aislar cada
    test para no arrastrar estado de otros tests que corren en el mismo
    proceso."""
    yield
    for guild_id in (_GUILD_A, _GUILD_B, _GUILD_UNTOUCHED):
        generation.reset_guild_caches(guild_id)


def test_forget_user_borra_e_invalida_cache_de_todos_los_guilds_afectados(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _AUTHOR_A, 1)
        await _seed(memory_db, _GUILD_B, _AUTHOR_A, 2)

        generation._markov_cache[_GUILD_A] = object()
        generation._markov_cache[_GUILD_B] = object()
        generation._markov_cache[_GUILD_UNTOUCHED] = object()

        report = await generation.forget_user(_AUTHOR_A)

        assert report["user_corpus_deleted"] == 2
        assert _GUILD_A not in generation._markov_cache
        assert _GUILD_B not in generation._markov_cache
        # El cache de un guild que no tenía nada que ver no debe tocarse.
        assert _GUILD_UNTOUCHED in generation._markov_cache

    asyncio.run(run())


def test_forget_user_invalida_cache_aunque_todo_sea_unknown(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _AUTHOR_A, 999, with_corpus_message=False)
        generation._markov_cache[_GUILD_A] = object()

        report = await generation.forget_user(_AUTHOR_A)

        assert report["unknown_deleted"] == 1
        assert report["corpus_messages_deleted"] == 0
        assert _GUILD_A not in generation._markov_cache

    asyncio.run(run())


def test_forget_user_sin_datos_no_falla_y_no_toca_ningun_cache(memory_db):
    async def run():
        generation._markov_cache[_GUILD_UNTOUCHED] = object()
        report = await generation.forget_user(999_999)
        assert report["guild_ids"] == []
        assert _GUILD_UNTOUCHED in generation._markov_cache

    asyncio.run(run())
