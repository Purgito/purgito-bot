"""Motor central de placeholders / variables para eventos del servidor.

Proporciona:
1. Definición y metadatos de todas las variables disponibles por evento.
2. Validación de variables desconocidas e incompatibles.
3. Resolución de variables en modo preview y producción.
4. Soporte para textos planos, embeds clásicos y Layout V2.
5. Formateo respetando el locale del servidor (es/en).
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any

import discord

EVENT_TYPES = ("welcome", "goodbye", "boost")

# Discord boost tiers requirements
BOOST_TIER_REQUIREMENTS = {
    0: 0,
    1: 2,
    2: 7,
    3: 14,
}

MONTHS_ES = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

MONTHS_EN = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def format_localized_date(dt: datetime | None, locale: str = "es") -> str:
    """Formatea una fecha legible en español o inglés."""
    if dt is None:
        return "N/A"
    try:
        month = dt.month
        if locale == "en":
            m_name = MONTHS_EN[month] if 1 <= month <= 12 else str(month)
            return f"{m_name} {dt.day}, {dt.year}"
        m_name = MONTHS_ES[month] if 1 <= month <= 12 else str(month)
        return f"{dt.day} de {m_name} de {dt.year}"
    except Exception:
        return dt.strftime("%Y-%m-%d")


def format_number(n: int, locale: str = "es") -> str:
    """Formatea un entero con separador de miles según el locale."""
    try:
        if locale == "es":
            return f"{n:,}".replace(",", ".")
        return f"{n:,}"
    except Exception:
        return str(n)


# Catálogo completo de variables con metadatos
PLACEHOLDER_DEFINITIONS: dict[str, dict[str, Any]] = {
    # --- Usuario ---
    "user": {
        "name": "user",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Mención al usuario que activó este evento.",
        "description_en": "Mention of the user who triggered this event.",
        "example": "@Isa",
    },
    "user_tag": {
        "name": "user_tag",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Nombre de usuario con discriminador o formato global.",
        "description_en": "Username with tag or global username format.",
        "example": "isa_dev",
    },
    "user_name": {
        "name": "user_name",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Nombre de usuario único de Discord.",
        "description_en": "Discord unique username.",
        "example": "isa_dev",
    },
    "user_nick": {
        "name": "user_nick",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Apodo del usuario en este servidor si tiene uno.",
        "description_en": "Server nickname of the user if set.",
        "example": "Isa ✨",
    },
    "user_displayname": {
        "name": "user_displayname",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Nombre mostrado del usuario.",
        "description_en": "Display name of the user.",
        "example": "Isa",
    },
    "user_avatar": {
        "name": "user_avatar",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "URL del avatar actual del usuario.",
        "description_en": "URL of the user's current avatar.",
        "example": "https://cdn.discordapp.com/embed/avatars/0.png",
    },
    "user_id": {
        "name": "user_id",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "ID numérico de Discord del usuario.",
        "description_en": "Discord numerical user ID.",
        "example": "123456789012345678",
    },
    "user_created_at": {
        "name": "user_created_at",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Fecha de creación de la cuenta del usuario.",
        "description_en": "Account creation date of the user.",
        "example": "15 de enero de 2022",
    },
    "user_joined_at": {
        "name": "user_joined_at",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Fecha en que el usuario entró al servidor.",
        "description_en": "Date when the user joined the server.",
        "example": "21 de agosto de 2026",
    },
    "user_boost_since": {
        "name": "user_boost_since",
        "category": "user",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Fecha desde la que el usuario está haciendo boost.",
        "description_en": "Date since the user has been boosting the server.",
        "example": "21 de agosto de 2026",
    },
    # --- Servidor ---
    "server_name": {
        "name": "server_name",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Nombre del servidor de Discord.",
        "description_en": "Name of the Discord server.",
        "example": "Mi Servidor",
    },
    "server_id": {
        "name": "server_id",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "ID numérico de Discord del servidor.",
        "description_en": "Discord numerical server ID.",
        "example": "987654321098765432",
    },
    "server_membercount": {
        "name": "server_membercount",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Cantidad total de miembros del servidor.",
        "description_en": "Total member count of the server.",
        "example": "1.284",
    },
    "server_membercount_ordinal": {
        "name": "server_membercount_ordinal",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Número de miembro ordinal (ej. #1.284).",
        "description_en": "Ordinal member count number (e.g. #1,284).",
        "example": "#1.284",
    },
    "server_icon": {
        "name": "server_icon",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "URL del icono del servidor.",
        "description_en": "URL of the server icon.",
        "example": "https://cdn.discordapp.com/icons/987654321/icon.png",
    },
    "server_owner": {
        "name": "server_owner",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Nombre del dueño del servidor.",
        "description_en": "Name of the server owner.",
        "example": "Owner",
    },
    "server_owner_id": {
        "name": "server_owner_id",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "ID numérico del dueño del servidor.",
        "description_en": "Numerical ID of the server owner.",
        "example": "111222333444555666",
    },
    "server_created_at": {
        "name": "server_created_at",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Fecha de creación del servidor.",
        "description_en": "Server creation date.",
        "example": "10 de marzo de 2020",
    },
    "server_rolecount": {
        "name": "server_rolecount",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Cantidad de roles creados en el servidor.",
        "description_en": "Total number of roles in the server.",
        "example": "42",
    },
    "server_channelcount": {
        "name": "server_channelcount",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Cantidad total de canales del servidor.",
        "description_en": "Total number of channels in the server.",
        "example": "28",
    },
    "server_boostlevel": {
        "name": "server_boostlevel",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Nivel de boost del servidor (0, 1, 2 o 3).",
        "description_en": "Server boost level (0, 1, 2, or 3).",
        "example": "2",
    },
    "server_boostcount": {
        "name": "server_boostcount",
        "category": "server",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Cantidad total de mejoras (boosts) del servidor.",
        "description_en": "Total number of boosts on the server.",
        "example": "9",
    },
    # --- Canal ---
    "channel": {
        "name": "channel",
        "category": "channel",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Mención del canal donde se envía el mensaje.",
        "description_en": "Mention of the destination channel.",
        "example": "#general",
    },
    "channel_name": {
        "name": "channel_name",
        "category": "channel",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Nombre del canal donde se envía el mensaje.",
        "description_en": "Name of the destination channel.",
        "example": "general",
    },
    "channel_id": {
        "name": "channel_id",
        "category": "channel",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "ID numérico del canal.",
        "description_en": "Numerical channel ID.",
        "example": "555666777888999000",
    },
    # --- Específicas de Boost ---
    "server_nextboostlevel": {
        "name": "server_nextboostlevel",
        "category": "boost",
        "allowed_events": {"boost"},
        "description_es": "Siguiente nivel de boost a alcanzar.",
        "description_en": "Next boost tier to achieve.",
        "example": "3",
    },
    "server_nextboostlevel_required": {
        "name": "server_nextboostlevel_required",
        "category": "boost",
        "allowed_events": {"boost"},
        "description_es": "Boosts totales necesarios para el siguiente nivel.",
        "description_en": "Total boosts required for the next level.",
        "example": "14",
    },
    "server_nextboostlevel_until_required": {
        "name": "server_nextboostlevel_until_required",
        "category": "boost",
        "allowed_events": {"boost"},
        "description_es": "Cantidad de boosts que faltan para el siguiente nivel.",
        "description_en": "Number of boosts remaining until the next level.",
        "example": "5",
    },
    # --- Fecha ---
    "date": {
        "name": "date",
        "category": "date",
        "allowed_events": {"welcome", "goodbye", "boost"},
        "description_es": "Fecha actual del evento.",
        "description_en": "Current date of the event.",
        "example": "21 de agosto de 2026",
    },
}

_VARIABLE_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def get_available_placeholders(
    event_type: str | None = None, locale: str = "es"
) -> list[dict[str, Any]]:
    """Devuelve la lista de placeholders disponibles, opcionalmente filtrados por evento."""
    results = []
    for var, data in PLACEHOLDER_DEFINITIONS.items():
        if event_type and event_type in EVENT_TYPES:
            if event_type not in data["allowed_events"]:
                continue
        desc = (
            data.get("description_en")
            if locale == "en"
            else data.get("description_es")
        )
        results.append(
            {
                "name": var,
                "category": data["category"],
                "allowed_events": sorted(list(data["allowed_events"])),
                "description": desc or data.get("description_es", ""),
                "example": data["example"],
            }
        )
    return results


def extract_variables_from_text(text: str | None) -> set[str]:
    """Extrae todos los nombres de variables dentro de `{nombre}` en el texto."""
    if not text or not isinstance(text, str):
        return set()
    return set(_VARIABLE_RE.findall(text))


def _extract_from_embed(embed: dict) -> set[str]:
    found = set()
    if not isinstance(embed, dict):
        return found
    found.update(extract_variables_from_text(embed.get("title")))
    found.update(extract_variables_from_text(embed.get("description")))
    for f in embed.get("fields") or []:
        if isinstance(f, dict):
            found.update(extract_variables_from_text(f.get("name")))
            found.update(extract_variables_from_text(f.get("value")))
    footer = embed.get("footer")
    if isinstance(footer, dict):
        found.update(extract_variables_from_text(footer.get("text")))
        found.update(extract_variables_from_text(footer.get("icon_url")))
    author = embed.get("author")
    if isinstance(author, dict):
        found.update(extract_variables_from_text(author.get("name")))
        found.update(extract_variables_from_text(author.get("icon_url")))
    thumb = embed.get("thumbnail")
    if isinstance(thumb, dict):
        found.update(extract_variables_from_text(thumb.get("url")))
    elif isinstance(thumb, str):
        found.update(extract_variables_from_text(thumb))
    img = embed.get("image")
    if isinstance(img, dict):
        found.update(extract_variables_from_text(img.get("url")))
    elif isinstance(img, str):
        found.update(extract_variables_from_text(img))
    return found


def _extract_from_block(block: dict) -> set[str]:
    found = set()
    if not isinstance(block, dict):
        return found
    b_type = block.get("type")
    if b_type == "container":
        for child in block.get("children") or []:
            found.update(_extract_from_block(child))
    elif b_type == "text":
        found.update(extract_variables_from_text(block.get("content")))
    elif b_type == "section":
        for tx in block.get("texts") or []:
            found.update(extract_variables_from_text(tx))
        acc = block.get("accessory")
        if isinstance(acc, dict):
            if acc.get("type") == "thumbnail":
                found.update(extract_variables_from_text(acc.get("url")))
                found.update(extract_variables_from_text(acc.get("description")))
            elif acc.get("type") == "button":
                found.update(extract_variables_from_text(acc.get("label")))
                found.update(extract_variables_from_text(acc.get("url")))
    elif b_type == "media_gallery":
        for item in block.get("items") or []:
            if isinstance(item, dict):
                found.update(extract_variables_from_text(item.get("url")))
                found.update(extract_variables_from_text(item.get("description")))
    elif b_type == "action_row":
        for btn in block.get("buttons") or []:
            if isinstance(btn, dict):
                found.update(extract_variables_from_text(btn.get("label")))
                found.update(extract_variables_from_text(btn.get("url")))
    return found


def extract_variables_from_content(
    content_mode: str, content: dict | list | str | None
) -> set[str]:
    """Extrae todas las variables de un mensaje normal, lista de embeds o layout_v2."""
    if not content:
        return set()
    if content_mode == "plain_text":
        if isinstance(content, str):
            return extract_variables_from_text(content)
        if isinstance(content, dict):
            return extract_variables_from_text(content.get("message"))
        return set()
    if content_mode == "classic_embed":
        embeds_list = []
        found = set()
        if isinstance(content, list):
            embeds_list = content
        elif isinstance(content, dict):
            embeds_list = content.get("embeds") or []
            send_opts = content.get("send_options")
            if isinstance(send_opts, dict):
                found.update(extract_variables_from_text(send_opts.get("username")))
                found.update(extract_variables_from_text(send_opts.get("avatar_url")))
        for e in embeds_list:
            if isinstance(e, dict):
                found.update(_extract_from_embed(e))
        return found
    if content_mode == "layout_v2":
        layout_dict = content if isinstance(content, dict) else {}
        found = set()
        send_opts = layout_dict.get("send_options")
        if isinstance(send_opts, dict):
            found.update(extract_variables_from_text(send_opts.get("username")))
            found.update(extract_variables_from_text(send_opts.get("avatar_url")))
        for b in layout_dict.get("blocks") or []:
            if isinstance(b, dict):
                found.update(_extract_from_block(b))
        return found
    if content_mode == "composite":
        found = set()
        if isinstance(content, dict):
            found.update(extract_variables_from_text(content.get("message")))
            for e in content.get("embeds") or []:
                if isinstance(e, dict):
                    found.update(_extract_from_embed(e))
            for b in content.get("buttons") or []:
                if isinstance(b, dict):
                    found.update(extract_variables_from_text(b.get("label")))
                    found.update(extract_variables_from_text(b.get("url")))
            send_opts = content.get("send_options")
            if isinstance(send_opts, dict):
                found.update(extract_variables_from_text(send_opts.get("username")))
                found.update(extract_variables_from_text(send_opts.get("avatar_url")))
        return found
    return set()


def validate_variables(
    variables: set[str] | list[str], event_type: str, locale: str = "es"
) -> list[str]:
    """Valida un conjunto de nombres de variables para un evento.

    Retorna una lista de errores (vacía si todo es válido).
    """
    errors = []
    if event_type not in EVENT_TYPES:
        msg = (
            f"Tipo de evento inválido: {event_type}"
            if locale == "es"
            else f"Invalid event type: {event_type}"
        )
        return [msg]

    for var in sorted(list(variables)):
        defn = PLACEHOLDER_DEFINITIONS.get(var)
        if defn is None:
            msg = (
                f"Variable desconocida: `{{{var}}}`"
                if locale == "es"
                else f"Unknown variable: `{{{var}}}`"
            )
            errors.append(msg)
            continue
        if event_type not in defn["allowed_events"]:
            msg = (
                f"La variable `{{{var}}}` no está disponible para el evento '{event_type}'"
                if locale == "es"
                else f"Variable `{{{var}}}` is not available for '{event_type}' event"
            )
            errors.append(msg)

    return errors


def validate_content_variables(
    content_mode: str,
    content: dict | list | str | None,
    event_type: str,
    locale: str = "es",
) -> list[str]:
    """Extrae y valida todas las variables de un contenido."""
    vars_found = extract_variables_from_content(content_mode, content)
    return validate_variables(vars_found, event_type, locale=locale)


def resolve_placeholders(text: str | None, context: dict[str, str]) -> str:
    """Reemplaza placeholders `{variable}` en un texto usando el diccionario de contexto."""
    if not text or not isinstance(text, str):
        return text or ""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name in context:
            return context[var_name]
        return match.group(0)

    return _VARIABLE_RE.sub(_replace, text)


def _is_valid_http_url(url: Any) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return u.startswith("http://") or u.startswith("https://")


def _resolve_embed(embed: Any, context: dict[str, str]) -> dict:
    if not isinstance(embed, dict):
        return {}
    e = copy.deepcopy(embed)
    if "title" in e and isinstance(e["title"], str):
        e["title"] = resolve_placeholders(e["title"], context)
    if "description" in e and isinstance(e["description"], str):
        e["description"] = resolve_placeholders(e["description"], context)
    if "url" in e and isinstance(e["url"], str):
        res_url = resolve_placeholders(e["url"], context)
        if _is_valid_http_url(res_url):
            e["url"] = res_url
        else:
            e.pop("url", None)
    if "fields" in e and isinstance(e["fields"], list):
        valid_fields = []
        for f in e["fields"]:
            if isinstance(f, dict):
                f_copy = copy.deepcopy(f)
                if "name" in f_copy and isinstance(f_copy["name"], str):
                    f_copy["name"] = resolve_placeholders(f_copy["name"], context)
                if "value" in f_copy and isinstance(f_copy["value"], str):
                    f_copy["value"] = resolve_placeholders(f_copy["value"], context)
                valid_fields.append(f_copy)
        e["fields"] = valid_fields
    if "footer" in e and isinstance(e["footer"], dict):
        if "text" in e["footer"] and isinstance(e["footer"]["text"], str):
            e["footer"]["text"] = resolve_placeholders(e["footer"]["text"], context)
        if "icon_url" in e["footer"] and isinstance(e["footer"]["icon_url"], str):
            res_icon = resolve_placeholders(e["footer"]["icon_url"], context)
            if _is_valid_http_url(res_icon):
                e["footer"]["icon_url"] = res_icon
            else:
                e["footer"].pop("icon_url", None)
        if not e["footer"].get("text") and not e["footer"].get("icon_url"):
            e.pop("footer", None)
    if "author" in e and isinstance(e["author"], dict):
        if "name" in e["author"] and isinstance(e["author"]["name"], str):
            e["author"]["name"] = resolve_placeholders(e["author"]["name"], context)
        if "icon_url" in e["author"] and isinstance(e["author"]["icon_url"], str):
            res_icon = resolve_placeholders(e["author"]["icon_url"], context)
            if _is_valid_http_url(res_icon):
                e["author"]["icon_url"] = res_icon
            else:
                e["author"].pop("icon_url", None)
        if "url" in e["author"] and isinstance(e["author"]["url"], str):
            res_a_url = resolve_placeholders(e["author"]["url"], context)
            if _is_valid_http_url(res_a_url):
                e["author"]["url"] = res_a_url
            else:
                e["author"].pop("url", None)
        if not e["author"].get("name"):
            e.pop("author", None)
    if "thumbnail" in e:
        if isinstance(e["thumbnail"], dict) and "url" in e["thumbnail"]:
            res_url = resolve_placeholders(e["thumbnail"]["url"], context)
            if _is_valid_http_url(res_url):
                e["thumbnail"]["url"] = res_url
            else:
                e.pop("thumbnail", None)
        elif isinstance(e["thumbnail"], str):
            res_url = resolve_placeholders(e["thumbnail"], context)
            if _is_valid_http_url(res_url):
                e["thumbnail"] = {"url": res_url}
            else:
                e.pop("thumbnail", None)
    if "image" in e:
        if isinstance(e["image"], dict) and "url" in e["image"]:
            res_url = resolve_placeholders(e["image"]["url"], context)
            if _is_valid_http_url(res_url):
                e["image"]["url"] = res_url
            else:
                e.pop("image", None)
        elif isinstance(e["image"], str):
            res_url = resolve_placeholders(e["image"], context)
            if _is_valid_http_url(res_url):
                e["image"] = {"url": res_url}
            else:
                e.pop("image", None)
    return e


def _resolve_block(block: Any, context: dict[str, str]) -> dict:
    if not isinstance(block, dict):
        return {}
    b = copy.deepcopy(block)
    b_type = b.get("type")
    if b_type == "container":
        if "children" in b and isinstance(b["children"], list):
            b["children"] = [
                _resolve_block(c, context)
                for c in b["children"]
                if isinstance(c, dict)
            ]
    elif b_type == "text":
        if "content" in b and isinstance(b["content"], str):
            b["content"] = resolve_placeholders(b["content"], context)
    elif b_type == "section":
        if "texts" in b and isinstance(b["texts"], list):
            b["texts"] = [
                resolve_placeholders(tx, context)
                for tx in b["texts"]
                if isinstance(tx, str)
            ]
        acc = b.get("accessory")
        if isinstance(acc, dict):
            if acc.get("type") == "thumbnail":
                res_url = resolve_placeholders(acc.get("url"), context)
                if _is_valid_http_url(res_url):
                    acc["url"] = res_url
                    if "description" in acc and isinstance(acc["description"], str):
                        acc["description"] = resolve_placeholders(
                            acc["description"], context
                        )
                else:
                    b.pop("accessory", None)
            elif acc.get("type") == "button":
                if "label" in acc and isinstance(acc["label"], str):
                    acc["label"] = resolve_placeholders(acc["label"], context)
                if "url" in acc and isinstance(acc["url"], str):
                    res_url = resolve_placeholders(acc["url"], context)
                    if _is_valid_http_url(res_url):
                        acc["url"] = res_url
                    else:
                        acc.pop("url", None)
    elif b_type == "media_gallery":
        if "items" in b and isinstance(b["items"], list):
            valid_items = []
            for it in b["items"]:
                if isinstance(it, dict):
                    res_url = resolve_placeholders(it.get("url"), context)
                    if _is_valid_http_url(res_url):
                        it_copy = copy.deepcopy(it)
                        it_copy["url"] = res_url
                        if "description" in it_copy and isinstance(it_copy["description"], str):
                            it_copy["description"] = resolve_placeholders(
                                it_copy["description"], context
                            )
                        valid_items.append(it_copy)
            b["items"] = valid_items
    elif b_type == "action_row":
        if "buttons" in b and isinstance(b["buttons"], list):
            for btn in b["buttons"]:
                if isinstance(btn, dict):
                    if "label" in btn and isinstance(btn["label"], str):
                        btn["label"] = resolve_placeholders(btn["label"], context)
                    if "url" in btn and isinstance(btn["url"], str):
                        res_url = resolve_placeholders(btn["url"], context)
                        if _is_valid_http_url(res_url):
                            btn["url"] = res_url
                        else:
                            btn.pop("url", None)
    return b


def resolve_content_placeholders(
    content_mode: str, content: dict | list | str, context: dict[str, str]
) -> dict | list | str:
    """Resuelve placeholders en cualquier estructura según content_mode."""
    if content_mode == "plain_text":
        if isinstance(content, str):
            return resolve_placeholders(content, context)
        if isinstance(content, dict):
            res = copy.deepcopy(content)
            if "message" in res and isinstance(res["message"], str):
                res["message"] = resolve_placeholders(res["message"], context)
            return res
        return str(content)
    if content_mode == "classic_embed":
        if isinstance(content, list):
            return [_resolve_embed(e, context) for e in content]
        if isinstance(content, dict):
            res = copy.deepcopy(content)
            if "embeds" in res and isinstance(res["embeds"], list):
                res["embeds"] = [_resolve_embed(e, context) for e in res["embeds"]]
            return res
        return content
    if content_mode == "layout_v2":
        if isinstance(content, dict):
            res = copy.deepcopy(content)
            if "blocks" in res and isinstance(res["blocks"], list):
                res["blocks"] = [_resolve_block(b, context) for b in res["blocks"]]
            return res
        return content
    if content_mode == "composite":
        if isinstance(content, dict):
            res = copy.deepcopy(content)
            if "message" in res and isinstance(res["message"], str):
                res["message"] = resolve_placeholders(res["message"], context)
            if "embeds" in res and isinstance(res["embeds"], list):
                res["embeds"] = [_resolve_embed(e, context) for e in res["embeds"] if isinstance(e, dict)]
            if "buttons" in res and isinstance(res["buttons"], list):
                valid_btns = []
                for btn in res["buttons"]:
                    if isinstance(btn, dict):
                        b_copy = copy.deepcopy(btn)
                        if "label" in b_copy and isinstance(b_copy["label"], str):
                            b_copy["label"] = resolve_placeholders(b_copy["label"], context)
                        if "url" in b_copy and isinstance(b_copy["url"], str):
                            res_url = resolve_placeholders(b_copy["url"], context)
                            if _is_valid_http_url(res_url):
                                b_copy["url"] = res_url
                        valid_btns.append(b_copy)
                res["buttons"] = valid_btns
            if "send_options" in res and isinstance(res["send_options"], dict):
                so = res["send_options"]
                if "username" in so and isinstance(so["username"], str):
                    so["username"] = resolve_placeholders(so["username"], context)
                if "avatar_url" in so and isinstance(so["avatar_url"], str):
                    so["avatar_url"] = resolve_placeholders(so["avatar_url"], context)
            return res
        return content
    return content


def get_preview_context(
    event_type: str, guild: discord.Guild | None = None, locale: str = "es"
) -> dict[str, str]:
    """Genera datos simulados realistas para preview y pruebas."""
    now = datetime.now(timezone.utc)
    date_str = format_localized_date(now, locale=locale)

    server_name = guild.name if guild else "Servidor de prueba"
    server_id = str(guild.id) if guild else "123456789012345678"
    member_count = (
        guild.member_count if (guild and guild.member_count) else 1284
    )
    formatted_member_count = format_number(member_count, locale=locale)
    ordinal_member_count = f"#{formatted_member_count}"

    server_icon = (
        str(guild.icon.url)
        if (guild and guild.icon)
        else "https://cdn.discordapp.com/embed/avatars/0.png"
    )
    owner_name = "Owner"
    owner_id = str(guild.owner_id) if (guild and guild.owner_id) else "111222333444555666"
    if guild and guild.owner:
        owner_name = guild.owner.display_name or guild.owner.name

    server_created = (
        format_localized_date(guild.created_at, locale=locale)
        if (guild and guild.created_at)
        else ("10 de marzo de 2020" if locale == "es" else "March 10, 2020")
    )
    role_count = str(len(guild.roles)) if guild else "25"
    channel_count = str(len(guild.channels)) if guild else "18"
    boost_level = str(guild.premium_tier) if guild else "1"
    boost_count = str(guild.premium_subscription_count) if guild else "4"

    curr_tier = guild.premium_tier if guild else 1
    curr_subs = guild.premium_subscription_count if guild else 4

    if curr_tier < 3:
        next_level = str(curr_tier + 1)
        req_subs = BOOST_TIER_REQUIREMENTS.get(curr_tier + 1, 7)
        until_req = str(max(0, req_subs - curr_subs))
        req_subs_str = str(req_subs)
    else:
        next_level = "Max" if locale == "en" else "Máximo"
        req_subs_str = str(BOOST_TIER_REQUIREMENTS.get(3, 14))
        until_req = "0"

    ctx: dict[str, str] = {
        # Usuario
        "user": "@Usuario de prueba",
        "user_tag": "usuario_prueba",
        "user_name": "usuario_prueba",
        "user_nick": "Usuario de prueba",
        "user_displayname": "Usuario de prueba",
        "user_avatar": "https://cdn.discordapp.com/embed/avatars/1.png",
        "user_id": "987654321012345678",
        "user_created_at": (
            "15 de enero de 2022" if locale == "es" else "January 15, 2022"
        ),
        "user_joined_at": date_str,
        "user_boost_since": date_str,
        # Servidor
        "server_name": server_name,
        "server_id": server_id,
        "server_membercount": formatted_member_count,
        "server_membercount_ordinal": ordinal_member_count,
        "server_icon": server_icon,
        "server_owner": owner_name,
        "server_owner_id": owner_id,
        "server_created_at": server_created,
        "server_rolecount": role_count,
        "server_channelcount": channel_count,
        "server_boostlevel": boost_level,
        "server_boostcount": boost_count,
        # Canal
        "channel": "#general",
        "channel_name": "general",
        "channel_id": "555666777888999000",
        # Boost
        "server_nextboostlevel": next_level,
        "server_nextboostlevel_required": req_subs_str,
        "server_nextboostlevel_until_required": until_req,
        # Fecha
        "date": date_str,
    }

    return ctx


def build_event_context(
    event_type: str,
    guild: discord.Guild,
    member: discord.Member | discord.User | None,
    channel: discord.abc.GuildChannel | None = None,
    boost_info: dict[str, Any] | None = None,
    locale: str = "es",
) -> dict[str, str]:
    """Construye el diccionario de variables con datos reales de Discord."""
    now = datetime.now(timezone.utc)
    date_str = format_localized_date(now, locale=locale)

    # Datos del servidor
    server_name = guild.name
    server_id = str(guild.id)
    m_count = guild.member_count or (len(guild.members) if guild.members else 1)
    formatted_member_count = format_number(m_count, locale=locale)
    ordinal_member_count = f"#{formatted_member_count}"

    server_icon = str(guild.icon.url) if guild.icon else ""
    owner_name = ""
    owner_id = str(guild.owner_id) if guild.owner_id else ""
    if guild.owner:
        owner_name = guild.owner.display_name or guild.owner.name
    elif guild.owner_id:
        owner_name = f"User {guild.owner_id}"

    server_created = format_localized_date(guild.created_at, locale=locale)
    role_count = str(len(guild.roles))
    channel_count = str(len(guild.channels))
    boost_level = str(guild.premium_tier)
    boost_count = str(guild.premium_subscription_count or 0)

    # Boost specific info
    try:
        curr_tier = int(guild.premium_tier)
    except (ValueError, TypeError):
        curr_tier = 0
    try:
        curr_subs = int(guild.premium_subscription_count or 0)
    except (ValueError, TypeError):
        curr_subs = 0

    if curr_tier < 3:
        next_level = str(curr_tier + 1)
        req_subs = BOOST_TIER_REQUIREMENTS.get(curr_tier + 1, 7)
        until_req = str(max(0, req_subs - curr_subs))
        req_subs_str = str(req_subs)
    else:
        next_level = "Max" if locale == "en" else "Máximo"
        req_subs_str = str(BOOST_TIER_REQUIREMENTS.get(3, 14))
        until_req = "0"

    # Datos de usuario
    user_mention = ""
    user_tag = ""
    user_name = ""
    user_nick = ""
    user_displayname = ""
    user_avatar = ""
    user_id = ""
    user_created = ""
    user_joined = ""
    user_boost_since = ""

    if member:
        user_mention = member.mention
        user_name = member.name
        user_tag = f"@{member.name}" if hasattr(member, "discriminator") and member.discriminator == "0" else str(member)
        user_id = str(member.id)
        user_avatar = (
            str(member.display_avatar.url)
            if hasattr(member, "display_avatar")
            else (str(member.avatar.url) if getattr(member, "avatar", None) else "")
        )
        user_displayname = getattr(member, "display_name", member.name)
        user_nick = getattr(member, "nick", None) or user_displayname

        if getattr(member, "created_at", None):
            user_created = format_localized_date(member.created_at, locale=locale)
        if getattr(member, "joined_at", None):
            user_joined = format_localized_date(member.joined_at, locale=locale)
        if getattr(member, "premium_since", None):
            user_boost_since = format_localized_date(
                member.premium_since, locale=locale
            )
        elif boost_info and boost_info.get("premium_since"):
            user_boost_since = format_localized_date(
                boost_info["premium_since"], locale=locale
            )

    # Datos de canal
    channel_mention = ""
    channel_name = ""
    channel_id = ""
    if channel:
        channel_mention = getattr(channel, "mention", f"<#{channel.id}>")
        channel_name = getattr(channel, "name", "")
        channel_id = str(channel.id)

    ctx: dict[str, str] = {
        # Usuario
        "user": user_mention or f"<@{user_id}>",
        "user_tag": user_tag or user_name,
        "user_name": user_name,
        "user_nick": user_nick or user_name,
        "user_displayname": user_displayname or user_name,
        "user_avatar": user_avatar,
        "user_id": user_id,
        "user_created_at": user_created or "N/A",
        "user_joined_at": user_joined or "N/A",
        "user_boost_since": user_boost_since or "N/A",
        # Servidor
        "server_name": server_name,
        "server_id": server_id,
        "server_membercount": formatted_member_count,
        "server_membercount_ordinal": ordinal_member_count,
        "server_icon": server_icon,
        "server_owner": owner_name,
        "server_owner_id": owner_id,
        "server_created_at": server_created,
        "server_rolecount": role_count,
        "server_channelcount": channel_count,
        "server_boostlevel": boost_level,
        "server_boostcount": boost_count,
        # Canal
        "channel": channel_mention,
        "channel_name": channel_name,
        "channel_id": channel_id,
        # Boost
        "server_nextboostlevel": next_level,
        "server_nextboostlevel_required": req_subs_str,
        "server_nextboostlevel_until_required": until_req,
        # Fecha
        "date": date_str,
    }

    return ctx
