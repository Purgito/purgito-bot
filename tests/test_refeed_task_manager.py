"""Fase 3: conecta /refeed_channels al TaskManager (src/tasks.py) sin tocar
la lógica de backfill ni channel_refeed_status.

Task representa la ejecución GLOBAL del comando (running/completed/failed +
"cuántos canales de N ya se procesaron"); channel_refeed_status sigue siendo
el cursor persistente POR CANAL, sin cambios de ningún tipo -- este archivo
prueba puntualmente que sigue escribiéndose igual a través de la
_refeed_guild ya modificada (no reescribe la suite existente de Refeed,
solo agrega estas pruebas).

_refeed_running (guard viejo, dict[guild_id, asyncio.Task] en RAM) se
reemplazó por una consulta a TaskManager.list_for_guild(...) filtrando
type="refeed_channels" y status en (pending, running) -- ver
cogs/chat.py:_refeed_task_running. Mismo patrón de test que ya usaba
test_refeed_channel_guard.py para el guard viejo: dos llamadas sin await
entre medio deben comportarse igual (una gana, la otra vuelve False).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiosqlite
import discord
import pytest

import cogs.chat as chat_mod
import db
import tasks
from cogs.chat import Chat

_GUILD = 555


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


@pytest.fixture(autouse=True)
def clean_task_manager():
    tm = tasks.get_task_manager()
    tm._tasks.clear()
    tm._locks.clear()
    tm._expires_at.clear()
    yield


def _fake_channel(channel_id: int, name: str) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = name
    channel.mention = f"#{name}"
    channel.permissions_for.return_value = SimpleNamespace(
        read_messages=True, read_message_history=True
    )
    return channel


def _fake_guild(guild_id: int, channels: list) -> SimpleNamespace:
    by_id = {c.id: c for c in channels}
    return SimpleNamespace(
        id=guild_id, me=SimpleNamespace(), get_channel=lambda cid: by_id.get(cid)
    )


class _FakeReportChannel:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, content):
        self.sent.append(content)


async def _fake_list_corpus_channels(guild_id):
    return [101]


async def _fake_not_ignored(guild_id, channel_id):
    return False


# ─── _refeed_guild: progreso a la Task + channel_refeed_status intacto ────────


def test_refeed_guild_reporta_progreso_y_no_cambia_channel_refeed_status(
    memory_db, monkeypatch
):
    channel = _fake_channel(101, "general")
    guild = _fake_guild(_GUILD, [channel])

    monkeypatch.setattr(chat_mod, "list_corpus_channels", _fake_list_corpus_channels)
    monkeypatch.setattr(chat_mod, "is_channel_ignored", _fake_not_ignored)

    chat = Chat(SimpleNamespace())

    async def fake_refeed_channel(guild_id, ch, max_messages):
        await db.upsert_channel_refeed_status(
            guild_id,
            ch.id,
            newest_message_id=999,
            oldest_message_id=1,
            backfill_complete=True,
        )
        return {
            "saved": 3,
            "gifs_saved": 0,
            "backfill_complete": True,
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    tm = tasks.get_task_manager()
    task = tm.create(guild_id=_GUILD, type="refeed_channels")

    totals = asyncio.run(
        chat._refeed_guild(guild, None, _FakeReportChannel(), task_id=task.id)
    )

    assert totals["completed"] == 1

    status = asyncio.run(db.get_channel_refeed_status(_GUILD, 101))
    assert status["backfill_complete"] is True
    assert status["newest_message_id"] == 999
    assert status["oldest_message_id"] == 1

    final = tm.get(task.id)
    assert final.progress_current == 1
    assert final.progress_total == 1
    assert "general" in final.message


# ─── start_refeed_channels: ciclo de vida completo de la Task ─────────────────


def _capture_background_task(monkeypatch):
    captured = {}
    real_create_task = asyncio.create_task

    def capture(coro, *a, **k):
        t = real_create_task(coro, *a, **k)
        captured["bg"] = t
        return t

    monkeypatch.setattr(chat_mod.asyncio, "create_task", capture)
    return captured


def test_start_refeed_channels_pasa_por_running_progresa_y_completa(monkeypatch):
    chat = Chat(SimpleNamespace())
    guild = SimpleNamespace(id=_GUILD)

    async def fake_refeed_guild(g, progress_msg, report_channel, task_id=None):
        tm = tasks.get_task_manager()
        await tm.update_progress(task_id, current=1, total=2, message="Procesando #a")
        await tm.update_progress(task_id, current=2, total=2, message="Procesando #b")
        return {"saved": 5}

    monkeypatch.setattr(chat, "_refeed_guild", fake_refeed_guild)
    captured = _capture_background_task(monkeypatch)

    tm = tasks.get_task_manager()

    async def run():
        started = chat.start_refeed_channels(guild, None, None)
        assert started is True

        running = tm.list_for_guild(_GUILD)
        assert len(running) == 1
        assert running[0].type == "refeed_channels"
        assert running[0].status in ("pending", "running")
        task_id = running[0].id

        await captured["bg"]

        final = tm.get(task_id)
        assert final.status == "completed"
        assert final.progress_current == 2
        assert final.progress_total == 2

    asyncio.run(run())


def test_start_refeed_channels_deja_la_task_failed_con_error_corto_si_explota(
    monkeypatch,
):
    chat = Chat(SimpleNamespace())
    guild = SimpleNamespace(id=_GUILD)

    async def fake_refeed_guild(g, progress_msg, report_channel, task_id=None):
        raise RuntimeError("boom: detalle técnico sensible que no debe filtrarse")

    monkeypatch.setattr(chat, "_refeed_guild", fake_refeed_guild)
    captured = _capture_background_task(monkeypatch)

    tm = tasks.get_task_manager()

    async def run():
        chat.start_refeed_channels(guild, None, None)
        task_id = tm.list_for_guild(_GUILD)[0].id

        await captured["bg"]

        final = tm.get(task_id)
        assert final.status == "failed"
        assert final.error
        assert "boom" not in final.error
        assert final.finished_at is not None

    asyncio.run(run())


# ─── guard: no dos refeeds del mismo guild a la vez (vía TaskManager) ─────────


def test_start_refeed_channels_guard_evita_dos_corridas_simultaneas(monkeypatch):
    chat = Chat(SimpleNamespace())
    guild = SimpleNamespace(id=_GUILD)
    release = asyncio.Event()
    calls = 0

    async def fake_refeed_guild(g, progress_msg, report_channel, task_id=None):
        nonlocal calls
        calls += 1
        await release.wait()
        return {"saved": 0}

    monkeypatch.setattr(chat, "_refeed_guild", fake_refeed_guild)
    captured = _capture_background_task(monkeypatch)

    async def run():
        first = chat.start_refeed_channels(guild, None, None)
        second = chat.start_refeed_channels(guild, None, None)
        assert first is True
        assert second is False
        release.set()
        await captured["bg"]

    asyncio.run(run())
    assert calls == 1
