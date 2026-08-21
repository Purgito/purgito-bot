"""Tests para la revisión integral de la experiencia de Discord (Discord UX Overhaul).

Cubre:
- SetupView (/setup): selector de canales, validación NSFW, permisos, estados dinámicos, refeed.
- SettingsPanel (/settings): CanalesCategory y AprendizajeCategory.
- WelcomeView y DM embed: bienvenida orientada a /setup y dashboard como secundario.
- empty_corpus_reply: mensaje amigable que guía a /setup.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

import db
import generation
from cogs.settings import (
    SettingsPanel,
    SetupView,
    WelcomeView,
    build_dm_welcome_embed,
    build_welcome_embed,
)
import tasks

_GUILD_ID = 999
_USER_ADMIN = 123
_USER_NON_ADMIN = 456


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(aiosqlite.connect(":memory:"))
    asyncio.run(conn.executescript(db.SCHEMA))
    asyncio.run(conn.execute("ALTER TABLE user_corpus ADD COLUMN channel_id INTEGER"))
    asyncio.run(conn.commit())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


@pytest.fixture(autouse=True)
def clean_task_manager():
    tm = tasks.get_task_manager()
    tm._tasks.clear()
    tm._locks.clear()
    tm._expires_at.clear()
    yield


def _make_channel(
    channel_id: int,
    name: str,
    is_nsfw: bool = False,
    view_perm: bool = True,
    read_history_perm: bool = True,
):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = name
    channel.is_nsfw.return_value = is_nsfw
    perms = SimpleNamespace(
        view_channel=view_perm,
        read_message_history=read_history_perm,
        send_messages=True,
    )
    channel.permissions_for.return_value = perms
    return channel


def _make_guild(channels=None):
    guild = MagicMock(spec=discord.Guild)
    guild.id = _GUILD_ID
    guild.name = "Servidor de Prueba"
    guild.text_channels = channels or []
    guild.get_channel = lambda cid: next(
        (c for c in guild.text_channels if c.id == cid), None
    )
    guild.me = SimpleNamespace(id=777)
    return guild


def _make_interaction(user_id: int, is_admin: bool = True, guild=None):
    inter = MagicMock(spec=discord.Interaction)
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.guild_permissions = SimpleNamespace(manage_guild=is_admin)
    inter.user = member
    inter.guild = guild or _make_guild()
    inter.response = AsyncMock()
    inter.response.is_done.return_value = False
    inter.followup = AsyncMock()
    inter.edit_original_response = AsyncMock()
    return inter


# ─── SetupView: Estados y Flujo ──────────────────────────────────────────────


def test_setup_view_status_no_channels(memory_db):
    guild = _make_guild()
    view = SetupView(guild, "es", _USER_ADMIN)
    embed = asyncio.run(view.build_embed())

    assert "Configuración inicial de Purgito" in embed.title
    assert "Purgito todavía no está aprendiendo de ningún canal" in embed.description


def test_setup_view_status_channels_no_history(memory_db):
    guild = _make_guild([_make_channel(101, "general")])
    asyncio.run(db.add_corpus_channel(_GUILD_ID, 101))

    view = SetupView(guild, "es", _USER_ADMIN)
    embed = asyncio.run(view.build_embed())

    assert "Purgito aprenderá los mensajes nuevos de 1 canal(es)" in embed.description
    assert "<#101>" in embed.description


def test_setup_view_status_ready_with_history(memory_db):
    guild = _make_guild([_make_channel(101, "general")])
    asyncio.run(db.add_corpus_channel(_GUILD_ID, 101))
    asyncio.run(db.save_corpus_and_user_message(_GUILD_ID, 101, 1, 99, "hola a todos"))

    view = SetupView(guild, "es", _USER_ADMIN)
    embed = asyncio.run(view.build_embed())

    assert "Purgito ya aprendió de 1 mensajes en 1 canal(es)" in embed.description
    assert "<#101>" in embed.description


def test_setup_view_status_refeeding(memory_db):
    guild = _make_guild([_make_channel(101, "general")])
    asyncio.run(db.add_corpus_channel(_GUILD_ID, 101))

    tm = tasks.get_task_manager()
    task = tm.create(guild_id=_GUILD_ID, type="refeed_channels")
    asyncio.run(tm.start(task.id))

    view = SetupView(guild, "es", _USER_ADMIN)
    embed = asyncio.run(view.build_embed())

    assert "Purgito está aprendiendo ahora" in embed.description


def test_setup_view_rebuild_components(memory_db):
    guild = _make_guild([_make_channel(101, "general")])
    asyncio.run(db.add_corpus_channel(_GUILD_ID, 101))

    view = SetupView(guild, "es", _USER_ADMIN)
    asyncio.run(view.rebuild())

    # Debe contener: ChannelSelect, Botón de aprender historial, Botón de link a dashboard
    items = view.children
    assert any(isinstance(item, discord.ui.ChannelSelect) for item in items)
    assert any(
        isinstance(item, discord.ui.Button) and item.label == "Aprender del historial"
        for item in items
    )
    assert any(
        isinstance(item, discord.ui.Button) and item.label == "Abrir dashboard"
        for item in items
    )


def test_setup_view_channel_select_validates_and_saves(memory_db):
    ch_general = _make_channel(101, "general")
    ch_nsfw = _make_channel(102, "nsfw-chat", is_nsfw=True)
    ch_secret = _make_channel(103, "secret", view_perm=False)
    guild = _make_guild([ch_general, ch_nsfw, ch_secret])

    view = SetupView(guild, "es", _USER_ADMIN)
    asyncio.run(view.rebuild())

    channel_select = next(
        item for item in view.children if isinstance(item, discord.ui.ChannelSelect)
    )
    channel_select._values = [
        SimpleNamespace(id=101),
        SimpleNamespace(id=102),
        SimpleNamespace(id=103),
    ]

    inter = _make_interaction(_USER_ADMIN, is_admin=True, guild=guild)
    inter.response.is_done.return_value = True
    asyncio.run(channel_select.callback(inter))

    allowed = asyncio.run(db.list_corpus_channels(_GUILD_ID))
    # Solo general debe haber entrado; nsfw y secret deben haberse rechazado
    assert allowed == [101]

    # Feedback message debe haberse renderizado en la edición del mensaje
    assert inter.edit_original_response.called
    call_kwargs = inter.edit_original_response.call_args.kwargs
    embed = call_kwargs["embed"]
    assert "es un canal NSFW" in embed.description
    assert "no tiene permiso para leer #secret" in embed.description


def test_setup_view_interaction_check(memory_db):
    guild = _make_guild()
    view = SetupView(guild, "es", _USER_ADMIN)

    # Invoker admin pasa
    inter_admin = _make_interaction(_USER_ADMIN, is_admin=True, guild=guild)
    assert asyncio.run(view.interaction_check(inter_admin)) is True

    # Otro usuario es rechazado
    inter_other = _make_interaction(_USER_NON_ADMIN, is_admin=True, guild=guild)
    assert asyncio.run(view.interaction_check(inter_other)) is False

    # Invoker sin manage_guild es rechazado
    inter_no_perm = _make_interaction(_USER_ADMIN, is_admin=False, guild=guild)
    assert asyncio.run(view.interaction_check(inter_no_perm)) is False


# ─── SettingsPanel: CanalesCategory & AprendizajeCategory ───────────────────


def test_canales_category_in_settings(memory_db):
    guild = _make_guild([_make_channel(101, "general")])
    panel = SettingsPanel(guild, "es", _USER_ADMIN)
    panel.current_key = "canales"

    embed = asyncio.run(panel.build_embed())
    assert "Canales de aprendizaje" in embed.title

    asyncio.run(panel.rebuild())
    assert any(isinstance(i, discord.ui.ChannelSelect) for i in panel.children)


def test_aprendizaje_category_in_settings(memory_db):
    guild = _make_guild([_make_channel(101, "general")])
    asyncio.run(db.add_corpus_channel(_GUILD_ID, 101))

    panel = SettingsPanel(guild, "es", _USER_ADMIN)
    panel.current_key = "aprendizaje"

    embed = asyncio.run(panel.build_embed())
    assert "Aprender del historial" in embed.title

    asyncio.run(panel.rebuild())
    btn = next(
        (
            i
            for i in panel.children
            if isinstance(i, discord.ui.Button) and i.label == "Iniciar aprendizaje"
        ),
        None,
    )
    assert btn is not None
    assert btn.disabled is False


# ─── WelcomeView & DM Embed ──────────────────────────────────────────────────


def test_build_welcome_embed():
    guild = _make_guild()
    embed = build_welcome_embed(guild, "es")

    assert embed.title == "¡Hola! Soy Purgito"
    assert "Aprendo cómo escribe tu servidor" in embed.description
    assert "/generar" in embed.description
    # No debe contener jerga técnica de Markov ni de corpus
    assert "Markov" not in embed.description
    assert "corpus" not in embed.description


def test_welcome_view_buttons():
    view = WelcomeView("es", _GUILD_ID)
    labels = [getattr(btn, "label", None) for btn in view.children]
    assert "Configurar Purgito" in labels
    assert "Abrir dashboard" in labels


def test_build_dm_welcome_embed():
    guild = _make_guild()
    embed = build_dm_welcome_embed(guild, "es", scan=None)

    assert "Gracias por agregarme" in embed.title
    assert "/setup" in embed.description
    assert "/generar" in embed.description


# ─── Empty Corpus Reply ─────────────────────────────────────────────────────


def test_empty_corpus_reply():
    msg = generation.empty_corpus_reply(_GUILD_ID, "es", throttle=False)
    assert "/setup" in msg
    assert "Todavía no he aprendido de este servidor" in msg
    # No debe contener menciones al dashboard como requisito obligatorio
    assert "Markov" not in msg
