"""Tests exhaustivos del TTSService: resolución de voz, circuit breaker, caché y fallbacks."""

import asyncio
import os
import shutil
import tempfile

import aiosqlite
import pytest

import db
from tts.cache import TTSCache
from tts.circuit_breaker import CircuitBreaker, CircuitState
from tts.errors import (
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from tts.providers.base import BaseTTSProvider
from tts.service import TTSService


class DummyTTSProvider(BaseTTSProvider):
    """Mock configurable de proveedor TTS para tests."""

    def __init__(self, name: str = "mock", supports_all: bool = True) -> None:
        self.name = name
        self.supports_all = supports_all
        self.call_count = 0
        self.last_text: str | None = None
        self.last_voice: str | None = None
        self.fail_with: Exception | None = None
        self.return_bytes = b"fake-audio-mp3-data"

    def supports_voice(self, voice_id: str) -> bool:
        if self.supports_all:
            return True
        return voice_id.startswith("tiktok_")

    def get_available_voices(self) -> dict[str, str]:
        return {"mock_voice": "Mock Voice"}

    async def synthesize(self, text: str, voice_id: str) -> bytes:
        self.call_count += 1
        self.last_text = text
        self.last_voice = voice_id
        if self.fail_with is not None:
            raise self.fail_with
        return self.return_bytes


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


@pytest.fixture
def temp_cache():
    tmp_dir = tempfile.mkdtemp(prefix="tts_cache_test_")
    cache = TTSCache(cache_dir=tmp_dir, max_size_bytes=1024 * 1024, ttl_seconds=3600)
    yield cache
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── 1. Resolución de voz (usuario > guild > global & override explícito) ─────


def test_voice_resolution_hierarchy(memory_db):
    async def _test():
        tiktok_mock = DummyTTSProvider("tiktok")
        edge_mock = DummyTTSProvider("edge")
        service = TTSService(tiktok_provider=tiktok_mock, edge_provider=edge_mock)

        user_id = 11111
        guild_id = 22222

        # 1. Sin preferencias: devuelve default global
        assert (
            await service.resolve_voice(user_id=user_id, guild_id=guild_id)
            == TTSService.DEFAULT_GLOBAL_VOICE
        )

        # 2. Solo preferencia del servidor
        await db.set_tts_guild_settings(guild_id, default_voice="es_server_voice")
        assert (
            await service.resolve_voice(user_id=user_id, guild_id=guild_id)
            == "es_server_voice"
        )

        # 3. Preferencia de usuario pisa a la del servidor
        await db.set_tts_user_settings(user_id, voice_id="es_user_voice")
        assert (
            await service.resolve_voice(user_id=user_id, guild_id=guild_id)
            == "es_user_voice"
        )

        # 4. Override explícito del comando pisa a usuario, servidor y default global
        assert (
            await service.resolve_voice(
                command_voice="override_voice", user_id=user_id, guild_id=guild_id
            )
            == "override_voice"
        )

    asyncio.run(_test())


# ─── 2. Cache Key y Cache Hit/Miss ──────────────────────────────────────────


def test_cache_key_parameters_sensitivity():
    # Parámetros idénticos -> mismo hash
    k1 = TTSCache.compute_key("auto", "es_002", "Hola mundo", 1.0, 1.0, "normal")
    k2 = TTSCache.compute_key("auto", "es_002", "Hola mundo", 1.0, 1.0, "normal")
    assert k1 == k2

    # Variación de texto -> distinto hash
    assert k1 != TTSCache.compute_key(
        "auto", "es_002", "Otro texto", 1.0, 1.0, "normal"
    )

    # Variación de voz -> distinto hash
    assert k1 != TTSCache.compute_key(
        "auto", "es_male_m3", "Hola mundo", 1.0, 1.0, "normal"
    )

    # Variación de speed -> distinto hash
    assert k1 != TTSCache.compute_key(
        "auto", "es_002", "Hola mundo", 1.25, 1.0, "normal"
    )

    # Variación de pitch -> distinto hash
    assert k1 != TTSCache.compute_key(
        "auto", "es_002", "Hola mundo", 1.0, 1.2, "normal"
    )

    # Variación de filtro -> distinto hash
    assert k1 != TTSCache.compute_key(
        "auto", "es_002", "Hola mundo", 1.0, 1.0, "nightcore"
    )

    # Variación de provider -> distinto hash
    assert k1 != TTSCache.compute_key(
        "edge", "es_002", "Hola mundo", 1.0, 1.0, "normal"
    )

    # Variación de formato -> distinto hash
    assert k1 != TTSCache.compute_key(
        "auto", "es_002", "Hola mundo", 1.0, 1.0, "normal", audio_format="opus"
    )

    # Variación de filter_params -> distinto hash
    assert k1 != TTSCache.compute_key(
        "auto",
        "es_002",
        "Hola mundo",
        1.0,
        1.0,
        "normal",
        filter_params={"cutoff": 500},
    )


def test_cache_hit_and_miss(temp_cache, monkeypatch):
    async def _test():
        tiktok_mock = DummyTTSProvider("tiktok")
        edge_mock = DummyTTSProvider("edge")
        service = TTSService(
            cache=temp_cache, tiktok_provider=tiktok_mock, edge_provider=edge_mock
        )

        # Evitar llamar a ffmpeg real en este test mockeando apply_audio_filters
        async def fake_filters(input_path, output_path, **kwargs):
            shutil.copyfile(input_path, output_path)
            return output_path

        import tts.service as s_mod

        monkeypatch.setattr(s_mod, "apply_audio_filters", fake_filters)

        # 1er llamado: MISS -> llama a TikTok y guarda en caché
        path1 = await service.synthesize_speech("Test de cache", "es_002")
        assert os.path.exists(path1)
        assert tiktok_mock.call_count == 1

        # 2do llamado con idénticos parámetros: HIT -> devuelve archivo sin llamar a proveedor
        path2 = await service.synthesize_speech("Test de cache", "es_002")
        assert path1 == path2
        assert tiktok_mock.call_count == 1  # No se incrementó

    asyncio.run(_test())


# ─── 3. Fallback: TikTok Timeout / Error -> Edge ────────────────────────────


def test_tiktok_timeout_fallback_to_edge(temp_cache, monkeypatch):
    async def _test():
        tiktok_mock = DummyTTSProvider("tiktok")
        tiktok_mock.fail_with = ProviderTimeoutError("TikTok timeout")
        edge_mock = DummyTTSProvider("edge")
        edge_mock.return_bytes = b"edge-fallback-audio"

        service = TTSService(
            cache=temp_cache, tiktok_provider=tiktok_mock, edge_provider=edge_mock
        )

        async def fake_filters(input_path, output_path, **kwargs):
            shutil.copyfile(input_path, output_path)
            return output_path

        import tts.service as s_mod

        monkeypatch.setattr(s_mod, "apply_audio_filters", fake_filters)

        # La síntesis no debe fallar, debe caer a Edge
        audio_path = await service.synthesize_speech("Prueba timeout", "es_002")
        assert os.path.exists(audio_path)
        # Se intentó TikTok (1 intento + 1 retry)
        assert tiktok_mock.call_count >= 1
        # Se llamó a Edge como fallback exitoso
        assert edge_mock.call_count == 1

        # Comprobar que el circuit breaker registró el fallo
        assert service.circuit_breaker.failure_count == 1

    asyncio.run(_test())


# ─── 4. Circuit Breaker: 429, OPEN state, saltar TikTok y recuperación ──────


def test_tiktok_429_circuit_breaker_flow(temp_cache, monkeypatch):
    async def _test():
        tiktok_mock = DummyTTSProvider("tiktok")
        tiktok_mock.fail_with = ProviderRateLimitError("TikTok 429")
        edge_mock = DummyTTSProvider("edge")

        breaker = CircuitBreaker(
            name="tiktok", failure_threshold=3, reset_timeout=0.2
        )  # 200ms para test rápido
        service = TTSService(
            cache=temp_cache,
            tiktok_provider=tiktok_mock,
            edge_provider=edge_mock,
            circuit_breaker=breaker,
        )

        async def fake_filters(input_path, output_path, **kwargs):
            shutil.copyfile(input_path, output_path)
            return output_path

        import tts.service as s_mod

        monkeypatch.setattr(s_mod, "apply_audio_filters", fake_filters)

        # Fallo 1
        await service.synthesize_speech("Texto 1", "es_002")
        assert breaker.failure_count == 1
        assert breaker.state == CircuitState.CLOSED

        # Fallo 2
        await service.synthesize_speech("Texto 2", "es_002")
        assert breaker.failure_count == 2
        assert breaker.state == CircuitState.CLOSED

        # Fallo 3 -> Pasa a OPEN
        await service.synthesize_speech("Texto 3", "es_002")
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open() is True

        calls_before = tiktok_mock.call_count

        # Solicitud mientras breaker está OPEN -> NO debe llamar a TikTok en lo absoluto
        await service.synthesize_speech("Texto 4", "es_002")
        assert tiktok_mock.call_count == calls_before  # No se tocó TikTok
        assert edge_mock.call_count == 4  # Edge atendió la solicitud

        # Esperar que expire el reset_timeout de 200ms
        await asyncio.sleep(0.25)

        # Ahora el breaker debe permitir un probe en HALF_OPEN
        # Si TikTok se recupera (quitamos el fail_with):
        tiktok_mock.fail_with = None
        await service.synthesize_speech("Texto 5", "es_002")

        # TikTok atendió la llamada de prueba exitosamente
        assert tiktok_mock.call_count == calls_before + 1
        # El circuito se recuperó a CLOSED
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    asyncio.run(_test())


# ─── 5. Proveedor completamente caído ───────────────────────────────────────


def test_all_providers_down(temp_cache):
    async def _test():
        tiktok_mock = DummyTTSProvider("tiktok")
        tiktok_mock.fail_with = ProviderError("TikTok down")
        edge_mock = DummyTTSProvider("edge")
        edge_mock.fail_with = ProviderError("Edge down")

        service = TTSService(
            cache=temp_cache, tiktok_provider=tiktok_mock, edge_provider=edge_mock
        )

        with pytest.raises(ProviderError):
            await service.synthesize_speech("Ambos caídos", "es_002")

    asyncio.run(_test())
