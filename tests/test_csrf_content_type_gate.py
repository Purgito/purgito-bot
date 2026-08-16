"""Auditoría sección 9, ronda 3, punto 1: CSRF en los endpoints de mutación.

El dashboard se autentica con una cookie de sesión (SameSite=Lax, Secure,
HttpOnly). Esa es la defensa primaria contra CSRF, y funciona para la enorme
mayoría de navegadores modernos: bloquea la cookie en un POST/PUT/DELETE
cross-site (solo deja pasar navegación top-level GET, y acá no hay ningún
endpoint de mutación registrado como GET -- se confirma con
test_no_hay_mutaciones_registradas_como_get). Pero no es la única pieza:

`_json_body` llamaba a `request.json()` sin mirar el Content-Type. Eso deja
una segunda vía independiente de SameSite: el Fetch/CORS spec permite mandar
un request "simple" (sin preflight) con Content-Type
application/x-www-form-urlencoded, multipart/form-data o text/plain -- los
tres únicos que un <form> nativo de HTML puede emitir. Como json.loads no
mira el Content-Type, un <form enctype="text/plain"> con un único input
cuyo name+value arman un body JSON válido llegaba servido tal cual a
`_json_body`, esquivando el preflight de CORS por completo. De ahí en más
la única defensa quedaba en SameSite=Lax -- que no cubre TODOS los clientes
(navegadores que ignoran el atributo, o la ventana de gracia que algunos dan
a una cookie Lax recién seteada en un POST de navegación top-level).

The fix (`_is_simple_request_content_type`) rechaza esos tres Content-Type
en `_json_body`.
"""

import inspect

import pytest

import webapi


class _Headers(dict):
    def get(self, key, default=""):
        return super().get(key, default)


class FakeRequest:
    def __init__(self, body, content_type="application/json", headers=True):
        self._body = body
        self.headers = _Headers({"Content-Type": content_type}) if headers else None

    async def json(self):
        return self._body


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "text/plain;charset=UTF-8",
        "multipart/form-data; boundary=----abc",
        "application/x-www-form-urlencoded",
        "APPLICATION/X-WWW-FORM-URLENCODED",  # case-insensitive
    ],
)
def test_content_type_safelisted_de_cors_se_rechaza(content_type):
    """Estos tres son justo los únicos que un <form> nativo puede mandar sin
    disparar preflight -- por eso importa rechazarlos server-side y no confiar
    solo en que el navegador haga el preflight bien."""
    import asyncio

    request = FakeRequest({"pattern": "x"}, content_type=content_type)
    assert asyncio.run(webapi._json_body(request)) is None


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/json; charset=utf-8", ""],
)
def test_content_type_no_safelisted_pasa(content_type):
    import asyncio

    request = FakeRequest({"pattern": "x"}, content_type=content_type)
    assert asyncio.run(webapi._json_body(request)) == {"pattern": "x"}


def test_json_polyglot_via_form_text_plain_no_llega_a_parsearse():
    """El body ES JSON válido (lo produciría un <form enctype="text/plain">
    con un único input bien armado) pero el Content-Type ya lo frena antes de
    intentar json.loads."""
    import asyncio

    class _RawRequest:
        headers = _Headers({"Content-Type": "text/plain"})

        async def json(self):
            raise AssertionError("no debería llegar a parsearse")

    assert asyncio.run(webapi._json_body(_RawRequest())) is None


def test_sin_headers_no_rompe():
    """Los FakeRequest de otros archivos de test no todos definen .headers;
    con getattr por defecto, la ausencia se trata como 'no safelisted' (deja
    pasar), no como un AttributeError."""
    import asyncio

    request = FakeRequest({"pattern": "x"}, headers=False)
    request.headers = None
    assert asyncio.run(webapi._json_body(request)) == {"pattern": "x"}


# ── No hay mutación disparable con una navegación GET top-level ─────────────


def test_no_hay_mutaciones_registradas_como_get():
    """SameSite=Lax deja pasar la cookie en un GET de navegación top-level
    (un link, window.location=). Si algún endpoint mutara datos por GET,
    SameSite no protegería nada -- confirmamos que no existe ninguno."""
    src = inspect.getsource(webapi)
    lineas = [ln for ln in src.splitlines() if "app.router.add_get(" in ln]
    assert lineas, "se esperaban rutas GET registradas"
    # Los nombres de handler de las rutas GET todos empiezan con un patrón de
    # lectura (_api_*_get, _api_me, _api_status, /health, /auth/*) -- ninguno
    # con sufijo _post/_put/_delete/_patch, que delataría una mutación por GET.
    for ln in lineas:
        assert not any(suf in ln for suf in ("_post", "_put)", "_delete", "_patch")), ln
