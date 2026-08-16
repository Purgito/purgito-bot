"""Tests para el sistema de Actualizaciones del Bot (relay y API)."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

import config
import db
import webapi
from cogs.updates import Updates, check_updates_channel_permissions

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


def _fake_channel(
    channel_id,
    guild_id,
    *,
    view_channel=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    send_messages_in_threads=True,
    manage_threads=False,
    is_thread=False,
    locked=False,
    name="anuncios",
):
    channel = MagicMock(spec=discord.Thread if is_thread else discord.TextChannel)
    channel.id = channel_id
    channel.name = name
    me = MagicMock()
    channel.guild = SimpleNamespace(id=guild_id, me=me, name=f"Guild {guild_id}")
    if is_thread:
        channel.parent = SimpleNamespace(id=999)
        channel.locked = locked
    else:
        channel.parent = None
    perms = MagicMock()
    perms.view_channel = view_channel
    perms.send_messages = send_messages
    perms.embed_links = embed_links
    perms.attach_files = attach_files
    perms.send_messages_in_threads = send_messages_in_threads
    perms.manage_threads = manage_threads
    channel.permissions_for.return_value = perms
    channel.send = AsyncMock()
    return channel


def _fake_guild(guild_id, channels: dict, name="Guild Test"):
    me = MagicMock()
    guild = SimpleNamespace(
        id=guild_id,
        name=name,
        me=me,
        get_channel=lambda cid: channels.get(cid),
        get_thread=lambda cid: channels.get(cid),
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


def test_non_existent_channel_skipped_and_cleaned_up(memory_db, caplog):
    """Canal eliminado de Discord se omite y se limpia automáticamente de la base de datos."""
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
    # La configuración inválida del guild 100 fue limpiada automáticamente
    assert asyncio.run(db.get_updates_channel(100)) is None
    # El guild 200 permanece configurado
    assert asyncio.run(db.get_updates_channel(200)) == 20


def test_guild_inaccessible_handled_gracefully(memory_db, caplog):
    """Si el bot fue expulsado o el guild no está en cache, no rompe el broadcast."""
    asyncio.run(db.set_updates_channel(100, 10))
    asyncio.run(db.set_updates_channel(200, 20))

    ch20 = _fake_channel(20, 200)
    guilds = {
        200: _fake_guild(200, {20: ch20}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
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
    """Si el bot no tiene permiso send_messages en el canal, se omite con warning estructurado."""
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
    assert any("Sin permisos suficientes" in r.message and "Send Messages" in r.message for r in caplog.records)


def test_missing_view_channel_permission_skipped(memory_db, caplog):
    """Si el bot no tiene permiso view_channel en el canal, se omite con warning estructurado."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100, view_channel=False)

    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    msg = _fake_message(content="Aviso")
    with caplog.at_level(logging.WARNING, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 0
    ch10.send.assert_not_awaited()
    assert any("Sin permisos suficientes" in r.message and "View Channel" in r.message for r in caplog.records)


def test_missing_embed_links_permission_sends_text_without_embeds(memory_db, caplog):
    """Si el bot no tiene permiso embed_links, envía el texto sin los embeds degradando limpiamente."""
    asyncio.run(db.set_updates_channel(100, 10))
    ch10 = _fake_channel(10, 100, embed_links=False)

    bot = MagicMock()
    bot.get_guild.return_value = _fake_guild(100, {10: ch10})
    cog = Updates(bot)

    embed = discord.Embed(title="Embed de anuncio", description="Detalles")
    msg = _fake_message(content="Texto del anuncio", embeds=[embed])
    with caplog.at_level(logging.INFO, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    ch10.send.assert_awaited_once()
    kw = ch10.send.call_args.kwargs
    assert kw["content"] == "Texto del anuncio"
    assert "embeds" not in kw or kw["embeds"] == []
    assert any("no tiene permiso Embed Links" in r.message for r in caplog.records)


def test_thread_permissions_and_locked_state(memory_db, caplog):
    """Validación de permisos específicos en hilos de Discord."""
    asyncio.run(db.set_updates_channel(100, 10))
    asyncio.run(db.set_updates_channel(200, 20))

    # Hilo sin send_messages_in_threads
    th10 = _fake_channel(10, 100, is_thread=True, send_messages_in_threads=False)
    # Hilo bloqueado sin manage_threads
    th20 = _fake_channel(20, 200, is_thread=True, locked=True, manage_threads=False)

    guilds = {
        100: _fake_guild(100, {10: th10}),
        200: _fake_guild(200, {20: th20}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    cog = Updates(bot)

    msg = _fake_message(content="Update en hilos")
    with caplog.at_level(logging.WARNING, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 0
    th10.send.assert_not_awaited()
    th20.send.assert_not_awaited()


# ── 4. Manejo de excepciones de Discord API ─────────────────────────────────


def test_discord_forbidden_handled_gracefully(memory_db, caplog):
    """discord.Forbidden durante el envío se registra sin cancelar otros servidores."""
    asyncio.run(db.set_updates_channel(100, 10))
    asyncio.run(db.set_updates_channel(200, 20))

    ch10 = _fake_channel(10, 100)
    ch10.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
    ch20 = _fake_channel(20, 200)

    guilds = {
        100: _fake_guild(100, {10: ch10}),
        200: _fake_guild(200, {20: ch20}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    cog = Updates(bot)

    msg = _fake_message(content="Aviso")
    with caplog.at_level(logging.ERROR, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    ch20.send.assert_awaited_once()
    assert any("Discord Forbidden (403)" in r.message for r in caplog.records)


def test_discord_not_found_cleans_db_configuration(memory_db, caplog):
    """discord.NotFound durante el envío limpia la configuración del canal en la base de datos."""
    asyncio.run(db.set_updates_channel(100, 10))
    asyncio.run(db.set_updates_channel(200, 20))

    ch10 = _fake_channel(10, 100)
    ch10.send.side_effect = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Channel")
    ch20 = _fake_channel(20, 200)

    guilds = {
        100: _fake_guild(100, {10: ch10}),
        200: _fake_guild(200, {20: ch20}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    cog = Updates(bot)

    msg = _fake_message(content="Aviso")
    with caplog.at_level(logging.WARNING, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    ch20.send.assert_awaited_once()
    assert asyncio.run(db.get_updates_channel(100)) is None
    assert asyncio.run(db.get_updates_channel(200)) == 20


def test_discord_rate_limited_handled_gracefully(memory_db, caplog):
    """discord.RateLimited se captura adecuadamente sin interrumpir otros servidores."""
    asyncio.run(db.set_updates_channel(100, 10))
    asyncio.run(db.set_updates_channel(200, 20))

    ch10 = _fake_channel(10, 100)
    ch10.send.side_effect = discord.RateLimited(1.5)
    ch20 = _fake_channel(20, 200)

    guilds = {
        100: _fake_guild(100, {10: ch10}),
        200: _fake_guild(200, {20: ch20}),
    }
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guilds.get(gid)
    cog = Updates(bot)

    msg = _fake_message(content="Aviso")
    with caplog.at_level(logging.WARNING, logger="cogs.updates"):
        sent = asyncio.run(cog.broadcast_update(msg))

    assert sent == 1
    ch20.send.assert_awaited_once()
    assert any("Rate limited por Discord" in r.message for r in caplog.records)


# ── 5. Formato de contenido y adjuntos ───────────────────────────────────────


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


# ── 6. Función check_updates_channel_permissions ─────────────────────────────


def test_check_updates_channel_permissions_all_cases():
    """Prueba exhaustiva de la función helper de verificación de permisos."""
    ch10 = _fake_channel(10, 100, name="anuncios")
    ch_no_send = _fake_channel(20, 100, send_messages=False, name="solo-lectura")
    ch_no_view = _fake_channel(30, 100, view_channel=False, name="oculto")
    ch_no_both = _fake_channel(40, 100, view_channel=False, send_messages=False, name="restringido")

    guild = _fake_guild(100, {10: ch10, 20: ch_no_send, 30: ch_no_view, 40: ch_no_both})

    # Caso 1: channel_id = None -> no_channel
    r_none = check_updates_channel_permissions(guild, None)
    assert r_none["status"] == "no_channel"
    assert r_none["can_publish"] is False

    # Caso 2: Canal válido -> healthy
    r_healthy = check_updates_channel_permissions(guild, 10)
    assert r_healthy["status"] == "healthy"
    assert r_healthy["can_publish"] is True
    assert r_healthy["channel_name"] == "anuncios"

    # Caso 3: Canal sin send_messages -> missing_permissions
    r_no_send = check_updates_channel_permissions(guild, 20)
    assert r_no_send["status"] == "missing_permissions"
    assert r_no_send["can_publish"] is False
    assert "send_messages" in r_no_send["missing_permissions"]
    assert "Enviar mensajes" in r_no_send["missing_permissions_labels"]

    # Caso 4: Canal sin view_channel -> missing_permissions
    r_no_view = check_updates_channel_permissions(guild, 30)
    assert r_no_view["status"] == "missing_permissions"
    assert r_no_view["can_publish"] is False
    assert "view_channel" in r_no_view["missing_permissions"]
    assert "Ver canal" in r_no_view["missing_permissions_labels"]

    # Caso 5: Canal sin view ni send -> ambos listados
    r_no_both = check_updates_channel_permissions(guild, 40)
    assert r_no_both["status"] == "missing_permissions"
    assert set(r_no_both["missing_permissions"]) == {"view_channel", "send_messages"}

    # Caso 6: Canal inexistente -> not_found
    r_not_found = check_updates_channel_permissions(guild, 999)
    assert r_not_found["status"] == "not_found"
    assert r_not_found["can_publish"] is False


# ── 7. Validación en endpoints de API (/settings/updates) ─────────────────────


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
    """PUT /settings/updates acepta canal válido y permite desvincular con null."""
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


def test_api_updates_put_rejects_missing_send_messages(memory_db, monkeypatch):
    """PUT /settings/updates rechaza canal donde Purgito no tiene permiso para enviar mensajes."""
    ch20 = _fake_channel(20, 100, send_messages=False, name="general")
    guild = _fake_guild(100, {20: ch20})
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: guild)

    req = FakeRequest({"channel_id": "20"}, guild_id="100")
    resp = asyncio.run(webapi._api_updates_put(req))
    assert resp.status == 400
    body = json.loads(resp.text)
    assert "Enviar mensajes" in body["error"]
    assert "send_messages" in body["missing_permissions"]
    # No se debe haber guardado en DB
    assert asyncio.run(db.get_updates_channel(100)) is None


def test_api_updates_put_rejects_missing_view_channel(memory_db, monkeypatch):
    """PUT /settings/updates rechaza canal donde Purgito no puede ver el canal."""
    ch30 = _fake_channel(30, 100, view_channel=False, name="privado")
    guild = _fake_guild(100, {30: ch30})
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: guild)

    req = FakeRequest({"channel_id": "30"}, guild_id="100")
    resp = asyncio.run(webapi._api_updates_put(req))
    assert resp.status == 400
    body = json.loads(resp.text)
    assert "Ver canal" in body["error"]
    assert "view_channel" in body["missing_permissions"]
    assert asyncio.run(db.get_updates_channel(100)) is None


def test_api_updates_put_rejects_missing_both_permissions(memory_db, monkeypatch):
    """PUT /settings/updates rechaza canal sin Ver canal ni Enviar mensajes detallando ambos."""
    ch40 = _fake_channel(40, 100, view_channel=False, send_messages=False, name="restringido")
    guild = _fake_guild(100, {40: ch40})
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: guild)

    req = FakeRequest({"channel_id": "40"}, guild_id="100")
    resp = asyncio.run(webapi._api_updates_put(req))
    assert resp.status == 400
    body = json.loads(resp.text)
    assert "Ver canal" in body["error"]
    assert "Enviar mensajes" in body["error"]
    assert set(body["missing_permissions"]) == {"view_channel", "send_messages"}
    assert asyncio.run(db.get_updates_channel(100)) is None


def test_api_updates_put_rejects_channel_from_other_guild(memory_db, monkeypatch):
    """PUT /settings/updates rechaza canal inexistente en el servidor."""
    ch10 = _fake_channel(10, 100)
    guild = _fake_guild(100, {10: ch10})
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: guild)

    req = FakeRequest({"channel_id": "999"}, guild_id="100")
    resp = asyncio.run(webapi._api_updates_put(req))
    assert resp.status == 400
    assert asyncio.run(db.get_updates_channel(100)) is None


def test_api_updates_get_returns_complete_status_payload(memory_db, monkeypatch):
    """GET /settings/updates devuelve el estado en tiempo real (healthy, missing_permissions, etc.)."""
    ch10 = _fake_channel(10, 100, name="anuncios")
    guild = _fake_guild(100, {10: ch10})
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: guild)

    # 1. Sin canal
    req = FakeRequest(guild_id="100")
    resp = asyncio.run(webapi._api_updates_get(req))
    body = json.loads(resp.text)
    assert body["status"] == "no_channel"
    assert body["channel_id"] is None
    assert body["can_publish"] is False

    # 2. Con canal healthy
    asyncio.run(db.set_updates_channel(100, 10))
    resp2 = asyncio.run(webapi._api_updates_get(req))
    body2 = json.loads(resp2.text)
    assert body2["status"] == "healthy"
    assert body2["channel_id"] == "10"
    assert body2["channel_name"] == "anuncios"
    assert body2["can_publish"] is True

    # 3. Permisos revocados posteriormente -> missing_permissions
    ch10.permissions_for.return_value.send_messages = False
    resp3 = asyncio.run(webapi._api_updates_get(req))
    body3 = json.loads(resp3.text)
    assert body3["status"] == "missing_permissions"
    assert body3["can_publish"] is False
    assert "send_messages" in body3["missing_permissions"]
    assert "Enviar mensajes" in body3["missing_permissions_labels"]

    # 4. Canal eliminado posteriormente -> not_found
    asyncio.run(db.set_updates_channel(100, 999))
    resp4 = asyncio.run(webapi._api_updates_get(req))
    body4 = json.loads(resp4.text)
    assert body4["status"] == "not_found"
    assert body4["can_publish"] is False

