"""Tests de db.py: delete_recent_corpus ("amnesia" de 24h).

DB SQLite en memoria vía executescript(db.SCHEMA) -- corpus_messages y
user_corpus están completas en el CREATE TABLE base (sin columnas de ALTER
TABLE), mismo patrón liviano que test_trim_corpus.py.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

import db

_GUILD = 1
_CHANNEL = 10


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


# ─── delete_recent_corpus ("amnesia") ────────────────────────────────────────


async def _insert_at(conn, table, guild_id, channel_or_author, created_at, n=1):
    for i in range(n):
        if table == "corpus_messages":
            await conn.execute(
                "INSERT INTO corpus_messages "
                "(guild_id, channel_id, message_id, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild_id, channel_or_author, None, f"msg{i}-{created_at}", created_at),
            )
        else:
            await conn.execute(
                "INSERT INTO user_corpus "
                "(guild_id, author_id, author_name, message_id, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    channel_or_author,
                    "user",
                    None,
                    f"msg{i}-{created_at}",
                    created_at,
                ),
            )
    await conn.commit()


def _iso(hours_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def test_amnesia_borra_solo_lo_de_las_ultimas_24h(memory_db):
    asyncio.run(_insert_at(memory_db, "corpus_messages", _GUILD, _CHANNEL, _iso(1)))
    asyncio.run(_insert_at(memory_db, "corpus_messages", _GUILD, _CHANNEL, _iso(48)))

    deleted = asyncio.run(db.delete_recent_corpus(_GUILD, hours=24))

    assert deleted["corpus_messages"] == 1
    rows = asyncio.run(db.get_corpus_messages(_GUILD))
    assert len(rows) == 1  # el de hace 48h sobrevive


def test_amnesia_borra_tambien_user_corpus(memory_db):
    asyncio.run(_insert_at(memory_db, "user_corpus", _GUILD, 555, _iso(1)))

    deleted = asyncio.run(db.delete_recent_corpus(_GUILD, hours=24))

    assert deleted["user_corpus"] == 1


def test_amnesia_esta_scopeada_al_guild(memory_db):
    asyncio.run(_insert_at(memory_db, "corpus_messages", _GUILD, _CHANNEL, _iso(1)))
    asyncio.run(_insert_at(memory_db, "corpus_messages", 999, _CHANNEL, _iso(1)))

    asyncio.run(db.delete_recent_corpus(_GUILD, hours=24))

    assert asyncio.run(db.count_guild_corpus_messages(_GUILD)) == 0
    assert asyncio.run(db.count_guild_corpus_messages(999)) == 1


def test_amnesia_sin_nada_reciente_no_rompe(memory_db):
    asyncio.run(_insert_at(memory_db, "corpus_messages", _GUILD, _CHANNEL, _iso(48)))

    deleted = asyncio.run(db.delete_recent_corpus(_GUILD, hours=24))

    assert deleted == {"corpus_messages": 0, "user_corpus": 0}
    assert asyncio.run(db.count_guild_corpus_messages(_GUILD)) == 1
