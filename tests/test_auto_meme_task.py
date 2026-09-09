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
import db
from cogs.memes import Memes


def _schedule(guild_id=1, channel_id=10, last_error=None):
    return {
        "guild_id": guild_id,
        "channel_id": channel_id,
        "interval_minutes": 30,
        "last_error": last_error,
    }


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

    async def fake_guild_locale(guild_id):
        return "es"

    monkeypatch.setattr(memes_mod, "is_premium_guild", lambda gid: True)
    monkeypatch.setattr(memes_mod, "guild_locale", fake_guild_locale)
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


# ── AUDITORIA_UX.md #8: avisar (una vez) cuando el schedule está bloqueado ──


def _patch_set_error(monkeypatch):
    calls = []

    async def fake_set_error(guild_id, channel_id, error):
        calls.append((guild_id, channel_id, error))

    monkeypatch.setattr(memes_mod, "set_meme_schedule_error", fake_set_error)
    return calls


def test_sin_imagenes_en_pool_avisa_una_vez_y_guarda_el_motivo(patched, monkeypatch):
    cog, channel = patched
    set_calls = _patch_set_error(monkeypatch)

    async def no_image(guild_id, log_prefix):
        return None, None

    monkeypatch.setattr(memes_mod, "_pick_pool_image", no_image)

    _run(cog, [_schedule()], monkeypatch)

    channel.send.assert_awaited_once()
    assert "🎯" in channel.send.await_args.args[0]
    assert set_calls == [(1, 10, memes_mod.MEME_SCHEDULE_ERROR_NO_POOL_IMAGES)]


def test_sin_imagenes_en_pool_no_repite_el_aviso_si_ya_estaba_marcado(
    patched, monkeypatch
):
    """El motivo no cambió desde la corrida anterior -- no hay que volver a
    publicar el mismo aviso cada 10 minutos."""
    cog, channel = patched
    set_calls = _patch_set_error(monkeypatch)

    async def no_image(guild_id, log_prefix):
        return None, None

    monkeypatch.setattr(memes_mod, "_pick_pool_image", no_image)

    schedule = _schedule(last_error=memes_mod.MEME_SCHEDULE_ERROR_NO_POOL_IMAGES)
    _run(cog, [schedule], monkeypatch)

    channel.send.assert_not_awaited()
    assert set_calls == []


def test_corpus_vacio_avisa_una_vez_y_guarda_el_motivo(patched, monkeypatch):
    cog, channel = patched
    set_calls = _patch_set_error(monkeypatch)

    async def empty_corpus(guild_id, min_words=1, limit=400):
        return []

    monkeypatch.setattr(memes_mod, "get_corpus_messages_filtered", empty_corpus)

    _run(cog, [_schedule()], monkeypatch)

    channel.send.assert_awaited_once()
    assert set_calls == [(1, 10, memes_mod.MEME_SCHEDULE_ERROR_EMPTY_CORPUS)]


def test_meme_posteado_con_exito_limpia_un_error_previo(patched, monkeypatch):
    """El canal venía bloqueado (sin imágenes, por ejemplo) y ahora sí pudo
    postear -- limpiar el motivo para que un futuro bloqueo distinto vuelva
    a avisar."""
    cog, channel = patched
    set_calls = _patch_set_error(monkeypatch)
    monkeypatch.setattr(memes_mod, "update_meme_last_posted", AsyncMock())

    schedule = _schedule(last_error=memes_mod.MEME_SCHEDULE_ERROR_EMPTY_CORPUS)
    _run(cog, [schedule], monkeypatch)

    channel.send.assert_awaited_once()  # el meme, no un aviso de bloqueo
    assert set_calls == [(1, 10, None)]


def test_meme_posteado_sin_error_previo_no_toca_set_meme_schedule_error(
    patched, monkeypatch
):
    cog, channel = patched
    set_calls = _patch_set_error(monkeypatch)
    monkeypatch.setattr(memes_mod, "update_meme_last_posted", AsyncMock())

    _run(cog, [_schedule()], monkeypatch)

    assert set_calls == []


# ── db.py: last_error persiste y se refleja en get_due/list ────────────────


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def test_set_meme_schedule_error_persiste_y_se_puede_limpiar(temp_db):
    async def run():
        await db.add_meme_schedule(1, 10, 120)
        await db.set_meme_schedule_error(1, 10, db.MEME_SCHEDULE_ERROR_NO_POOL_IMAGES)
        due = await db.get_due_meme_schedules()
        listed = await db.list_meme_schedules(1)

        await db.set_meme_schedule_error(1, 10, None)
        due_after_clear = await db.get_due_meme_schedules()
        return due, listed, due_after_clear

    due, listed, due_after_clear = asyncio.run(run())

    assert due[0]["last_error"] == db.MEME_SCHEDULE_ERROR_NO_POOL_IMAGES
    assert listed[0]["last_error"] == db.MEME_SCHEDULE_ERROR_NO_POOL_IMAGES
    assert due_after_clear[0]["last_error"] is None
