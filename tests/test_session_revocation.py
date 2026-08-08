"""Revocación server-side de sesiones del dashboard (logout).

EncryptedCookieStorage guarda toda la sesión cifrada en la cookie -- no hay
session store del lado del server -- así que sin esto, una copia de la
cookie tomada antes del logout (XSS, log, dispositivo compartido) seguía
autenticando hasta que expirara sola (7 días, el max_age de la cookie). Ver
revoke_session/is_session_revoked/purge_expired_revoked_sessions en db.py y
_session_logged_in/_auth_logout en webapi.py.
"""

import asyncio
import json

import pytest

import db
import webapi
from cogs.general import General


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


class _FakeSession(dict):
    def invalidate(self) -> None:
        self.clear()


class _FakeRequest:
    match_info = {"guild_id": "123"}


def _patch_session(monkeypatch, session: dict) -> None:
    async def fake_get_session(_request):
        return session

    monkeypatch.setattr(webapi, "get_session", fake_get_session)


# ── Capa DB ───────────────────────────────────────────────────────────────


def test_revoke_session_marca_el_sid_como_revocado(temp_db):
    async def run():
        assert await db.is_session_revoked("sid-1") is False
        await db.revoke_session("sid-1")
        return await db.is_session_revoked("sid-1")

    assert asyncio.run(run()) is True


def test_revoke_session_es_idempotente(temp_db):
    async def run():
        await db.revoke_session("sid-1")
        await db.revoke_session("sid-1")  # no debe explotar (INSERT OR IGNORE)
        return await db.is_session_revoked("sid-1")

    assert asyncio.run(run()) is True


def test_purge_expired_revoked_sessions_respeta_el_horizonte_de_7_dias(temp_db):
    async def run():
        conn = await db.get_db()
        await conn.execute(
            "INSERT INTO revoked_sessions (sid, revoked_at) VALUES "
            "('viejo', datetime('now', '-8 days')), "
            "('reciente', datetime('now', '-1 days'))"
        )
        await conn.commit()
        deleted = await db.purge_expired_revoked_sessions()
        return (
            deleted,
            await db.is_session_revoked("viejo"),
            await db.is_session_revoked("reciente"),
        )

    deleted, viejo_revocado, reciente_revocado = asyncio.run(run())
    assert deleted == 1
    assert viejo_revocado is False
    assert reciente_revocado is True


# ── _session_logged_in: el gate que usan guild_api/_api_me/_api_me_guilds ──


def test_session_logged_in_false_sin_user_id():
    assert asyncio.run(webapi._session_logged_in({})) is False


def test_session_logged_in_true_sin_sid_sesion_previa_al_fix():
    # Cookies mintadas antes de este fix no tienen "sid": no se pueden
    # revocar individualmente, pero siguen autenticando como antes.
    assert asyncio.run(webapi._session_logged_in({"user_id": "42"})) is True


def test_session_logged_in_false_tras_revocar_el_sid(temp_db):
    async def run():
        await db.revoke_session("sid-42")
        return await webapi._session_logged_in({"user_id": "42", "sid": "sid-42"})

    assert asyncio.run(run()) is False


# ── guild_api end-to-end: logout en otra pestaña corta la sesión vieja ────


def test_guild_api_rechaza_una_sesion_cuyo_sid_fue_revocado(monkeypatch, temp_db):
    @webapi.guild_api
    async def handler(request, guild_id):
        return webapi.web.json_response({"ok": True})

    session = _FakeSession(user_id="42", access_token="tok", sid="sid-42")
    _patch_session(monkeypatch, session)

    async def fake_check_guild_access(_request, _guild_id):
        return None  # simula "el usuario administra ese guild"

    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda _request, _guild_id: object())

    async def run():
        antes = await handler(_FakeRequest())
        await db.revoke_session("sid-42")
        despues = await handler(_FakeRequest())
        return antes, despues

    antes, despues = asyncio.run(run())
    assert antes.status == 200
    assert despues.status == 401


def test_api_me_deja_de_reportar_logueado_tras_revocar_el_sid(monkeypatch, temp_db):
    session = _FakeSession(user_id="42", username="Frambuesa", sid="sid-77")
    _patch_session(monkeypatch, session)

    async def run():
        antes = await webapi._api_me(_FakeRequest())
        await db.revoke_session("sid-77")
        despues = await webapi._api_me(_FakeRequest())
        return antes, despues

    antes, despues = asyncio.run(run())
    assert json.loads(antes.body)["logged_in"] is True
    assert json.loads(despues.body)["logged_in"] is False


def test_auth_logout_revoca_el_sid_de_la_sesion(monkeypatch, temp_db):
    session = _FakeSession(user_id="42", sid="sid-99")
    _patch_session(monkeypatch, session)

    async def run():
        assert await db.is_session_revoked("sid-99") is False
        with pytest.raises(webapi.web.HTTPFound):
            await webapi._auth_logout(_FakeRequest())
        return await db.is_session_revoked("sid-99")

    assert asyncio.run(run()) is True


def test_auth_logout_no_invalida_la_cookie_si_la_revocacion_falla(monkeypatch):
    """Orden a propósito en _auth_logout: revoke_session() ANTES de
    session.invalidate(). Si el insert falla (DB caída, lock), la excepción
    corta la función antes de invalidar -- el navegador se queda con la
    cookie vieja intacta en vez de "verse deslogueado" mientras el sid sigue
    sin revocar server-side (el peor de los dos fallos posibles)."""
    session = _FakeSession(user_id="42", sid="sid-boom")

    async def fake_get_session(_request):
        return session

    async def boom(_sid):
        raise RuntimeError("db caída")

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "revoke_session", boom)

    async def run():
        with pytest.raises(RuntimeError):
            await webapi._auth_logout(_FakeRequest())

    asyncio.run(run())
    # session.invalidate() nunca se ejecutó: la sesión sigue teniendo sus
    # datos (en la práctica esto se traduce en "no se manda Set-Cookie",
    # ver aiohttp_session.session_middleware -- una excepción no
    # HTTPException no llega a storage.save_session).
    assert session.get("user_id") == "42"


