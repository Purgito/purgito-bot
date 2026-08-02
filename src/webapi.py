"""API HTTP del bot: webhook de Polar, health check y todo lo que consume el
dashboard de purgito.app.

Este archivo sirve **solo JSON**. Las páginas (landing, docs, perfil,
dashboard) son HTML estático en ``landing/`` que nginx sirve desde disco; acá
no se renderiza ni una etiqueta, salvo la pantalla de error de OAuth.

Bloques:

- ``/webhooks/polar``: Polar avisa altas/bajas de suscripción por acá. Sin este
  endpoint, un pago cobrado nunca activa el premium del servidor.
- ``/health``: monitoreo externo.
- OAuth2 de Discord + sesión: la capa de autenticación de la que dependen todos
  los endpoints con scope de guild (``guild_api`` exige sesión con permiso de
  administrar el guild).
- ``/api/me`` y ``/api/me/guilds``: quién soy y qué servidores administro. Lo
  consumen el navbar de todo el sitio y la lista de servidores de ``/es/perfil``.
- ``/api/server/{guild_id}/…``: configuración por servidor — canales, roles,
  emojis, chat, corpus, reacciones, frases, actualizaciones, estilo del bot,
  estadísticas, GIFs, editor de embeds y premium.
"""

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import urlencode, urlparse

import aiohttp
import discord
from aiohttp import web
from aiohttp_session import get_session, setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from discord.ext import commands
from polar_sdk import Polar
from polar_sdk.webhooks import (
    WebhookUnknownTypeError,
    WebhookVerificationError,
    validate_event,
)

from config import (
    DASHBOARD_BASE_URL,
    DASHBOARD_ENABLED,
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    LANDING_ORIGINS,
    LANDING_URL,
    POLAR_ACCESS_TOKEN,
    POLAR_PRODUCT_ID_ANNUAL,
    POLAR_PRODUCT_ID_MONTHLY,
    POLAR_SERVER,
    POLAR_WEBHOOK_SECRET,
    SESSION_COOKIE_DOMAIN,
    SESSION_SECRET,
    WEB_PORT,
    env_int,
    get_invite_url,
)
from cogs.gifs import HEALTH_CHECK_BATCH, run_gif_health_check
from cogs.premium import is_premium_guild, set_premium, unset_premium
from db import (
    add_button_action,
    add_chat_channel,
    add_embed_template,
    add_frase_especial,
    add_ignored_channel,
    add_reaction_to_pool,
    add_scheduled_announcement,
    add_shared_embed,
    count_corpus_by_channel,
    count_gif_urls,
    count_guild_corpus_messages,
    count_shared_embeds_today,
    delete_embed_template,
    delete_frase_especial,
    delete_gif_url_by_id,
    embed_template_limit,
    extract_send_options,
    get_bot_style,
    get_chat_settings,
    get_counters,
    get_gif_by_url,
    get_shared_embed,
    get_updates_channel,
    list_chat_channels,
    list_embed_templates,
    list_frases_especiales,
    list_gif_urls,
    list_ignored_channels,
    list_premium_guilds,
    list_reaction_pool,
    normalize_embeds_json,
    remove_chat_channel,
    remove_ignored_channel,
    remove_reaction_from_pool,
    save_gif_url,
    set_bot_style,
    set_chat_enabled,
    set_chat_mode,
    set_updates_channel,
    share_links_daily_limit,
    update_embed_template,
)
from layout_v2 import (
    assign_button_custom_ids,
    build_layout_view,
    validate_layout_v2_payload,
)
from message_options import sanitize_send_options, send_kwargs
from utils import LRUDict
import r2

log = logging.getLogger(__name__)

# Rate limit por IP de las acciones que escriben o disparan trabajo pesado.
_rate_post: LRUDict = LRUDict(512)
_rate_delete: LRUDict = LRUDict(512)
_rate_gif_verify: LRUDict = LRUDict(512)
# user_id -> (expira_monotonic, [guilds con manage_guild]) — cache 5 min para
# no golpear a Discord en cada request.
_user_guilds_cache: LRUDict = LRUDict(256)
_runner: web.AppRunner | None = None

_DISCORD_API = "https://discord.com/api"
_ADMINISTRATOR = 1 << 3
_MANAGE_GUILD = 1 << 5
_GUILDS_CACHE_TTL = 300.0
_PUBLIC_GETS = ("/health",)


def _client_ip(request: web.Request) -> str:
    """IP real del cliente: detrás de Cloudflare + nginx, request.remote es siempre 127.0.0.1."""
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote
        or "unknown"
    )


@web.middleware
async def _cors_middleware(request: web.Request, handler) -> web.StreamResponse:
    origin = request.headers.get("Origin", "")
    if request.method == "OPTIONS":
        resp: web.StreamResponse = web.Response()
    else:
        resp = await handler(request)
    if (
        DASHBOARD_ENABLED
        and origin
        and (origin == DASHBOARD_BASE_URL or origin in LANDING_ORIGINS)
    ):
        # Origen confiable: eco del origin + credentials para que las cookies de
        # sesión viajen. No va por el comodín "*" de abajo: Allow-Origin "*" y
        # Allow-Credentials son incompatibles.
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    elif request.method in ("GET", "OPTIONS") and request.path in _PUBLIC_GETS:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ---------------- Permisos por guild ----------------


def _filter_manage_guilds(guilds: list[dict]) -> list[dict]:
    """Filtra los guilds donde el usuario es owner o tiene MANAGE_GUILD/ADMINISTRATOR."""
    manage = []
    for g in guilds:
        try:
            perms = int(g.get("permissions") or 0)
        except (TypeError, ValueError):
            perms = 0
        if g.get("owner") or perms & (_MANAGE_GUILD | _ADMINISTRATOR):
            manage.append(g)
    return manage


async def _fetch_manage_guilds(request: web.Request) -> list[dict] | None:
    """Guilds del usuario donde tiene MANAGE_GUILD/owner, cacheados 5 min por user_id."""
    session = await get_session(request)
    user_id = session.get("user_id")
    token = session.get("access_token")
    if not user_id or not token:
        return None
    now = time.monotonic()
    cached = _user_guilds_cache.get(user_id)
    if cached and cached[0] > now:
        return cached[1]
    try:
        http = request.app["http"]
        async with http.get(
            f"{_DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {token}"},
        ) as r:
            if r.status != 200:
                log.warning(
                    "GET /users/@me/guilds devolvió %s para user %s "
                    "(429 = rate limit de Discord en este endpoint)",
                    r.status,
                    user_id,
                )
                if r.status == 429 and cached:
                    # Rate limit transitorio: mejor servir la lista vencida que desloguear.
                    return cached[1]
                return None
            guilds = await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        log.exception("Fallo consultando /users/@me/guilds")
        return None
    manage = _filter_manage_guilds(guilds)
    _user_guilds_cache[user_id] = (now + _GUILDS_CACHE_TTL, manage)
    return manage


async def check_guild_access(
    request: web.Request, guild_id: int
) -> web.Response | None:
    """None si el usuario puede administrar el guild; si no, la respuesta de error."""
    manage = await _fetch_manage_guilds(request)
    if manage is None:
        return web.json_response(
            {"error": "sesión expirada, inicia sesión de nuevo"}, status=401
        )
    if not any(int(g["id"]) == guild_id for g in manage):
        return web.json_response({"error": "acceso denegado"}, status=403)
    return None


