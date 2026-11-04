"""Interfaz privada local. Reutiliza OBSERVABILITY_TOKEN, sin usuarios/cookies nuevos."""

import base64
from pathlib import Path

import aiohttp
from aiohttp import web

from observability.runtime import internal_access

_FILES = {
    "": ("index.html", "text/html"),
    "studio.css": ("studio.css", "text/css"),
    "studio.js": ("studio.js", "application/javascript"),
}
_PROXY_HEADERS = ("Forwarded", "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP")


def application(token, *, backend_port=8080, port=18081, assets=None):
    if not token:
        raise ValueError("Configura OBSERVABILITY_TOKEN antes de abrir Studio")
    assets = assets or Path(__file__).resolve().parents[2] / "studio"
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @web.middleware
    async def private(request, handler):
        if request.host not in hosts or any(
            h in request.headers for h in _PROXY_HEADERS
        ):
            return web.Response(status=404)
        if request.headers.get("Origin") and request.headers["Origin"] not in origins:
            return web.Response(status=403)
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return web.Response(status=403)
        supplied = request.headers.get("Authorization", "")
        if supplied.lower().startswith("basic "):
            try:
                user, password = (
                    base64.b64decode(supplied[6:], validate=True).decode().split(":", 1)
                )
                supplied = f"Bearer {password}" if user == "admin" else ""
            except (ValueError, UnicodeError):
                supplied = ""
        if internal_access({"Authorization": supplied}, token) != "ok":
            return web.Response(
                status=401,
                headers={
                    "WWW-Authenticate": 'Basic realm="Purgito Studio", charset="UTF-8"',
                    "Cache-Control": "no-store",
                },
            )
        if request.method == "POST" and (
            request.content_type != "application/json"
            or request.headers.get("X-Studio-Request") != "1"
        ):
            return web.Response(status=403)
        result = await handler(request)
        result.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            }
        )
        return result

    app = web.Application(middlewares=[private], client_max_size=8192)

    async def assets_handler(request):
        entry = _FILES.get(request.match_info.get("asset", ""))
        if not entry:
            raise web.HTTPNotFound()
        return web.Response(
            body=(assets / entry[0]).read_bytes(), content_type=entry[1]
        )

    async def proxy(request):
        path = request.path
        try:
            async with aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=10)
            ) as client:
                # Destino fijo loopback. No se reenvían cookies, cabeceras proxy ni Origin.
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

    app.router.add_get("/", assets_handler)
    app.router.add_get("/{asset:studio\\.(css|js)}", assets_handler)
    app.router.add_get("/internal/studio/report", proxy)
    app.router.add_post("/internal/studio/annotations", proxy)
    return app
