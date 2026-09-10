"""Tests para la funcionalidad de Chat-to-Speech pasivo inspirada en Wamellow para Purgito."""

import asyncio
from types import SimpleNamespace

import aiosqlite
import pytest

import db
from cogs.tts import TTS
from tts.errors import ProviderError, QueueFullError
from tts.service import TTSService


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


class MockVoiceChannel:
    """Mock de canal de voz con método connect()."""

    def __init__(self, id: int = 55555, name: str = "General"):
        self.id = id
        self.name = name
        self.connect_called = False

    async def connect(self, timeout: float = 10.0, reconnect: bool = True):
        self.connect_called = True
        return MockVoiceClient(connected=True, channel=self)


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
        author_in_voice: bool = False,
        voice_channel=None,
    ):
        vc = MockVoiceClient(connected=voice_connected) if voice_connected else None
        self.guild = (
            SimpleNamespace(id=guild_id, name="Test Guild", voice_client=vc)
            if guild_id is not None
            else None
        )
        self.channel = SimpleNamespace(id=channel_id, name="tts-chat")
        v_chan = voice_channel or (MockVoiceChannel() if author_in_voice else None)
        self.author = SimpleNamespace(
            id=user_id,
            name="TestUser",
            bot=is_bot,
            voice=SimpleNamespace(channel=v_chan) if v_chan else None,
        )
        self.content = content
        self.clean_content = content
        self.webhook_id = webhook_id


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


# 1. Canal configurado → entra a cola
def test_chat_to_speech_configured_channel_enqueues(memory_db, monkeypatch):
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


# 2. Canal no configurado (NULL) → ignorado
def test_chat_to_speech_no_channel_configured_ignored(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345

        # No se ha configurado ningún canal (chat_to_speech_channel_id es None)
        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=None,
            chat_to_speech_enabled=False,
        )

        msg = MockMessage(
            content="Mensaje en canal no configurado",
            guild_id=guild_id,
            channel_id=1001,
        )
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 3. Mensaje en otro canal → ignorado
def test_chat_to_speech_other_channel_ignored(memory_db, monkeypatch):
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
        )  # Canal distinto
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 4. Disabled/no channel → ignorado
def test_chat_to_speech_disabled_or_no_channel_ignored(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        # Caso A: chat_to_speech_enabled = False
        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=False,
        )

        msg_a = MockMessage(content="Hola A", guild_id=guild_id, channel_id=channel_id)
        await cog.on_message(msg_a)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        # Caso B: settings inexistentes en BD (None)
        msg_b = MockMessage(content="Hola B", guild_id=99999, channel_id=channel_id)
        await cog.on_message(msg_b)

        player_b = await cog.tts_queue_manager.get_player(99999)
        assert player_b.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 5. Mensaje de bot/webhook ignorado por defecto
def test_chat_to_speech_bot_webhook_ignored_by_default(memory_db, monkeypatch):
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

        # Mensaje de bot
        bot_msg = MockMessage(
            content="Mensaje de bot",
            guild_id=guild_id,
            channel_id=channel_id,
            is_bot=True,
        )
        await cog.on_message(bot_msg)

        # Mensaje de webhook
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


# 6. Allow_bots=true → procesado
def test_chat_to_speech_allow_bots_true_processed(memory_db, monkeypatch):
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


# 7a. Bot no conectado + autor en canal de voz → se conecta automáticamente y reproduce
def test_chat_to_speech_auto_connects_when_author_in_voice(memory_db, monkeypatch):
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

        v_chan = MockVoiceChannel(id=7777, name="General")
        msg = MockMessage(
            content="Hola auto-connect",
            guild_id=guild_id,
            channel_id=channel_id,
            voice_connected=False,  # Purgito NO está conectado inicialmente
            voice_channel=v_chan,  # Autor SÍ está en canal de voz
        )

        await cog.on_message(msg)

        assert v_chan.connect_called is True
        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.text == "Hola auto-connect"

        await cog.cog_unload()

    asyncio.run(_test())


