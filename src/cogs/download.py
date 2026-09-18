"""Comando "dl": descarga un video de Instagram, TikTok, Twitter/X o
Facebook y lo sube al mismo canal.

Se invoca con cualquiera de los dos prefijos que resuelve bot.py:get_prefix
-- el símbolo (custom por guild, default "!") o la palabra fija ("purgito
dl <link>", sin importar mayúsculas/minúsculas: bot.py:get_prefix devuelve
el prefijo con el casing exacto que escribió el usuario). Si el comando se
invoca sin link propio pero respondiendo a un mensaje, usa el link de ese
mensaje (_reply_target_url) -- así alcanza con "purgito dl" en respuesta a
un mensaje que ya tiene el video. YouTube queda deliberadamente afuera:
bloquea activamente la descarga por fuera del navegador (throttling, a
veces pide cookies de sesión) -- ver discusión en el PR.

Nada de SSRF nuevo acá pese a que yt-dlp termina haciendo requests de red a
partir de un link que manda el usuario: a diferencia de r2.py (que sí
resuelve y filtra IPs porque acepta CUALQUIER URL de imagen), acá el host
tiene que estar en _ALLOWED_HOSTS antes de llamar a yt-dlp -- no hay forma
de apuntarlo a una IP interna. Por eso "t.co" NO está en la lista aunque
sea de Twitter: es un acortador de propósito general (cualquiera puede
tuitear un link a cualquier sitio), así que permitirlo reabriría el mismo
hueco que esta allowlist existe para cerrar.
"""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from urllib.parse import urlparse

import discord
import yt_dlp
from discord.ext import commands

from config import env_int
from i18n import guild_locale, t

log = logging.getLogger(__name__)

# Tope duro además de guild.filesize_limit (que ya depende del nivel de boost
# del server): sin esto, un guild boosteado nivel 3 (100MB) podría hacer que
# el proceso descargue videos larguísimos innecesariamente.
MAX_DL_VIDEO_BYTES = env_int("MAX_DL_VIDEO_BYTES", 100 * 1024 * 1024)

# Dominios base: el chequeo de host también acepta cualquier subdominio
# (".instagram.com", "vm.tiktok.com", etc.) -- ver _is_supported_url.
# fb.watch es el dominio corto que usa Facebook específicamente para
# compartir videos (no es un acortador genérico como t.co: no shortea
# links a otros sitios), así que no tiene el mismo problema que descartó
# a t.co.
_ALLOWED_HOSTS = {
    "instagram.com",
    "instagr.am",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "fb.watch",
}
_URL_RE = re.compile(r"https?://\S+")
_DL_COOLDOWN_SECONDS = 20


class DownloadFailed(Exception):
    """El link es válido pero yt-dlp no pudo bajar el video (privado, borrado,
    o el sitio cambió algo de su lado)."""


