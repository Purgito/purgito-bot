"""Filtros de imagen tipo NotSoBot (Fases 1, 2 y 4): comandos con prefijo
que transforman la imagen/GIF/video adjunto al mensaje, el del mensaje
respondido, o (solo para imagen) el avatar de quien invoca -- mismo
mecanismo de "adjunto propio -> reply" que ya usa cogs/download.py para
"purgito dl". "!gif" prueba, en orden: adjunto propio o del mensaje
respondido (extensión o content-type de video), video EMBEBIDO en el
propio mensaje o en el respondido (Embed.video -- bots como NotSoBot
postean su resultado así, no como adjunto; sirve tanto si ese video quedó
alojado en Discord como si Discord solo lo está proxeando desde el host
del otro bot, ver proxy_url en cogs/download.py:_embed_video_url); si no
hay ningún video, una imagen estática por las mismas vías (Embed.image en
vez de Embed.video) se empaqueta como GIF de un solo frame sin pasar por
ffmpeg; y, por último, un link propio o del mensaje respondido igual que
"!dl" (mismo allowlist de hosts, mismo módulo)."""

import asyncio
import io
import logging
import os
import shutil
import time
from typing import Callable

import discord
from discord.ext import commands

import cogs.download as download_mod
import image_filters
import video_filters
from cogs.gifs import is_valid_gif_bytes
from config import IMAGEFX_MAX_BYTES, env_int
from i18n import guild_locale, t
from meme_generator import is_valid_image
from utils import LRUDict

log = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_GIF_EXTS = {".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm"}

# Tope del video FUENTE de "!gif", antes de convertirlo -- deliberadamente
# más chico que MAX_DL_VIDEO_BYTES (cogs/download.py): un gif es un clip
# corto, no tiene sentido aceptar un archivo enorme solo para truncarlo a
# GIF_MAX_DURATION_SECONDS después.
MAX_GIF_SOURCE_VIDEO_BYTES = env_int("MAX_GIF_SOURCE_VIDEO_BYTES", 25 * 1024 * 1024)
GIF_MAX_DURATION_SECONDS = 8

# Cooldown compartido por TODOS los filtros de imagen/GIF de este cog, no uno
# por comando: son ~30 comandos de costo parecido, así que un cooldown por
# nombre de comando (lo que da @commands.cooldown por default) se evade
# rotando entre ellos -- mismo problema que ya resolvió _check_meme_cooldown
# en cogs/memes.py para /momo vs. el trigger de texto.
_FX_COOLDOWN_SECONDS = 6
_fx_cooldowns: LRUDict = LRUDict(1024)

# "!gif" tiene su propio cooldown, más largo: a diferencia del resto (Pillow
# puro, milisegundos), acá hay un proceso de ffmpeg de verdad -- mismo orden
# de costo que "!dl" (yt-dlp), por eso el mismo valor que _DL_COOLDOWN_SECONDS.
_GIF_CONVERT_COOLDOWN_SECONDS = 20
_gif_convert_cooldowns: LRUDict = LRUDict(256)


