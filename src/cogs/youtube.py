"""Notificaciones de YouTube: suscripciones por RSS y chequeo periódico."""

import asyncio
import logging
import re
from urllib.parse import quote

import discord
import feedparser
import requests
from discord.ext import commands, tasks

from db import (
    YOUTUBE_ERROR_CHANNEL_NOT_FOUND,
    YOUTUBE_ERROR_FEED_NOT_FOUND,
    YOUTUBE_ERROR_NO_PERMISSION,
    get_all_youtube_subs,
    set_youtube_sub_error,
    update_last_video_id,
)
from i18n import guild_locale, t

log = logging.getLogger(__name__)

# User-Agent de navegador para resolver @handles: YouTube responde con
# HTML/JSON completo con el channelId embebido, sin consumir cuota de la API.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


class YouTubeFeedNotFound(Exception):
    """El RSS del canal devolvió 404: canal borrado o channel_id inválido,
    a diferencia de un error transitorio (500, timeout) que sí se reintenta."""


async def _resolve_handle_to_channel_id(raw: str) -> str | None:
    """Resuelve un input arbitrario (ID crudo UC..., @handle o URL completa de
    YouTube) al channel_id canónico (UC... de 24 caracteres).

    Si el input ya tiene formato UC..., se devuelve directamente sin requests
    extra. Para @handles y URLs se descarga la página del canal en un hilo
    separado para extraer el channelId embebido.
    """
    s = (raw or "").strip()
    if not s:
        return None

    # 1. ID canónico directo: evita una petición innecesaria en el caso más común.
    if _CHANNEL_ID_RE.match(s):
        return s

    # 2. URL directa con /channel/UC...: extrae el ID sin necesidad de fetch.
    m_chan = re.search(r"[/?&]channel/(UC[\w-]{22})(?:[/?&]|$)", s)
    if m_chan:
        return m_chan.group(1)

    # 3. Construcción de URL destino según el formato del input.
    m_handle_url = re.search(r"youtube\.com/@([A-Za-z0-9_.-]+)", s)
    if m_handle_url:
        target_url = f"https://www.youtube.com/@{quote(m_handle_url.group(1), safe='')}"
    elif s.startswith("@"):
        handle = s[1:].split("/")[0].split("?")[0].strip()
        if not handle:
            return None
        target_url = f"https://www.youtube.com/@{quote(handle, safe='')}"
    elif re.search(r"youtube\.com/(?:c|user)/([A-Za-z0-9_.-]+)", s):
        m_custom = re.search(r"youtube\.com/((?:c|user)/[A-Za-z0-9_.-]+)", s)
        target_url = f"https://www.youtube.com/{m_custom.group(1)}"
    elif s.startswith("http://") or s.startswith("https://") or "youtube.com" in s:
        target_url = (
            s
            if (s.startswith("http://") or s.startswith("https://"))
            else f"https://{s}"
        )
    else:
        # Handle / nombre sin arroba (ej: "MrBeast")
        handle = s.split("/")[0].split("?")[0].strip()
        if not handle:
            return None
        target_url = f"https://www.youtube.com/@{quote(handle, safe='')}"

    def _fetch():
        resp = requests.get(target_url, headers=_BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.text

    try:
        html_text = await asyncio.to_thread(_fetch)
    except Exception as e:
        log.warning("No se pudo resolver canal YouTube %s: %s", raw, e)
        return None

    # YouTube incluye el channelId en el HTML inicial ("channelId":"UC...", meta tags, etc.).
    match = re.search(r'"channelId":"(UC[\w-]{22})"', html_text)
    if not match:
        match = re.search(r'itemprop="channelId"\s+content="(UC[\w-]{22})"', html_text)
    if not match:
        match = re.search(r'itemprop="identifier"\s+content="(UC[\w-]{22})"', html_text)
    if not match:
        match = re.search(
            r'href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html_text
        )
    if not match:
        match = re.search(r'"externalId":"(UC[\w-]{22})"', html_text)

    if match:
        return match.group(1)

    log.warning("No se encontró channelId en la página de YouTube para %s", raw)
    return None


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
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning(
                "Canal YouTube %s no encontrado, RSS devolvió 404", youtube_channel_id
            )
            raise YouTubeFeedNotFound(youtube_channel_id) from e
        log.exception("Error obteniendo RSS para canal YouTube %s", youtube_channel_id)
        return None
    except Exception:
        log.exception("Error obteniendo RSS para canal YouTube %s", youtube_channel_id)
        return None


async def resolve_youtube_channel(youtube_channel_id: str) -> dict | None:
    """Valida que el canal exista (el RSS responde) y devuelve su id canónico,
    nombre y último video, para dar de alta una suscripción nueva (dashboard web
    y /settings). None significa que el canal o RSS no resolvió -- canal
    inexistente o error de red -- y el alta debe rechazarse.

    Acepta IDs de canal crudos (UC...), @handles y URLs completas.

    A diferencia de get_latest_video, un canal real pero sin videos subidos
    todavía NO es un error acá: se puede dar de alta igual (con nombre
    genérico, que el caller decide) -- el chequeo periódico ya sabe esperar
    sin video. get_latest_video sigue devolviendo None en ese caso porque ahí
    "sin entradas" significa correctamente "nada nuevo que avisar".
    """
    channel_id = await _resolve_handle_to_channel_id(youtube_channel_id)
    if not channel_id:
        return None

    try:
        feed = await _fetch_feed(channel_id)
    except Exception:
        log.exception("Error resolviendo canal YouTube %s", channel_id)
        return None
    if not feed.entries:
        log.info(
            "Canal YouTube %s parece válido pero todavía no tiene videos",
            channel_id,
        )
        return {"id": channel_id, "name": None, "latest_video_id": None}
    entry = feed.entries[0]
    video_id = getattr(entry, "yt_videoid", None) or entry.get("id", "").split(":")[-1]
    return {
        "id": channel_id,
        "name": entry.get("author") or None,
        "latest_video_id": video_id or None,
    }


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

                if sub["last_error"] in (
                    YOUTUBE_ERROR_CHANNEL_NOT_FOUND,
                    YOUTUBE_ERROR_NO_PERMISSION,
                ):
                    await set_youtube_sub_error(
                        sub["guild_id"], sub["youtube_channel_id"], None
                    )
                    log.info(
                        "Suscripción YouTube %s (guild %s) recuperada, reanuda avisos",
                        sub["youtube_channel_id"],
                        sub["guild_id"],
                    )

                try:
                    video = await get_latest_video(sub["youtube_channel_id"])
                except YouTubeFeedNotFound:
                    if sub["last_error"] != YOUTUBE_ERROR_FEED_NOT_FOUND:
                        log.warning(
                            "Suscripción YouTube %s (guild %s) no puede avisar: %s",
                            sub["youtube_channel_id"],
                            sub["guild_id"],
                            YOUTUBE_ERROR_FEED_NOT_FOUND,
                        )
                        await set_youtube_sub_error(
                            sub["guild_id"],
                            sub["youtube_channel_id"],
                            YOUTUBE_ERROR_FEED_NOT_FOUND,
                        )
                    return

                if sub["last_error"] == YOUTUBE_ERROR_FEED_NOT_FOUND:
                    await set_youtube_sub_error(
                        sub["guild_id"], sub["youtube_channel_id"], None
                    )
                    log.info(
                        "Suscripción YouTube %s (guild %s) recuperada, reanuda avisos",
                        sub["youtube_channel_id"],
                        sub["guild_id"],
                    )

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
