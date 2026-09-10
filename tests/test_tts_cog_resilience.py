"""Tests de resiliencia del Cog TTS: asegura que ningún error tumbe el bot o el loop."""

import asyncio
from types import SimpleNamespace

import aiosqlite
import pytest

import db
from cogs.tts import TTS
from tts.errors import (
    AudioProcessingError,
    ProviderError,
    QueueFullError,
)


class MockInteraction:
    """Mock completo de discord.Interaction para comandos slash."""

    def __init__(
        self,
        guild_id: int = 12345,
        user_id: int = 67890,
        in_voice: bool = True,
        is_admin: bool = False,
    ) -> None:
        self.guild = SimpleNamespace(id=guild_id, name="Test Guild", voice_client=None)

        voice_channel = (
            SimpleNamespace(id=55555, connect=self._fake_connect) if in_voice else None
        )
        self.user = SimpleNamespace(
            id=user_id,
            name="TestUser",
            voice=SimpleNamespace(channel=voice_channel) if in_voice else None,
            guild_permissions=SimpleNamespace(
                administrator=is_admin, manage_guild=is_admin
            ),
        )
        self.channel_id = 99999
        self.response = SimpleNamespace(
            send_message=self._fake_send_message,
            defer=self._fake_defer,
            is_done=lambda: self._deferred or self._responded,
        )
        self.followup = SimpleNamespace(send=self._fake_followup_send)

        self._deferred = False
        self._responded = False
        self.sent_messages: list[tuple[str, bool]] = []  # (content, ephemeral)
        self.followup_messages: list[tuple[str, bool]] = []

    async def _fake_send_message(self, content=None, ephemeral=False, **kwargs):
        self._responded = True
        self.sent_messages.append((content, ephemeral))

    async def _fake_defer(self, ephemeral=False):
        self._deferred = True

    async def _fake_followup_send(self, content=None, ephemeral=False, **kwargs):
        self.followup_messages.append((content, ephemeral))

    async def _fake_connect(self, timeout=10.0, reconnect=True):
        vc = SimpleNamespace(
            is_connected=lambda: True,
            is_playing=lambda: False,
            channel=self.user.voice.channel,
            play=lambda src, after=None: after(None) if after else None,
            stop=lambda: None,
            disconnect=self._fake_disconnect,
        )
        self.guild.voice_client = vc
        return vc

    async def _fake_disconnect(self, force=True):
        self.guild.voice_client = None


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


def test_decir_user_not_in_voice(memory_db):
    async def _test():
        cog = TTS(SimpleNamespace())
        interaction = MockInteraction(in_voice=False)

        # Usuario no está en canal de voz -> debe avisar con mensaje efímero y continuar vivo
        await cog.decir.callback(cog, interaction, texto="Hola")

        assert len(interaction.sent_messages) == 1
        msg, ephemeral = interaction.sent_messages[0]
        assert "canal de voz" in msg
        assert ephemeral is True

        await cog.cog_unload()

    asyncio.run(_test())


def test_decir_empty_text_and_too_long(memory_db):
    async def _test():
        cog = TTS(SimpleNamespace())

        # Texto vacío
        interaction_empty = MockInteraction(in_voice=True)
        await cog.decir.callback(cog, interaction_empty, texto="   ")
        assert "vacío" in interaction_empty.sent_messages[0][0]

        # Texto demasiado largo
        interaction_long = MockInteraction(in_voice=True)
        long_text = "a" * (cog.tts_service.max_text_length + 50)
        await cog.decir.callback(cog, interaction_long, texto=long_text)
        assert "demasiado largo" in interaction_long.sent_messages[0][0]

        await cog.cog_unload()

    asyncio.run(_test())


