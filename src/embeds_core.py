"""Lógica pura de embeds: validación contra los límites reales de Discord y
almacenamiento de imágenes en R2.

Vivía dentro de webapi.py, junto a las rutas del panel. Se extrajo al desmontar
la capa web (landing + dashboard) para que sobreviva al rediseño del sitio: no
depende de aiohttp ni de ninguna página, solo de los límites de Discord y de
r2.py, así que el frontend nuevo puede reusarla tal cual.
"""

import asyncio
import hashlib

import r2

# Límites reales de Discord para embeds (title/description/fields/etc.).
EMBED_MAX_TITLE = 256
EMBED_MAX_DESCRIPTION = 4096
EMBED_MAX_FIELDS = 25
EMBED_MAX_FIELD_NAME = 256
EMBED_MAX_FIELD_VALUE = 1024
EMBED_MAX_FOOTER = 2048
EMBED_MAX_AUTHOR = 256
EMBED_MAX_TOTAL = 6000
EMBED_MAX_COUNT = 10  # Discord: máximo de embeds por mensaje en modo clásico.


def embed_char_count(embed: dict) -> int:
    """Caracteres que Discord cuenta contra el límite de 6000 por mensaje:
    title + description + footer.text + author.name + fields (name y value)."""
    fields = embed.get("fields") or []
    return (
        len(embed.get("title") or "")
        + len(embed.get("description") or "")
        + len((embed.get("footer") or {}).get("text") or "")
        + len((embed.get("author") or {}).get("name") or "")
        + sum(
            len(f.get("name") or "") + len(f.get("value") or "")
            for f in fields
            if isinstance(f, dict)
        )
    )


def validate_embed_payload(embed: dict) -> str | None:
    """Valida un dict de embed contra los límites reales de Discord.

    Devuelve un mensaje de error o None si es válido. Efecto lateral
    deliberado: si `color` viene como string hex ("#8B6EF5"), lo convierte a
    int in place — discord.Embed.from_dict espera un int, no un hex con #.
    """
    if not isinstance(embed, dict):
        return "embed inválido: se esperaba un objeto"

    title = embed.get("title") or ""
    description = embed.get("description") or ""
    fields = embed.get("fields") or []
    footer_text = (embed.get("footer") or {}).get("text") or ""
    author_name = (embed.get("author") or {}).get("name") or ""

    if not isinstance(title, str) or not isinstance(description, str):
        return "title y description deben ser texto"
    if len(title) > EMBED_MAX_TITLE:
        return f"title supera los {EMBED_MAX_TITLE} caracteres"
    if len(description) > EMBED_MAX_DESCRIPTION:
        return f"description supera los {EMBED_MAX_DESCRIPTION} caracteres"
    if not isinstance(fields, list) or len(fields) > EMBED_MAX_FIELDS:
        return f"fields admite máximo {EMBED_MAX_FIELDS} elementos"
    if len(footer_text) > EMBED_MAX_FOOTER:
        return f"footer.text supera los {EMBED_MAX_FOOTER} caracteres"
    if len(author_name) > EMBED_MAX_AUTHOR:
        return f"author.name supera los {EMBED_MAX_AUTHOR} caracteres"

    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            return f"field {i + 1} inválido"
        name = f.get("name") or ""
        value = f.get("value") or ""
        if not isinstance(name, str) or not isinstance(value, str):
            return f"field {i + 1}: name y value deben ser texto"
        if not name.strip() or not value.strip():
            return f"field {i + 1}: name y value no pueden estar vacíos"
        if len(name) > EMBED_MAX_FIELD_NAME:
            return f"field {i + 1}: name supera los {EMBED_MAX_FIELD_NAME} caracteres"
        if len(value) > EMBED_MAX_FIELD_VALUE:
            return f"field {i + 1}: value supera los {EMBED_MAX_FIELD_VALUE} caracteres"
    if embed_char_count(embed) > EMBED_MAX_TOTAL:
        return f"el embed supera los {EMBED_MAX_TOTAL} caracteres en total"

    # Discord rechaza embeds sin contenido visible.
    if not any(
        (title.strip(), description.strip(), fields, footer_text.strip(),
         author_name.strip(), embed.get("image"), embed.get("thumbnail"))
    ):
        return "el embed está vacío: completa al menos un campo"

    color = embed.get("color")
    if isinstance(color, str):
        try:
            color = int(color.lstrip("#"), 16)
        except ValueError:
            return "color inválido: usa formato #RRGGBB"
        embed["color"] = color
    if color is not None and not (
        isinstance(color, int) and 0 <= color <= 0xFFFFFF
    ):
        return "color inválido: fuera de rango"
    return None


def validate_embeds_payload(embeds) -> str | None:
    """Valida una lista de hasta 10 embeds (modo clásico). Cada embed se valida
    con validate_embed_payload, y además el tope de 6000 caracteres aplica a la
    SUMA de todos los embeds del mensaje (regla real de Discord, no por embed).
    Convierte los colores hex a int in place (efecto lateral heredado de
    validate_embed_payload)."""
    if not isinstance(embeds, list) or not embeds:
        return "se esperaba una lista de al menos un embed"
    if len(embeds) > EMBED_MAX_COUNT:
        return f"máximo {EMBED_MAX_COUNT} embeds por mensaje"
    for i, embed in enumerate(embeds):
        err = validate_embed_payload(embed)
        if err:
            return f"Embed {i + 1}: {err}"
    total = sum(embed_char_count(e) for e in embeds)
    if total > EMBED_MAX_TOTAL:
        return (
            f"el mensaje supera los {EMBED_MAX_TOTAL} caracteres "
            f"sumando todos los embeds ({total})"
        )
    return None


# Firmas mágicas de los formatos de imagen que acepta el uploader.
def sniff_image(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


async def store_upload(data: bytes, guild_id: int, ext: str) -> str | None:
    """Sube bytes de imagen (ya validados por sniff_image) a R2.

    La key deriva del md5 del CONTENIDO: subir dos veces la misma imagen
    produce la misma key (el segundo put pisa el primero en R2, sin objeto
    duplicado)."""
    digest = hashlib.md5(data, usedforsecurity=False).hexdigest()
    return await asyncio.to_thread(
        r2.upload_image_bytes_sync, f"panel-upload:{digest}", data, guild_id, ext
    )
