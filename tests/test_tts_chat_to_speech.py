"""Tests para la funcionalidad de Chat-to-Speech inspirada en Wamellow para Purgito."""

import asyncio
from types import SimpleNamespace

import aiosqlite
import pytest

import db
from cogs.tts import TTS
from tts.errors import ProviderError, QueueFullError


class MockVoiceClient:
    """Mock de VoiceClient conectado."""

    def __init__(self, connected: bool = True, channel=None):
        self._connected = connected
        self.channel = channel or SimpleNamespace(id=55555, name="voice-chan")

    def is_connected(self) -> bool:
        return self._connected

    def is_playing(self) -> bool:
        return False

    def play(self, source, after=None):
        if after:
            after(None)

    def stop(self):
        pass

    async def disconnect(self, force=True):
        self._connected = False


class MockMessage:
    """Mock completo de discord.Message."""

    def __init__(
        self,
        content: str,
        guild_id: int = 12345,
        channel_id: int = 1001,
        user_id: int = 67890,
        is_bot: bool = False,
        webhook_id: int | None = None,
        voice_connected: bool = True,
    ):
        vc = MockVoiceClient(connected=voice_connected) if voice_connected else None
        self.guild = (
            SimpleNamespace(id=guild_id, name="Test Guild", voice_client=vc)
            if guild_id is not None
            else None
        )
        self.channel = SimpleNamespace(id=channel_id, name="tts-chat")
        self.author = SimpleNamespace(id=user_id, name="TestUser", bot=is_bot)
        self.content = content
        self.clean_content = content
        self.webhook_id = webhook_id


class MockInteraction:
    """Mock de discord.Interaction para comandos slash de configuración."""

    def __init__(
        self,
        guild_id: int = 12345,
        user_id: int = 67890,
        is_admin: bool = True,
    ):
        self.guild = SimpleNamespace(id=guild_id, name="Test Guild")
        self.user = SimpleNamespace(
            id=user_id,
            name="AdminUser",
            guild_permissions=SimpleNamespace(
                administrator=is_admin, manage_guild=is_admin
            ),
        )
        self.sent_messages: list[tuple[str, bool]] = []
        self.response = SimpleNamespace(send_message=self._fake_send_message)

    async def _fake_send_message(self, content=None, ephemeral=False, **kwargs):
        self.sent_messages.append((str(content), ephemeral))


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


