"""Notificaciones de feeds RSS/Atom genéricos: suscripciones y chequeo periódico."""

import asyncio
import logging

import discord
import feedparser
import requests
from discord.ext import commands, tasks

from db import (
    RSS_ERROR_CHANNEL_NOT_FOUND,
    RSS_ERROR_FEED_NOT_FOUND,
    RSS_ERROR_NO_PERMISSION,
    get_all_rss_subs,
    set_rss_sub_error,
    update_last_item_id,
)
from i18n import guild_locale, t

log = logging.getLogger(__name__)

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


class RSSFeedNotFound(Exception):
    """El feed devolvió 404 o fue borrado, a diferencia de un error transitorio
    (500, timeout) que sí se reintenta."""


async def _fetch_feed(url: str):
    # Se descarga con timeout explícito: feedparser.parse(url) usa urllib sin
    # timeout y puede colgar el thread (y con él, el loop de chequeo).
    def _fetch():
        resp = requests.get(url, headers=_FETCH_HEADERS, timeout=10)
        resp.raise_for_status()
        return feedparser.parse(resp.content)

    return await asyncio.to_thread(_fetch)


async def get_latest_rss_item(url: str) -> dict | None:
    try:
        feed = await _fetch_feed(url)
        if not feed.entries:
            return None
        entry = feed.entries[0]
        item_id = entry.get("id") or entry.get("link") or entry.get("title")
        if not item_id:
            return None
        feed_title = getattr(feed.feed, "title", None) or url
        return {
            "id": item_id,
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "feed_title": feed_title,
        }
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("Feed RSS %s no encontrado, devolvió 404", url)
            raise RSSFeedNotFound(url) from e
        log.exception("Error obteniendo feed RSS %s", url)
        return None
    except Exception:
        log.exception("Error obteniendo feed RSS %s", url)
        return None


async def resolve_rss_feed(url: str) -> dict | None:
    """Valida que la URL responda y sea un feed RSS/Atom estructurado, devolviendo
    su título y último item publicado para dar de alta una suscripción.

    Rechaza URLs inválidas o páginas HTML genéricas que no constituyan un feed
    (feedparser marca bozo y no encuentra entradas ni metadatos de canal).
    """
    url = (url or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return None

    try:
        feed = await _fetch_feed(url)
    except Exception:
        log.exception("Error resolviendo feed RSS %s", url)
        return None

    # Si feedparser no detecta versión de feed válida ni entradas, descartamos
    # para no aceptar páginas HTML comunes que no sean feeds reales.
    version = getattr(feed, "version", "")
    if not version and not feed.entries:
        log.warning("URL %s no parece ser un feed RSS/Atom válido", url)
        return None

    feed_meta = getattr(feed, "feed", None)
    feed_title = (
        getattr(feed_meta, "title", None) or getattr(feed_meta, "subtitle", None) or url
    )
    latest_item_id = None
    if feed.entries:
        entry = feed.entries[0]
        latest_item_id = entry.get("id") or entry.get("link") or entry.get("title")

    return {
        "title": feed_title,
        "latest_item_id": latest_item_id,
    }


class RSS(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.check_rss.start()

    async def cog_unload(self) -> None:
        self.check_rss.cancel()

    @tasks.loop(minutes=15)
    async def check_rss(self):
        subs = await get_all_rss_subs()

        async def _check_one(sub: dict) -> None:
            try:
                channel = self.bot.get_channel(sub["discord_channel_id"])
                if channel is None:
                    error = RSS_ERROR_CHANNEL_NOT_FOUND
                elif (
                    not isinstance(channel, discord.TextChannel)
                    or not channel.permissions_for(channel.guild.me).send_messages
                ):
                    error = RSS_ERROR_NO_PERMISSION
                else:
                    error = None

                if error:
                    if sub["last_error"] != error:
                        log.warning(
                            "Suscripción RSS %s (guild %s) no puede avisar: %s",
                            sub["feed_url"],
                            sub["guild_id"],
                            error,
                        )
                        await set_rss_sub_error(sub["guild_id"], sub["feed_url"], error)
                    return

                if sub["last_error"] in (
                    RSS_ERROR_CHANNEL_NOT_FOUND,
                    RSS_ERROR_NO_PERMISSION,
                ):
                    await set_rss_sub_error(sub["guild_id"], sub["feed_url"], None)
                    log.info(
                        "Suscripción RSS %s (guild %s) recuperada, reanuda avisos",
                        sub["feed_url"],
                        sub["guild_id"],
                    )

                try:
                    item = await get_latest_rss_item(sub["feed_url"])
                except RSSFeedNotFound:
                    if sub["last_error"] != RSS_ERROR_FEED_NOT_FOUND:
                        log.warning(
                            "Suscripción RSS %s (guild %s) no puede avisar: %s",
                            sub["feed_url"],
                            sub["guild_id"],
                            RSS_ERROR_FEED_NOT_FOUND,
                        )
                        await set_rss_sub_error(
                            sub["guild_id"],
                            sub["feed_url"],
                            RSS_ERROR_FEED_NOT_FOUND,
                        )
                    return

                if sub["last_error"] == RSS_ERROR_FEED_NOT_FOUND:
                    await set_rss_sub_error(sub["guild_id"], sub["feed_url"], None)
                    log.info(
                        "Suscripción RSS %s (guild %s) recuperada, reanuda avisos",
                        sub["feed_url"],
                        sub["guild_id"],
                    )

                if item is None:
                    return
                if item["id"] != sub["last_item_id"]:
                    role_id = sub.get("mention_role_id")
                    mention = f"<@&{role_id}> " if role_id else ""
                    locale = await guild_locale(sub["guild_id"])
                    feed_title = sub.get("feed_title") or item.get("feed_title") or ""
                    await channel.send(
                        mention
                        + t(
                            "rss.new_item",
                            locale,
                            feed_title=feed_title,
                            title=item["title"],
                            url=item["url"],
                        ),
                        # El título y resumen del post provienen del feed externo.
                        # Se restringen las menciones para evitar que mencione @everyone.
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False,
                            users=False,
                            roles=[discord.Object(id=role_id)] if role_id else False,
                        ),
                    )
                    await update_last_item_id(
                        sub["guild_id"], sub["feed_url"], item["id"]
                    )
            except Exception:
                log.exception("Error procesando suscripción RSS %s", sub["feed_url"])

        await asyncio.gather(*(_check_one(sub) for sub in subs))

    @check_rss.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RSS(bot))
