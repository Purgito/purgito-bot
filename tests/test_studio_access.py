"""Acceso remoto a Studio (Cloudflare Access): verificación del JWT y separación de las dos entradas.

Todo local: el par de claves RSA se genera aquí y las «claves públicas del equipo» las entrega un
proveedor falso. No hay red ni cuentas de Cloudflare.
"""

import asyncio
import base64
import json
import logging

from aiohttp import BasicAuth, web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest

from studio.access import AccessDenied, AccessSettings, AccessVerifier, fetch_jwks
from studio.local_server import application

TEAM = "purgito-test.cloudflareaccess.com"
AUD = "a" * 64
HOST = "studio.example.test"
EMAIL = "operador@example.test"
TOKEN = "studio-test-only-observability-token"
NOW = 1_800_000_000


def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Signer:
    def __init__(self, kid="k1"):
        self.kid = kid
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @property
    def jwk(self):
        nums = self.key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "kid": self.kid,
            "alg": "RS256",
            "use": "sig",
            "n": b64u(nums.n.to_bytes(256, "big")),
            "e": b64u(nums.e.to_bytes(3, "big")),
        }

    def token(self, claims=None, *, header=None, key=None, kid=None):
        payload = {
            "iss": f"https://{TEAM}",
            "aud": [AUD],
            "email": EMAIL,
            "exp": NOW + 3600,
            "iat": NOW - 10,
            "nbf": NOW - 10,
            "sub": "uid",
        }
        payload.update(claims or {})
        head = {"alg": "RS256", "kid": kid or self.kid, "typ": "JWT", **(header or {})}
        signing = (
            f"{b64u(json.dumps(head).encode())}.{b64u(json.dumps(payload).encode())}"
        )
        sig = (key or self.key).sign(
            signing.encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        return f"{signing}.{b64u(sig)}"


def settings(**over):
    base = {
        "STUDIO_ACCESS_TEAM": TEAM,
        "STUDIO_ACCESS_AUD": AUD,
        "STUDIO_PUBLIC_HOST": HOST,
        "STUDIO_ACCESS_EMAILS": EMAIL,
    }
    base.update(over)
    return AccessSettings.from_env(base)


def verifier(signer, *, clock=lambda: NOW, **kw):
    async def fetch():
        return {"keys": [signer.jwk]}

    return AccessVerifier(settings(), fetch, clock=clock, **kw)


def check(verifier_, token):
    return asyncio.run(verifier_.verify(token))


def denied(verifier_, token):
    with pytest.raises(AccessDenied) as exc:
        asyncio.run(verifier_.verify(token))
    return exc.value.code


# ---------------------------------------------------------------- configuración


def test_remote_access_is_off_unless_fully_configured():
    assert AccessSettings.from_env({}) is None
    assert AccessSettings.from_env({"STUDIO_ACCESS_TEAM": "  "}) is None
    ok = settings(STUDIO_ACCESS_EMAILS="A@Example.test, b@example.test ,")
    assert (
        ok.emails == frozenset({"a@example.test", "b@example.test"}) and ok.host == HOST
    )
    for name in (
        "STUDIO_ACCESS_TEAM",
        "STUDIO_ACCESS_AUD",
        "STUDIO_PUBLIC_HOST",
        "STUDIO_ACCESS_EMAILS",
    ):
        with pytest.raises(
            ValueError, match=name
        ):  # configuración a medias: error, no «medio abierto»
            settings(**{name: ""})
    for bad in (
        {"STUDIO_ACCESS_TEAM": "evil.example.com"},
        {"STUDIO_ACCESS_TEAM": "x.cloudflareaccess.com.evil.test"},
        {"STUDIO_ACCESS_AUD": "abc"},
        {"STUDIO_ACCESS_AUD": "G" * 64},
        {"STUDIO_PUBLIC_HOST": "https://studio.example.test"},
        {"STUDIO_PUBLIC_HOST": "studio.example.test:443"},
        {"STUDIO_PUBLIC_HOST": "x.cloudflareaccess.com"},
        {"STUDIO_ACCESS_EMAILS": "no-es-un-correo"},
        {"STUDIO_ACCESS_EMAILS": ",,"},
    ):
        with pytest.raises(ValueError):
            settings(**bad)


# -------------------------------------------------------------------- JWT


def test_valid_token_returns_claims_and_normalizes_email():
    signer = Signer()
    claims = check(verifier(signer), signer.token({"email": EMAIL.upper()}))
    assert claims["email"] == EMAIL
    assert (
        check(verifier(signer), signer.token({"aud": AUD}))["sub"] == "uid"
    )  # aud como cadena


def test_forged_expired_and_foreign_tokens_are_denied_with_a_short_code():
    signer, other = Signer(), Signer()
    v = verifier(signer)
    assert denied(v, "") == "missing" and denied(v, None) == "missing"
    for malformed in ("a.b", "a.b.c.d", "....", "no-es-jwt", "x" * 9000):
        assert denied(v, malformed) == "malformed", malformed
    assert (
        denied(v, signer.token(key=other.key)) == "signature"
    )  # firmado con otra clave
    good = signer.token()
    head, payload, sig = good.split(".")
    tampered = json.loads(base64.urlsafe_b64decode(payload + "=="))
    tampered["email"] = "otro@example.test"
    assert (
        denied(v, f"{head}.{b64u(json.dumps(tampered).encode())}.{sig}") == "signature"
    )  # payload alterado
    assert (
        denied(v, signer.token({"iss": "https://otro.cloudflareaccess.com"})) == "iss"
    )
    assert (
        denied(v, signer.token({"aud": ["b" * 64]})) == "aud"
    )  # token de OTRA aplicación del mismo equipo
    assert (
        denied(v, signer.token({"aud": []})) == "aud"
        and denied(v, signer.token({"aud": None})) == "aud"
    )
    assert denied(v, signer.token({"exp": NOW - 31})) == "exp"
    check(v, signer.token({"exp": NOW - 29}))  # dentro de la tolerancia de reloj
    assert (
        denied(v, signer.token({"exp": None})) == "exp"
        and denied(v, signer.token({"exp": True})) == "exp"
    )
    assert denied(v, signer.token({"exp": "9999999999"})) == "exp"
    assert denied(v, signer.token({"nbf": NOW + 31})) == "nbf"
    assert denied(v, signer.token({"iat": NOW + 31})) == "iat"
    assert (
        denied(v, signer.token({"email": "otro@example.test"})) == "email"
    )  # válido en Access, no en Studio
    assert (
        denied(v, signer.token({"email": None})) == "email"
        and denied(v, signer.token({"email": ["a"]})) == "email"
    )
    no_email = signer.token()
    body = json.loads(base64.urlsafe_b64decode(no_email.split(".")[1] + "=="))
    body.pop("email")
    h0 = no_email.split(".")[0]
    signing = f"{h0}.{b64u(json.dumps(body).encode())}"
    sig = signer.key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    assert (
        denied(v, f"{signing}.{b64u(sig)}") == "email"
    )  # un token de servicio no entra como persona


def test_algorithm_confusion_and_unsigned_tokens_are_rejected():
    signer = Signer()
    v = verifier(signer)
    for alg in ("none", "None", "HS256", "rs256", "RS384", "ES256", "PS256", "", None):
        assert denied(v, signer.token(header={"alg": alg})) == "alg", alg
    # Clásico: HS256 firmado con la clave pública como secreto.
    import hashlib
    import hmac

    pub = signer.jwk["n"].encode()
    head = b64u(json.dumps({"alg": "HS256", "kid": "k1"}).encode())
    body = b64u(
        json.dumps(
            {"iss": f"https://{TEAM}", "aud": [AUD], "email": EMAIL, "exp": NOW + 99}
        ).encode()
    )
    mac = hmac.new(pub, f"{head}.{body}".encode(), hashlib.sha256).digest()
    assert denied(v, f"{head}.{body}.{b64u(mac)}") == "alg"
    # «none» con firma vacía.
    nohead = b64u(json.dumps({"alg": "none", "kid": "k1"}).encode())
    assert (
        denied(v, f"{nohead}.{body}.") == "malformed"
        or denied(v, f"{nohead}.{body}.") == "alg"
    )
    # Cabecera sin kid o con kid de otro tipo.
    for header in ({"kid": None}, {"kid": 7}, {"kid": ["k1"]}):
        assert denied(v, signer.token(header=header)) == "kid"


def test_unknown_kid_cannot_force_key_downloads_and_rotation_works():
    signer = Signer("k1")
    calls = []
    clock = [NOW]
    keys = {"keys": [signer.jwk]}

    async def fetch():
        calls.append(1)
        return keys

    v = AccessVerifier(
        settings(), fetch, clock=lambda: clock[0], key_ttl=3600, refetch_min=300
    )
    check(v, signer.token())
    assert len(calls) == 1
    for _ in range(
        5
    ):  # kid desconocido repetido: sin descargas nuevas dentro de la ventana
        assert denied(v, signer.token(kid="otro")) == "kid"
    assert len(calls) == 1
    # Rotación: aparece una clave nueva; tras la ventana mínima se descarga y se acepta.
    rotated = Signer("k2")
    keys["keys"] = [signer.jwk, rotated.jwk]
    clock[0] += 301
    check(v, rotated.token())
    assert len(calls) == 2
    # Caducidad de la caché: se refresca aunque el kid exista.
    clock[0] += 3601
    check(v, signer.token({"exp": clock[0] + 99, "iat": clock[0], "nbf": clock[0]}))
    assert len(calls) == 3


def test_key_endpoint_failures_deny_instead_of_allowing():
    signer = Signer()

    async def boom():
        raise OSError("sin red")

    assert (
        denied(AccessVerifier(settings(), boom, clock=lambda: NOW), signer.token())
        == "keys-unavailable"
    )

    async def garbage():
        return {
            "keys": [
                {"kty": "RSA", "kid": "k1", "n": "!!", "e": "AQAB"},
                {"kty": "EC", "kid": "k1"},
                "x",
                None,
                {"kty": "RSA", "kid": "k1", "n": b64u(b"\x01" * 16), "e": "AQAB"},
            ]
        }

    assert (
        denied(AccessVerifier(settings(), garbage, clock=lambda: NOW), signer.token())
        == "kid"
    )  # claves débiles/ilegibles se ignoran

    async def empty():
        return {}

    assert (
        denied(AccessVerifier(settings(), empty, clock=lambda: NOW), signer.token())
        == "kid"
    )


def test_jwks_download_only_uses_the_team_https_endpoint(monkeypatch):
    seen = {}

    class Response:
        status = 200

        def __init__(self, body):
            self.content = type("C", (), {"read": staticmethod(self._read)})()
            self.body = body

        async def _read(self, n):
            return self.body[:n]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Session:
        def __init__(self, **kw):
            seen["kw"] = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kw):
            seen["url"], seen["get"] = url, kw
            return Response(b'{"keys": []}')

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    assert asyncio.run(fetch_jwks(TEAM)) == {"keys": []}
    assert seen["url"] == f"https://{TEAM}/cdn-cgi/access/certs"
    assert seen["get"]["allow_redirects"] is False and seen["kw"]["trust_env"] is False


