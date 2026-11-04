"""Opcional: pip install playwright && python -m playwright install chromium.

Backend real + panel real + PostgreSQL de pruebas, sin Discord ni red externa. Los datos son sintéticos
(tests/studio_demo.py) y solo existen en la base de pruebas. Las capturas van a data/ (ignorado por Git).
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
import uuid

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

import pg_support
import webapi
from studio import runtime
from studio.http import register
from studio.local_server import application
from studio.model import Settings, utcnow
from studio.runtime import Collector
from studio.store import Store
from studio_demo import seed_demo
from test_studio import KEY, TOKEN

TABLES = "studio_sessions, studio_usage, studio_inventory, studio_presence, studio_lifecycle, studio_annotations, studio_batches, studio_meta"
SHOTS = Path("data")


@pytest.fixture
def backend():
    database = asyncio.run(pg_support.connect())
    settings = Settings(enabled=True, key=KEY, version="7ee712b")
    store = Store(database, settings)

    async def clean():
        async with store.pool.acquire() as c:
            await c.execute(f"TRUNCATE {TABLES} CASCADE")

    asyncio.run(clean())
    yield store, settings
    asyncio.run(database.close())


@asynccontextmanager
async def studio(store, settings, monkeypatch, *, demo, port):
    now = utcnow()
    if demo:
        async with store.pool.acquire() as c:
            await seed_demo(c, settings, now)
    collector = Collector(store, settings)
    await store.start(collector.session_id, now.replace(microsecond=0))
    collector.bot = type("Bot", (), {"is_ready": lambda self: True, "guilds": []})()
    await collector.flush()
    collector.catalog = {("slash", "ayuda"): "general"}
    monkeypatch.setattr(runtime, "_current", collector)
    monkeypatch.setattr(webapi, "OBSERVABILITY_TOKEN", TOKEN)
    api = web.Application(
        middlewares=[webapi._csrf_origin_middleware, webapi._error_middleware]
    )
    register(api, webapi._internal_gate)
    async with TestServer(api) as backend_server:
        panel = application(TOKEN, backend_port=backend_server.port, port=port)
        async with TestServer(panel, host="127.0.0.1", port=port):
            yield f"http://127.0.0.1:{port}"


async def open_page(playwright, *, width=1440, height=900):
    browser = await playwright.chromium.launch(args=["--no-sandbox"])
    context = await browser.new_context(
        http_credentials={"username": "admin", "password": TOKEN},
        viewport={"width": width, "height": height},
    )
    page = await context.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("console", lambda m: m.type == "error" and problems.append(m.text))
    page.requests = []
    page.on(
        "request",
        lambda r: "/internal/studio/report" in r.url and page.requests.append(r.url),
    )
    return browser, page, problems


async def ready(page):
    await page.wait_for_selector('#content[aria-busy="false"]')
    await page.wait_for_timeout(150)


def test_empty_state_navigation_privacy_and_mobile(backend, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    store, settings = backend

    async def go():
        async with studio(store, settings, monkeypatch, demo=False, port=18081) as base:
            async with playwright.async_playwright() as p:
                browser, page, problems = await open_page(p)
                await page.goto(f"{base}/")
                await ready(page)
                assert await page.locator("#title").inner_text() == "Resumen"
                assert "empezó a medir" in await page.locator(".lead").inner_text()
                assert await page.locator("#nav a").all_inner_texts() == [
                    "Resumen",
                    "Comunidades",
                    "Retención",
                    "Funciones",
                    "Calidad",
                    "Versiones",
                    "Actualizaciones",
                ]
                assert await page.locator('#nav a[aria-current="page"]').count() == 1
                # Los estados vacíos explican qué falta y cuándo habrá datos; nunca un cero inventado.
                await page.locator('#nav a[data-view="retention"]').click()
                await ready(page)
                text = await page.locator("#content").inner_text()
                assert "Sin cohortes" in text or "Todavía no hay cohortes" in text
                assert "Retención D1" in text and "en " in text
                assert "#/retencion" in page.url
                await page.go_back()
                await ready(page)
                assert await page.locator("#title").inner_text() == "Resumen"
                # Sin credenciales ni datos en el almacenamiento del navegador.
                storage = await page.evaluate(
                    "JSON.stringify([localStorage, sessionStorage, document.cookie])"
                )
                assert TOKEN not in storage and "guild_key" not in storage
                assert TOKEN not in await page.content()
                SHOTS.mkdir(exist_ok=True)
                await page.screenshot(
                    path=str(SHOTS / "studio-ui-empty.png"), full_page=True
                )
                await browser.close()
                # Móvil: sin desbordamiento horizontal y con menú lateral.
                browser, page, mobile_problems = await open_page(
                    p, width=390, height=844
                )
                await page.goto(f"{base}/")
                await ready(page)
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                assert await page.evaluate(
                    "document.getElementById('sidebar').getBoundingClientRect().right <= 0"
                )
                await page.locator("#menu").click()
                await page.locator('#nav a[data-view="features"]').click()
                await ready(page)
                assert await page.locator("#title").inner_text() == "Funciones"
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                await page.screenshot(
                    path=str(SHOTS / "studio-ui-mobile.png"), full_page=True
                )
                await browser.close()
                assert not problems and not mobile_problems, (problems, mobile_problems)

    asyncio.run(go())


def test_populated_views_filters_charts_tables_dialogs_and_annotations(
    backend, monkeypatch
):
    playwright = pytest.importorskip("playwright.async_api")
    store, settings = backend

    async def go():
        async with studio(store, settings, monkeypatch, demo=True, port=18082) as base:
            async with playwright.async_playwright() as p:
                browser, page, problems = await open_page(p)
                await page.goto(f"{base}/")
                await ready(page)
                # Portada: una cifra principal, tarjetas, gráfico y estado de la medición.
                assert await page.locator(".kpi-hero .kpi-value").inner_text()
                assert await page.locator(".kpi").count() == 5
                assert await page.locator(".plot").count() >= 1
                assert "Cobertura" in await page.locator("#quality").inner_text()
                # Las ventanas largas terminan en medianoche UTC: ningún día del gráfico queda a medias.
                assert (
                    "T00%3A00%3A00.000Z"
                    in page.requests[-1].split("end=")[1].split("&")[0]
                )
                # Gráfico: crosshair con tooltip, también con teclado.
                box = await page.locator(".plot .overlay").first.bounding_box()
                await page.mouse.move(
                    box["x"] + box["width"] * 0.6, box["y"] + box["height"] / 2
                )
                assert await page.locator("#tooltip").is_visible()
                await page.mouse.move(0, 0)
                assert not await page.locator("#tooltip").is_visible()
                await page.locator(".chart").first.focus()
                await page.keyboard.press("ArrowLeft")
                assert await page.locator("#tooltip").is_visible()
                await page.keyboard.press("Escape")
                assert not await page.locator("#tooltip").is_visible()
                # Cada gráfico tiene su tabla equivalente.
                await page.get_by_role("button", name="Ver como tabla").first.click()
                assert await page.locator(".panel table.table").first.is_visible()
                assert await page.get_by_role("button", name="Ver gráfico").count() >= 1
                # Filtros: período por horas, versión y comparación.
                before = len(page.requests)
                await page.locator('label:has(input[value="72h"])').click()
                await ready(page)
                assert len(page.requests) > before and "p=72h" in page.url
                assert (
                    "agregación por hora" in await page.locator("#quality").inner_text()
                )
                await page.locator('label:has(input[value="7d"])').click()
                await ready(page)
                await page.select_option("#f-version", "7ee712b")
                await ready(page)
                assert (
                    "v=7ee712b" in page.url and "version=7ee712b" in page.requests[-1]
                )
                await page.locator("#f-compare").uncheck()
                await ready(page)
                assert (
                    "cmp=0" in page.url
                    and "Comparación desactivada"
                    in await page.locator("#quality").inner_text()
                )
                await page.locator("#f-compare").check()
                await page.get_by_role("button", name="Quitar filtros").click()
                await ready(page)
                # Personalizado: valida antes de pedir datos.
                await page.locator(".custom summary").click()
                await page.fill("#c-start", "2026-10-02T00:00")
                await page.fill("#c-end", "2026-10-01T00:00")
                await page.get_by_role("button", name="Aplicar período").click()
                assert (
                    "posterior"
                    in await page.locator(".popover .form-error").inner_text()
                )
                await page.keyboard.press("Escape")
                # Diálogos accesibles.
                await page.locator("#open-glossary").click()
                assert await page.locator("dialog#glossary").evaluate("d => d.open")
                assert "Cobertura" in await page.locator("dialog#glossary").inner_text()
                await page.keyboard.press("Escape")
                assert not await page.locator("dialog#glossary").evaluate("d => d.open")
                await page.locator("button.cov-chip").click()
                assert (
                    "Período anterior"
                    in await page.locator("#coverage-dialog").inner_text()
                )
                await page.keyboard.press("Escape")
                # Vistas: cada una renderiza su contenido propio.
                expectations = {
                    "growth": "Entradas y salidas",
                    "retention": "Cohortes por primera actividad",
                    "features": "Todas las funciones",
                    "reliability": "Calidad por función",
                    "versions": "Versiones en el período",
                    "updates": "Registrar un cambio",
                }
                for view, text in expectations.items():
                    await page.locator(f'#nav a[data-view="{view}"]').click()
                    await ready(page)
                    assert text in await page.locator("#content").inner_text(), view
                # Retención: celdas con valor y cambio de métrica.
                await page.locator('#nav a[data-view="retention"]').click()
                await ready(page)
                assert await page.locator("td.heat").count() > 0
                await page.locator('label:has(input[value="installed"])').click()
                await ready(page)
                assert (
                    "presente en el inventario"
                    in await page.locator("#content").inner_text()
                )
                # Funciones: ordenar y filtrar comandos; las no instrumentadas no son un cero.
                await page.locator('#nav a[data-view="features"]').click()
                await ready(page)
                await page.get_by_role("button", name="Usos").click()
                assert await page.locator('th[aria-sort="ascending"]').count() == 1
                assert "Sin instrumentar" in await page.locator("#content").inner_text()
                await page.fill("#cmd-filter", "ayuda")
                await page.wait_for_timeout(150)
                assert await page.locator("#cmd-filter").evaluate(
                    "e => e === document.activeElement"
                )
                # Calidad: los rechazos de Discord se muestran aparte de los fallos.
                await page.locator('#nav a[data-view="reliability"]').click()
                await ready(page)
                content = await page.locator("#content").inner_text()
                assert (
                    "Rechazos de Discord" in content and "fuera de la tasa" in content
                )
                # Actualizaciones: texto malicioso se muestra literal; la anotación se guarda y aparece.
                await page.locator('#nav a[data-view="updates"]').click()
                await ready(page)
                evil = "<img src=x onerror=window.pwned=1>"
                await page.fill('input[name="title"]', evil)
                await page.select_option('select[name="kind"]', "release")
                await page.fill('input[name="version"]', "v-test")
                await page.fill(
                    'textarea[name="note"]', "<script>window.pwned=2</script> nota"
                )
                await page.get_by_role("button", name="Guardar anotación").click()
                await page.wait_for_selector(".timeline h3:has-text('onerror')")
                assert await page.locator(".timeline h3").first.inner_text() == evil
                assert await page.evaluate("window.pwned === undefined")
                assert await page.locator(".timeline img").count() == 0
                await page.fill('input[name="title"]', "")
                await page.get_by_role("button", name="Guardar anotación").click()
                assert (
                    "título" in await page.locator("#content .form-error").inner_text()
                )
                # Capturas para revisión visual.
                SHOTS.mkdir(exist_ok=True)
                for view in (
                    "overview",
                    "growth",
                    "retention",
                    "features",
                    "reliability",
                    "versions",
                    "updates",
                ):
                    await page.locator(f'#nav a[data-view="{view}"]').click()
                    await ready(page)
                    await page.screenshot(
                        path=str(SHOTS / f"studio-ui-{view}.png"), full_page=True
                    )
                await browser.close()
                assert not problems, problems

    asyncio.run(go())


def test_coverage_dialog_lists_gaps_and_comparison_policy(backend, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    store, settings = backend

    async def go():
        async with studio(store, settings, monkeypatch, demo=False, port=18083) as base:
            end = utcnow().replace(minute=0, second=0, microsecond=0)
            async with store.pool.acquire() as c:
                await c.execute("TRUNCATE studio_sessions CASCADE")
                spans = [
                    (end - timedelta(days=70), end - timedelta(days=9)),
                    (end - timedelta(days=8, hours=12), end + timedelta(minutes=3)),
                ]
                for n, (a, b) in enumerate(spans):
                    await c.execute(
                        "INSERT INTO studio_sessions(id,version,started_at,flushed_until) VALUES($1,'v1',$2,$3)",
                        uuid.UUID(int=70 + n),
                        a,
                        b,
                    )
                await c.execute(
                    "INSERT INTO studio_usage VALUES($1,$2,'chat','','mention','ok','v1',9,0,0,$3)",
                    end - timedelta(days=3),
                    settings.guild_key(1),
                    [0] * 11,
                )
            async with playwright.async_playwright() as p:
                browser, page, problems = await open_page(p)
                await page.goto(f"{base}/#/resumen?p=28d")
                await ready(page)
                quality = await page.locator("#quality").inner_text()
                assert "Cobertura" in quality and "Comparación parcial" in quality
                # Una comparación con cobertura parcial se declara «solo lo observado», nunca como estimación.
                assert "solo lo observado" in quality
                await page.locator("button.cov-chip").click()
                dialog = await page.locator("#coverage-dialog").inner_text()
                assert (
                    "Huecos" in dialog
                    and "Período anterior" in dialog
                    and "Solo lo observado" in dialog
                )
                await browser.close()
                assert not problems, problems

    asyncio.run(go())


def test_backend_without_hourly_series_degrades_to_days_with_notice(
    backend, monkeypatch
):
    """Un bot en ejecución anterior a `hourly` no debe dibujar una línea plana en cero con uso real."""
    playwright = pytest.importorskip("playwright.async_api")
    store, settings = backend

    async def go():
        async with studio(store, settings, monkeypatch, demo=True, port=18084) as base:
            async with playwright.async_playwright() as p:
                browser, page, problems = await open_page(p)

                async def old_backend(route):
                    response = await route.fetch()
                    body = await response.json()
                    for window in ("current", "previous"):
                        body[window].pop("hourly", None)
                    await route.fulfill(response=response, json=body)

                await page.route("**/internal/studio/report*", old_backend)
                await page.goto(f"{base}/#/resumen?p=72h")
                await ready(page)
                quality = await page.locator("#quality").inner_text()
                assert "aún no envía la serie por horas" in quality
                assert (
                    "agregación por día" in quality
                    and "por hora" not in quality.split("aún no envía")[0]
                )
                # El uso real aparece (tabla del gráfico), no ceros.
                await page.get_by_role("button", name="Ver como tabla").first.click()
                cells = await page.locator(
                    ".panel table.table tbody tr td"
                ).all_inner_texts()
                assert any(c.strip() not in ("0", "Sin medición", "") for c in cells), (
                    cells
                )
                await page.get_by_role("button", name="Ver gráfico").first.click()
                # Los tramos parciales se dibujan con punto hueco: su contorno debe verse (no ser del color del fondo).
                hollow = page.locator(".plot .dot-hollow")
                assert await hollow.count() >= 1
                stroke = await hollow.first.evaluate("e => getComputedStyle(e).stroke")
                surface = await page.evaluate(
                    "getComputedStyle(document.documentElement).getPropertyValue('--surface').trim()"
                )
                assert surface == "#111820" and stroke != "rgb(17, 24, 32)", stroke
                assert not problems, problems
                await browser.close()

    asyncio.run(go())