def guild_api(handler):
    """Handler de API por guild: exige login + manage_guild + que el bot esté
    en ese guild, y pasa guild_id ya validado."""

    async def wrapper(request: web.Request) -> web.StreamResponse:
        session = await get_session(request)
        if not session.get("user_id"):
            return web.json_response({"error": "no autenticado"}, status=401)
        try:
            guild_id = int(request.match_info["guild_id"])
        except (KeyError, ValueError):
            return web.json_response({"error": "guild_id inválido"}, status=400)
        denied = await check_guild_access(request, guild_id)
        if denied is not None:
            return denied
        if _bot_guild(request, guild_id) is None:
            return web.json_response(
                {"error": "el bot no está en ese servidor"}, status=404
            )
        return await handler(request, guild_id)

    return wrapper


async def _json_body(request: web.Request) -> dict | None:
    try:
        data = await request.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bot_guild(request: web.Request, guild_id: int):
    return request.app["bot"].get_guild(guild_id)


async def _api_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def _rate_ok(store: LRUDict, ip: str, limit: int, window: float = 60.0) -> bool:
    now = time.monotonic()
    ts = [t for t in store.get(ip, []) if now - t < window]
    if len(ts) >= limit:
        store[ip] = ts
        return False
    ts.append(now)
    store[ip] = ts
    return True


def _valid_gif_url(url: str) -> bool:
    # Se valida el host real, no un substring: "https://evil.com/tenor.com" no pasa.
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if url.startswith(("http://", "https://")) and (
        host in ("tenor.com", "giphy.com")
        or host.endswith((".tenor.com", ".giphy.com"))
    ):
        return True
    pub = r2.public_url()
    # El prefijo termina en "/": sin eso, "https://pub.dominio.evil.com/x"
    # pasaría el startswith de "https://pub.dominio".
    return bool(pub and url.startswith(pub.rstrip("/") + "/"))


def _channel_name(guild, channel_id: int | None) -> str | None:
    if guild is None or channel_id is None:
        return None
    return getattr(guild.get_channel(channel_id), "name", None)


# ---------------- GIF API ----------------


async def _gif_add_impl(request: web.Request, guild_id: int) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_post, ip, 5):
        return web.json_response({"error": "rate limit"}, status=429)
    data = await _json_body(request)
    url = (data.get("url") or "").strip() if data else ""
    if not url or not _valid_gif_url(url):
        return web.json_response({"error": "url inválida o no permitida"}, status=400)
    inserted, evicted_id = await save_gif_url(guild_id, url)
    total = await count_gif_urls(guild_id)
    resp = {"inserted": inserted, "total": total}
    if inserted:
        gif = await get_gif_by_url(guild_id, url)
        if gif:
            resp["gif"] = gif
        if evicted_id is not None:
            resp["evicted_id"] = evicted_id
    return web.json_response(resp)


async def _gif_delete_impl(
    request: web.Request, guild_id: int, raw_id: str
) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_delete, ip, 3):
        return web.json_response({"error": "rate limit"}, status=429)
    gif_id = _to_int(raw_id)
    if gif_id is None:
        return web.json_response({"error": "id inválido"}, status=400)
    deleted = await delete_gif_url_by_id(guild_id, gif_id)
    return web.json_response({"deleted": deleted})


async def _api_me_guilds(request: web.Request) -> web.Response:
    session = await get_session(request)
    if not session.get("user_id"):
        return web.json_response({"error": "no autenticado"}, status=401)
    manage = await _fetch_manage_guilds(request)
    if manage is None:
        return web.json_response(
            {"error": "sesión expirada, inicia sesión de nuevo"}, status=401
        )
    bot = request.app["bot"]
    bot_guild_ids = {g.id for g in bot.guilds}
    # Nota del plan premium (ej. "Polar — mensual") para la tab Facturación.
    premium_notes = {g["guild_id"]: g["note"] for g in await list_premium_guilds()}
    configured, available = [], []
    for g in manage:
        gid = int(g["id"])
        icon = g.get("icon")
        icon_url = (
            f"https://cdn.discordapp.com/icons/{gid}/{icon}.png?size=128"
            if icon
            else None
        )
        if gid in bot_guild_ids:
            bot_guild = bot.get_guild(gid)
            configured.append(
                {
                    "id": str(gid),
                    "name": g.get("name", ""),
                    "icon_url": icon_url,
                    "member_count": getattr(bot_guild, "member_count", None),
                    "is_premium": is_premium_guild(gid),
                    "premium_note": premium_notes.get(gid),
                }
            )
        else:
            available.append(
                {
                    "id": str(gid),
                    "name": g.get("name", ""),
                    "icon_url": icon_url,
                    "invite_url": get_invite_url(str(gid)),
                }
            )
    return web.json_response({"configured": configured, "available": available})


# ---------------- API: canales y roles ----------------


@guild_api
async def _api_channels(request: web.Request, guild_id: int) -> web.Response:
    # guild_api ya garantiza que el bot está en el guild.
    guild = _bot_guild(request, guild_id)
    channels = []
    for c in guild.text_channels:
        perms = c.permissions_for(guild.me)
        channels.append(
            {
                "id": str(c.id),
                "name": c.name,
                # Para marcar "canal sin permisos" en los selectores del dashboard.
                "can_send": perms.view_channel and perms.send_messages,
            }
        )
    return web.json_response({"channels": channels})


@guild_api
async def _api_roles(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    roles = [
        {"id": str(r.id), "name": r.name, "color": f"#{r.colour.value:06x}"}
        for r in guild.roles
        if not r.is_default()
    ]
    return web.json_response({"roles": roles})


# ---------------- API: chat ----------------


@guild_api
async def _api_chat_get(request: web.Request, guild_id: int) -> web.Response:
    settings = await get_chat_settings(guild_id)
    channel_id = settings["channel_id"]
    return web.json_response(
        {
            "enabled": settings["enabled"],
            "channel_id": str(channel_id) if channel_id else None,
        }
    )


@guild_api
async def _api_chat_put(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    if data is None or not isinstance(data.get("enabled"), bool):
        return web.json_response({"error": "body inválido"}, status=400)
    if "channel_id" not in data:
        # Dashboard nuevo: el toggle solo prende/apaga la respuesta a menciones,
        # sin pisar el chat_channel_id legacy que administra el panel viejo.
        await set_chat_enabled(guild_id, data["enabled"])
        return web.json_response({"ok": True})
    channel_id = None
    if data.get("channel_id") is not None:
        channel_id = _to_int(data["channel_id"])
        if channel_id is None:
            return web.json_response({"error": "channel_id inválido"}, status=400)
    await set_chat_mode(guild_id, data["enabled"], channel_id)
    return web.json_response({"ok": True})


# ---------------- API: corpus (canales ignorados) ----------------


@guild_api
async def _api_corpus_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    channel_ids = await list_ignored_channels(guild_id)
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)} for cid in channel_ids
    ]
    return web.json_response({"channels": channels})


@guild_api
async def _api_corpus_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    added = await add_ignored_channel(guild_id, channel_id)
    return web.json_response({"added": added})


@guild_api
async def _api_corpus_delete(request: web.Request, guild_id: int) -> web.Response:
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    removed = await remove_ignored_channel(guild_id, channel_id)
    return web.json_response({"removed": removed})


# ---------------- API: dashboard nuevo (chat-channels, updates, stats, estilo) --


@guild_api
async def _api_chat_channels_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)}
        for cid in await list_chat_channels(guild_id)
    ]
    return web.json_response({"channels": channels})


@guild_api
async def _api_chat_channels_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    added = await add_chat_channel(guild_id, channel_id)
    return web.json_response({"added": added})


@guild_api
async def _api_chat_channels_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    removed = await remove_chat_channel(guild_id, channel_id)
    return web.json_response({"removed": removed})