# ------------------------------------------------------- entradas del panel


class Backend:
    """Backend ficticio que registra qué le llega desde el panel."""

    def __init__(self):
        self.requests = []
        app = web.Application()
        app.router.add_get("/internal/studio/report", self.handle)
        app.router.add_post("/internal/studio/annotations", self.handle)
        self.server = TestServer(app)

    async def handle(self, request):
        self.requests.append(
            {
                "method": request.method,
                "headers": dict(request.headers),
                "body": await request.read(),
            }
        )
        return web.json_response(
            {"ok": True}, status=201 if request.method == "POST" else 200
        )


def run_panel(test, *, access=True):
    signer = Signer()

    async def fetch():
        return {"keys": [signer.jwk]}

    async def go():
        backend = Backend()
        async with backend.server:
            app = application(
                TOKEN,
                backend_port=backend.server.port,
                port=18081,
                access=settings() if access else None,
                keys_fetcher=fetch,
            )
            async with TestClient(TestServer(app)) as ui:
                await test(ui, signer, backend, app)

    asyncio.run(go())


def remote(signer, **extra):
    import time

    token = signer.token(
        {
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()) - 5,
            "nbf": int(time.time()) - 5,
        }
    )
    return {
        "Host": HOST,
        "Cf-Access-Jwt-Assertion": token,
        "X-Forwarded-For": "203.0.113.7",
        "Cf-Ray": "abc",
        **extra,
    }


