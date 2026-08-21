"""Relay de actualizaciones oficiales del bot hacia servidores suscritos."""

import asyncio
import io
import logging
from typing import Any

import discord
from discord.ext import commands

import config
from db import list_all_updates_channels, set_updates_channel
from utils import chunk_message

log = logging.getLogger(__name__)

# No permitir menciones automáticas masivas a @everyone / @here / roles al retransmitir
_SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=False)

# Límite por archivo adjunto individual a descargar en memoria
_MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024  # 8 MB

# Concurrencia máxima para el broadcast a los guilds destino
_BROADCAST_CONCURRENCY = 10


def check_updates_channel_permissions(
    guild: Any,
    channel_id: int | None,
) -> dict:
    """Valida exhaustivamente el estado y los permisos efectivos de Discord
    para el canal de actualizaciones del bot en un guild.

    Retorna un diccionario con:
    - 'channel_id': str | None
    - 'channel_name': str | None
    - 'status': 'no_channel' | 'not_found' | 'invalid_type' | 'missing_permissions' | 'healthy'
    - 'can_publish': bool
    - 'missing_permissions': list[str]
    - 'missing_permissions_labels': list[str]
    - 'warnings': list[str]
    - 'details': str
    """
    if channel_id is None:
        return {
            "channel_id": None,
            "channel_name": None,
            "status": "no_channel",
            "can_publish": False,
            "missing_permissions": [],
            "missing_permissions_labels": [],
            "warnings": [],
            "details": "No hay ningún canal configurado. Las novedades del bot no se publicarán en este servidor.",
        }

    str_cid = str(channel_id)
    if guild is None:
        return {
            "channel_id": str_cid,
            "channel_name": None,
            "status": "not_found",
            "can_publish": False,
            "missing_permissions": [],
            "missing_permissions_labels": [],
            "warnings": [],
            "details": "El servidor de Discord no está disponible o Purgito no es miembro del mismo.",
        }

    channel = guild.get_channel(channel_id)
    if channel is None and hasattr(guild, "get_thread"):
        channel = guild.get_thread(channel_id)

    if channel is None:
        return {
            "channel_id": str_cid,
            "channel_name": None,
            "status": "not_found",
            "can_publish": False,
            "missing_permissions": [],
            "missing_permissions_labels": [],
            "warnings": [],
            "details": f"El canal configurado (ID: {str_cid}) no existe en este servidor o fue eliminado.",
        }

    ch_name = getattr(channel, "name", str_cid)

    # El canal debe soportar envío de mensajes y cálculo de permisos
    if not hasattr(channel, "send") or not hasattr(channel, "permissions_for"):
        return {
            "channel_id": str_cid,
            "channel_name": ch_name,
            "status": "invalid_type",
            "can_publish": False,
            "missing_permissions": [],
            "missing_permissions_labels": [],
            "warnings": [],
            "details": f"El canal #{ch_name} no es de tipo texto ni admite el envío de mensajes.",
        }

    bot_member = getattr(guild, "me", None)
    if bot_member is None:
        return {
            "channel_id": str_cid,
            "channel_name": ch_name,
            "status": "missing_permissions",
            "can_publish": False,
            "missing_permissions": ["view_channel", "send_messages"],
            "missing_permissions_labels": ["Ver canal", "Enviar mensajes"],
            "warnings": [],
            "details": "No se pudieron verificar los permisos del bot en el servidor.",
        }

    perms = channel.permissions_for(bot_member)
    missing = []
    missing_labels = []

    if not getattr(perms, "view_channel", False):
        missing.append("view_channel")
        missing_labels.append("Ver canal")

    if not getattr(perms, "send_messages", False):
        missing.append("send_messages")
        missing_labels.append("Enviar mensajes")

    # Si es un hilo, validar permisos adicionales de hilos
    if getattr(channel, "parent", None) is not None:
        if not getattr(perms, "send_messages_in_threads", True):
            missing.append("send_messages_in_threads")
            missing_labels.append("Enviar mensajes en hilos")
        if getattr(channel, "locked", False) and not getattr(
            perms, "manage_threads", False
        ):
            missing.append("manage_threads")
            missing_labels.append("Gestionar hilos (el hilo está bloqueado)")

    if missing:
        return {
            "channel_id": str_cid,
            "channel_name": ch_name,
            "status": "missing_permissions",
            "can_publish": False,
            "missing_permissions": missing,
            "missing_permissions_labels": missing_labels,
            "warnings": [],
            "details": f"Purgito no puede publicar en #{ch_name}. Faltan permisos: {', '.join(missing_labels)}.",
        }

    warnings = []
    if not getattr(perms, "embed_links", False):
        warnings.append("Sin permiso para incrustar enlaces (embeds)")
    if not getattr(perms, "attach_files", False):
        warnings.append("Sin permiso para adjuntar archivos")

    return {
        "channel_id": str_cid,
        "channel_name": ch_name,
        "status": "healthy",
        "can_publish": True,
        "missing_permissions": [],
        "missing_permissions_labels": [],
        "warnings": warnings,
        "details": f"Purgito tiene permisos suficientes para publicar novedades en #{ch_name}.",
    }