@guild_api
async def _api_updates_get(request: web.Request, guild_id: int) -> web.Response:
    channel_id = await get_updates_channel(guild_id)
    return web.json_response({"channel_id": str(channel_id) if channel_id else None})


@guild_api
async def _api_updates_put(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    channel_id = None
    if data.get("channel_id") is not None:
        channel_id = _to_int(data["channel_id"])
        if channel_id is None:
            return web.json_response({"error": "channel_id inválido"}, status=400)
    await set_updates_channel(guild_id, channel_id)
    return web.json_response({"ok": True})


@guild_api
async def _api_stats(request: web.Request, guild_id: int) -> web.Response:
    """Métricas del bot en el guild para la tab INICIO del dashboard.

    Dos familias distintas en la misma respuesta: los **estados** (cuánto tiene
    guardado y de dónde lee ahora mismo) y los **logs** (`counters`), que son
    acumulados históricos de lo que el bot mandó.
    """
    guild = _bot_guild(request, guild_id)
    per_channel = await count_corpus_by_channel(guild_id)
    ignored = set(await list_ignored_channels(guild_id))
    text_channels = list(getattr(guild, "text_channels", []))
    chat_channels = await list_chat_channels(guild_id)
    return web.json_response(
        {
            "corpus_total": await count_guild_corpus_messages(guild_id),
            # Canales que el bot lee = los de texto menos los ignorados.
            "reading_channels": len([c for c in text_channels if c.id not in ignored]),
            "text_channels": len(text_channels),
            # Lista vacía = participa en todos (ver la allowlist en cogs/chat.py).
            "reply_channels": len(chat_channels) or len(text_channels),
            "counters": await get_counters(guild_id),
            "corpus_by_channel": [
                {
                    "channel_id": str(r["channel_id"]),
                    "name": _channel_name(guild, r["channel_id"]),
                    "count": r["count"],
                }
                for r in per_channel[:8]
            ],
            "reactions": len(await list_reaction_pool(guild_id)),
            "gifs": await count_gif_urls(guild_id),
            "frases": len(await list_frases_especiales(guild_id)),
            "member_count": getattr(guild, "member_count", None),
        }
    )


_STYLE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _valid_r2_url(url) -> bool:
    pub = r2.public_url()
    return isinstance(url, str) and bool(pub) and url.startswith(pub.rstrip("/") + "/")


async def _r2_image_datauri(request: web.Request, url: str) -> str | None:
    """Baja una imagen ya subida a R2 y la vuelve data URI (formato que pide
    la API de Discord para avatar/banner)."""
    try:
        async with request.app["http"].get(url) as r:
            if r.status != 200:
                return None
            data = await r.read()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        log.exception("No se pudo bajar %s de R2 para el estilo del bot", url)
        return None
    ext = _sniff_image(data)
    if ext is None:
        return None
    return f"data:{_STYLE_MIME[ext]};base64,{base64.b64encode(data).decode()}"


@guild_api
async def _api_style_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    me = guild.me
    style = await get_bot_style(guild_id)
    return web.json_response(
        {
            **style,
            "current_nick": (me.nick or me.name) if me else None,
            "current_avatar_url": str(me.display_avatar.url) if me else None,
        }
    )


@guild_api
async def _api_style_put(request: web.Request, guild_id: int) -> web.Response:
    """Aplica el estilo del bot en el guild: apodo vía Member.edit y
    avatar/banner por PATCH /guilds/{id}/members/@me con las imágenes que el
    modal ya subió a R2 (mismo uploader que el editor de embeds).

    Solo se tocan avatar/banner si la clave viene en el body (checkboxes
    "Editar Avatar"/"Editar Banner" del modal); null explícito = remover."""
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    nick = str(data.get("nick") or "").strip()[:32]
    guild = _bot_guild(request, guild_id)
    current = await get_bot_style(guild_id)
    profile_patch: dict = {}
    avatar_url = current["avatar_url"]
    banner_url = current["banner_url"]
    for key, field in (("avatar_url", "avatar"), ("banner_url", "banner")):
        if key not in data:
            continue
        url = data[key]
        if url is not None and not _valid_r2_url(url):
            return web.json_response(
                {"error": f"{key} inválida: sube la imagen desde el panel"}, status=400
            )
        if url is None:
            profile_patch[field] = None
        else:
            datauri = await _r2_image_datauri(request, url)
            if datauri is None:
                return web.json_response(
                    {"error": "no se pudo leer la imagen subida, intenta de nuevo"},
                    status=502,
                )
            profile_patch[field] = datauri
        if key == "avatar_url":
            avatar_url = url
        else:
            banner_url = url

    try:
        if guild.me and (guild.me.nick or "") != nick:
            await guild.me.edit(nick=nick or None)
    except discord.Forbidden:
        return web.json_response(
            {"error": "el bot no tiene permiso para cambiar su apodo en este servidor"},
            status=403,
        )
    except discord.HTTPException as e:
        return web.json_response(
            {"error": f"Discord rechazó el apodo: {e.text or e}"}, status=400
        )

    warning = None
    if profile_patch:
        # ponytail: request crudo — discord.py 2.7 no expone avatar/banner de
        # guild para bots; si Discord lo rechaza se guarda igual la URL (sirve
        # para el preview del panel) y se avisa por warning.
        try:
            await request.app["bot"].http.request(
                discord.http.Route(
                    "PATCH", "/guilds/{guild_id}/members/@me", guild_id=guild_id
                ),
                json=profile_patch,
            )
        except discord.HTTPException as e:
            warning = f"Discord no aceptó el avatar/banner: {e.text or e}"
            log.warning("PATCH members/@me falló en guild %s: %s", guild_id, e)

    await set_bot_style(guild_id, nick or None, avatar_url, banner_url)
    return web.json_response({"ok": True, "warning": warning})


# ---------------- API: reacciones ----------------


@guild_api
async def _api_reacciones_get(request: web.Request, guild_id: int) -> web.Response:
    pool = await list_reaction_pool(guild_id)
    return web.json_response({"reactions": pool})


@guild_api
async def _api_reacciones_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    emoji = (data.get("emoji") or "").strip() if data else ""
    if not emoji:
        return web.json_response({"error": "emoji vacío"}, status=400)
    added = await add_reaction_to_pool(guild_id, emoji)
    return web.json_response({"added": added})


@guild_api
async def _api_reacciones_delete(request: web.Request, guild_id: int) -> web.Response:
    reaction_id = _to_int(request.match_info.get("reaction_id"))
    if reaction_id is None:
        return web.json_response({"error": "reaction_id inválido"}, status=400)
    removed = await remove_reaction_from_pool(guild_id, reaction_id)
    return web.json_response({"removed": removed})


# ---------------- API: frases ----------------


@guild_api
async def _api_frases_get(request: web.Request, guild_id: int) -> web.Response:
    frases = await list_frases_especiales(guild_id)
    return web.json_response(
        {
            "frases": [
                {"id": f["id"], "frase": f["frase"], "user_name": f["user_name"]}
                for f in frases
            ]
        }
    )


@guild_api
async def _api_frases_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    frase = (data.get("frase") or "").strip() if data else ""
    if not frase:
        return web.json_response({"error": "frase vacía"}, status=400)
    session = await get_session(request)
    added = await add_frase_especial(
        guild_id, int(session["user_id"]), str(session.get("username", "panel")), frase
    )
    return web.json_response({"added": added})


@guild_api
async def _api_frases_delete(request: web.Request, guild_id: int) -> web.Response:
    frase_id = _to_int(request.match_info.get("frase_id"))
    if frase_id is None:
        return web.json_response({"error": "frase_id inválido"}, status=400)
    deleted = await delete_frase_especial(guild_id, frase_id)
    return web.json_response({"deleted": deleted})


# ---------------- API: gifs por guild ----------------


@guild_api
async def _api_server_gifs_get(request: web.Request, guild_id: int) -> web.Response:
    gifs = await list_gif_urls(guild_id)
    return web.json_response({"gifs": gifs, "total": len(gifs)})


@guild_api
async def _api_server_gifs_post(request: web.Request, guild_id: int) -> web.Response:
    return await _gif_add_impl(request, guild_id)


@guild_api
async def _api_server_gifs_delete(request: web.Request, guild_id: int) -> web.Response:
    return await _gif_delete_impl(
        request, guild_id, request.match_info.get("gif_id", "")
    )


@guild_api
async def _api_server_gifs_verify(request: web.Request, guild_id: int) -> web.Response:
    # Dispara el chequeo en background: con cientos/miles de GIFs y el
    # espaciado entre requests (HEALTH_CHECK_DELAY) esto puede tardar
    # minutos, muy por encima de cualquier timeout razonable de request.
    ip = _client_ip(request)
    if not _rate_ok(_rate_gif_verify, ip, 1, window=300.0):
        return web.json_response({"error": "rate limit"}, status=429)
    total = await count_gif_urls(guild_id)
    asyncio.create_task(run_gif_health_check(guild_id))
    return web.json_response(
        {"started": True, "total": total, "checking": min(total, HEALTH_CHECK_BATCH)}
    )


# ---------------- API: embeds (editor del panel) ----------------

# Límites reales de Discord para embeds (title/description/fields/etc.).
_EMBED_MAX_TITLE = 256
_EMBED_MAX_DESCRIPTION = 4096
_EMBED_MAX_FIELDS = 25
_EMBED_MAX_FIELD_NAME = 256
_EMBED_MAX_FIELD_VALUE = 1024
_EMBED_MAX_FOOTER = 2048
_EMBED_MAX_AUTHOR = 256
_EMBED_MAX_TOTAL = 6000
_EMBED_MAX_COUNT = 10  # Discord: máximo de embeds por mensaje en modo clásico.


def embed_char_count(embed: dict) -> int:
    """Caracteres que Discord cuenta contra el límite de 6000 por mensaje:
    title + description + footer.text + author.name + fields (name y value).
    Espejo de embedChars() en panel.js — mantener en sync."""
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
    if len(title) > _EMBED_MAX_TITLE:
        return f"title supera los {_EMBED_MAX_TITLE} caracteres"
    if len(description) > _EMBED_MAX_DESCRIPTION:
        return f"description supera los {_EMBED_MAX_DESCRIPTION} caracteres"
    if not isinstance(fields, list) or len(fields) > _EMBED_MAX_FIELDS:
        return f"fields admite máximo {_EMBED_MAX_FIELDS} elementos"
    if len(footer_text) > _EMBED_MAX_FOOTER:
        return f"footer.text supera los {_EMBED_MAX_FOOTER} caracteres"
    if len(author_name) > _EMBED_MAX_AUTHOR:
        return f"author.name supera los {_EMBED_MAX_AUTHOR} caracteres"

    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            return f"field {i + 1} inválido"
        name = f.get("name") or ""
        value = f.get("value") or ""
        if not isinstance(name, str) or not isinstance(value, str):
            return f"field {i + 1}: name y value deben ser texto"
        if not name.strip() or not value.strip():
            return f"field {i + 1}: name y value no pueden estar vacíos"
        if len(name) > _EMBED_MAX_FIELD_NAME:
            return f"field {i + 1}: name supera los {_EMBED_MAX_FIELD_NAME} caracteres"
        if len(value) > _EMBED_MAX_FIELD_VALUE:
            return (
                f"field {i + 1}: value supera los {_EMBED_MAX_FIELD_VALUE} caracteres"
            )
    if embed_char_count(embed) > _EMBED_MAX_TOTAL:
        return f"el embed supera los {_EMBED_MAX_TOTAL} caracteres en total"

    # Discord rechaza embeds sin contenido visible.
    if not any(
        (
            title.strip(),
            description.strip(),
            fields,
            footer_text.strip(),
            author_name.strip(),
            embed.get("image"),
            embed.get("thumbnail"),
        )
    ):
        return "el embed está vacío: completa al menos un campo"

    color = embed.get("color")
    if isinstance(color, str):
        try:
            color = int(color.lstrip("#"), 16)
        except ValueError:
            return "color inválido: usa formato #RRGGBB"
        embed["color"] = color
    if color is not None and not (isinstance(color, int) and 0 <= color <= 0xFFFFFF):
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
    if len(embeds) > _EMBED_MAX_COUNT:
        return f"máximo {_EMBED_MAX_COUNT} embeds por mensaje"
    for i, embed in enumerate(embeds):
        err = validate_embed_payload(embed)
        if err:
            return f"Embed {i + 1}: {err}"
    total = sum(embed_char_count(e) for e in embeds)
    if total > _EMBED_MAX_TOTAL:
        return (
            f"el mensaje supera los {_EMBED_MAX_TOTAL} caracteres "
            f"sumando todos los embeds ({total})"
        )
    return None


def _extract_embeds(data: dict) -> tuple[list, str | None]:
    """Saca la lista de embeds del body y la valida. Acepta el formato nuevo
    ({"embeds": [...]}); no hay clientes con el formato viejo de {"embed": {...}}
    porque el panel es el único consumidor y ya manda arrays."""
    embeds = data.get("embeds")
    err = validate_embeds_payload(embeds)
    return (embeds or []), err


def _block_text(b: dict) -> str:
    kind = b.get("type")
    if kind == "text":
        return (b.get("content") or "").strip()
    if kind == "section":
        for tx in b.get("texts", []) or []:
            if isinstance(tx, str) and tx.strip():
                return tx.strip()
    if kind == "container":
        for c in b.get("children", []) or []:
            s = _block_text(c)
            if s:
                return s
    return ""


def _layout_preview(layout: dict) -> str:
    """Texto legible del primer bloque con contenido, para el listado de
    /settings en Discord (donde `message` no puede ser NULL)."""
    for b in layout.get("blocks", []) or []:
        s = _block_text(b)
        if s:
            return s[:60]
    return "[layout]"


def _extract_content(data: dict) -> tuple[str, str, str, str | None]:
    """Valida el contenido del body según content_mode y devuelve
    (content_mode, json_a_guardar, preview_legible, error).

    - 'layout_v2': valida contra validate_layout_v2_payload, guarda el layout.
    - 'classic_embed' (default): valida el array de embeds, guarda la lista.
    Los dos formatos comparten la columna embed_json; content_mode desambigua.

    Si el body trae send_options (envío silencioso / restricción de menciones,
    Fase 5.6), se guardan dentro del mismo JSON: como clave extra del dict del
    layout, o envolviendo la lista de embeds en {"embeds": [...],
    "send_options": {...}} — normalize_embeds_json ya conoce ese wrapper."""
    mode = data.get("content_mode") or "classic_embed"
    options = sanitize_send_options(data.get("send_options"))
    if mode == "layout_v2":
        layout = data.get("layout")
        err = validate_layout_v2_payload(layout)
        if err:
            return "", "", "", err
        if options:
            layout["send_options"] = options
        return mode, json.dumps(layout), _layout_preview(layout), None
    embeds, err = _extract_embeds(data)
    if err:
        return "", "", "", err
    preview = (embeds[0].get("title") or "").strip()[:60] or "[embed]"
    payload = {"embeds": embeds, "send_options": options} if options else embeds
    return "classic_embed", json.dumps(payload), preview, None


async def _register_role_buttons(bot, guild_id: int, assignments: list[dict]) -> None:
    """Persiste el mapeo custom_id -> rol (layout_button_actions) y registra
    los botones nuevos como vista persistente EN VIVO, para que funcionen sin
    esperar el próximo reinicio del bot. `assignments` sale de
    layout_v2.assign_button_custom_ids (vacío si el layout no tiene botones de
    rol nuevos, en cuyo caso esto no hace nada)."""
    if not assignments:
        return
    from cogs.layout_buttons import register_button_actions

    rows = []
    for a in assignments:
        action_data = json.dumps({"role_id": a["role_id"]})
        await add_button_action(a["custom_id"], guild_id, "role_toggle", action_data)
        rows.append(
            {
                "custom_id": a["custom_id"],
                "guild_id": guild_id,
                "action_type": "role_toggle",
                "action_data": action_data,
            }
        )
    await register_button_actions(bot, rows)


def _embed_target_channel(request: web.Request, guild_id: int, channel_id: int | None):
    """(canal, None) si el canal es del guild y el bot puede mandar embeds ahí;
    si no, (None, respuesta de error)."""
    if channel_id is None:
        return None, web.json_response({"error": "channel_id inválido"}, status=400)
    guild = _bot_guild(request, guild_id)
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return None, web.json_response(
            {"error": "el canal no existe en este servidor"}, status=400
        )
    perms = channel.permissions_for(guild.me)
    if not perms.send_messages or not perms.embed_links:
        return None, web.json_response(
            {"error": "el bot no tiene permiso de enviar mensajes/embeds en ese canal"},
            status=403,
        )
    return channel, None


@guild_api
async def _api_embeds_send(request: web.Request, guild_id: int) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_post, ip, 5):
        return web.json_response({"error": "rate limit"}, status=429)
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    mode = data.get("content_mode") or "classic_embed"
    if mode == "layout_v2":
        err = validate_layout_v2_payload(data.get("layout"))
    else:
        _, err = _extract_embeds(data)
    if err:
        return web.json_response({"error": err}, status=400)
    channel, denied = _embed_target_channel(
        request, guild_id, _to_int(data.get("channel_id"))
    )
    if denied is not None:
        return denied
    extra = send_kwargs(sanitize_send_options(data.get("send_options")))
    try:
        if mode == "layout_v2":
            layout = data["layout"]
            assignments = assign_button_custom_ids(layout)
            await _register_role_buttons(request.app["bot"], guild_id, assignments)
            await channel.send(view=build_layout_view(layout), **extra)
        else:
            await channel.send(
                embeds=[discord.Embed.from_dict(e) for e in data["embeds"]], **extra
            )
    except discord.HTTPException as e:
        # Típicamente una URL de imagen/ícono que Discord rechaza.
        return web.json_response(
            {"error": f"Discord rechazó el contenido: {e.text or e}"}, status=400
        )
    return web.json_response({"sent": True})