# 1. Mensaje en canal configurado -> entra a cola
def test_chat_to_speech_message_in_configured_channel_enqueues(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        async def fake_synthesize(text, voice_id, **kwargs):
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        msg = MockMessage(
            content="Hola a todos", guild_id=guild_id, channel_id=channel_id
        )
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.text == "Hola a todos"
        assert item.channel_id == channel_id

        await cog.cog_unload()

    asyncio.run(_test())


# 2. Mensaje en otro canal -> ignorado
def test_chat_to_speech_message_in_other_channel_ignored(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        msg = MockMessage(
            content="Hola", guild_id=guild_id, channel_id=9999
        )  # Otro canal
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 3. TTS desactivado en el guild -> ignorado
def test_chat_to_speech_disabled_ignored(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=False,  # Desactivado
        )

        msg = MockMessage(content="Hola", guild_id=guild_id, channel_id=channel_id)
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 4. Mensaje de bot/webhook ignorado por defecto
def test_chat_to_speech_bot_ignored_by_default(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
            allow_bots=False,
        )

        # Mensaje de un bot
        bot_msg = MockMessage(
            content="Mensaje de bot",
            guild_id=guild_id,
            channel_id=channel_id,
            is_bot=True,
        )
        await cog.on_message(bot_msg)

        # Mensaje de un webhook
        webhook_msg = MockMessage(
            content="Mensaje de webhook",
            guild_id=guild_id,
            channel_id=channel_id,
            webhook_id=8888,
        )
        await cog.on_message(webhook_msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 5. Mensaje de bot procesado si allow_bots=True
def test_chat_to_speech_bot_processed_when_allow_bots_true(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
            allow_bots=True,
        )

        async def fake_synthesize(text, voice_id, **kwargs):
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        bot_msg = MockMessage(
            content="Bot hablando",
            guild_id=guild_id,
            channel_id=channel_id,
            is_bot=True,
        )
        await cog.on_message(bot_msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.text == "Bot hablando"

        await cog.cog_unload()

    asyncio.run(_test())


# 6. Sin voice connection activa -> ignorado (no auto-connect)
def test_chat_to_speech_no_voice_connection_ignored(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        # 1. voice_client es None
        msg1 = MockMessage(
            content="Nadie en voz",
            guild_id=guild_id,
            channel_id=channel_id,
            voice_connected=False,
        )
        await cog.on_message(msg1)

        # 2. voice_client existe pero no está conectado
        disconnected_vc = MockVoiceClient(connected=False)
        msg2 = MockMessage(
            content="Desconectado",
            guild_id=guild_id,
            channel_id=channel_id,
            voice_connected=False,
        )
        msg2.guild.voice_client = disconnected_vc
        await cog.on_message(msg2)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 7. Mensaje demasiado largo -> truncado según política
def test_chat_to_speech_text_truncated(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        synthesized_text = None

        async def fake_synthesize(text, voice_id, **kwargs):
            nonlocal synthesized_text
            synthesized_text = text
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        # Texto que excede el límite
        long_content = "X" * (cog.tts_service.max_text_length + 100)
        msg = MockMessage(
            content=long_content,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert len(item.text) == cog.tts_service.max_text_length
        assert synthesized_text == "X" * cog.tts_service.max_text_length

        await cog.cog_unload()

    asyncio.run(_test())


# 8. Prefijo de exclusión (//, \\, /*) -> ignorado
def test_chat_to_speech_exclusion_prefix_ignored(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        for prefix in ("//", "\\\\", "/*", "  // con espacios"):
            msg = MockMessage(
                content=f"{prefix} este mensaje no debe sonar",
                guild_id=guild_id,
                channel_id=channel_id,
            )
            await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 9. Voz personal del autor aplicada
def test_chat_to_speech_personal_voice_applied(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001
        user_id = 4444

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
            default_voice="es_002",
        )
        await db.set_tts_user_settings(user_id=user_id, voice_id="es_female_f6")

        async def fake_synthesize(text, voice_id, **kwargs):
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        msg = MockMessage(
            content="Hola con mi voz",
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
        )
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.voice_id == "es_female_f6"

        await cog.cog_unload()

    asyncio.run(_test())


# 10. Voz del guild aplicada si el usuario no tiene override
def test_chat_to_speech_guild_voice_applied(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001
        user_id = 5555

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
            default_voice="es-MX-JorgeNeural",
        )

        async def fake_synthesize(text, voice_id, **kwargs):
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        msg = MockMessage(
            content="Hola con voz del servidor",
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
        )
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.voice_id == "es-MX-JorgeNeural"

        await cog.cog_unload()

    asyncio.run(_test())


# 11. Fallback global
def test_chat_to_speech_global_voice_fallback(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
            default_voice=None,
        )

        async def fake_synthesize(text, voice_id, **kwargs):
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        msg = MockMessage(
            content="Hola global",
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=6666,
        )
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.voice_id == cog.tts_service.DEFAULT_GLOBAL_VOICE

        await cog.cog_unload()

    asyncio.run(_test())


# 12. Chat-to-Speech y /tts decir reutilizan el mismo TTSService
def test_chat_to_speech_and_decir_share_same_service_and_queue(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        called_with_services = []

        async def fake_synthesize(text, voice_id, **kwargs):
            called_with_services.append(cog.tts_service)
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        # 1. Chat-to-Speech message
        msg = MockMessage(
            content="Mensaje C2S",
            guild_id=guild_id,
            channel_id=channel_id,
        )

        player = await cog.tts_queue_manager.get_player(guild_id)
        enqueued_items = []

        async def spy_enqueue(item):
            enqueued_items.append(item)
            # No delegar al worker de audio para evitar llamadas a ffmpeg en test
            player.queue.put_nowait(item)

        monkeypatch.setattr(player, "enqueue", spy_enqueue)

        await cog.on_message(msg)

        # 2. /tts decir command
        from test_tts_cog_resilience import MockInteraction

        interaction = MockInteraction(guild_id=guild_id, in_voice=True)
        # Apuntar el mock voice client y canal del interaction al mismo
        interaction.guild.voice_client = msg.guild.voice_client
        interaction.user.voice.channel = msg.guild.voice_client.channel
        await cog.decir.callback(cog, interaction, texto="Mensaje Slash")

        assert len(enqueued_items) == 2
        assert len(called_with_services) == 2
        assert called_with_services[0] is called_with_services[1]
        assert called_with_services[0] is cog.tts_service

        # Verificar orden FIFO
        assert enqueued_items[0].text == "Mensaje C2S"
        assert enqueued_items[1].text == "Mensaje Slash"

        await cog.cog_unload()

    asyncio.run(_test())


# 13. Errores del provider no rompen el listener de on_message
def test_chat_to_speech_provider_error_does_not_break_listener(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        async def fake_synthesize(text, voice_id, **kwargs):
            raise ProviderError("Proveedor caído")

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        msg = MockMessage(
            content="Prueba de fallo del proveedor",
            guild_id=guild_id,
            channel_id=channel_id,
        )

        # No debe lanzar excepción
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 14. Queue overflow no rompe el listener
def test_chat_to_speech_queue_overflow_does_not_break_listener(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        async def fake_synthesize(text, voice_id, **kwargs):
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        player = await cog.tts_queue_manager.get_player(guild_id)

        async def fake_enqueue(item):
            raise QueueFullError("Cola saturada")

        monkeypatch.setattr(player, "enqueue", fake_enqueue)

        msg = MockMessage(
            content="Mensaje con cola llena",
            guild_id=guild_id,
            channel_id=channel_id,
        )

        # No debe lanzar excepción
        await cog.on_message(msg)

        await cog.cog_unload()

    asyncio.run(_test())


# 15. Override explícito de voz en el mensaje: [voz_id] texto
def test_chat_to_speech_explicit_voice_override_tag(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
            default_voice="es_002",
        )

        async def fake_synthesize(text, voice_id, **kwargs):
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        msg = MockMessage(
            content="[en_us_002] Hello world from tag",
            guild_id=guild_id,
            channel_id=channel_id,
        )
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.voice_id == "en_us_002"
        assert item.text == "Hello world from tag"

        await cog.cog_unload()

    asyncio.run(_test())


# 16. Slash command /tts channel consulta y modificación
def test_tts_channel_command(memory_db):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345

        # 1. Consulta inicial de estado
        inter_query = MockInteraction(guild_id=guild_id, is_admin=False)
        await cog.channel.callback(cog, inter_query)
        assert len(inter_query.sent_messages) == 1
        assert "Estado de Chat-to-Speech" in inter_query.sent_messages[0][0]

        # 2. Modificación sin permisos
        fake_chan = SimpleNamespace(id=2002, name="general")
        inter_no_perm = MockInteraction(guild_id=guild_id, is_admin=False)
        await cog.channel.callback(cog, inter_no_perm, canal=fake_chan)
        assert "permiso" in inter_no_perm.sent_messages[0][0].lower()

        # 3. Modificación con permisos de admin
        inter_admin = MockInteraction(guild_id=guild_id, is_admin=True)
        await cog.channel.callback(
            cog,
            inter_admin,
            canal=fake_chan,
            activar=True,
            permitir_bots=True,
        )
        assert "actualizada" in inter_admin.sent_messages[0][0].lower()

        # Verificar en base de datos
        settings = await db.get_tts_guild_settings(guild_id)
        assert settings["chat_to_speech_channel_id"] == 2002
        assert settings["chat_to_speech_enabled"] is True
        assert settings["allow_bots"] is True

        # 4. Desvincular canal
        inter_unlink = MockInteraction(guild_id=guild_id, is_admin=True)
        await cog.channel.callback(cog, inter_unlink, desvincular=True)
        settings_after = await db.get_tts_guild_settings(guild_id)
        assert settings_after["chat_to_speech_channel_id"] is None

        await cog.cog_unload()

    asyncio.run(_test())