def test_remote_entry_serves_the_panel_only_with_a_valid_access_token():
    async def test(ui, signer, backend, app):
        page = await ui.get("/", headers=remote(signer))
        assert page.status == 200 and "Purgito Studio" in await page.text()
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        assert "font-src 'self'" in page.headers["Content-Security-Policy"]
        assert page.headers["Strict-Transport-Security"].startswith("max-age=")
        assert page.headers["Cache-Control"] == "no-cache"
        for asset in ("/js/main.mjs", "/css/studio.css", "/fonts/lexend-latin.woff2"):
            assert (await ui.get(asset, headers=remote(signer))).status == 200
        assert (
            await ui.get("/js/test_derive.mjs", headers=remote(signer))
        ).status == 404
        # Sin token, con token inválido o con identidad «anunciada» por cabecera: 403.
        base = {"Host": HOST, "X-Forwarded-For": "203.0.113.7"}
        assert (await ui.get("/", headers=base)).status == 403
        assert (
            await ui.get("/", headers={**base, "Cf-Access-Jwt-Assertion": "x.y.z"})
        ).status == 403
        spoof = {
            **base,
            "Cf-Access-Authenticated-User-Email": EMAIL,
            "Cf-Access-Authenticated-User-Id": "1",
        }
        assert (await ui.get("/", headers=spoof)).status == 403
        assert (
            await ui.get(
                "/",
                headers={**base, "Authorization": BasicAuth("admin", TOKEN).encode()},
            )
        ).status == 403  # el token interno no abre la entrada remota
        assert (
            await ui.get(
                "/",
                headers=remote(
                    signer,
                    **{
                        "Cf-Access-Jwt-Assertion": signer.token(
                            {"email": "otro@example.test"}
                        )
                    },
                ),
            )
        ).status == 403
        # Otro Host: no existe.
        assert (
            await ui.get("/", headers=remote(signer, Host="otro.example.test"))
        ).status == 404
        assert (
            await ui.get("/", headers=remote(signer, Host=f"{HOST}:18081"))
        ).status == 404

    run_panel(test)


