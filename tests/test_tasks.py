"""Tests de TaskManager (Fase 1): registro en RAM de operaciones largas.

No conecta con Refeed ni GIF Verify todavía -- eso es Fase 2/3. Acá solo se
prueba la API interna: create/start/update_progress/complete/fail/cancel/
get/list_for_guild, aislamiento por guild y seguridad frente a updates
concurrentes.
"""

import asyncio

import pytest

import tasks


@pytest.fixture(autouse=True)
def clean_state():
    tm = tasks.get_task_manager()
    tm._tasks.clear()
    tm._locks.clear()
    tm._expires_at.clear()
    yield


def test_create_produce_task_pending_con_id_unico():
    tm = tasks.get_task_manager()
    t1 = tm.create(guild_id=123, type="gif_health_check")
    t2 = tm.create(guild_id=123, type="gif_health_check")

    assert t1.status == "pending"
    assert t1.guild_id == 123
    assert t1.type == "gif_health_check"
    assert t1.id != t2.id


def test_update_progress_actualiza_campos():
    tm = tasks.get_task_manager()
    t = tm.create(guild_id=1, type="refeed_channels")

    asyncio.run(tm.update_progress(t.id, current=3, total=10, message="canal #general"))

    updated = tm.get(t.id)
    assert updated.progress_current == 3
    assert updated.progress_total == 10
    assert updated.message == "canal #general"


def test_complete_deja_status_completed_y_setea_finished_at():
    tm = tasks.get_task_manager()
    t = tm.create(guild_id=1, type="refeed_channels")

    asyncio.run(tm.complete(t.id))

    updated = tm.get(t.id)
    assert updated.status == "completed"
    assert updated.finished_at is not None


def test_fail_deja_status_failed_con_error_corto_y_finished_at():
    tm = tasks.get_task_manager()
    t = tm.create(guild_id=1, type="gif_health_check")

    asyncio.run(tm.fail(t.id, error="discord_rate_limited"))

    updated = tm.get(t.id)
    assert updated.status == "failed"
    assert updated.error == "discord_rate_limited"
    assert updated.finished_at is not None


def test_cancel_deja_status_cancelled():
    tm = tasks.get_task_manager()
    t = tm.create(guild_id=1, type="refeed_channels")

    asyncio.run(tm.cancel(t.id))

    assert tm.get(t.id).status == "cancelled"


def test_updates_concurrentes_no_corrompen_estado():
    tm = tasks.get_task_manager()
    t = tm.create(guild_id=1, type="refeed_channels")

    async def _run():
        await asyncio.gather(
            *[tm.update_progress(t.id, current=i, total=100) for i in range(50)]
        )

    asyncio.run(_run())

    updated = tm.get(t.id)
    assert updated.progress_total == 100
    assert updated.progress_current in range(50)


def test_list_for_guild_aisla_por_guild():
    tm = tasks.get_task_manager()
    a = tm.create(guild_id=111, type="refeed_channels")
    tm.create(guild_id=222, type="refeed_channels")

    guild_a_tasks = tm.list_for_guild(111)

    assert [t.id for t in guild_a_tasks] == [a.id]


def test_dos_tasks_mismo_guild_conviven_sin_pisarse():
    tm = tasks.get_task_manager()
    refeed = tm.create(guild_id=1, type="refeed_channels")
    gif_check = tm.create(guild_id=1, type="gif_health_check")

    asyncio.run(tm.start(refeed.id))
    asyncio.run(tm.start(gif_check.id))
    asyncio.run(tm.update_progress(refeed.id, current=1))
    asyncio.run(tm.complete(gif_check.id))

    ids = {t.id for t in tm.list_for_guild(1)}
    assert ids == {refeed.id, gif_check.id}
    assert tm.get(refeed.id).status == "running"
    assert tm.get(refeed.id).progress_current == 1
    assert tm.get(gif_check.id).status == "completed"


def test_tasks_terminadas_se_limpian_tras_el_ttl(monkeypatch):
    tm = tasks.get_task_manager()
    t = tm.create(guild_id=1, type="refeed_channels")

    monkeypatch.setattr(tasks.time, "monotonic", lambda: 1000.0)
    asyncio.run(tm.complete(t.id))
    assert tm.get(t.id) is not None

    monkeypatch.setattr(
        tasks.time, "monotonic", lambda: 1000.0 + tasks._FINISHED_TTL_SECONDS + 1
    )
    assert tm.get(t.id) is None
