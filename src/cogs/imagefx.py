"""Filtros de imagen tipo NotSoBot (Fases 1, 2 y 4).

"!gif" resuelve sus fuentes de forma independiente de "!dl": adjuntos,
URLs y medios de embeds, desde el mensaje actual o el mensaje respondido.
Así no hereda las restricciones ni los mensajes propios del descargador de
redes sociales.
"""

import asyncio
import io
import logging
import os
import re
import time
from typing import Callable
from urllib.parse import urlparse

import discord
import requests
from discord.ext import commands

import image_filters
import r2
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
_MEDIA_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

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


def _clean_url(url: str) -> str:
    """Limpia caracteres de cierre de markdown o puntuación residual de una URL."""
    url = url.strip()
    for start_char, end_char in (("<", ">"), ("(", ")"), ("[", "]"), ('"', '"'), ("'", "'")):
        if url.startswith(start_char) and url.endswith(end_char):
            url = url[1:-1].strip()
    while url and url[-1] in (")", "]", ">", "\"", "'", ",", ";", "."):
        url = url[:-1]
    return url


async def _resolve_reference(ctx: commands.Context) -> discord.Message | None:
    """Obtiene el mensaje respondido sin depender del handler de !dl.

    Si Discord mandó un snapshot parcial en `referenced_message` o el mensaje
    estaba en caché antes de que Discord generase los embeds (unfurl
    asíncrono), intenta un `fetch_message` para obtener la versión completa con
    embeds y adjuntos.
    """
    reference = getattr(ctx.message, "reference", None)
    if reference is None:
        return None
    resolved = getattr(reference, "resolved", None)
    if isinstance(resolved, discord.DeletedReferencedMessage):
        return None

    message_id = getattr(reference, "message_id", None)
    needs_fetch = resolved is None or (
        not getattr(resolved, "attachments", None)
        and not getattr(resolved, "embeds", None)
    )
    if needs_fetch and message_id is not None:
        channel = ctx.channel
        reference_channel_id = getattr(reference, "channel_id", None)
        bot = getattr(ctx, "bot", None)
        if reference_channel_id and reference_channel_id != getattr(channel, "id", None) and bot is not None:
            channel = getattr(bot, "get_channel", lambda _: None)(reference_channel_id)
            if channel is None and hasattr(bot, "fetch_channel"):
                try:
                    channel = await bot.fetch_channel(reference_channel_id)
                except discord.HTTPException:
                    channel = None
        if channel is not None and hasattr(channel, "fetch_message"):
            try:
                fetched = await channel.fetch_message(message_id)
                if fetched is not None:
                    resolved = fetched
            except discord.HTTPException:
                pass
    return resolved


async def _source_messages(ctx: commands.Context) -> list[discord.Message]:
    """Mensaje actual primero y, si existe, el mensaje al que se responde."""
    messages = [ctx.message]
    referenced = await _resolve_reference(ctx)
    if referenced is not None:
        messages.append(referenced)
    return messages


def _embed_media_urls(message: discord.Message, attributes: tuple[str, ...]):
    """Entrega todas las URLs de medio que Discord expone en sus embeds.

    Los embeds no tienen una forma única: según el proveedor y el tipo,
    discord.py puede poner el archivo en ``url`` o en ``proxy_url``. Se
    recorren ambos y todos los embeds en vez de descartar el mensaje tras el
    primer recurso que falle.
    """
    seen: set[str] = set()
    for embed in getattr(message, "embeds", ()):
        for attribute in attributes:
            media = getattr(embed, attribute, None)
            for name in ("url", "proxy_url"):
                url = getattr(media, name, None)
                if url:
                    url = _clean_url(url)
                    if url and url not in seen:
                        seen.add(url)
                        yield url


