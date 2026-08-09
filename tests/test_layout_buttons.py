"""Tests de cogs/layout_buttons.py (Fase 3 del editor de embeds): registro de
la vista persistente de botones de rol al arrancar el bot, y el toggle de rol
en sí (asignar/quitar, y los casos de permisos insuficientes del bot). Usa una
DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

import db
from cogs.layout_buttons import LayoutButtons, register_button_actions


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


# ─── Registro de vistas persistentes ─────────────────────────────────────────


def test_cog_load_registers_one_view_per_unique_custom_id(memory_db):
    asyncio.run(
        db.add_button_action(
            "purgito_role_toggle_a", 1, "role_toggle", json.dumps({"role_id": 10})
        )
    )
    asyncio.run(
        db.add_button_action(
            "purgito_role_toggle_b", 1, "role_toggle", json.dumps({"role_id": 11})
        )
    )
    bot = MagicMock()
    bot.add_view = MagicMock()
    cog = LayoutButtons(bot)
    asyncio.run(cog.cog_load())
    bot.add_view.assert_called_once()
    view = bot.add_view.call_args.args[0]
    ids = {c.custom_id for c in view.children}
    assert ids == {"purgito_role_toggle_a", "purgito_role_toggle_b"}
    assert len(view.children) == 2  # sin duplicados


def test_cog_load_with_no_rows_does_not_register(memory_db):
    bot = MagicMock()
    bot.add_view = MagicMock()
    cog = LayoutButtons(bot)
    asyncio.run(cog.cog_load())
    bot.add_view.assert_not_called()


def test_cog_load_skips_malformed_action_data(memory_db):
    asyncio.run(
        db.add_button_action("purgito_role_toggle_bad", 1, "role_toggle", "not json")
    )
    asyncio.run(
        db.add_button_action(
            "purgito_role_toggle_ok", 1, "role_toggle", json.dumps({"role_id": 1})
        )
    )
    bot = MagicMock()
    bot.add_view = MagicMock()
    cog = LayoutButtons(bot)
    asyncio.run(cog.cog_load())
    view = bot.add_view.call_args.args[0]
    assert len(view.children) == 1
    assert view.children[0].custom_id == "purgito_role_toggle_ok"


def test_purge_guild_data_removes_button_actions(memory_db):
    asyncio.run(
        db.add_button_action(
            "purgito_role_toggle_x", 1, "role_toggle", json.dumps({"role_id": 1})
        )
    )
    asyncio.run(db.purge_guild_data(1))
    assert asyncio.run(db.get_button_action("purgito_role_toggle_x")) is None


# ─── Toggle de rol: asignar / quitar / permisos insuficientes ────────────────


def _make_role(role_id, position):
    role = MagicMock()
    role.id = role_id
    role.position = position
    role.mention = f"<@&{role_id}>"
    return role


def _make_guild(guild_id, role, bot_top_role_position, manage_roles=True):
    guild = MagicMock()
    guild.id = guild_id
    guild.get_role.return_value = role
    me = MagicMock()
    me.guild_permissions.manage_roles = manage_roles
    me.top_role.position = bot_top_role_position
    guild.me = me
    return guild


def _make_member(roles):
    member = MagicMock(spec=discord.Member)
    member.roles = roles
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


def _make_interaction(guild, member):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = member
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _role_toggle(*args):
    from cogs.layout_buttons import _role_toggle as fn

    return fn(*args)


@pytest.fixture(autouse=True)
def _fake_guild_locale(monkeypatch):
    """_role_toggle resuelve el locale del guild vía DB -- estos tests no
    levantan una (a diferencia de memory_db, arriba), así que se mockea
    para no requerir una."""
    import cogs.layout_buttons as layout_buttons_mod

    async def fake_guild_locale(guild_id):
        return "es"

    monkeypatch.setattr(layout_buttons_mod, "guild_locale", fake_guild_locale)


def test_role_toggle_assigns_when_missing():
    role = _make_role(1, position=1)
    guild = _make_guild(42, role, bot_top_role_position=5)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    asyncio.run(_role_toggle(interaction, 42, 1))
    member.add_roles.assert_awaited_once()
    member.remove_roles.assert_not_called()
    assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True


def test_role_toggle_removes_when_present():
    role = _make_role(1, position=1)
    guild = _make_guild(42, role, bot_top_role_position=5)
    member = _make_member(roles=[role])
    interaction = _make_interaction(guild, member)
    asyncio.run(_role_toggle(interaction, 42, 1))
    member.remove_roles.assert_awaited_once()
    member.add_roles.assert_not_called()


def test_role_toggle_insufficient_permissions_no_manage_roles():
    role = _make_role(1, position=1)
    guild = _make_guild(42, role, bot_top_role_position=5, manage_roles=False)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    asyncio.run(_role_toggle(interaction, 42, 1))
    member.add_roles.assert_not_called()
    member.remove_roles.assert_not_called()
    interaction.response.send_message.assert_awaited_once()


def test_role_toggle_role_above_bot_hierarchy():
    role = _make_role(1, position=10)  # por encima del top_role del bot
    guild = _make_guild(42, role, bot_top_role_position=5)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    asyncio.run(_role_toggle(interaction, 42, 1))
    member.add_roles.assert_not_called()


def test_role_toggle_role_no_longer_exists():
    guild = _make_guild(42, role=None, bot_top_role_position=5)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    asyncio.run(_role_toggle(interaction, 42, 999))
    member.add_roles.assert_not_called()
    interaction.response.send_message.assert_awaited_once()


def test_role_toggle_wrong_guild_context():
    role = _make_role(1, position=1)
    guild = _make_guild(42, role, bot_top_role_position=5)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    # custom_id fue mintado para el guild 999, pero llega en una interacción del 42.
    asyncio.run(_role_toggle(interaction, 999, 1))
    member.add_roles.assert_not_called()
    member.remove_roles.assert_not_called()
