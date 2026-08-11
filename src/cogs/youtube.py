"""Notificaciones de YouTube: suscripciones por RSS y chequeo periódico."""

import asyncio
import logging
from urllib.parse import quote

import discord
import feedparser
import requests
from discord.ext import commands, tasks

from db import (
    YOUTUBE_ERROR_CHANNEL_NOT_FOUND,
    YOUTUBE_ERROR_NO_PERMISSION,
    get_all_youtube_subs,
    set_youtube_sub_error,
    update_last_video_id,
)
from i18n import guild_locale, t

log = logging.getLogger(__name__)


async def _fetch_feed(youtube_channel_id: str):
    url = (
        "https://www.youtube.com/feeds/videos.xml"
        f"?channel_id={quote(youtube_channel_id, safe='')}"
    )

    # Se descarga con timeout explícito: feedparser.parse(url) usa urllib sin
    # timeout y puede colgar el thread (y con él, el loop de chequeo).
    def _fetch():
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return feedparser.parse(resp.content)

    return await asyncio.to_thread(_fetch)


async def get_latest_video(youtube_channel_id: str) -> dict | None:
    try:
        feed = await _fetch_feed(youtube_channel_id)
        if not feed.entries:
            return None
        entry = feed.entries[0]
        video_id = (
            getattr(entry, "yt_videoid", None) or entry.get("id", "").split(":")[-1]
        )
        if not video_id:
            return None
        return {
            "id": video_id,
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "author": entry.get("author", ""),
        }
    except Exception:
        log.exception("Error obteniendo RSS para canal YouTube %s", youtube_channel_id)
        return None


async def resolve_youtube_channel(youtube_channel_id: str) -> dict | None:
    """Valida que el canal exista (el RSS responde) y devuelve su nombre y
    último video, para dar de alta una suscripción nueva (dashboard web y
    /settings). None significa que el RSS no resolvió -- canal inexistente o
    error de red -- y el alta debe rechazarse.

    A diferencia de get_latest_video, un canal real pero sin videos subidos
    todavía NO es un error acá: se puede dar de alta igual (con nombre
    genérico, que el caller decide) -- el chequeo periódico ya sabe esperar
    sin video. get_latest_video sigue devolviendo None en ese caso porque ahí
    "sin entradas" significa correctamente "nada nuevo que avisar".
    """
    try:
        feed = await _fetch_feed(youtube_channel_id)
    except Exception:
        log.exception("Error resolviendo canal YouTube %s", youtube_channel_id)
        return None
    if not feed.entries:
        log.info(
            "Canal YouTube %s parece válido pero todavía no tiene videos",
            youtube_channel_id,
        )
        return {"name": None, "latest_video_id": None}
    entry = feed.entries[0]
    video_id = getattr(entry, "yt_videoid", None) or entry.get("id", "").split(":")[-1]
    return {"name": entry.get("author") or None, "latest_video_id": video_id or None}


class YouTube(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.check_youtube.start()

    async def cog_unload(self) -> None:
        self.check_youtube.cancel()

    @tasks.loop(minutes=15)
    async def check_youtube(self):
        subs = await get_all_youtube_subs()

        async def _check_one(sub: dict) -> None:
            try:
                channel = self.bot.get_channel(sub["discord_channel_id"])
                if channel is None:
                    error = YOUTUBE_ERROR_CHANNEL_NOT_FOUND
                elif (
                    not isinstance(channel, discord.TextChannel)
                    or not channel.permissions_for(channel.guild.me).send_messages
                ):
                    error = YOUTUBE_ERROR_NO_PERMISSION
                else:
                    error = None

                if error:
                    # Se avisa (log + DB) una sola vez por cada vez que se rompe,
                    # no en cada corrida del loop mientras siga rota.
                    if sub["last_error"] != error:
                        log.warning(
                            "Suscripción YouTube %s (guild %s) no puede avisar: %s",
                            sub["youtube_channel_id"],
                            sub["guild_id"],
                            error,
                        )
                        await set_youtube_sub_error(
                            sub["guild_id"], sub["youtube_channel_id"], error
                        )
                    return

                if sub["last_error"]:
                    await set_youtube_sub_error(
                        sub["guild_id"], sub["youtube_channel_id"], None
                    )
                    log.info(
                        "Suscripción YouTube %s (guild %s) recuperada, reanuda avisos",
                        sub["youtube_channel_id"],
                        sub["guild_id"],
                    )

                video = await get_latest_video(sub["youtube_channel_id"])
                if video is None:
                    return
                if video["id"] != sub["last_video_id"]:
                    role_id = sub.get("mention_role_id")
                    mention = f"<@&{role_id}> " if role_id else ""
                    locale = await guild_locale(sub["guild_id"])
                    await channel.send(
                        mention
                        + t(
                            "youtube.new_video",
                            locale,
                            author=video["author"],
                            title=video["title"],
                            url=video["url"],
                        ),
                        # El título y el autor los escribe quien sube el video,
                        # no el servidor: un video titulado "@everyone ..." hacía
                        # que el bot pinguee a todo el servidor con SUS permisos.
                        # Se permite únicamente el rol que el admin configuró
                        # como aviso; todo lo demás que venga en el texto del
                        # feed queda inerte.
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False,
                            users=False,
                            roles=[discord.Object(id=role_id)] if role_id else False,
                        ),
                    )
                    await update_last_video_id(
                        sub["guild_id"], sub["youtube_channel_id"], video["id"]
                    )
            except Exception:
                log.exception(
                    "Error procesando suscripción YouTube %s", sub["youtube_channel_id"]
                )

        await asyncio.gather(*(_check_one(sub) for sub in subs))

    @check_youtube.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(YouTube(bot))