# 7b. Bot no conectado + autor FUERA de cualquier canal de voz → ignorar (no conectar ni sintetizar)
def test_chat_to_speech_ignored_when_author_not_in_voice(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        synthesize_called = False

        async def fake_synthesize(text, voice_id, **kwargs):
            nonlocal synthesize_called
            synthesize_called = True
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        # Autor NO está en ningún canal de voz (author.voice = None)
        msg = MockMessage(
            content="Hola sin voz",
            guild_id=guild_id,
            channel_id=channel_id,
            voice_connected=False,
            author_in_voice=False,
        )

        await cog.on_message(msg)

        assert synthesize_called is False
        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 7c. Bot YA conectado a voz → reutiliza la conexión existente
def test_chat_to_speech_reuses_existing_voice_connection(memory_db, monkeypatch):
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

        # Bot YA conectado a voz
        msg = MockMessage(
            content="Hola con bot ya conectado",
            guild_id=guild_id,
            channel_id=channel_id,
            voice_connected=True,
            author_in_voice=False,  # Incluso si el autor no tiene voice_state, usa la conexión activa
        )

        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 1
        item = player.queue.get_nowait()
        assert item.text == "Hola con bot ya conectado"

        await cog.cog_unload()

    asyncio.run(_test())


# 8. Mensaje demasiado largo → truncado según política
def test_chat_to_speech_message_too_long_truncated(memory_db, monkeypatch):
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

        long_content = "Z" * (cog.tts_service.max_text_length + 100)
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
        assert synthesized_text == "Z" * cog.tts_service.max_text_length

        await cog.cog_unload()

    asyncio.run(_test())


# 9. Prefijo de exclusión (//, \\, /*) → ignorado
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


# 10. Preferencia personal → aplicada
def test_chat_to_speech_personal_preference_applied(memory_db, monkeypatch):
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
            content="Hola con mi voz personal",
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


# 11. Preferencia guild → aplicada si no existe personal
def test_chat_to_speech_guild_preference_applied_if_no_personal(memory_db, monkeypatch):
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


# 12. Fallback global
def test_chat_to_speech_fallback_global(memory_db, monkeypatch):
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
            content="Hola fallback global",
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


# 13. Mismo TTSService que el pipeline TTS existente
def test_chat_to_speech_uses_same_tts_service(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 12345
        channel_id = 1001

        assert isinstance(cog.tts_service, TTSService)

        await db.set_tts_guild_settings(
            guild_id=guild_id,
            chat_to_speech_channel_id=channel_id,
            chat_to_speech_enabled=True,
        )

        used_service = None

        async def fake_synthesize(text, voice_id, **kwargs):
            nonlocal used_service
            used_service = cog.tts_service
            return "audio.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        msg = MockMessage(
            content="Mensaje C2S",
            guild_id=guild_id,
            channel_id=channel_id,
        )
        await cog.on_message(msg)

        assert used_service is cog.tts_service

        await cog.cog_unload()

    asyncio.run(_test())


# 14. Provider error → on_message continúa
def test_chat_to_speech_provider_error_continues(memory_db, monkeypatch):
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

        # No debe propagar excepción ni crashear el listener
        await cog.on_message(msg)

        player = await cog.tts_queue_manager.get_player(guild_id)
        assert player.queue_size() == 0

        await cog.cog_unload()

    asyncio.run(_test())


# 15. Queue overflow → on_message continúa
def test_chat_to_speech_queue_overflow_continues(memory_db, monkeypatch):
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

        # No debe propagar excepción
        await cog.on_message(msg)

        await cog.cog_unload()

    asyncio.run(_test())


# 16. Override explícito de voz en el mensaje: [voz_id] texto
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


# 17. Integración en /settings con TTSCategory
def test_settings_tts_category_panel(memory_db):
    async def _test():
        from cogs.settings import SettingsPanel, TTSCategory

        guild_id = 77777
        guild = SimpleNamespace(id=guild_id, name="Test Guild", text_channels=[])
        panel = SettingsPanel(guild=guild, locale="es", invoker_id=123)

        category = TTSCategory()

        # 1. Embed cuando no hay canal configurado
        embed_before = await category.build_embed(panel)
        assert "Desactivado" in embed_before.description

        # 2. Configurar canal
        items = await category.build_items(panel)
        chan_select = items[0]
        fake_chan_obj = SimpleNamespace(id=8888)
        chan_select._values = [fake_chan_obj]

        async def fake_edit(**kw):
            pass

        fake_interaction = SimpleNamespace(
            guild=guild,
            user=SimpleNamespace(id=123),
            response=SimpleNamespace(
                is_done=lambda: True,
                edit_message=fake_edit,
            ),
            edit_original_response=fake_edit,
        )
        await chan_select.callback(fake_interaction)

        settings = await db.get_tts_guild_settings(guild_id)
        assert settings["chat_to_speech_channel_id"] == 8888
        assert settings["chat_to_speech_enabled"] is True

        embed_after = await category.build_embed(panel)
        assert "Activo" in embed_after.description
        assert "<#8888>" in embed_after.description

        # 3. Toggle bots
        items_active = await category.build_items(panel)
        bots_btn = items_active[1]
        await bots_btn.callback(fake_interaction)

        settings_bots = await db.get_tts_guild_settings(guild_id)
        assert settings_bots["allow_bots"] is True

        # 4. Desvincular / Desactivar canal
        items_with_clear = await category.build_items(panel)
        clear_btn = items_with_clear[2]
        await clear_btn.callback(fake_interaction)

        settings_cleared = await db.get_tts_guild_settings(guild_id)
        assert settings_cleared["chat_to_speech_channel_id"] is None

        embed_final = await category.build_embed(panel)
        assert "Desactivado" in embed_final.description

    asyncio.run(_test())
