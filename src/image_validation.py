"""Validación de imágenes recibidas de Discord, compartida por los filtros de imagen
(`cogs/imagefx.py`, `image_filters.py`)."""

import io

from PIL import Image

# Rechaza imágenes descomprimidas gigantes (decompression bomb) antes de procesarlas.
Image.MAX_IMAGE_PIXELS = 15_000_000

# formats= restringe qué decoder de Pillow llega a tocar los bytes. Sin esto,
# Image.open() prueba TODOS los formatos que Pillow sabe leer (TIFF, ICO, EPS -- que
# puede shellear a Ghostscript --, PCX, etc.) contra el contenido de un adjunto de
# Discord con la extensión falseada: cualquiera puede subir un .png que en realidad es
# otra cosa, y el nombre de archivo nunca llega hasta acá (Image.open ve puros bytes).
# Nada de esto depende de que el paquete tenga un CVE conocido -- es reducir qué
# parsers de Pillow quedan expuestos a bytes no confiables, conocido o no.
_ALLOWED_FORMATS = ("PNG", "JPEG", "WEBP")


def is_valid_image(data: bytes) -> bool:
    """Verifica que los bytes sean una imagen real (no solo por extensión)
    antes de persistirlos: Image.verify() decodifica el header y rechaza
    contenido corrupto o que no sea una imagen. MAX_IMAGE_PIXELS (arriba)
    también aplica acá, así que un decompression bomb también cae."""
    try:
        with Image.open(io.BytesIO(data), formats=_ALLOWED_FORMATS) as img:
            img.verify()
        return True
    except Exception:
        return False