class DownloadTooLarge(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


def _is_supported_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return host in _ALLOWED_HOSTS or any(
        host.endswith(f".{allowed}") for allowed in _ALLOWED_HOSTS
    )


_TWITTER_HOSTS = {"twitter.com", "x.com"}


def _is_twitter_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _TWITTER_HOSTS or any(host.endswith(f".{h}") for h in _TWITTER_HOSTS)


def _attempt_download(
    url: str, max_bytes: int, extra_opts: dict | None = None
) -> tuple[str, dict]:
    """Un intento de descarga. Devuelve (ruta del archivo, info de yt-dlp);
    si falla, borra su propio tmp_dir antes de propagar la excepción (el
    caller solo tiene que limpiar tmp_dir en el camino feliz)."""
    tmp_dir = tempfile.mkdtemp(prefix="purgito_dl_")
    ydl_opts = {
        "outtmpl": os.path.join(tmp_dir, "%(id)s.%(ext)s"),
        # "best" a secas: un solo archivo progresivo, sin mergear video+audio
        # por separado -- así no hace falta ffmpeg instalado en el server.
        "format": "best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": max_bytes,
        "socket_timeout": 20,
        "retries": 2,
        **(extra_opts or {}),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info), info
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def _download_video(url: str, max_bytes: int) -> tuple[str, bool]:
    """Bloqueante -- se corre en un thread aparte. Devuelve (ruta del
    archivo descargado, si el sitio de origen lo marca como contenido
    sensible/+18); el caller es responsable de borrar el directorio temporal
    entero (no solo el archivo) cuando termine."""
    try:
        path, info = _attempt_download(url, max_bytes)
    except yt_dlp.utils.DownloadError as e:
        if "max-filesize" in str(e).lower():
            raise DownloadTooLarge(max_bytes) from e
        if not _is_twitter_url(url):
            raise DownloadFailed(str(e)) from e
        # Sin cookies de una cuenta logueada, yt-dlp pega por default a la
        # API graphql con un guest token -- y esa API le exige login a
        # cualquier tuit que X marque como sensible ("NSFW tweet requires
        # authentication"), aunque el tuit sea público y cualquiera pueda
        # verlo en el navegador. El endpoint de syndication
        # (cdn.syndication.twimg.com) es el que usa el embed/widget público
        # de Twitter: no tiene ese gate ni pide cuenta, a costa de menos
        # metadata. Reintentamos ahí antes de darlo por perdido -- el tuit
        # sigue viniendo marcado sensible en el info que devuelve (ver
        # age_limit abajo), simplemente ya no hace falta login para leerlo.
        try:
            path, info = _attempt_download(
                url,
                max_bytes,
                {"extractor_args": {"twitter": {"api": ["syndication"]}}},
            )
        except yt_dlp.utils.DownloadError as e2:
            if "max-filesize" in str(e2).lower():
                raise DownloadTooLarge(max_bytes) from e2
            raise DownloadFailed(str(e2)) from e2
        except Exception as e2:
            raise DownloadFailed(str(e2)) from e2
    except Exception as e:
        raise DownloadFailed(str(e)) from e

    tmp_dir = os.path.dirname(path)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise DownloadFailed("archivo vacío o no generado")

    if os.path.getsize(path) > max_bytes:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise DownloadTooLarge(max_bytes)

    # age_limit es el campo estándar de yt-dlp para esto (no es cosa de
    # Twitter/X: Instagram y TikTok también lo completan cuando corresponde).
    is_sensitive = bool(info.get("age_limit"))
    return path, is_sensitive


async def _reply_target_url(ctx: commands.Context) -> str | None:
    """Si el comando se invocó sin link propio pero respondiendo a un
    mensaje, busca un link ahí -- así "purgito dl" alcanza como respuesta a
    un mensaje con un video, sin tener que repetir la URL. `resolved` ya
    viene poblado en la mayoría de los casos (Discord lo manda junto con el
    mensaje de reply), pero si no -- mensaje viejo fuera de caché -- se
    busca con un fetch aparte.

    Además del texto plano, revisa los embeds del mensaje: bots que postean
    un preview del video (ej. NotSoBot) suelen mandarlo como embed puro, sin
    el link en el texto -- Embed.url es la página de origen en ese caso."""
    reference = ctx.message.reference
    if reference is None:
        return None
    resolved = reference.resolved
    if isinstance(resolved, discord.DeletedReferencedMessage):
        return None
    if resolved is None:
        if reference.message_id is None:
            return None
        try:
            resolved = await ctx.channel.fetch_message(reference.message_id)
        except discord.HTTPException:
            return None
    match = _URL_RE.search(resolved.content or "")
    if match:
        return match.group(0)
    for embed in resolved.embeds:
        if embed.url:
            return embed.url
    return None


class Download(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="dl")
    @commands.cooldown(1, _DL_COOLDOWN_SECONDS, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=False)
    async def dl(self, ctx: commands.Context, *, url: str | None = None):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        match = _URL_RE.search(url or "")
        link = match.group(0) if match else await _reply_target_url(ctx)
        if not link:
            await ctx.reply(t("download.dl.missing_url", locale))
            return
        if not _is_supported_url(link):
            await ctx.reply(t("download.dl.unsupported_site", locale))
            return

        max_bytes = MAX_DL_VIDEO_BYTES
        if ctx.guild is not None:
            max_bytes = min(max_bytes, ctx.guild.filesize_limit)

        tmp_dir = None
        async with ctx.typing():
            try:
                path, is_sensitive = await asyncio.to_thread(
                    _download_video, link, max_bytes
                )
                tmp_dir = os.path.dirname(path)
            except DownloadTooLarge as e:
                await ctx.reply(
                    t("download.dl.too_large", locale, mb=e.max_bytes // (1024 * 1024))
                )
                return
            except DownloadFailed:
                await ctx.reply(t("download.dl.failed", locale))
                return

        try:
            channel_is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
            if is_sensitive and not channel_is_nsfw:
                await ctx.reply(t("download.dl.nsfw_channel_required", locale))
                return
            await ctx.reply(file=discord.File(path))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @dl.error
    async def dl_error(self, ctx: commands.Context, error: Exception):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(
                t("general.error.cooldown", locale, seconds=round(error.retry_after))
            )
            return
        if isinstance(error, commands.MaxConcurrencyReached):
            await ctx.reply(t("download.dl.busy", locale))
            return
        log.error("Error en !dl", exc_info=error)
        await ctx.reply(t("general.error.generic", locale))


async def setup(bot: commands.Bot):
    await bot.add_cog(Download(bot))
