"""Filtros de imagen tipo NotSoBot (Fase 1): comandos con prefijo que
transforman la imagen adjunta al mensaje, la del mensaje respondido, o el
avatar de quien invoca si no hay ninguna de las dos -- mismo mecanismo de
"adjunto propio -> reply" que ya usa cogs/download.py para "purgito dl"."""

import asyncio
import io
import logging
import os
import time
from typing import Callable

import discord
from discord.ext import commands

import image_filters
from config import IMAGEFX_MAX_BYTES
from i18n import guild_locale, t
from meme_generator import is_valid_image
from utils import LRUDict

log = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Cooldown compartido por TODOS los filtros de este cog, no uno por comando:
# son 14 comandos de costo parecido, así que un cooldown por nombre de
# comando (lo que da @commands.cooldown por default) se evade rotando entre
# ellos -- mismo problema que ya resolvió _check_meme_cooldown en cogs/memes.py
# para /momo vs. el trigger de texto.
_FX_COOLDOWN_SECONDS = 6
_fx_cooldowns: LRUDict = LRUDict(1024)


class ImageTooLarge(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


def _check_fx_cooldown(user_id: int) -> int | None:
    now = time.monotonic()
    elapsed = now - _fx_cooldowns.get(user_id, 0.0)
    if elapsed < _FX_COOLDOWN_SECONDS:
        return int(_FX_COOLDOWN_SECONDS - elapsed) or 1
    _fx_cooldowns[user_id] = now
    return None


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    ext = os.path.splitext(attachment.filename.lower())[1]
    return ext in _IMAGE_EXTS


async def _find_attachment(ctx: commands.Context) -> discord.Attachment | None:
    for attachment in ctx.message.attachments:
        if _is_image_attachment(attachment):
            return attachment

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
    for attachment in resolved.attachments:
        if _is_image_attachment(attachment):
            return attachment
    return None


async def _resolve_image_bytes(ctx: commands.Context) -> bytes:
    """Adjunto propio -> adjunto del mensaje respondido -> avatar de quien
    invoca. with_static_format fuerza un PNG estático incluso si el avatar
    es animado -- is_valid_image no acepta GIF (ver _ALLOWED_FORMATS en
    meme_generator.py)."""
    attachment = await _find_attachment(ctx)
    if attachment is not None:
        if attachment.size > IMAGEFX_MAX_BYTES:
            raise ImageTooLarge(IMAGEFX_MAX_BYTES)
        return await attachment.read()
    avatar = ctx.author.display_avatar.with_static_format("png")
    return await avatar.read()


class ImageFx(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _run_filter(
        self, ctx: commands.Context, fn: Callable[..., bytes], *args
    ) -> None:
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        remaining = _check_fx_cooldown(ctx.author.id)
        if remaining is not None:
            await ctx.reply(t("general.error.cooldown", locale, seconds=remaining))
            return

        try:
            data = await _resolve_image_bytes(ctx)
        except ImageTooLarge as e:
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

        await ctx.reply(file=discord.File(io.BytesIO(result), filename="purgito.png"))

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
