"""Memes: /momo, memes automáticos, captura de imágenes con 🎯 y captions Groq/Markov."""

import asyncio
import io
import logging
import os
import time

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks
from groq import AsyncGroq

import r2
from cogs.premium import is_premium_guild, premium_required_message
from config import BOT_TRIGGER_NAME, GROQ_API_KEY, GROQ_GUILD_COOLDOWN, MEME_MAX_BYTES
from db import (
    delete_image_url,
    get_corpus_messages_filtered,
    get_due_meme_schedules,
    get_random_image_url_excluding,
    is_user_excluded_from_interaction,
    save_image_url,
    update_meme_last_posted,
)
from generation import build_markov_model
from i18n import guild_locale, t
from meme_generator import _try_short_sentence, is_valid_image, render_caption
from utils import LRUDict

log = logging.getLogger(__name__)

_groq_client = AsyncGroq(api_key=GROQ_API_KEY, timeout=15.0) if GROQ_API_KEY else None

_momo_cooldowns: LRUDict = LRUDict(512)
_groq_cooldowns: LRUDict = LRUDict(256)
_last_meme_image: LRUDict = LRUDict(256)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

_MEME_COOLDOWN_SECONDS = 45


def _check_meme_cooldown(guild_id: int, user_id: int) -> int | None:
    """None si puede generar un meme (y marca el cooldown); si no, segundos
    restantes. Compartido por /momo y por el trigger de texto ("generar"),
    así spamear replies no evade el límite de /momo."""
    now = time.time()
    key = (guild_id, user_id)
    elapsed = now - _momo_cooldowns.get(key, 0)
    if elapsed < _MEME_COOLDOWN_SECONDS:
        return int(_MEME_COOLDOWN_SECONDS - elapsed)
    _momo_cooldowns[key] = now
    return None


def is_meme_trigger(bot: commands.Bot, message: discord.Message) -> bool:
    parts = (message.content or "").strip().lower().split()
    if parts == [BOT_TRIGGER_NAME, "generar"]:
        return True
    if bot.user:
        for mention in (f"<@{bot.user.id}>", f"<@!{bot.user.id}>"):
            if parts == [mention, "generar"]:
                return True
    return False


def _detect_image_mime(image_bytes: bytes) -> str:
    if image_bytes[:4] == b"\x89PNG":
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[:3] == b"GIF":
        return "image/gif"
    return "image/jpeg"


async def generate_groq_meme_caption(
    image_bytes: bytes,
    corpus_sample: list[str],
    guild_id: int = 0,
) -> str | None:
    if not _groq_client:
        return None

    now = time.monotonic()
    if guild_id and now - _groq_cooldowns.get(guild_id, 0.0) < GROQ_GUILD_COOLDOWN:
        log.debug("Groq cooldown activo para guild %s, fallback a Markov", guild_id)
        return None
    if guild_id:
        _groq_cooldowns[guild_id] = now

    import base64

    mime_type = _detect_image_mime(image_bytes)
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    short_msgs = [m for m in corpus_sample if len(m.split()) <= 5]
    long_msgs = [m for m in corpus_sample if len(m.split()) > 5]
    voice_sample = short_msgs[:25] + long_msgs[:15]
    corpus_text = "\n".join(voice_sample)

    system_prompt = (
        "You write ironic meme captions for a Spanish-speaking Discord server. "
        "The humor comes from dissonance: the caption introduces a subject, expectation, or context "
        "that clashes with what the image actually shows — that clash is the joke. "
        "Never describe or narrate the image. "
        "Techniques: attribute the image to a subject that clearly doesn't fit it; "
        "set up a high expectation that the image deflates; "
        "present the image as evidence of the opposite of what it shows; "
        "compare the image to a grand or grave concept it contradicts. "
        "POV and CUANDO only work when what follows contrasts with the image, not when it summarizes it. "
        "Use the vocabulary and tone from the server corpus. "
        "Max 80 characters. Return only the caption text, nothing else."
    )

    user_prompt = (
        f"Vocabulario y registro de este server:\n"
        f"{corpus_text}\n\n"
        f"Mira la imagen. Escribe un caption que cree contraste con lo que muestra: "
        f"introduce un sujeto, expectativa o contexto que no encaje. "
        f"Usa las palabras y el registro de arriba. "
        f"Máximo 80 caracteres."
    )

    try:
        response = await _groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_b64}"
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            max_tokens=120,
            temperature=0.9,
        )
        caption = response.choices[0].message.content.strip()
        caption = caption.strip('"').strip("'").strip()
        if len(caption) > 80:
            caption = caption[:80].rsplit(" ", 1)[0].strip()
        return caption if caption else None
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            log.warning("Groq rate limit, fallback a Markov")
            return None
        log.exception("Error en Groq caption")
        return None