def test_remote_entry_does_not_exist_without_configuration():
    async def test(ui, signer, backend, app):
        assert (await ui.get("/", headers=remote(signer))).status == 404
        assert (
            await ui.get("/internal/studio/report", headers=remote(signer))
        ).status == 404

    run_panel(test, access=False)


def test_service_credentials_stay_between_panel_and_backend():
    async def test(ui, signer, backend, app):
        response = await ui.get(
            "/internal/studio/report?start=1",
            headers=remote(
                signer,
                Cookie="CF_Authorization=secreto; sesion=1",
                Origin=f"https://{HOST}",
            ),
        )
        assert response.status == 200
        sent = backend.requests[-1]["headers"]
        assert sent["Authorization"] == f"Bearer {TOKEN}"
        lowered = {k.lower() for k in sent}
        # Ni el JWT, ni cookies, ni cabeceras de proxy o identidad llegan al backend.
        assert not lowered & {
            "cf-access-jwt-assertion",
            "cookie",
            "x-forwarded-for",
            "cf-ray",
            "origin",
            "cf-access-authenticated-user-email",
        }
        # Y el navegador nunca ve el token interno.
        body = await response.text()
        assert TOKEN not in body and TOKEN not in json.dumps(dict(response.headers))
        page = await ui.get("/", headers=remote(signer))
        assert TOKEN not in await page.text()
        for asset in ("/js/main.mjs", "/js/api.mjs", "/css/studio.css"):
            assert (
                TOKEN not in await (await ui.get(asset, headers=remote(signer))).text()
            )

    run_panel(test)


