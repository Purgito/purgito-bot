"""Tests de trim_guild_total_if_needed y _water_fill_threshold (db.py): tope
combinado sobre el TOTAL de corpus_messages de un guild (todos los canales
sumados), como red de seguridad adicional sobre trim_corpus_if_needed
(que ya limita por canal). La política es water-filling, NO "más antiguo
global" — ver tests/test_trim_corpus.py para el bug que eso causaba.

Usa una DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db."""

import asyncio

import aiosqlite
import pytest

import db

_GUILD = 1
_CHAN_A = 10
_CHAN_B = 20
_CHAN_C = 30


def test_water_fill_threshold_basic():
    # A=100, B=50, C=10, cap=100 -> T=45 (45+45+10=100)
    assert db._water_fill_threshold([100, 50, 10], 100) == 45


def test_water_fill_threshold_small_channels_never_forced_below_their_own_count():
    # D=1000, E=F=G=1, cap=10 -> los 3 canales de 1 solo aportan 1 c/u (no
    # bajan de su propio count), así que T sube hasta 7 para D: 7+1+1+1=10
    assert db._water_fill_threshold([1000, 1, 1, 1], 10) == 7


def test_water_fill_threshold_under_cap_is_noop():
    assert (
        db._water_fill_threshold([5, 3, 2], 100) == 5
    )  # max(counts), nada que recortar


def test_water_fill_threshold_empty():
    assert db._water_fill_threshold([], 100) == 0


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    monkeypatch.setenv("MAX_CORPUS_MESSAGES_PER_GUILD_TOTAL_FREE", "10")
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _insert_n(conn, guild_id, channel_id, n, start=0):
    for i in range(start, start + n):
        await conn.execute(
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
            "VALUES (?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                guild_id * 1_000_000 + channel_id * 1000 + i,
                f"msg{i}",
            ),
        )
    await conn.commit()


async def _count(conn, guild_id, channel_id):
    cur = await conn.execute(
        "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    )
    return (await cur.fetchone())[0]


def test_trim_is_proportional_small_channel_untouched(memory_db):
    """cap=10; A=8, B=6, C=2 (total=16). Umbral esperado T=4 (4+4+2=10):
    A y B se recortan parejo a 4, C (ya chico) queda intacto, sin llegar a 0."""

    async def run():
        await _insert_n(memory_db, _GUILD, _CHAN_A, 8)
        await _insert_n(memory_db, _GUILD, _CHAN_B, 6)
        await _insert_n(memory_db, _GUILD, _CHAN_C, 2)

        await db.trim_guild_total_if_needed(_GUILD)

        assert await _count(memory_db, _GUILD, _CHAN_A) == 4
        assert await _count(memory_db, _GUILD, _CHAN_B) == 4
        assert await _count(memory_db, _GUILD, _CHAN_C) == 2, (
            "un canal ya chico no debe llegar a 0 solo por orden de procesamiento"
        )

    asyncio.run(run())


def test_trim_deletes_oldest_within_each_trimmed_channel(memory_db):
    async def run():
        await _insert_n(memory_db, _GUILD, _CHAN_A, 8)  # msg0..msg7, ids ascendentes
        await _insert_n(memory_db, _GUILD, _CHAN_B, 6)
        await _insert_n(memory_db, _GUILD, _CHAN_C, 2)

        await db.trim_guild_total_if_needed(_GUILD)

        cur = await memory_db.execute(
            "SELECT message_id FROM corpus_messages WHERE guild_id=? AND channel_id=? ORDER BY id",
            (_GUILD, _CHAN_A),
        )
        remaining = [r[0] async for r in cur]
        # quedan los 4 más nuevos de los 8 originales (msg4..msg7)
        assert remaining == [
            _GUILD * 1_000_000 + _CHAN_A * 1000 + i for i in (4, 5, 6, 7)
        ]

    asyncio.run(run())


def test_trim_noop_under_cap(memory_db):
    async def run():
        await _insert_n(memory_db, _GUILD, _CHAN_A, 3)
        await _insert_n(memory_db, _GUILD, _CHAN_B, 3)
        await db.trim_guild_total_if_needed(_GUILD)
        assert await _count(memory_db, _GUILD, _CHAN_A) == 3
        assert await _count(memory_db, _GUILD, _CHAN_B) == 3

    asyncio.run(run())
