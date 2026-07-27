"""Test de MusicPlayer.cleanup() (music_player.py): discord.py llama al
after-callback tanto en un fin de canción natural como en un stop() manual, así
que cleanup() debe evitar que ese callback tardío reprograme _advance() (que
mandaba un segundo embed de "cola vacía" después del de /stop o /leave) y debe
cancelar cualquier prefetch en curso en vez de dejarlo huérfano."""

import asyncio
from unittest.mock import MagicMock

from music_player import MusicPlayer


class _FakeVoiceClient:
    def __init__(self):
        self.stopped = False
        self.disconnected = False

    def is_playing(self):
        return True

    def is_paused(self):
        return False

    def is_connected(self):
        return not self.disconnected

    def stop(self):
        self.stopped = True

    async def disconnect(self):
        self.disconnected = True


def test_cleanup_clears_loop_so_late_after_callback_is_a_noop(monkeypatch):
    player = MusicPlayer(guild_id=1)
    player.voice_client = _FakeVoiceClient()
    player._loop = object()  # simula un event loop activo, como en producción

    scheduler = MagicMock()
    monkeypatch.setattr("music_player.asyncio.run_coroutine_threadsafe", scheduler)

    asyncio.run(player.cleanup())

    assert player._loop is None
    player._after(None)  # el after-callback que discord.py dispara tras stop()
    scheduler.assert_not_called()


def test_cleanup_cancels_pending_prefetch_task():
    player = MusicPlayer(guild_id=1)
    player.voice_client = _FakeVoiceClient()
    task = MagicMock()
    player._bg_tasks.add(task)

    asyncio.run(player.cleanup())

    task.cancel.assert_called_once()