def test_remote_writes_require_same_origin_json_and_explicit_header(caplog):
    async def test(ui, signer, backend, app):
        url = "/internal/studio/annotations"
        body = {"at": "2026-11-01T00:00:00Z", "title": "x"}
        good = remote(signer, Origin=f"https://{HOST}", **{"X-Studio-Request": "1"})
        with caplog.at_level(logging.INFO, logger="studio.access"):
            assert (await ui.post(url, headers=good, json=body)).status == 201
        assert any(
            EMAIL in r.getMessage() and "POST" in r.getMessage() for r in caplog.records
        )  # quién escribió
        assert (
            await ui.post(
                url, headers={k: v for k, v in good.items() if k != "Origin"}, json=body
            )
        ).status == 403
        assert (
            await ui.post(
                url, headers={**good, "Origin": "https://evil.example"}, json=body
            )
        ).status == 403
        assert (
            await ui.post(url, headers={**good, "Origin": f"http://{HOST}"}, json=body)
        ).status == 403  # esquema distinto
        assert (
            await ui.post(
                url, headers={**good, "Sec-Fetch-Site": "cross-site"}, json=body
            )
        ).status == 403
        assert (
            await ui.post(
                url,
                headers={k: v for k, v in good.items() if k != "X-Studio-Request"},
                json=body,
            )
        ).status == 403
        assert (
            await ui.post(url, headers=good, data="x=1")
        ).status == 403  # no es JSON
        assert (
            await ui.get(
                "/", headers=remote(signer, **{"Sec-Fetch-Site": "cross-site"})
            )
        ).status == 403
        assert (
            await ui.get("/", headers=remote(signer, Origin="https://evil.example"))
        ).status == 403
        assert len(backend.requests) == 1  # solo la escritura legítima llegó al backend

    run_panel(test)


def test_denials_are_logged_with_a_code_and_never_with_the_token(caplog):
    async def test(ui, signer, backend, app):
        token = signer.token({"aud": ["b" * 64]})
        with caplog.at_level(logging.WARNING, logger="studio.access"):
            assert (
                await ui.get(
                    "/", headers={"Host": HOST, "Cf-Access-Jwt-Assertion": token}
                )
            ).status == 403
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert (
            "motivo=aud" in logged
            and token not in logged
            and token.split(".")[1] not in logged
        )

    run_panel(test)


def test_local_entry_is_unchanged_and_ignores_access_tokens():
    async def test(ui, signer, backend, app):
        local = {"Host": "127.0.0.1:18081"}
        valid = {**local, "Authorization": BasicAuth("admin", TOKEN).encode()}
        assert (await ui.get("/", headers=local)).status == 401
        assert (await ui.get("/", headers=valid)).status == 200
        assert (
            await ui.get(
                "/",
                headers={**local, "Authorization": BasicAuth("admin", "otra").encode()},
            )
        ).status == 401
        assert (
            await ui.get(
                "/",
                headers={**local, "Authorization": BasicAuth("root", TOKEN).encode()},
            )
        ).status == 401
        # Un JWT de Access sin contraseña NO abre la entrada local.
        assert (
            await ui.get(
                "/", headers={**local, "Cf-Access-Jwt-Assertion": signer.token()}
            )
        ).status == 404
        # La entrada local rechaza cualquier rastro de intermediario, aunque lleve la contraseña correcta.
        for header in (
            "X-Forwarded-For",
            "X-Forwarded-Host",
            "X-Forwarded-Proto",
            "X-Real-IP",
            "CF-Connecting-IP",
            "CF-Ray",
            "Forwarded",
        ):
            assert (await ui.get("/", headers={**valid, header: "x"})).status == 404, (
                header
            )
        assert (
            await ui.get("/", headers={**valid, "Origin": "https://evil.example"})
        ).status == 403
        assert (
            await ui.get(
                "/",
                headers={
                    "Host": "localhost:18081",
                    "Authorization": valid["Authorization"],
                },
            )
        ).status == 200
        assert (
            await ui.get(
                "/",
                headers={
                    "Host": "127.0.0.1:9999",
                    "Authorization": valid["Authorization"],
                },
            )
        ).status == 404

    run_panel(test)