# ── guild_cleanup_task: la purga diaria realmente invoca la función ───────


def test_guild_cleanup_task_purga_revoked_sessions_de_verdad(temp_db):
    """No alcanza con que purge_expired_revoked_sessions() exista y esté
    importada -- confirma que el loop diario de limpieza (cogs/general.py)
    la invoca de verdad, corriendo el cuerpo real del @tasks.loop.

    Cuenta filas en vez de usar is_session_revoked: ese helper no distingue
    "nunca revocado" de "revocado y ya purgado" (ambos dan False), lo que
    importa acá es que la fila haya desaparecido de la tabla.
    """

    async def run():
        conn = await db.get_db()
        await conn.execute(
            "INSERT INTO revoked_sessions (sid, revoked_at) VALUES "
            "('viejo', datetime('now', '-8 days'))"
        )
        await conn.commit()

        cog = General(bot=None)
        await cog.guild_cleanup_task.coro(cog)

        async with conn.execute("SELECT COUNT(*) FROM revoked_sessions") as cur:
            row = await cur.fetchone()
            return row[0]

    assert asyncio.run(run()) == 0


# ── _api_me_guilds: el otro punto de entrada gateado a mano ───────────────


def test_api_me_guilds_rechaza_una_sesion_cuyo_sid_fue_revocado(monkeypatch, temp_db):
    session = _FakeSession(user_id="42", access_token="tok", sid="sid-88")
    _patch_session(monkeypatch, session)

    async def fake_fetch_manage_guilds(_request, force=False):
        return []  # simula "Discord contestó, no administra ningún guild"

    monkeypatch.setattr(webapi, "_fetch_manage_guilds", fake_fetch_manage_guilds)

    class _FakeMeGuildsBot:
        guilds: list = []

    class _Req:
        query: dict = {}
        app = {"bot": _FakeMeGuildsBot()}

    async def run():
        antes = await webapi._api_me_guilds(_Req())
        await db.revoke_session("sid-88")
        despues = await webapi._api_me_guilds(_Req())
        return antes, despues

    antes, despues = asyncio.run(run())
    assert antes.status == 200
    assert despues.status == 401


# ── Cobertura del router: ningún handler {guild_id} se queda sin el gate ──

# _api_status_guild es la única ruta con {guild_id} deliberadamente pública
# (info de servidor visible desde afuera para el buscador de /es/estado, sin
# login -- ver su docstring en webapi.py). Cualquier otra ruta con
# {guild_id} que no pase por @guild_api es un endpoint que puede mutar o
# leer datos de un guild sin validar que quien pregunta lo administre.
_GUILD_ID_ROUTES_SIN_GUILD_API = {"/api/status/guild/{guild_id}"}


class _FakeBot:
    guilds: list = []

    def get_guild(self, guild_id):
        return None


def test_todas_las_rutas_con_guild_id_pasan_por_guild_api():
    """guild_api es lo único que valida que el usuario administre justo ESE
    guild_id (no solo que esté logueado) -- ver check_guild_access. Este
    test corre el router real (no una copia de la lista de rutas) para que
    agregar una ruta nueva sin el decorador la haga fallar."""
    original_enabled = webapi.DASHBOARD_ENABLED
    original_runner = webapi._runner
    webapi.DASHBOARD_ENABLED = True
    webapi._runner = None

    async def run():
        await webapi.start_web_server(_FakeBot())
        try:
            sin_gate = []
            for route in webapi._runner.app.router.routes():
                if route.resource is None:
                    continue
                path = route.resource.canonical
                if (
                    "{guild_id}" in path
                    and path not in _GUILD_ID_ROUTES_SIN_GUILD_API
                    and route.handler.__name__ != "wrapper"
                ):
                    sin_gate.append((path, route.method))
            return sin_gate
        finally:
            await webapi.stop_web_server()

    try:
        sin_gate = asyncio.run(run())
    finally:
        webapi.DASHBOARD_ENABLED = original_enabled
        webapi._runner = original_runner

    assert not sin_gate, f"rutas con {{guild_id}} sin @guild_api: {sin_gate}"


# ── /auth/logout no responde a GET (logout CSRF) ────────────────────────────

# SameSite=Lax deja pasar la cookie de sesión en una navegación GET
# top-level (un <a href> normal, `window.location=`, un meta-refresh) sin
# importar el origen que la dispara. Si /auth/logout respondiera a GET, una
# página de un atacante podía forzar el logout de una víctima logueada con
# solo redirigirla ahí -- sin click, sin confirmación. POST no tiene ese
# problema: SameSite=Lax lo bloquea en requests cross-site.


def test_auth_logout_no_registra_metodo_get():
    original_enabled = webapi.DASHBOARD_ENABLED
    original_runner = webapi._runner
    webapi.DASHBOARD_ENABLED = True
    webapi._runner = None

    async def run():
        await webapi.start_web_server(_FakeBot())
        try:
            methods = {
                route.method
                for route in webapi._runner.app.router.routes()
                if route.resource is not None
                and route.resource.canonical == "/auth/logout"
            }
            return methods
        finally:
            await webapi.stop_web_server()

    try:
        methods = asyncio.run(run())
    finally:
        webapi.DASHBOARD_ENABLED = original_enabled
        webapi._runner = original_runner

    assert "GET" not in methods, (
        "/auth/logout responde a GET: logout CSRF vía navegación"
    )
    assert "POST" in methods
