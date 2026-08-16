"""Tests para el sistema de Actualizaciones del Bot (relay y API)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

import config
import db
import webapi
from cogs.updates import Updates

_OFFICIAL_CHANNEL_ID = config.OFFICIAL_UPDATES_CHANNEL_ID


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


def _fake_channel(channel_id, guild_id, *, send_messages=True, embed_links=True, attach_files=True):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    me = MagicMock()
    channel.guild = SimpleNamespace(id=guild_id, me=me)
    perms = MagicMock()
    perms.send_messages = send_messages
    perms.embed_links = embed_links
    perms.attach_files = attach_files
    channel.permissions_for.return_value = perms
    channel.send = AsyncMock()
    return channel


def _fake_guild(guild_id, channels: dict):
    guild = SimpleNamespace(
        id=guild_id,
        me=MagicMock(),
        get_channel=lambda cid: channels.get(cid),
    )
    return guild


def _fake_message(
    *,
    channel_id=_OFFICIAL_CHANNEL_ID,
    author_bot=False,
    content="Nueva actualización de Purgito v2.0",
    embeds=None,
    attachments=None,
):
    msg = MagicMock(spec=discord.Message)
    msg.channel = SimpleNamespace(id=channel_id)
    msg.author = SimpleNamespace(bot=author_bot, id=123)
    msg.content = content
    msg.embeds = embeds or []
    msg.attachments = attachments or []
    return msg


# ── 1. Filtrado de canal, bots y contenido ───────────────────────────────────


def test_message_outside_official_channel_ignored(memory_db):
    """Mensajes en canales que no sean el oficial de updates se ignoran por completo."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100)
    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    msg = _fake_message(channel_id=999999999)
    asyncio.run(cog.on_message(msg))

    ch10.send.assert_not_awaited()


def test_bot_message_ignored_to_prevent_loops(memory_db):
    """Mensajes de bots (incluyendo Purgito o webhooks) se ignoran para evitar bucles."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100)
    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    msg = _fake_message(author_bot=True)
    asyncio.run(cog.on_message(msg))

    ch10.send.assert_not_awaited()


def test_empty_message_ignored(memory_db):
    """Mensaje sin texto, embeds ni adjuntos se ignora."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100)
    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    msg = _fake_message(content="", embeds=[], attachments=[])
    asyncio.run(cog.on_message(msg))

    ch10.send.assert_not_awaited()


# ── 2. Relay y suscripción por servidor ──────────────────────────────────────


