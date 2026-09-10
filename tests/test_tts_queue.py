"""Tests para el gestor de colas de TTS (FIFO, aislamiento entre guilds, overflow, busy)."""

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

from tts.errors import QueueFullError
from tts.queue_manager import GuildTTSPlayer, TTSQueueItem, TTSQueueManager


class MockVoiceClient:
    """Mock de discord.VoiceClient para probar reproducción y callbacks."""

    def __init__(self, guild_id: int, play_delay: float = 0.05) -> None:
        self.guild = SimpleNamespace(id=guild_id)
        self.play_delay = play_delay
        self._connected = True
        self._playing = False
        self.played_paths: list[str] = []
        self._current_after = None

    def is_connected(self) -> bool:
        return self._connected

    def is_playing(self) -> bool:
        return self._playing

    def play(self, source, *, after=None) -> None:
        self._playing = True
        self._current_after = after

        async def _finish_playback():
            await asyncio.sleep(self.play_delay)
            self._playing = False
            if self._current_after:
                cb = self._current_after
                self._current_after = None
                cb(None)

        asyncio.create_task(_finish_playback())

    def stop(self) -> None:
        self._playing = False
        if self._current_after:
            cb = self._current_after
            self._current_after = None
            cb(None)

    async def disconnect(self, force: bool = True) -> None:
        self._connected = False
        self.stop()


@pytest.fixture
def fake_audio_file():
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix="fake_audio_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(b"mock-audio-content")
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_queue_fifo_order_per_guild(fake_audio_file, monkeypatch):
    async def _test():
        # Mock create_discord_audio_source para no llamar a ffmpeg
        import tts.queue_manager as qm_mod

        monkeypatch.setattr(qm_mod, "create_discord_audio_source", lambda p: p)

        guild_id = 1001
        player = GuildTTSPlayer(
            guild_id=guild_id, max_queue_size=10, idle_timeout_seconds=5.0
        )
        vc = MockVoiceClient(guild_id=guild_id, play_delay=0.08)
        player.voice_client = vc

        order_played: list[str] = []

        def track_play(source, *, after=None):
            order_played.append(source)
            vc._playing = True
            vc._current_after = after

            async def _done():
                await asyncio.sleep(vc.play_delay)
                vc._playing = False
                if vc._current_after:
                    cb = vc._current_after
                    vc._current_after = None
                    cb(None)

            asyncio.create_task(_done())

        vc.play = track_play

        # Encolar 3 audios en orden: A, B, C
        itemA = TTSQueueItem("idA", guild_id, "Texto A", "es_002", "audio_A.mp3", 1, 1)
        itemB = TTSQueueItem("idB", guild_id, "Texto B", "es_002", "audio_B.mp3", 1, 1)
        itemC = TTSQueueItem("idC", guild_id, "Texto C", "es_002", "audio_C.mp3", 1, 1)

        await player.enqueue(itemA)
        await player.enqueue(itemB)
        await player.enqueue(itemC)

        # Esperar a que se procesen los 3 elementos
        await asyncio.sleep(0.35)

        # Verificar orden estricto FIFO
        assert order_played == ["audio_A.mp3", "audio_B.mp3", "audio_C.mp3"]

        await player.disconnect_and_clear()

    asyncio.run(_test())


