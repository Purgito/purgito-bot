"""Tests para el módulo de audio y procesamiento con FFmpeg (filtros, errores, cleanup)."""

import asyncio
import os
import tempfile

import pytest

from tts.audio import (
    apply_audio_filters,
    build_atempo_chain,
    build_audio_filter_chain,
)
from tts.errors import AudioProcessingError


def test_build_atempo_chain():
    # Velocidad estándar 1.0
    assert build_atempo_chain(1.0) == "atempo=1.000"

    # Velocidad moderada 1.5
    assert build_atempo_chain(1.5) == "atempo=1.500"

    # Velocidad extrema > 2.0 encadena filtros atempo
    chain_fast = build_atempo_chain(3.0)
    assert "atempo=2.000" in chain_fast
    assert "atempo=1.500" in chain_fast

    # Velocidad lenta < 0.5 encadena filtros atempo
    chain_slow = build_atempo_chain(0.2)
    assert "atempo=0.500" in chain_slow


def test_build_audio_filter_chain_presets():
    # Normal 1.0 -> None (no requiere proceso ffmpeg)
    assert build_audio_filter_chain("normal", speed=1.0, pitch=1.0) is None

    # Nightcore -> asetrate alto
    nc = build_audio_filter_chain("nightcore")
    assert nc is not None
    assert "asetrate=55125" in nc
    assert "aresample=44100" in nc

    # Vaporwave -> asetrate bajo
    vw = build_audio_filter_chain("vaporwave")
    assert vw is not None
    assert "asetrate=35280" in vw
    assert "aresample=44100" in vw

    # Pitch solo -> asetrate + compensación atempo
    p = build_audio_filter_chain("pitch", pitch=1.2)
    assert p is not None
    assert "asetrate=52920" in p
    assert "atempo=" in p

    # Speed solo -> atempo
    sp = build_audio_filter_chain("speed", speed=1.5)
    assert sp is not None
    assert "atempo=1.500" in sp


def test_ffmpeg_error_handling(monkeypatch):
    async def _test():
        tmp_in = tempfile.mktemp(suffix=".mp3")
        tmp_out = tempfile.mktemp(suffix=".mp3")
        with open(tmp_in, "wb") as f:
            f.write(b"dummy")

        # Simular fallo de FFmpeg con código de retorno != 0
        class MockProc:
            returncode = 1

            async def communicate(self):
                return b"", b"Invalid audio data or corrupted stream"

        async def fake_exec(*args, **kwargs):
            return MockProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        with pytest.raises(AudioProcessingError) as exc_info:
            await apply_audio_filters(
                input_path=tmp_in,
                output_path=tmp_out,
                filter_name="nightcore",
            )

        assert "FFmpeg falló" in str(exc_info.value)
        # Asegurar que el archivo temporal no quedó huérfano
        assert not os.path.exists(tmp_out)

        if os.path.exists(tmp_in):
            os.remove(tmp_in)

    asyncio.run(_test())


def test_ffmpeg_timeout_handling(monkeypatch):
    async def _test():
        tmp_in = tempfile.mktemp(suffix=".mp3")
        tmp_out = tempfile.mktemp(suffix=".mp3")
        with open(tmp_in, "wb") as f:
            f.write(b"dummy")

        class HangingProc:
            returncode = None

            async def communicate(self):
                await asyncio.sleep(10.0)
                return b"", b""

        async def fake_exec(*args, **kwargs):
            return HangingProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        with pytest.raises(AudioProcessingError) as exc_info:
            await apply_audio_filters(
                input_path=tmp_in,
                output_path=tmp_out,
                filter_name="vaporwave",
                timeout_seconds=0.1,  # 100ms para disparar timeout inmediato
            )

        assert "Timeout" in str(exc_info.value)

        if os.path.exists(tmp_in):
            os.remove(tmp_in)

    asyncio.run(_test())