class Updates(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # 1. Escuchar únicamente mensajes en el canal oficial de actualizaciones
        if message.channel.id != config.OFFICIAL_UPDATES_CHANNEL_ID:
            return

        # 2. Ignorar mensajes enviados por bots (incluyendo Purgito) para evitar bucles
        if message.author.bot:
            return

        # 3. Ignorar mensajes vacíos (sin texto, embeds ni adjuntos)
        if not message.content and not message.embeds and not message.attachments:
            return

        await self.broadcast_update(message)

    async def broadcast_update(self, message: discord.Message) -> int:
        """Reenvía el contenido del anuncio a todos los servidores con canal de updates."""
        destinations = await list_all_updates_channels()
        if not destinations:
            return 0

        log.info(
            "[Updates Relay] Iniciando broadcast de actualización (msg_id=%s) a %d servidores configurados",
            getattr(message, "id", "desconocido"),
            len(destinations),
        )

        # Pre-descargar adjuntos en memoria una sola vez para no descargar por cada guild
        attachments_data: list[tuple[str, bytes]] = []
        for att in message.attachments:
            if getattr(att, "size", 0) <= _MAX_ATTACHMENT_BYTES:
                try:
                    data = await att.read()
                    attachments_data.append((att.filename, data))
                except Exception:
                    log.warning(
                        "[Updates Relay] No se pudo descargar el adjunto %s para replicar actualización",
                        getattr(att, "filename", "desconocido"),
                    )

        embeds = [discord.Embed.from_dict(e.to_dict()) for e in message.embeds[:10]]
        content = message.content or ""
        chunks = chunk_message(content) if content else []

        sem = asyncio.Semaphore(_BROADCAST_CONCURRENCY)
        sent_count = 0
        lock = asyncio.Lock()

        async def _send_to_guild(dest: dict) -> None:
            nonlocal sent_count
            guild_id = dest.get("guild_id")
            channel_id = dest.get("channel_id")
            if not guild_id or not channel_id:
                return

            async with sem:
                guild = None
                channel = None
                try:
                    guild = self.bot.get_guild(guild_id)
                    if guild is None:
                        log.warning(
                            "[Updates Relay] Guild %s no disponible en cache del bot para updates; omitiendo",
                            guild_id,
                        )
                        return

                    guild_name = getattr(guild, "name", "Desconocido")
                    channel = guild.get_channel(channel_id)
                    if channel is None and hasattr(guild, "get_thread"):
                        channel = guild.get_thread(channel_id)

                    if channel is None:
                        # Comprobar si el canal existe en el bot pero pertenece a otro servidor
                        other_channel = self.bot.get_channel(channel_id)
                        if (
                            other_channel is not None
                            and getattr(other_channel, "guild", None)
                            and other_channel.guild.id != guild_id
                        ):
                            log.error(
                                "[Updates Relay] Aislamiento de canal violado: canal %s pertenece a guild %s, no a %s",
                                channel_id,
                                other_channel.guild.id,
                                guild_id,
                            )
                            return
                        log.warning(
                            "[Updates Relay] Canal de actualizaciones %s no encontrado en guild %s (%s). Limpiando configuración inválida.",
                            channel_id,
                            guild_id,
                            guild_name,
                        )
                        try:
                            await set_updates_channel(guild_id, None)
                        except Exception:
                            log.exception(
                                "[Updates Relay] Error al limpiar canal de updates inválido en guild %s",
                                guild_id,
                            )
                        return

                    # Doble chequeo de aislamiento: el canal DEBE pertenecer al guild destino
                    if not hasattr(channel, "guild") or channel.guild.id != guild_id:
                        log.error(
                            "[Updates Relay] Aislamiento de canal violado: canal %s pertenece a guild %s, no a %s",
                            channel_id,
                            getattr(channel.guild, "id", None),
                            guild_id,
                        )
                        return

                    channel_name = getattr(channel, "name", str(channel_id))
                    bot_member = getattr(guild, "me", None)
                    if bot_member is None:
                        log.warning(
                            "[Updates Relay] No se pudo obtener el miembro bot en guild %s (%s) para canal #%s (%s)",
                            guild_id,
                            guild_name,
                            channel_name,
                            channel_id,
                        )
                        return

                    perms = channel.permissions_for(bot_member)
                    missing = []
                    if not getattr(perms, "view_channel", False):
                        missing.append("View Channel")
                    if not getattr(perms, "send_messages", False):
                        missing.append("Send Messages")

                    if getattr(channel, "parent", None) is not None:
                        if not getattr(perms, "send_messages_in_threads", True):
                            missing.append("Send Messages in Threads")
                        if getattr(channel, "locked", False) and not getattr(
                            perms, "manage_threads", False
                        ):
                            missing.append("Manage Threads (hilo bloqueado)")

                    if missing:
                        log.warning(
                            "[Updates Relay] Sin permisos suficientes en canal #%s (%s) de guild %s (%s). Faltan: %s. Omitiendo envío.",
                            channel_name,
                            channel_id,
                            guild_id,
                            guild_name,
                            ", ".join(missing),
                        )
                        return

                    can_embed = bool(getattr(perms, "embed_links", False))
                    can_attach = bool(getattr(perms, "attach_files", False))

                    if embeds and not can_embed:
                        log.info(
                            "[Updates Relay] Guild %s (%s) canal #%s no tiene permiso Embed Links; enviando solo texto",
                            guild_id,
                            guild_name,
                            channel_name,
                        )
                    if attachments_data and not can_attach:
                        log.info(
                            "[Updates Relay] Guild %s (%s) canal #%s no tiene permiso Attach Files; omitiendo adjuntos",
                            guild_id,
                            guild_name,
                            channel_name,
                        )

                    send_embeds = embeds if can_embed else []
                    files = (
                        [
                            discord.File(io.BytesIO(data), filename=name)
                            for name, data in attachments_data
                        ]
                        if can_attach
                        else []
                    )

                    if not chunks:
                        kw = {"allowed_mentions": _SAFE_MENTIONS}
                        if send_embeds:
                            kw["embeds"] = send_embeds
                        if files:
                            kw["files"] = files
                        if len(kw) > 1:
                            await channel.send(**kw)
                            async with lock:
                                sent_count += 1
                            log.info(
                                "[Updates Relay] Actualización entregada exitosamente a guild %s (%s) en canal #%s (%s)",
                                guild_id,
                                guild_name,
                                channel_name,
                                channel_id,
                            )
                    else:
                        for i, chunk in enumerate(chunks):
                            is_last = i == len(chunks) - 1
                            kw = {"content": chunk, "allowed_mentions": _SAFE_MENTIONS}
                            if is_last:
                                if send_embeds:
                                    kw["embeds"] = send_embeds
                                if files:
                                    kw["files"] = files
                            await channel.send(**kw)
                        async with lock:
                            sent_count += 1
                        log.info(
                            "[Updates Relay] Actualización (%d fragmentos) entregada exitosamente a guild %s (%s) en canal #%s (%s)",
                            len(chunks),
                            guild_id,
                            guild_name,
                            channel_name,
                            channel_id,
                        )
                except discord.Forbidden as err:
                    log.error(
                        "[Updates Relay] Discord Forbidden (403) enviando a guild %s (%s) en canal #%s (%s): %s",
                        guild_id,
                        getattr(guild, "name", "Desconocido")
                        if guild
                        else "Desconocido",
                        getattr(channel, "name", "desconocido")
                        if channel
                        else "desconocido",
                        channel_id,
                        err,
                    )
                except discord.NotFound:
                    log.warning(
                        "[Updates Relay] Discord NotFound (404) enviando a guild %s (%s) en canal %s: canal eliminado. Limpiando configuración.",
                        guild_id,
                        getattr(guild, "name", "Desconocido")
                        if guild
                        else "Desconocido",
                        channel_id,
                    )
                    try:
                        await set_updates_channel(guild_id, None)
                    except Exception:
                        pass
                except discord.RateLimited as err:
                    log.warning(
                        "[Updates Relay] Rate limited por Discord enviando a guild %s en canal %s: retry_after=%.2fs",
                        guild_id,
                        channel_id,
                        getattr(err, "retry_after", 0.0),
                    )
                except discord.HTTPException as err:
                    status_code = getattr(err, "status", None)
                    if status_code == 429:
                        log.warning(
                            "[Updates Relay] Rate limit (429) de Discord enviando a guild %s en canal %s: %s",
                            guild_id,
                            channel_id,
                            err,
                        )
                    elif status_code == 404:
                        log.warning(
                            "[Updates Relay] Discord NotFound (404) al enviar a guild %s en canal %s. Limpiando configuración.",
                            guild_id,
                            channel_id,
                        )
                        try:
                            await set_updates_channel(guild_id, None)
                        except Exception:
                            pass
                    elif status_code == 403:
                        log.error(
                            "[Updates Relay] Discord Forbidden (403) al enviar a guild %s en canal %s: %s",
                            guild_id,
                            channel_id,
                            err,
                        )
                    else:
                        log.error(
                            "[Updates Relay] Error HTTP (%s) de Discord enviando a guild %s en canal %s: %s",
                            status_code,
                            guild_id,
                            channel_id,
                            err,
                        )
                except Exception as err:
                    log.exception(
                        "[Updates Relay] Excepción no controlada enviando a guild %s (%s) en canal %s: %s",
                        guild_id,
                        getattr(guild, "name", "Desconocido")
                        if guild
                        else "Desconocido",
                        channel_id,
                        err,
                    )

        await asyncio.gather(
            *[_send_to_guild(d) for d in destinations], return_exceptions=True
        )
        log.info(
            "[Updates Relay] Broadcast completado: %d de %d servidores recibieron la actualización exitosamente",
            sent_count,
            len(destinations),
        )
        return sent_count


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Updates(bot))