@guild_api
async def _api_embeds_schedule(request: web.Request, guild_id: int) -> web.Response:
    """Programa un embed como anuncio (misma tabla/worker que los anuncios de
    texto de /settings, con embed_json en la columna nueva)."""
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    content_mode, payload, preview, err = _extract_content(data)
    if err:
        return web.json_response({"error": err}, status=400)
    channel, denied = _embed_target_channel(
        request, guild_id, _to_int(data.get("channel_id"))
    )
    if denied is not None:
        return denied

    if content_mode == "layout_v2":
        # Mintea los custom_id de botones de rol UNA vez, acá: el JSON con los
        # custom_id ya horneados es lo que queda guardado en embed_json, así
        # que cada disparo periódico del anuncio reutiliza el mismo mapeo
        # (nunca se re-mintea en el loop de anuncios.py).
        layout = data["layout"]
        assignments = assign_button_custom_ids(layout)
        await _register_role_buttons(request.app["bot"], guild_id, assignments)
        payload = json.dumps(layout)

    # `mode` es la cadencia del anuncio (interval/daily), distinta de content_mode.
    mode = data.get("mode")
    interval_minutes = hour = minute = None
    if mode == "interval":
        interval_minutes = _to_int(data.get("interval_minutes"))
        # Mismo rango que la UI de anuncios de /settings (5-1440 minutos).
        if interval_minutes is None or not (5 <= interval_minutes <= 1440):
            return web.json_response(
                {"error": "interval_minutes debe estar entre 5 y 1440"}, status=400
            )
    elif mode == "daily":
        hour = _to_int(data.get("hour"))
        minute = _to_int(data.get("minute"))
        if (
            hour is None
            or minute is None
            or not (0 <= hour <= 23 and 0 <= minute <= 59)
        ):
            return web.json_response(
                {"error": "hora inválida (HH 0-23, MM 0-59)"}, status=400
            )
    else:
        return web.json_response(
            {"error": "mode debe ser 'interval' o 'daily'"}, status=400
        )

    session = await get_session(request)
    new_id = await add_scheduled_announcement(
        guild_id,
        channel.id,
        preview,
        mode,
        int(session["user_id"]),
        interval_minutes=interval_minutes,
        hour=hour,
        minute=minute,
        embed_json=payload,
        content_mode=content_mode,
    )
    if new_id is None:
        return web.json_response(
            {
                "error": "límite de anuncios programados alcanzado — elimina uno desde /settings en Discord"
            },
            status=409,
        )
    return web.json_response({"id": new_id})


