"""Auditoría sección Dependencias/supply chain, ronda 2: los dos puntos que
decodifican bytes no confiables con Pillow (meme_generator.is_valid_image,
alimentado por adjuntos de Discord con extensión falseable, y
r2.compute_phash, alimentado por contenido de una URL de host confiable pero
no de contenido garantizado) restringen `Image.open(..., formats=...)` al
allowlist real en vez de dejar que Pillow pruebe cualquier decoder que sepa
leer (TIFF, ICO, EPS -- puede shellear a Ghostscript --, etc.).
"""

import io

import pytest
from PIL import Image

import meme_generator
import r2


def _encode(fmt: str, mode: str = "RGB", size=(4, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color=(1, 2, 3) if mode == "RGB" else 1).save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_is_valid_image_acepta_los_formatos_permitidos(fmt):
    assert meme_generator.is_valid_image(_encode(fmt)) is True


def test_is_valid_image_rechaza_un_formato_real_pero_no_permitido():
    """BMP es una imagen perfectamente válida para Pillow -- lo que prueba
    que el rechazo viene de formats=, no de que el archivo esté corrupto."""
    assert meme_generator.is_valid_image(_encode("BMP")) is False


def test_is_valid_image_rechaza_contenido_no_imagen():
    assert meme_generator.is_valid_image(b"no es una imagen") is False


def test_compute_phash_acepta_gif():
    assert r2.compute_phash(_encode("GIF", mode="P")) is not None


def test_compute_phash_rechaza_un_formato_real_pero_no_gif():
    assert r2.compute_phash(_encode("PNG")) is None
