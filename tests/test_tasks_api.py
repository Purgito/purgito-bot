"""Fase 4: GET /api/server/{guild_id}/tasks -- expone las Tasks activas de un
guild (TaskManager, Fase 1) vía @guild_api, el mismo decorador que usan
todos los demás endpoints de /api/server/{guild_id}/... No hay ruta pública
ni mecanismo de auth alternativo: estos tests lo confirman monkeypatcheando
get_session/check_guild_access/_bot_guild igual que el resto de la suite de
webapi (ver test_gif_unblock_api.py), no reimplementando la lógica de sesión.
"""

import asyncio
import json

import pytest

import tasks
import webapi

_GUILD_A = 111
_GUILD_B = 222
_USER_ID = "999888777"


class FakeRequest:
    def __init__(self, guild_id):
        self.match_info = {"guild_id": str(guild_id)}
        self.headers = {}
        self.remote = "1.2.3.4"


@pytest.fixture(autouse=True)
def clean_task_manager():
    tm = tasks.get_task_manager()
    tm._tasks.clear()
    tm._locks.clear()
    tm._expires_at.clear()
    yield


@pytest.fixture(autouse=True)
def allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": "Frambuesa"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: object())


def _run(guild_id):
    return asyncio.run(webapi._api_server_tasks_get(FakeRequest(guild_id)))


def _body(resp):
    return json.loads(resp.body)


# ─── aislamiento por guild ─────────────────────────────────────────────────


def test_devuelve_solo_las_tasks_del_guild_pedido():
    tm = tasks.get_task_manager()
    tm.create(guild_id=_GUILD_A, type="gif_health_check")
    tm.create(guild_id=_GUILD_B, type="refeed_channels")

    resp = _run(_GUILD_A)

    assert resp.status == 200
    body = _body(resp)
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["type"] == "gif_health_check"


def test_guild_b_no_ve_las_tasks_de_guild_a_por_error():
    tm = tasks.get_task_manager()
    tm.create(guild_id=_GUILD_A, type="gif_health_check")

    resp = _run(_GUILD_B)

    assert resp.status == 200
    assert _body(resp)["tasks"] == []


# ─── forma de la respuesta ──────────────────────────────────────────────────


def test_formato_de_una_task_running_con_progreso():
    tm = tasks.get_task_manager()
    task = tm.create(guild_id=_GUILD_A, type="gif_health_check")
    asyncio.run(tm.start(task.id))
    asyncio.run(
        tm.update_progress(
            task.id, current=127, total=320, message="Verificando GIFs..."
        )
    )

    body = _body(_run(_GUILD_A))

    (entry,) = body["tasks"]
    assert entry["id"] == task.id
    assert entry["type"] == "gif_health_check"
    assert entry["status"] == "running"
    assert entry["started_at"] is not None
    assert entry["progress_current"] == 127
    assert entry["progress_total"] == 320
    assert entry["message"] == "Verificando GIFs..."


def test_error_expuesto_tal_cual_porque_ya_viene_saneado_por_taskmanager():
    """TaskManager.fail() (Fase 1) nunca guarda un traceback en error -- solo
    un mensaje corto ya pensado para mostrarse. Por eso el endpoint lo puede
    exponer directo, sin filtrarlo de nuevo."""
    tm = tasks.get_task_manager()
    task = tm.create(guild_id=_GUILD_A, type="gif_health_check")
    asyncio.run(tm.fail(task.id, error="unknown_error"))

    (entry,) = _body(_run(_GUILD_A))["tasks"]
    assert entry["status"] == "failed"
    assert entry["error"] == "unknown_error"


# ─── mismo mecanismo de auth que el resto de /api/server/{guild_id}/... ────


def test_sin_sesion_devuelve_401_como_cualquier_otro_endpoint_guild_api(
    monkeypatch,
):
    async def fake_get_session(request):
        return {}

    monkeypatch.setattr(webapi, "get_session", fake_get_session)

    resp = _run(_GUILD_A)

    assert resp.status == 401


def test_sin_manage_guild_devuelve_403_como_cualquier_otro_endpoint_guild_api(
    monkeypatch,
):
    from aiohttp import web

    async def fake_check_guild_access(request, guild_id):
        return web.json_response({"error": "acceso denegado"}, status=403)

    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)

    resp = _run(_GUILD_A)

    assert resp.status == 403
