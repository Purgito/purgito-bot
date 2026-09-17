"""Filtros de imagen tipo NotSoBot (Fase 1): transformaciones Pillow puras
sobre bytes de una imagen ya resuelta. La resolución de la fuente (adjunto,
mensaje respondido o avatar) vive en cogs/imagefx.py -- este módulo no sabe
nada de discord.py."""

import io
import os
import textwrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from meme_generator import _ALLOWED_FORMATS

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONT_PATH = os.path.join(_BASE_DIR, "assets", "Impact.ttf")


def _open(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes), formats=_ALLOWED_FORMATS)
    if hasattr(img, "n_frames") and img.n_frames > 1:
        img.seek(0)
    return img


def _open_rgb(image_bytes: bytes) -> Image.Image:
    return _open(image_bytes).convert("RGB")


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _draw_outlined_text(img: Image.Image, text: str, position: str) -> None:
    """Dibuja `text` en Impact blanco con borde negro, arriba o abajo de
    `img` (modifica `img` in place). Mismo algoritmo de ajuste de tamaño de
    fuente que meme_generator.render_meme, pero sin su lógica de split por
    conectores ("PERO"/"CUANDO"/etc.) -- esa existe para repartir un caption
    autogenerado en una sola oración entre arriba/abajo, y acá el usuario ya
    especifica cada parte explícitamente."""
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size
    padding_h = int(img_w * 0.05)
    usable_w = img_w - 2 * padding_h
    font_size = max(28, img_w // 10)
    font = None
    lines: list[str] = []

    while font_size >= 18:
        f = ImageFont.truetype(_FONT_PATH, font_size)
        avg_char_w = max(1, f.getlength("A"))
        chars_per_line = max(1, int(usable_w / avg_char_w))
        wrapped = textwrap.wrap(text, width=chars_per_line) or [text[:chars_per_line]]
        if all(f.getlength(line) <= usable_w for line in wrapped):
            font = f
            lines = wrapped
            break
        font_size -= 2

    if font is None:
        font_size = 18
        font = ImageFont.truetype(_FONT_PATH, font_size)
        avg_char_w = max(1, font.getlength("A"))
        chars_per_line = max(1, int(usable_w / avg_char_w))
        lines = textwrap.wrap(text, width=chars_per_line) or [text]

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    total_h = len(lines) * line_h
    margin = int(img_h * 0.03)
    y = margin if position == "top" else img_h - total_h - margin
    stroke = max(2, font_size // 12)

    for line in lines:
        line_w = font.getlength(line)
        x = int((img_w - line_w) / 2)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0),
        )
        y += line_h


def caption(image_bytes: bytes, text: str) -> bytes:
    """`text` puede traer "arriba|abajo"; sin "|" todo va arriba."""
    img = _open_rgb(image_bytes)
    top, _, bottom = text.upper().partition("|")
    top, bottom = top.strip(), bottom.strip()
    if top:
        _draw_outlined_text(img, top, "top")
    if bottom:
        _draw_outlined_text(img, bottom, "bottom")
    return _png_bytes(img)


def deepfry(image_bytes: bytes) -> bytes:
    from PIL import ImageEnhance

    img = _open_rgb(image_bytes)
    img = ImageEnhance.Color(img).enhance(2.5)
    img = ImageEnhance.Contrast(img).enhance(1.6)
    img = ImageEnhance.Brightness(img).enhance(1.1)
    img = ImageEnhance.Sharpness(img).enhance(8.0)
    # Recomprimir en JPEG de calidad ínfima varias veces es lo que produce
    # los artefactos de bloques que hacen reconocible al "deep fry".
    for _ in range(3):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=3)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
    return _png_bytes(img)


def wide(image_bytes: bytes, factor: float = 2.0) -> bytes:
    img = _open_rgb(image_bytes)
    factor = max(1.2, min(factor, 4.0))
    w, h = img.size
    return _png_bytes(img.resize((int(w * factor), h), Image.Resampling.LANCZOS))


def squish(image_bytes: bytes, factor: float = 0.5) -> bytes:
    img = _open_rgb(image_bytes)
    factor = max(0.2, min(factor, 0.8))
    w, h = img.size
    resized = img.resize((max(1, int(w * factor)), h), Image.Resampling.LANCZOS)
    return _png_bytes(resized)


def invert(image_bytes: bytes) -> bytes:
    return _png_bytes(ImageOps.invert(_open_rgb(image_bytes)))


def greyscale(image_bytes: bytes) -> bytes:
    return _png_bytes(ImageOps.grayscale(_open_rgb(image_bytes)).convert("RGB"))


# Matriz estándar de conversión a sepia: 3 filas (R,G,B de salida) x 4
# columnas (coeficientes de R,G,B de entrada + offset). Ver Image.convert().
_SEPIA_MATRIX = (
    0.393, 0.769, 0.189, 0,
    0.349, 0.686, 0.168, 0,
    0.272, 0.534, 0.131, 0,
)  # fmt: skip


def sepia(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    return _png_bytes(img.convert("RGB", _SEPIA_MATRIX))


def pixelate(image_bytes: bytes, block_size: int = 12) -> bytes:
    img = _open_rgb(image_bytes)
    block_size = max(4, min(block_size, 40))
    w, h = img.size
    small = img.resize(
        (max(1, w // block_size), max(1, h // block_size)), Image.Resampling.NEAREST
    )
    return _png_bytes(small.resize((w, h), Image.Resampling.NEAREST))


def rotate(image_bytes: bytes, degrees: int = 90) -> bytes:
    img = _open(image_bytes).convert("RGBA")
    degrees = degrees % 360
    rotated = img.rotate(-degrees, expand=True, fillcolor=(0, 0, 0, 0))
    return _png_bytes(rotated)


def flip(image_bytes: bytes) -> bytes:
    return _png_bytes(ImageOps.flip(_open_rgb(image_bytes)))


def flop(image_bytes: bytes) -> bytes:
    return _png_bytes(ImageOps.mirror(_open_rgb(image_bytes)))


def circle(image_bytes: bytes) -> bytes:
    img = _open(image_bytes).convert("RGBA")
    size = min(img.size)
    fitted = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(fitted, (0, 0), mask)
    return _png_bytes(out)


def blur(image_bytes: bytes, radius: int = 6) -> bytes:
    radius = max(1, min(radius, 20))
    img = _open_rgb(image_bytes)
    return _png_bytes(img.filter(ImageFilter.GaussianBlur(radius)))


def sharpen(image_bytes: bytes) -> bytes:
    return _png_bytes(_open_rgb(image_bytes).filter(ImageFilter.SHARPEN))
