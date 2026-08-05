"""Tests del aviso de arranque/apagado (bot.py::_report_lifecycle /
_handle_shutdown_signal) y de la tabla lifecycle_state (db.py).

Usa una DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db, y
monkeypatchea bot._send_lifecycle_notice / bot.bot.close para no requerir una
conexión real a Discord.
"""

import asyncio
import signal

import aiosqlite
import pytest

import bot as bot_module
import db


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
def _reset_lifecycle_flags(monkeypatch):
    """_lifecycle_reported/_shutdown_in_progress son guards de una sola vez
    por proceso: resetear entre tests para que no se pisen entre sí."""
    monkeypatch.setattr(bot_module, "_lifecycle_reported", False)
    monkeypatch.setattr(bot_module, "_shutdown_in_progress", False)


@pytest.fixture
def captured_notices(monkeypatch):
    sent = []

    async def _fake_notice(content):
        sent.append(content)

    monkeypatch.setattr(bot_module, "_send_lifecycle_notice", _fake_notice)
    return sent


# ---------- db.get_lifecycle_state / set_lifecycle_state ----------


def test_get_lifecycle_state_none_when_never_written(memory_db):
    assert asyncio.run(db.get_lifecycle_state()) is None


def test_set_then_get_lifecycle_state_roundtrip(memory_db):
    asyncio.run(db.set_lifecycle_state(clean_shutdown=True))
    assert asyncio.run(db.get_lifecycle_state())["clean_shutdown"] is True
    asyncio.run(db.set_lifecycle_state(clean_shutdown=False))
    assert asyncio.run(db.get_lifecycle_state())["clean_shutdown"] is False


# ---------- bot._report_lifecycle (arranque) ----------


def test_first_boot_ever_sends_no_notice(memory_db, captured_notices):
    """Fila ausente = primer arranque de la historia: no debe reportar caída
    falsa, pero sí debe dejar la marca de 'corriendo' para la próxima vez."""
    asyncio.run(bot_module._report_lifecycle())
    assert captured_notices == []
    state = asyncio.run(db.get_lifecycle_state())
    assert state["clean_shutdown"] is False


def test_boot_after_clean_shutdown_reports_intentional_restart(
    memory_db, captured_notices
):
    asyncio.run(db.set_lifecycle_state(clean_shutdown=True))
    asyncio.run(bot_module._report_lifecycle())
    assert len(captured_notices) == 1
    assert "reinicio intencional" in captured_notices[0]
    assert "✅" in captured_notices[0]
    # queda marcado como corriendo para el próximo arranque
    assert asyncio.run(db.get_lifecycle_state())["clean_shutdown"] is False


def test_boot_after_unclean_shutdown_reports_crash(memory_db, captured_notices):
    asyncio.run(db.set_lifecycle_state(clean_shutdown=False))
    asyncio.run(bot_module._report_lifecycle())
    assert len(captured_notices) == 1
    assert "caída inesperada" in captured_notices[0]
    assert "⚠️" in captured_notices[0]


def test_report_lifecycle_only_runs_once_per_process(memory_db, captured_notices):
    """on_ready también se dispara al reconectar -- no debe reportar dos veces."""
    asyncio.run(db.set_lifecycle_state(clean_shutdown=True))
    asyncio.run(bot_module._report_lifecycle())
    asyncio.run(bot_module._report_lifecycle())
    assert len(captured_notices) == 1


# ---------- bot._handle_shutdown_signal (SIGTERM/SIGINT) ----------


def test_shutdown_signal_marks_clean_before_notice_before_close(memory_db, monkeypatch):
    order = []
    real_set_state = db.set_lifecycle_state

    async def _tracking_set_state(clean_shutdown):
        order.append("set_state")
        await real_set_state(clean_shutdown)

    async def _tracking_notice(content):
        order.append("notice")

    async def _fake_close():
        order.append("close")

    monkeypatch.setattr(bot_module, "set_lifecycle_state", _tracking_set_state)
    monkeypatch.setattr(bot_module, "_send_lifecycle_notice", _tracking_notice)
    monkeypatch.setattr(bot_module.bot, "close", _fake_close)

    asyncio.run(bot_module._handle_shutdown_signal(signal.SIGTERM))

    assert order == ["set_state", "notice", "close"]
    assert asyncio.run(db.get_lifecycle_state())["clean_shutdown"] is True


def test_shutdown_signal_runs_only_once(memory_db, captured_notices, monkeypatch):
    calls = []

    async def _fake_close():
        calls.append(1)

    monkeypatch.setattr(bot_module.bot, "close", _fake_close)

    asyncio.run(bot_module._handle_shutdown_signal(signal.SIGTERM))
    asyncio.run(bot_module._handle_shutdown_signal(signal.SIGTERM))
    assert len(calls) == 1


def test_shutdown_signal_marks_clean_even_if_close_raises(
    memory_db, captured_notices, monkeypatch
):
    """El estado se escribe ANTES de bot.close(): si el cierre falla o
    cuelga, igual queda registrado que el apagado fue intencional."""

    async def _raising_close():
        raise RuntimeError("boom")

    monkeypatch.setattr(bot_module.bot, "close", _raising_close)

    with pytest.raises(RuntimeError):
        asyncio.run(bot_module._handle_shutdown_signal(signal.SIGTERM))

    assert asyncio.run(db.get_lifecycle_state())["clean_shutdown"] is True
