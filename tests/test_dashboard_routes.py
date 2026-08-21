"""Tests del dashboard: rutas de la API, contadores de uso y páginas estáticas.

Las tres piezas que se rompen en silencio si alguien toca una sola de ellas:
el JS pide una URL que la app no registra, el HTML se olvida de un hueco que
el JS busca, o el build de landing/ queda desactualizado en el repo.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

import db
import webapi

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
DOCS = ROOT / "docs"


# ── La API registra exactamente lo que el frontend pide ──────────────────────


def _registered_paths() -> set[str]:
    """Rutas que start_web_server monta de verdad, leídas del router ya armado.

    Se levanta la app real en vez de duplicar acá la lista de rutas — una copia
    se desincronizaría al primer cambio, que es justo lo que estos tests
    tendrían que detectar. DASHBOARD_ENABLED se fuerza porque en CI no hay
    credenciales de Discord y el bloque entero quedaría sin montar.
    """
    original = webapi.DASHBOARD_ENABLED
    webapi.DASHBOARD_ENABLED = True
    webapi._runner = None
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(webapi.start_web_server(_FakeBot()))
        paths = {
            r.resource.canonical
            for r in webapi._runner.app.router.routes()
            if r.resource is not None
        }
        loop.run_until_complete(webapi.stop_web_server())
    finally:
        loop.close()
        webapi.DASHBOARD_ENABLED = original
    return paths


class _FakeBot:
    guilds: list = []

    def get_guild(self, guild_id):
        return None


def _frontend_api_paths() -> set[str]:
    """URLs que arman los módulos de landing/js/, normalizadas a la forma del
    router (`${GUILD_ID}` → `{guild_id}`, `${x}` → `{x}`)."""
    found = set()
    for js in (LANDING / "js").rglob("*.js"):
        for raw in re.findall(r"`(/api/[^`]+)`|'(/api/[^']+)'", js.read_text("utf-8")):
            url = raw[0] or raw[1]
            url = url.replace("${GUILD_ID}", "{guild_id}")
            url = re.sub(r"\$\{[^}]+\}", "{x}", url)
            found.add(url)
    return found


def test_frontend_no_pide_rutas_que_la_api_no_registra():
    registered = _registered_paths()
    # El router usa nombres propios para cada parámetro; para comparar alcanza
    # con la forma "hay un segmento variable acá".
    shapes = {re.sub(r"\{[^}]+\}", "{x}", p) for p in registered}
    missing = {
        u for u in _frontend_api_paths() if re.sub(r"\{[^}]+\}", "{x}", u) not in shapes
    }
    assert not missing, f"el JS llama a rutas inexistentes: {sorted(missing)}"


def test_rutas_clave_del_dashboard_estan_montadas():
    registered = _registered_paths()
    for path in (
        "/api/me",
        "/api/me/guilds",
        "/api/me/billing",
        "/api/me/billing/portal",
        "/api/server/{guild_id}/stats",
        "/api/server/{guild_id}/style",
        "/api/server/{guild_id}/settings/spontaneous-channels",
        "/api/server/{guild_id}/settings/mention-channels",
        "/api/server/{guild_id}/embeds/templates",
        # Zona protegida: sigue viva junto a las rutas nuevas.
        "/webhooks/polar",
        "/health",
        "/api/server/{guild_id}/premium/checkout",
    ):
        assert path in registered, f"falta {path}"


# ── /api/me expone el snowflake que el perfil necesita ───────────────────────


def test_api_me_incluye_user_id():
    """La cabecera de /es/perfil saca "En Discord desde …" del snowflake."""

    class FakeSession(dict):
        pass

    session = FakeSession(
        user_id="1471724794411089920", username="Frambuesa", email="a@b.c"
    )

    async def fake_get_session(_request):
        return session

    original = webapi.get_session
    webapi.get_session = fake_get_session
    try:
        resp = asyncio.run(webapi._api_me(None))
    finally:
        webapi.get_session = original

    body = json.loads(resp.body)
    assert body["logged_in"] is True
    assert body["user_id"] == "1471724794411089920"
    assert resp.headers["Cache-Control"] == "no-store"


# ── "Recargar" de /es/perfil ─────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class _FakeHttp:
    """Cuenta los GET a Discord para distinguir cache-hit de refetch."""

    def __init__(self, status=200, payload=None):
        self.calls = 0
        self.status = status
        self.payload = payload if payload is not None else []

    def get(self, url, headers=None):
        self.calls += 1
        return _FakeResponse(self.status, self.payload)


def _request_with(http, session):
    async def fake_get_session(_request):
        return session

    webapi.get_session = fake_get_session

    class Req:
        app = {"http": http}
        query: dict = {}

    return Req()


def _guilds_env(monkeypatch, http):
    """Sesión válida + cache limpio, con get_session parcheado."""
    monkeypatch.setattr(webapi, "_user_guilds_cache", webapi.LRUDict(8))
    monkeypatch.setattr(webapi, "get_session", webapi.get_session, raising=False)
    session = {"user_id": "42", "access_token": "tok"}
    return _request_with(http, session)


def test_recargar_saltea_el_cache_de_guilds(monkeypatch):
    """Sin force, el segundo pedido sale del cache; con force vuelve a Discord."""
    original = webapi.get_session
    http = _FakeHttp(payload=[{"id": "1", "name": "S", "owner": True}])
    req = _guilds_env(monkeypatch, http)
    try:
        asyncio.run(webapi._fetch_manage_guilds(req))
        assert http.calls == 1
        asyncio.run(webapi._fetch_manage_guilds(req))  # cache hit
        assert http.calls == 1, "el cache de guilds dejó de funcionar"
        asyncio.run(webapi._fetch_manage_guilds(req, force=True))
        assert http.calls == 2, "?refresh=1 no volvió a preguntarle a Discord"
    finally:
        webapi.get_session = original


def test_recargar_con_429_devuelve_la_lista_vieja_en_vez_de_deslogear(monkeypatch):
    """Dos clicks seguidos chocan con el ~1 req/s de Discord; no puede leerse
    como sesión expirada."""
    original = webapi.get_session
    http = _FakeHttp(payload=[{"id": "1", "name": "S", "owner": True}])
    req = _guilds_env(monkeypatch, http)
    try:
        primera = asyncio.run(webapi._fetch_manage_guilds(req))
        http.status = 429
        segunda = asyncio.run(webapi._fetch_manage_guilds(req, force=True))
        assert segunda is not None, "un 429 en el refresh desloguearía al usuario"
        assert segunda == primera
    finally:
        webapi.get_session = original


def test_el_boton_dice_recargar_y_no_reportar():
    perfil = (LANDING / "js" / "perfil.js").read_text("utf-8")
    assert "'Recargar'" in perfil
    assert "Reportar" not in perfil
    # Y recarga de verdad: pide la lista salteando el cache.
    assert "?refresh=1" in perfil


# ── Contadores de uso (los "logs" de la tab INICIO) ──────────────────────────


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def test_bump_counter_acumula_por_guild_y_metrica(temp_db):
    async def run():
        await db.bump_counter(1, "gifs_enviados")
        await db.bump_counter(1, "gifs_enviados")
        await db.bump_counter(1, "mensajes_enviados")
        await db.bump_counter(2, "gifs_enviados")
        return await db.get_counters(1), await db.get_counters(2)

    uno, dos = asyncio.run(run())
    assert uno == {"gifs_enviados": 2, "mensajes_enviados": 1}
    assert dos == {"gifs_enviados": 1}


def test_bump_counter_nunca_explota_sin_db(monkeypatch):
    """Es telemetría: no puede voltear el envío que la dispara."""
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.bump_counter(1, "gifs_enviados"))  # no lanza


def test_purge_guild_data_borra_los_contadores(temp_db):
    async def run():
        await db.bump_counter(7, "gifs_enviados")
        await db.purge_guild_data(7)
        return await db.get_counters(7)

    assert asyncio.run(run()) == {}


# ── Páginas generadas ────────────────────────────────────────────────────────


def test_paginas_del_dashboard_existen_con_sus_huecos():
    perfil = (LANDING / "es" / "perfil" / "index.html").read_text("utf-8")
    dash = (LANDING / "es" / "dashboard" / "index.html").read_text("utf-8")

    for page in (perfil, dash):
        # El navbar y estilos compartidos
        assert 'class="nav" id="top"' in page
        assert 'id="toast"' in page
        assert '<link rel="stylesheet" href="/dash.css?v=' in page

    # El footer está presente en perfil pero se omite en el dashboard de servidor
    assert 'class="footer"' in perfil
    assert 'class="footer"' not in dash

    assert 'id="contenido"' in perfil
    assert "/js/perfil.js?v=" in perfil
    for hole in ('id="dashHead"', 'id="dashTabs"', 'id="catContent"'):
        assert hole in dash, hole
    assert "/js/dash.js?v=" in dash

    # Las cuatro tabs de cuenta/perfil son páginas reales, no anclas.
    for slug in ("servidores", "conexiones", "facturacion"):
        assert (LANDING / "es" / "perfil" / slug / "index.html").exists()


def test_importmap_cubre_todos_los_modulos():
    """Sin esto Cloudflare sirve módulos internos viejos tras un deploy."""
    dash = (LANDING / "es" / "dashboard" / "index.html").read_text("utf-8")
    mapped = set(re.findall(r'"(/js/[^"]+\.js)":', dash))
    on_disk = {
        "/" + p.relative_to(LANDING).as_posix() for p in (LANDING / "js").rglob("*.js")
    }
    assert mapped == on_disk, f"import map desincronizado: {mapped ^ on_disk}"


def test_el_navbar_no_tiene_ningun_dashboard_suelto():
    """El bloque de usuario es un trigger de menú y no un link suelto a dashboard."""
    script = (LANDING / "script.js").read_text("utf-8")
    index = (LANDING / "index.html").read_text("utf-8")
    # Ni ítem en el dropdown…
    assert "label: 'Dashboard'" not in script
    # …ni botón suelto en el nav.
    assert not re.search(r'class="nav-link[^"]*"[^>]*>\s*Dashboard', index)
    # El bloque de usuario es un botón con aria-haspopup/aria-expanded que abre el menú
    assert "btn.className = 'auth-btn'" in script
    assert "btn.setAttribute('aria-haspopup', 'true')" in script
    assert "'/' + LOC + '/perfil'" in script


# ── Frescura de datos en Header y Dashboard ──────────────────────────────────


class _FakeAsset:
    def __init__(self, url):
        self.url = url

    def with_size(self, size):
        return _FakeAsset(f"{self.url.split('?')[0]}?size={size}")


class _FakeGuild:
    def __init__(self, id, name, icon_url=None, member_count=10):
        self.id = id
        self.name = name
        self.icon = _FakeAsset(icon_url) if icon_url else None
        self.member_count = member_count


def test_api_me_guilds_prioritizes_gateway_bot_guild_data(temp_db, monkeypatch):
    """Para guilds configurados, el nombre e icono salen en vivo del Gateway."""
    original = webapi.get_session
    live_guild = _FakeGuild(
        id=123,
        name="Live Gateway Server",
        icon_url="https://cdn.discordapp.com/icons/123/live_icon.png",
        member_count=77,
    )
    fake_bot = _FakeBot()
    fake_bot.guilds = [live_guild]
    fake_bot.get_guild = lambda gid: live_guild if gid == 123 else None

    http = _FakeHttp(
        payload=[
            {
                "id": "123",
                "name": "Stale OAuth Server",
                "icon": "stale_oauth_icon",
                "owner": True,
            }
        ]
    )
    req = _guilds_env(monkeypatch, http)
    req.app["bot"] = fake_bot

    try:
        resp = asyncio.run(webapi._api_me_guilds(req))
        data = json.loads(resp.body)
        assert len(data["configured"]) == 1
        conf = data["configured"][0]
        # Prioriza los datos en vivo del Gateway sobre los cacheados de OAuth
        assert conf["name"] == "Live Gateway Server"
        assert (
            conf["icon_url"]
            == "https://cdn.discordapp.com/icons/123/live_icon.png?size=128"
        )
        assert conf["member_count"] == 77
    finally:
        webapi.get_session = original


def test_api_me_guilds_falls_back_to_oauth_when_bot_guild_is_none_or_missing_icon(
    temp_db, monkeypatch
):
    """Guard de caso límite: si bot_guild es None o no tiene icono, usa el fallback de OAuth."""
    original = webapi.get_session

    # Caso 1: bot_guild es None (ej. gap de reconexión/sincronización)
    fake_bot_none = _FakeBot()
    fake_bot_none.guilds = [_FakeGuild(id=123, name="")]  # id presente en bot_guild_ids
    fake_bot_none.get_guild = lambda gid: None  # pero get_guild retorna None

    http = _FakeHttp(
        payload=[
            {
                "id": "123",
                "name": "Fallback OAuth Name",
                "icon": "fallback_oauth_icon",
                "owner": True,
            }
        ]
    )
    req = _guilds_env(monkeypatch, http)
    req.app["bot"] = fake_bot_none

    try:
        resp = asyncio.run(webapi._api_me_guilds(req))
        data = json.loads(resp.body)
        conf = data["configured"][0]
        assert conf["name"] == "Fallback OAuth Name"
        assert (
            conf["icon_url"]
            == "https://cdn.discordapp.com/icons/123/fallback_oauth_icon.png?size=128"
        )

        # Caso 2: bot_guild existe pero sin icono en Discord (icon=None), OAuth sí tiene
        live_no_icon = _FakeGuild(id=123, name="Live Name", icon_url=None)
        fake_bot_no_icon = _FakeBot()
        fake_bot_no_icon.guilds = [live_no_icon]
        fake_bot_no_icon.get_guild = lambda gid: live_no_icon if gid == 123 else None

        req.app["bot"] = fake_bot_no_icon
        resp2 = asyncio.run(webapi._api_me_guilds(req))
        data2 = json.loads(resp2.body)
        conf2 = data2["configured"][0]
        assert conf2["name"] == "Live Name"
        assert (
            conf2["icon_url"]
            == "https://cdn.discordapp.com/icons/123/fallback_oauth_icon.png?size=128"
        )

        # Caso 3: sin icono en ninguno
        http_no_icon = _FakeHttp(
            payload=[{"id": "123", "name": "Live Name", "icon": None, "owner": True}]
        )
        monkeypatch.setattr(webapi, "_user_guilds_cache", webapi.LRUDict(8))
        req_no_icon = _guilds_env(monkeypatch, http_no_icon)
        req_no_icon.app["bot"] = fake_bot_no_icon
        resp3 = asyncio.run(webapi._api_me_guilds(req_no_icon))
        data3 = json.loads(resp3.body)
        conf3 = data3["configured"][0]
        assert conf3["icon_url"] is None
    finally:
        webapi.get_session = original


def test_get_channels_force_refetch_contract():
    """panel-shell.js acepta force y dash.js lo usa al activar INICIO y CHAT."""
    panel_shell = (LANDING / "js" / "panel-shell.js").read_text("utf-8")
    dash = (LANDING / "js" / "dash.js").read_text("utf-8")

    assert "export async function getChannels(opts = {})" in panel_shell
    assert "force" in panel_shell

    # loadInicio y loadChatTab deben pedir canales con force
    assert "getChannels({ force: true })" in dash


def test_dash_refreshes_load_head_on_inicio_navigation():
    """Al volver a INICIO desde otra pestaña, activate() dispara loadHead()."""
    dash = (LANDING / "js" / "dash.js").read_text("utf-8")
    assert "if (key === 'inicio')" in dash
    assert "loadHead();" in dash


def test_insert_popover_se_reposiciona_con_cambios_de_viewport():
    """El popover fixed del editor no puede conservar coordenadas viejas al
    aparecer el teclado o cambiar la orientación en Safari móvil."""
    shared_ui = (LANDING / "js" / "embeds" / "shared-ui.js").read_text("utf-8")

    assert "window.visualViewport" in shared_ui
    assert (
        "window.addEventListener('resize', _scheduleInsertPopoverPosition)" in shared_ui
    )
    assert (
        "window.addEventListener('orientationchange', _scheduleInsertPopoverPosition)"
        in shared_ui
    )
    assert "requestAnimationFrame(_positionInsertPopover)" in shared_ui
    assert "window.visualViewport?.removeEventListener('resize'" in shared_ui


def test_dashboard_y_premium_tienen_fallbacks_de_viewport_y_blur():
    dash_css = (LANDING / "dash.css").read_text("utf-8")
    style_css = (LANDING / "style.css").read_text("utf-8")

    assert "max-height: 85vh;" in dash_css
    assert "max-height: 85dvh;" in dash_css
    assert "height: calc(100dvh - 230px);" in dash_css
    assert ".prem-mascot-card" in style_css
    assert ".prem-mascot-img" in style_css


def test_pagina_premium_redisenada_tiene_elementos_y_limites_reales():
    """Verifica que /es/premium/ contiene la estructura rediseñada y límites de limits.env."""
    prem_page = (LANDING / "es" / "premium" / "index.html").read_text("utf-8")

    # Secciones clave del rediseño
    assert 'class="prem-hero"' in prem_page
    assert 'class="prem-features-grid"' in prem_page
    assert 'class="box prem-stat-matrix"' in prem_page
    assert 'class="prem-plans-grid"' in prem_page
    assert 'class="box donate"' in prem_page

    # Elementos interactivos que script.js escucha
    assert 'id="plan-toggle"' in prem_page
    assert 'id="plan-amount"' in prem_page
    assert 'id="plan-per"' in prem_page
    assert 'id="plan-trial"' in prem_page

    # Límites reales de limits.env presentes en la comparativa
    for limit in ("50.000", "500.000", "4.000", "200", "50", "10"):
        assert limit in prem_page, f"Falta el límite {limit} en la página premium"

    # Enlaces legales y de contacto
    assert 'href="/es/terminos"' in prem_page
    assert 'href="/es/reembolsos"' in prem_page
    assert 'href="/es/privacidad"' in prem_page
    assert "billing@purgito.app" in prem_page

    # Sin logos comerciales de métodos de pago en la zona de planes
    assert "visa.svg" not in prem_page
    assert "mastercard.svg" not in prem_page


def test_navbar_dropdowns_and_mobile_menu_structure_and_behavior():
    """Verifica que la navbar cuenta con dropdowns accesibles, enlaces reales y menú móvil."""
    index = (LANDING / "index.html").read_text("utf-8")
    script = (LANDING / "script.js").read_text("utf-8")
    style = (LANDING / "style.css").read_text("utf-8")

    # Contenedores de dropdowns desktop
    assert "data-nav-dropdown" in index
    assert 'id="nav-btn-recursos"' in index
    assert 'id="nav-btn-comunidad"' in index
    assert 'aria-haspopup="true"' in index
    assert 'aria-expanded="false"' in index

    # Enlaces reales en dropdowns
    assert 'href="/es/documentacion"' in index
    assert 'href="/es/estado"' in index
    assert 'href="/es/premium"' in index
    assert 'href="https://discord.gg/5U7HKyxnBv"' in index
    assert 'href="https://top.gg/bot/1471724794411089920"' in index
    assert 'href="https://github.com/punkyyy01/bot-discord-purg"' in index

    # Toggle y Drawer móvil
    assert 'id="nav-mobile-toggle"' in index
    assert 'id="nav-mobile-panel"' in index
    assert 'class="nav-mobile-accordion-btn"' in index

    # Lógica en script.js
    assert "openDropdown" in script
    assert "closeDropdown" in script
    assert "scheduleClose" in script
    assert "setMobileOpen" in script
    assert "ArrowDown" in script
    assert "Escape" in script
    assert "is-scrolled" in script
    assert "updateNavScroll" in script

    # Estilos en style.css
    assert ".nav-dropdown" in style
    assert ".nav-drop-item" in style
    assert ".nav-mobile-panel" in style
    assert ".nav-mobile-toggle" in style
    assert ".nav.is-scrolled" in style

    # El logo es completamente estático (sin rotación ni transformación hover)
    assert ".nav-brand:hover" not in style


def test_documentacion_inicio_redisenada_con_recursos_rapidos_y_categorias():
    """Verifica que el Inicio de /es/documentacion incluye encabezado compacto, recursos rápidos y categorías."""
    docs_home = (LANDING / "es" / "documentacion" / "index.html").read_text("utf-8")

    # Encabezado y recursos rápidos
    assert 'class="docs-home-head"' in docs_home
    assert 'class="docs-home-lead"' in docs_home
    assert 'class="docs-quick-links"' in docs_home
    assert "dash-link" in docs_home
    assert "https://discord.gg/5U7HKyxnBv" in docs_home
    assert "client_id=1471724794411089920" in docs_home

    # Separación y sección de exploración
    assert 'class="docs-divider"' in docs_home
    assert 'class="docs-section-heading"' in docs_home
    assert "Explora la documentación" in docs_home

    # Categorías de documentación técnica
    for cat in (
        "arquitectura",
        "discord",
        "api",
        "generacion",
        "almacenamiento",
        "seguridad",
        "infraestructura",
        "desarrollo",
        "referencia",
    ):
        assert f'href="/es/documentacion/{cat}"' in docs_home


def test_popover_positioning_and_viewport_resilience():
    """Verifica que los popovers del editor y el layout del dashboard gestionan viewport y limpieza."""
    shared_ui = (LANDING / "js" / "embeds" / "shared-ui.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")
    style_css = (LANDING / "style.css").read_text("utf-8")

    # shared-ui.js maneja visualViewport, pointerdown, resize, orientación y limpieza
    assert "window.visualViewport?.addEventListener('resize'" in shared_ui
    assert "window.visualViewport?.removeEventListener('resize'" in shared_ui
    assert "pointerdown" in shared_ui
    assert "orientationchange" in shared_ui
    assert "fitsBelow" in shared_ui
    assert "closeInsertPopover" in shared_ui

    # dash.css tiene restricciones de viewport dvh/vh para popovers y modales
    assert "max-height: calc(100dvh - 16px);" in dash_css
    assert "max-height: 85dvh;" in dash_css

    # style.css aísla la capa del dropdown y soporta dvh en el menú móvil
    assert ".nav-mobile-panel" in style_css
    assert "height: calc(100dvh - var(--nav-h));" in style_css
    assert ".nav-sep" in style_css


def test_dashboard_en_navbar_y_menu_de_usuario_para_autenticados():
    """Verifica que Dashboard aparece en navbar desktop y drawer móvil para autenticados apuntando a /perfil/servidores, y Perfil en el menú de usuario."""
    script = (LANDING / "script.js").read_text("utf-8")

    # Ícono y opción 'Perfil' en el menú de usuario apuntando a /perfil
    assert "user:" in script
    assert "label: 'Perfil'" in script
    assert "icon: ICONS.user" in script
    assert "'/' + LOC + '/perfil'" in script

    # Regex de estado activo del Dashboard en la navbar: solo activo en /perfil/servidores y /dashboard
    pattern = (
        re.search(r"isDashboardActive = (/.*?/)\.test", script).group(1).strip("/")
    )
    active_re = re.compile(pattern)
    assert active_re.search("/es/perfil/servidores")
    assert active_re.search("/es/perfil/servidores/")
    assert active_re.search("/es/dashboard")
    assert active_re.search("/es/dashboard/12345")
    assert not active_re.search("/es/perfil")
    assert not active_re.search("/es/perfil/")
    assert not active_re.search("/es/perfil/conexiones")
    assert not active_re.search("/es/perfil/facturacion")
    assert not active_re.search("/es/premium")


def test_estructura_de_cuatro_tabs_en_perfil():
    """Verifica que perfil.js define y renderiza las 4 pestañas en orden:
    Servidores, Conexiones, Facturación y Perfil (Perfil siempre al final),
    y que la metadata del header solo se incluye en la pestaña Perfil."""
    perfil_js = (LANDING / "js" / "perfil.js").read_text("utf-8")
    assert "{ key: 'perfil', label: 'Perfil', path: '' }" in perfil_js
    assert (
        "{ key: 'servidores', label: 'Servidores', path: '/servidores' }" in perfil_js
    )
    assert (
        "{ key: 'conexiones', label: 'Conexiones', path: '/conexiones' }" in perfil_js
    )
    assert (
        "{ key: 'facturacion', label: 'Facturación', path: '/facturacion' }"
        in perfil_js
    )
    # Orden exacto: Servidores, Conexiones, Facturación, Perfil
    idx_serv = perfil_js.index("'servidores'")
    idx_con = perfil_js.index("'conexiones'")
    idx_fact = perfil_js.index("'facturacion'")
    idx_perf = perfil_js.index("'perfil'")
    assert idx_serv < idx_con < idx_fact < idx_perf

    # Cabecera condicional para pestaña perfil
    assert "tab === 'perfil'" in perfil_js

    assert "tabPerfil" in perfil_js
    assert "tabServidores" in perfil_js
    assert "tabConexiones" in perfil_js
    assert "tabFacturacion" in perfil_js


def test_frases_dashboard_ui_busqueda_paginacion_y_edicion():
    """Verifica que dash.js y dash.css implementan búsqueda, paginación y edición inline en Frases."""
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")

    # Búsqueda y filtrado antes de paginar
    assert "frases-search-input" in dash_js
    assert "Buscar una frase…" in dash_js
    assert "frases-empty-search" in dash_js
    assert "Limpiar búsqueda" in dash_js

    # Paginación de 20 por página
    assert "PAGE_SIZE = 20" in dash_js
    assert "frases-pagination" in dash_js
    assert "← Anterior" in dash_js
    assert "Siguiente →" in dash_js

    # Edición inline sin borrar/recrear
    assert "frase-edit-input" in dash_js
    assert "frase-item-editing" in dash_js
    assert "'Guardar'" in dash_js or '"Guardar"' in dash_js
    assert "'Cancelar'" in dash_js or '"Cancelar"' in dash_js
    assert "maxlength: '300'" in dash_js
    assert "Frase actualizada" in dash_js

    # Estilos en dash.css
    assert ".frases-container" in dash_css
    assert ".frases-search-input" in dash_css
    assert ".frase-item" in dash_css
    assert ".frase-item-editing" in dash_css
    assert ".frases-pagination" in dash_css
    assert ".frases-empty-search" in dash_css


def test_dashboard_sidebar_contextual_sticky_navigation():
    """Verifica que el dashboard cuenta con navegación lateral contextual y sticky en desktop y compacta en móvil."""
    dash_html = (LANDING / "es" / "dashboard" / "index.html").read_text("utf-8")
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")

    # Layout HTML
    assert 'class="dash-layout"' in dash_html
    assert 'id="dashTabs" class="dash-sidebar"' in dash_html
    assert 'id="catContent" class="dash-content"' in dash_html

    # JS lógica de renderizado, persistencia del sidebar (rail) y toggle móvil
    assert "renderSidebar" in dash_js
    assert "toggleSidebarCollapse" in dash_js
    assert "SIDEBAR_COLLAPSED_KEY" in dash_js
    assert "dash-sidebar-collapse-btn" in dash_js
    assert "Mostrar navegación" in dash_js
    assert "Ocultar navegación" in dash_js
    assert "dash-sidebar-inner" in dash_js
    assert "dash-mobile-nav-toggle" in dash_js
    assert "dash-mobile-nav-current" in dash_js

    # Iconos coherentes en todas las 8 secciones principales
    dom_js = (LANDING / "js" / "core" / "dom.js").read_text("utf-8")
    for key, icon_name in [
        ("inicio", "home"),
        ("chat", "chat"),
        ("gifs", "film"),
        ("memes", "image"),
        ("embeds", "layout"),
        ("premium", "star"),
        ("youtube", "youtube"),
        ("historial", "history"),
    ]:
        assert f"key: '{key}', label:" in dash_js
        assert f"icon: '{icon_name}'" in dash_js
        assert f"{icon_name}:" in dom_js

    # CSS Sticky, layout fluido progresivo, modo foco / rail colapsable y responsive
    assert ".shell-main:has(.dash-layout)" in dash_css
    assert "min(94vw, 1720px)" in dash_css
    assert "@media (min-width: 1440px)" in dash_css
    assert "@media (min-width: 2560px)" in dash_css
    assert ".dash-layout" in dash_css
    assert ".dash-layout.sidebar-collapsed" in dash_css
    assert ".dash-sidebar" in dash_css
    assert ".dash-sidebar.collapsed" in dash_css
    assert ".dash-sidebar-collapse-btn" in dash_css
    assert ".dash-tab .nav-icon" in dash_css
    assert ".dash-tab.active .nav-icon" in dash_css
    assert "position: sticky" in dash_css
    assert ".dash-subtabs-list" in dash_css
    assert ".dash-subtab" in dash_css
    assert ".dash-subtab-try" in dash_css
    assert ".dash-mobile-nav-toggle" in dash_css
    assert "@media (max-width: 860px)" in dash_css


def test_all_js_modules_import_icon_helper_when_used():
    """Verifica que ningún archivo JS use icon(...) sin importar la función desde dom.js."""
    import re

    js_dir = LANDING / "js"
    for js_file in js_dir.rglob("*.js"):
        if js_file.name == "dom.js":
            continue
        content = js_file.read_text("utf-8")
        if "icon(" in content:
            dom_imports = re.findall(
                r"import\s*\{([^}]+)\}\s*from\s*['\"][^'\"]*dom\.js['\"]", content
            )
            assert dom_imports, f"{js_file} usa icon(...) pero no importa desde dom.js"
            imported_names = [
                name.strip() for names in dom_imports for name in names.split(",")
            ]
            assert "icon" in imported_names, (
                f"{js_file} usa icon(...) pero no importa icon desde dom.js"
            )


def test_guia_purgito_page_structure_and_integration():
    """Verifica que /es/guia está generada, tiene metadata SEO correcta, sidebar dedicado, todas las secciones requeridas y sin placeholders."""
    guia_file = LANDING / "es" / "guia" / "index.html"
    assert guia_file.exists(), "landing/es/guia/index.html debe existir"

    guia_html = guia_file.read_text("utf-8")
    index_html = (LANDING / "index.html").read_text("utf-8")
    script_js = (LANDING / "script.js").read_text("utf-8")
    style_css = (LANDING / "style.css").read_text("utf-8")

    # Metadata & SEO
    assert (
        "<title>Guía de Purgito — Cómo funciona el bot — Purgito</title>" in guia_html
    )
    assert 'content="https://purgito.app/es/guia"' in guia_html
    assert 'property="og:type" content="article"' in guia_html
    assert 'name="description"' in guia_html
    assert "Aprende cómo funciona Purgito" in guia_html

    # Integración en Navbar y Footer
    assert 'href="/es/guia"' in index_html
    assert 'href="/es/guia"' in guia_html
    assert "Guía de Purgito" in index_html
    assert 'class="nav-mobile-link" href="/es/guia"' in index_html

    # Sidebar dedicado con anclas
    assert 'class="docs-sidebar guia-sidebar"' in guia_html
    expected_sections = [
        "introduccion",
        "primeros-pasos",
        "como-aprende",
        "chat",
        "corpus",
        "gifs",
        "memes",
        "reacciones",
        "frases-y-packs",
        "triggers",
        "embeds",
        "youtube",
        "anuncios",
        "premium",
        "dashboard",
        "historial",
    ]
    for sec in expected_sections:
        assert f'href="#{sec}"' in guia_html, f"El sidebar debe enlazar a #{sec}"
        assert f'id="{sec}"' in guia_html, (
            f"La sección id='{sec}' debe existir en el HTML"
        )

    # Enlaces cruzados a documentación técnica, dashboard y soporte real
    assert 'href="/es/documentacion"' in guia_html
    assert 'href="/es/documentacion/generacion"' in guia_html
    assert 'href="/es/documentacion/discord"' in guia_html
    assert 'href="/es/perfil/servidores"' in guia_html
    assert 'href="/es/premium"' in guia_html
    assert "https://discord.gg/5U7HKyxnBv" in guia_html

    # Cero placeholders o enlaces rotos
    assert "PLACEHOLDER" not in guia_html
    assert "discord.gg/PLACEHOLDER" not in (DOCS / "guia" / "index.md").read_text(
        "utf-8"
    )

    # Soporte en CSS y JS
    assert ".guia-sidebar" in style_css
    assert ".guia-content" in style_css
    assert "guiaSidebar" in script_js


def test_chat_reacciones_pool_and_on_demand_modal():
    """Verifica que la sub-pestaña Reacciones use el patrón de pool limpio + selector modal bajo demanda."""
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")

    # 1. Pool visual: chips para custom y unicode, botón + Añadir emoji
    assert "emoji-pool-wrap" in dash_css
    assert "emoji-pool-chip" in dash_css
    assert "emoji-chip-img" in dash_css
    assert "+ Añadir emoji" in dash_js
    assert "parseEmojiText" in dash_js

    # 2. No hay galería permanente de 500 emojis en la página principal
    assert "openAddEmojiModal" in dash_js

    # 3. Modal bajo demanda con pestañas Unicode y Del servidor
    assert "emoji-modal-box" in dash_css
    assert "emoji-modal-tabs" in dash_css
    assert "Del servidor" in dash_js
    assert "Unicode" in dash_js
    assert "Frecuentes" in dash_js
    assert "Recientes" in dash_js

    # 4. Búsqueda y paginación para custom emojis del servidor
    assert "emoji-search-input" in dash_js
    assert "emoji-pager" in dash_css
    assert "CUSTOM_PAGE_SIZE" in dash_js


def test_docs_card_no_underline():
    """Verifica que las cards de 'Explora la documentación' nunca tengan subrayado en títulos o cuerpo (ni en estado normal ni en :hover)."""
    style_css = (LANDING / "style.css").read_text("utf-8")

    # .docs-content a sigue teniendo subrayado para enlaces normales de texto
    assert (
        ".docs-content a { color: var(--accent-soft); text-decoration: underline;"
        in style_css
    )

    # Pero las cards de documentación (.docs-card) anulan el subrayado en normal y hover
    assert ".docs-content a.docs-card" in style_css
    assert (
        ".docs-card h3,\n.docs-card:hover h3 {\n  font-family: var(--font-head);\n  font-size: var(--t-md);\n  font-weight: 700;\n  color: var(--text);\n  margin: 0 0 0.35rem 0;\n  line-height: 1.3;\n  text-decoration: none;\n}"
        in style_css
    )


def test_server_card_dashboard_canonical_href_and_routing():
    """Verifica que el botón Dashboard en la lista de servidores genere la ruta canónica con /inicio y que el dashboard normalice la URL."""
    perfil_js = (LANDING / "js" / "perfil.js").read_text("utf-8")
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    deploy_md = (ROOT / "DEPLOY.md").read_text("utf-8")

    # 1. serverCard genera la URL usando el helper centralizado getDashboardUrl
    assert (
        "const dashboardHref = getDashboardUrl(g.id, plan ? 'premium' : 'inicio', plan, locale);"
        in perfil_js
    )

    # 2. initDash normaliza cualquier acceso raíz a la sub-pestaña activa
    assert "history.replaceState({}, '', getDashboardUrl(GUILD_ID, tab));" in dash_js

    # 3. DEPLOY.md documenta la regex que captura tanto /dashboard como /dashboard/*
    assert "location ~ ^/(es|en|ru|ja|de)/dashboard(/.*)?$ {" in deploy_md


def test_dashboard_persistent_server_picker_and_global_context():
    """Verifica el selector persistente de servidor en el sidebar con cambio reactivo sin recarga total."""
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")
    config_js = (LANDING / "js" / "core" / "config.js").read_text("utf-8")

    # 1. Configuración global reactiva
    assert "export let GUILD_ID" in config_js
    assert "export function setGuildId" in config_js
    assert "export function clearGuildCaches" in config_js

    # 2. Selector de servidor en JS
    assert "buildServerPicker" in dash_js
    assert "selectGuild" in dash_js
    assert "fetchUserGuilds" in dash_js
    assert "server-dropdown-menu" in dash_js
    assert "server-dropdown-search" in dash_js
    assert "Tus servidores con Purgito" in dash_js
    assert "Otros servidores que administras" in dash_js

    # 3. CSS del selector de servidor
    assert ".server-picker" in dash_css
    assert ".server-picker-btn" in dash_css
    assert ".server-dropdown-menu" in dash_css
    assert ".server-dropdown-item" in dash_css
    assert ".server-dropdown-search" in dash_css


def test_dashboard_command_search_palette_ctrl_k():
    """Verifica la paleta de comandos global (Ctrl + K / Cmd + K) con búsqueda y navegación por teclado."""
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")

    # 1. Paleta de comandos en JS
    assert "openCommandPalette" in dash_js
    assert "cmd-palette-modal" in dash_js
    assert "cmd-palette-input" in dash_js
    assert "cmd-palette-results" in dash_js
    assert "e.key.toLowerCase() === 'k'" in dash_js

    # 2. CSS de la paleta
    assert ".cmd-palette-backdrop" in dash_css
    assert ".cmd-palette-modal" in dash_css
    assert ".cmd-palette-input" in dash_css
    assert ".cmd-palette-item" in dash_css
    assert ".cmd-palette-footer" in dash_css
    assert "backdrop-filter: blur(8px)" in dash_css


def test_dashboard_category_grouped_collapsible_navigation():
    """Verifica que la barra lateral organice los módulos por categorías reales de Purgito con acordeones colapsables y badges."""
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")

    # 1. Definición de categorías conceptuales reales (sin anime ni placeholders inventados)
    assert "export const CATEGORIES" in dash_js
    assert "export const MODULES" in dash_js
    for cat in [
        "principal",
        "alertas",
        "anuncios",
        "automatizacion",
        "entretenimiento",
        "utilidades",
    ]:
        assert f"key: '{cat}'" in dash_js

    assert "anime" not in dash_js.lower()

    # 2. Persistencia en localStorage
    assert "purgito_dash_collapsed_cats" in dash_js
    assert "toggleCategoryCollapse" in dash_js
    assert "dash-sidebar-cat-group" in dash_js
    assert "dash-sidebar-cat-header" in dash_js

    # 3. Badges de módulos
    assert "badge-premium" in dash_css
    assert "badge-new" in dash_css
    assert "scrollbar-width: thin" in dash_css


def test_dashboard_executive_inicio_redesign():
    """Verifica el rediseño de Inicio como dashboard ejecutivo con resumen del servidor, límites, acciones rápidas y widgets."""
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    dash_css = (LANDING / "dash.css").read_text("utf-8")

    # 1. Hero resumen del servidor
    assert "dash-server-hero" in dash_js
    assert "dash-server-hero" in dash_css

    # 2. Métricas y avisos de cupo
    assert "withCap" in dash_js
    assert "stat-quota-box" in dash_js
    assert "stat-quota-box" in dash_css

    # 3. Acciones rápidas (Quick Actions)
    assert "quickActionCard" in dash_js
    assert "quick-actions-grid" in dash_js
    assert "quick-action-card" in dash_css

    # 4. Personalización y Actualizaciones
    assert "openStyleModal" in dash_js
    assert "/api/server/${GUILD_ID}/style" in dash_js
    assert "/api/server/${GUILD_ID}/settings/updates" in dash_js


def test_dashboard_availability_and_resilience_architecture():
    """Verifica que el dashboard maneje disponibilidad global de forma robusta para todo tipo de usuario."""
    dash_js = (LANDING / "js" / "dash.js").read_text("utf-8")
    panel_shell_js = (LANDING / "js" / "panel-shell.js").read_text("utf-8")

    # 1. initDash es determinista y no sufre race conditions entre loadHead y activate
    assert "export async function initDash()" in dash_js
    assert "export function renderTopBar(guild)" in dash_js
    assert "fetchUserGuilds" in dash_js

    # 2. Carga resiliente de Inicio con Promise.allSettled
    assert "Promise.allSettled" in dash_js

    # 3. Deduplicación de llamadas concurrentes a /api/me/guilds
    assert "_fetchingGuildsPromise" in dash_js

    # 4. Manejo seguro de listas vacías y null-safety en panel-shell
    assert "Array.isArray(channels)" in panel_shell_js
    assert "Array.isArray(roles)" in panel_shell_js
    assert (
        "setChannelCache((data && Array.isArray(data.channels)) ? data.channels : []);"
        in panel_shell_js
    )


def test_dashboard_frontend_node_suite():
    """Ejecuta los tests del frontend con Node.js verificando que dash.js y sus módulos
    se importen, evalúen y rendericen correctamente sin SyntaxError ni fallas de estado."""
    import shutil
    import subprocess

    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js no está instalado en el entorno")

    res_dash = subprocess.run(
        [node_bin, str(LANDING / "test_dash.mjs")],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert res_dash.returncode == 0, (
        f"test_dash.mjs falló:\nSTDOUT:\n{res_dash.stdout}\nSTDERR:\n{res_dash.stderr}"
    )

    res_hist = subprocess.run(
        [node_bin, str(LANDING / "test_historial.mjs")],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert res_hist.returncode == 0, (
        f"test_historial.mjs falló:\nSTDOUT:\n{res_hist.stdout}\nSTDERR:\n{res_hist.stderr}"
    )
