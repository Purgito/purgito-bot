"""Tests de check_twitch (cogs/twitch.py) -- mismo diseño que check_youtube
(ver test_youtube_check.py): estado roto (sin permiso / canal borrado) se
detecta antes de mandar nada, se loguea una sola vez por cada vez que se
rompe, y se limpia solo cuando el canal vuelve a estar bien. La diferencia
con YouTube es que acá "hay algo nuevo" se resuelve comparando contra un mapa
de streams en vivo (get_live_streams), no contra un solo fetch por canal.
"""

import asyncio
import logging
from types import SimpleNamespace

import aiosqlite
import pytest

import cogs.twitch as twitch_mod
import db
from cogs.twitch import Twitch
from db import TWITCH_ERROR_CHANNEL_NOT_FOUND, TWITCH_ERROR_NO_PERMISSION

_GUILD = 1
_TWITCH_USER_ID = "999"
_DISCORD_CHANNEL_ID = 10


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


@pytest.fixture(autouse=True)
def patch_text_channel(monkeypatch):
    monkeypatch.setattr(twitch_mod.discord, "TextChannel", FakeTextChannel)


@pytest.fixture(autouse=True)
def _fake_guild_locale(monkeypatch):
    async def fake_guild_locale(guild_id):
        return "es"

    monkeypatch.setattr(twitch_mod, "guild_locale", fake_guild_locale)


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _add_sub(conn, last_stream_id="old", last_error=None):
    await conn.execute(
        "INSERT INTO twitch_subscriptions "
        "(guild_id, twitch_user_id, twitch_login, discord_channel_id, last_stream_id, last_error) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            _GUILD,
            _TWITCH_USER_ID,
            "canal_de_prueba",
            _DISCORD_CHANNEL_ID,
            last_stream_id,
            last_error,
        ),
    )
    await conn.commit()


async def _sub_row(conn):
    async with conn.execute(
        "SELECT last_stream_id, last_error FROM twitch_subscriptions "
        "WHERE guild_id=? AND twitch_user_id=?",
        (_GUILD, _TWITCH_USER_ID),
    ) as cur:
        return await cur.fetchone()


class FakePermissions:
    def __init__(self, send_messages):
        self.send_messages = send_messages


class FakeTextChannel:
    def __init__(self, send_messages=True):
        self.guild = SimpleNamespace(me=object())
        self._send_messages = send_messages
        self.sent: list[str] = []
        self.allowed_mentions: list = []

    def permissions_for(self, member):
        return FakePermissions(self._send_messages)

    async def send(self, content, allowed_mentions=None):
        self.sent.append(content)
        self.allowed_mentions.append(allowed_mentions)


def _stream(stream_id="stream-nuevo"):
    return {
        "id": stream_id,
        "title": "Jugando algo",
        "game_name": "Un juego",
        "url": "https://twitch.tv/canal_de_prueba",
    }


def _run(cog):
    asyncio.run(cog.check_twitch.coro(cog))


def _make_cog(monkeypatch, get_channel, live: dict | None = None):
    async def fake_get_live_streams(user_ids):
        return live or {}

    monkeypatch.setattr(twitch_mod, "get_live_streams", fake_get_live_streams)
    return Twitch(SimpleNamespace(get_channel=get_channel))


# ---------- sin suscripciones ----------


def test_no_subs_does_not_call_get_live_streams(memory_db, monkeypatch):
    called = []

    async def fake_get_live_streams(user_ids):
        called.append(user_ids)
        return {}

    monkeypatch.setattr(twitch_mod, "get_live_streams", fake_get_live_streams)
    cog = Twitch(SimpleNamespace(get_channel=lambda cid: None))
    _run(cog)
    assert called == []


# ---------- falta de permiso ----------


def test_no_permission_does_not_send_and_marks_error_once(
    memory_db, monkeypatch, caplog
):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=False)
    cog = _make_cog(
        monkeypatch, get_channel=lambda cid: channel, live={_TWITCH_USER_ID: _stream()}
    )

    with caplog.at_level(logging.WARNING, logger="cogs.twitch"):
        _run(cog)

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", TWITCH_ERROR_NO_PERMISSION)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="cogs.twitch"):
        _run(cog)  # segunda corrida, el estado roto sigue igual

    assert asyncio.run(_sub_row(memory_db)) == ("old", TWITCH_ERROR_NO_PERMISSION)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# ---------- recuperación ----------


def test_recovery_clears_error_and_sends_pending_stream(memory_db, monkeypatch, caplog):
    asyncio.run(_add_sub(memory_db, last_error=TWITCH_ERROR_NO_PERMISSION))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(
        monkeypatch,
        get_channel=lambda cid: channel,
        live={_TWITCH_USER_ID: _stream("stream-pendiente")},
    )

    with caplog.at_level(logging.INFO, logger="cogs.twitch"):
        _run(cog)

    assert len(channel.sent) == 1
    assert "canal_de_prueba" in channel.sent[0]
    assert asyncio.run(_sub_row(memory_db)) == ("stream-pendiente", None)
    assert any(
        r.levelno == logging.INFO and "recuperada" in r.getMessage()
        for r in caplog.records
    )


# ---------- canal borrado ----------


def test_channel_not_found_marks_error_without_advancing(memory_db, monkeypatch):
    asyncio.run(_add_sub(memory_db))
    cog = _make_cog(
        monkeypatch, get_channel=lambda cid: None, live={_TWITCH_USER_ID: _stream()}
    )

    _run(cog)

    assert asyncio.run(_sub_row(memory_db)) == ("old", TWITCH_ERROR_CHANNEL_NOT_FOUND)


# ---------- no está en vivo ----------


def test_not_live_does_not_send_and_leaves_last_stream_id_untouched(
    memory_db, monkeypatch
):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(monkeypatch, get_channel=lambda cid: channel, live={})

    _run(cog)

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", None)


def test_still_live_same_stream_id_does_not_resend(memory_db, monkeypatch):
    """Mismo stream_id que la última vez: sigue en vivo desde el chequeo
    anterior, no es un aviso nuevo."""
    asyncio.run(_add_sub(memory_db, last_stream_id="stream-actual"))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(
        monkeypatch,
        get_channel=lambda cid: channel,
        live={_TWITCH_USER_ID: _stream("stream-actual")},
    )

    _run(cog)

    assert channel.sent == []


# ---------- error genérico no relacionado ----------


def test_unrelated_exception_in_get_live_streams_does_not_crash(memory_db, monkeypatch):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=True)

    async def boom(user_ids):
        raise RuntimeError("Twitch caído")

    monkeypatch.setattr(twitch_mod, "get_live_streams", boom)
    cog = Twitch(SimpleNamespace(get_channel=lambda cid: channel))

    _run(cog)  # no debe propagar la excepción

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", None)


def test_mention_role_is_included_and_restricted(memory_db, monkeypatch):
    conn = memory_db
    asyncio.run(
        conn.execute(
            "INSERT INTO twitch_subscriptions "
            "(guild_id, twitch_user_id, twitch_login, discord_channel_id, mention_role_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (_GUILD, _TWITCH_USER_ID, "canal_de_prueba", _DISCORD_CHANNEL_ID, 777),
        )
    )
    asyncio.run(conn.commit())
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(
        monkeypatch, get_channel=lambda cid: channel, live={_TWITCH_USER_ID: _stream()}
    )

    _run(cog)

    assert len(channel.sent) == 1
    assert "<@&777>" in channel.sent[0]
    mentions = channel.allowed_mentions[0]
    assert mentions.everyone is False
    assert mentions.users is False
