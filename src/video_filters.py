"""Conversión de video a GIF (comando "!gif" / "purgito gif") vía el binario
de ffmpeg que empaqueta imageio-ffmpeg -- no depende de que el server tenga
ffmpeg instalado (ver comentario junto al pin en requirements.txt).

A diferencia de image_filters.py (Pillow puro, bytes -> bytes en memoria),
acá hace falta un archivo real en disco: ffmpeg no acepta bytes crudos por
stdin de forma confiable para todos los contenedores de video que puede
subir alguien a Discord."""

import os
import shutil
import subprocess
import tempfile

import imageio_ffmpeg

_FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

# Timeout del proceso de ffmpeg -- si un video corrupto o un contenedor raro
# lo cuelga, esto evita que un solo !gif deje un proceso zombie consumiendo
# CPU indefinidamente.
_FFMPEG_TIMEOUT_SECONDS = 30


class VideoConversionFailed(Exception):
    """El archivo no es un video que ffmpeg pueda decodificar, o el proceso
    falló/se colgó."""


class GifTooLarge(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


def convert_video_to_gif(
    video_bytes: bytes,
    max_seconds: float,
    max_output_bytes: int,
    fps: int = 12,
    width: int = 380,
) -> bytes:
    """Bloqueante -- se corre en un thread aparte (ver cogs/imagefx.py).
    Trunca a los primeros `max_seconds` del video. El filtergraph
    palettegen/paletteuse es más caro que un scale a secas pero da GIFs
    bastante mejores (sin el banding de una paleta genérica de 256 colores
    fija) -- para clips cortos de pocos segundos el costo extra es chico."""
    tmp_dir = tempfile.mkdtemp(prefix="purgito_gif_")
    in_path = os.path.join(tmp_dir, "input")
    out_path = os.path.join(tmp_dir, "output.gif")
    try:
        with open(in_path, "wb") as f:
            f.write(video_bytes)

        filtergraph = (
            f"fps={fps},scale={width}:-2:flags=lanczos,"
            "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
        )
        cmd = [
            _FFMPEG_EXE,
            "-y",
            "-t",
            str(max_seconds),
            "-i",
            in_path,
            "-vf",
            filtergraph,
            "-loop",
            "0",
            out_path,
        ]
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=_FFMPEG_TIMEOUT_SECONDS,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise VideoConversionFailed(str(e)) from e

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise VideoConversionFailed("archivo vacío o no generado")
        if os.path.getsize(out_path) > max_output_bytes:
            raise GifTooLarge(max_output_bytes)

        with open(out_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