def _embed_url_texts_single(embed: discord.Embed):
    def walk(key, value):
        # Evitar imágenes/iconos que nunca son el video
        if key in ("thumbnail", "author", "footer", "icon"):
            return
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for k, child in value.items():
                yield from walk(k, child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from walk(key, child)

    for attribute in ("title", "description"):
        value = getattr(embed, attribute, None)
        if isinstance(value, str):
            yield value

    for field in getattr(embed, "fields", ()):
        if isinstance(field, dict):
            name = field.get("name")
            val = field.get("value")
        else:
            name = getattr(field, "name", None)
            val = getattr(field, "value", None)
        if isinstance(name, str):
            yield name
        if isinstance(val, str):
            yield val

    author = getattr(embed, "author", None)
    author_url = getattr(author, "url", None)
    if isinstance(author_url, str):
        yield author_url

    to_dict = getattr(embed, "to_dict", None)
    if callable(to_dict):
        try:
            yield from walk("", to_dict())
        except Exception:
            log.debug("No se pudo serializar embed para !gif", exc_info=True)


def _embed_url_texts(message: discord.Message):
    """Expone las URLs y texto serializado de cualquier variante de embed."""
    for embed in getattr(message, "embeds", ()):
        yield from _embed_url_texts_single(embed)


def _embed_video_urls(message: discord.Message):
    """Entrega todas las URLs potenciales de video de los embeds del mensaje.

    Cubre todas las variantes de embeds de Discord:
    1. Embeds con reproductor de video (type='video', 'gifv'):
       - embed.video.url y embed.video.proxy_url
    2. Embeds con URL principal (type='rich', 'link', 'article', etc.):
       - embed.url
    3. URLs encontradas en description, fields o to_dict() del embed
    """
    seen: set[str] = set()

    def _yield_url(raw: str | None):
        if not raw or not isinstance(raw, str):
            return
        cleaned = _clean_url(raw)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            yield cleaned

    for embed in getattr(message, "embeds", ()):
        # 1. Video explícito del embed
        video = getattr(embed, "video", None)
        if video is not None:
            for name in ("url", "proxy_url"):
                yield from _yield_url(getattr(video, name, None))

        # 2. URL principal del embed (clave en embeds tipo 'rich', 'link', 'article')
        yield from _yield_url(getattr(embed, "url", None))

        # 3. URLs en texto serializado del embed
        for text in _embed_url_texts_single(embed):
            for match in _MEDIA_URL_RE.finditer(text):
                yield from _yield_url(match.group(0))


async def _fetch_media_bytes(url: str, max_bytes: int, timeout: float = 15.0) -> bytes | None:
    """Baja una URL HTTP(S) de medios con límite y protección SSRF."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    def _download() -> bytes | None:
        try:
            response = r2.fetch_public_url(
                requests.get,
                url,
                headers={"User-Agent": _BROWSER_UA},
                timeout=timeout,
                stream=True,
            )
            try:
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type.startswith("text/html"):
                    return None
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise SourceTooLarge(max_bytes)
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=262144):
                    total += len(chunk)
                    if total > max_bytes:
                        raise SourceTooLarge(max_bytes)
                    chunks.append(chunk)
                data = b"".join(chunks)
                if data.lstrip().startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"<?xml")):
                    return None
                return data
            finally:
                response.close()
        except SourceTooLarge:
            raise
        except Exception:
            log.debug("No se pudo bajar medio para !gif: %s", url, exc_info=True)
            return None

    return await asyncio.to_thread(_download)


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

    for message in (await _source_messages(ctx))[1:]:
        for attachment in getattr(message, "attachments", ()):
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


async def _resolve_video_bytes(
    ctx: commands.Context, url: str | None = None
) -> bytes | None:
    """Fuente del video para "!gif":
    1. Adjunto de video propio o del mensaje respondido (extensión o video/*).
    2. Video en los embeds del mensaje actual o del respondido:
       - embed.video (url y proxy_url)
       - embed.url (clave en embeds de tipo rich, link, etc. que envían bots)
       - URLs en description, fields o payload serializado del embed
    3. URL provista como argumento o presente en el texto del mensaje.
    """
    attachment = await _find_attachment(ctx, _VIDEO_EXTS, content_type_prefix="video/")
    if attachment is not None:
        if attachment.size > MAX_GIF_SOURCE_VIDEO_BYTES:
            raise SourceTooLarge(MAX_GIF_SOURCE_VIDEO_BYTES)
        return await attachment.read()

    # Si el comando tiene un adjunto propio (aunque sea imagen), ese adjunto
    # local tiene prioridad sobre links o descargas web.
    if ctx.message.attachments:
        return None

    seen_urls: set[str] = set()
    for message in await _source_messages(ctx):
        for video_url in _embed_video_urls(message):
            if video_url in seen_urls:
                continue
            seen_urls.add(video_url)
            data = await _fetch_media_bytes(video_url, MAX_GIF_SOURCE_VIDEO_BYTES)
            if data is not None:
                if is_valid_image(data):
                    continue
                return data

    candidates: list[str] = [url] if url else []
    for message in await _source_messages(ctx):
        content = getattr(message, "content", "") or ""
        if content:
            candidates.append(content)
    for candidate in candidates:
        for match in _MEDIA_URL_RE.finditer(candidate):
            clean = _clean_url(match.group(0))
            if not clean or clean in seen_urls:
                continue
            seen_urls.add(clean)
            data = await _fetch_media_bytes(clean, MAX_GIF_SOURCE_VIDEO_BYTES)
            if data is not None and not is_valid_image(data):
                return data

    return None


async def _resolve_gif_source_image_bytes(
    ctx: commands.Context, url: str | None = None
) -> bytes | None:
    """Fuente de imagen para "!gif" cuando NO hubo ningún video:
    1. Adjunto de imagen propio o del mensaje respondido
    2. Imagen o thumbnail embebidos en el mensaje
    3. URL directa o presente en el texto del mensaje
    """
    attachment = await _find_attachment(ctx, _IMAGE_EXTS, content_type_prefix="image/")
    if attachment is not None:
        if attachment.size > IMAGEFX_MAX_BYTES:
            raise SourceTooLarge(IMAGEFX_MAX_BYTES)
        return await attachment.read()

    if ctx.message.attachments:
        return None

    seen_urls: set[str] = set()
    for message in await _source_messages(ctx):
        for image_url in _embed_media_urls(message, ("image", "thumbnail")):
            if image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            data = await _fetch_media_bytes(image_url, IMAGEFX_MAX_BYTES)
            if data is not None:
                return data

    candidates: list[str] = [url] if url else []
    for message in await _source_messages(ctx):
        content = getattr(message, "content", "") or ""
        if content:
            candidates.append(content)
        candidates.extend(_embed_url_texts(message))
    for candidate in candidates:
        for match in _MEDIA_URL_RE.finditer(candidate):
            clean = _clean_url(match.group(0))
            if not clean or clean in seen_urls:
                continue
            seen_urls.add(clean)
            data = await _fetch_media_bytes(clean, IMAGEFX_MAX_BYTES)
            if data is not None:
                return data

    return None


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
            data = await _resolve_video_bytes(ctx, url=url)
        except SourceTooLarge as e:
            await ctx.reply(
                t("imagefx.video_too_large", locale, mb=e.max_bytes // (1024 * 1024))
            )
            return
        except discord.HTTPException:
            await ctx.reply(t("general.error.generic", locale))
            return

        if data is None:
            # Sin ningún video (adjunto, embed o URL): se busca una imagen
            # estática como fallback (adjunto, embed o URL) y se empaqueta
            # como GIF de un solo frame.
            try:
                image_data = await _resolve_gif_source_image_bytes(ctx, url=url)
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

            await ctx.reply(t("imagefx.video_missing", locale))
            return

        if is_valid_image(data):
            try:
                result = await asyncio.to_thread(image_filters.image_to_gif, data)
            except Exception:
                log.exception("Error convirtiendo imagen a GIF en !gif")
                await ctx.reply(t("general.error.generic", locale))
                return
            await ctx.reply(file=discord.File(io.BytesIO(result), filename="purgito.gif"))
            return

        async with ctx.typing():
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

        await ctx.reply(file=discord.File(io.BytesIO(result), filename="purgito.gif"))

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
