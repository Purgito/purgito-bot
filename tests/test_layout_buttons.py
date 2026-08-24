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
from cogs.layout_buttons import LayoutButtons


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


# ─── Modal interactivo: open_modal / DynamicLayoutModal ──────────────────────


def test_cog_load_registers_open_modal_action(memory_db):
    action_data = json.dumps(
        {
            "title": "Feedback",
            "fields": [{"label": "Comentarios", "style": "paragraph"}],
            "response_message": "¡Gracias!",
        }
    )
    asyncio.run(
        db.add_button_action("purgito_modal_trigger_123", 1, "open_modal", action_data)
    )
    bot = MagicMock()
    bot.add_view = MagicMock()
    cog = LayoutButtons(bot)
    asyncio.run(cog.cog_load())
    bot.add_view.assert_called_once()
    view = bot.add_view.call_args.args[0]
    assert len(view.children) == 1
    assert view.children[0].custom_id == "purgito_modal_trigger_123"


def test_open_modal_sends_modal():
    from cogs.layout_buttons import _open_modal

    guild = _make_guild(42, role=None, bot_top_role_position=5)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    interaction.response.send_modal = AsyncMock()

    modal_data = {
        "title": "Sugerencias",
        "fields": [
            {
                "label": "Idea",
                "style": "paragraph",
                "placeholder": "Tu idea aquí",
            }
        ],
        "response_message": "Sugerencia recibida",
    }
    asyncio.run(_open_modal(interaction, 42, modal_data))
    interaction.response.send_modal.assert_awaited_once()
    modal = interaction.response.send_modal.await_args.args[0]
    assert modal.title == "Sugerencias"
    assert len(modal.inputs) == 1
    assert modal.inputs[0].label == "Idea"


def test_open_modal_default_field_when_fields_empty():
    from cogs.layout_buttons import _open_modal

    guild = _make_guild(42, role=None, bot_top_role_position=5)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    interaction.response.send_modal = AsyncMock()

    modal_data = {"title": "Contacto"}
    asyncio.run(_open_modal(interaction, 42, modal_data))
    interaction.response.send_modal.assert_awaited_once()
    modal = interaction.response.send_modal.await_args.args[0]
    assert modal.title == "Contacto"
    assert len(modal.inputs) == 1
    assert modal.inputs[0].label == "Contacto"


def test_open_modal_wrong_guild_context():
    from cogs.layout_buttons import _open_modal

    guild = _make_guild(42, role=None, bot_top_role_position=5)
    member = _make_member(roles=[])
    interaction = _make_interaction(guild, member)
    interaction.response.send_modal = AsyncMock()

    asyncio.run(_open_modal(interaction, 999, {"title": "Test"}))
    interaction.response.send_modal.assert_not_called()
    interaction.response.send_message.assert_awaited_once()


def test_dynamic_layout_modal_on_submit():
    from cogs.layout_buttons import DynamicLayoutModal

    modal = DynamicLayoutModal(
        title="Formulario", response_message="Mensaje personalizado"
    )
    modal_interaction = MagicMock(spec=discord.Interaction)
    modal_interaction.guild_id = 42
    modal_interaction.response = MagicMock()
    modal_interaction.response.send_message = AsyncMock()

    asyncio.run(modal.on_submit(modal_interaction))
    modal_interaction.response.send_message.assert_awaited_once_with(
        "Mensaje personalizado", ephemeral=True
    )


def test_dynamic_layout_modal_on_submit_default_locale():
    from cogs.layout_buttons import DynamicLayoutModal

    modal = DynamicLayoutModal(title="Formulario")
    modal_interaction = MagicMock(spec=discord.Interaction)
    modal_interaction.guild_id = 42
    modal_interaction.response = MagicMock()
    modal_interaction.response.send_message = AsyncMock()

    asyncio.run(modal.on_submit(modal_interaction))
    modal_interaction.response.send_message.assert_awaited_once_with(
        "Tu respuesta fue enviada.", ephemeral=True
    )


def test_assign_button_custom_ids_modal():
    from layout_v2 import MODAL_TRIGGER_PREFIX, assign_button_custom_ids

    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {
                        "style": "modal",
                        "label": "Dar feedback",
                        "modal_title": "Formulario de feedback",
                        "destination": {"type": "channel", "channel_id": 98765},
                    },
                    {"style": "link", "label": "Web", "url": "https://example.com"},
                    {"style": "role", "label": "Rol", "role_id": 123},
                ],
            }
        ]
    }
    assignments = assign_button_custom_ids(layout)
    assert len(assignments) == 2
    modal_asgn = next(a for a in assignments if a["action_type"] == "open_modal")
    role_asgn = next(a for a in assignments if a["action_type"] == "role_toggle")
    assert modal_asgn["custom_id"].startswith(MODAL_TRIGGER_PREFIX)
    assert modal_asgn["modal_title"] == "Formulario de feedback"
    assert modal_asgn["destination"]["channel_id"] == 98765
    assert role_asgn["role_id"] == 123