# ---------------- Embeds compartidos por link ----------------


def _valid_share_id(share_id: str) -> bool:
    """Formato de los ids que emite generate_unique_share_id (alfanuméricos,
    8+). El rango laxo evita que un id malformado llegue a la DB o a un
    redirect."""
    return share_id.isalnum() and 4 <= len(share_id) <= 32


@guild_api
async def _api_embeds_share(request: web.Request, guild_id: int) -> web.Response:
    """Genera un link compartible con el contenido del editor. Mismo shape de
    body que /embeds/send (embeds + send_options), misma validación."""
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    embeds, err = _extract_embeds(data)
    if err:
        return web.json_response({"error": err}, status=400)
    if await count_shared_embeds_today(guild_id) >= share_links_daily_limit():
        return web.json_response(
            {
                "error": "límite diario de links compartidos alcanzado — intenta de nuevo mañana"
            },
            status=429,
        )
    options = sanitize_send_options(data.get("send_options"))
    payload = {"embeds": embeds}
    if options:
        payload["send_options"] = options
    share_id, expires_at = await add_shared_embed(json.dumps(payload), guild_id)
    return web.json_response(
        {
            "share_id": share_id,
            "url": f"{LANDING_URL}/es/perfil?share={share_id}",
            "expires_at": expires_at,
        }
    )


async def _api_embeds_share_get(request: web.Request) -> web.Response:
    """Público y sin scope de guild: el payload se pide desde el panel de
    cualquier servidor, incluso antes de haber elegido uno."""
    share_id = request.match_info.get("share_id", "")
    payload = await get_shared_embed(share_id) if _valid_share_id(share_id) else None
    if payload is None:
        return web.json_response(
            {"error": "Este link ya expiró o no existe"}, status=404
        )
    return web.json_response(json.loads(payload))


