"""Tests de check_rss (cogs/rss.py)."""

import asyncio
import logging
from types import SimpleNamespace

import aiosqlite
import pytest

import cogs.rss as rss_mod
import db
from cogs.rss import RSS, RSSFeedNotFound
from db import (
    RSS_ERROR_CHANNEL_NOT_FOUND,
    RSS_ERROR_FEED_NOT_FOUND,
    RSS_ERROR_NO_PERMISSION,
)

_GUILD = 1
_FEED_URL = "https://ejemplo.com/rss"
_DISCORD_CHANNEL_ID = 10


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


@pytest.fixture(autouse=True)
def patch_text_channel(monkeypatch):
    monkeypatch.setattr(rss_mod.discord, "TextChannel", FakeTextChannel)


@pytest.fixture(autouse=True)
def _fake_guild_locale(monkeypatch):
    async def fake_guild_locale(guild_id):
        return "es"

    monkeypatch.setattr(rss_mod, "guild_locale", fake_guild_locale)


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _add_sub(conn, last_item_id="old", last_error=None, mention_role_id=None):
    await conn.execute(
        "INSERT INTO rss_subscriptions "
        "(guild_id, feed_url, feed_title, discord_channel_id, last_item_id, last_error, mention_role_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _GUILD,
            _FEED_URL,
            "Blog de prueba",
            _DISCORD_CHANNEL_ID,
            last_item_id,
            last_error,
            mention_role_id,
        ),
    )
    await conn.commit()


async def _sub_row(conn):
    async with conn.execute(
        "SELECT last_item_id, last_error FROM rss_subscriptions "
        "WHERE guild_id=? AND feed_url=?",
        (_GUILD, _FEED_URL),
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


def _item(item_id="item-nuevo"):
    return {
        "id": item_id,
        "title": "Un post nuevo",
        "url": "https://ejemplo.com/post-1",
        "feed_title": "Blog de prueba",
    }


def _run(cog):
    asyncio.run(cog.check_rss.coro(cog))


def _make_cog(monkeypatch, get_channel, item=None):
    async def fake_get_latest_rss_item(url):
        return item

    monkeypatch.setattr(rss_mod, "get_latest_rss_item", fake_get_latest_rss_item)
    return RSS(SimpleNamespace(get_channel=get_channel))


# ---------- falta de permiso ----------


def test_no_permission_does_not_send_and_marks_error_once(
    memory_db, monkeypatch, caplog
):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=False)
    cog = _make_cog(monkeypatch, get_channel=lambda cid: channel, item=_item())

    with caplog.at_level(logging.WARNING, logger="cogs.rss"):
        _run(cog)

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", RSS_ERROR_NO_PERMISSION)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="cogs.rss"):
        _run(cog)  # segunda corrida

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", RSS_ERROR_NO_PERMISSION)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# ---------- recuperación ----------


def test_recovery_clears_error_and_sends_pending_item(memory_db, monkeypatch, caplog):
    asyncio.run(_add_sub(memory_db, last_error=RSS_ERROR_NO_PERMISSION))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(
        monkeypatch, get_channel=lambda cid: channel, item=_item("item-pendiente")
    )

    with caplog.at_level(logging.INFO, logger="cogs.rss"):
        _run(cog)

    assert len(channel.sent) == 1
    assert "Un post nuevo" in channel.sent[0]
    assert asyncio.run(_sub_row(memory_db)) == ("item-pendiente", None)
    assert any(
        r.levelno == logging.INFO and "recuperada" in r.getMessage()
        for r in caplog.records
    )


# ---------- canal borrado ----------


def test_channel_not_found_marks_error_without_advancing(memory_db, monkeypatch):
    asyncio.run(_add_sub(memory_db))
    cog = _make_cog(monkeypatch, get_channel=lambda cid: None, item=_item())

    _run(cog)

    assert asyncio.run(_sub_row(memory_db)) == ("old", RSS_ERROR_CHANNEL_NOT_FOUND)


# ---------- feed 404 ----------


def _make_cog_feed_not_found(monkeypatch, get_channel):
    async def fake_get_latest_rss_item(url):
        raise RSSFeedNotFound(url)

    monkeypatch.setattr(rss_mod, "get_latest_rss_item", fake_get_latest_rss_item)
    return RSS(SimpleNamespace(get_channel=get_channel))


def test_feed_not_found_marks_error_once(memory_db, monkeypatch, caplog):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog_feed_not_found(monkeypatch, get_channel=lambda cid: channel)

    with caplog.at_level(logging.WARNING, logger="cogs.rss"):
        _run(cog)

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", RSS_ERROR_FEED_NOT_FOUND)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="cogs.rss"):
        _run(cog)

    assert asyncio.run(_sub_row(memory_db)) == ("old", RSS_ERROR_FEED_NOT_FOUND)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_transient_error_does_not_mark_feed_not_found(memory_db, monkeypatch):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(monkeypatch, get_channel=lambda cid: channel, item=None)

    _run(cog)

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", None)


def test_feed_recovery_clears_error_and_sends_pending_item(
    memory_db, monkeypatch, caplog
):
    asyncio.run(_add_sub(memory_db, last_error=RSS_ERROR_FEED_NOT_FOUND))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(
        monkeypatch, get_channel=lambda cid: channel, item=_item("item-pendiente")
    )

    with caplog.at_level(logging.INFO, logger="cogs.rss"):
        _run(cog)

    assert len(channel.sent) == 1
    assert asyncio.run(_sub_row(memory_db)) == ("item-pendiente", None)
    assert any(
        r.levelno == logging.INFO and "recuperada" in r.getMessage()
        for r in caplog.records
    )


# ---------- allowed_mentions y roles de mención ----------


def test_new_item_sends_with_restricted_allowed_mentions(memory_db, monkeypatch):
    asyncio.run(_add_sub(memory_db, last_item_id="antiguo", mention_role_id=9876))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(
        monkeypatch,
        get_channel=lambda cid: channel,
        item={
            "id": "nuevo-id",
            "title": "Post @everyone peligroso",
            "url": "https://ejemplo.com/post",
            "feed_title": "Blog",
        },
    )

    _run(cog)

    assert len(channel.sent) == 1
    assert "<@&9876>" in channel.sent[0]
    assert len(channel.allowed_mentions) == 1
    am = channel.allowed_mentions[0]
    assert am.everyone is False
    assert am.users is False
    assert len(am.roles) == 1
    assert am.roles[0].id == 9876
