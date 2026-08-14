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
import io
import json
import logging
import math
import secrets
import time
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlencode, urlparse

import aiohttp
import discord
import generation
import regex
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
from cogs.chat import simulate_message
from cogs.gifs import HEALTH_CHECK_BATCH, resolve_tenor_gif_url, run_gif_health_check
from cogs.premium import is_premium_guild, set_premium, unset_premium
from cogs.youtube import resolve_youtube_channel
from db import (
    CHAT_TUNABLES,
    MAX_TRIGGER_PATTERN,
    TRIGGER_ACTIONS,
    TRIGGER_MATCH_TYPES,
    add_button_action,
    add_channel_trigger,
    add_corpus_channel,
    add_embed_template,
    add_exempt_channel,
    add_exempt_role,
    add_frase_channel,
    add_frase_especial,
    add_frase_pack,
    add_mention_channel,
    add_reaction_to_pool,
    add_scheduled_announcement,
    add_shared_embed,
    add_spontaneous_channel,
    add_youtube_sub,
    assign_pack_to_channel,
    block_gif,
    channel_triggers_limit,
    corpus_channel_limit,
    corpus_total_limit,
    count_audit_action,
    count_corpus_by_channel,
    count_gif_urls,
    count_guild_corpus_messages,
    delete_channel_trigger,
    delete_embed_template,
    delete_frase_especial,
    delete_frase_pack,
    delete_gif_url_by_id,
    delete_recent_corpus,
    embed_template_limit,
    extract_send_options,
    frase_pack_limit,
    frases_limit,
    get_bot_style,
    get_channel_tunables,
    get_chat_settings,
    get_counters,
    get_effective_chat_settings,
    get_gif_by_id,
    get_gif_by_url,
    get_shared_embed,
    get_updates_channel,
    gifs_limit,
    import_corpus_messages,
    is_session_revoked,
    list_audit_log_page,
    list_blocked_gifs,
    list_corpus_channels,
    list_embed_templates,
    list_exempt_channels,
    list_exempt_roles,
    list_frase_channels,
    list_frase_packs,
    list_frases_especiales,
    list_gif_urls,
    list_guild_triggers,
    list_ignored_channels,
    list_mention_channels,
    list_pack_channels,
    list_premium_guilds,
    list_reaction_pool,
    list_spontaneous_channels,
    list_uploaded_images,
    list_youtube_subs,
    log_audit,
    normalize_embeds_json,
    record_uploaded_image,
    remove_corpus_channel,
    remove_exempt_channel,
    remove_exempt_role,
    remove_frase_channel,
    remove_mention_channel,
    remove_reaction_from_pool,
    remove_spontaneous_channel,
    remove_youtube_sub_by_id,
    revoke_session,
    save_gif_url,
    set_bot_style,
    set_channel_tunables,
    set_chat_enabled,
    set_chat_mode,
    set_chat_tunables,
    set_frase_pack,
    set_updates_channel,
    set_youtube_mention_role_by_id,
    unassign_pack_from_channel,
    unblock_gif,
    update_embed_template,
    update_last_video_id,
)
from layout_v2 import (
    MAX_FILENAME_LEN,
    assign_button_custom_ids,
    build_layout_view,
    has_file_block,
    iter_buttons,
    validate_layout_v2_payload,
)
from message_options import (
    sanitize_send_options,
    send_kwargs,
    validate_send_options,
    wants_custom_identity,
)
from utils import LRUDict
from webhook_identity import WebhookIdentityError, send_via_webhook
import r2

log = logging.getLogger(__name__)

# Rate limit por IP de las acciones que escriben o disparan trabajo pesado.
_rate_post: LRUDict = LRUDict(512)
_rate_delete: LRUDict = LRUDict(512)
_rate_gif_verify: LRUDict = LRUDict(512)
_rate_status_search: LRUDict = LRUDict(512)
_rate_corpus_import: LRUDict = LRUDict(512)
# Sin esto, /auth/callback no tenía ningún límite: cada hit con un `state`
# válido (basta con pedir /auth/login primero, gratis) dispara un POST real a
# discord.com/oauth2/token con nuestro client_id/client_secret. Discord
# ratea ese endpoint por client_id -- un solo atacante en loop podía agotarlo
# y tirar el login de TODOS los guilds que usan este bot, no solo el suyo.
_rate_auth_callback: LRUDict = LRUDict(512)
# /webhooks/polar es público y corre en el mismo proceso que el dashboard:
# cada hit calcula una firma HMAC (barato) pero sigue siendo trabajo en el
# mismo event loop. Límite generoso a propósito -- no debe interferir con
# reintentos legítimos de Polar tras una falla transitoria.
_rate_webhook_polar: LRUDict = LRUDict(512)
# user_id -> (expira_monotonic, [guilds con manage_guild]) — cache para no
# golpear a Discord en cada request.
_user_guilds_cache: LRUDict = LRUDict(256)
_runner: web.AppRunner | None = None

_DISCORD_API = "https://discord.com/api"
_ADMINISTRATOR = 1 << 3
_MANAGE_GUILD = 1 << 5
# Ventana en la que un admin recién degradado/expulsado en Discord conserva
# acceso de escritura al dashboard (la revalidación real es contra la API de
# Discord, esto es solo cuánto se confía en la última respuesta). 60s en vez
# de los 300s originales -- suficiente margen frente al rate limit real de
# /users/@me/guilds (~1 req/s por token: un usuario navegando activamente el
# dashboard dispara como mucho una revalidación por minuto, muy por debajo).
_GUILDS_CACHE_TTL = 60.0
_PUBLIC_GETS = ("/health",)

# CSS de /auth/error (único HTML que sirve esta API). Antes vivía como
# atributos style="..." inline en el HTML, pero la CSP global de abajo es
# default-src 'none' sin style-src -- eso bloquea TAMBIÉN los atributos
# style, no solo <script>/<link>, así que la página salía sin ningún color
# ni layout aplicado. Un <style> con hash en vez de 'unsafe-inline' arregla
# la página sin aflojar la CSP para el resto de las respuestas (JSON puro,
# nunca usa estilos).
_AUTH_ERROR_STYLE = (
    "body{background:#0B0C10;color:#EDEAE3;font-family:system-ui,sans-serif;"
    "display:flex;align-items:center;justify-content:center;min-height:100vh;"
    "text-align:center;padding:24px}"
    "h1{color:#8B6EF5}"
    "a{color:#A28BF7}"
)
_AUTH_ERROR_STYLE_HASH = (
    "sha256-"
    + base64.b64encode(hashlib.sha256(_AUTH_ERROR_STYLE.encode()).digest()).decode()
)


def _client_ip(request: web.Request) -> str:
    """IP real del cliente: detrás de Cloudflare + nginx, request.remote es siempre 127.0.0.1.

    Es la clave de bucket de TODOS los _rate_ok() del archivo -- ningún otro
    dato decide qué tan seguido puede pegarle alguien a un endpoint. CF-Connecting-IP
    se prioriza porque, con la config de nginx documentada en DEPLOY.md
    ($remote_addr en vez de $proxy_add_x_forwarded_for para blindar
    X-Forwarded-For contra spoofing), X-Forwarded-For termina siendo la IP de
    borde de Cloudflare -- la misma para miles de visitantes -- y no serviría
    para nada como clave de rate limit.

    Confianza real: quien le hable directo a nginx (sin pasar por Cloudflare)
    puede mandar el CF-Connecting-IP que quiera y este código lo cree, porque
    nginx no lo limpia ni lo verifica -- nada en esta capa puede distinguir
    "esto lo puso Cloudflare" de "esto lo forjó el cliente" una vez que la
    conexión ya pasó por el proxy. Cerrarlo de verdad es un cambio de
    infraestructura (Authenticated Origin Pulls o un allowlist de IPs de
    Cloudflare en nginx, ver DEPLOY.md), no algo resoluble acá.
    """
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote
        or "unknown"
    )


@web.middleware
async def _security_headers_middleware(
    request: web.Request, handler
) -> web.StreamResponse:
    """Cabeceras defensivas para toda respuesta: esto es una API JSON pura,
    nunca debería terminar embebida en un frame ni interpretada como HTML."""
    try:
        resp = await handler(request)
    except web.HTTPException as ex:
        # web.HTTPFound/HTTPException son excepciones Y Response a la vez.
        # Sin este except, un `raise web.HTTPFound(...)` (todo /auth/login,
        # /auth/callback y /auth/logout) se propaga por encima de este
        # middleware en vez de pasar por `resp = await handler(...)` --
        # confirmado con un servidor aiohttp mínimo -- y esas respuestas
        # salen sin ninguna cabecera de las de abajo, Server real de aiohttp
        # incluido.
        resp = ex
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        f"default-src 'none'; style-src '{_AUTH_ERROR_STYLE_HASH}'; "
        "frame-ancestors 'none'"
    )
    # aiohttp manda "Python/3.x aiohttp/3.x" acá con headers.setdefault(...) --
    # solo pisa si el header ya está seteado, así que hay que setearlo con
    # ALGO para que gane. Sin esto, cada respuesta (incluidos los errores)
    # anuncia la versión exacta de Python y de aiohttp corriendo en
    # producción: reconocimiento gratis para buscar CVEs puntuales, sin
    # aportarle nada al usuario real.
    resp.headers["Server"] = "Purgito"
    # GET /api/* siempre es por-sesión (config de guild, stats, tokens de
    # share): con Cloudflare delante, sin esto un GET sin Cache-Control
    # propio (la mayoría de los ~25 endpoints de /api/server/{guild_id}/...)
    # queda a merced de la política de caché default del proxy -- el mismo
    # motivo por el que /api/me y /api/me/guilds ya lo seteaban a mano.
    # setdefault: no pisa un Cache-Control más específico que un handler
    # puntual ya haya puesto.
    if request.path.startswith("/api/") and request.method == "GET":
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@web.middleware
async def _cors_middleware(request: web.Request, handler) -> web.StreamResponse:
    origin = request.headers.get("Origin", "")
    if request.method == "OPTIONS":
        resp: web.StreamResponse = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as ex:
            resp = ex
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
        # El valor de Allow-Origin depende del Origin del request -- sin Vary,
        # un caché compartido delante (Cloudflare) podría guardar la respuesta
        # armada para un origin confiable y servirla tal cual a otro. No es
        # una fuga (el navegador igual compara Allow-Origin contra SU propio
        # origin y bloquea si no matchea), pero rompe el fetch legítimo del
        # origin que no recibió su propio eco.
        resp.headers["Vary"] = "Origin"
    elif request.method in ("GET", "OPTIONS") and request.path in _PUBLIC_GETS:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    )
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


async def _fetch_manage_guilds(
    request: web.Request, force: bool = False
) -> list[dict] | None:
    """Guilds del usuario donde tiene MANAGE_GUILD/owner, cacheados 5 min por user_id.

    ``force`` salta el TTL (botón "Recargar" del perfil) pero NO borra la
    entrada cacheada: si Discord contesta 429 —su límite en este endpoint es de
    ~1 req/s por token— la lista vieja sigue ahí para devolverla. Borrarla haría
    que dos clicks seguidos parecieran una sesión expirada.
    """
    session = await get_session(request)
    user_id = session.get("user_id")
    token = session.get("access_token")
    if not user_id or not token:
        return None
    now = time.monotonic()
    cached = _user_guilds_cache.get(user_id)
    if cached and not force and cached[0] > now:
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