def _template_row_to_json(t: dict) -> dict:
    content_mode = t.get("content_mode") or "classic_embed"
    out = {
        "id": t["id"],
        "name": t["name"],
        "content_mode": content_mode,
        # None si la plantilla no guarda opciones de envío (el caso común).
        "send_options": extract_send_options(t["embed_json"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
    }
    if content_mode == "layout_v2":
        out["layout"] = json.loads(t["embed_json"])
    else:
        # Siempre una lista, incluso para plantillas viejas guardadas como dict
        # suelto (normalize_embeds_json las envuelve al leer).
        out["embeds"] = normalize_embeds_json(t["embed_json"])
    return out


@guild_api
async def _api_embed_templates_get(request: web.Request, guild_id: int) -> web.Response:
    templates = await list_embed_templates(guild_id)
    return web.json_response(
        {
            "templates": [_template_row_to_json(t) for t in templates],
            "total": len(templates),
            "limit": embed_template_limit(guild_id),
        }
    )


def _template_body(data: dict | None) -> tuple[str, str, str] | web.Response:
    """Valida el body común de POST/PUT de plantillas: (name, json, content_mode)
    o una respuesta de error."""
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    name = str(data.get("name") or "").strip()[:100]
    if not name:
        return web.json_response(
            {"error": "la plantilla necesita un nombre"}, status=400
        )
    content_mode, payload, _preview, err = _extract_content(data)
    if err:
        return web.json_response({"error": err}, status=400)
    return name, payload, content_mode


@guild_api
async def _api_embed_templates_post(
    request: web.Request, guild_id: int
) -> web.Response:
    parsed = _template_body(await _json_body(request))
    if isinstance(parsed, web.Response):
        return parsed
    name, payload, content_mode = parsed
    new_id = await add_embed_template(guild_id, name, payload, content_mode)
    if new_id is None:
        return web.json_response(
            {
                "error": "límite de plantillas alcanzado — elimina una antes de guardar otra"
            },
            status=409,
        )
    return web.json_response({"id": new_id})


@guild_api
async def _api_embed_template_put(request: web.Request, guild_id: int) -> web.Response:
    template_id = _to_int(request.match_info.get("template_id"))
    if template_id is None:
        return web.json_response({"error": "template_id inválido"}, status=400)
    parsed = _template_body(await _json_body(request))
    if isinstance(parsed, web.Response):
        return parsed
    name, payload, content_mode = parsed
    updated = await update_embed_template(
        template_id, guild_id, name, payload, content_mode
    )
    if not updated:
        return web.json_response({"error": "plantilla no encontrada"}, status=404)
    return web.json_response({"updated": True})


@guild_api
async def _api_embed_template_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    template_id = _to_int(request.match_info.get("template_id"))
    if template_id is None:
        return web.json_response({"error": "template_id inválido"}, status=400)
    deleted = await delete_embed_template(template_id, guild_id)
    return web.json_response({"deleted": deleted})


# ---------------- API: emojis, validación en vivo y subida de imágenes ------


@guild_api
async def _api_emojis(request: web.Request, guild_id: int) -> web.Response:
    """Emojis custom del guild, para la pestaña Emoji del popover de inserción."""
    guild = _bot_guild(request, guild_id)
    emojis = [
        {"id": str(e.id), "name": e.name, "animated": e.animated, "url": str(e.url)}
        for e in guild.emojis
    ]
    return web.json_response({"emojis": emojis})


@guild_api
async def _api_embeds_validate(request: web.Request, guild_id: int) -> web.Response:
    """Validación en vivo para el modo JSON del editor: corre el mismo
    validador del backend (una sola fuente de verdad, sin duplicar el schema
    en el cliente) y devuelve el error específico o ok."""
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    if (data.get("content_mode") or "classic_embed") == "layout_v2":
        err = validate_layout_v2_payload(data.get("layout"))
    else:
        err = validate_embeds_payload(data.get("embeds"))
    return web.json_response({"ok": err is None, "error": err})


# Firmas mágicas de los formatos de imagen que acepta el uploader del editor.
def _sniff_image(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


async def _store_upload(data: bytes, guild_id: int, ext: str) -> str | None:
    """Sube bytes de imagen (ya validados por _sniff_image) a R2.

    La key deriva del md5 del CONTENIDO: subir dos veces la misma imagen
    produce la misma key (el segundo put pisa el primero en R2, sin objeto
    duplicado), y el frontend además ofrece "reusar archivo ya subido" para ni
    siquiera repetir el request."""
    digest = hashlib.md5(data, usedforsecurity=False).hexdigest()
    return await asyncio.to_thread(
        r2.upload_image_bytes_sync, f"panel-upload:{digest}", data, guild_id, ext
    )


_rate_upload: LRUDict = LRUDict(512)


@guild_api
async def _api_embeds_upload(request: web.Request, guild_id: int) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_upload, ip, 10):
        return web.json_response({"error": "rate limit"}, status=429)
    if not r2.available():
        return web.json_response(
            {"error": "almacenamiento de imágenes no configurado"}, status=503
        )
    max_bytes = env_int("MAX_EMBED_IMAGE_UPLOAD_BYTES", 8 * 1024 * 1024)
    if request.content_length and request.content_length > max_bytes:
        return web.json_response(
            {"error": f"la imagen supera el máximo de {max_bytes // (1024 * 1024)} MB"},
            status=413,
        )
    data = await request.read()
    if len(data) > max_bytes:
        return web.json_response(
            {"error": f"la imagen supera el máximo de {max_bytes // (1024 * 1024)} MB"},
            status=413,
        )
    if not data:
        return web.json_response({"error": "archivo vacío"}, status=400)
    ext = _sniff_image(data)
    if ext is None:
        return web.json_response(
            {"error": "el archivo no es una imagen válida (png, jpg, gif o webp)"},
            status=400,
        )
    url = await _store_upload(data, guild_id, ext)
    if url is None:
        return web.json_response(
            {"error": "no se pudo subir la imagen, intenta de nuevo"}, status=502
        )
    return web.json_response({"url": url})


# ---------------- Auth OAuth2 ----------------


def _avatar_url(user: dict) -> str:
    avatar = user.get("avatar")
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=64"
    index = (int(user["id"]) >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


async def _auth_login(request: web.Request) -> web.StreamResponse:
    session = await get_session(request)
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = urlencode(
        {
            "client_id": DISCORD_CLIENT_ID,
            "redirect_uri": f"{DASHBOARD_BASE_URL}/auth/callback",
            "response_type": "code",
            "scope": "identify email guilds",
            "state": state,
        }
    )
    raise web.HTTPFound(f"https://discord.com/oauth2/authorize?{params}")


async def _auth_callback(request: web.Request) -> web.StreamResponse:
    session = await get_session(request)
    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state or state != session.pop("oauth_state", None):
        raise web.HTTPFound("/auth/error")

    try:
        http = request.app["http"]
        # Canje del code por access_token (grant authorization_code).
        async with http.post(
            f"{_DISCORD_API}/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{DASHBOARD_BASE_URL}/auth/callback",
            },
        ) as r:
            if r.status != 200:
                raise web.HTTPFound("/auth/error")
            access = (await r.json()).get("access_token")

        # Quién es el usuario.
        async with http.get(
            f"{_DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {access}"}
        ) as r:
            if r.status != 200:
                raise web.HTTPFound("/auth/error")
            user = await r.json()

        # Guilds del usuario, para verificar que administre alguno.
        async with http.get(
            f"{_DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access}"},
        ) as r:
            if r.status != 200:
                raise web.HTTPFound("/auth/error")
            user_guilds = await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        log.exception("Fallo llamando a la API de Discord en el callback OAuth2")
        raise web.HTTPFound("/auth/error")

    manage = _filter_manage_guilds(user_guilds)
    if not manage:
        raise web.HTTPFound("/auth/error?reason=no_guilds")

    session["user_id"] = user["id"]
    session["username"] = user.get("global_name") or user.get("username") or "admin"
    session["avatar_url"] = _avatar_url(user)
    session["email"] = user.get("email") or ""
    # Solo server-side (cookie cifrada): se usa para consultar /users/@me/guilds.
    session["access_token"] = access
    # Precarga el cache: /users/@me/guilds tiene rate limit estricto por token
    # (~1 req/s) y sin esto el primer request autenticado recibiría 429.
    _user_guilds_cache[user["id"]] = (time.monotonic() + _GUILDS_CACHE_TTL, manage)
    # El panel ya no existe; el sitio nuevo define su propio destino post-login.
    raise web.HTTPFound(LANDING_URL)


