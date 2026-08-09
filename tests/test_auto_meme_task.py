"""Sección 5, ronda 2: auto_meme_task (cogs/memes.py) tenía el mismo problema
que check_announcements (cogs/anuncios.py) -- si el meme se postea con éxito
en Discord pero el UPDATE de last_posted_at falla, el schedule sigue "due" y
la próxima corrida (10 min) lo repostea, un duplicado visible. El fix separa
el try/except del envío del try/except del marcado posterior, con un log
distinguible para el segundo caso.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import cogs.memes as memes_mod
from cogs.memes import Memes


def _schedule(guild_id=1, channel_id=10):
    return {"guild_id": guild_id, "channel_id": channel_id, "interval_minutes": 30}


@pytest.fixture
def patched(monkeypatch):
    """Deja pasar auto_meme_task hasta channel.send con todo lo previo
    parcheado a valores válidos; retorna (cog, channel, calls) para que cada
    test decida cómo falla update_meme_last_posted."""
    channel = SimpleNamespace(id=10, send=AsyncMock())

    async def fake_pick_pool_image(guild_id, log_prefix):
        return b"bytes-imagen", "https://cdn.example.com/x.png"

    async def fake_corpus_sample(guild_id, min_words=1, limit=400):
        return ["hola", "mundo"]

    async def fake_caption(guild_id, img_bytes, corpus_sample):
        return "un caption cualquiera"

    def fake_render_caption(img_bytes, caption):
        return b"meme-bytes"

    monkeypatch.setattr(memes_mod, "is_premium_guild", lambda gid: True)
    monkeypatch.setattr(memes_mod, "_pick_pool_image", fake_pick_pool_image)
    monkeypatch.setattr(memes_mod, "get_corpus_messages_filtered", fake_corpus_sample)
    monkeypatch.setattr(memes_mod, "_generate_caption", fake_caption)
    monkeypatch.setattr(memes_mod, "render_caption", fake_render_caption)

    bot = SimpleNamespace(get_channel=lambda cid: channel)
    # isinstance(channel, discord.TextChannel) en auto_meme_task: mismo truco
    # que test_memes_target_fail.py, parchear la clase para que el fake pase.
    monkeypatch.setattr(memes_mod.discord, "TextChannel", SimpleNamespace)
    cog = Memes(bot)
    return cog, channel


def _run(cog, schedules, monkeypatch):
    async def fake_due():
        return schedules

    monkeypatch.setattr(memes_mod, "get_due_meme_schedules", fake_due)
    asyncio.run(cog.auto_meme_task.coro(cog))


def test_meme_se_postea_y_se_marca_ok(patched, monkeypatch):
    cog, channel = patched

    marked = []

    async def fake_mark(guild_id, channel_id):
        marked.append((guild_id, channel_id))

    monkeypatch.setattr(memes_mod, "update_meme_last_posted", fake_mark)

    _run(cog, [_schedule()], monkeypatch)

    channel.send.assert_awaited_once()
    assert marked == [(1, 10)]


def test_meme_se_postea_pero_falla_el_marcado_loguea_fuerte_y_distinguible(
    patched, monkeypatch, caplog
):
    """El meme YA salió a Discord (channel.send se llamó) aunque el UPDATE
    posterior falle -- y el log tiene que dejar rastro explícito de que
    puede reenviarse, no un genérico indistinguible de un fallo de envío."""
    cog, channel = patched

    async def failing_mark(guild_id, channel_id):
        raise RuntimeError("db explotó")

    monkeypatch.setattr(memes_mod, "update_meme_last_posted", failing_mark)

    with caplog.at_level(logging.ERROR):
        _run(cog, [_schedule()], monkeypatch)

    channel.send.assert_awaited_once()  # el meme SÍ se posteó
    assert any(
        "se posteó" in r.message and "no se pudo marcar" in r.message
        for r in caplog.records
    )