def _download_capped(url: str, max_bytes: int) -> bytes | None:
    """GET a `url`, cortando la descarga apenas se supera `max_bytes`.

    Antes leía con `.content` (requests.get sin stream=True), que junta el
    cuerpo entero en memoria ANTES de que el chequeo de tamaño de más arriba
    pudiera actuar -- mismo anti-patrón que upload_gif_sync ya corrigió en
    r2.py. Hoy no hay ruta de entrada real (las URLs que llegan al pool ya
    están acotadas a MEME_MAX_BYTES desde que se guardaron), pero es el mismo
    código sirviendo un pool de imágenes por guild -- barato de alinear con el
    patrón ya establecido, y cubre a un caller futuro menos cuidadoso."""
    resp = requests.get(url, timeout=15, stream=True)
    if resp.status_code != 200:
        resp.close()
        return None
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=262144):
        total += len(chunk)
        if total > max_bytes:
            resp.close()
            return None
        chunks.append(chunk)
    resp.close()
    return b"".join(chunks)


async def _pick_pool_image(
    guild_id: int, log_prefix: str
) -> tuple[bytes | None, str | None]:
    """Elige una imagen válida del pool, con eviction lazy de URLs muertas/expiradas."""
    img_bytes = None
    image_url = None
    last = _last_meme_image.get(guild_id)
    for _ in range(10):
        url_candidate = await get_random_image_url_excluding(guild_id, exclude_url=last)
        if not url_candidate:
            break
        try:
            img_bytes_candidate = await asyncio.to_thread(
                _download_capped, url_candidate, MEME_MAX_BYTES
            )
            if img_bytes_candidate is not None:
                img_bytes = img_bytes_candidate
                image_url = url_candidate
                break
            else:
                log.warning(
                    "%s: URL inválida o excede el tamaño máximo, eliminando: %s",
                    log_prefix,
                    url_candidate,
                )
                await delete_image_url(guild_id, url_candidate)
        except Exception:
            log.warning(
                "%s: error descargando, eliminando del pool: %s",
                log_prefix,
                url_candidate,
            )
            await delete_image_url(guild_id, url_candidate)
    if image_url:
        _last_meme_image[guild_id] = image_url
    return img_bytes, image_url


async def _generate_caption(
    guild_id: int, img_bytes: bytes, corpus_sample: list[str]
) -> str | None:
    caption = None
    if _groq_client:
        caption = await generate_groq_meme_caption(
            img_bytes, corpus_sample, guild_id=guild_id
        )
    if not caption:
        model = await build_markov_model(guild_id)
        if model and not model.is_empty:
            caption = await asyncio.to_thread(_try_short_sentence, model)
    return caption


async def handle_meme_command(message: discord.Message) -> None:
    locale = await guild_locale(message.guild.id if message.guild else None)
    if not is_premium_guild(message.guild.id if message.guild else None):
        try:
            await message.reply(premium_required_message(locale))
        except Exception:
            log.debug("No se pudo avisar el gate de premium", exc_info=True)
        return

    # Cooldown por usuario: sin esto, spamear replies "artemis generar" fuerza
    # renders de Pillow (y, cada 10s por guild, llamadas a Groq) sin límite.
    # Silencioso a propósito: responder "espera X segundos" en cada intento de
    # spam sería, en sí mismo, otra forma de ruido en el canal.
    if _check_meme_cooldown(message.guild.id, message.author.id) is not None:
        log.debug("handle_meme_command: cooldown activo, ignorando")
        return

    log.info(
        "handle_meme_command: message_id=%s content=%r has_reference=%s ref_message_id=%s",
        message.id,
        message.content,
        message.reference is not None,
        message.reference.message_id if message.reference else None,
    )

    if not message.reference or not message.reference.message_id:
        log.info("handle_meme_command: no es reply, ignorando")
        return

    ref = message.reference.resolved
    if ref is None or isinstance(ref, discord.DeletedReferencedMessage):
        log.info(
            "handle_meme_command: ref no resuelto, haciendo fetch de message_id=%s",
            message.reference.message_id,
        )
        try:
            ref = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            log.info(
                "handle_meme_command: fetch del mensaje referenciado falló, ignorando"
            )
            return
    if not isinstance(ref, discord.Message):
        log.info(
            "handle_meme_command: ref es %s (no es Message válido), ignorando",
            type(ref).__name__,
        )
        return

    log.info(
        "handle_meme_command: ref resuelto OK, message_id=%s, attachments=%d",
        ref.id,
        len(ref.attachments),
    )

    image_att = next(
        (
            a
            for a in ref.attachments
            if os.path.splitext(a.filename.lower())[1] in _IMAGE_EXTS
        ),
        None,
    )
    if image_att is None:
        log.info(
            "handle_meme_command: no se encontró attachment de imagen en el mensaje referenciado"
        )
        await message.reply(t("memes.need_image_reply", locale))
        return

    log.info(
        "handle_meme_command: imagen encontrada filename=%r size=%d bytes",
        image_att.filename,
        image_att.size,
    )

    if image_att.size > MEME_MAX_BYTES:
        await message.reply(t("memes.image_too_large", locale))
        return

    try:
        img_bytes = await image_att.read()
    except Exception:
        log.exception("Error descargando imagen para meme")
        await message.reply(t("memes.download_failed", locale))
        return

    if not message.guild:
        log.info(
            "handle_meme_command: mensaje fuera de guild, no hay modelo Markov disponible"
        )
        await message.reply(t("memes.no_guild", locale))
        return

    log.info("handle_meme_command: generando caption")

    text = None
    if _groq_client:
        corpus_sample = await get_corpus_messages_filtered(
            message.guild.id, min_words=1, limit=400
        )
        if corpus_sample:
            text = await generate_groq_meme_caption(
                img_bytes, corpus_sample, guild_id=message.guild.id
            )
    if not text:
        model = await build_markov_model(message.guild.id)
        if model and not model.is_empty:
            text = await asyncio.to_thread(_try_short_sentence, model)
    log.info("handle_meme_command: texto generado=%r", text)
    if not text:
        await message.reply(t("memes.caption_missing", locale))
        return

    try:
        meme_bytes = await asyncio.to_thread(render_caption, img_bytes, text)
    except Exception:
        log.exception("Error generando meme con Pillow")
        await message.reply(t("memes.render_failed", locale))
        return

    await message.reply(file=discord.File(io.BytesIO(meme_bytes), filename="meme.png"))


