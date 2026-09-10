"""Gestor de colas FIFO por servidor para reproducción ordenada de TTS en Discord."""

import asyncio
import logging
import time
from dataclasses import dataclass

import discord

from tts.audio import create_discord_audio_source
from tts.errors import QueueFullError

log = logging.getLogger(__name__)


@dataclass
class TTSQueueItem:
    """Elemento individual en la cola de TTS de un servidor."""

    id: str
    guild_id: int
    text: str
    voice_id: str
    audio_path: str
    channel_id: int
    user_id: int
    created_at: float = 0.0


class GuildTTSPlayer:
    """Maneja la cola FIFO y el ciclo de reproducción de un servidor específico."""

    def __init__(
        self,
        guild_id: int,
        max_queue_size: int = 20,
        idle_timeout_seconds: float = 180.0,
    ) -> None:
        self.guild_id = guild_id
        self.max_queue_size = max_queue_size
        self.idle_timeout_seconds = idle_timeout_seconds
        self.queue: asyncio.Queue[TTSQueueItem] = asyncio.Queue(maxsize=max_queue_size)
        self.current_item: TTSQueueItem | None = None
        self.worker_task: asyncio.Task | None = None
        self.voice_client: discord.VoiceClient | None = None
        self._playback_done_event: asyncio.Event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def is_playing(self) -> bool:
        return (
            self.voice_client is not None
            and self.voice_client.is_connected()
            and (self.voice_client.is_playing() or self.current_item is not None)
        )

    def queue_size(self) -> int:
        return self.queue.qsize()

    async def enqueue(self, item: TTSQueueItem) -> None:
        """Añade un audio a la cola del servidor. Lanza QueueFullError si excede el límite."""
        if self.queue.qsize() >= self.max_queue_size:
            raise QueueFullError(
                f"La cola de TTS está llena ({self.max_queue_size} audios máximos)."
            )
        item.created_at = time.time()
        self.queue.put_nowait(item)
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(
                self._worker_loop(), name=f"tts-worker-{self.guild_id}"
            )

    async def skip(self) -> bool:
        """Detiene el audio actual para pasar inmediatamente al siguiente de la cola."""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
            return True
        return False

    async def stop(self) -> None:
        """Vacía la cola y detiene la reproducción actual."""
        # Vaciar cola
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except (asyncio.QueueEmpty, ValueError):
                break

        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()

    async def disconnect_and_clear(self) -> None:
        """Detiene reproducción, vacía cola y desconecta el VoiceClient."""
        self._closed = True
        await self.stop()
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

        if self.voice_client and self.voice_client.is_connected():
            try:
                await self.voice_client.disconnect(force=True)
            except Exception:
                log.warning(
                    "Error al desconectar VoiceClient del guild %s", self.guild_id
                )
        self.voice_client = None

    async def _worker_loop(self) -> None:
        """Worker FIFO dedicado exclusivamente a este servidor."""
        loop = asyncio.get_running_loop()
        log.debug("Iniciando worker de TTS para guild %s", self.guild_id)

        try:
            while not self._closed:
                try:
                    # Esperar siguiente elemento o desconectar tras timeout de inactividad
                    item = await asyncio.wait_for(
                        self.queue.get(), timeout=self.idle_timeout_seconds
                    )
                except asyncio.TimeoutError:
                    log.info(
                        "Cola de TTS inactiva por %.0fs en guild %s. Desconectando por inactividad.",
                        self.idle_timeout_seconds,
                        self.guild_id,
                    )
                    break

                self.current_item = item
                self._playback_done_event.clear()
                playback_error: Exception | None = None

                def _after_playback(err: Exception | None) -> None:
                    nonlocal playback_error
                    playback_error = err
                    loop.call_soon_threadsafe(self._playback_done_event.set)

                try:
                    vc = self.voice_client
                    if vc is None or not vc.is_connected():
                        log.warning(
                            "Guild %s: VoiceClient no conectado al iniciar item %s",
                            self.guild_id,
                            item.id,
                        )
                        continue

                    # Crear source de audio de discord con FFmpeg
                    source = create_discord_audio_source(item.audio_path)
                    vc.play(source, after=_after_playback)

                    # Esperar a que finalice la reproducción de este audio
                    await self._playback_done_event.wait()

                    if playback_error:
                        log.error(
                            "Error durante reproducción en guild %s: %s",
                            self.guild_id,
                            playback_error,
                        )

                except Exception:
                    log.exception(
                        "Error inesperado procesando audio TTS en guild %s",
                        self.guild_id,
                    )
                finally:
                    self.current_item = None
                    try:
                        self.queue.task_done()
                    except ValueError:
                        pass

        except asyncio.CancelledError:
            log.debug("Worker de TTS cancelado para guild %s", self.guild_id)
        finally:
            self.current_item = None
            if self.voice_client and self.voice_client.is_connected():
                try:
                    await self.voice_client.disconnect(force=True)
                except Exception:
                    pass
            self.voice_client = None


class TTSQueueManager:
    """Administrador global de colas por servidor."""

    def __init__(
        self,
        max_queue_size: int = 20,
        idle_timeout_seconds: float = 180.0,
    ) -> None:
        self.max_queue_size = max_queue_size
        self.idle_timeout_seconds = idle_timeout_seconds
        self.players: dict[int, GuildTTSPlayer] = {}
        self._lock = asyncio.Lock()

    async def get_player(self, guild_id: int) -> GuildTTSPlayer:
        """Obtiene o crea el reproductor dedicado para el servidor."""
        async with self._lock:
            player = self.players.get(guild_id)
            if player is None or player._closed:
                player = GuildTTSPlayer(
                    guild_id=guild_id,
                    max_queue_size=self.max_queue_size,
                    idle_timeout_seconds=self.idle_timeout_seconds,
                )
                self.players[guild_id] = player
            return player

    async def remove_player(self, guild_id: int) -> None:
        """Elimina y desconecta el reproductor de un servidor."""
        async with self._lock:
            player = self.players.pop(guild_id, None)
        if player is not None:
            await player.disconnect_and_clear()

    async def stop_all(self) -> None:
        """Detiene y desconecta todos los reproductores al cerrar el bot."""
        async with self._lock:
            current_players = list(self.players.values())
            self.players.clear()

        for player in current_players:
            try:
                await player.disconnect_and_clear()
            except Exception:
                log.exception(
                    "Error deteniendo reproductor de guild %s", player.guild_id
                )
