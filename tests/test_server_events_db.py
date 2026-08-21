import asyncio

import aiosqlite
import pytest

import db
from db import (
    delete_server_event,
    get_server_event,
    is_boost_processed,
    list_server_events,
    purge_guild_data,
    record_member_boost,
    set_server_event,
    toggle_server_event,
)


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


def test_server_events_crud_and_isolation(memory_db):
    async def _test():
        guild1 = 111
        guild2 = 222

        # Initial state: None
        assert await get_server_event(guild1, "welcome") is None
        assert await list_server_events(guild1) == {}

        # Set welcome for guild1
        ev1 = await set_server_event(
            guild_id=guild1,
            event_type="welcome",
            enabled=True,
            channel_id=12345,
            content_mode="plain_text",
            message="Bienvenido {user} a {server_name}!",
            embed_json=None,
        )
        assert ev1["guild_id"] == guild1
        assert ev1["event_type"] == "welcome"
        assert ev1["enabled"] is True
        assert ev1["channel_id"] == 12345
        assert ev1["content_mode"] == "plain_text"
        assert ev1["message"] == "Bienvenido {user} a {server_name}!"

        # Isolation check: guild2 still has nothing
        assert await get_server_event(guild2, "welcome") is None
        assert await list_server_events(guild2) == {}

        # Set boost for guild1
        await set_server_event(
            guild_id=guild1,
            event_type="boost",
            enabled=False,
            channel_id=54321,
            content_mode="classic_embed",
            message=None,
            embed_json='[{"title": "Nuevo Boost de {user}!"}]',
        )

        all_g1 = await list_server_events(guild1)
        assert len(all_g1) == 2
        assert "welcome" in all_g1
        assert "boost" in all_g1
        assert all_g1["welcome"]["enabled"] is True
        assert all_g1["boost"]["enabled"] is False

        # Toggle event
        toggled = await toggle_server_event(guild1, "boost", True)
        assert toggled is True
        boost_ev = await get_server_event(guild1, "boost")
        assert boost_ev["enabled"] is True

        # Delete event
        deleted = await delete_server_event(guild1, "welcome")
        assert deleted is True
        assert await get_server_event(guild1, "welcome") is None

        # Delete non-existent returns False
        assert await delete_server_event(guild1, "welcome") is False

        # Purge guild data cleans up
        await set_server_event(
            guild_id=guild1,
            event_type="goodbye",
            enabled=True,
            channel_id=999,
            content_mode="plain_text",
            message="Adios {user}",
        )
        await purge_guild_data(guild1)
        assert await list_server_events(guild1) == {}

    asyncio.run(_test())


def test_member_boost_idempotency_records(memory_db):
    async def _test():
        guild_id = 999
        user_id = 888
        timestamp = "2026-08-21T12:00:00+00:00"

        assert await is_boost_processed(guild_id, user_id, timestamp) is False

        await record_member_boost(guild_id, user_id, timestamp)
        assert await is_boost_processed(guild_id, user_id, timestamp) is True

        # Different timestamp (e.g. later boost)
        timestamp2 = "2026-09-01T12:00:00+00:00"
        assert await is_boost_processed(guild_id, user_id, timestamp2) is False
        await record_member_boost(guild_id, user_id, timestamp2)
        assert await is_boost_processed(guild_id, user_id, timestamp2) is True

    asyncio.run(_test())


def test_try_record_member_boost_atomicity(memory_db):
    """SEC-01: Comprobar que try_record_member_boost opera de forma atómica devolviendo True sólo al ganador."""
    from db import try_record_member_boost

    async def _test():
        guild_id = 555
        user_id = 444
        ts_a = "2026-08-21T10:00:00+00:00"
        ts_b = "2026-09-01T15:00:00+00:00"

        # Primer intento con ts_a: gana (True)
        assert await try_record_member_boost(guild_id, user_id, ts_a) is True

        # Segundo intento con exactamente el mismo ts_a: pierde (False)
        assert await try_record_member_boost(guild_id, user_id, ts_a) is False

        # Nuevo boost legítimo con ts_b: gana (True)
        assert await try_record_member_boost(guild_id, user_id, ts_b) is True

        # Repetición con ts_b: pierde (False)
        assert await try_record_member_boost(guild_id, user_id, ts_b) is False

    asyncio.run(_test())


def test_purge_guild_data_clears_channel_webhooks_and_events(memory_db):
    """SEC-08: purge_guild_data debe limpiar server_events, member_boost_records y channel_webhooks."""
    from db import get_channel_webhook, get_server_event, set_channel_webhook

    async def _test():
        guild_id = 777
        channel_id = 888

        # 1. Crear server_event
        await set_server_event(
            guild_id=guild_id,
            event_type="welcome",
            enabled=True,
            channel_id=channel_id,
            content_mode="plain_text",
            message="Welcome!",
        )

        # 2. Crear member_boost_record
        from db import try_record_member_boost
        await try_record_member_boost(guild_id, 123, "2026-08-21T10:00:00")

        # 3. Crear channel_webhook
        await set_channel_webhook(guild_id, channel_id, 999999, "fake_token_123")

        assert await get_server_event(guild_id, "welcome") is not None
        assert await get_channel_webhook(guild_id, channel_id) is not None

        # 4. Purgar datos del servidor
        await purge_guild_data(guild_id)

        # 5. Comprobar que no queda rastro
        assert await get_server_event(guild_id, "welcome") is None
        assert await get_channel_webhook(guild_id, channel_id) is None
        assert await is_boost_processed(guild_id, 123, "2026-08-21T10:00:00") is False

    asyncio.run(_test())