def test_decir_resilience_on_synthesis_failure(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        interaction = MockInteraction(in_voice=True)

        # Simular fallo total del servicio de síntesis
        async def fake_synthesize(*args, **kwargs):
            raise ProviderError("Todos los proveedores fallaron")

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        # El comando no debe crashear ni propagar excepción no controlada
        await cog.decir.callback(cog, interaction, texto="Prueba de fallo")

        # Se envió mensaje de error controlado al usuario
        assert len(interaction.followup_messages) == 1
        msg, ephemeral = interaction.followup_messages[0]
        assert "problema" in msg.lower() or "error" in msg.lower()

        await cog.cog_unload()

    asyncio.run(_test())


def test_decir_resilience_on_ffmpeg_failure(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        interaction = MockInteraction(in_voice=True)

        async def fake_synthesize(*args, **kwargs):
            raise AudioProcessingError("FFmpeg corrupt stream")

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        await cog.decir.callback(cog, interaction, texto="Fallo de FFmpeg")

        assert len(interaction.followup_messages) == 1
        msg, ephemeral = interaction.followup_messages[0]
        assert "problema" in msg.lower() or "error" in msg.lower()

        await cog.cog_unload()

    asyncio.run(_test())


def test_decir_resilience_on_queue_full(memory_db, monkeypatch):
    async def _test():
        cog = TTS(SimpleNamespace())
        interaction = MockInteraction(in_voice=True)

        async def fake_synthesize(*args, **kwargs):
            return "fake_path.mp3"

        monkeypatch.setattr(cog.tts_service, "synthesize_speech", fake_synthesize)

        player = await cog.tts_queue_manager.get_player(interaction.guild.id)

        async def fake_enqueue(item):
            raise QueueFullError("Cola llena")

        monkeypatch.setattr(player, "enqueue", fake_enqueue)

        await cog.decir.callback(cog, interaction, texto="Cola saturada")

        assert len(interaction.followup_messages) == 1
        msg, ephemeral = interaction.followup_messages[0]
        assert "Cola llena" in msg

        await cog.cog_unload()

    asyncio.run(_test())


def test_tts_server_permissions_check(memory_db):
    async def _test():
        cog = TTS(SimpleNamespace())

        # Usuario sin permisos de admin/manage_guild
        interaction_user = MockInteraction(is_admin=False)
        await cog.server.callback(cog, interaction_user, voz="es_002")
        assert len(interaction_user.sent_messages) == 1
        msg, ephemeral = interaction_user.sent_messages[0]
        assert "permiso" in msg.lower()
        assert ephemeral is True

        # Usuario con permisos de admin
        interaction_admin = MockInteraction(is_admin=True)
        await cog.server.callback(cog, interaction_admin, voz="es_male_m3")
        assert len(interaction_admin.sent_messages) == 1
        msg2, _ = interaction_admin.sent_messages[0]
        assert "es_male_m3" in msg2

        await cog.cog_unload()

    asyncio.run(_test())


def test_tts_voz_command(memory_db):
    async def _test():
        cog = TTS(SimpleNamespace())
        interaction = MockInteraction(user_id=777)

        await cog.voz.callback(cog, interaction, voz="es_female_f6")
        assert len(interaction.sent_messages) == 1
        msg, ephemeral = interaction.sent_messages[0]
        assert "es_female_f6" in msg
        assert ephemeral is True

        # Comprobar persistencia
        settings = await db.get_tts_user_settings(777)
        assert settings["voice_id"] == "es_female_f6"

        await cog.cog_unload()

    asyncio.run(_test())


def test_leave_stop_skip_commands(memory_db):
    async def _test():
        cog = TTS(SimpleNamespace())
        guild_id = 888

        # Leave
        inter_leave = MockInteraction(guild_id=guild_id)
        await cog.leave.callback(cog, inter_leave)
        assert "desconectado" in inter_leave.sent_messages[0][0]

        # Stop
        inter_stop = MockInteraction(guild_id=guild_id)
        await cog.stop.callback(cog, inter_stop)
        assert "detenida" in inter_stop.sent_messages[0][0]

        # Skip cuando no hay nada reproduciendo
        inter_skip = MockInteraction(guild_id=guild_id)
        await cog.skip.callback(cog, inter_skip)
        assert "No hay ningún audio" in inter_skip.sent_messages[0][0]

        await cog.cog_unload()

    asyncio.run(_test())
