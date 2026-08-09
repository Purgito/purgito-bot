"""Tests de check_youtube (cogs/youtube.py).

Antes, si el bot no podía escribir en el canal destino, channel.send()
tiraba discord.Forbidden y caía en el except Exception genérico: se logueaba
como error y se repetía cada 15 minutos para siempre, sin que nadie se
enterara salvo mirando los logs. Ahora el estado roto (sin permiso / canal
borrado) se detecta ANTES de intentar mandar nada, se loguea una sola vez
por cada vez que se rompe, y se limpia solo cuando el canal vuelve a estar
bien -- ver docs/AUDITORIA_UX.md, hallazgo 7 (b) y (c).

isinstance(channel, discord.TextChannel) se satisface parcheando
discord.TextChannel por la clase fake, mismo patrón que
test_memes_target_fail.py. DB en memoria, mismo patrón que test_gif_dedup.py.
"""

import asyncio
import logging
from types import SimpleNamespace

import aiosqlite
import pytest

import cogs.youtube as youtube_mod
import db
from cogs.youtube import YouTube
from db import YOUTUBE_ERROR_CHANNEL_NOT_FOUND, YOUTUBE_ERROR_NO_PERMISSION

_GUILD = 1
_YT_CHANNEL_ID = "UCxxx"
_DISCORD_CHANNEL_ID = 10


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


@pytest.fixture(autouse=True)
def patch_text_channel(monkeypatch):
    monkeypatch.setattr(youtube_mod.discord, "TextChannel", FakeTextChannel)


@pytest.fixture(autouse=True)
def _fake_guild_locale(monkeypatch):
    """check_youtube resuelve el locale del guild vía la columna settings.locale,
    que se agrega con un ALTER TABLE en init_db() -- no está en el db.SCHEMA
    crudo que usa memory_db acá. Se mockea para no requerir esa migración."""

    async def fake_guild_locale(guild_id):
        return "es"

    monkeypatch.setattr(youtube_mod, "guild_locale", fake_guild_locale)


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _add_sub(conn, last_video_id="old", last_error=None):
    await conn.execute(
        "INSERT INTO youtube_subscriptions "
        "(guild_id, channel_id, youtube_channel_id, youtube_channel_name, "
        "discord_channel_id, last_video_id, last_error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _GUILD,
            5,
            _YT_CHANNEL_ID,
            "Canal de prueba",
            _DISCORD_CHANNEL_ID,
            last_video_id,
            last_error,
        ),
    )
    await conn.commit()


async def _sub_row(conn):
    async with conn.execute(
        "SELECT last_video_id, last_error FROM youtube_subscriptions "
        "WHERE guild_id=? AND youtube_channel_id=?",
        (_GUILD, _YT_CHANNEL_ID),
    ) as cur:
        return await cur.fetchone()


class FakePermissions:
    def __init__(self, send_messages):
        self.send_messages = send_messages


class FakeTextChannel:
    """Se registra como discord.TextChannel (ver fixture patch_text_channel)
    para satisfacer isinstance() dentro de cogs/youtube.py."""

    def __init__(self, send_messages=True):
        self.guild = SimpleNamespace(me=object())
        self._send_messages = send_messages
        self.sent: list[str] = []

    def permissions_for(self, member):
        return FakePermissions(self._send_messages)

    async def send(self, content):
        self.sent.append(content)


def _video(video_id="video-nuevo"):
    return {
        "id": video_id,
        "title": "Un video",
        "url": "https://youtu.be/x",
        "author": "Canal de prueba",
    }


def _run(cog):
    asyncio.run(cog.check_youtube.coro(cog))


def _make_cog(monkeypatch, get_channel, video=None):
    async def fake_get_latest_video(youtube_channel_id):
        return video

    monkeypatch.setattr(youtube_mod, "get_latest_video", fake_get_latest_video)
    return YouTube(SimpleNamespace(get_channel=get_channel))


# ---------- falta de permiso ----------


def test_no_permission_does_not_send_and_marks_error_once(
    memory_db, monkeypatch, caplog
):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=False)
    cog = _make_cog(monkeypatch, get_channel=lambda cid: channel, video=_video())

    with caplog.at_level(logging.WARNING, logger="cogs.youtube"):
        _run(cog)

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", YOUTUBE_ERROR_NO_PERMISSION)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="cogs.youtube"):
        _run(cog)  # segunda corrida, el estado roto sigue igual

    assert channel.sent == []
    assert asyncio.run(_sub_row(memory_db)) == ("old", YOUTUBE_ERROR_NO_PERMISSION)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# ---------- recuperación ----------


def test_recovery_clears_error_and_sends_pending_video(memory_db, monkeypatch, caplog):
    asyncio.run(_add_sub(memory_db, last_error=YOUTUBE_ERROR_NO_PERMISSION))
    channel = FakeTextChannel(send_messages=True)
    cog = _make_cog(
        monkeypatch, get_channel=lambda cid: channel, video=_video("video-pendiente")
    )

    with caplog.at_level(logging.INFO, logger="cogs.youtube"):
        _run(cog)

    assert len(channel.sent) == 1
    assert "Un video" in channel.sent[0]
    assert asyncio.run(_sub_row(memory_db)) == ("video-pendiente", None)
    assert any(
        r.levelno == logging.INFO and "recuperada" in r.getMessage()
        for r in caplog.records
    )


# ---------- canal borrado ----------


def test_channel_not_found_marks_error_without_advancing(memory_db, monkeypatch):
    asyncio.run(_add_sub(memory_db))
    cog = _make_cog(monkeypatch, get_channel=lambda cid: None, video=_video())

    _run(cog)

    assert asyncio.run(_sub_row(memory_db)) == ("old", YOUTUBE_ERROR_CHANNEL_NOT_FOUND)


# ---------- error genérico no relacionado ----------


def test_unrelated_exception_still_falls_into_generic_handler(
    memory_db, monkeypatch, caplog
):
    asyncio.run(_add_sub(memory_db))
    channel = FakeTextChannel(send_messages=True)

    async def boom(youtube_channel_id):
        raise RuntimeError("RSS caído")

    monkeypatch.setattr(youtube_mod, "get_latest_video", boom)
    cog = YouTube(SimpleNamespace(get_channel=lambda cid: channel))

    with caplog.at_level(logging.ERROR, logger="cogs.youtube"):
        _run(cog)

    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 1
    assert channel.sent == []
    # No es un problema de canal/permiso: last_error no se toca por esto.
    assert asyncio.run(_sub_row(memory_db)) == ("old", None)