def test_only_loopback_peers_can_use_the_remote_entry():
    async def test(ui, signer, backend, app):
        class Transport:
            def __init__(self, peer):
                self.peer = peer

            def get_extra_info(self, name, default=None):
                return self.peer if name == "peername" else default

        for peer in (
            ("203.0.113.9", 5000),
            ("10.1.2.3", 5000),
            ("2001:db8::1", 5000),
            ("fe80::1", 5000),
        ):
            request = make_mocked_request(
                "GET", "/", headers=remote(signer), transport=Transport(peer), app=app
            )
            assert (await app._handle(request)).status == 404, peer
        ok = make_mocked_request(
            "GET",
            "/",
            headers=remote(signer),
            transport=Transport(("127.0.0.1", 5000)),
            app=app,
        )
        assert (await app._handle(ok)).status == 200

    run_panel(test)


def test_panel_process_does_not_load_the_bots_configuration():
    """Como servicio, el panel solo debe ver su propio entorno: importarlo no puede cargar el .env del bot."""
    import subprocess
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, studio.local_server, studio.access;"
        "print(sorted(m for m in ('config', 'dotenv', 'discord', 'asyncpg', 'webapi') if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env={"PATH": "/usr/bin", "PYTHONPATH": str(src)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "[]"


def test_http_path_traversal_attempts_never_reach_files_outside_the_allowlist():
    from yarl import URL

    async def test(ui, signer, backend, app):
        headers = remote(signer)
        for raw in (
            "/js/%2e%2e/css/studio.css",
            "/js/..%2fcss/studio.css",
            "/%2e%2e/%2e%2e/etc/passwd",
            "/js/%2e%2e%2f%2e%2e%2fsrc/studio/access.py",
            "/css/..%5c..%5csrc/studio/access.py",
            "/js/main.mjs%00.css",
            "/js/main.mjs/",
            "/src/studio/access.py",
            "/index.html/../../README.md",
            "/js/test_derive.mjs",
            "/fonts/OFL.txt",
        ):
            response = await ui.get(URL(raw, encoded=True), headers=headers)
            assert response.status in (404, 400), (raw, response.status)
            assert "def " not in await response.text()
        # Control: la ruta legítima sí responde.
        assert (await ui.get("/js/main.mjs", headers=headers)).status == 200

    run_panel(test)


# ------------------------------------- vuelta de Cloudflare Access (navegación entre sitios)

# Lo que envía el navegador al volver de <equipo>.cloudflareaccess.com tras el código de un solo uso
# (y también al recargar esa misma página: Chrome conserva el Sec-Fetch-Site de la navegación original).
ACCESS_RETURN = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    "Referer": f"https://{TEAM}/",
}


