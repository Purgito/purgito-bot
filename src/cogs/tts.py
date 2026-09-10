"""Cog de Chat-to-Speech pasivo para Purgito con cola FIFO y soporte multi-proveedor."""

import logging
import re
import uuid

import discord
from discord.ext import commands, tasks

import config
from db import get_tts_guild_settings
from tts.errors import InvalidInputError, QueueFullError, TTSError
from tts.queue_manager import TTSQueueItem, TTSQueueManager
from tts.service import TTSService

log = logging.getLogger(__name__)


class TTS(commands.Cog):
    """Chat-to-Speech pasivo para Purgito: reproduce automáticamente mensajes del canal configurado."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tts_service = TTSService(
            max_concurrent_generations=config.TTS_MAX_CONCURRENT_GENERATIONS,
            max_text_length=config.TTS_MAX_TEXT_LENGTH,
        )
        self.tts_queue_manager = TTSQueueManager(
            max_queue_size=config.TTS_MAX_QUEUE_PER_GUILD,
            idle_timeout_seconds=180.0,
        )

    async def cog_load(self) -> None:
        self.cache_prune_task.start()
        log.info("Cog TTS cargado correctamente (Chat-to-Speech pasivo)")

    async def cog_unload(self) -> None:
        self.cache_prune_task.cancel()
        await self.tts_queue_manager.stop_all()
        log.info("Cog TTS descargado y colas detenidas")

    @tasks.loop(hours=24)
    async def cache_prune_task(self) -> None:
        """Limpieza periódica diaria de audios expirados en la caché."""
        try:
            deleted = await self.tts_service.cache.prune()
            if deleted > 0:
                log.info("Caché TTS: %d archivos antiguos podados", deleted)
        except Exception:
            log.exception("Error durante la poda periódica de caché TTS")

    @cache_prune_task.before_loop
    async def before_cache_prune(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listener para Chat-to-Speech automático en el canal configurado."""
        try:
            await self._handle_chat_to_speech(message)
        except Exception:
            log.exception("Excepción no controlada en on_message de Chat-to-Speech")

    async def _handle_chat_to_speech(self, message: discord.Message) -> None:
        # 1. Ignorar mensajes fuera de un servidor (DMs)
        guild = getattr(message, "guild", None)
        if guild is None:
            return

        # 2. Consultar configuración del servidor
        guild_settings = await get_tts_guild_settings(guild.id)
        if not guild_settings:
            return

        # Si chat_to_speech_channel_id NO está configurado, Chat-to-Speech está inactivo
        target_channel_id = guild_settings.get("chat_to_speech_channel_id")
        if not target_channel_id:
            return

        if not guild_settings.get("chat_to_speech_enabled", True):
            return

        # Mensajes de otros canales se ignoran
        channel = getattr(message, "channel", None)
        if (
            target_channel_id is None
            or getattr(channel, "id", None) != target_channel_id
        ):
            return

        # 3. Filtrar bots/webhooks según configuración del servidor (allow_bots=False por defecto)
        author = getattr(message, "author", None)
        is_bot = bool(
            getattr(author, "bot", False) or getattr(message, "webhook_id", None)
        )
        if is_bot and not guild_settings.get("allow_bots", False):
            return

        # 4. Contenido del mensaje y prefijos de exclusión
        raw_content = (
            getattr(message, "clean_content", None)
            or getattr(message, "content", "")
            or ""
        )
        content = raw_content.strip()
        if not content:
            return

        # Mantener exclusión por prefijo (ej. //, \\, /*)
        if content.startswith(("//", "\\\\", "/*")):
            return

        # 5. Detección de override explícito de voz: [voz_id] texto
        override_voice: str | None = None
        text_to_speak = content

        override_match = re.match(r"^\[([a-zA-Z0-9_\-]+)\]\s*(.*)$", content, re.DOTALL)
        if override_match:
            candidate_voice = override_match.group(1)
            remaining = override_match.group(2).strip()
            if remaining:
                override_voice = candidate_voice
                text_to_speak = remaining

        # 6. Respetar límite de caracteres (truncado limpio según política)
        if len(text_to_speak) > self.tts_service.max_text_length:
            text_to_speak = text_to_speak[: self.tts_service.max_text_length].strip()

        if not text_to_speak:
            return

        # 7. Gestión de conexión al canal de voz:
        # - Si Purgito YA está conectado, usa esa conexión existente.
        # - Si NO está conectado, busca el canal de voz del autor y se conecta automáticamente.
        # - Si el autor NO está en un canal de voz, ignora el mensaje (no conecta ni sintetiza).
        vc = getattr(guild, "voice_client", None)
        is_connected = False
        if vc is not None:
            is_conn_attr = getattr(vc, "is_connected", None)
            is_connected = (
                is_conn_attr() if callable(is_conn_attr) else bool(is_conn_attr)
            )

        if not is_connected:
            voice_state = getattr(author, "voice", None)
            author_voice_channel = getattr(voice_state, "channel", None)
            if author_voice_channel is None:
                # El autor no está actualmente en un canal de voz -> ignorar
                return

            try:
                vc = await author_voice_channel.connect(timeout=10.0, reconnect=True)
            except Exception as exc:
                vc = getattr(guild, "voice_client", None)
                is_now_connected = False
                if vc is not None:
                    is_conn_now = getattr(vc, "is_connected", None)
                    is_now_connected = (
                        is_conn_now() if callable(is_conn_now) else bool(is_conn_now)
                    )
                if not is_now_connected:
                    log.warning(
                        "No se pudo conectar automáticamente al canal de voz %s en guild %s: %s",
                        getattr(author_voice_channel, "id", None),
                        guild.id,
                        exc,
                    )
                    return

        # 8. Resolver voz: override explícito > preferencia usuario > preferencia guild > default global
        author_id = getattr(author, "id", None)
        resolved_voice = await self.tts_service.resolve_voice(
            command_voice=override_voice,
            user_id=author_id,
            guild_id=guild.id,
        )

        user_settings = (
            await self.tts_service.resolve_user_settings(author_id)
            if author_id
            else {"filter": "normal", "speed": 1.0, "pitch": 1.0}
        )

        # 9. Síntesis y encolado seguro en la cola FIFO del guild
        try:
            audio_path = await self.tts_service.synthesize_speech(
                text=text_to_speak,
                voice_id=resolved_voice,
                filter_name=user_settings["filter"],
                speed=user_settings["speed"],
                pitch=user_settings["pitch"],
            )

            player = await self.tts_queue_manager.get_player(guild.id)
            player.voice_client = vc

            item = TTSQueueItem(
                id=uuid.uuid4().hex,
                guild_id=guild.id,
                text=text_to_speak,
                voice_id=resolved_voice,
                audio_path=audio_path,
                channel_id=getattr(channel, "id", 0),
                user_id=author_id or 0,
            )
            await player.enqueue(item)

        except QueueFullError as exc:
            log.warning(
                "Cola TTS llena en guild %s, mensaje descartado: %s",
                guild.id,
                exc,
            )
        except InvalidInputError as exc:
            log.debug(
                "Mensaje TTS inválido en guild %s: %s",
                guild.id,
                exc,
            )
        except TTSError as exc:
            log.warning(
                "Error de síntesis TTS en Chat-to-Speech para guild %s: %s",
                guild.id,
                exc,
            )
        except Exception:
            log.exception(
                "Error inesperado procesando Chat-to-Speech en guild %s",
                guild.id,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TTS(bot))
