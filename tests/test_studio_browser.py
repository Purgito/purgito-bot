"""Opcional: pip install playwright && python -m playwright install chromium.
Solo test DB; ninguna red o sesión real de Discord. Screenshot vacío en data/.
"""

import asyncio
from datetime import timedelta
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

import webapi
from studio import runtime
from studio.http import register
from studio.local_server import application
from studio.model import utcnow
from test_studio import setup, TOKEN, KEY
import pg_support
from studio.model import Settings
from studio.store import Store


@pytest.fixture
def backend():
    database = asyncio.run(pg_support.connect())
    settings = Settings(enabled=True, key=KEY, version="v1")
    yield Store(database, settings), settings
    asyncio.run(database.close())


def test_browser_seven_views_filters_notes_empty_and_mobile(backend, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    store, settings = backend
    collector, _ = setup(store, settings, utcnow() - timedelta(days=1))
    monkeypatch.setattr(runtime, "_current", collector)
    monkeypatch.setattr(webapi, "OBSERVABILITY_TOKEN", TOKEN)

    async def run():
        app = web.Application(
            middlewares=[webapi._csrf_origin_middleware, webapi._error_middleware]
        )
        register(app, webapi._internal_gate)
        async with TestServer(app) as api:
            async with TestServer(
                application(TOKEN, backend_port=api.port), host="127.0.0.1", port=18081
            ) as ui:
                async with playwright.async_playwright() as p:
                    browser = await p.chromium.launch(args=["--no-sandbox"])
                    context = await browser.new_context(
                        http_credentials={"username": "admin", "password": TOKEN},
                        viewport={"width": 1440, "height": 1000},
                    )
                    page = await context.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    await page.goto(str(ui.make_url("/")))
                    await page.wait_for_selector('#content[aria-busy="false"]')
                    assert await page.locator("#title").inner_text() == "Resumen"
                    assert await page.locator("#content .value").all_inner_texts() == [
                        "Sin datos",
                        "0",
                        "0",
                        "No calculable",
                    ]
                    assert (
                        "cobertura insuficiente"
                        in await page.locator("#notice").inner_text()
                    )
                    Path("data").mkdir(exist_ok=True)
                    await page.screenshot(
                        path="data/studio-preview-empty.png", full_page=True
                    )
                    for name, title in [
                        ("growth", "Comunidades"),
                        ("retention", "Retención"),
                        ("features", "Funciones"),
                        ("reliability", "Calidad"),
                        ("versions", "Versiones"),
                        ("updates", "Actualizaciones"),
                    ]:
                        await page.locator(f'button[data-view="{name}"]').click()
                        assert await page.locator("#title").inner_text() == title
                    await page.locator(".annotation-form input[name=at]").fill(
                        (utcnow() - timedelta(days=1)).isoformat()[:16]
                    )
                    await page.locator(".annotation-form input[name=title]").fill(
                        "Prueba <img src=x onerror=alert(1)>"
                    )
                    await page.locator(".annotation-form textarea").fill(
                        "Nota privada de prueba; no es actividad del bot."
                    )
                    await page.get_by_role("button", name="Guardar", exact=True).click()
                    await page.wait_for_selector(".note h3")
                    assert "<img src=x" in await page.locator(".note h3").inner_text()
                    assert await page.locator(".note img").count() == 0
                    await page.reload()
                    await page.wait_for_selector('#content[aria-busy="false"]')
                    await page.locator('button[data-view="updates"]').click()
                    assert await page.locator(".note h3").count() == 1
                    await page.locator("#feature").select_option("chat")
                    await page.get_by_role("button", name="Aplicar", exact=True).click()
                    await page.wait_for_selector('#content[aria-busy="false"]')
                    await page.locator('button[data-view="features"]').click()
                    assert (
                        await page.locator("#content article")
                        .first.locator("tbody tr")
                        .count()
                        == 1
                    )
                    assert (
                        "Conversación"
                        in await page.locator("#content article").first.inner_text()
                    )
                    await page.locator("#comparison").select_option("custom")
                    await page.locator("#compare-end").fill(
                        (utcnow() - timedelta(days=35)).isoformat()[:16]
                    )
                    async with page.expect_response(
                        lambda r: "/internal/studio/report?" in r.url
                    ) as compared:
                        await page.get_by_role(
                            "button", name="Aplicar", exact=True
                        ).click()
                    comparison_response = await compared.value
                    assert comparison_response.status == 200
                    comparison_data = await comparison_response.json()
                    assert (
                        comparison_data["period"]["compare_end"]
                        != comparison_data["period"]["start"]
                    )
                    await page.wait_for_selector('#content[aria-busy="false"]')
                    assert await page.evaluate("Object.keys(localStorage).length") == 0
                    assert not errors
                    await page.set_viewport_size({"width": 390, "height": 844})
                    assert await page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth + 1"
                    )
                    await page.screenshot(
                        path="data/studio-preview-mobile.png", full_page=True
                    )
                    await browser.close()

    asyncio.run(run())


def test_browser_shows_baseline_cohorts_coverage_notes_and_discord_refusals(
    backend, monkeypatch
):
    playwright = pytest.importorskip("playwright.async_api")
    from test_studio import seed_history

    store, settings = backend
    now = utcnow()

    async def seed():
        async with store.pool.acquire() as conn:
            await seed_history(conn, settings, now)
            await conn.execute(
                "INSERT INTO studio_usage VALUES($1,$2,'youtube','','background','refused','v1',7,0,0,$3)",
                now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=5),
                settings.guild_key(1),
                [0] * 11,
            )

    asyncio.run(seed())
    collector, _ = setup(store, settings, now)
    monkeypatch.setattr(runtime, "_current", collector)
    monkeypatch.setattr(webapi, "OBSERVABILITY_TOKEN", TOKEN)

    async def run():
        app = web.Application(
            middlewares=[webapi._csrf_origin_middleware, webapi._error_middleware]
        )
        register(app, webapi._internal_gate)
        async with TestServer(app) as api:
            async with TestServer(
                application(TOKEN, backend_port=api.port, port=18082),
                host="127.0.0.1",
                port=18082,
            ) as ui:
                async with playwright.async_playwright() as p:
                    browser = await p.chromium.launch(args=["--no-sandbox"])
                    context = await browser.new_context(
                        http_credentials={"username": "admin", "password": TOKEN}
                    )
                    page = await context.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    await page.goto(str(ui.make_url("/")))
                    await page.wait_for_selector('#content[aria-busy="false"]')
                    notice = await page.locator("#notice").inner_text()
                    assert "hueco(s)" in notice and "registros descartados" in notice
                    assert "Comparación parcial" in notice
                    overview = await page.locator("#content").inner_text()
                    assert "no es una estimación representativa" in overview
                    await page.get_by_role("button", name="Retención").click()
                    text = await page.locator("#content").inner_text()
                    assert "Primera actividad observada" in text
                    assert "línea base" in text and "con entrada verificada" in text
                    await page.get_by_role("button", name="Calidad").click()
                    text = await page.locator("#content").inner_text()
                    assert "Rechazos de Discord" in text
                    assert not errors
                    await browser.close()

    asyncio.run(run())
