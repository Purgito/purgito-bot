"""Cog de TTS (Text-to-Speech) para Purgito con cola FIFO y soporte multi-proveedor."""

import logging
import re
import uuid

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from db import get_tts_guild_settings, set_tts_guild_settings, set_tts_user_settings
from tts.errors import InvalidInputError, QueueFullError, TTSError
from tts.queue_manager import TTSQueueItem, TTSQueueManager
from tts.service import TTSService

log = logging.getLogger(__name__)


async def _voice_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete interactivo para selección de voces de TikTok y Edge."""
    # Catálogo de voces rápidas y comunes
    quick_voices = [
        ("es_002", "Español (Hombre - TikTok)"),
        ("es_male_m3", "Español - Julio (TikTok)"),
        ("es_female_f6", "Español - Marcela (TikTok)"),
        ("es_female_fp1", "Español - Suave (TikTok)"),
        ("es_mx_002", "Español México (TikTok)"),
        ("es-ES-AlvaroNeural", "Español España - Álvaro (Edge)"),
        ("es-ES-ElviraNeural", "Español España - Elvira (Edge)"),
        ("es-MX-JorgeNeural", "Español México - Jorge (Edge)"),
        ("es-MX-DaliaNeural", "Español México - Dalia (Edge)"),
        ("es-AR-TomasNeural", "Español Argentina - Tomás (Edge)"),
        ("es-CL-LorenzoNeural", "Español Chile - Lorenzo (Edge)"),
        ("en_us_002", "English - Jessie (TikTok)"),
        ("en_male_narration", "English - Narrator (TikTok)"),
        ("en_male_ghostface", "English - Ghostface (TikTok)"),
        ("en-US-ChristopherNeural", "English US - Christopher (Edge)"),
    ]
    current_lower = current.lower().strip()
    choices = []
    for v_id, label in quick_voices:
        if (
            not current_lower
            or current_lower in v_id.lower()
            or current_lower in label.lower()
        ):
            choices.append(app_commands.Choice(name=f"{v_id} — {label}", value=v_id))
            if len(choices) >= 25:
                break
    return choices


class TTS(commands.Cog):
    """Comandos de voz Text-to-Speech (TTS) inspirados en la experiencia de Wamellow."""

    tts_group = app_commands.Group(
        name="tts",
        description="Comandos de texto a voz (TTS)",
        guild_only=True,
    )

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
        log.info("Cog TTS cargado correctamente")

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

    @tts_group.command(
        name="decir",
        description="Convierte texto a voz y lo reproduce en tu canal de voz actual.",
    )
    @app_commands.describe(
        texto="Texto que dirá el bot en voz alta",
        voz="Voz opcional para este mensaje (ignora temporalmente tus ajustes)",
    )
    @app_commands.autocomplete(voz=_voice_autocomplete)
    async def decir(
        self,
        interaction: discord.Interaction,
        texto: str,
        voz: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo puede utilizarse dentro de un servidor.",
                ephemeral=True,
            )
            return

        user = interaction.user
        voice_state = getattr(user, "voice", None)
        if voice_state is None or getattr(voice_state, "channel", None) is None:
            await interaction.response.send_message(
                "Debes estar conectado a un canal de voz para usar este comando.",
                ephemeral=True,
            )
            return

        target_channel = voice_state.channel

        clean_text = (texto or "").strip()
        if not clean_text:
            await interaction.response.send_message(
                "No puedes enviar un texto vacío.",
                ephemeral=True,
            )
            return

        if len(clean_text) > self.tts_service.max_text_length:
            await interaction.response.send_message(
                f"El texto es demasiado largo (máximo {self.tts_service.max_text_length} caracteres).",
                ephemeral=True,
            )
            return

        # Deferir para permitir síntesis y conexión de voz
        await interaction.response.defer(ephemeral=False)

        try:
            # 1. Resolución de voz
            resolved_voice = await self.tts_service.resolve_voice(
                command_voice=voz,
                user_id=user.id,
                guild_id=interaction.guild.id,
            )

            # 2. Preferencias de filtros del usuario
            user_settings = await self.tts_service.resolve_user_settings(user.id)

            # 3. Síntesis y procesamiento de audio
            audio_path = await self.tts_service.synthesize_speech(
                text=clean_text,
                voice_id=resolved_voice,
                filter_name=user_settings["filter"],
                speed=user_settings["speed"],
                pitch=user_settings["pitch"],
            )

            # 4. Gestión de conexión al canal de voz
            guild = interaction.guild
            vc = guild.voice_client

            if vc is None or not vc.is_connected():
                try:
                    vc = await target_channel.connect(timeout=10.0, reconnect=True)
                except Exception as exc:
                    log.error(
                        "Error conectando al canal de voz %s: %s",
                        target_channel.id,
                        exc,
                    )
                    await interaction.followup.send(
                        "No pude conectarme a tu canal de voz. Comprueba mis permisos.",
                        ephemeral=True,
                    )
                    return
            elif vc.channel != target_channel:
                try:
                    await vc.move_to(target_channel)
                except Exception as exc:
                    log.warning(
                        "No se pudo mover al canal de voz %s: %s",
                        target_channel.id,
                        exc,
                    )

            # 5. Encolar en el reproductor del servidor
            player = await self.tts_queue_manager.get_player(guild.id)
            player.voice_client = vc

            item = TTSQueueItem(
                id=uuid.uuid4().hex,
                guild_id=guild.id,
                text=clean_text,
                voice_id=resolved_voice,
                audio_path=audio_path,
                channel_id=interaction.channel_id,
                user_id=user.id,
            )

            is_busy = player.is_playing
            await player.enqueue(item)

            if is_busy:
                pos = player.queue_size()
                await interaction.followup.send(
                    f"⏳ Añadido a la cola en la posición #{pos}: *{clean_text}* [{resolved_voice}]"
                )
            else:
                await interaction.followup.send(
                    f"🔊 Reproduciendo: *{clean_text}* [{resolved_voice}]"
                )

        except QueueFullError as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
        except InvalidInputError as exc:
            await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
        except TTSError as exc:
            log.warning("Error de TTS en /tts decir: %s", exc)
            await interaction.followup.send(
                "Hubo un problema al generar el audio. Inténtalo de nuevo en unos momentos.",
                ephemeral=True,
            )
        except Exception:
            log.exception("Error no controlado en /tts decir")
            await interaction.followup.send(
                "Ocurrió un error inesperado al procesar la solicitud de TTS.",
                ephemeral=True,
            )

    @tts_group.command(
        name="voz",
        description="Configura tu voz de TTS preferida para todos los servidores.",
    )
    @app_commands.describe(voz="Identificador de la voz que deseas usar por defecto")
    @app_commands.autocomplete(voz=_voice_autocomplete)
    async def voz(
        self,
        interaction: discord.Interaction,
        voz: str,
    ) -> None:
        clean_voice = (voz or "").strip()
        if not clean_voice:
            await interaction.response.send_message(
                "Debes especificar una voz válida.",
                ephemeral=True,
            )
            return

        await set_tts_user_settings(interaction.user.id, voice_id=clean_voice)
        await interaction.response.send_message(
            f"✅ Tu voz de TTS preferida ahora es: `{clean_voice}`",
            ephemeral=True,
        )

    @tts_group.command(
        name="server",
        description="Configura la voz de TTS por defecto para este servidor.",
    )
    @app_commands.describe(voz="Voz por defecto para usuarios sin configuración propia")
    @app_commands.autocomplete(voz=_voice_autocomplete)
    async def server(
        self,
        interaction: discord.Interaction,
        voz: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo puede ejecutarse dentro de un servidor.",
                ephemeral=True,
            )
            return

        user = interaction.user
        perms = getattr(user, "guild_permissions", None)
        is_admin = bool(
            perms
            and (
                getattr(perms, "administrator", False)
                or getattr(perms, "manage_guild", False)
            )
        )
        if not is_admin:
            await interaction.response.send_message(
                "Necesitas el permiso de Administrador o Gestionar Servidor para usar este comando.",
                ephemeral=True,
            )
            return

        clean_voice = (voz or "").strip()
        if not clean_voice:
            await interaction.response.send_message(
                "Debes especificar una voz válida.",
                ephemeral=True,
            )
            return

        await set_tts_guild_settings(interaction.guild.id, default_voice=clean_voice)
        await interaction.response.send_message(
            f"✅ La voz de TTS por defecto para este servidor ahora es: `{clean_voice}`"
        )

    @tts_group.command(
        name="leave",
        description="Desconecta el bot del canal de voz y vacía la cola de reproducción.",
    )
    async def leave(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo puede ejecutarse en un servidor.",
                ephemeral=True,
            )
            return

        player = await self.tts_queue_manager.get_player(interaction.guild.id)
        await player.disconnect_and_clear()
        await interaction.response.send_message(
            "👋 Me he desconectado del canal de voz."
        )

    @tts_group.command(
        name="stop",
        description="Detiene la reproducción actual y vacía la cola de TTS.",
    )
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo puede ejecutarse en un servidor.",
                ephemeral=True,
            )
            return

        player = await self.tts_queue_manager.get_player(interaction.guild.id)
        await player.stop()
        await interaction.response.send_message(
            "🛑 Reproducción detenida y cola vaciada."
        )

    @tts_group.command(
        name="skip",
        description="Salta el audio que se está reproduciendo actualmente.",
    )
    async def skip(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo puede ejecutarse en un servidor.",
                ephemeral=True,
            )
            return

        player = await self.tts_queue_manager.get_player(interaction.guild.id)
        skipped = await player.skip()
        if skipped:
            await interaction.response.send_message("⏭️ Audio saltado.")
        else:
            await interaction.response.send_message(
                "No hay ningún audio reproduciéndose en este momento.",
                ephemeral=True,
            )

    @tts_group.command(
        name="channel",
        description="Configura o consulta el canal de Chat-to-Speech de este servidor.",
    )
    @app_commands.describe(
        canal="Canal de texto que el bot leerá en voz alta",
        activar="Activar o desactivar Chat-to-Speech",
        permitir_bots="Permitir que el bot lea mensajes de otros bots o webhooks",
        desvincular="Desvincular el canal actual de Chat-to-Speech",
    )
    async def channel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        activar: bool | None = None,
        permitir_bots: bool | None = None,
        desvincular: bool | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo puede ejecutarse dentro de un servidor.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if (
            canal is None
            and activar is None
            and permitir_bots is None
            and not desvincular
        ):
            settings = await get_tts_guild_settings(guild.id) or {}
            c_id = settings.get("chat_to_speech_channel_id")
            c_str = f"<#{c_id}>" if c_id else "Ninguno"
            enabled = settings.get("chat_to_speech_enabled", False)
            bots = settings.get("allow_bots", False)
            voice = settings.get("default_voice") or "es_002"

            status_msg = (
                "🎙️ **Estado de Chat-to-Speech en este servidor:**\n"
                f"• **Canal activo:** {c_str}\n"
                f"• **Estado:** {'✅ Activado' if enabled else '❌ Desactivado'}\n"
                f"• **Leer bots/webhooks:** {'Sí' if bots else 'No'}\n"
                f"• **Voz por defecto:** `{voice}`\n\n"
                "*(Usa `/tts channel canal:#nombre activar:True` o el panel `/settings` para modificarlo)*"
            )
            await interaction.response.send_message(status_msg, ephemeral=True)
            return

        user = interaction.user
        perms = getattr(user, "guild_permissions", None)
        is_admin = bool(
            perms
            and (
                getattr(perms, "administrator", False)
                or getattr(perms, "manage_guild", False)
            )
        )
        if not is_admin:
            await interaction.response.send_message(
                "Necesitas el permiso de Administrador o Gestionar Servidor para modificar Chat-to-Speech.",
                ephemeral=True,
            )
            return

        clear_channel = bool(desvincular)
        new_channel_id = canal.id if canal is not None else None
        new_enabled = activar
        if canal is not None and activar is None:
            new_enabled = True

        updated = await set_tts_guild_settings(
            guild_id=guild.id,
            chat_to_speech_channel_id=new_channel_id,
            chat_to_speech_enabled=new_enabled,
            allow_bots=permitir_bots,
            clear_chat_to_speech_channel=clear_channel,
        )

        c_id = updated.get("chat_to_speech_channel_id")
        c_str = f"<#{c_id}>" if c_id else "Ninguno"
        enabled = updated.get("chat_to_speech_enabled", False)
        bots = updated.get("allow_bots", False)

        resp = (
            "✅ **Configuración de Chat-to-Speech actualizada:**\n"
            f"• **Canal:** {c_str}\n"
            f"• **Estado:** {'✅ Activado' if enabled else '❌ Desactivado'}\n"
            f"• **Leer bots:** {'Sí' if bots else 'No'}"
        )
        await interaction.response.send_message(resp)

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

        # 2. Purgito solo procesa si está actualmente conectado a un canal de voz
        # NUNCA autoconectar por un mensaje de Chat-to-Speech
        vc = getattr(guild, "voice_client", None)
        if vc is None:
            return
        is_conn = getattr(vc, "is_connected", None)
        if callable(is_conn):
            if not is_conn():
                return
        elif not bool(is_conn):
            return

        # 3. Consultar configuración del servidor
        guild_settings = await get_tts_guild_settings(guild.id)
        if not guild_settings:
            return

        if not guild_settings.get("chat_to_speech_enabled", False):
            return

        target_channel_id = guild_settings.get("chat_to_speech_channel_id")
        channel = getattr(message, "channel", None)
        if (
            target_channel_id is None
            or getattr(channel, "id", None) != target_channel_id
        ):
            return

        # 4. Filtrar bots/webhooks según configuración del servidor
        author = getattr(message, "author", None)
        is_bot = bool(
            getattr(author, "bot", False) or getattr(message, "webhook_id", None)
        )
        if is_bot and not guild_settings.get("allow_bots", False):
            return

        # 5. Contenido del mensaje y prefijos de exclusión
        raw_content = (
            getattr(message, "clean_content", None)
            or getattr(message, "content", "")
            or ""
        )
        content = raw_content.strip()
        if not content:
            return

        # Ignorar mensajes que comienzan con prefijo de exclusión
        if content.startswith(("//", "\\\\", "/*")):
            return

        # 6. Detección de override explícito de voz: [voz_id] texto
        override_voice: str | None = None
        text_to_speak = content

        override_match = re.match(r"^\[([a-zA-Z0-9_\-]+)\]\s*(.*)$", content, re.DOTALL)
        if override_match:
            candidate_voice = override_match.group(1)
            remaining = override_match.group(2).strip()
            if remaining:
                override_voice = candidate_voice
                text_to_speak = remaining

        # 7. Truncar texto si excede el límite máximo configurado
        if len(text_to_speak) > self.tts_service.max_text_length:
            text_to_speak = text_to_speak[: self.tts_service.max_text_length].strip()

        if not text_to_speak:
            return

        # 8. Resolver voz y preferencias del usuario
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