class Memes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        if not _groq_client:
            log.info(
                "GROQ_API_KEY no configurada: captions de memes usarán solo Markov."
            )
        self.auto_meme_task.start()

    async def cog_unload(self) -> None:
        self.auto_meme_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild and await is_user_excluded_from_interaction(
            message.guild.id, message.author.id
        ):
            return
        if is_meme_trigger(self.bot, message):
            await handle_meme_command(message)

    async def _target_fail(
        self, message: discord.Message, user_id: int, reason: str, locale: str
    ) -> None:
        """Señal de fallo para 🎯: ❌ garantizado en el mensaje + DM best-effort."""
        try:
            await message.add_reaction("❌")
        except Exception:
            log.debug("No se pudo reaccionar ❌ al mensaje %s", message.id)
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(t("memes.pool_fail_dm", locale, reason=reason))
        except Exception:
            pass  # DMs cerrados: la reacción ❌ ya es la señal mínima

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != "🎯":
            return
        if payload.guild_id is None:
            return
        if await is_user_excluded_from_interaction(payload.guild_id, payload.user_id):
            return
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return
        if message.author.bot:
            return
        locale = await guild_locale(payload.guild_id)
        if not is_premium_guild(payload.guild_id):
            await self._target_fail(
                message, payload.user_id, premium_required_message(locale), locale
            )
            return

        added = False
        oversized = False
        unsupported = False
        duplicate = False
        save_error = False
        for attachment in message.attachments:
            ext = os.path.splitext(attachment.filename.lower())[1]
            if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                unsupported = True
                continue
            if attachment.size > MEME_MAX_BYTES:
                oversized = True
                continue
            try:
                img_bytes = await attachment.read()
            except Exception:
                save_error = True
                log.exception(
                    "Error descargando adjunto para el pool de memes: %s",
                    attachment.url,
                )
                continue
            # La extensión sola no garantiza que el contenido sea una imagen
            # real: sin esto, cualquier archivo con extensión .png/.jpg entra
            # al pool y termina abriéndose con Pillow al generar un meme.
            if not is_valid_image(img_bytes):
                unsupported = True
                continue
            try:
                if r2.available():
                    final_url = await asyncio.to_thread(
                        r2.upload_image_bytes_sync,
                        attachment.url,
                        img_bytes,
                        payload.guild_id,
                        ext,
                    )
                    if not final_url:
                        log.warning(
                            "No se pudo subir imagen a R2, usando URL original: %s",
                            attachment.url,
                        )
                        final_url = attachment.url
                else:
                    final_url = attachment.url
                inserted = await save_image_url(payload.guild_id, final_url)
                if inserted:
                    added = True
                    log.info("Imagen agregada al pool 🎯: %s", final_url)
                else:
                    duplicate = True
            except Exception:
                save_error = True
                log.exception("Error guardando imagen por reaccion")
        if added:
            try:
                await message.add_reaction("✅")
            except Exception:
                pass
            return

        # Nada guardado: explicar por qué en vez de quedarse callado.
        if duplicate:
            reason = t("memes.pool_reason.duplicate", locale)
        elif save_error:
            reason = t("memes.pool_reason.save_error", locale)
        elif oversized:
            reason = t(
                "memes.pool_reason.oversized",
                locale,
                mb=MEME_MAX_BYTES // (1024 * 1024),
            )
        elif unsupported:
            reason = t("memes.pool_reason.unsupported", locale)
        else:
            reason = t("memes.pool_reason.no_image", locale)
        await self._target_fail(message, payload.user_id, reason, locale)

    @tasks.loop(minutes=10)
    async def auto_meme_task(self):
        schedules = await get_due_meme_schedules()
        for schedule in schedules:
            try:
                channel = self.bot.get_channel(schedule["channel_id"])
                if not channel or not isinstance(channel, discord.TextChannel):
                    continue

                guild_id = schedule["guild_id"]
                if not is_premium_guild(guild_id):
                    continue

                img_bytes, image_url = await _pick_pool_image(guild_id, "auto_meme")
                if not image_url:
                    log.info(
                        "auto_meme: sin imágenes válidas en pool para guild %s",
                        guild_id,
                    )
                    continue

                corpus_sample = await get_corpus_messages_filtered(
                    guild_id, min_words=1, limit=400
                )
                if not corpus_sample:
                    log.info("auto_meme: corpus vacío para guild %s", guild_id)
                    continue

                caption = await _generate_caption(guild_id, img_bytes, corpus_sample)
                if not caption:
                    log.info("auto_meme: no se generó caption para guild %s", guild_id)
                    continue

                meme_bytes = await asyncio.to_thread(render_caption, img_bytes, caption)
                await channel.send(
                    file=discord.File(io.BytesIO(meme_bytes), filename="meme.png")
                )
            except Exception:
                log.exception(
                    "auto_meme: error inesperado para canal %s", schedule["channel_id"]
                )
                continue

            # El meme YA se posteó. Si update_meme_last_posted falla acá, el
            # schedule sigue "due" y se repostea en la próxima corrida (10
            # min) -- duplicado visible. Log distinto y más fuerte que el de
            # arriba a propósito: esto no es "no se pudo generar el meme",
            # es "se generó y se mandó, pero puede reenviarse".
            try:
                await update_meme_last_posted(guild_id, schedule["channel_id"])
                log.info(
                    "auto_meme: meme posteado en canal %s con caption: %s",
                    schedule["channel_id"],
                    caption,
                )
            except Exception:
                log.error(
                    "auto_meme: se posteó el meme en canal %s pero no se pudo "
                    "marcar como enviado -- probablemente se repostee en la "
                    "próxima corrida (10 min)",
                    schedule["channel_id"],
                    exc_info=True,
                )

    @auto_meme_task.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    async def _momo_impl(self, interaction: discord.Interaction) -> None:
        locale = await guild_locale(interaction.guild_id)
        if not is_premium_guild(interaction.guild_id):
            await interaction.response.send_message(
                premium_required_message(locale), ephemeral=True
            )
            return
        remaining = _check_meme_cooldown(interaction.guild_id or 0, interaction.user.id)
        if remaining is not None:
            await interaction.response.send_message(
                t("memes.momo_cooldown", locale, seconds=remaining),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        if not interaction.guild:
            await interaction.followup.send(
                t("general.guild_only", locale), ephemeral=True
            )
            return

        try:
            guild_id = interaction.guild.id

            img_bytes, image_url = await _pick_pool_image(guild_id, "momo")
            if not image_url:
                await interaction.followup.send(
                    t("memes.momo_no_pool_image", locale),
                    ephemeral=True,
                )
                return

            corpus_sample = await get_corpus_messages_filtered(
                guild_id, min_words=1, limit=400
            )
            if not corpus_sample:
                await interaction.followup.send(
                    t("memes.momo_no_corpus", locale),
                    ephemeral=True,
                )
                return

            caption = await _generate_caption(guild_id, img_bytes, corpus_sample)
            if not caption:
                await interaction.followup.send(
                    t("memes.caption_missing", locale),
                    ephemeral=True,
                )
                return

            meme_bytes = await asyncio.to_thread(render_caption, img_bytes, caption)
            await interaction.followup.send(
                file=discord.File(io.BytesIO(meme_bytes), filename="meme.png")
            )

        except Exception:
            log.exception("momo: error inesperado")
            await interaction.followup.send(
                t("memes.momo_generic_error", locale),
                ephemeral=True,
            )

    @app_commands.command(name="momo", description="Genera un meme del server.")
    async def momo(self, interaction: discord.Interaction):
        await self._momo_impl(interaction)

    @app_commands.command(name="meme", description="Genera un meme del server.")
    async def meme(self, interaction: discord.Interaction):
        await self._momo_impl(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Memes(bot))
