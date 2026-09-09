"""Tests de la nueva actividad reciente en la tab Estadísticas del dashboard:
db.count_corpus_messages_by_day, db.top_corpus_contributors,
generation.top_corpus_words y el endpoint _api_stats_activity que los junta.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import db
import generation
import webapi

_GUILD = 9001


@pytest.fixture
def memory_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_bot.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


async def _seed_corpus(guild_id, channel_id, content, *, days_ago=0, message_id=None):
    created_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = await db.get_db()
    await conn.execute(
        "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (guild_id, channel_id, message_id, content, created_at),
    )
    await conn.commit()


# ─── db.count_corpus_messages_by_day ────────────────────────────────────────


def test_count_by_day_agrupa_por_fecha(memory_db):
    async def _run():
        await _seed_corpus(_GUILD, 1, "hola", days_ago=0, message_id=1)
        await _seed_corpus(_GUILD, 1, "hola de nuevo", days_ago=0, message_id=2)
        await _seed_corpus(_GUILD, 1, "ayer", days_ago=1, message_id=3)
        return await db.count_corpus_messages_by_day(_GUILD, days=14)

    rows = asyncio.run(_run())
    assert len(rows) == 2
    counts = {r["day"]: r["count"] for r in rows}
    assert sorted(counts.values()) == [1, 2]


def test_count_by_day_respeta_ventana_de_dias(memory_db):
    async def _run():
        await _seed_corpus(_GUILD, 1, "viejo", days_ago=30, message_id=1)
        return await db.count_corpus_messages_by_day(_GUILD, days=14)

    assert asyncio.run(_run()) == []


def test_count_by_day_otro_guild_no_se_mezcla(memory_db):
    async def _run():
        await _seed_corpus(_GUILD, 1, "mio", message_id=1)
        await _seed_corpus(_GUILD + 1, 1, "ajeno", message_id=2)
        return await db.count_corpus_messages_by_day(_GUILD, days=14)

    rows = asyncio.run(_run())
    assert len(rows) == 1
    assert rows[0]["count"] == 1


# ─── db.top_corpus_contributors ─────────────────────────────────────────────


def test_top_contributors_ordena_de_mayor_a_menor(memory_db):
    async def _run():
        for i in range(3):
            await db.save_corpus_and_user_message(
                guild_id=_GUILD,
                channel_id=1,
                author_id=111,
                author_name="ana",
                content=f"mensaje {i} de ana",
                message_id=1000 + i,
            )
        await db.save_corpus_and_user_message(
            guild_id=_GUILD,
            channel_id=1,
            author_id=222,
            author_name="beto",
            content="un mensaje de beto",
            message_id=2000,
        )
        return await db.top_corpus_contributors(_GUILD, limit=5)

    rows = asyncio.run(_run())
    assert rows[0]["author_id"] == 111
    assert rows[0]["count"] == 3
    assert rows[1]["author_id"] == 222
    assert rows[1]["count"] == 1


def test_top_contributors_respeta_limit(memory_db):
    async def _run():
        for author_id in range(10):
            await db.save_corpus_and_user_message(
                guild_id=_GUILD,
                channel_id=1,
                author_id=author_id,
                author_name=f"user{author_id}",
                content="hola",
                message_id=author_id,
            )
        return await db.top_corpus_contributors(_GUILD, limit=3)

    assert len(asyncio.run(_run())) == 3


# ─── generation.top_corpus_words ────────────────────────────────────────────


def test_top_words_filtra_stopwords_y_tokens_cortos():
    messages = [
        "el gato salta la barda",
        "el perro salta tambien",
        "un gato duerme",
    ]
    result = generation.top_corpus_words(messages, limit=10)
    words = [r["word"] for r in result]
    assert "el" not in words
    assert "la" not in words
    assert "un" not in words
    assert "gato" in words
    assert "salta" in words


def test_top_words_ignora_urls_menciones_y_emoji():
    messages = [
        "mira esto https://example.com/algo <@123456789> <:pepehands:987654321>",
        "otro mensaje normal sin nada raro",
    ]
    result = generation.top_corpus_words(messages, limit=20)
    words = [r["word"] for r in result]
    assert not any(w.startswith("http") for w in words)
    assert "123456789" not in words


def test_top_words_ordena_por_frecuencia():
    messages = ["purgito purgito purgito", "purgito bot", "otro bot"]
    result = generation.top_corpus_words(messages, limit=5)
    assert result[0]["word"] == "purgito"
    assert result[0]["count"] == 4


def test_top_words_respeta_limit():
    messages = ["alfa beta gamma delta epsilon zeta"]
    result = generation.top_corpus_words(messages, limit=2)
    assert len(result) == 2


# ─── webapi._api_stats_activity ─────────────────────────────────────────────


class FakeRequest:
    def __init__(self, guild_id=_GUILD):
        self.match_info = {"guild_id": str(guild_id)}
        self.method = "GET"
        self.headers = {}
        self.remote = "1.2.3.4"


@pytest.fixture(autouse=True)
def allow_guild_access(monkeypatch):
    async def fake_check_guild_access(request, guild_id):
        return None

    async def fake_get_session(request):
        return {"user_id": "1", "username": "u"}

    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(
        webapi, "_bot_guild", lambda request, guild_id: SimpleNamespace()
    )


def test_api_stats_activity_junta_las_tres_metricas(memory_db):
    async def _run():
        await db.save_corpus_and_user_message(
            guild_id=_GUILD,
            channel_id=1,
            author_id=111,
            author_name="ana",
            content="purgito es genial",
            message_id=1,
        )
        return await webapi._api_stats_activity(FakeRequest())

    resp = asyncio.run(_run())
    assert resp.status == 200
    data = json.loads(resp.body)
    assert "by_day" in data
    assert "top_contributors" in data
    assert "top_words" in data
    assert data["top_contributors"][0]["author_name"] == "ana"
    assert isinstance(data["top_contributors"][0]["author_id"], str)


def test_api_stats_activity_sin_datos_no_rompe(memory_db):
    resp = asyncio.run(webapi._api_stats_activity(FakeRequest()))
    assert resp.status == 200
    data = json.loads(resp.body)
    assert data["by_day"] == []
    assert data["top_contributors"] == []
    assert data["top_words"] == []