async def _session_logged_in(session) -> bool:
    """True si la sesión tiene un usuario Y su sid no fue revocado por logout.

    EncryptedCookieStorage no tiene session store del lado del server: la
    sesión entera vive cifrada en la cookie, así que sin este chequeo un
    logout solo borra la cookie del navegador que lo pidió -- una copia
    tomada antes (XSS, log, dispositivo compartido) seguiría autenticando
    hasta que la cookie expire sola. `sid` se mintea en el login
    (_auth_callback) y revoke_session lo marca en logout (_auth_logout);
    sesiones viejas sin `sid` (pre-fix) no se pueden revocar individualmente,
    igual que antes.
    """
    if not session.get("user_id"):
        return False
    sid = session.get("sid")
    if sid and await is_session_revoked(sid):
        return False
    return True


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
        if not await _session_logged_in(session):
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


# Los únicos tres Content-Type que el Fetch/CORS spec deja mandar SIN
# preflight ("simple request") -- son justo los tres únicos que un <form>
# nativo de HTML puede emitir; ninguna otra API de navegador los produce sola.
# Nuestro propio panel (apiFetch, landing/js/core/api.js) siempre manda
# application/json, así que un body con uno de estos tres solo puede venir de
# un <form> ajeno o de un fetch armado a mano para esquivar el preflight de
# CORS -- y json.loads no mira el Content-Type, así que igual podía parsear
# como JSON válido (el truco clásico de "JSON polyglot" en un form
# enctype=text/plain con un único input). De ahí en más la única defensa
# quedaba en SameSite=Lax de la cookie de sesión, que no cubre TODOS los
# clientes (navegadores que ignoran el atributo, o la ventana de gracia que
# algunos dan a una cookie Lax recién seteada en un POST de navegación
# top-level). Rechazar acá hace que cualquier llamada cross-origin dependa
# del preflight -- que ya bloquea el origin no permitido -- sin depender de
# esa ventana de tiempo ni de qué tan bien un navegador puntual implemente
# SameSite.
_CORS_SAFELISTED_CONTENT_TYPES = (
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
)


def _is_simple_request_content_type(request: web.Request) -> bool:
    headers = getattr(request, "headers", None) or {}
    ctype = headers.get("Content-Type", "").split(";")[0].strip().lower()
    return ctype in _CORS_SAFELISTED_CONTENT_TYPES


async def _json_body(request: web.Request) -> dict | None:
    if _is_simple_request_content_type(request):
        return None
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


async def _member_can_view_channel(request: web.Request, guild, channel) -> bool:
    """True si el USUARIO de la sesión (no el bot) puede ver `channel` en
    Discord real.

    guild_api solo exige MANAGE_GUILD en algún lado del servidor -- ese
    permiso NO incluye ver canales con overwrites que se los esconden
    (Discord los trata separados). Sin este chequeo, alguien con MANAGE_GUILD
    pero sin acceso a un canal privado podía anotarlo en
    corpus_allowed_channels: el bot sí lo ve y aprende de ahí, y esa lectura
    termina mezclada en el Markov que CUALQUIERA ve después en un canal
    público -- el corpus se genera por guild entero, no por canal (ver
    generation.build_markov_model). Mismo patrón de la Sección 9 (R1): un
    permiso amplio (MANAGE_GUILD, ahí MANAGE_GUILD-sin-roles) no implica el
    alcance puntual que la acción necesita.

    fetch_member (no get_member): el bot corre con Intents.default(), sin el
    intent privilegiado de members, así que su cache de miembros no es
    confiable para alguien que solo usa el panel web y nunca interactúa por
    Discord -- sin un fetch en vivo, el chequeo le fallaría igual a un admin
    legítimo que a un atacante. Ante cualquier error (ya no es miembro,
    Discord caído) se niega: mismo criterio restrictivo que
    _reject_unassignable_roles.
    """
    session = await get_session(request)
    try:
        member = await guild.fetch_member(int(session["user_id"]))
    except discord.HTTPException:
        return False
    return channel.permissions_for(member).view_channel


async def _log_audit(
    request: web.Request, guild_id: int, action: str, detail: str | None = None
) -> None:
    """Registra quién hizo un cambio de config desde el dashboard. Se llama al
    final de cada handler de mutación bajo @guild_api, después de que la
    escritura ya se confirmó -- guild_api garantiza que la sesión existe."""
    session = await get_session(request)
    await log_audit(
        guild_id,
        int(session["user_id"]),
        str(session.get("username") or "panel"),
        action,
        detail,
    )


async def _api_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


# ---------------- API: estado público (/es/estado, sin login) ----------------

_PROCESS_START = time.monotonic()


