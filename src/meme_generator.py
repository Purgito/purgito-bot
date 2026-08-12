import io
import os
import re
import textwrap
from PIL import Image, ImageDraw, ImageFont

# Rechaza imágenes descomprimidas gigantes (decompression bomb) antes de procesarlas.
Image.MAX_IMAGE_PIXELS = 15_000_000

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONT_PATH = os.path.join(_BASE_DIR, "assets", "Impact.ttf")


# Mismo allowlist que ya exige el caller por extensión (cogs/memes.py) --
# formats= restringe qué decoder de Pillow llega a tocar los bytes. Sin
# esto, Image.open() prueba TODOS los formatos que Pillow sabe leer
# (TIFF, ICO, EPS -- que puede shellear a Ghostscript --, PCX, etc.) contra
# contenido de un adjunto de Discord con la extensión falseada: cualquiera
# puede subir un .png que en realidad es otra cosa, y el nombre de archivo
# nunca llega hasta acá (Image.open ve puros bytes). Nada de esto depende
# de que el paquete tenga un CVE conocido -- es reducir qué parsers de
# Pillow quedan expuestos a bytes no confiables, conocido o no.
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


def _try_short_sentence(model, max_chars: int = 80, tries: int = 100) -> str | None:
    import re

    _DIGITS_RE = re.compile(r"\b\d{5,}\b")
    for _ in range(tries):
        candidate = model.generate(max_words=12, max_attempts=1, min_words=2)
        if not candidate:
            continue
        candidate = _DIGITS_RE.sub("", candidate).strip()
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate and len(candidate) <= max_chars:
            return candidate
    return None


def render_caption(image_bytes: bytes, caption: str) -> bytes:
    # image_bytes ya pasó por is_valid_image antes de entrar al pool -- se
    # repite formats= igual, no puede depender de que ese chequeo haya
    # corrido antes en el mismo proceso.
    base = Image.open(io.BytesIO(image_bytes), formats=_ALLOWED_FORMATS)
    if hasattr(base, "n_frames") and base.n_frames > 1:
        base.seek(0)
    base = base.convert("RGBA")
    img_w, img_h = base.size

    text_upper = caption.upper()
    import unicodedata

    text_upper = unicodedata.normalize("NFKD", text_upper)
    text_upper = "".join(c for c in text_upper if not unicodedata.combining(c))
    text_upper = re.sub(r"\s+", " ", text_upper).strip()
    padding_h = int(img_w * 0.05)
    usable_w = img_w - 2 * padding_h

    font_size = max(24, img_w // 12)
    font = None
    lines: list[str] = []

    while font_size >= 16:
        f = ImageFont.truetype(_FONT_PATH, font_size)
        avg_char_w = max(1, f.getlength("A"))
        chars_per_line = max(1, int(usable_w / avg_char_w))
        wrapped = textwrap.wrap(text_upper, width=chars_per_line) or [
            text_upper[: max(1, chars_per_line)]
        ]
        if all(f.getlength(line) <= usable_w for line in wrapped):
            font = f
            lines = wrapped
            break
        font_size -= 2

    if font is None:
        font_size = 16
        font = ImageFont.truetype(_FONT_PATH, font_size)
        avg_char_w = max(1, font.getlength("A"))
        chars_per_line = max(1, int(usable_w / avg_char_w))
        lines = textwrap.wrap(text_upper, width=chars_per_line) or [
            text_upper[: max(1, chars_per_line)]
        ]

    ascent, descent = font.getmetrics()
    line_h = ascent + descent

    padding_v = int(img_w * 0.08)
    min_banner_h = int(img_h * 0.12)
    if len(lines) * line_h + 2 * padding_v < min_banner_h:
        padding_v = (min_banner_h - len(lines) * line_h) // 2
    banner_h = len(lines) * line_h + 2 * padding_v

    out = Image.new("RGB", (img_w, banner_h + img_h), "white")

    white_bg = Image.new("RGBA", base.size, (255, 255, 255, 255))
    white_bg.alpha_composite(base)
    out.paste(white_bg.convert("RGB"), (0, banner_h))

    draw = ImageDraw.Draw(out)
    y = padding_v
    for line in lines:
        line_w = font.getlength(line)
        x = int((img_w - line_w) / 2)
        draw.text((x, y), line, fill=(0, 0, 0), font=font)
        y += line_h

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


import random as _random  # noqa: E402

_SPLIT_CONNECTORS = [
    "HASTA QUE",
    "Y ENTONCES",
    "PERO",
    "CUANDO",
    "VS",
    "MIENTRAS",
    "ENTONCES",
    "PORQUE",
    "O",
]


def _find_connector_split(words: list[str]) -> tuple[str, str] | None:
    for connector in _SPLIT_CONNECTORS:
        conn_words = connector.split()
        n = len(conn_words)
        for i in range(1, len(words) - n):
            if words[i : i + n] == conn_words:
                return " ".join(words[:i]), " ".join(words[i:])
    return None


def render_meme(image_bytes: bytes, caption: str) -> bytes:
    import unicodedata

    base = Image.open(io.BytesIO(image_bytes))
    if hasattr(base, "n_frames") and base.n_frames > 1:
        base.seek(0)
    base = base.convert("RGB")
    img_w, img_h = base.size

    text = caption.upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return image_bytes

    words = text.split()
    split = _find_connector_split(words) if len(words) >= 4 else None

    if split:
        top_text, bottom_text = split
    else:
        if _random.choice([True, False]):
            top_text, bottom_text = text, None
        else:
            top_text, bottom_text = None, text

    draw = ImageDraw.Draw(base)

    def draw_outlined_text(txt: str, position: str):
        if not txt:
            return
        padding_h = int(img_w * 0.05)
        usable_w = img_w - 2 * padding_h
        font_size = max(28, img_w // 10)
        font = None
        lines = []
        while font_size >= 18:
            f = ImageFont.truetype(_FONT_PATH, font_size)
            avg_char_w = max(1, f.getlength("A"))
            chars_per_line = max(1, int(usable_w / avg_char_w))
            wrapped = textwrap.wrap(txt, width=chars_per_line) or [txt[:chars_per_line]]
            if all(f.getlength(ln) <= usable_w for ln in wrapped):
                font = f
                lines = wrapped
                break
            font_size -= 2
        if font is None:
            font_size = 18
            font = ImageFont.truetype(_FONT_PATH, font_size)
            avg_char_w = max(1, font.getlength("A"))
            chars_per_line = max(1, int(usable_w / avg_char_w))
            lines = textwrap.wrap(txt, width=chars_per_line) or [txt]

        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        total_h = len(lines) * line_h
        margin = int(img_h * 0.03)

        if position == "top":
            y = margin
        else:
            y = img_h - total_h - margin

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

    draw_outlined_text(top_text, "top")
    draw_outlined_text(bottom_text, "bottom")

    buf = io.BytesIO()
    base.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
