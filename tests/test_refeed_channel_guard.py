"""Sección 3, tercera pasada: _refeed_channel (cogs/chat.py) tiene tres
entradas independientes (/refeed, /refeed_channels vía _refeed_guild,
on_guild_channel_update) que no se conocían entre sí -- dos de ellas podían
correr en paralelo sobre el MISMO canal, leyendo el mismo
channel_refeed_status y pisando el progreso de la otra al escribir
(upsert_channel_refeed_status hace un COALESCE simple, sin comparar contra
lo que ya había).

_refeeding_channels (guard en memoria, mismo patrón que _refeed_running) hace
que la segunda corrida sobre un canal ya ocupado vuelva sin tocar nada, en
vez de correr en paralelo con la primera. Se testea el wrapper aislado
(_refeed_channel_locked mockeada) para no depender de DB ni de discord.py,
igual que test_refeed_retry.py.
"""

import asyncio
from types import SimpleNamespace

import pytest

import cogs.chat as chat_mod
from cogs.chat import Chat

_EMPTY_RESULT = {
    "saved": 0,
    "gifs_saved": 0,
    "backfill_complete": False,
    "was_incremental": False,
    "forbidden": False,
}


@pytest.fixture(autouse=True)
def _clean_guard():
    chat_mod._refeeding_channels.clear()
    yield
    chat_mod._refeeding_channels.clear()


def test_dos_corridas_concurrentes_del_mismo_canal_no_se_pisan(monkeypatch):
    """Mientras la primera corrida de un canal sigue en curso, una segunda
    sobre el MISMO canal vuelve sin llamar a _refeed_channel_locked --
    exactamente lo que evita la carrera sobre channel_refeed_status."""
    chat = Chat(SimpleNamespace())
    calls = 0
    release = asyncio.Event()

    async def fake_locked(guild_id, channel, max_messages):
        nonlocal calls
        calls += 1
        await release.wait()
        return {**_EMPTY_RESULT, "saved": 1, "backfill_complete": True}

    monkeypatch.setattr(chat, "_refeed_channel_locked", fake_locked)
    channel = SimpleNamespace(id=100)

    async def run():
        first = asyncio.ensure_future(chat._refeed_channel(1, channel, 100))
        await asyncio.sleep(0)  # deja correr a `first` hasta su primer await
        second = await chat._refeed_channel(1, channel, 100)
        release.set()
        first_result = await first
        return first_result, second

    first_result, second_result = asyncio.run(run())

    assert calls == 1  # la corrida real solo pasó UNA vez
    assert first_result["saved"] == 1
    assert second_result == _EMPTY_RESULT


def test_canal_distinto_no_se_bloquea(monkeypatch):
    """El guard es por (guild_id, channel_id): un canal distinto no se ve
    afectado por una corrida en curso en otro."""
    chat = Chat(SimpleNamespace())
    calls = []

    async def fake_locked(guild_id, channel, max_messages):
        calls.append(channel.id)
        return {**_EMPTY_RESULT, "backfill_complete": True}

    monkeypatch.setattr(chat, "_refeed_channel_locked", fake_locked)

    async def run():
        return await asyncio.gather(
            chat._refeed_channel(1, SimpleNamespace(id=100), 100),
            chat._refeed_channel(1, SimpleNamespace(id=200), 100),
        )

    asyncio.run(run())
    assert sorted(calls) == [100, 200]


def test_el_guard_se_libera_despues_de_terminar(monkeypatch):
    """Una vez que la corrida termina, el mismo canal puede volver a correr
    -- el guard no queda pegado."""
    chat = Chat(SimpleNamespace())
    calls = 0

    async def fake_locked(guild_id, channel, max_messages):
        nonlocal calls
        calls += 1
        return {**_EMPTY_RESULT, "saved": calls, "backfill_complete": True}

    monkeypatch.setattr(chat, "_refeed_channel_locked", fake_locked)
    channel = SimpleNamespace(id=100)

    async def run():
        first = await chat._refeed_channel(1, channel, 100)
        second = await chat._refeed_channel(1, channel, 100)
        return first, second

    first, second = asyncio.run(run())
    assert calls == 2
    assert first["saved"] == 1
    assert second["saved"] == 2


def test_el_guard_se_libera_incluso_si_la_corrida_real_tira_una_excepcion(
    monkeypatch,
):
    """finally: si _refeed_channel_locked explota, igual libera el canal --
    si no, un solo error dejaría ese canal bloqueado para siempre."""
    chat = Chat(SimpleNamespace())

    async def boom(guild_id, channel, max_messages):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat, "_refeed_channel_locked", boom)
    channel = SimpleNamespace(id=100)

    async def run():
        with pytest.raises(RuntimeError):
            await chat._refeed_channel(1, channel, 100)
        assert (1, 100) not in chat_mod._refeeding_channels

    asyncio.run(run())
