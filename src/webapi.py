"""Servidor web mínimo del bot: webhook de Polar, API de premium y health check.

Lo que queda acá tras desmontar la capa web (landing + panel/dashboard) es lo
que NO puede morir mientras el sitio se rediseña desde cero:

- ``/webhooks/polar``: Polar avisa altas/bajas de suscripción por acá. Sin este
  endpoint, un pago cobrado nunca activa el premium del servidor.
- ``/api/server/{guild_id}/premium`` y ``.../premium/checkout``: API pura (sin
  HTML) para consultar el estado premium y abrir un checkout. Es lo que va a
  consumir el sitio nuevo para poder seguir vendiendo Premium.
- ``/health``: monitoreo externo.
- OAuth2 de Discord + sesión: no es "página", es la capa de autenticación de la
  que dependen los dos endpoints de premium (``guild_api`` exige sesión con
  permiso de administrar el guild). Sin esto el checkout es inalcanzable.
- ``/api/me``: quién soy. El navbar de la landing lo consulta por CORS para
  pintar la variante con sesión (nick + avatar) o el botón de login.

Todo lo demás (galería de GIFs, páginas del panel, APIs de settings/embeds/gifs,
subida de imágenes, admin) se eliminó junto con el frontend.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import aiohttp
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
)
from cogs.premium import is_premium_guild, set_premium, unset_premium
from db import list_premium_guilds
from utils import LRUDict

log = logging.getLogger(__name__)

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
    if DASHBOARD_ENABLED and origin and (
        origin == DASHBOARD_BASE_URL or origin in LANDING_ORIGINS
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
        return web.json_response({"error": "sesión expirada, inicia sesión de nuevo"}, status=401)
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
    """Quién soy. Lo consume el navbar de la landing (purgito.app) por CORS con
    credentials: la cookie de sesión es del apex (.purgito.app), así que llega
    igual desde otro subdominio.

    Sin sesión responde 200 con logged_in=False, nunca 401: el navbar solo
    decide qué variante pintar y un 401 ensuciaría la consola del navegador.
    """
    session = await get_session(request)
    body = {"logged_in": False}
    if session.get("user_id"):
        body = {
            "logged_in": True,
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
        message = "No se pudo completar el inicio de sesión con Discord. Intenta de nuevo."
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
        log.error("Webhook de Polar recibido pero POLAR_WEBHOOK_SECRET no está configurado")
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
                guild_id, note, reason,
            )
        else:
            # Ya estaba premium (ej: subscription.active llega después de que
            # subscription.created ya activó el trial) — set_premium es
            # idempotente, no hay nada nuevo que reportar.
            log.debug(
                "Webhook de Polar %s (%s) para guild %s: ya estaba premium, sin cambios",
                event_type, reason, guild_id,
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
        # ".purgito.app" en producción la comparte con la landing.
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

        base = "/api/server/{guild_id}"
        app.router.add_get(f"{base}/premium", _api_premium_get)
        app.router.add_post(f"{base}/premium/checkout", _api_premium_checkout)
        log.info("OAuth2 + API de premium habilitados")
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
