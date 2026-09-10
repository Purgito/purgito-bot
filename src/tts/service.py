"""Servicio principal de TTS: orquestación de proveedores, circuit breaker, caché y filtros."""

import asyncio
import logging
import os
import tempfile
import uuid
from typing import ClassVar

from db import get_tts_guild_settings, get_tts_user_settings
from tts.audio import apply_audio_filters
from tts.cache import TTSCache
from tts.circuit_breaker import CircuitBreaker
from tts.errors import (
    CircuitBreakerOpenError,
    InvalidInputError,
    ProviderError,
    TTSError,
)
from tts.providers.base import BaseTTSProvider
from tts.providers.edge import EdgeTTSProvider
from tts.providers.tiktok import TikTokTTSProvider

log = logging.getLogger(__name__)


class TTSService:
    """Orquestador de síntesis de voz."""

    DEFAULT_GLOBAL_VOICE: ClassVar[str] = "es_002"

    def __init__(
        self,
        cache: TTSCache | None = None,
        tiktok_provider: BaseTTSProvider | None = None,
        edge_provider: BaseTTSProvider | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        max_concurrent_generations: int = 3,
        max_text_length: int = 300,
    ) -> None:
        self.cache = cache or TTSCache()
        self.tiktok_provider = tiktok_provider or TikTokTTSProvider()
        self.edge_provider = edge_provider or EdgeTTSProvider()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name="tiktok", failure_threshold=3, reset_timeout=60.0
        )
        self.semaphore = asyncio.Semaphore(max_concurrent_generations)
        self.max_text_length = max_text_length

    async def resolve_voice(
        self,
        command_voice: str | None = None,
        user_id: int | None = None,
        guild_id: int | None = None,
    ) -> str:
        """Resuelve la voz efectiva según el orden de prioridad estricto:

        1. Override explícito del comando
        2. Preferencia del usuario
        3. Preferencia del servidor (guild)
        4. Default global ("es_002")
        """
        # 1. Override explícito del comando
        if command_voice and command_voice.strip():
            return command_voice.strip()

        # 2. Preferencia del usuario
        if user_id is not None:
            try:
                user_settings = await get_tts_user_settings(user_id)
                if user_settings and user_settings.get("voice_id"):
                    return str(user_settings["voice_id"]).strip()
            except Exception:
                log.exception(
                    "Error consultando tts_user_settings para usuario %s", user_id
                )

        # 3. Preferencia del servidor
        if guild_id is not None:
            try:
                guild_settings = await get_tts_guild_settings(guild_id)
                if guild_settings and guild_settings.get("default_voice"):
                    return str(guild_settings["default_voice"]).strip()
            except Exception:
                log.exception(
                    "Error consultando tts_guild_settings para guild %s", guild_id
                )

        # 4. Default global
        return self.DEFAULT_GLOBAL_VOICE

    async def resolve_user_settings(self, user_id: int) -> dict:
        """Obtiene la configuración completa de filtros del usuario."""
        try:
            settings = await get_tts_user_settings(user_id)
            if settings:
                return {
                    "filter": settings.get("filter") or "normal",
                    "speed": float(settings.get("speed") or 1.0),
                    "pitch": float(settings.get("pitch") or 1.0),
                }
        except Exception:
            log.exception("Error leyendo ajustes de usuario %s", user_id)
        return {"filter": "normal", "speed": 1.0, "pitch": 1.0}

    def get_available_voices(self) -> dict[str, str]:
        """Devuelve todas las voces conocidas combinando TikTok y Edge."""
        voices = dict(self.tiktok_provider.get_available_voices())
        voices.update(self.edge_provider.get_available_voices())
        return voices

    async def synthesize_speech(
        self,
        text: str,
        voice_id: str,
        filter_name: str = "normal",
        speed: float = 1.0,
        pitch: float = 1.0,
    ) -> str:
        """Sintetiza texto y aplica filtros, utilizando caché y fallback inteligente.

        Devuelve la ruta absoluta al archivo de audio generado o recuperado de la caché.
        """
        clean_text = (text or "").strip()
        if not clean_text:
            raise InvalidInputError("El texto no puede estar vacío.")

        if len(clean_text) > self.max_text_length:
            raise InvalidInputError(
                f"El texto excede el límite permitido de {self.max_text_length} caracteres "
                f"(longitud actual: {len(clean_text)})."
            )

        filter_params = {"speed": speed, "pitch": pitch}

        # 1. Comprobar si ya existe en caché (clave SHA-256 de parámetros efectivos)
        cache_key = self.cache.compute_key(
            provider="auto",
            voice=voice_id,
            text=clean_text,
            speed=speed,
            pitch=pitch,
            filter_name=filter_name,
            filter_params=filter_params,
            audio_format="mp3",
        )

        cached_path = await self.cache.get(cache_key, audio_format="mp3")
        if cached_path:
            log.debug("TTS Cache HIT para key %s", cache_key)
            return cached_path

        log.debug("TTS Cache MISS para key %s", cache_key)

        # 2. Generación con concurrencia acotada mediante semáforo
        async with self.semaphore:
            # Doble chequeo tras esperar el semáforo
            cached_path = await self.cache.get(cache_key, audio_format="mp3")
            if cached_path:
                return cached_path

            raw_audio = await self._synthesize_with_fallback(clean_text, voice_id)

            # 3. Aplicar filtros con FFmpeg
            temp_dir = tempfile.gettempdir()
            raw_temp = os.path.join(temp_dir, f"tts_raw_{uuid.uuid4().hex}.mp3")
            filtered_temp = os.path.join(temp_dir, f"tts_filt_{uuid.uuid4().hex}.mp3")

            try:

                def _write_raw():
                    with open(raw_temp, "wb") as f:
                        f.write(raw_audio)

                await asyncio.to_thread(_write_raw)

                # Procesar filtros
                await apply_audio_filters(
                    input_path=raw_temp,
                    output_path=filtered_temp,
                    filter_name=filter_name,
                    speed=speed,
                    pitch=pitch,
                )

                # 4. Guardar archivo final en caché
                final_path = await self.cache.put_file(
                    cache_key=cache_key,
                    source_path=filtered_temp,
                    audio_format="mp3",
                )
                return final_path

            finally:
                for p in (raw_temp, filtered_temp):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass

    async def _synthesize_with_fallback(self, text: str, voice_id: str) -> bytes:
        """Intenta sintetizar con TikTok respetando el Circuit Breaker; si falla, cae a Edge-TTS."""
        # Si la voz es explícitamente exclusiva de Edge (ej: es-ES-AlvaroNeural), usar Edge directo
        if not self.tiktok_provider.supports_voice(voice_id):
            log.debug("Voz %s no es de TikTok. Usando Edge-TTS directamente.", voice_id)
            return await self.edge_provider.synthesize(text, voice_id)

        # Verificar disponibilidad del circuit breaker para TikTok
        can_call_tiktok = False
        try:
            await self.circuit_breaker.check_available()
            can_call_tiktok = True
        except CircuitBreakerOpenError as exc:
            log.warning(
                "Circuit breaker abierto para TikTok (%s). Usando fallback Edge-TTS.",
                exc,
            )

        if can_call_tiktok:
            try:
                # Intento con TikTok
                audio_bytes = await self._call_tiktok_with_retry(text, voice_id)
                await self.circuit_breaker.record_success()
                return audio_bytes

            except InvalidInputError:
                # Errores permanentes de entrada (no cuentan como fallos del proveedor)
                raise
            except ProviderError as exc:
                # Fallo del proveedor TikTok -> Registrar fallo en circuit breaker y fallback
                log.warning(
                    "Fallo en proveedor primario TikTok (%s: %s). Cayendo a Edge-TTS.",
                    type(exc).__name__,
                    exc,
                )
                await self.circuit_breaker.record_failure()
            except Exception:
                log.exception(
                    "Excepción inesperada en TikTok. Registrando fallo y usando fallback Edge-TTS."
                )
                await self.circuit_breaker.record_failure()

        # Fallback a Edge-TTS
        log.info(
            "Sintetizando con proveedor de fallback Edge-TTS para voz %s", voice_id
        )
        try:
            return await self.edge_provider.synthesize(text, voice_id)
        except Exception as exc:
            log.error("Fallback Edge-TTS también falló: %s", exc)
            if isinstance(exc, TTSError):
                raise
            raise ProviderError(
                f"Todos los proveedores de TTS fallaron: {exc}"
            ) from exc

    async def _call_tiktok_with_retry(
        self, text: str, voice_id: str, max_retries: int = 1
    ) -> bytes:
        """Ejecuta la llamada a TikTok con retry limitado y backoff corto."""
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await self.tiktok_provider.synthesize(text, voice_id)
            except InvalidInputError:
                # No reintentar entradas inválidas
                raise
            except (ProviderError, Exception) as exc:
                last_exc = exc
                if attempt < max_retries:
                    backoff = 0.5 * (2**attempt)
                    await asyncio.sleep(backoff)

        assert last_exc is not None
        raise last_exc