def test_guild_without_updates_channel_receives_nothing(memory_db):
    """Guilds con updates_channel_id = NULL no reciben nada."""
    # Guild 100 configurado, Guild 200 sin configurar
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100)
    ch20 = _fake_channel(20, 200)

    guilds = {
        100: _fake_guild(100, {10: ch10}),
        200: _fake_guild(200, {20: ch20}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    cog = Updates(bot)

    msg = _fake_message(content="Actualización importante")
    asyncio.run(cog.on_message(msg))

    ch10.send.assert_awaited_once()
    ch20.send.assert_not_awaited()


def test_multiple_guilds_all_receive_update(memory_db):
    """Varios servidores con canal configurado reciben la actualización."""
    asyncio.run(db.set_updates_channel(100, 10))
    asyncio.run(db.set_updates_channel(200, 20))
    asyncio.run(db.set_updates_channel(300, 30))

    ch10 = _fake_channel(10, 100)
    ch20 = _fake_channel(20, 200)
    ch30 = _fake_channel(30, 300)

    guilds = {
        100: _fake_guild(100, {10: ch10}),
        200: _fake_guild(200, {20: ch20}),
        300: _fake_guild(300, {30: ch30}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    cog = Updates(bot)

    msg = _fake_message(content="Lanzamiento de características nuevas")
    sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 3
    ch10.send.assert_awaited_once()
    ch20.send.assert_awaited_once()
    ch30.send.assert_awaited_once()
    assert ch10.send.call_args.kwargs["content"] == "Lanzamiento de características nuevas"


def test_failed_guild_does_not_break_other_guilds(memory_db, caplog):
    """Si el envío a Guild A lanza excepción, Guild B y Guild C reciben normalmente."""
    asyncio.run(db.set_updates_channel(100, 10))
    asyncio.run(db.set_updates_channel(200, 20))
    asyncio.run(db.set_updates_channel(300, 30))

    ch10 = _fake_channel(10, 100)
    ch10.send.side_effect = discord.HTTPException(SimpleNamespace(status=500, reason="Discord error"), "fallo")

    ch20 = _fake_channel(20, 200)
    ch30 = _fake_channel(30, 300)

    guilds = {
        100: _fake_guild(100, {10: ch10}),
        200: _fake_guild(200, {20: ch20}),
        300: _fake_guild(300, {30: ch30}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    cog = Updates(bot)

    msg = _fake_message(content="Noticia")
    with caplog.at_level(logging.ERROR, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    # Guild 100 falló, pero 200 y 300 se completaron exitosamente
    assert sent == 2
    ch20.send.assert_awaited_once()
    ch30.send.assert_awaited_once()


# ── 3. Validación de canales, permisos y aislamiento ─────────────────────────


def test_non_existent_channel_skipped_gracefully(memory_db, caplog):
    """Canal eliminado de Discord se omite sin romper el broadcast."""
    asyncio.run(db.set_updates_channel(100, 999))  # canal 999 no existe
    asyncio.run(db.set_updates_channel(200, 20))

    ch20 = _fake_channel(20, 200)
    guilds = {
        100: _fake_guild(100, {}),  # sin canales
        200: _fake_guild(200, {20: ch20}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    bot.get_channel.return_value = None
    cog = Updates(bot)

    msg = _fake_message(content="Hola")
    with caplog.at_level(logging.WARNING, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    ch20.send.assert_awaited_once()


def test_cross_guild_channel_leak_rejected(memory_db, caplog):
    """Aislamiento: si por inconsistencia el canal no pertenece al guild destino, se rechaza."""
    asyncio.run(db.set_updates_channel(100, 10))

    # Canal 10 pertenece a Guild 999, no a Guild 100
    ch10_wrong = _fake_channel(10, 999)
    bot = MagicMock()
    bot.get_guild.return_value = SimpleNamespace(id=100, me=MagicMock(), get_channel=lambda cid: ch10_wrong)
    cog = Updates(bot)

    msg = _fake_message(content="Anuncio confidencial")
    with caplog.at_level(logging.ERROR, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 0
    ch10_wrong.send.assert_not_awaited()
    assert any("Aislamiento de canal violado" in r.message for r in caplog.records)


def test_missing_send_messages_permission_skipped(memory_db, caplog):
    """Si el bot no tiene permiso send_messages en el canal, se omite con warning."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100, send_messages=False)

    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    msg = _fake_message(content="Aviso")
    with caplog.at_level(logging.WARNING, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 0
    ch10.send.assert_not_awaited()


def test_missing_embed_links_permission_sends_text_without_embeds(memory_db):
    """Si el bot no tiene permiso embed_links, envía el texto sin los embeds."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100, embed_links=False)

    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    embed = discord.Embed(title="Embed de anuncio", description="Detalles")
    msg = _fake_message(content="Texto del anuncio", embeds=[embed])
    sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    ch10.send.assert_awaited_once()
    kw = ch10.send.call_args.kwargs
    assert kw["content"] == "Texto del anuncio"
    assert "embeds" not in kw or kw["embeds"] == []


# ── 4. Formato de contenido y adjuntos ───────────────────────────────────────


def test_content_with_embeds_and_attachments(memory_db):
    """Reenvío con texto, embeds y archivos adjuntos."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100)

    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    embed = discord.Embed(title="Título", description="Desc")
    att = MagicMock(spec=discord.Attachment)
    att.size = 1024
    att.filename = "changelog.txt"
    att.read = AsyncMock(return_value=b"changelog data")

    msg = _fake_message(content="Notas de versión", embeds=[embed], attachments=[att])
    sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    ch10.send.assert_awaited_once()
    kw = ch10.send.call_args.kwargs
    assert kw["content"] == "Notas de versión"
    assert len(kw["embeds"]) == 1
    assert kw["embeds"][0].title == "Título"
    assert len(kw["files"]) == 1
    assert kw["files"][0].filename == "changelog.txt"


def test_long_message_chunked_properly(memory_db):
    """Mensajes largos (> 1900 caracteres) se fragmentan en varios envíos."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100)

    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    long_text = "A" * 3000
    msg = _fake_message(content=long_text)
    sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    assert ch10.send.await_count == 2


def test_multiple_consecutive_updates_work(memory_db):
    """Múltiples actualizaciones consecutivas se transmiten correctamente."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100)

    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    for i in range(3):
        msg = _fake_message(content=f"Update #{i}")
        asyncio.run(cog.broadcast_update(msg))

    assert ch10.send.await_count == 3


# ── 5. Validación en endpoint PUT /settings/updates ───────────────────────────


class FakeRequest:
    def __init__(self, body=None, guild_id="100"):
        self._body = body
        self.match_info = {"guild_id": guild_id}
        self.headers = {"Content-Type": "application/json"}
        self.remote = "1.2.3.4"

    async def json(self):
        return self._body


@pytest.fixture(autouse=True)
def sesion_api(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": "777", "username": "admin"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_rate_post", webapi.LRUDict(64))


def test_api_updates_put_accepts_valid_channel_and_null(memory_db, monkeypatch):
    ch10 = _fake_channel(10, 100)
    guild = _fake_guild(100, {10: ch10})
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: guild)

    # 1. Configurar canal válido 10
    req = FakeRequest({"channel_id": "10"}, guild_id="100")
    resp = asyncio.run(webapi._api_updates_put(req))
    assert resp.status == 200
    assert asyncio.run(db.get_updates_channel(100)) == 10

    # 2. Desvincular canal enviando null
    req_null = FakeRequest({"channel_id": None}, guild_id="100")
    resp_null = asyncio.run(webapi._api_updates_put(req_null))
    assert resp_null.status == 200
    assert asyncio.run(db.get_updates_channel(100)) is None


def test_api_updates_put_rejects_channel_from_other_guild(memory_db, monkeypatch):
    # En guild 100 solo existe el canal 10; canal 999 no existe aquí
    ch10 = _fake_channel(10, 100)
    guild = _fake_guild(100, {10: ch10})
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: guild)

    req = FakeRequest({"channel_id": "999"}, guild_id="100")
    resp = asyncio.run(webapi._api_updates_put(req))
    assert resp.status == 400
    assert asyncio.run(db.get_updates_channel(100)) is None
