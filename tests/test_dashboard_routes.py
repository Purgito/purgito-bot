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
        "/api/server/{guild_id}/stats",
        "/api/server/{guild_id}/style",
        "/api/server/{guild_id}/settings/chat-channels",
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
        # El navbar y el footer salen recortados de index.html, no duplicados.
        assert 'class="nav" id="top"' in page
        assert 'class="footer"' in page
        assert 'id="toast"' in page
        assert '<link rel="stylesheet" href="/dash.css?v=' in page

    assert 'id="contenido"' in perfil
    assert "/js/perfil.js?v=" in perfil
    for hole in ('id="dashHead"', 'id="dashTabs"', 'id="catContent"'):
        assert hole in dash, hole
    assert "/js/dash.js?v=" in dash

    # Las tres tabs del perfil son páginas reales, no anclas.
    for slug in ("conexiones", "facturacion"):
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
    """El acceso al perfil es el bloque avatar+nombre, y solo ese."""
    script = (LANDING / "script.js").read_text("utf-8")
    index = (LANDING / "index.html").read_text("utf-8")
    # Ni ítem en el dropdown…
    assert "label: 'Dashboard'" not in script
    # …ni botón suelto en el nav.
    assert not re.search(r'class="nav-link[^"]*"[^>]*>\s*Dashboard', index)
    # El bloque avatar+nombre navega al perfil.
    assert "profile.href = DASHBOARD" in script
    assert "'/' + LOC + '/perfil'" in script
