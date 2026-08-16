"""Relay de actualizaciones oficiales del bot hacia servidores suscritos."""

import asyncio
import io
import logging

import discord
from discord.ext import commands

import config
from db import list_all_updates_channels
from utils import chunk_message

log = logging.getLogger(__name__)

# No permitir menciones automáticas masivas a @everyone / @here / roles al retransmitir
_SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=False)

# Límite por archivo adjunto individual a descargar en memoria
_MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024  # 8 MB

# Concurrencia máxima para el broadcast a los guilds destino
_BROADCAST_CONCURRENCY = 10


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

        # Pre-descargar adjuntos en memoria una sola vez para no descargar por cada guild
        attachments_data: list[tuple[str, bytes]] = []
        for att in message.attachments:
            if getattr(att, "size", 0) <= _MAX_ATTACHMENT_BYTES:
                try:
                    data = await att.read()
                    attachments_data.append((att.filename, data))
                except Exception:
                    log.warning(
                        "No se pudo descargar el adjunto %s para replicar actualización",
                        getattr(att, "filename", "desconocido"),
                    )

        embeds = [
            discord.Embed.from_dict(e.to_dict()) for e in message.embeds[:10]
        ]
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
                try:
                    guild = self.bot.get_guild(guild_id)
                    if guild is None:
                        log.debug(
                            "Guild %s no disponible en cache del bot para updates",
                            guild_id,
                        )
                        return

                    channel = guild.get_channel(channel_id)
                    if channel is None:
                        # Comprobar si el canal existe en el bot pero pertenece a otro servidor
                        other_channel = self.bot.get_channel(channel_id)
                        if (
                            other_channel is not None
                            and getattr(other_channel, "guild", None)
                            and other_channel.guild.id != guild_id
                        ):
                            log.error(
                                "Aislamiento de canal violado: canal %s pertenece a guild %s, no a %s",
                                channel_id,
                                other_channel.guild.id,
                                guild_id,
                            )
                            return
                        log.warning(
                            "Canal de actualizaciones %s no encontrado en guild %s",
                            channel_id,
                            guild_id,
                        )
                        return

                    # Doble chequeo de aislamiento: el canal DEBE pertenecer al guild destino
                    if not hasattr(channel, "guild") or channel.guild.id != guild_id:
                        log.error(
                            "Aislamiento de canal violado: canal %s pertenece a guild %s, no a %s",
                            channel_id,
                            getattr(channel.guild, "id", None),
                            guild_id,
                        )
                        return

                    perms = channel.permissions_for(guild.me)
                    if not perms.send_messages:
                        log.warning(
                            "Sin permiso send_messages en canal de actualizaciones %s (guild %s)",
                            channel_id,
                            guild_id,
                        )
                        return

                    send_embeds = embeds if perms.embed_links else []
                    files = (
                        [
                            discord.File(io.BytesIO(data), filename=name)
                            for name, data in attachments_data
                        ]
                        if perms.attach_files
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
                except Exception:
                    log.exception(
                        "Error enviando actualización a guild %s (canal %s)",
                        guild_id,
                        channel_id,
                    )

        await asyncio.gather(*[_send_to_guild(d) for d in destinations])
        log.info(
            "Actualización oficial replicada a %d de %d servidores configurados",
            sent_count,
            len(destinations),
        )
        return sent_count


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Updates(bot))