async def _auth_logout(request: web.Request) -> web.StreamResponse:
    session = await get_session(request)
    # Sin esto, un re-login del mismo user reutilizaría la lista de guilds del token anterior.
    _user_guilds_cache.pop(session.get("user_id"), None)
    session.invalidate()
    raise web.HTTPFound(LANDING_URL)


async def _api_me(request: web.Request) -> web.Response:
    """Quién soy. Lo consume el navbar de la landing, que ahora vive en el mismo
    origen (purgito.app): la llamada es same-origin y la cookie viaja sola, sin
    CORS de por medio.

    Sin sesión responde 200 con logged_in=False, nunca 401: el navbar solo
    decide qué variante pintar y un 401 ensuciaría la consola del navegador.
    """
    session = await get_session(request)
    body = {"logged_in": False}
    if session.get("user_id"):
        body = {
            "logged_in": True,
            # El id es el snowflake de Discord: la cabecera del perfil saca de
            # ahí la fecha de creación de la cuenta, sin pedir nada más.
            "user_id": session.get("user_id", ""),
            "name": session.get("username", ""),
            "avatar_url": session.get("avatar_url", ""),
            "email": session.get("email", ""),
        }
    # no-store obligatorio: la respuesta es por usuario y delante hay Cloudflare.
    return web.json_response(body, headers={"Cache-Control": "no-store"})


async def _auth_error(request: web.Request) -> web.Response:
    # HTML autocontenido: la hoja de estilos del panel ya no existe.
    if request.query.get("reason") == "no_guilds":
        message = (
            "Necesitas el permiso <em>Gestionar servidor</em> en algún servidor "
            "para poder administrar Purgito."
        )
    else:
        message = (
            "No se pudo completar el inicio de sesión con Discord. Intenta de nuevo."
        )
    body = (
        "<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>Purgito · Acceso denegado</title></head>"
        "<body style='background:#0B0C10;color:#EDEAE3;font-family:system-ui,sans-serif;"
        "display:flex;align-items:center;justify-content:center;min-height:100vh;"
        "text-align:center;padding:24px'>"
        "<div><h1 style='color:#8B6EF5'>Acceso denegado</h1>"
        f"<p>{message}</p>"
        "<a style='color:#A28BF7' href='/auth/login'>Volver a intentar</a>"
        "</div></body></html>"
    )
    return web.Response(text=body, content_type="text/html", charset="utf-8")


# ---------------- Polar.sh (premium) ----------------

# Cliente único para toda la vida del proceso; el httpx interno se libera al
# terminar el proceso.
_polar: Polar | None = (
    Polar(access_token=POLAR_ACCESS_TOKEN, server=POLAR_SERVER)
    if POLAR_ACCESS_TOKEN
    else None
)

_POLAR_ACTIVATE = ("subscription.active", "subscription.resumed")
_POLAR_DEACTIVATE = ("subscription.paused", "subscription.revoked")
# subscription.created dispara con status "trialing" cuando el producto tiene
# free trial. Sin esto, alguien que arranca un trial no tiene premium hasta que
# Polar cobra el primer pago una semana después — justo lo que rompe el trial.
# subscription.active ya cubre altas sin trial y la conversión trial→pago;
# set_premium es idempotente (INSERT OR IGNORE). subscription.revoked cubre
# "trial terminó sin método de pago válido".
_POLAR_TRIAL_STATUS = "trialing"


def _polar_plan_note(product_id) -> str:
    if product_id == POLAR_PRODUCT_ID_ANNUAL:
        return "Polar — anual"
    if product_id == POLAR_PRODUCT_ID_MONTHLY:
        return "Polar — mensual"
    return "Polar"


@guild_api
async def _api_premium_get(request: web.Request, guild_id: int) -> web.Response:
    """Estado premium del guild."""
    note = next(
        (g["note"] for g in await list_premium_guilds() if g["guild_id"] == guild_id),
        None,
    )
    return web.json_response({"premium": is_premium_guild(guild_id), "note": note})