def test_isolation_between_guilds(fake_audio_file, monkeypatch):
    async def _test():
        import tts.queue_manager as qm_mod

        monkeypatch.setattr(qm_mod, "create_discord_audio_source", lambda p: p)

        manager = TTSQueueManager(max_queue_size=10)

        # Guild 1 con reproducción lenta
        player1 = await manager.get_player(111)
        vc1 = MockVoiceClient(111, play_delay=0.25)
        player1.voice_client = vc1

        # Guild 2 con reproducción rápida
        player2 = await manager.get_player(222)
        vc2 = MockVoiceClient(222, play_delay=0.04)
        player2.voice_client = vc2

        g2_completed = []

        def track_play2(source, *, after=None):
            g2_completed.append(source)
            vc2._playing = True

            async def _done():
                await asyncio.sleep(vc2.play_delay)
                vc2._playing = False
                if after:
                    after(None)

            asyncio.create_task(_done())

        vc2.play = track_play2

        # Encolar item lento en Guild 1
        item1 = TTSQueueItem("id1", 111, "Lento G1", "es_002", "g1_slow.mp3", 1, 1)
        await player1.enqueue(item1)

        # Encolar 2 items rápidos en Guild 2
        item2A = TTSQueueItem("id2A", 222, "Rápido 1", "es_002", "g2_fast1.mp3", 2, 2)
        item2B = TTSQueueItem("id2B", 222, "Rápido 2", "es_002", "g2_fast2.mp3", 2, 2)
        await player2.enqueue(item2A)
        await player2.enqueue(item2B)

        # Guild 2 debe terminar antes de que Guild 1 termine su único item lento
        await asyncio.sleep(0.12)
        assert len(g2_completed) == 2
        assert (
            vc1.is_playing() is True
        )  # Guild 1 sigue reproduciéndose independientemente

        await manager.stop_all()

    asyncio.run(_test())


def test_queue_overflow():
    async def _test():
        player = GuildTTSPlayer(guild_id=333, max_queue_size=2)
        vc = MockVoiceClient(333, play_delay=1.0)
        player.voice_client = vc

        # Llenar la cola (capacidad 2)
        item1 = TTSQueueItem("1", 333, "T1", "es_002", "1.mp3", 1, 1)
        item2 = TTSQueueItem("2", 333, "T2", "es_002", "2.mp3", 1, 1)
        await player.enqueue(item1)
        await player.enqueue(item2)

        # El 3er item excede la capacidad de 2 -> QueueFullError
        item3 = TTSQueueItem("3", 333, "T3", "es_002", "3.mp3", 1, 1)
        with pytest.raises(QueueFullError):
            await player.enqueue(item3)

        await player.disconnect_and_clear()

    asyncio.run(_test())


def test_voice_client_busy_and_skip(monkeypatch):
    async def _test():
        import tts.queue_manager as qm_mod

        monkeypatch.setattr(qm_mod, "create_discord_audio_source", lambda p: p)

        player = GuildTTSPlayer(guild_id=444, max_queue_size=5)
        vc = MockVoiceClient(444, play_delay=0.5)
        player.voice_client = vc

        item = TTSQueueItem("1", 444, "Audio largo", "es_002", "audio.mp3", 1, 1)
        await player.enqueue(item)

        await asyncio.sleep(0.05)
        # VoiceClient está reproduciendo
        assert player.is_playing is True

        # Skip interrumpe y libera
        skipped = await player.skip()
        assert skipped is True

        await asyncio.sleep(0.05)
        assert vc.is_playing() is False

        await player.disconnect_and_clear()

    asyncio.run(_test())


def test_stop_empties_queue_and_stops_playback(monkeypatch):
    async def _test():
        import tts.queue_manager as qm_mod

        monkeypatch.setattr(qm_mod, "create_discord_audio_source", lambda p: p)

        player = GuildTTSPlayer(guild_id=555, max_queue_size=10)
        vc = MockVoiceClient(555, play_delay=1.0)
        player.voice_client = vc

        await player.enqueue(TTSQueueItem("1", 555, "T1", "es_002", "1.mp3", 1, 1))
        await player.enqueue(TTSQueueItem("2", 555, "T2", "es_002", "2.mp3", 1, 1))
        await player.enqueue(TTSQueueItem("3", 555, "T3", "es_002", "3.mp3", 1, 1))

        await asyncio.sleep(0.05)
        assert player.queue_size() == 2

        await player.stop()

        # Cola vacía y playback detenido
        assert player.queue_size() == 0
        assert vc.is_playing() is False

        await player.disconnect_and_clear()

    asyncio.run(_test())
