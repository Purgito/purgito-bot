"""Procesamiento y aplicación de filtros de audio con FFmpeg de forma asíncrona."""

import asyncio
import logging
import os
import shutil
import uuid

import discord

from tts.errors import AudioProcessingError

log = logging.getLogger(__name__)

SUPPORTED_FILTERS = {"normal", "nightcore", "vaporwave", "pitch", "speed"}


def build_atempo_chain(tempo: float) -> str:
    """Genera la cadena de filtros 'atempo' para cualquier velocidad positiva.

    FFmpeg restringe atempo a [0.5, 2.0]. Si el factor está fuera de rango,
    se encadenan múltiples filtros atempo.
    """
    if tempo <= 0:
        tempo = 1.0

    factors: list[float] = []
    remaining = tempo

    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5

    factors.append(remaining)
    return ",".join(f"atempo={f:.3f}" for f in factors)


def build_audio_filter_chain(
    filter_name: str,
    speed: float = 1.0,
    pitch: float = 1.0,
    sample_rate: int = 44100,
) -> str | None:
    """Construye la cadena de filtros de audio para FFmpeg (-af).

    Devuelve None si no se requiere ningún filtro (reproducción normal 1.0).
    """
    filter_name = (filter_name or "normal").lower().strip()
    filters: list[str] = []

    if filter_name == "nightcore":
        # Sube el tono y la velocidad 1.25x
        nc_rate = int(sample_rate * 1.25)
        filters.append(f"asetrate={nc_rate},aresample={sample_rate}")
        if speed != 1.0:
            filters.append(build_atempo_chain(speed))

    elif filter_name == "vaporwave":
        # Baja el tono y la velocidad 0.8x
        vw_rate = int(sample_rate * 0.8)
        filters.append(f"asetrate={vw_rate},aresample={sample_rate}")
        if speed != 1.0:
            filters.append(build_atempo_chain(speed))

    elif filter_name == "pitch":
        # Cambia el tono manteniendo la velocidad deseada
        effective_pitch = max(0.5, min(2.0, pitch))
        p_rate = int(sample_rate * effective_pitch)
        filters.append(f"asetrate={p_rate},aresample={sample_rate}")
        # Compensar velocidad para que solo cambie el tono
        tempo_comp = (1.0 / effective_pitch) * speed
        filters.append(build_atempo_chain(tempo_comp))

    elif filter_name == "speed":
        # Solo cambia velocidad
        effective_speed = max(0.25, min(3.0, speed))
        filters.append(build_atempo_chain(effective_speed))

    else:  # "normal"
        # Si se especificó pitch o speed customizado
        needs_pitch = abs(pitch - 1.0) > 0.01
        needs_speed = abs(speed - 1.0) > 0.01

        if needs_pitch:
            effective_pitch = max(0.5, min(2.0, pitch))
            p_rate = int(sample_rate * effective_pitch)
            filters.append(f"asetrate={p_rate},aresample={sample_rate}")
            tempo_comp = (1.0 / effective_pitch) * (speed if needs_speed else 1.0)
            filters.append(build_atempo_chain(tempo_comp))
        elif needs_speed:
            filters.append(build_atempo_chain(speed))

    return ",".join(filters) if filters else None


async def apply_audio_filters(
    input_path: str,
    output_path: str,
    filter_name: str = "normal",
    speed: float = 1.0,
    pitch: float = 1.0,
    timeout_seconds: float = 15.0,
) -> str:
    """Aplica los filtros de audio especificados mediante FFmpeg sin bloquear el event loop.

    Si no se requiere ningún filtro, copia el archivo directamente de forma atómica.
    """
    filter_chain = build_audio_filter_chain(filter_name, speed=speed, pitch=pitch)

    # Si no hay filtros que aplicar, simplemente copiar el archivo
    if not filter_chain:

        def _copy():
            temp_out = f"{output_path}.tmp.{uuid.uuid4().hex}"
            shutil.copyfile(input_path, temp_out)
            os.replace(temp_out, output_path)

        await asyncio.to_thread(_copy)
        return output_path

    temp_out = f"{output_path}.tmp.{uuid.uuid4().hex}"

    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        input_path,
        "-af",
        filter_chain,
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        temp_out,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )

        if proc.returncode != 0:
            err_msg = stderr_bytes.decode("utf-8", errors="replace").strip()
            if os.path.exists(temp_out):
                try:
                    os.remove(temp_out)
                except OSError:
                    pass
            raise AudioProcessingError(
                f"FFmpeg falló (código {proc.returncode}): {err_msg}"
            )

        os.replace(temp_out, output_path)
        return output_path

    except asyncio.TimeoutError as exc:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except OSError:
                pass
        raise AudioProcessingError(
            "Timeout durante el procesamiento de audio con FFmpeg"
        ) from exc
    except FileNotFoundError as exc:
        raise AudioProcessingError(
            "El binario 'ffmpeg' no se encuentra instalado o no está disponible en PATH"
        ) from exc
    except Exception as exc:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except OSError:
                pass
        if isinstance(exc, AudioProcessingError):
            raise
        raise AudioProcessingError(
            f"Error inesperado al ejecutar FFmpeg: {exc}"
        ) from exc


def create_discord_audio_source(file_path: str) -> discord.FFmpegPCMAudio:
    """Crea una fuente de audio para discord.VoiceClient."""
    return discord.FFmpegPCMAudio(
        file_path,
        options="-vn",
    )