@guild_api
async def _api_premium_checkout(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    plan = (data or {}).get("plan")
    if plan not in ("monthly", "annual"):
        return web.json_response(
            {"error": "plan inválido: usa 'monthly' o 'annual'"}, status=400
        )
    if _polar is None:
        log.error("Checkout premium pedido pero POLAR_ACCESS_TOKEN no está configurado")
        return web.json_response({"error": "pagos no disponibles"}, status=502)
    product_id = (
        POLAR_PRODUCT_ID_MONTHLY if plan == "monthly" else POLAR_PRODUCT_ID_ANNUAL
    )
    try:
        checkout = await _polar.checkouts.create_async(
            request={
                "products": [product_id],
                "metadata": {"guild_id": str(guild_id)},
                # La página de éxito del panel ya no existe: se vuelve a la
                # landing hasta que el sitio nuevo defina su propio destino.
                # {CHECKOUT_ID} lo reemplaza Polar al redirigir; no interpolar acá.
                "success_url": f"{LANDING_URL}?checkout_id={{CHECKOUT_ID}}",
            }
        )
    except Exception as exc:
        if "insufficient_scope" in str(exc):
            log.error(
                "Polar rechazó el checkout por permisos insuficientes del token "
                "(guild %s, plan %s, server %s). Verifica que POLAR_ACCESS_TOKEN "
                "sea un token de organización con permisos para crear checkouts y "
                "que apunte al entorno correcto.",
                guild_id,
                plan,
                POLAR_SERVER,
            )
            return web.json_response(
                {
                    "error": (
                        "Polar rechazó la creación del checkout por permisos "
                        "insuficientes del token"
                    )
                },
                status=502,
            )
        log.exception(
            "Fallo creando checkout de Polar (guild %s, plan %s)", guild_id, plan
        )
        return web.json_response(
            {"error": "no se pudo iniciar el pago, intenta de nuevo más tarde"},
            status=502,
        )
    return web.json_response({"checkout_url": checkout.url})


async def _webhook_polar(request: web.Request) -> web.Response:
    # Público: Polar autentica con la firma Standard Webhooks, no con sesión.
    # Sin secret, validate_event firmaría con clave vacía y cualquiera podría
    # forjar un evento válido (premium gratis): mejor rechazar de plano.
    if not POLAR_WEBHOOK_SECRET:
        log.error(
            "Webhook de Polar recibido pero POLAR_WEBHOOK_SECRET no está configurado"
        )
        return web.json_response({"error": "webhook no configurado"}, status=503)
    body = await request.read()
    try:
        event = validate_event(body, dict(request.headers), POLAR_WEBHOOK_SECRET)
        event_type = event.TYPE
        metadata = getattr(event.data, "metadata", None) or {}
        product_id = getattr(event.data, "product_id", None)
        status = getattr(event.data, "status", None)
    except WebhookVerificationError:
        log.warning(
            "Webhook de Polar con firma inválida desde %s "
            "(¿ataque o POLAR_WEBHOOK_SECRET mal configurado?)",
            _client_ip(request),
        )
        return web.json_response({"error": "firma inválida"}, status=403)
    except WebhookUnknownTypeError:
        # Firma válida pero polar-sdk 0.31.7 no modela el tipo (les pasa a
        # subscription.paused/resumed): se saca lo necesario del JSON crudo,
        # que ya fue verificado.
        payload = json.loads(body)
        event_type = payload.get("type")
        data = payload.get("data") or {}
        metadata = data.get("metadata") or {}
        product_id = data.get("product_id")
        status = data.get("status")

    # subscription.created con status "trialing" = arrancó un free trial:
    # cuenta como alta igual que subscription.active.
    is_trial_start = (
        event_type == "subscription.created" and status == _POLAR_TRIAL_STATUS
    )

    if event_type not in _POLAR_ACTIVATE + _POLAR_DEACTIVATE and not is_trial_start:
        log.debug("Webhook de Polar ignorado: %s (status=%s)", event_type, status)
        return web.json_response({"ok": True})

    guild_id = _to_int(metadata.get("guild_id") if isinstance(metadata, dict) else None)
    if guild_id is None:
        log.warning("Webhook de Polar %s sin guild_id válido en metadata", event_type)
        return web.json_response({"ok": True})

    if event_type in _POLAR_ACTIVATE or is_trial_start:
        note = _polar_plan_note(product_id)
        reason = "trial" if is_trial_start else "pago confirmado"
        was_new = await set_premium(guild_id, note)
        if was_new:
            log.info(
                "Premium activado por Polar para guild %s (%s, %s)",
                guild_id,
                note,
                reason,
            )
        else:
            # Ya estaba premium (ej: subscription.active llega después de que
            # subscription.created ya activó el trial) — set_premium es
            # idempotente, no hay nada nuevo que reportar.
            log.debug(
                "Webhook de Polar %s (%s) para guild %s: ya estaba premium, sin cambios",
                event_type,
                reason,
                guild_id,
            )
    else:
        await unset_premium(guild_id)
        log.info(
            "Premium desactivado por Polar para guild %s (%s)", guild_id, event_type
        )
    return web.json_response({"ok": True})


# ---------------- Server ----------------


def _new_session_storage() -> EncryptedCookieStorage:
    # Derivamos 32 bytes exactos desde SESSION_SECRET (cualquier longitud) para Fernet.
    key = hashlib.sha256(SESSION_SECRET.encode()).digest()
    return EncryptedCookieStorage(
        key,
        cookie_name="PURGITO_SESSION",
        # None = cookie atada al host que la emite (comportamiento clásico);
        # ".purgito.app" en producción para que www comparta sesión con el apex.
        domain=SESSION_COOKIE_DOMAIN,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="Lax",
        secure=True,
    )


async def start_web_server(bot: commands.Bot) -> None:
    global _runner
    if _runner is not None:
        return
    app = web.Application(middlewares=[_cors_middleware])
    app["bot"] = bot
    # Sesión HTTP compartida para llamadas a la API de Discord, con timeout global.
    app["http"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    app.router.add_get("/health", _api_health)
    # Fuera del bloque DASHBOARD_ENABLED: Polar le pega sin sesión OAuth
    # y el premium debe poder activarse aunque la auth esté apagada.
    app.router.add_post("/webhooks/polar", _webhook_polar)

    if DASHBOARD_ENABLED:
        setup_session(app, _new_session_storage())
        app.router.add_get("/auth/login", _auth_login)
        app.router.add_get("/auth/callback", _auth_callback)
        app.router.add_get("/auth/logout", _auth_logout)
        app.router.add_get("/auth/error", _auth_error)
        app.router.add_get("/api/me", _api_me)
        app.router.add_get("/api/me/guilds", _api_me_guilds)
        # Público (sin scope de guild): el editor de embeds lo pide antes de
        # saber en qué servidor va a pegar el contenido compartido.
        app.router.add_get("/api/embeds/share/{share_id}", _api_embeds_share_get)

        base = "/api/server/{guild_id}"
        app.router.add_get(f"{base}/channels", _api_channels)
        app.router.add_get(f"{base}/roles", _api_roles)
        app.router.add_get(f"{base}/emojis", _api_emojis)
        app.router.add_get(f"{base}/stats", _api_stats)
        app.router.add_get(f"{base}/style", _api_style_get)
        app.router.add_put(f"{base}/style", _api_style_put)
        app.router.add_get(f"{base}/settings/chat", _api_chat_get)
        app.router.add_put(f"{base}/settings/chat", _api_chat_put)
        app.router.add_get(f"{base}/settings/chat-channels", _api_chat_channels_get)
        app.router.add_post(f"{base}/settings/chat-channels", _api_chat_channels_post)
        app.router.add_delete(
            f"{base}/settings/chat-channels/{{channel_id}}", _api_chat_channels_delete
        )
        app.router.add_get(f"{base}/settings/corpus", _api_corpus_get)
        app.router.add_post(f"{base}/settings/corpus", _api_corpus_post)
        app.router.add_delete(
            f"{base}/settings/corpus/{{channel_id}}", _api_corpus_delete
        )
        app.router.add_get(f"{base}/settings/reacciones", _api_reacciones_get)
        app.router.add_post(f"{base}/settings/reacciones", _api_reacciones_post)
        app.router.add_delete(
            f"{base}/settings/reacciones/{{reaction_id}}", _api_reacciones_delete
        )
        app.router.add_get(f"{base}/settings/frases", _api_frases_get)
        app.router.add_post(f"{base}/settings/frases", _api_frases_post)
        app.router.add_delete(
            f"{base}/settings/frases/{{frase_id}}", _api_frases_delete
        )
        app.router.add_get(f"{base}/settings/updates", _api_updates_get)
        app.router.add_put(f"{base}/settings/updates", _api_updates_put)
        app.router.add_get(f"{base}/settings/gifs", _api_server_gifs_get)
        app.router.add_post(f"{base}/settings/gifs", _api_server_gifs_post)
        app.router.add_delete(
            f"{base}/settings/gifs/{{gif_id}}", _api_server_gifs_delete
        )
        app.router.add_post(f"{base}/settings/gifs/verify", _api_server_gifs_verify)
        app.router.add_post(f"{base}/embeds/send", _api_embeds_send)
        app.router.add_post(f"{base}/embeds/share", _api_embeds_share)
        app.router.add_post(f"{base}/embeds/schedule", _api_embeds_schedule)
        app.router.add_post(f"{base}/embeds/validate", _api_embeds_validate)
        app.router.add_post(f"{base}/embeds/upload", _api_embeds_upload)
        app.router.add_get(f"{base}/embeds/templates", _api_embed_templates_get)
        app.router.add_post(f"{base}/embeds/templates", _api_embed_templates_post)
        app.router.add_put(
            f"{base}/embeds/templates/{{template_id}}", _api_embed_template_put
        )
        app.router.add_delete(
            f"{base}/embeds/templates/{{template_id}}", _api_embed_template_delete
        )
        app.router.add_get(f"{base}/premium", _api_premium_get)
        app.router.add_post(f"{base}/premium/checkout", _api_premium_checkout)
        log.info("OAuth2 + API del dashboard habilitados")
    else:
        log.info("Auth deshabilitada: solo /health y el webhook de Polar")

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", WEB_PORT)
    await site.start()
    log.info("Web API iniciada en 0.0.0.0:%s", WEB_PORT)


async def stop_web_server() -> None:
    global _runner
    if _runner is not None:
        app = _runner.app
        if app is not None and "http" in app:
            await app["http"].close()
        await _runner.cleanup()
        _runner = None
