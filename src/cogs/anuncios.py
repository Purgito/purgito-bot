"""Anuncios programados: mensajes de texto que el bot envía solo a un canal,
por intervalo o a una hora fija (ver /settings > Anuncios). Distinto de
frases_especiales (esas se mezclan al azar en el chat Markov)."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import json

import discord
from discord.ext import commands, tasks

from db import (
    add_pending_deletion,
    extract_send_options,
    get_due_pending_deletions,
    get_due_scheduled_announcements,
    normalize_embeds_json,
    remove_pending_deletion,
    update_announcement_last_sent,
)
from layout_v2 import build_layout_view
from message_options import send_kwargs, wants_custom_identity
from webhook_identity import send_via_webhook

log = logging.getLogger(__name__)


class Anuncios(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.check_announcements.start()
        self.sweep_pending_deletions.start()

    async def cog_unload(self) -> None:
        self.check_announcements.cancel()
        self.sweep_pending_deletions.cancel()

    @tasks.loop(minutes=1)
    async def check_announcements(self):
        due = await get_due_scheduled_announcements()

        async def _send_one(item: dict) -> None:
            try:
                channel = self.bot.get_channel(item["channel_id"])
                if not isinstance(channel, discord.TextChannel):
                    return
                # get_channel es una búsqueda GLOBAL (los ids de canal son
                # snowflakes únicos en todo Discord, no por guild): si algún
                # día otra vía de escritura guarda una fila con guild_id y
                # channel_id de servidores distintos -- hoy no la hay, la
                # única (_api_embeds_schedule) valida el canal contra el guild
                # antes de guardar, ver _embed_target_channel --, esto evita
                # mandar el contenido de un guild al canal de otro.
                if channel.guild.id != item["guild_id"]:
                    log.error(
                        "Anuncio %s: channel_id %s no pertenece al guild_id %s de la fila, se descarta",
                        item["id"],
                        item["channel_id"],
                        item["guild_id"],
                    )
                    return
                perms = channel.permissions_for(channel.guild.me)
                if not perms.send_messages:
                    return
                # delete_after= es el camino rápido (asyncio.sleep interno de
                # discord.py, vive en memoria); add_pending_deletion de abajo
                # es la red de seguridad que sobrevive a un restart del bot.
                # Webhook.send() (identidad personalizada) no tiene ese kwarg
                # -- para esos envíos el borrado depende solo de la red de
                # seguridad, hasta 30s más tarde (ver sweep_pending_deletions).
                delete_after = item.get("delete_after_seconds")
                delete_kwarg = {"delete_after": delete_after} if delete_after else {}
                if item.get("embed_json") and item.get("content_mode") == "layout_v2":
                    # Layout Components V2 armado en el editor del panel.
                    if not perms.embed_links:
                        return
                    view = build_layout_view(json.loads(item["embed_json"]))
                    options = extract_send_options(item["embed_json"])
                    extra = send_kwargs(options)
                    if wants_custom_identity(options):
                        msg = await send_via_webhook(
                            self.bot,
                            item["guild_id"],
                            channel,
                            username=options.get("username", ""),
                            avatar_url=options.get("avatar_url", ""),
                            view=view,
                            **extra,
                        )
                    else:
                        msg = await channel.send(view=view, **delete_kwarg, **extra)
                elif item.get("embed_json"):
                    # Embeds clásicos. El JSON es siempre una lista (Discord
                    # admite hasta 10); normalize_embeds_json envuelve el formato
                    # viejo de un solo dict, así que este branch no las distingue.
                    if not perms.embed_links:
                        return
                    embeds = [
                        discord.Embed.from_dict(e)
                        for e in normalize_embeds_json(item["embed_json"])
                    ]
                    options = extract_send_options(item["embed_json"])
                    extra = send_kwargs(options)
                    if wants_custom_identity(options):
                        msg = await send_via_webhook(
                            self.bot,
                            item["guild_id"],
                            channel,
                            username=options.get("username", ""),
                            avatar_url=options.get("avatar_url", ""),
                            embeds=embeds,
                            **extra,
                        )
                    else:
                        msg = await channel.send(embeds=embeds, **delete_kwarg, **extra)
                else:
                    msg = await channel.send(item["message"], **delete_kwarg)
            except Exception:
                log.exception("Error enviando anuncio programado %s", item["id"])
                return

            # A partir de acá el mensaje YA salió a Discord. Si algo de esto
            # falla, la fila sigue "due" (get_due_scheduled_announcements no
            # se enteró) y la próxima corrida, en 1 minuto, la va a reenviar
            # -- un duplicado visible en el canal. No hay forma barata de
            # hacer esto atómico con el envío (son dos sistemas distintos),
            # así que al menos queda un rastro explícito con el id del
            # mensaje YA enviado, para poder borrarlo a mano si hace falta.
            try:
                if delete_after:
                    delete_at = datetime.now(timezone.utc) + timedelta(
                        seconds=delete_after
                    )
                    await add_pending_deletion(channel.id, msg.id, delete_at)
                await update_announcement_last_sent(item["id"])
            except Exception:
                log.error(
                    "Anuncio %s SE ENVIÓ (mensaje %s en canal %s) pero no se pudo "
                    "marcar como enviado -- probablemente se reenvíe en la próxima "
                    "corrida (1 min)",
                    item["id"],
                    msg.id,
                    item["channel_id"],
                    exc_info=True,
                )

        await asyncio.gather(*(_send_one(item) for item in due))

    @check_announcements.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def sweep_pending_deletions(self):
        due = await get_due_pending_deletions()

        async def _delete_one(item: dict) -> None:
            try:
                channel = self.bot.get_channel(item["channel_id"])
                if channel is not None:
                    msg = await channel.fetch_message(item["message_id"])
                    await msg.delete()
            except discord.NotFound:
                pass  # ya se borró por el camino rápido, o un mod lo borró antes — está bien
            except discord.Forbidden:
                log.warning(
                    "Sin permiso para borrar mensaje %s en canal %s",
                    item["message_id"],
                    item["channel_id"],
                )
            except Exception:
                log.exception("Error en sweep de borrado pendiente %s", item["id"])
                return  # no se borra la fila, se reintenta en el próximo sweep
            await remove_pending_deletion(item["id"])

        await asyncio.gather(*(_delete_one(item) for item in due))

    @sweep_pending_deletions.before_loop
    async def _wait_ready_sweep(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Anuncios(bot))
