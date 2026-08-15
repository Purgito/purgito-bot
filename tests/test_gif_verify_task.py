"""Fase 2: conecta /api/server/{guild_id}/settings/gifs/verify y
run_gif_health_check (cogs/gifs.py) al TaskManager de la Fase 1.

No prueba el chequeo de salud en sí (eso ya lo cubre test_gif_health.py) --
mockea el trabajo real (r2.check_gif_url_health, asyncio.sleep) para no
esperar minutos reales, y verifica la secuencia de estados de la Task:
running -> progreso reportado periódicamente -> completed. También cubre el
caso de fallo no recuperable -> failed con un error corto, no un traceback.
"""

import asyncio

import aiosqlite
import pytest

import cogs.gifs as gifs_mod
import db
import r2
import tasks
import webapi

_GUILD = 123
_USER_ID = "999888777"


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _insert_gif(conn, guild_id, url) -> int:
    cur = await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url) VALUES (?, ?)", (guild_id, url)
    )
    await conn.commit()
    return cur.lastrowid


async def _fast_sleep(*args, **kwargs) -> None:
    return None


@pytest.fixture(autouse=True)
def clean_task_manager():
    tm = tasks.get_task_manager()
    tm._tasks.clear()
    tm._locks.clear()
    tm._expires_at.clear()
    yield


# ─── run_gif_health_check reporta progreso a una Task ─────────────────────────


def test_run_gif_health_check_reporta_progreso_periodicamente(memory_db, monkeypatch):
    async def setup():
        for i in range(25):
            await _insert_gif(memory_db, _GUILD, f"https://example.com/{i}.gif")

    asyncio.run(setup())
    monkeypatch.setattr(r2, "check_gif_url_health", lambda *a, **k: "ok")
    monkeypatch.setattr(gifs_mod.asyncio, "sleep", _fast_sleep)

    tm = tasks.get_task_manager()
    task = tm.create(guild_id=_GUILD, type="gif_health_check")

    calls = []
    real_update_progress = tm.update_progress

    async def spy_update_progress(task_id, **kwargs):
        calls.append(kwargs)
        await real_update_progress(task_id, **kwargs)

    monkeypatch.setattr(tm, "update_progress", spy_update_progress)

    checked = asyncio.run(gifs_mod.run_gif_health_check(_GUILD, task_id=task.id))

    assert checked == 25
    assert len(calls) > 1  # avanzó en más de un paso, no solo al final

    final = tm.get(task.id)
    assert final.progress_current == 25
    assert final.progress_total == 25
    assert final.message == "Verificando GIFs..."


def test_run_gif_health_check_sin_task_id_no_llama_al_task_manager(
    memory_db, monkeypatch
):
    """El ciclo diario (guild_id=None, sin task_id) sigue funcionando igual
    que antes de la Fase 2: no debe tocar el TaskManager para nada."""

    async def setup():
        await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")

    asyncio.run(setup())
    monkeypatch.setattr(r2, "check_gif_url_health", lambda *a, **k: "ok")
    monkeypatch.setattr(gifs_mod.asyncio, "sleep", _fast_sleep)

    checked = asyncio.run(gifs_mod.run_gif_health_check())

    assert checked == 1
    assert tasks.get_task_manager().list_for_guild(_GUILD) == []


# ─── endpoint /settings/gifs/verify ────────────────────────────────────────


class FakeRequest:
    def __init__(self, guild_id=_GUILD):
        self.match_info = {"guild_id": str(guild_id)}
        self.headers = {}
        self.remote = "1.2.3.4"


@pytest.fixture(autouse=True)
def allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": "Frambuesa"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: object())
    monkeypatch.setattr(webapi, "_rate_gif_verify", webapi.LRUDict(64))


def _capture_background_task(monkeypatch):
    captured = {}
    real_create_task = asyncio.create_task

    def capture(coro, *a, **k):
        t = real_create_task(coro, *a, **k)
        captured["bg"] = t
        return t

    monkeypatch.setattr(webapi.asyncio, "create_task", capture)
    return captured


def test_verify_endpoint_deja_la_task_running_y_luego_completed(memory_db, monkeypatch):
    async def fake_run_gif_health_check(guild_id=None, limit=500, task_id=None):
        if task_id:
            await tasks.get_task_manager().update_progress(
                task_id, current=1, total=1, message="Verificando GIFs..."
            )
        return 1

    monkeypatch.setattr(webapi, "run_gif_health_check", fake_run_gif_health_check)
    captured = _capture_background_task(monkeypatch)

    async def run():
        resp = await webapi._api_server_gifs_verify(FakeRequest())
        assert resp.status == 200

        tm = tasks.get_task_manager()
        running = tm.list_for_guild(_GUILD)
        assert len(running) == 1
        assert running[0].status == "running"

        await captured["bg"]

        finished = tm.get(running[0].id)
        assert finished.status == "completed"
        assert finished.progress_current == 1

    asyncio.run(run())


def test_verify_endpoint_deja_la_task_failed_con_error_corto_si_explota(
    memory_db, monkeypatch
):
    async def fake_run_gif_health_check(guild_id=None, limit=500, task_id=None):
        raise RuntimeError("boom: detalle técnico sensible que no debe filtrarse")

    monkeypatch.setattr(webapi, "run_gif_health_check", fake_run_gif_health_check)
    captured = _capture_background_task(monkeypatch)

    async def run():
        resp = await webapi._api_server_gifs_verify(FakeRequest())
        assert resp.status == 200

        tm = tasks.get_task_manager()
        running = tm.list_for_guild(_GUILD)
        task_id = running[0].id

        await captured["bg"]

        finished = tm.get(task_id)
        assert finished.status == "failed"
        assert finished.error
        assert "boom" not in finished.error
        assert finished.finished_at is not None

    asyncio.run(run())