class SourceTooLarge(Exception):
    """El adjunto/reply encontrado (imagen, GIF o video fuente de "!gif")
    supera el tope de tamaño correspondiente."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


def _check_fx_cooldown(user_id: int) -> int | None:
    now = time.monotonic()
    elapsed = now - _fx_cooldowns.get(user_id, 0.0)
    if elapsed < _FX_COOLDOWN_SECONDS:
        return int(_FX_COOLDOWN_SECONDS - elapsed) or 1
    _fx_cooldowns[user_id] = now
    return None


def _check_gif_convert_cooldown(user_id: int) -> int | None:
    now = time.monotonic()
    elapsed = now - _gif_convert_cooldowns.get(user_id, 0.0)
    if elapsed < _GIF_CONVERT_COOLDOWN_SECONDS:
        return int(_GIF_CONVERT_COOLDOWN_SECONDS - elapsed) or 1
    _gif_convert_cooldowns[user_id] = now
    return None


async def _find_attachment(
    ctx: commands.Context, exts: set[str], content_type_prefix: str | None = None
) -> discord.Attachment | None:
    """content_type_prefix es un fallback además de la extensión (no en su
    reemplazo) -- lo usa _resolve_video_bytes/_resolve_gif_source_image_bytes
    porque algunos clientes suben el archivo con una extensión que no está
    en el set (ej. .mkv), pero sí content_type="video/..." o "image/...",
    mismo patrón que ya usa cogs/gifs.py.save_gif_candidates para adjuntos
    GIF. getattr en vez de attachment.content_type directo: un
    discord.Attachment real siempre tiene el atributo (None si Discord no
    reportó uno), pero no vale la pena exigirlo de cualquier objeto que
    llegue acá -- mismo criterio que _embed_video_url/_embed_image_url en
    cogs/download.py."""

    def _matches(attachment: discord.Attachment) -> bool:
        if os.path.splitext(attachment.filename.lower())[1] in exts:
            return True
        content_type = getattr(attachment, "content_type", None)
        return bool(
            content_type_prefix
            and content_type
            and content_type.lower().startswith(content_type_prefix)
        )

    for attachment in ctx.message.attachments:
        if _matches(attachment):
            return attachment

    resolved = await download_mod._resolve_reference(ctx)
    if resolved is None:
        return None
    for attachment in resolved.attachments:
        if _matches(attachment):
            return attachment
    return None


async def _resolve_image_bytes(ctx: commands.Context) -> bytes:
    """Adjunto propio -> adjunto del mensaje respondido -> avatar de quien
    invoca. with_static_format fuerza un PNG estático incluso si el avatar
    es animado -- is_valid_image no acepta GIF (ver _ALLOWED_FORMATS en
    meme_generator.py)."""
    attachment = await _find_attachment(ctx, _IMAGE_EXTS)
    if attachment is not None:
        if attachment.size > IMAGEFX_MAX_BYTES:
            raise SourceTooLarge(IMAGEFX_MAX_BYTES)
        return await attachment.read()
    avatar = ctx.author.display_avatar.with_static_format("png")
    return await avatar.read()


async def _resolve_gif_bytes(ctx: commands.Context) -> bytes | None:
    """Adjunto propio -> adjunto del mensaje respondido. A diferencia de
    _resolve_image_bytes, sin fallback a avatar (no hay "avatar en GIF" que
    tenga sentido usar acá) -- None significa "no hay nada para editar"."""
    attachment = await _find_attachment(ctx, _GIF_EXTS)
    if attachment is None:
        return None
    if attachment.size > IMAGEFX_MAX_BYTES:
        raise SourceTooLarge(IMAGEFX_MAX_BYTES)
    return await attachment.read()


async def _resolve_video_bytes(ctx: commands.Context) -> bytes | None:
    """Fuente del video para "!gif": adjunto propio o del mensaje
    respondido primero (como _resolve_gif_bytes, pero también por
    content-type). Si no hay adjunto, prueba el video EMBEBIDO -- del
    propio mensaje primero (por si Discord ya desempaquetó un link que
    mandó el usuario junto con el comando) y del mensaje respondido después
    -- así alcanza con responder al resultado de otro bot (ej. NotSoBot)
    aunque lo haya mandado como embed y no como adjunto, sea que ese embed
    apunte a un adjunto propio de Discord o a un host de terceros (ver
    proxy_url en _embed_video_url). None si ninguna tiene nada; a partir de
    ahí gif_cmd todavía prueba una imagen y, después, un link de página
    antes de rendirse."""
    attachment = await _find_attachment(ctx, _VIDEO_EXTS, content_type_prefix="video/")
    if attachment is not None:
        if attachment.size > MAX_GIF_SOURCE_VIDEO_BYTES:
            raise SourceTooLarge(MAX_GIF_SOURCE_VIDEO_BYTES)
        return await attachment.read()

    video_url = download_mod._embed_video_url(ctx.message)
    if video_url is None:
        resolved = await download_mod._resolve_reference(ctx)
        if resolved is None:
            return None
        video_url = download_mod._embed_video_url(resolved)
        if video_url is None:
            return None
    return await download_mod._fetch_direct_media_bytes(
        video_url, MAX_GIF_SOURCE_VIDEO_BYTES
    )


async def _resolve_gif_source_image_bytes(ctx: commands.Context) -> bytes | None:
    """Fuente de imagen para "!gif" cuando no hay ningún video (ver
    _resolve_video_bytes): mismas tres vías -- adjunto propio, adjunto del
    mensaje respondido, o imagen EMBEBIDA del mensaje respondido
    (Embed.image, mismo caso que Embed.video pero para una imagen estática).
    Una imagen no necesita convertirse de verdad -- se empaqueta como GIF de
    un solo frame en image_filters.image_to_gif, sin pasar por ffmpeg."""
    attachment = await _find_attachment(ctx, _IMAGE_EXTS, content_type_prefix="image/")
    if attachment is not None:
        if attachment.size > IMAGEFX_MAX_BYTES:
            raise SourceTooLarge(IMAGEFX_MAX_BYTES)
        return await attachment.read()

    resolved = await download_mod._resolve_reference(ctx)
    if resolved is None:
        return None
    image_url = download_mod._embed_image_url(resolved)
    if image_url is None:
        return None
    return await download_mod._fetch_direct_media_bytes(image_url, IMAGEFX_MAX_BYTES)


class ImageFx(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _run_filter(
        self,
        ctx: commands.Context,
        fn: Callable[..., bytes],
        *args,
        filename: str = "purgito.png",
    ) -> None:
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        remaining = _check_fx_cooldown(ctx.author.id)
        if remaining is not None:
            await ctx.reply(t("general.error.cooldown", locale, seconds=remaining))
            return

        try:
            data = await _resolve_image_bytes(ctx)
        except SourceTooLarge as e:
            await ctx.reply(
                t("imagefx.too_large", locale, mb=e.max_bytes // (1024 * 1024))
            )
            return
        except discord.HTTPException:
            await ctx.reply(t("general.error.generic", locale))
            return

        if not is_valid_image(data):
            await ctx.reply(t("imagefx.invalid_image", locale))
            return

        try:
            result = await asyncio.to_thread(fn, data, *args)
        except Exception:
            log.exception("Error aplicando filtro de imagen (%s)", fn.__name__)
            await ctx.reply(t("general.error.generic", locale))
            return

        await ctx.reply(file=discord.File(io.BytesIO(result), filename=filename))

    async def _run_gif_filter(
        self, ctx: commands.Context, fn: Callable[..., bytes], *args
    ) -> None:
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        remaining = _check_fx_cooldown(ctx.author.id)
        if remaining is not None:
            await ctx.reply(t("general.error.cooldown", locale, seconds=remaining))
            return

        try:
            data = await _resolve_gif_bytes(ctx)
        except SourceTooLarge as e:
            await ctx.reply(
                t("imagefx.too_large", locale, mb=e.max_bytes // (1024 * 1024))
            )
            return
        except discord.HTTPException:
            await ctx.reply(t("general.error.generic", locale))
            return

        if data is None:
            await ctx.reply(t("imagefx.gif_missing", locale))
            return
        if not is_valid_gif_bytes(data):
            await ctx.reply(t("imagefx.invalid_gif", locale))
            return

        try:
            result = await asyncio.to_thread(fn, data, *args)
        except Exception:
            log.exception("Error aplicando filtro de GIF (%s)", fn.__name__)
            await ctx.reply(t("general.error.generic", locale))
            return

        await ctx.reply(file=discord.File(io.BytesIO(result), filename="purgito.gif"))

    @commands.command(name="caption")
    async def caption_cmd(self, ctx: commands.Context, *, texto: str | None = None):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if not texto:
            await ctx.reply(t("imagefx.caption.missing_text", locale))
            return
        await self._run_filter(ctx, image_filters.caption, texto)

    @commands.command(name="deepfry")
    async def deepfry_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.deepfry)

    @commands.command(name="wide")
    async def wide_cmd(self, ctx: commands.Context, factor: float = 2.0):
        await self._run_filter(ctx, image_filters.wide, factor)

    @commands.command(name="squish")
    async def squish_cmd(self, ctx: commands.Context, factor: float = 0.5):
        await self._run_filter(ctx, image_filters.squish, factor)

    @commands.command(name="invert")
    async def invert_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.invert)

    @commands.command(name="greyscale", aliases=["grayscale"])
    async def greyscale_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.greyscale)

    @commands.command(name="sepia")
    async def sepia_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.sepia)

    @commands.command(name="pixelate")
    async def pixelate_cmd(self, ctx: commands.Context, block_size: int = 12):
        await self._run_filter(ctx, image_filters.pixelate, block_size)

    @commands.command(name="rotate")
    async def rotate_cmd(self, ctx: commands.Context, degrees: int = 90):
        await self._run_filter(ctx, image_filters.rotate, degrees)

    @commands.command(name="flip")
    async def flip_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.flip)

    @commands.command(name="flop")
    async def flop_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.flop)

    @commands.command(name="circle")
    async def circle_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.circle)

    @commands.command(name="blur")
    async def blur_cmd(self, ctx: commands.Context, radius: int = 6):
        await self._run_filter(ctx, image_filters.blur, radius)

    @commands.command(name="sharpen")
    async def sharpen_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.sharpen)

    # ── Fase 2: overlays y efectos de un solo chiste ─────────────────────────

    @commands.command(name="triggered")
    async def triggered_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.triggered, filename="purgito.gif")

    @commands.command(name="wasted")
    async def wasted_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.wasted)

    @commands.command(name="trash")
    async def trash_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.trash)

    @commands.command(name="communism")
    async def communism_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.communism)

    @commands.command(name="gay")
    async def gay_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.gay)

    @commands.command(name="jail")
    async def jail_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.jail)

    @commands.command(name="wanted")
    async def wanted_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.wanted)

    @commands.command(name="rip")
    async def rip_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.rip)

    @commands.command(name="america")
    async def america_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.america)

    @commands.command(name="polaroid")
    async def polaroid_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.polaroid)

    @commands.command(name="poster")
    async def poster_cmd(self, ctx: commands.Context, bits: int = 2):
        await self._run_filter(ctx, image_filters.poster, bits)

    @commands.command(name="threshold")
    async def threshold_cmd(self, ctx: commands.Context, level: int = 128):
        await self._run_filter(ctx, image_filters.threshold, level)

    @commands.command(name="emboss")
    async def emboss_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.emboss)

    # ── Fase 4: video -> GIF y edición de un GIF existente ───────────────────

    @commands.command(name="gif")
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=False)
    async def gif_cmd(self, ctx: commands.Context, *, url: str | None = None):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        remaining = _check_gif_convert_cooldown(ctx.author.id)
        if remaining is not None:
            await ctx.reply(t("general.error.cooldown", locale, seconds=remaining))
            return

        try:
            data = await _resolve_video_bytes(ctx)
        except SourceTooLarge as e:
            await ctx.reply(
                t("imagefx.video_too_large", locale, mb=e.max_bytes // (1024 * 1024))
            )
            return
        except discord.HTTPException:
            await ctx.reply(t("general.error.generic", locale))
            return

        if data is None:
            # Sin ningún video (_resolve_video_bytes ya probó adjunto y
            # embed): una imagen estática alcanza igual -- se empaqueta como
            # GIF de un solo frame, sin pasar por ffmpeg ni por el resto de
            # este método. Mismas tres vías que el video, por eso mismas
            # excepciones; solo se intenta si no hubo ningún video, así que
            # sigue ganando el video cuando hay los dos.
            try:
                image_data = await _resolve_gif_source_image_bytes(ctx)
            except SourceTooLarge as e:
                await ctx.reply(
                    t("imagefx.too_large", locale, mb=e.max_bytes // (1024 * 1024))
                )
                return
            except discord.HTTPException:
                await ctx.reply(t("general.error.generic", locale))
                return

            if image_data is not None:
                if not is_valid_image(image_data):
                    await ctx.reply(t("imagefx.invalid_image", locale))
                    return
                try:
                    result = await asyncio.to_thread(
                        image_filters.image_to_gif, image_data
                    )
                except Exception:
                    log.exception("Error convirtiendo imagen a GIF en !gif")
                    await ctx.reply(t("general.error.generic", locale))
                    return
                await ctx.reply(
                    file=discord.File(io.BytesIO(result), filename="purgito.gif")
                )
                return

        tmp_dir = None
        try:
            async with ctx.typing():
                if data is None:
                    # Sin video (adjunto, embed o imagen -- las tres ya se
                    # probaron arriba, esta rama es solo si ninguna tuvo
                    # nada): mismo mecanismo que "!dl" -- link propio o del
                    # mensaje respondido, mismo allowlist de hosts
                    # (Instagram/TikTok/Twitter-X/Facebook) y las mismas
                    # protecciones de SSRF ya auditadas en cogs/download.py.
                    match = download_mod._URL_RE.search(url or "")
                    link = (
                        match.group(0)
                        if match
                        else await download_mod._reply_target_url(ctx)
                    )
                    if not link:
                        await ctx.reply(t("imagefx.video_missing", locale))
                        return
                    if not download_mod._is_supported_url(link):
                        await ctx.reply(t("download.dl.unsupported_site", locale))
                        return

                    try:
                        path, is_sensitive = await asyncio.to_thread(
                            download_mod._download_video,
                            link,
                            MAX_GIF_SOURCE_VIDEO_BYTES,
                        )
                    except download_mod.DownloadTooLarge as e:
                        await ctx.reply(
                            t(
                                "imagefx.video_too_large",
                                locale,
                                mb=e.max_bytes // (1024 * 1024),
                            )
                        )
                        return
                    except download_mod.DownloadFailed:
                        await ctx.reply(t("download.dl.failed", locale))
                        return

                    tmp_dir = os.path.dirname(path)
                    channel_is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
                    if is_sensitive and not channel_is_nsfw:
                        await ctx.reply(t("download.dl.nsfw_channel_required", locale))
                        return

                    with open(path, "rb") as f:
                        data = f.read()

                max_output = IMAGEFX_MAX_BYTES
                if ctx.guild is not None:
                    max_output = min(max_output, ctx.guild.filesize_limit)

                try:
                    result = await asyncio.to_thread(
                        video_filters.convert_video_to_gif,
                        data,
                        GIF_MAX_DURATION_SECONDS,
                        max_output,
                    )
                except video_filters.GifTooLarge as e:
                    await ctx.reply(
                        t(
                            "imagefx.gif_output_too_large",
                            locale,
                            mb=e.max_bytes // (1024 * 1024),
                        )
                    )
                    return
                except video_filters.VideoConversionFailed:
                    await ctx.reply(t("imagefx.video_conversion_failed", locale))
                    return

            await ctx.reply(
                file=discord.File(io.BytesIO(result), filename="purgito.gif")
            )
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    @gif_cmd.error
    async def gif_cmd_error(self, ctx: commands.Context, error: Exception):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if isinstance(error, commands.MaxConcurrencyReached):
            await ctx.reply(t("imagefx.gif_busy", locale))
            return
        log.error("Error en comando !gif", exc_info=error)
        await ctx.reply(t("general.error.generic", locale))

    @commands.command(name="gifcaption")
    async def gifcaption_cmd(self, ctx: commands.Context, *, texto: str | None = None):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if not texto:
            await ctx.reply(t("imagefx.caption.missing_text", locale))
            return
        await self._run_gif_filter(ctx, image_filters.gif_caption, texto)

    @commands.command(name="gifspeed")
    async def gifspeed_cmd(self, ctx: commands.Context, factor: float = 2.0):
        await self._run_gif_filter(ctx, image_filters.gif_speed, factor)

    @commands.command(name="gifreverse")
    async def gifreverse_cmd(self, ctx: commands.Context):
        await self._run_gif_filter(ctx, image_filters.gif_reverse)

    @commands.command(name="gifwide")
    async def gifwide_cmd(self, ctx: commands.Context, factor: float = 2.0):
        await self._run_gif_filter(ctx, image_filters.gif_wide, factor)

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        error = getattr(error, "original", error)
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if isinstance(error, commands.BadArgument):
            await ctx.reply(t("general.error.missing_argument", locale))
            return
        log.error("Error en comando de imagefx (%s)", ctx.command, exc_info=error)
        await ctx.reply(t("general.error.generic", locale))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImageFx(bot))