def test_dynamic_layout_modal_on_submit_sends_to_channel():
    from cogs.layout_buttons import DynamicLayoutModal

    modal = DynamicLayoutModal(
        title="Reporte",
        fields=[
            {"label": "Título", "style": "short"},
            {"label": "Detalles", "style": "paragraph"},
        ],
        destination={"type": "channel", "channel_id": 555},
    )
    # Simular valores ingresados por el usuario
    modal.inputs[0]._value = "Bug en login"
    modal.inputs[1]._value = "No carga el botón"

    channel = MagicMock()
    channel.send = AsyncMock()

    guild = MagicMock(spec=discord.Guild)
    guild.id = 42
    guild.get_channel = MagicMock(return_value=channel)

    user = MagicMock(spec=discord.Member)
    user.id = 1234
    user.name = "testuser"
    user.display_name = "Test User"
    user.display_avatar.url = "https://cdn.discordapp.com/avatars/1234/abc.png"

    modal_interaction = MagicMock(spec=discord.Interaction)
    modal_interaction.guild_id = 42
    modal_interaction.guild = guild
    modal_interaction.user = user
    modal_interaction.response = MagicMock()
    modal_interaction.response.send_message = AsyncMock()

    asyncio.run(modal.on_submit(modal_interaction))

    channel.send.assert_awaited_once()
    call_kwargs = channel.send.await_args.kwargs
    assert "embed" in call_kwargs
    sent_embed = call_kwargs["embed"]
    assert "Reporte" in sent_embed.title
    assert len(sent_embed.fields) == 2
    assert sent_embed.fields[0].name == "Título"
    assert sent_embed.fields[0].value == "Bug en login"
    assert sent_embed.fields[1].name == "Detalles"
    assert sent_embed.fields[1].value == "No carga el botón"

    # Verificar seguridad de menciones: allowed_mentions debe estar restringido (none)
    assert "allowed_mentions" in call_kwargs
    am = call_kwargs["allowed_mentions"]
    assert am.everyone is False
    assert am.roles is False
    assert am.users is False

    modal_interaction.response.send_message.assert_awaited_once_with(
        "Tu respuesta fue enviada.", ephemeral=True
    )


def test_validate_buttons_payload_modal():
    from webapi import validate_buttons_payload

    # Válido
    valid_btns = [
        {
            "style": "modal",
            "label": "Abrir",
            "modal_title": "Formulario",
            "modal_fields": [{"label": "Campo 1", "style": "short"}],
            "destination": {"type": "channel", "channel_id": 12345},
        }
    ]
    assert validate_buttons_payload(valid_btns) is None

    # Título faltante
    assert (
        validate_buttons_payload(
            [{"style": "modal", "label": "Abrir", "modal_title": ""}]
        )
        is not None
    )

    # Título demasiado largo
    assert (
        validate_buttons_payload(
            [{"style": "modal", "label": "Abrir", "modal_title": "x" * 46}]
        )
        is not None
    )

    # Más de 5 campos
    too_many_fields = [{"label": f"C{i}"} for i in range(6)]
    assert (
        validate_buttons_payload(
            [
                {
                    "style": "modal",
                    "label": "Abrir",
                    "modal_title": "Test",
                    "modal_fields": too_many_fields,
                }
            ]
        )
        is not None
    )

    # Campo con etiqueta vacía
    assert (
        validate_buttons_payload(
            [
                {
                    "style": "modal",
                    "label": "Abrir",
                    "modal_title": "Test",
                    "modal_fields": [{"label": "   "}],
                }
            ]
        )
        is not None
    )


def test_list_button_actions_includes_open_modal(memory_db):
    action_data_modal = json.dumps(
        {
            "title": "Feedback",
            "fields": [{"label": "Texto"}],
            "destination": {"type": "dm_confirmation"},
        }
    )
    action_data_role = json.dumps({"role_id": 101})

    asyncio.run(db.add_button_action("modal_btn_1", 1, "open_modal", action_data_modal))
    asyncio.run(db.add_button_action("role_btn_1", 1, "role_toggle", action_data_role))

    actions = asyncio.run(db.list_button_actions())
    types = {a["action_type"] for a in actions}
    assert "open_modal" in types
    assert "role_toggle" in types