def test_access_login_redirect_loads_studio_for_an_authorized_user(caplog):
    async def test(ui, signer, backend, app):
        with caplog.at_level(logging.INFO, logger="studio.access"):
            page = await ui.get("/", headers=remote(signer, **ACCESS_RETURN))
            assert page.status == 200 and "Purgito Studio" in await page.text()
            # Las protecciones de la respuesta siguen intactas.
            assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
            assert page.headers["Cross-Origin-Opener-Policy"] == "same-origin"
            assert (
                await ui.get("/index.html", headers=remote(signer, **ACCESS_RETURN))
            ).status == 200
            # Sin Sec-Fetch-User (redirección automática o recarga) también entra.
            no_user = {k: v for k, v in ACCESS_RETURN.items() if k != "Sec-Fetch-User"}
            assert (await ui.get("/", headers=remote(signer, **no_user))).status == 200
            assert (await ui.head("/", headers=remote(signer, **no_user))).status == 200
        assert any(f"identidad={EMAIL} GET /" in r.getMessage() for r in caplog.records)
        # Después, la propia página carga sus recursos y datos como mismo origen.
        same = {
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        assert (
            await ui.get("/js/main.mjs", headers=remote(signer, **same))
        ).status == 200
        report = await ui.get(
            "/internal/studio/report?start=1", headers=remote(signer, **same)
        )
        assert report.status == 200

    run_panel(test)


def test_access_redirect_exception_never_replaces_the_jwt(caplog):
    async def test(ui, signer, backend, app):
        import time

        base = {"Host": HOST, "X-Forwarded-For": "203.0.113.7", **ACCESS_RETURN}
        intruder = Signer()  # firma con una clave que no es la del equipo
        now = int(time.time())
        fresh = {"exp": now + 3600, "iat": now - 5, "nbf": now - 5}
        cases = {
            "missing": base,
            "malformed": {**base, "Cf-Access-Jwt-Assertion": "x.y.z"},
            "signature": {
                **base,
                "Cf-Access-Jwt-Assertion": intruder.token(fresh, kid=signer.kid),
            },
            "exp": {
                **base,
                "Cf-Access-Jwt-Assertion": signer.token(
                    {"exp": now - 3600, "iat": now - 7200, "nbf": now - 7200}
                ),
            },
            "aud": {
                **base,
                "Cf-Access-Jwt-Assertion": signer.token({**fresh, "aud": ["b" * 64]}),
            },
            "iss": {
                **base,
                "Cf-Access-Jwt-Assertion": signer.token(
                    {**fresh, "iss": "https://otro.cloudflareaccess.com"}
                ),
            },
            "email": {
                **base,
                "Cf-Access-Jwt-Assertion": signer.token(
                    {**fresh, "email": "otro@example.test"}
                ),
            },
            "alg": {
                **base,
                "Cf-Access-Jwt-Assertion": signer.token(fresh, header={"alg": "HS256"}),
            },
        }
        for code, headers in cases.items():
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="studio.access"):
                response = await ui.get("/", headers=headers)
            assert response.status == 403, code
            assert f"motivo={code}" in caplog.text, code
        # Identidad «anunciada» por cabecera tampoco vale en la navegación de vuelta.
        spoof = {**base, "Cf-Access-Authenticated-User-Email": EMAIL}
        assert (await ui.get("/", headers=spoof)).status == 403
        # Ni el token interno.
        basic = {**base, "Authorization": BasicAuth("admin", TOKEN).encode()}
        assert (await ui.get("/", headers=basic)).status == 403
        # Otro Host o un par que no es loopback siguen sin existir.
        assert (
            await ui.get(
                "/", headers=remote(signer, Host="otro.example.test", **ACCESS_RETURN)
            )
        ).status == 404
        assert backend.requests == []

    run_panel(test)


def test_cross_site_writes_stay_blocked_even_when_disguised_as_navigation(caplog):
    async def test(ui, signer, backend, app):
        url = "/internal/studio/annotations"
        body = {"at": "2026-11-01T00:00:00Z", "title": "x"}
        # Envío de formulario desde otro sitio (navegación POST de nivel superior).
        form = remote(signer, Origin="https://evil.example", **ACCESS_RETURN)
        assert (await ui.post(url, headers=form, data="title=x")).status == 403
        assert (await ui.post(url, headers=form, json=body)).status == 403
        assert (await ui.post("/", headers=form, data="title=x")).status == 403
        # Aunque copie todo lo de una escritura legítima salvo el sitio de origen.
        disguised = remote(
            signer,
            Origin=f"https://{HOST}",
            **{**ACCESS_RETURN, "X-Studio-Request": "1"},
        )
        assert (await ui.post(url, headers=disguised, json=body)).status == 403
        cors = remote(
            signer,
            Origin=f"https://{HOST}",
            **{
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "X-Studio-Request": "1",
            },
        )
        assert (await ui.post(url, headers=cors, json=body)).status == 403
        # Un POST sin Origin, aun con el resto de cabeceras correctas, tampoco.
        no_origin = remote(signer, **{**ACCESS_RETURN, "X-Studio-Request": "1"})
        assert (await ui.post(url, headers=no_origin, json=body)).status == 403
        # El método forma parte de la excepción: un POST al documento que imita una navegación
        # se corta en la comprobación de sitio, no más tarde por casualidad.
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="studio.access"):
            assert (await ui.post("/", headers=disguised, json=body)).status == 403
        assert "motivo=fetch-site POST '/'" in caplog.text
        for method in ("PUT", "PATCH", "DELETE"):
            assert (
                await ui.request(method, "/", headers=remote(signer, **ACCESS_RETURN))
            ).status in (403, 405), method
        assert backend.requests == []

    run_panel(test)


