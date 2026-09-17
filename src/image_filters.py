"""Filtros de imagen tipo NotSoBot (Fases 1 y 2): transformaciones Pillow
puras sobre bytes de una imagen ya resuelta. La resolución de la fuente
(adjunto, mensaje respondido o avatar) vive en cogs/imagefx.py -- este
módulo no sabe nada de discord.py."""

import io
import os
import textwrap

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

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


def _sepia_img(img: Image.Image) -> Image.Image:
    return img.convert("RGB", _SEPIA_MATRIX)


def sepia(image_bytes: bytes) -> bytes:
    return _png_bytes(_sepia_img(_open_rgb(image_bytes)))


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


# ── Fase 2: overlays y efectos de un solo chiste ─────────────────────────────


def triggered(image_bytes: bytes) -> bytes:
    """GIF corto: zoom + temblor + tinte rojo + banner "TRIGGERED" abajo."""
    base = _open_rgb(image_bytes)
    base.thumbnail((400, 400))
    w, h = base.size
    zoomed = base.resize((int(w * 1.15), int(h * 1.15)), Image.Resampling.LANCZOS)
    zw, zh = zoomed.size

    banner_h = max(28, h // 6)
    shake = max(4, w // 40)
    offsets = [(-shake, 0), (shake, 0), (0, -shake), (0, shake)] * 2
    font = ImageFont.truetype(_FONT_PATH, banner_h - 6)
    text = "TRIGGERED"
    text_w = font.getlength(text)

    frames = []
    for dx, dy in offsets:
        x = (zw - w) // 2 + dx
        y = (zh - h) // 2 + dy
        cropped = zoomed.crop((x, y, x + w, y + h))
        red_overlay = Image.new("RGB", cropped.size, (200, 0, 0))
        cropped = Image.blend(cropped, red_overlay, 0.35)

        canvas = Image.new("RGB", (w, h + banner_h), (0, 0, 0))
        canvas.paste(cropped, (0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text(((w - text_w) / 2, h + 2), text, font=font, fill=(255, 255, 255))
        frames.append(canvas)

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=60,
        loop=0,
    )
    return buf.getvalue()


def wasted(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    grey = ImageOps.grayscale(img).convert("RGB")
    darkened = ImageEnhance.Brightness(grey).enhance(0.5)
    w, h = darkened.size

    font_size = max(28, w // 6)
    font = ImageFont.truetype(_FONT_PATH, font_size)
    text = "WASTED"
    text_w = font.getlength(text)
    draw = ImageDraw.Draw(darkened)
    draw.text(
        ((w - text_w) / 2, (h - font_size) / 2),
        text,
        font=font,
        fill=(255, 255, 255),
        stroke_width=max(2, font_size // 15),
        stroke_fill=(0, 0, 0),
    )
    return _png_bytes(darkened)


def trash(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    img.thumbnail((400, 400))
    w, h = img.size
    dark = ImageEnhance.Brightness(img).enhance(0.55)

    pad = max(16, int(w * 0.08))
    lid_h = max(16, h // 10)
    canvas_w = w + pad * 2
    canvas_h = lid_h + h + pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), (60, 64, 68))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas_w, lid_h), fill=(90, 95, 100))
    handle_w = canvas_w // 3
    draw.rectangle(
        ((canvas_w - handle_w) // 2, 0, (canvas_w + handle_w) // 2, lid_h // 2),
        fill=(90, 95, 100),
    )
    canvas.paste(dark, (pad, lid_h + pad // 2))
    for frac in (0.3, 0.7):
        y = lid_h + int((canvas_h - lid_h) * frac)
        draw.line((6, y, canvas_w - 6, y), fill=(30, 32, 34), width=3)

    return _png_bytes(canvas)


def communism(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    grey = ImageOps.grayscale(img)
    red_tinted = ImageOps.colorize(grey, black=(20, 0, 0), white=(255, 60, 50))
    w, h = red_tinted.size

    icon_size = max(24, min(w, h) // 4)
    cx, cy = w - icon_size, icon_size
    color = (255, 220, 0)
    draw = ImageDraw.Draw(red_tinted)
    draw.arc(
        (
            cx - icon_size // 2,
            cy - icon_size // 2,
            cx + icon_size // 2,
            cy + icon_size // 2,
        ),
        start=200,
        end=340,
        fill=color,
        width=max(3, icon_size // 8),
    )
    draw.line(
        (cx, cy, cx + icon_size // 3, cy + icon_size // 3),
        fill=color,
        width=max(3, icon_size // 10),
    )
    draw.rectangle(
        (
            cx - icon_size // 6,
            cy - icon_size // 6,
            cx + icon_size // 6,
            cy + icon_size // 6,
        ),
        fill=color,
    )
    return _png_bytes(red_tinted)


_RAINBOW_COLORS = [
    (228, 3, 3), (255, 140, 0), (255, 237, 0),
    (0, 128, 38), (0, 76, 255), (115, 41, 130),
]  # fmt: skip


def gay(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes).convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(overlay)
    stripe_h = max(1, h // len(_RAINBOW_COLORS))
    for i, color in enumerate(_RAINBOW_COLORS):
        y0 = i * stripe_h
        y1 = h if i == len(_RAINBOW_COLORS) - 1 else y0 + stripe_h
        draw.rectangle((0, y0, w, y1), fill=color + (110,))
    out = Image.alpha_composite(img, overlay)
    return _png_bytes(out.convert("RGB"))


def jail(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    w, h = img.size
    darkened = ImageEnhance.Brightness(img).enhance(0.8)
    draw = ImageDraw.Draw(darkened)
    bar_w = max(4, w // 14)
    gap = bar_w * 2
    x = 0
    while x < w:
        draw.rectangle((x, 0, x + bar_w, h), fill=(10, 10, 10))
        x += bar_w + gap
    return _png_bytes(darkened)


def wanted(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    img.thumbnail((350, 350))
    toned = _sepia_img(img)
    w, h = toned.size

    margin = max(20, w // 8)
    header_h = max(50, h // 5)
    footer_h = max(30, h // 8)
    canvas_w = w + margin * 2
    canvas_h = header_h + h + footer_h
    ink = (40, 25, 15)
    canvas = Image.new("RGB", (canvas_w, canvas_h), (222, 197, 150))

    border = max(4, margin // 6)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (border, border, canvas_w - border, canvas_h - border),
        outline=ink,
        width=border,
    )

    title_size = header_h - 16
    title_font = ImageFont.truetype(_FONT_PATH, title_size)
    title = "WANTED"
    title_w = title_font.getlength(title)
    draw.text(
        ((canvas_w - title_w) / 2, (header_h - title_size) / 2),
        title,
        font=title_font,
        fill=ink,
    )

    canvas.paste(toned, (margin, header_h))

    sub_size = max(16, footer_h - 14)
    sub_font = ImageFont.truetype(_FONT_PATH, sub_size)
    subtitle = "DEAD OR ALIVE"
    sub_w = sub_font.getlength(subtitle)
    draw.text(
        ((canvas_w - sub_w) / 2, header_h + h + (footer_h - sub_size) / 2),
        subtitle,
        font=sub_font,
        fill=ink,
    )
    return _png_bytes(canvas)


def rip(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    portrait_size = 160
    portrait = ImageOps.fit(
        img, (portrait_size, portrait_size), Image.Resampling.LANCZOS
    )
    portrait = ImageOps.grayscale(portrait).convert("RGB")

    canvas_w, canvas_h = 320, 380
    grass_y = canvas_h - 40
    canvas = Image.new("RGB", (canvas_w, canvas_h), (120, 170, 110))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, grass_y, canvas_w, canvas_h), fill=(90, 140, 85))

    stone_w, stone_h = 220, 260
    stone_x = (canvas_w - stone_w) // 2
    stone_y = grass_y - stone_h
    stone_color = (150, 150, 150)
    draw.ellipse(
        (stone_x, stone_y, stone_x + stone_w, stone_y + stone_h // 2), fill=stone_color
    )
    draw.rectangle(
        (stone_x, stone_y + stone_h // 4, stone_x + stone_w, stone_y + stone_h),
        fill=stone_color,
    )

    portrait_x = stone_x + (stone_w - portrait_size) // 2
    portrait_y = stone_y + stone_h // 2 - portrait_size // 2
    canvas.paste(portrait, (portrait_x, portrait_y))

    font = ImageFont.truetype(_FONT_PATH, 36)
    text = "R.I.P."
    text_w = font.getlength(text)
    draw.text(
        (stone_x + (stone_w - text_w) / 2, portrait_y + portrait_size + 10),
        text,
        font=font,
        fill=(60, 60, 60),
    )
    return _png_bytes(canvas)


def america(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes).convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(overlay)
    stripes = 7
    stripe_h = max(1, h // stripes)
    red, white = (178, 34, 52, 120), (255, 255, 255, 90)
    for i in range(stripes):
        y0 = i * stripe_h
        y1 = h if i == stripes - 1 else y0 + stripe_h
        draw.rectangle((0, y0, w, y1), fill=red if i % 2 == 0 else white)
    canton_w, canton_h = int(w * 0.4), int(h * 0.45)
    draw.rectangle((0, 0, canton_w, canton_h), fill=(60, 60, 140, 140))
    out = Image.alpha_composite(img, overlay)
    return _png_bytes(out.convert("RGB"))


def polaroid(image_bytes: bytes) -> bytes:
    img = _open_rgb(image_bytes)
    img.thumbnail((400, 400))
    w, h = img.size
    border = max(10, w // 20)
    bottom_border = border * 4
    canvas = Image.new(
        "RGB", (w + border * 2, h + border + bottom_border), (250, 250, 245)
    )
    canvas.paste(img, (border, border))
    return _png_bytes(canvas)


def poster(image_bytes: bytes, bits: int = 2) -> bytes:
    bits = max(1, min(bits, 7))
    return _png_bytes(ImageOps.posterize(_open_rgb(image_bytes), bits))


def threshold(image_bytes: bytes, level: int = 128) -> bytes:
    level = max(1, min(level, 254))
    grey = ImageOps.grayscale(_open_rgb(image_bytes))
    bw = grey.point(lambda p: 255 if p > level else 0)
    return _png_bytes(bw.convert("RGB"))


def emboss(image_bytes: bytes) -> bytes:
    return _png_bytes(_open_rgb(image_bytes).filter(ImageFilter.EMBOSS))
