"""Interfaz privada de Studio. Escucha solo en loopback y admite dos entradas, separadas por el Host:

* local  (127.0.0.1/localhost:<puerto>): administración desde el propio servidor o por túnel SSH.
  Credencial Basic ``admin`` + OBSERVABILITY_TOKEN. Rechaza cualquier cabecera de proxy.
* remota (STUDIO_PUBLIC_HOST): detrás de Cloudflare Tunnel + Access. No hay contraseña: se exige el JWT
  de Access, verificado (firma, emisor, audiencia, vigencia y correo autorizado). Sin esa configuración
  completa este modo no existe y ese Host responde 404.

El navegador nunca recibe ni envía el token interno: el companion lo añade al hablar con el backend
(autenticación de servicio), que mantiene sus propias protecciones (loopback, Host y token).
"""

import base64
import ipaddress
import logging
from pathlib import Path

import aiohttp
from aiohttp import web

from observability.runtime import internal_access

from .access import AccessDenied, AccessVerifier

log = logging.getLogger("studio.access")

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
}
_ROOT_FILES = {"index.html", "favicon.svg"}
_DIRS = {"css", "js", "fonts"}
# Cualquier cabecera que delate un intermediario: el acceso local nunca pasa por uno.
_PROXY_HEADERS = (
    "Forwarded",
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Forwarded-Proto",
    "X-Real-IP",
    "CF-Connecting-IP",
    "CF-Ray",
    "Cf-Access-Jwt-Assertion",
)
_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def asset_index(assets):
    """{ruta URL: archivo} de todo lo que el panel puede servir. Lista cerrada, construida UNA vez al
    arrancar a partir de lo que hay en disco: una petición solo hace una búsqueda en este diccionario,
    así que ningún dato de la petición llega jamás a una ruta del sistema de archivos."""
    root = Path(assets).resolve()
    index = {}

    def add(url, candidate):
        file = (
            candidate.resolve()
        )  # un enlace simbólico hacia fuera de la raíz queda excluido
        if (
            root in file.parents
            and file.is_file()
            and file.suffix in _TYPES
            and not file.name.startswith(("test_", "."))
        ):
            index[url] = file

    for name in _ROOT_FILES:
        add(f"/{name}", root / name)
    add("/", root / "index.html")
    for directory in _DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for candidate in base.rglob("*"):
            if any(part.startswith(".") for part in candidate.relative_to(base).parts):
                continue
            add("/" + candidate.relative_to(root).as_posix(), candidate)
    return index


def _is_loopback(remote):
    try:
        return ipaddress.ip_address(remote or "").is_loopback
    except ValueError:
        return False


def application(
    token, *, backend_port=8080, port=18081, assets=None, access=None, keys_fetcher=None
):
    if not token:
        raise ValueError("Configura OBSERVABILITY_TOKEN antes de abrir Studio")
    assets = Path(assets or Path(__file__).resolve().parents[2] / "studio")
    local_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    local_origins = {f"http://{h}" for h in local_hosts}
    verifier = AccessVerifier(access, keys_fetcher) if access else None

    def denied(status, reason):
        log.warning("studio.access denegado status=%s motivo=%s", status, reason)
        return web.Response(status=status, headers={"Cache-Control": "no-store"})

    async def authenticate(request):
        """Devuelve (respuesta de rechazo | None, identidad | None)."""
        host = request.host
        if host in local_hosts:
            if any(h in request.headers for h in _PROXY_HEADERS):
                return web.Response(status=404), None
            origin = request.headers.get("Origin")
            if origin and origin not in local_origins:
                return web.Response(status=403), None
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                return web.Response(status=403), None
            supplied = request.headers.get("Authorization", "")
            if supplied.lower().startswith("basic "):
                try:
                    user, password = (
                        base64.b64decode(supplied[6:], validate=True)
                        .decode()
                        .split(":", 1)
                    )
                    supplied = f"Bearer {password}" if user == "admin" else ""
                except (ValueError, UnicodeError):
                    supplied = ""
            if internal_access({"Authorization": supplied}, token) != "ok":
                return (
                    web.Response(
                        status=401,
                        headers={
                            "WWW-Authenticate": 'Basic realm="Purgito Studio", charset="UTF-8"',
                            "Cache-Control": "no-store",
                        },
                    ),
                    None,
                )
            return None, "local"
        if verifier is None or host != access.host:
            return web.Response(status=404), None
        # Entrada remota: solo cloudflared (mismo host) puede llegar aquí.
        if not _is_loopback(request.remote):
            return web.Response(status=404), None
        try:
            claims = await verifier.verify(
                request.headers.get("Cf-Access-Jwt-Assertion", "")
            )
        except AccessDenied as exc:
            return denied(403, exc.code), None
        origin = request.headers.get("Origin")
        if origin and origin != f"https://{access.host}":
            return denied(403, "origin"), None
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return denied(403, "fetch-site"), None
        if request.method not in ("GET", "HEAD") and origin is None:
            return denied(403, "origin-required"), None
        return None, claims["email"]

    @web.middleware
    async def private(request, handler):
        refusal, who = await authenticate(request)
        if refusal is not None:
            return refusal
        if request.method == "POST" and (
            request.content_type != "application/json"
            or request.headers.get("X-Studio-Request") != "1"
        ):
            return web.Response(status=403)
        if who != "local" and (request.method == "POST" or request.path == "/"):
            log.info(
                "studio.access identidad=%s %s %s", who, request.method, request.path
            )
        result = await handler(request)
        result.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": _CSP,
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
            }
        )
        result.headers.setdefault("Cache-Control", "no-store")
        if who != "local":
            result.headers["Strict-Transport-Security"] = "max-age=31536000"
        return result

    app = web.Application(middlewares=[private], client_max_size=8192)

    files = asset_index(assets)

    async def static(request):
        target = files.get(request.path)
        if target is None:
            return web.Response(status=404)
        headers = (
            {"Cache-Control": "private, max-age=86400"}
            if target.suffix == ".woff2"
            else {"Cache-Control": "no-cache"}
        )
        try:
            body = target.read_bytes()
        except OSError:
            return web.Response(status=404)
        return web.Response(
            body=body,
            content_type=_TYPES[target.suffix].split(";")[0],
            charset="utf-8" if target.suffix != ".woff2" else None,
            headers=headers,
        )

    async def proxy(request):
        path = request.path
        try:
            async with aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=10)
            ) as client:
                # Destino fijo loopback. No se reenvían cookies, cabeceras de proxy, Origin ni el JWT de Access.
                async with client.request(
                    request.method,
                    f"http://127.0.0.1:{int(backend_port)}{path}",
                    params=request.query,
                    data=await request.read() if request.method == "POST" else None,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    allow_redirects=False,
                ) as upstream:
                    return web.Response(
                        body=await upstream.read(),
                        status=upstream.status,
                        content_type="application/json",
                    )
        except Exception:
            return web.json_response(
                {"error": "El bot no responde en el puerto local configurado"},
                status=503,
            )

    app.router.add_get("/internal/studio/report", proxy)
    app.router.add_post("/internal/studio/annotations", proxy)
    app.router.add_get("/{path:.*}", static)
    return app