def _process_memory_mb() -> float | None:
    """RSS actual del proceso en MB, leído de /proc/self (Linux, que es lo
    que corre en el droplet) -- no vale la pena sumar psutil como dependencia
    solo para esto. None si no está disponible (dev en otro SO); el frontend
    lo muestra como "—"."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return None


async def _api_status(request: web.Request) -> web.Response:
    """Estado general del proceso para /es/estado: pública, sin sesión.
    bot.latency es NaN/inf antes del primer heartbeat -- se manda None en
    vez de un número sin sentido."""
    bot = request.app["bot"]
    latency_ms = round(bot.latency * 1000) if math.isfinite(bot.latency) else None
    return web.json_response(
        {
            "uptime_seconds": int(time.monotonic() - _PROCESS_START),
            "memory_mb": _process_memory_mb(),
            "latency_ms": latency_ms,
            "guild_count": len(bot.guilds),
            "member_count": sum(g.member_count or 0 for g in bot.guilds),
        }
    )


async def _api_status_guild(request: web.Request) -> web.Response:
    """Info pública de un guild puntual (buscador de /es/estado): sin login,
    así que nada de configuración ni datos sensibles -- solo lo que ya se ve
    mirando el servidor desde afuera."""
    ip = _client_ip(request)
    if not _rate_ok(_rate_status_search, ip, 20):
        return web.json_response({"error": "rate limit"}, status=429)
    guild_id = _to_int(request.match_info.get("guild_id"))
    if guild_id is None:
        return web.json_response({"error": "guild_id inválido"}, status=400)
    guild = request.app["bot"].get_guild(guild_id)
    if guild is None:
        return web.json_response({"found": False})
    return web.json_response(
        {
            "found": True,
            "name": guild.name,
            "icon_url": guild.icon.with_size(128).url if guild.icon else None,
            "member_count": guild.member_count,
            "premium": is_premium_guild(guild.id),
        }
    )


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
        await _log_audit(request, guild_id, "gifs.add", detail=url)
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
    if deleted:
        await _log_audit(request, guild_id, "gifs.remove", detail=f"gif_id={gif_id}")
    return web.json_response({"deleted": deleted})


async def _gif_block_impl(
    request: web.Request, guild_id: int, raw_id: str
) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_delete, ip, 3):
        return web.json_response({"error": "rate limit"}, status=429)
    gif_id = _to_int(raw_id)
    if gif_id is None:
        return web.json_response({"error": "id inválido"}, status=400)
    gif = await get_gif_by_id(guild_id, gif_id)
    if gif is None:
        return web.json_response({"error": "no encontrado"}, status=404)
    await block_gif(guild_id, gif["content_hash"], gif["url"])
    await _log_audit(request, guild_id, "gifs.block", detail=gif["url"])
    return web.json_response({"blocked": True})


async def _api_me_guilds(request: web.Request) -> web.Response:
    """Servidores que el usuario administra, partidos en los que ya tienen el
    bot (``configured``) y los que no (``available``).

    ``?refresh=1`` lo manda el botón "Recargar" de /es/perfil: vuelve a
    preguntarle la lista a Discord en vez de servir el cache de 5 min, que es
    justo lo que hace falta después de invitar el bot a un servidor nuevo.
    """
    session = await get_session(request)
    if not await _session_logged_in(session):
        return web.json_response({"error": "no autenticado"}, status=401)
    manage = await _fetch_manage_guilds(
        request, force=request.query.get("refresh") == "1"
    )
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
        oauth_icon = g.get("icon")
        oauth_icon_url = (
            f"https://cdn.discordapp.com/icons/{gid}/{oauth_icon}.png?size=128"
            if oauth_icon
            else None
        )
        oauth_name = g.get("name", "")
        if gid in bot_guild_ids:
            bot_guild = bot.get_guild(gid)
            name = (
                getattr(bot_guild, "name", None)
                if bot_guild and getattr(bot_guild, "name", None)
                else oauth_name
            ) or ""
            bot_icon = getattr(bot_guild, "icon", None) if bot_guild else None
            if bot_icon is not None:
                try:
                    icon_url = bot_icon.with_size(128).url
                except Exception:
                    icon_url = (
                        str(getattr(bot_icon, "url", None) or oauth_icon_url or "")
                        or None
                    )
            else:
                icon_url = oauth_icon_url
            configured.append(
                {
                    "id": str(gid),
                    "name": name,
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
                    "name": oauth_name,
                    "icon_url": oauth_icon_url,
                    "invite_url": get_invite_url(str(gid)),
                }
            )
    # no-store por el mismo motivo que /api/me: la respuesta es por usuario y
    # delante hay Cloudflare. Sin esto el "Recargar" podría comerse una copia
    # cacheada y no cambiar nada.
    return web.json_response(
        {"configured": configured, "available": available},
        headers={"Cache-Control": "no-store"},
    )


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
                # Idem para el aviso de identidad personalizada (Fase 4) -- un
                # override a nivel canal puede sacarle este permiso al bot
                # aunque lo tenga a nivel servidor, así que hay que chequearlo
                # por canal, no alcanza con el permiso del bot en general.
                "can_manage_webhooks": perms.manage_webhooks,
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
    """Toggle del chat + los ajustes numéricos de conducta (tab CHAT).

    `channel_id` sigue saliendo por compatibilidad pero está deprecado: los
    canales donde responde a menciones son la lista `mention-channels`
    (`spontaneous-channels` para la participación espontánea).
    """
    settings = await get_chat_settings(guild_id)
    channel_id = settings["channel_id"]
    return web.json_response(
        {
            "enabled": settings["enabled"],
            "channel_id": str(channel_id) if channel_id else None,
            **{k: settings[k] for k in CHAT_TUNABLES},
            # El dashboard necesita los rangos para armar los inputs sin
            # duplicar los límites en el JS.
            "limits": {k: list(v) for k, v in CHAT_TUNABLES.items()},
        }
    )


@guild_api
async def _api_chat_tunables_put(request: web.Request, guild_id: int) -> web.Response:
    """Guarda uno o varios ajustes numéricos del chat (autoguardado por campo).

    Incluye `mention_rate_limit`, que existía en la DB y en la lógica del bot
    desde antes pero nunca había tenido endpoint.
    """
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    unknown = set(data) - set(CHAT_TUNABLES)
    if unknown:
        return web.json_response(
            {"error": f"campos desconocidos: {', '.join(sorted(unknown))}"}, status=400
        )
    saved = await set_chat_tunables(guild_id, data)
    if not saved:
        return web.json_response(
            {"error": "ningún valor válido para guardar"}, status=400
        )
    await _log_audit(
        request, guild_id, "chat.tunables_update", detail=json.dumps(saved)
    )
    # Devuelve lo guardado ya recortado al rango: si el usuario mandó 5000
    # mensajes, el input se corrige solo en vez de mentir.
    return web.json_response({"ok": True, "saved": saved})


@guild_api
async def _api_channel_settings_get(
    request: web.Request, guild_id: int
) -> web.Response:
    """Tunables de chat de un canal puntual: el efectivo (resuelto, lo que
    de verdad usa cogs/chat.py) y los overrides crudos, para que el
    dashboard pueda marcar campo por campo "default del servidor" vs
    "override acá" sin ambigüedad."""
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    effective = await get_effective_chat_settings(guild_id, channel_id)
    overrides = await get_channel_tunables(guild_id, channel_id)
    return web.json_response(
        {
            "effective": {k: effective[k] for k in CHAT_TUNABLES},
            "overrides": overrides,
            "limits": {k: list(v) for k, v in CHAT_TUNABLES.items()},
        }
    )


@guild_api
async def _api_channel_settings_put(
    request: web.Request, guild_id: int
) -> web.Response:
    """Guarda o borra overrides de un canal. Mismo contrato que
    set_channel_tunables: clave ausente en el body no se toca, `null` borra
    el override (vuelve a heredar el default del servidor), un valor lo
    recorta a su rango y lo guarda como override."""
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    unknown = set(data) - set(CHAT_TUNABLES)
    if unknown:
        return web.json_response(
            {"error": f"campos desconocidos: {', '.join(sorted(unknown))}"}, status=400
        )
    saved = await set_channel_tunables(guild_id, channel_id, data)
    if not saved:
        return web.json_response(
            {"error": "ningún valor válido para guardar"}, status=400
        )
    await _log_audit(
        request,
        guild_id,
        "channel_settings.update",
        detail=f"channel_id={channel_id} {json.dumps(saved)}",
    )
    return web.json_response({"ok": True, "saved": saved})


@guild_api
async def _api_chat_playground_post(
    request: web.Request, guild_id: int
) -> web.Response:
    """Simula qué habría generado el motor de chat (triggers y la decisión
    frase-vs-Markov) para un mensaje de prueba en un canal puntual, con la
    config efectiva de ese canal -- overrides de channel_settings (Fase 2),
    pack/allowlist de frases (Fase 3) y triggers (Fase 4) incluidos. Nunca
    manda nada a Discord ni toca corpus/contadores/cooldowns reales, ver
    simulate_message en cogs/chat.py.
    """
    ip = _client_ip(request)
    if not _rate_ok(_rate_playground, ip, 20):
        return web.json_response({"error": "demasiadas solicitudes"}, status=429)
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    # Recortado al máximo real de un mensaje de Discord: simular algo más
    # largo no tiene sentido, y sin tope el texto entraba entero al matcheo de
    # cada trigger 'regex' del canal (hasta _TRIGGER_REGEX_TIMEOUT segundos de
    # thread pool cada uno, el mismo pool compartido con la generación de
    # Markov de todos los servidores).
    message_text = (data.get("message") or "").strip()[:4000]
    if not message_text:
        return web.json_response(
            {"error": "el mensaje de prueba está vacío"}, status=400
        )
    channel_id = _to_int(data.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)

    guild = _bot_guild(request, guild_id)
    channel = guild.get_channel(channel_id)
    if channel is None:
        return web.json_response(
            {"error": "el canal no existe en este servidor"}, status=400
        )

    # El admin que prueba el playground hace de "autor" para {{user.*}}: se
    # busca su Member real (para que {{user.mention}} sea el suyo) y si no
    # se puede resolver (permisos, caché del bot) se cae a un placeholder
    # en vez de romper la simulación por eso.
    session = await get_session(request)
    member = guild.get_member(int(session["user_id"]))
    author = member or SimpleNamespace(
        mention=f"<@{session['user_id']}>",
        display_name=str(session.get("username") or "tú"),
    )

    result = await simulate_message(
        guild_id, channel_id, message_text, author=author, channel=channel, guild=guild
    )
    return web.json_response(result)


@guild_api
async def _api_chat_put(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    if data is None or not isinstance(data.get("enabled"), bool):
        return web.json_response({"error": "body inválido"}, status=400)
    if "channel_id" not in data:
        # Dashboard nuevo: el toggle solo prende/apaga la respuesta a menciones,
        # sin pisar el chat_channel_id legacy que administra el panel viejo.
        await set_chat_enabled(guild_id, data["enabled"])
        await _log_audit(
            request,
            guild_id,
            "chat.settings_update",
            detail=f"enabled={data['enabled']}",
        )
        return web.json_response({"ok": True})
    channel_id = None
    if data.get("channel_id") is not None:
        channel_id = _to_int(data["channel_id"])
        if channel_id is None:
            return web.json_response({"error": "channel_id inválido"}, status=400)
    await set_chat_mode(guild_id, data["enabled"], channel_id)
    await _log_audit(
        request,
        guild_id,
        "chat.settings_update",
        detail=f"enabled={data['enabled']} channel_id={channel_id}",
    )
    return web.json_response({"ok": True})


# ---------------- API: corpus (canales ignorados) ----------------


# Allowlist positiva: estos endpoints operan sobre corpus_allowed_channels.
# Antes editaban ignored_channels con la lógica invertida (el dashboard mostraba
# "canales donde aprende" y guardaba "canales ignorados"), que era imposible de
# leer y no distinguía "no aprendo acá" de "acá estoy completamente mudo".
# ignored_channels sigue existiendo como concepto aparte y se administra desde
# /settings en Discord.


@guild_api
async def _api_corpus_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    # Los ignorados viajan aparte para que el dashboard pueda marcarlos: están
    # excluidos del corpus pase lo que pase, y elegirlos acá no haría nada.
    ignored = set(await list_ignored_channels(guild_id))
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)}
        for cid in await list_corpus_channels(guild_id)
    ]
    return web.json_response(
        {"channels": channels, "ignored": [str(cid) for cid in sorted(ignored)]}
    )


@guild_api
async def _api_corpus_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    guild = _bot_guild(request, guild_id)
    channel = guild.get_channel(channel_id)
    if channel is None:
        return web.json_response(
            {"error": "el canal no existe en este servidor"}, status=400
        )
    # corpus_allowed_channels es la única allowlist que hace que el bot LEA
    # mensajes -- las demás (spontaneous/mention/frases/triggers) solo hacen
    # que el bot ESCRIBA ahí. Leer es más invasivo (ver el comentario de la
    # tabla en db.py), así que esta es la primera en cerrarse: sin esto, un
    # canal privado que el admin no puede ver terminaba entrenando el Markov
    # que sale después en cualquier canal público (ver
    # _member_can_view_channel). Las demás allowlists de canal quedan para
    # una ronda siguiente -- mismo hueco, impacto menor (el bot escribe, no
    # filtra contenido ajeno).
    if not await _member_can_view_channel(request, guild, channel):
        return web.json_response({"error": "no tienes acceso a ese canal"}, status=403)
    added = await add_corpus_channel(guild_id, channel_id)
    if added:
        await _log_audit(
            request, guild_id, "corpus.add", detail=f"channel_id={channel_id}"
        )
    return web.json_response({"added": added})


@guild_api
async def _api_corpus_delete(request: web.Request, guild_id: int) -> web.Response:
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    removed = await remove_corpus_channel(guild_id, channel_id)
    if removed:
        await _log_audit(
            request, guild_id, "corpus.remove", detail=f"channel_id={channel_id}"
        )
    return web.json_response({"removed": removed})


@guild_api
async def _api_corpus_import_post(request: web.Request, guild_id: int) -> web.Response:
    """Sube un .txt (body crudo, mismo patrón que _api_embeds_upload) y lo
    trocea en "mensajes" -- una línea no vacía es un mensaje -- que entran a
    corpus_messages del canal como si fueran reales: mismo pipeline de
    limpieza (generation.clean_for_corpus) y sujetos a los mismos límites
    MAX_CORPUS_MESSAGES_PER_GUILD_* de siempre (ver import_corpus_messages).
    """
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    # Único endpoint de mutación fuera de _json_body que legítimamente acepta
    # un Content-Type CORS-safelisted (el panel manda text/plain) -- por eso
    # el mismo gate de _json_body no lo cubre, y por eso lo repite acá: un
    # <form> ajeno con enctype="text/plain" podía entregar cualquier body sin
    # preflight de CORS, dejando el import de corpus (contenido que el bot
    # después puede repetir) apoyado solo en SameSite=Lax. El panel real manda
    # application/octet-stream (landing/js/dash.js), que si o si dispara
    # preflight.
    if _is_simple_request_content_type(request):
        return web.json_response({"error": "Content-Type inválido"}, status=400)
    ip = _client_ip(request)
    if not _rate_ok(_rate_corpus_import, ip, 3):
        return web.json_response({"error": "rate limit"}, status=429)
    max_bytes = env_int("MAX_CORPUS_IMPORT_BYTES", 2 * 1024 * 1024)
    if request.content_length and request.content_length > max_bytes:
        return web.json_response(
            {
                "error": f"el archivo supera el máximo de {max_bytes // (1024 * 1024)} MB"
            },
            status=413,
        )
    data = await request.read()
    if len(data) > max_bytes:
        return web.json_response(
            {
                "error": f"el archivo supera el máximo de {max_bytes // (1024 * 1024)} MB"
            },
            status=413,
        )
    if not data:
        return web.json_response({"error": "archivo vacío"}, status=400)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return web.json_response(
            {"error": "el archivo no es texto UTF-8 válido"}, status=400
        )
    lines = []
    for raw_line in text.splitlines():
        cleaned = generation.clean_for_corpus(raw_line)
        if cleaned is not None:
            lines.append(cleaned)
    if not lines:
        return web.json_response(
            {"error": "no se encontró texto aprovechable en el archivo"}, status=400
        )
    inserted = await import_corpus_messages(guild_id, channel_id, lines)
    generation.reset_guild_caches(guild_id)
    await _log_audit(
        request,
        guild_id,
        "corpus.import",
        detail=f"channel_id={channel_id} lines={inserted}",
    )
    return web.json_response({"imported": inserted, "lines_found": len(lines)})


@guild_api
async def _api_corpus_amnesia_post(request: web.Request, guild_id: int) -> web.Response:
    """ "Amnesia": borra el corpus (mensajes + estilo por usuario) de las
    últimas 24 horas del guild. Irreversible -- la confirmación vive en el
    dashboard, acá se ejecuta sin preguntar de nuevo."""
    if not _rate_ok(_rate_delete, _client_ip(request), 3):
        return web.json_response({"error": "demasiadas solicitudes"}, status=429)
    deleted = await delete_recent_corpus(guild_id, hours=24)
    generation.reset_guild_caches(guild_id)
    await _log_audit(
        request,
        guild_id,
        "corpus.amnesia",
        detail=(
            f"corpus_messages={deleted['corpus_messages']} "
            f"user_corpus={deleted['user_corpus']}"
        ),
    )
    return web.json_response({"deleted": deleted})


# ---------------- API: roles exentos del límite de menciones ----------------


@guild_api
async def _api_exempt_roles_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    roles = []
    for rid in await list_exempt_roles(guild_id):
        role = guild.get_role(rid) if guild else None
        roles.append({"id": str(rid), "name": getattr(role, "name", None)})
    return web.json_response({"roles": roles})


@guild_api
async def _api_exempt_roles_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    role_id = _to_int(data.get("role_id")) if data else None
    if role_id is None:
        return web.json_response({"error": "role_id inválido"}, status=400)
    added = await add_exempt_role(guild_id, role_id)
    if added:
        await _log_audit(
            request, guild_id, "exempt_roles.add", detail=f"role_id={role_id}"
        )
    return web.json_response({"added": added})


@guild_api
async def _api_exempt_roles_delete(request: web.Request, guild_id: int) -> web.Response:
    role_id = _to_int(request.match_info.get("role_id"))
    if role_id is None:
        return web.json_response({"error": "role_id inválido"}, status=400)
    removed = await remove_exempt_role(guild_id, role_id)
    if removed:
        await _log_audit(
            request, guild_id, "exempt_roles.remove", detail=f"role_id={role_id}"
        )
    return web.json_response({"removed": removed})


# --------------- API: canales exentos del límite de menciones ---------------
# Mismo concepto que los roles exentos, por canal (#bot-testing y similares).


@guild_api
async def _api_exempt_channels_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)}
        for cid in await list_exempt_channels(guild_id)
    ]
    return web.json_response({"channels": channels})


@guild_api
async def _api_exempt_channels_post(
    request: web.Request, guild_id: int
) -> web.Response:
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    added = await add_exempt_channel(guild_id, channel_id)
    if added:
        await _log_audit(
            request,
            guild_id,
            "exempt_channels.add",
            detail=f"channel_id={channel_id}",
        )
    return web.json_response({"added": added})


@guild_api
async def _api_exempt_channels_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    removed = await remove_exempt_channel(guild_id, channel_id)
    if removed:
        await _log_audit(
            request,
            guild_id,
            "exempt_channels.remove",
            detail=f"channel_id={channel_id}",
        )
    return web.json_response({"removed": removed})


# ---------------- API: dashboard nuevo (chat-channels, updates, stats, estilo) --

# Dos allowlists independientes desde que se separó "habla espontáneamente"
# de "responde a menciones" — ver spontaneous_channels/mention_channels en
# db.py. Reemplazan al viejo /settings/chat-channels (un solo concepto), que
# ya no se registra.


@guild_api
async def _api_spontaneous_channels_get(
    request: web.Request, guild_id: int
) -> web.Response:
    guild = _bot_guild(request, guild_id)
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)}
        for cid in await list_spontaneous_channels(guild_id)
    ]
    return web.json_response({"channels": channels})


@guild_api
async def _api_spontaneous_channels_post(
    request: web.Request, guild_id: int
) -> web.Response:
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    added = await add_spontaneous_channel(guild_id, channel_id)
    if added:
        await _log_audit(
            request,
            guild_id,
            "spontaneous_channels.add",
            detail=f"channel_id={channel_id}",
        )
    return web.json_response({"added": added})


@guild_api
async def _api_spontaneous_channels_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    removed = await remove_spontaneous_channel(guild_id, channel_id)
    if removed:
        await _log_audit(
            request,
            guild_id,
            "spontaneous_channels.remove",
            detail=f"channel_id={channel_id}",
        )
    return web.json_response({"removed": removed})


@guild_api
async def _api_mention_channels_get(
    request: web.Request, guild_id: int
) -> web.Response:
    guild = _bot_guild(request, guild_id)
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)}
        for cid in await list_mention_channels(guild_id)
    ]
    return web.json_response({"channels": channels})


@guild_api
async def _api_mention_channels_post(
    request: web.Request, guild_id: int
) -> web.Response:
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    added = await add_mention_channel(guild_id, channel_id)
    if added:
        await _log_audit(
            request, guild_id, "mention_channels.add", detail=f"channel_id={channel_id}"
        )
    return web.json_response({"added": added})


@guild_api
async def _api_mention_channels_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    removed = await remove_mention_channel(guild_id, channel_id)
    if removed:
        await _log_audit(
            request,
            guild_id,
            "mention_channels.remove",
            detail=f"channel_id={channel_id}",
        )
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
    await _log_audit(
        request, guild_id, "updates_channel.set", detail=f"channel_id={channel_id}"
    )
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
    mention_channels = await list_mention_channels(guild_id)
    return web.json_response(
        {
            "corpus_total": await count_guild_corpus_messages(guild_id),
            # Canales que el bot lee = los de texto menos los ignorados.
            "reading_channels": len([c for c in text_channels if c.id not in ignored]),
            "text_channels": len(text_channels),
            # Lista vacía = responde en todos (ver mention_channels en cogs/chat.py).
            "reply_channels": len(mention_channels) or len(text_channels),
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
            # Denominadores de las tarjetas de estado: sin esto el dashboard
            # muestra "14.982 mensajes" sin decir que el tope está en 15.000 y
            # que a partir de ahí se van borrando los más viejos en silencio.
            "limits": {
                "corpus_total": corpus_total_limit(guild_id),
                "corpus_per_channel": corpus_channel_limit(guild_id),
                "gifs": gifs_limit(guild_id),
                "frases": frases_limit(guild_id),
            },
        }
    )


# ---------------- API: audit log ----------------


@guild_api
async def _api_audit_log_get(request: web.Request, guild_id: int) -> web.Response:
    """Últimas mutaciones de config del guild, paginado por cursor (id
    descendente) para el tab HISTORIAL del dashboard -- ver
    list_audit_log_page sobre por qué cursor y no offset."""
    limit = _to_int(request.query.get("limit")) or 5
    limit = max(1, min(limit, 50))
    before_id = _to_int(request.query.get("before_id"))
    entries, has_more = await list_audit_log_page(
        guild_id, before_id=before_id, limit=limit
    )
    return web.json_response({"entries": entries, "has_more": has_more})


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
    await _log_audit(
        request,
        guild_id,
        "style.update",
        detail=f"nick={nick or None!r} avatar={'avatar_url' in data} banner={'banner_url' in data}",
    )
    return web.json_response({"ok": True, "warning": warning})


# ---------------- API: reacciones ----------------


@guild_api
async def _api_reacciones_get(request: web.Request, guild_id: int) -> web.Response:
    pool = await list_reaction_pool(guild_id)
    return web.json_response({"reactions": pool})


@guild_api
async def _api_reacciones_post(request: web.Request, guild_id: int) -> web.Response:
    # A diferencia de frases/packs/triggers/embed templates, reaction_pool no
    # tiene cuota (MAX_*_PER_GUILD) -- es la única tabla de este estilo sin
    # ningún tope. Cada fila es ínfima y esto no toca el ThreadPoolExecutor,
    # así que no amerita una cuota nueva en limits.env (eso sí sería
    # funcionalidad nueva); el rate limit por IP ya establecido para el resto
    # de los POST de settings alcanza para cerrar el hueco.
    if not _rate_ok(_rate_post, _client_ip(request), 5):
        return web.json_response({"error": "demasiadas solicitudes"}, status=429)
    data = await _json_body(request)
    emoji = (data.get("emoji") or "").strip() if data else ""
    if not emoji:
        return web.json_response({"error": "emoji vacío"}, status=400)
    added = await add_reaction_to_pool(guild_id, emoji)
    if added:
        await _log_audit(request, guild_id, "reactions.add", detail=emoji)
    return web.json_response({"added": added})


@guild_api
async def _api_reacciones_delete(request: web.Request, guild_id: int) -> web.Response:
    reaction_id = _to_int(request.match_info.get("reaction_id"))
    if reaction_id is None:
        return web.json_response({"error": "reaction_id inválido"}, status=400)
    removed = await remove_reaction_from_pool(guild_id, reaction_id)
    if removed:
        await _log_audit(
            request, guild_id, "reactions.remove", detail=f"reaction_id={reaction_id}"
        )
    return web.json_response({"removed": removed})


# ---------------- API: frases ----------------


@guild_api
async def _api_frases_get(request: web.Request, guild_id: int) -> web.Response:
    frases = await list_frases_especiales(guild_id)
    return web.json_response(
        {
            "frases": [
                {
                    "id": f["id"],
                    "frase": f["frase"],
                    "user_name": f["user_name"],
                    "pack_id": f["pack_id"],
                }
                for f in frases
            ],
            "total": len(frases),
            "limit": frases_limit(guild_id),
        }
    )


@guild_api
async def _api_frases_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    frase = (data.get("frase") or "").strip() if data else ""
    if not frase:
        return web.json_response({"error": "frase vacía"}, status=400)
    pack_id = None
    if data and data.get("pack_id") is not None:
        pack_id = _to_int(data["pack_id"])
        if pack_id is None:
            return web.json_response({"error": "pack_id inválido"}, status=400)
    session = await get_session(request)
    added = await add_frase_especial(
        guild_id,
        int(session["user_id"]),
        str(session.get("username", "panel")),
        frase,
        pack_id=pack_id,
    )
    if added is None:
        return web.json_response(
            {"error": "límite de frases alcanzado — elimina una antes de agregar otra"},
            status=409,
        )
    if added:
        await _log_audit(request, guild_id, "frases.add", detail=frase)
    return web.json_response({"added": added})


@guild_api
async def _api_frases_delete(request: web.Request, guild_id: int) -> web.Response:
    frase_id = _to_int(request.match_info.get("frase_id"))
    if frase_id is None:
        return web.json_response({"error": "frase_id inválido"}, status=400)
    deleted = await delete_frase_especial(guild_id, frase_id)
    if deleted:
        await _log_audit(
            request, guild_id, "frases.remove", detail=f"frase_id={frase_id}"
        )
    return web.json_response({"deleted": deleted})


@guild_api
async def _api_frases_patch(request: web.Request, guild_id: int) -> web.Response:
    """Reasigna el pack de una frase existente (pack_id null la vuelve al
    pool default del servidor)."""
    frase_id = _to_int(request.match_info.get("frase_id"))
    if frase_id is None:
        return web.json_response({"error": "frase_id inválido"}, status=400)
    data = await _json_body(request)
    if data is None or "pack_id" not in data:
        return web.json_response({"error": "pack_id es obligatorio"}, status=400)
    pack_id = None
    if data["pack_id"] is not None:
        pack_id = _to_int(data["pack_id"])
        if pack_id is None:
            return web.json_response({"error": "pack_id inválido"}, status=400)
    updated = await set_frase_pack(guild_id, frase_id, pack_id)
    if updated:
        await _log_audit(
            request,
            guild_id,
            "frases.set_pack",
            detail=f"frase_id={frase_id} pack_id={pack_id}",
        )
    return web.json_response({"updated": updated})


# ---------------- API: canales permitidos para frases especiales ----------


@guild_api
async def _api_frase_channels_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)}
        for cid in await list_frase_channels(guild_id)
    ]
    return web.json_response({"channels": channels})


@guild_api
async def _api_frase_channels_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    added = await add_frase_channel(guild_id, channel_id)
    if added:
        await _log_audit(
            request, guild_id, "frase_channels.add", detail=f"channel_id={channel_id}"
        )
    return web.json_response({"added": added})


@guild_api
async def _api_frase_channels_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    channel_id = _to_int(request.match_info.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    removed = await remove_frase_channel(guild_id, channel_id)
    if removed:
        await _log_audit(
            request,
            guild_id,
            "frase_channels.remove",
            detail=f"channel_id={channel_id}",
        )
    return web.json_response({"removed": removed})


# ---------------- API: packs de frases especiales --------------------------


@guild_api
async def _api_frase_packs_get(request: web.Request, guild_id: int) -> web.Response:
    packs = await list_frase_packs(guild_id)
    return web.json_response(
        {"packs": packs, "total": len(packs), "limit": frase_pack_limit(guild_id)}
    )


@guild_api
async def _api_frase_packs_post(request: web.Request, guild_id: int) -> web.Response:
    data = await _json_body(request)
    name = (data.get("name") or "").strip() if data else ""
    if not name:
        return web.json_response({"error": "el pack necesita un nombre"}, status=400)
    pack_id = await add_frase_pack(guild_id, name)
    if pack_id is None:
        return web.json_response(
            {"error": "límite de packs alcanzado, o ya existe un pack con ese nombre"},
            status=409,
        )
    await _log_audit(request, guild_id, "frase_packs.create", detail=name)
    return web.json_response({"id": pack_id})


@guild_api
async def _api_frase_packs_delete(request: web.Request, guild_id: int) -> web.Response:
    pack_id = _to_int(request.match_info.get("pack_id"))
    if pack_id is None:
        return web.json_response({"error": "pack_id inválido"}, status=400)
    deleted = await delete_frase_pack(guild_id, pack_id)
    if deleted:
        await _log_audit(
            request, guild_id, "frase_packs.delete", detail=f"pack_id={pack_id}"
        )
    return web.json_response({"deleted": deleted})


@guild_api
async def _api_frase_pack_channels_get(
    request: web.Request, guild_id: int
) -> web.Response:
    pack_id = _to_int(request.match_info.get("pack_id"))
    if pack_id is None:
        return web.json_response({"error": "pack_id inválido"}, status=400)
    guild = _bot_guild(request, guild_id)
    channels = [
        {"id": str(cid), "name": _channel_name(guild, cid)}
        for cid in await list_pack_channels(guild_id, pack_id)
    ]
    return web.json_response({"channels": channels})


@guild_api
async def _api_frase_pack_channels_post(
    request: web.Request, guild_id: int
) -> web.Response:
    pack_id = _to_int(request.match_info.get("pack_id"))
    if pack_id is None:
        return web.json_response({"error": "pack_id inválido"}, status=400)
    data = await _json_body(request)
    channel_id = _to_int(data.get("channel_id")) if data else None
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    ok = await assign_pack_to_channel(guild_id, channel_id, pack_id)
    if not ok:
        return web.json_response({"error": "pack no encontrado"}, status=404)
    await _log_audit(
        request,
        guild_id,
        "frase_packs.assign_channel",
        detail=f"pack_id={pack_id} channel_id={channel_id}",
    )
    return web.json_response({"ok": True})


@guild_api
async def _api_frase_pack_channels_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    pack_id = _to_int(request.match_info.get("pack_id"))
    channel_id = _to_int(request.match_info.get("channel_id"))
    if pack_id is None or channel_id is None:
        return web.json_response({"error": "pack_id o channel_id inválido"}, status=400)
    removed = await unassign_pack_from_channel(guild_id, channel_id, pack_id)
    if removed:
        await _log_audit(
            request,
            guild_id,
            "frase_packs.unassign_channel",
            detail=f"pack_id={pack_id} channel_id={channel_id}",
        )
    return web.json_response({"removed": removed})


# ---------------- API: triggers de canal ------------------------------------


@guild_api
async def _api_triggers_get(request: web.Request, guild_id: int) -> web.Response:
    triggers = await list_guild_triggers(guild_id)
    return web.json_response(
        {
            "triggers": [{**t, "channel_id": str(t["channel_id"])} for t in triggers],
            "total": len(triggers),
            "limit": channel_triggers_limit(guild_id),
            "match_types": list(TRIGGER_MATCH_TYPES),
            "actions": list(TRIGGER_ACTIONS),
        }
    )


@guild_api
async def _api_triggers_post(request: web.Request, guild_id: int) -> web.Response:
    if not _rate_ok(_rate_post, _client_ip(request), 5):
        return web.json_response({"error": "demasiadas solicitudes"}, status=429)
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    channel_id = _to_int(data.get("channel_id"))
    if channel_id is None:
        return web.json_response({"error": "channel_id inválido"}, status=400)
    match_type = data.get("match_type")
    if match_type not in TRIGGER_MATCH_TYPES:
        return web.json_response(
            {"error": f"match_type debe ser uno de: {', '.join(TRIGGER_MATCH_TYPES)}"},
            status=400,
        )
    action = data.get("action")
    if action not in TRIGGER_ACTIONS:
        return web.json_response(
            {"error": f"action debe ser una de: {', '.join(TRIGGER_ACTIONS)}"},
            status=400,
        )
    pattern = (data.get("pattern") or "").strip()
    if not pattern:
        return web.json_response({"error": "pattern vacío"}, status=400)
    # El largo se chequea ANTES de compilar: regex.compile es sincrónico y
    # bloquea el event loop entero (bot incluido) mientras corre -- un patrón
    # de 1 MB tarda ~7 s. El tope es el mismo que aplica add_channel_trigger,
    # así que lo que valida esta ruta es exactamente lo que se guarda.
    if len(pattern) > MAX_TRIGGER_PATTERN:
        return web.json_response(
            {"error": f"pattern supera los {MAX_TRIGGER_PATTERN} caracteres"},
            status=400,
        )
    if match_type == "regex":
        try:
            regex.compile(pattern)
        except regex.error as e:
            return web.json_response({"error": f"regex inválido: {e}"}, status=400)
    pack_id = None
    if data.get("pack_id") is not None:
        pack_id = _to_int(data["pack_id"])
        if pack_id is None:
            return web.json_response({"error": "pack_id inválido"}, status=400)
    trigger_id = await add_channel_trigger(
        guild_id, channel_id, match_type, pattern, action, pack_id=pack_id
    )
    if trigger_id is None:
        return web.json_response(
            {
                "error": "límite de triggers alcanzado, o pattern/match_type/action inválido"
            },
            status=409,
        )
    await _log_audit(
        request,
        guild_id,
        "triggers.create",
        detail=f"channel_id={channel_id} match_type={match_type} action={action}",
    )
    return web.json_response({"id": trigger_id})


@guild_api
async def _api_triggers_delete(request: web.Request, guild_id: int) -> web.Response:
    trigger_id = _to_int(request.match_info.get("trigger_id"))
    if trigger_id is None:
        return web.json_response({"error": "trigger_id inválido"}, status=400)
    deleted = await delete_channel_trigger(guild_id, trigger_id)
    if deleted:
        await _log_audit(
            request, guild_id, "triggers.delete", detail=f"trigger_id={trigger_id}"
        )
    return web.json_response({"deleted": deleted})


# ---------------- API: gifs por guild ----------------


@guild_api
async def _api_server_gifs_get(request: web.Request, guild_id: int) -> web.Response:
    gifs = await list_gif_urls(guild_id)
    # `limit` da el denominador del contador de la pestaña, y `auto_removed_30d`
    # los GIFs que el chequeo de salud sacó solo: sin esto desaparecían sin
    # ningún rastro visible y era indistinguible de un bug.
    return web.json_response(
        {
            "gifs": gifs,
            "total": len(gifs),
            "limit": gifs_limit(guild_id),
            "auto_removed_30d": await count_audit_action(
                guild_id, "gifs.auto_removed", days=30
            ),
        }
    )


@guild_api
async def _api_server_gifs_post(request: web.Request, guild_id: int) -> web.Response:
    return await _gif_add_impl(request, guild_id)


@guild_api
async def _api_server_gifs_delete(request: web.Request, guild_id: int) -> web.Response:
    return await _gif_delete_impl(
        request, guild_id, request.match_info.get("gif_id", "")
    )


@guild_api
async def _api_server_gifs_block(request: web.Request, guild_id: int) -> web.Response:
    return await _gif_block_impl(
        request, guild_id, request.match_info.get("gif_id", "")
    )


@guild_api
async def _api_server_gifs_blocked_get(
    request: web.Request, guild_id: int
) -> web.Response:
    blocked = await list_blocked_gifs(guild_id)
    return web.json_response({"blocked": blocked, "total": len(blocked)})


@guild_api
async def _api_server_gifs_unblock(request: web.Request, guild_id: int) -> web.Response:
    # key es el content_hash o, para GIFs sin hash (tenor/giphy), la url --
    # lo que haya identificado la fila en list_blocked_gifs (aiohttp ya la
    # decodifica: encodeURIComponent en el frontend, match_info acá).
    if not _rate_ok(_rate_delete, _client_ip(request), 3):
        return web.json_response({"error": "demasiadas solicitudes"}, status=429)
    key = request.match_info.get("key", "")
    if not key:
        return web.json_response({"error": "key inválida"}, status=400)
    deleted = await unblock_gif(guild_id, key) or await unblock_gif(guild_id, None, key)
    if deleted:
        await _log_audit(request, guild_id, "gifs.unblock", detail=key)
    return web.json_response({"unblocked": deleted})


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


# ---------------- API: YouTube (suscripciones, tab del dashboard) ----------------

# Paridad con la categoría YouTube de /settings (cogs/settings.py ->
# YouTubeCategory): agregar, quitar, mención por rol y el aviso de
# last_error del fix de cogs/youtube.py._check_one.


def _youtube_sub_json(guild, s: dict) -> dict:
    return {
        "id": s["id"],
        "youtube_channel_id": s["youtube_channel_id"],
        "youtube_channel_name": s["youtube_channel_name"],
        "discord_channel_id": str(s["discord_channel_id"]),
        "discord_channel_name": _channel_name(guild, s["discord_channel_id"]),
        "mention_role_id": str(s["mention_role_id"]) if s["mention_role_id"] else None,
        "last_error": s["last_error"],
    }


@guild_api
async def _api_youtube_get(request: web.Request, guild_id: int) -> web.Response:
    guild = _bot_guild(request, guild_id)
    subs = await list_youtube_subs(guild_id)
    return web.json_response(
        {"subscriptions": [_youtube_sub_json(guild, s) for s in subs]}
    )


@guild_api
async def _api_youtube_post(request: web.Request, guild_id: int) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_post, ip, 5):
        return web.json_response({"error": "rate limit"}, status=429)
    data = await _json_body(request)
    channel_id = (data.get("channel_id") or "").strip() if data else ""
    discord_channel_id = _to_int(data.get("discord_channel_id")) if data else None
    if not channel_id or discord_channel_id is None:
        return web.json_response(
            {"error": "channel_id y discord_channel_id son obligatorios"}, status=400
        )
    resolved = await resolve_youtube_channel(channel_id)
    if resolved is None:
        return web.json_response(
            {"error": "No se pudo obtener información del canal. Verifica el ID."},
            status=400,
        )
    channel_name = resolved["name"] or channel_id
    added = await add_youtube_sub(
        guild_id, discord_channel_id, channel_id, channel_name, discord_channel_id
    )
    if added:
        if resolved["latest_video_id"]:
            await update_last_video_id(
                guild_id, channel_id, resolved["latest_video_id"]
            )
        await _log_audit(request, guild_id, "youtube.add", detail=channel_name)
    return web.json_response({"added": added})


@guild_api
async def _api_youtube_delete(request: web.Request, guild_id: int) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_delete, ip, 3):
        return web.json_response({"error": "rate limit"}, status=429)
    sub_id = _to_int(request.match_info.get("sub_id"))
    if sub_id is None:
        return web.json_response({"error": "id inválido"}, status=400)
    removed = await remove_youtube_sub_by_id(guild_id, sub_id)
    if removed:
        await _log_audit(request, guild_id, "youtube.remove", detail=f"sub_id={sub_id}")
    return web.json_response({"removed": removed})


@guild_api
async def _api_youtube_patch(request: web.Request, guild_id: int) -> web.Response:
    sub_id = _to_int(request.match_info.get("sub_id"))
    if sub_id is None:
        return web.json_response({"error": "id inválido"}, status=400)
    data = await _json_body(request)
    if data is None or "mention_role_id" not in data:
        return web.json_response(
            {"error": "mention_role_id es obligatorio"}, status=400
        )
    role_id = None
    if data["mention_role_id"] is not None:
        role_id = _to_int(data["mention_role_id"])
        if role_id is None:
            return web.json_response({"error": "mention_role_id inválido"}, status=400)
    updated = await set_youtube_mention_role_by_id(guild_id, sub_id, role_id)
    if updated:
        await _log_audit(
            request,
            guild_id,
            "youtube.update_mention_role",
            detail=f"sub_id={sub_id} role_id={role_id}",
        )
    return web.json_response({"updated": updated})


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

    timestamp = embed.get("timestamp")
    if timestamp is not None:
        if not isinstance(timestamp, str):
            return "timestamp inválido"
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return "timestamp inválido"
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
    opts_err = validate_send_options(options)
    if opts_err:
        return "", "", "", opts_err
    if mode == "layout_v2":
        layout = data.get("layout")
        err = validate_layout_v2_payload(layout)
        if err:
            return "", "", "", err
        # Los bloques de archivo referencian bytes en memoria de proceso con
        # TTL corto (ver _pending_layout_files) — nada que sobreviva hasta el
        # próximo disparo de un anuncio programado ni hasta que se cargue una
        # plantilla guardada. Esta función es el punto único que usan
        # /embeds/schedule y /embeds/templates (POST y PUT), así que el
        # rechazo acá cubre los tres.
        if has_file_block(layout.get("blocks")):
            return (
                "",
                "",
                "",
                "los bloques de archivo no se pueden programar ni guardar en una"
                ' plantilla — solo funcionan con "Enviar ahora"',
            )
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


async def _reject_unassignable_roles(request: web.Request, guild_id: int, layout):
    """Respuesta de error si algún botón de rol del layout apunta a un rol que
    no corresponde, o None si están todos bien.

    validate_layout_v2_payload solo mira que role_id sea un número: sin esto,
    el id podía ser de CUALQUIER rol (mismo IDOR por id numérico que pack_id).
    Dos cosas distintas se cierran acá:

    - Rol de otro servidor: el click ya fallaba (guild.get_role resuelve contra
      el guild de la interacción), pero quedaba un botón muerto guardado en
      layout_button_actions. Se rechaza al crearlo, no al clickearlo.
    - Escalada de privilegios: el panel se entra con MANAGE_GUILD, que NO
      incluye gestionar roles. Sin este chequeo, quien tuviera acceso al panel
      podía fabricarse un botón que reparte cualquier rol por debajo del bot
      -- Administrador incluido -- y clickearlo. Se aplica la misma jerarquía
      que Discord aplica en su propia UI: nada por encima del top role de uno
      mismo (el dueño del servidor no tiene ese techo).
    """
    role_ids = [
        btn.get("role_id")
        for btn in iter_buttons(layout.get("blocks") or [])
        if btn.get("style") == "role"
    ]
    if not role_ids:
        return None
    guild = _bot_guild(request, guild_id)
    session = await get_session(request)
    member = guild.get_member(int(session["user_id"]))
    for raw in role_ids:
        role = guild.get_role(int(raw))
        if role is None or role.is_default():
            return web.json_response(
                {
                    "error": "un botón de rol apunta a un rol que no existe en este servidor"
                },
                status=400,
            )
        if role.managed:
            return web.json_response(
                {
                    "error": f"el rol {role.name} lo gestiona una integración y no se puede repartir"
                },
                status=400,
            )
        if guild.me is None or role >= guild.me.top_role:
            return web.json_response(
                {
                    "error": f"el rol {role.name} está por encima del rol de Purgito: el botón no podría asignarlo"
                },
                status=400,
            )
        # member None = no está cacheado; se trata como el caso restrictivo.
        if guild.owner_id != getattr(member, "id", None) and (
            member is None or role >= member.top_role
        ):
            return web.json_response(
                {
                    "error": f"no puedes repartir el rol {role.name}: está por encima del tuyo"
                },
                status=403,
            )
    return None


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
    send_options = sanitize_send_options(data.get("send_options"))
    opts_err = validate_send_options(send_options)
    if opts_err:
        return web.json_response({"error": opts_err}, status=400)
    extra = send_kwargs(send_options)
    custom_identity = wants_custom_identity(send_options)
    discord_files: list[discord.File] = []
    used_upload_ids: list[str] = []
    if mode == "layout_v2":
        denied = await _reject_unassignable_roles(request, guild_id, data["layout"])
        if denied is not None:
            return denied
        discord_files, used_upload_ids, file_err = _resolve_layout_files(
            data["layout"].get("blocks"), guild_id
        )
        if file_err:
            return web.json_response({"error": file_err}, status=400)
    try:
        if mode == "layout_v2":
            layout = data["layout"]
            assignments = assign_button_custom_ids(layout)
            await _register_role_buttons(request.app["bot"], guild_id, assignments)
            view = build_layout_view(layout, files=discord_files)
            # files solo se agrega al kwargs cuando hay algo -- ni channel.send
            # ni (sobre todo) Webhook.send toleran files=None: channel.send lo
            # traduce a MISSING solo, Webhook.send lo pasa crudo y explota
            # iterándolo (ver handle_message_parameters en discord/http.py).
            content_kwargs: dict = {"view": view, **extra}
            if discord_files:
                content_kwargs["files"] = discord_files
            if custom_identity:
                await send_via_webhook(
                    request.app["bot"],
                    guild_id,
                    channel,
                    username=send_options.get("username", ""),
                    avatar_url=send_options.get("avatar_url", ""),
                    **content_kwargs,
                )
            else:
                await channel.send(**content_kwargs)
        else:
            embeds = [discord.Embed.from_dict(e) for e in data["embeds"]]
            if custom_identity:
                await send_via_webhook(
                    request.app["bot"],
                    guild_id,
                    channel,
                    username=send_options.get("username", ""),
                    avatar_url=send_options.get("avatar_url", ""),
                    embeds=embeds,
                    **extra,
                )
            else:
                await channel.send(embeds=embeds, **extra)
    except WebhookIdentityError as e:
        return web.json_response({"error": str(e)}, status=400)
    except discord.HTTPException as e:
        # Típicamente una URL de imagen/ícono que Discord rechaza.
        return web.json_response(
            {"error": f"Discord rechazó el contenido: {e.text or e}"}, status=400
        )
    # Recién acá, con el envío confirmado: si hubiera fallado (permisos,
    # Discord rechazando el contenido) los archivos pendientes quedan vivos
    # para el reintento, en vez de obligar a resubirlos.
    for upload_id in used_upload_ids:
        _pending_layout_files.pop(upload_id, None)
    await _log_audit(
        request, guild_id, "embeds.send", detail=f"channel_id={channel.id}"
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
        # (nunca se re-mintea en el loop de anuncios.py). Por eso el chequeo
        # de roles va ANTES de acuñar nada: un anuncio programado sobrevive a
        # reinicios y se dispara solo, así que un botón mal formado acá queda
        # repartiendo el rol para siempre.
        layout = data["layout"]
        denied = await _reject_unassignable_roles(request, guild_id, layout)
        if denied is not None:
            return denied
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
    await _log_audit(
        request,
        guild_id,
        "embeds.schedule",
        detail=f"channel_id={channel.id} mode={mode}",
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
    options = sanitize_send_options(data.get("send_options"))
    opts_err = validate_send_options(options)
    if opts_err:
        return web.json_response({"error": opts_err}, status=400)
    payload = {"embeds": embeds}
    if options:
        payload["send_options"] = options
    result = await add_shared_embed(json.dumps(payload), guild_id)
    if result is None:
        return web.json_response(
            {
                "error": "límite diario de links compartidos alcanzado — intenta de nuevo mañana"
            },
            status=429,
        )
    share_id, expires_at = result
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
    await _log_audit(request, guild_id, "embed_template.create", detail=name)
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
    await _log_audit(request, guild_id, "embed_template.update", detail=name)
    return web.json_response({"updated": True})


@guild_api
async def _api_embed_template_delete(
    request: web.Request, guild_id: int
) -> web.Response:
    template_id = _to_int(request.match_info.get("template_id"))
    if template_id is None:
        return web.json_response({"error": "template_id inválido"}, status=400)
    deleted = await delete_embed_template(template_id, guild_id)
    if deleted:
        await _log_audit(
            request,
            guild_id,
            "embed_template.delete",
            detail=f"template_id={template_id}",
        )
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
# El playground llama a simulate_message -> generation.generate_markov_reply,
# el mismo motor caro (query + build/generate en el ThreadPoolExecutor
# default compartido con TODOS los guilds) que la generación real, y no
# tenía ningún límite -- cualquier admin autenticado podía golpearlo en loop
# desde el navegador y degradar la generación de Markov de otros servidores.
_rate_playground: LRUDict = LRUDict(512)
_rate_premium_checkout: LRUDict = LRUDict(512)


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
    await record_uploaded_image(guild_id, url)
    return web.json_response({"url": url})


@guild_api
async def _api_embeds_uploads_get(request: web.Request, guild_id: int) -> web.Response:
    """Últimas imágenes subidas desde el editor de este guild, para el
    selector de reutilización — R2 ya dedupe por contenido, esto es solo el
    índice de qué URLs subió el guild."""
    return web.json_response({"urls": await list_uploaded_images(guild_id)})


@guild_api
async def _api_embeds_resolve_gif(request: web.Request, guild_id: int) -> web.Response:
    """Resuelve un link de tenor.com/view/... al .gif animado real (Fase 4)
    — el navegador no puede pegarle a tenor.com directo por CORS, así que
    esto corre del lado del servidor. `url: null` (no un error) si no se
    pudo resolver -- el frontend cae al aviso manual de siempre."""
    ip = _client_ip(request)
    if not _rate_ok(_rate_upload, ip, 10):
        return web.json_response({"error": "rate limit"}, status=429)
    data = await _json_body(request)
    if data is None:
        return web.json_response({"error": "body inválido"}, status=400)
    url = (data.get("url") or "").strip()
    if not url:
        return web.json_response({"error": "falta la url"}, status=400)
    resolved = await resolve_tenor_gif_url(url)
    return web.json_response({"url": resolved})


# ---------------- API: bloques File de Layout V2 ----------------
#
# Un bloque File de Components V2 necesita el archivo real adjunto al MISMO
# mensaje (Discord exige la referencia "attachment://<filename>", no una URL
# — ver el comentario grande de layout_v2.py). Eso descarta subir directo a
# R2 como las imágenes de embeds: acá no hace falta persistencia entre
# sesiones (Fase 2 ronda 2 los dejó fuera de Programar y de plantillas por
# eso mismo), solo un puente corto entre "el usuario elige el archivo en el
# editor" y "hace click en Enviar ahora", segundos o minutos después.
#
# _pending_layout_files es un dict en memoria del proceso de Python, sin
# tocar disco ni R2. NOTA PARA EL FUTURO: si alguna vez el bot corre con más
# de un worker/proceso (hoy es uno solo), esto se rompe en silencio — un
# upload que cae en el worker A y un /embeds/send que cae en el worker B no
# van a encontrar la entrada. El día que eso pase, esta tabla necesita mudarse
# a algo compartido entre procesos (Redis, o directo R2 con TTL corto).
#
# No se sube por el mismo endpoint que las imágenes de embeds (Content-Type
# application/octet-stream, igual patrón) porque tampoco comparte su
# validación: acá no se sniffean magic bytes de imagen -- puede ser
# cualquier tipo de archivo, es justamente lo que distingue un bloque File de
# un MediaGallery.

MAX_LAYOUT_FILE_UPLOAD_BYTES = env_int("MAX_LAYOUT_FILE_UPLOAD_BYTES", 10 * 1024 * 1024)
_PENDING_LAYOUT_FILE_TTL = 600  # 10 minutos
_MAX_PENDING_LAYOUT_FILES = 200  # tope defensivo de memoria del proceso

_pending_layout_files: dict[str, dict] = {}


def _prune_pending_layout_files() -> None:
    now = time.monotonic()
    expired = [k for k, v in _pending_layout_files.items() if v["expires_at"] <= now]
    for k in expired:
        del _pending_layout_files[k]


@guild_api
async def _api_layout_file_upload(request: web.Request, guild_id: int) -> web.Response:
    ip = _client_ip(request)
    if not _rate_ok(_rate_upload, ip, 10):
        return web.json_response({"error": "rate limit"}, status=429)
    filename = (request.match_info.get("filename") or "").strip()
    if not filename:
        return web.json_response({"error": "falta el nombre del archivo"}, status=400)
    if len(filename) > MAX_FILENAME_LEN:
        return web.json_response(
            {
                "error": f"el nombre del archivo supera los {MAX_FILENAME_LEN} caracteres"
            },
            status=400,
        )
    max_bytes = MAX_LAYOUT_FILE_UPLOAD_BYTES
    if request.content_length and request.content_length > max_bytes:
        return web.json_response(
            {
                "error": f"el archivo supera el máximo de {max_bytes // (1024 * 1024)} MB"
            },
            status=413,
        )
    data = await request.read()
    if len(data) > max_bytes:
        return web.json_response(
            {
                "error": f"el archivo supera el máximo de {max_bytes // (1024 * 1024)} MB"
            },
            status=413,
        )
    if not data:
        return web.json_response({"error": "archivo vacío"}, status=400)
    _prune_pending_layout_files()
    if len(_pending_layout_files) >= _MAX_PENDING_LAYOUT_FILES:
        return web.json_response(
            {
                "error": "demasiadas subidas pendientes en el servidor, intenta en unos minutos"
            },
            status=429,
        )
    upload_id = secrets.token_urlsafe(16)
    _pending_layout_files[upload_id] = {
        "data": data,
        "filename": filename,
        "guild_id": guild_id,
        "expires_at": time.monotonic() + _PENDING_LAYOUT_FILE_TTL,
    }
    return web.json_response({"upload_id": upload_id, "filename": filename})


def _resolve_layout_files(
    blocks, guild_id: int
) -> tuple[list[discord.File], list[str], str | None]:
    """Recorre el layout en el mismo orden que build_layout_view/_build_block
    y resuelve cada bloque "file" a un discord.File real, leyendo (sin
    todavía borrar) de _pending_layout_files. Devuelve
    (files_en_orden, upload_ids_usados, error) — el caller borra
    upload_ids_usados de _pending_layout_files recién si el envío sale bien
    (así un fallo de permisos no obliga a resubir el archivo)."""
    _prune_pending_layout_files()
    files: list[discord.File] = []
    used: list[str] = []
    seen_filenames: dict[str, int] = {}

    def walk(items) -> str | None:
        for b in items or []:
            kind = b.get("type")
            if kind == "container":
                err = walk(b.get("children"))
                if err:
                    return err
            elif kind == "file":
                upload_id = b.get("upload_id")
                entry = _pending_layout_files.get(upload_id)
                if entry is None or entry["guild_id"] != guild_id:
                    return (
                        "un archivo adjunto expiró o no se encontró — vuelve a elegirlo"
                    )
                filename = entry["filename"]
                # Discord exige nombres de adjunto únicos por mensaje -- pasa
                # si el mismo archivo se usa en dos bloques (ej. "Duplicar
                # bloque"). Mismos bytes, filename distinto por instancia.
                count = seen_filenames.get(filename, 0)
                seen_filenames[filename] = count + 1
                if count:
                    stem, dot, ext = filename.rpartition(".")
                    filename = f"{stem or filename} ({count + 1}){dot}{ext}"
                files.append(discord.File(io.BytesIO(entry["data"]), filename=filename))
                used.append(upload_id)
        return None

    err = walk(blocks)
    return files, used, err


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
    # La landing de Premium no puede abrir checkout todavía: primero hay que
    # elegir un guild. Solo conserva los dos planes conocidos y un locale de
    # la lista soportada; así el destino post-login nunca acepta una URL que
    # venga libremente del navegador.
    plan = request.query.get("plan")
    locale = request.query.get("locale", "es")
    if plan in ("monthly", "annual") and locale in ("es", "en", "ru", "ja", "de"):
        session["auth_return_to"] = f"/{locale}/perfil?plan={plan}"
    else:
        session.pop("auth_return_to", None)
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
    if not _rate_ok(_rate_auth_callback, _client_ip(request), 10):
        raise web.HTTPFound("/auth/error")
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
    # Id de esta sesión puntual (no del usuario): revoke_session lo marca en
    # logout para invalidarla server-side -- ver _session_logged_in.
    session["sid"] = secrets.token_urlsafe(16)
    # Precarga el cache: /users/@me/guilds tiene rate limit estricto por token
    # (~1 req/s) y sin esto el primer request autenticado recibiría 429.
    _user_guilds_cache[user["id"]] = (time.monotonic() + _GUILDS_CACHE_TTL, manage)
    # Si llegó desde el selector de Premium, vuelve a elegir el servidor con
    # el ciclo ya validado. Cualquier otro login conserva el destino general.
    raise web.HTTPFound(session.pop("auth_return_to", LANDING_URL))


async def _revoke_discord_token(request: web.Request, access_token: str) -> None:
    """Revoca el access_token en Discord. Best-effort a propósito: si Discord
    está caído o tarda, no puede trabar el logout -- revoke_session ya es la
    protección primaria del lado de Purgito. Sin esto, un access_token
    filtrado ANTES del logout (XSS, log, SESSION_SECRET comprometido) seguía
    siendo un bearer token válido contra la API real de Discord
    (identify/email/guilds) aun después de que la víctima se desloguea acá --
    revoke_session solo corta el acceso al dashboard de Purgito, no a Discord."""
    try:
        http = request.app["http"]
        async with http.post(
            f"{_DISCORD_API}/oauth2/token/revoke",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "token": access_token,
                "token_type_hint": "access_token",
            },
        ):
            pass
    except (aiohttp.ClientError, asyncio.TimeoutError):
        log.warning("No se pudo revocar el access_token en Discord durante el logout")


async def _auth_logout(request: web.Request) -> web.StreamResponse:
    session = await get_session(request)
    # Sin esto, un re-login del mismo user reutilizaría la lista de guilds del token anterior.
    _user_guilds_cache.pop(session.get("user_id"), None)
    # Server-side: sin esto, una copia de la cookie tomada antes del logout
    # (XSS, log, dispositivo compartido) seguiría autenticando -- ver
    # _session_logged_in. session.invalidate() de abajo solo borra la cookie
    # de ESTE navegador.
    sid = session.get("sid")
    if sid:
        await revoke_session(sid)
    access_token = session.get("access_token")
    if access_token:
        await _revoke_discord_token(request, access_token)
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
    if await _session_logged_in(session):
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
        "<title>Purgito · Acceso denegado</title>"
        f"<style>{_AUTH_ERROR_STYLE}</style></head>"
        "<body><div><h1>Acceso denegado</h1>"
        f"<p>{message}</p>"
        "<a href='/auth/login'>Volver a intentar</a>"
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
# Un reembolso NO implica por sí solo que la suscripción se revoque -- son
# decisiones independientes en el modelo de Polar (confirmado: el objeto
# Refund trae su propio campo `revoke_benefits`, separado del `status` del
# reembolso). refund.created dispara "regardless of status" (incluye
# pending/failed), así que además hay que esperar a status="succeeded".
# order.refunded no sirve para esto: ese payload es un Order y no trae
# revoke_benefits, solo refunded_amount/total_amount (full vs. parcial).
_POLAR_REFUND_TYPES = ("refund.created", "refund.updated")
_POLAR_REFUND_SUCCEEDED_STATUS = "succeeded"


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
    # Zona protegida (ver CLAUDE.md): esto solo CREA la sesión de checkout en
    # Polar -- la activación real de premium pasa por _webhook_polar (ya
    # rate-limitado aparte), así que este límite no puede interferir con ella.
    # Generoso a propósito: el botón del dashboard ya se desactiva al click
    # (ver landing/js/tabs/premium.js) y solo vuelve a habilitarse si esta
    # llamada falla o el admin abandona el checkout de Polar y reintenta --
    # unos pocos reintentos legítimos por minuto tienen que entrar de sobra.
    if not _rate_ok(_rate_premium_checkout, _client_ip(request), 8):
        return web.json_response({"error": "demasiadas solicitudes"}, status=429)
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


def _polar_event_timestamp(event, payload: dict | None) -> datetime | None:
    """El `timestamp` del sobre del webhook (cuándo Polar generó ESTE evento
    puntual, no cuándo llegó acá) -- lo usa _webhook_polar para no dejar que
    un reintento tardío de un evento viejo pise el estado de uno más nuevo.
    None si no se pudo determinar: mejor no bloquear el evento que arriesgar
    descartar uno legítimo por un parseo que falló."""
    if event is not None:
        ts = getattr(event, "timestamp", None)
        return ts if isinstance(ts, datetime) else None
    raw = (payload or {}).get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _webhook_polar(request: web.Request) -> web.Response:
    # Público: Polar autentica con la firma Standard Webhooks, no con sesión.
    # Sin secret, validate_event firmaría con clave vacía y cualquiera podría
    # forjar un evento válido (premium gratis): mejor rechazar de plano.
    if not POLAR_WEBHOOK_SECRET:
        log.error(
            "Webhook de Polar recibido pero POLAR_WEBHOOK_SECRET no está configurado"
        )
        return web.json_response({"error": "webhook no configurado"}, status=503)
    # Generoso a propósito (ver _rate_webhook_polar): esto es un backstop
    # contra flood, no un límite funcional -- Polar no debería tropezar con él.
    if not _rate_ok(_rate_webhook_polar, _client_ip(request), 60, window=60.0):
        return web.json_response({"error": "rate limit"}, status=429)
    body = await request.read()
    payload: dict | None = None
    try:
        event = validate_event(body, dict(request.headers), POLAR_WEBHOOK_SECRET)
        event_type = event.TYPE
        metadata = getattr(event.data, "metadata", None) or {}
        product_id = getattr(event.data, "product_id", None)
        status = getattr(event.data, "status", None)
        revoke_benefits = getattr(event.data, "revoke_benefits", None)
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
        #
        # Con su propio try anidado: una excepción levantada DENTRO de un
        # bloque `except` no la atrapa el `except Exception` de abajo, sale
        # del handler entero. Esta es justo la rama que parsea JSON sin tipar
        # -- la que más lo necesita -- y un body que no sea un objeto (una
        # lista, o "data" como string) tumbaba el request con un 500, que es
        # lo que el catch-all de abajo existe para evitar.
        try:
            event = None
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise TypeError("el payload del webhook no es un objeto JSON")
            event_type = payload.get("type")
            data = payload.get("data")
            data = data if isinstance(data, dict) else {}
            metadata = data.get("metadata") or {}
            product_id = data.get("product_id")
            status = data.get("status")
            revoke_benefits = data.get("revoke_benefits")
        except Exception:
            log.exception(
                "Webhook de Polar de tipo no modelado con payload inesperado (firma OK)"
            )
            return web.json_response({"error": "payload inválido"}, status=400)
    except Exception:
        # Firma válida (o el body ni llegó a esa altura) pero el payload no
        # tiene la forma esperada -- JSON inválido, o JSON válido que no
        # matchea el schema de Polar para ese event_type (ValidationError de
        # pydantic al armar el modelo tipado). Sin este catch-all, cualquiera
        # de estos dos casos tumbaba el handler con un 500 no controlado en
        # vez de un 4xx -- y un 500 hace que Polar reintente contra algo que
        # nunca se va a resolver solo, agotando sus reintentos en vano.
        log.exception("Webhook de Polar con payload inesperado (firma OK)")
        return web.json_response({"error": "payload inválido"}, status=400)

    # subscription.created con status "trialing" = arrancó un free trial:
    # cuenta como alta igual que subscription.active.
    is_trial_start = (
        event_type == "subscription.created" and status == _POLAR_TRIAL_STATUS
    )
    is_refund_event = event_type in _POLAR_REFUND_TYPES
    # revoke_benefits es la decisión explícita de Polar (o de quien emitió el
    # reembolso desde su dashboard) de que ESTE reembolso corta el acceso --
    # no todo reembolso lo hace (uno parcial, por ejemplo). status="succeeded"
    # porque refund.created dispara "regardless of status", incluyendo
    # pending/failed -- no hay que actuar hasta que el reembolso se concretó.
    is_refund_revoke = (
        is_refund_event
        and status == _POLAR_REFUND_SUCCEEDED_STATUS
        and bool(revoke_benefits)
    )

    if (
        event_type not in _POLAR_ACTIVATE + _POLAR_DEACTIVATE
        and not is_trial_start
        and not is_refund_event
    ):
        # INFO y no debug: nivel de log configurado en producción es INFO
        # (bot.py) -- un debug acá es invisible, y esta línea es la única
        # forma de notar en producción si Polar empieza a mandar un tipo de
        # evento relevante que el código todavía no reconoce.
        log.info("Webhook de Polar ignorado: %s (status=%s)", event_type, status)
        return web.json_response({"ok": True})

    guild_id = _to_int(metadata.get("guild_id") if isinstance(metadata, dict) else None)
    if guild_id is None:
        log.warning("Webhook de Polar %s sin guild_id válido en metadata", event_type)
        return web.json_response({"ok": True})

    if is_refund_event and not is_refund_revoke:
        # Reembolso real (parcial, o total sin revoke_benefits, o todavía no
        # "succeeded") que a propósito NO toca el acceso -- se loguea aparte
        # del "ignorado" genérico de arriba porque acá SÍ hay un guild_id
        # identificado, útil para reconciliar manualmente si hace falta.
        log.info(
            "Webhook de Polar %s para guild %s no revoca beneficios "
            "(status=%s, revoke_benefits=%s)",
            event_type,
            guild_id,
            status,
            revoke_benefits,
        )
        return web.json_response({"ok": True})

    # Polar no garantiza orden de entrega, y dos webhooks del mismo guild
    # pueden llegar casi simultáneos (reintentos en paralelo, o dos eventos
    # legítimos muy seguidos): el chequeo de "es más viejo que el último
    # aplicado" y el propio cambio de estado + el nuevo watermark se hacen
    # los tres como una sola operación atómica en
    # apply_premium_webhook_change (bajo _db_lock) -- si estuvieran
    # separados acá, dos requests concurrentes podrían leer el mismo
    # watermark viejo cada uno por su lado y los dos pasar el chequeo antes
    # de que cualquiera de los dos llegue a escribir nada.
    event_at = _polar_event_timestamp(event, payload)
    event_at_iso = event_at.isoformat() if event_at is not None else None

    if event_type in _POLAR_ACTIVATE or is_trial_start:
        note = _polar_plan_note(product_id)
        reason = "trial" if is_trial_start else "pago confirmado"
        was_new = await set_premium(guild_id, note, event_at_iso)
        if was_new is None:
            log.info(
                "Webhook de Polar %s para guild %s ignorado: más viejo que el "
                "último evento aplicado (entrega fuera de orden)",
                event_type,
                guild_id,
            )
        elif was_new:
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
        removed = await unset_premium(guild_id, event_at_iso)
        if removed is None:
            log.info(
                "Webhook de Polar %s para guild %s ignorado: más viejo que el "
                "último evento aplicado (entrega fuera de orden)",
                event_type,
                guild_id,
            )
        else:
            reason = "reembolso" if is_refund_revoke else event_type
            log.info(
                "Premium desactivado por Polar para guild %s (%s)", guild_id, reason
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
    app = web.Application(middlewares=[_security_headers_middleware, _cors_middleware])
    app["bot"] = bot
    # Sesión HTTP compartida para llamadas a la API de Discord, con timeout global.
    app["http"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    app.router.add_get("/health", _api_health)
    # Fuera del bloque DASHBOARD_ENABLED: Polar le pega sin sesión OAuth
    # y el premium debe poder activarse aunque la auth esté apagada.
    app.router.add_post("/webhooks/polar", _webhook_polar)
    # /es/estado es pública (sin login) y no es parte del dashboard: vive
    # fuera del bloque DASHBOARD_ENABLED por el mismo motivo que /health.
    app.router.add_get("/api/status", _api_status)
    app.router.add_get("/api/status/guild/{guild_id}", _api_status_guild)

    if DASHBOARD_ENABLED:
        setup_session(app, _new_session_storage())
        app.router.add_get("/auth/login", _auth_login)
        app.router.add_get("/auth/callback", _auth_callback)
        # POST, no GET: logout muta estado (revoke_session + session.invalidate).
        # SameSite=Lax deja pasar la cookie en una navegación GET top-level
        # (un link, `window.location=`, un meta-refresh) aunque venga de otro
        # origen -- una página maliciosa podía forzar el logout de una víctima
        # con solo redirigirla acá. El frontend dispara esto con fetch(POST),
        # no con un <a href> navegable -- ver landing/script.js.
        app.router.add_post("/auth/logout", _auth_logout)
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
        app.router.add_put(f"{base}/settings/chat/tunables", _api_chat_tunables_put)
        app.router.add_get(
            "/api/guilds/{guild_id}/channels/{channel_id}/settings",
            _api_channel_settings_get,
        )
        app.router.add_put(
            "/api/guilds/{guild_id}/channels/{channel_id}/settings",
            _api_channel_settings_put,
        )
        app.router.add_post(f"{base}/chat/playground", _api_chat_playground_post)
        app.router.add_get(f"{base}/settings/exempt-roles", _api_exempt_roles_get)
        app.router.add_post(f"{base}/settings/exempt-roles", _api_exempt_roles_post)
        app.router.add_delete(
            f"{base}/settings/exempt-roles/{{role_id}}", _api_exempt_roles_delete
        )
        app.router.add_get(f"{base}/settings/exempt-channels", _api_exempt_channels_get)
        app.router.add_post(
            f"{base}/settings/exempt-channels", _api_exempt_channels_post
        )
        app.router.add_delete(
            f"{base}/settings/exempt-channels/{{channel_id}}",
            _api_exempt_channels_delete,
        )
        app.router.add_get(
            f"{base}/settings/spontaneous-channels", _api_spontaneous_channels_get
        )
        app.router.add_post(
            f"{base}/settings/spontaneous-channels", _api_spontaneous_channels_post
        )
        app.router.add_delete(
            f"{base}/settings/spontaneous-channels/{{channel_id}}",
            _api_spontaneous_channels_delete,
        )
        app.router.add_get(
            f"{base}/settings/mention-channels", _api_mention_channels_get
        )
        app.router.add_post(
            f"{base}/settings/mention-channels", _api_mention_channels_post
        )
        app.router.add_delete(
            f"{base}/settings/mention-channels/{{channel_id}}",
            _api_mention_channels_delete,
        )
        app.router.add_get(f"{base}/settings/corpus", _api_corpus_get)
        app.router.add_post(f"{base}/settings/corpus", _api_corpus_post)
        app.router.add_delete(
            f"{base}/settings/corpus/{{channel_id}}", _api_corpus_delete
        )
        app.router.add_post(
            f"{base}/settings/corpus/import/{{channel_id}}", _api_corpus_import_post
        )
        app.router.add_post(f"{base}/settings/corpus/amnesia", _api_corpus_amnesia_post)
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
        app.router.add_patch(f"{base}/settings/frases/{{frase_id}}", _api_frases_patch)
        app.router.add_get(f"{base}/settings/frases/channels", _api_frase_channels_get)
        app.router.add_post(
            f"{base}/settings/frases/channels", _api_frase_channels_post
        )
        app.router.add_delete(
            f"{base}/settings/frases/channels/{{channel_id}}",
            _api_frase_channels_delete,
        )
        app.router.add_get(f"{base}/frases/packs", _api_frase_packs_get)
        app.router.add_post(f"{base}/frases/packs", _api_frase_packs_post)
        app.router.add_delete(
            f"{base}/frases/packs/{{pack_id}}", _api_frase_packs_delete
        )
        app.router.add_get(
            f"{base}/frases/packs/{{pack_id}}/channels",
            _api_frase_pack_channels_get,
        )
        app.router.add_post(
            f"{base}/frases/packs/{{pack_id}}/channels",
            _api_frase_pack_channels_post,
        )
        app.router.add_delete(
            f"{base}/frases/packs/{{pack_id}}/channels/{{channel_id}}",
            _api_frase_pack_channels_delete,
        )
        app.router.add_get(f"{base}/settings/triggers", _api_triggers_get)
        app.router.add_post(f"{base}/settings/triggers", _api_triggers_post)
        app.router.add_delete(
            f"{base}/settings/triggers/{{trigger_id}}", _api_triggers_delete
        )
        app.router.add_get(f"{base}/settings/updates", _api_updates_get)
        app.router.add_put(f"{base}/settings/updates", _api_updates_put)
        app.router.add_get(f"{base}/settings/gifs", _api_server_gifs_get)
        app.router.add_post(f"{base}/settings/gifs", _api_server_gifs_post)
        app.router.add_delete(
            f"{base}/settings/gifs/{{gif_id}}", _api_server_gifs_delete
        )
        app.router.add_post(f"{base}/settings/gifs/verify", _api_server_gifs_verify)
        app.router.add_get(
            f"{base}/settings/gifs/blocked", _api_server_gifs_blocked_get
        )
        app.router.add_delete(
            f"{base}/settings/gifs/blocked/{{key}}", _api_server_gifs_unblock
        )
        app.router.add_post(
            f"{base}/settings/gifs/{{gif_id}}/block", _api_server_gifs_block
        )
        app.router.add_get(f"{base}/youtube", _api_youtube_get)
        app.router.add_post(f"{base}/youtube", _api_youtube_post)
        app.router.add_delete(f"{base}/youtube/{{sub_id}}", _api_youtube_delete)
        app.router.add_patch(f"{base}/youtube/{{sub_id}}", _api_youtube_patch)
        app.router.add_post(f"{base}/embeds/send", _api_embeds_send)
        app.router.add_post(f"{base}/embeds/share", _api_embeds_share)
        app.router.add_post(f"{base}/embeds/schedule", _api_embeds_schedule)
        app.router.add_post(f"{base}/embeds/validate", _api_embeds_validate)
        app.router.add_post(f"{base}/embeds/upload", _api_embeds_upload)
        app.router.add_get(f"{base}/embeds/uploads", _api_embeds_uploads_get)
        app.router.add_post(f"{base}/embeds/resolve-gif", _api_embeds_resolve_gif)
        app.router.add_post(
            f"{base}/embeds/upload-file/{{filename}}", _api_layout_file_upload
        )
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
        app.router.add_get("/api/guilds/{guild_id}/audit", _api_audit_log_get)
        log.info("OAuth2 + API del dashboard habilitados")
    else:
        log.info("Auth deshabilitada: solo /health y el webhook de Polar")

    _runner = web.AppRunner(app)
    await _runner.setup()
    # 127.0.0.1, no 0.0.0.0: nginx es el único que le habla a este puerto
    # (proxy_pass http://127.0.0.1:8080 en los tres server blocks, ver
    # DEPLOY.md) -- escuchar en todas las interfaces lo dejaba alcanzable
    # directo desde internet si el firewall del droplet no lo tapaba,
    # saltándose Cloudflare y nginx por completo (rate limits por IP
    # incluidos, ver _client_ip más arriba).
    site = web.TCPSite(_runner, "127.0.0.1", WEB_PORT)
    await site.start()
    log.info("Web API iniciada en 127.0.0.1:%s", WEB_PORT)


async def stop_web_server() -> None:
    global _runner
    if _runner is not None:
        app = _runner.app
        if app is not None and "http" in app:
            await app["http"].close()
        await _runner.cleanup()
        _runner = None
