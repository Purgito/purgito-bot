"""Auditoría sección 9, ronda 3, punto 3: check_announcements resolvía el
canal con bot.get_channel(channel_id) -- una búsqueda GLOBAL, ya que los ids
de canal son snowflakes únicos en todo Discord, no por guild. Sin comparar
channel.guild.id contra el guild_id de la fila, un futuro bug en cualquier
vía de escritura que guardara una fila con esos dos campos desalineados
mandaría el contenido de un guild al canal de otro, en silencio.

Hoy no hay ruta de entrada real: el único camino de escritura
(_api_embeds_schedule, vía _embed_target_channel) valida el canal contra el
guild ANTES de guardar. Este test fija el comportamiento defensivo agregado
como red de seguridad, no como corrección de un bug explotable hoy.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

import db
from cogs.anuncios import Anuncios


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


def _fake_channel(guild_id):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 10
    channel.guild = SimpleNamespace(id=guild_id, me=MagicMock())
    perms = MagicMock()
    perms.send_messages = True
    perms.embed_links = True
    channel.permissions_for.return_value = perms
    channel.send = AsyncMock()
    return channel


def _run(channel):
    bot = MagicMock()
    bot.get_channel.return_value = channel
    cog = Anuncios(bot)
    asyncio.run(cog.check_announcements.coro(cog))


def test_canal_de_otro_guild_no_recibe_el_anuncio(memory_db, caplog):
    """La fila dice guild_id=1, pero get_channel(10) devuelve un canal cuyo
    guild real es 999 -- exactamente lo que pasaría si una fila quedara
    desalineada por cualquier motivo."""
    asyncio.run(
        db.add_scheduled_announcement(
            1, 10, "contenido del guild 1", "interval", 1, interval_minutes=30
        )
    )
    channel = _fake_channel(guild_id=999)

    with caplog.at_level(logging.ERROR, logger="cogs.anuncios"):
        _run(channel)

    channel.send.assert_not_awaited()
    assert any("no pertenece al guild_id" in r.message for r in caplog.records)


def test_canal_del_guild_correcto_recibe_el_anuncio(memory_db):
    """El caso normal -- el que pasa hoy siempre -- no se rompe."""
    asyncio.run(
        db.add_scheduled_announcement(
            1, 10, "contenido del guild 1", "interval", 1, interval_minutes=30
        )
    )
    channel = _fake_channel(guild_id=1)

    _run(channel)

    channel.send.assert_awaited_once_with("contenido del guild 1")
