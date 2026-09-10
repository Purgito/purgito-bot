"""Comando "dl": descarga un video de Instagram y lo sube al mismo canal.

Se invoca con cualquiera de los dos prefijos que resuelve bot.py:get_prefix
-- el símbolo (custom por guild, default "!") o la palabra fija ("purgito
dl <link>"). Solo Instagram por ahora: YouTube bloquea activamente la
descarga por fuera del navegador (throttling, a veces pide cookies de
sesión) y queda deliberadamente afuera -- ver discusión en el PR.

Nada de SSRF nuevo acá pese a que yt-dlp termina haciendo requests de red a
partir de un link que manda el usuario: a diferencia de r2.py (que sí
resuelve y filtra IPs porque acepta CUALQUIER URL de imagen), acá el host
tiene que ser literalmente instagram.com/instagr.am antes de llamar a
yt-dlp -- no hay forma de apuntarlo a una IP interna.
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

_INSTAGRAM_HOSTS = {"instagram.com", "instagr.am"}
_URL_RE = re.compile(r"https?://\S+")
_DL_COOLDOWN_SECONDS = 20


class DownloadFailed(Exception):
    """El link es válido pero yt-dlp no pudo bajar el video (privado, borrado,
    o Instagram cambió algo del lado de ellos)."""


class DownloadTooLarge(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


def _is_instagram_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return host in _INSTAGRAM_HOSTS or any(
        host.endswith(f".{allowed}") for allowed in _INSTAGRAM_HOSTS
    )


def _download_video(url: str, max_bytes: int) -> str:
    """Bloqueante -- se corre en un thread aparte. Devuelve la ruta del
    archivo descargado; el caller es responsable de borrar el directorio
    temporal entero (no solo el archivo) cuando termine."""
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
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if "max-filesize" in str(e).lower():
            raise DownloadTooLarge(max_bytes) from e
        raise DownloadFailed(str(e)) from e
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise DownloadFailed(str(e)) from e

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise DownloadFailed("archivo vacío o no generado")

    if os.path.getsize(path) > max_bytes:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise DownloadTooLarge(max_bytes)

    return path


class Download(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="dl")
    @commands.cooldown(1, _DL_COOLDOWN_SECONDS, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=False)
    async def dl(self, ctx: commands.Context, *, url: str | None = None):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        match = _URL_RE.search(url or "")
        if not match:
            await ctx.reply(t("download.dl.missing_url", locale))
            return
        link = match.group(0)
        if not _is_instagram_url(link):
            await ctx.reply(t("download.dl.only_instagram", locale))
            return

        max_bytes = MAX_DL_VIDEO_BYTES
        if ctx.guild is not None:
            max_bytes = min(max_bytes, ctx.guild.filesize_limit)

        tmp_dir = None
        async with ctx.typing():
            try:
                path = await asyncio.to_thread(_download_video, link, max_bytes)
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