def test_redirect_exception_only_covers_the_top_level_document(caplog):
    async def test(ui, signer, backend, app):
        def cross(**over):
            return remote(signer, **{**ACCESS_RETURN, **over})

        # Datos internos: ni como navegación ni como subrecurso desde otro sitio.
        for path in ("/internal/studio/report", "/internal/studio/report?start=1"):
            assert (await ui.get(path, headers=cross())).status == 403, path
            assert (
                await ui.get(
                    path,
                    headers=cross(
                        **{"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
                    ),
                )
            ).status == 403, path
        # Recursos estáticos navegados o incluidos desde otro sitio.
        for path in (
            "/js/main.mjs",
            "/css/studio.css",
            "/fonts/lexend-latin.woff2",
            "/favicon.svg",
        ):
            assert (await ui.get(path, headers=cross())).status == 403, path
            assert (
                await ui.get(
                    path,
                    headers=cross(
                        **{"Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "script"}
                    ),
                )
            ).status == 403, path
        # El documento, pero no como navegación de nivel superior.
        for over in (
            {"Sec-Fetch-Dest": "iframe"},
            {"Sec-Fetch-Dest": "frame"},
            {"Sec-Fetch-Dest": "embed"},
            {"Sec-Fetch-Dest": "object"},
            {"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"},
            {"Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "empty"},
            {"Sec-Fetch-Mode": "nested-navigate"},
            {"Sec-Fetch-Mode": "Navigate"},  # sin normalizar: no se adivina
        ):
            assert (await ui.get("/", headers=cross(**over))).status == 403, over
        missing_mode = {k: v for k, v in cross().items() if k != "Sec-Fetch-Mode"}
        missing_dest = {k: v for k, v in cross().items() if k != "Sec-Fetch-Dest"}
        assert (await ui.get("/", headers=missing_mode)).status == 403
        assert (await ui.get("/", headers=missing_dest)).status == 403
        # Un Origin ajeno en la navegación sigue bloqueado.
        assert (
            await ui.get("/", headers=cross(Origin="https://evil.example"))
        ).status == 403
        # Rutas fuera de la lista no se convierten en 200 ni filtran nada.
        assert (await ui.get("/src/studio/access.py", headers=cross())).status in (
            403,
            404,
        )
        assert backend.requests == []
        # Los rechazos dicen qué se pidió y cómo (sin token) para poder diagnosticar.
        caplog.clear()
        token_headers = cross(**{"Sec-Fetch-Dest": "iframe"})
        with caplog.at_level(logging.WARNING, logger="studio.access"):
            await ui.get("/", headers=token_headers)
        logged = caplog.text
        assert "motivo=fetch-site" in logged and "dest='iframe'" in logged
        assert token_headers["Cf-Access-Jwt-Assertion"].split(".")[1] not in logged

    run_panel(test)


def test_local_admin_entry_keeps_its_behaviour_with_navigation_headers():
    async def test(ui, signer, backend, app):
        local = {"Host": "127.0.0.1:18081"}
        valid = {**local, "Authorization": BasicAuth("admin", TOKEN).encode()}
        typed = {
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        assert (await ui.get("/", headers={**valid, **typed})).status == 200
        assert (await ui.get("/", headers={**local, **typed})).status == 401
        # La excepción remota no existe en la entrada local: entre sitios sigue siendo 403.
        assert (await ui.get("/", headers={**valid, **ACCESS_RETURN})).status == 403
        # Ni el JWT de Access ni cabeceras de proxy abren la entrada local.
        assert (
            await ui.get(
                "/",
                headers={**local, **typed, "Cf-Access-Jwt-Assertion": signer.token()},
            )
        ).status == 404
        assert (
            await ui.get("/", headers={**valid, **typed, "X-Forwarded-For": "1.2.3.4"})
        ).status == 404
        report = await ui.get(
            "/internal/studio/report",
            headers={
                **valid,
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
        )
        assert report.status == 200

    run_panel(test)
