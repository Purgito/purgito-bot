import datetime
from unittest.mock import MagicMock

import discord
import pytest

from placeholders import (
    build_event_context,
    extract_variables_from_content,
    extract_variables_from_text,
    format_localized_date,
    format_number,
    get_available_placeholders,
    get_preview_context,
    resolve_content_placeholders,
    resolve_placeholders,
    validate_content_variables,
    validate_variables,
)


def test_format_helpers():
    assert format_number(1284, "es") == "1.284"
    assert format_number(1284, "en") == "1,284"

    dt = datetime.datetime(2026, 8, 21, 12, 0, tzinfo=datetime.timezone.utc)
    assert format_localized_date(dt, "es") == "21 de agosto de 2026"
    assert format_localized_date(dt, "en") == "August 21, 2026"
    assert format_localized_date(None) == "N/A"


def test_extract_variables_from_text():
    text = "Hola {user}, bienvenido a {server_name}! Miembro #{server_membercount}."
    vars_found = extract_variables_from_text(text)
    assert vars_found == {"user", "server_name", "server_membercount"}

    assert extract_variables_from_text("") == set()
    assert extract_variables_from_text(None) == set()
    assert extract_variables_from_text("Sin variables") == set()


def test_extract_variables_from_content():
    # Plain text
    assert extract_variables_from_content(
        "plain_text", "Hola {user}"
    ) == {"user"}
    assert extract_variables_from_content(
        "plain_text", {"message": "Hola {server_name}"}
    ) == {"server_name"}

    # Classic Embed
    embed = {
        "title": "Bienvenido {user_name}!",
        "description": "En {server_name} ya somos {server_membercount}",
        "fields": [{"name": "Canal", "value": "{channel}"}],
        "footer": {"text": "ID: {user_id}", "icon_url": "{server_icon}"},
        "author": {"name": "{server_owner}", "icon_url": "{user_avatar}"},
        "thumbnail": {"url": "{user_avatar}"},
        "image": {"url": "https://example.com/banner.png"},
    }
    embed_vars = extract_variables_from_content("classic_embed", [embed])
    assert embed_vars == {
        "user_name",
        "server_name",
        "server_membercount",
        "channel",
        "user_id",
        "server_icon",
        "server_owner",
        "user_avatar",
    }

    # Layout V2
    layout = {
        "blocks": [
            {
                "type": "container",
                "children": [
                    {"type": "text", "content": "¡Bienvenido {user} a {server_name}!"},
                    {
                        "type": "section",
                        "texts": ["Miembro {server_membercount_ordinal}"],
                        "accessory": {
                            "type": "button",
                            "label": "Ir a {channel_name}",
                            "url": "https://discord.com",
                        },
                    },
                ],
            }
        ]
    }
    layout_vars = extract_variables_from_content("layout_v2", layout)
    assert layout_vars == {
        "user",
        "server_name",
        "server_membercount_ordinal",
        "channel_name",
    }


def test_validate_variables():
    # Valid welcome
    errors = validate_variables({"user", "server_name", "date"}, "welcome")
    assert errors == []

    # Unknown variable
    errors = validate_variables({"noexiste", "user"}, "welcome")
    assert len(errors) == 1
    assert "Variable desconocida: `{noexiste}`" in errors[0]

    # Incompatible variable (boost variable in welcome)
    errors = validate_variables(
        {"server_nextboostlevel", "user"}, "welcome"
    )
    assert len(errors) == 1
    assert "no está disponible para el evento 'welcome'" in errors[0]

    # Valid boost variable in boost event
    errors = validate_variables(
        {"server_nextboostlevel", "server_nextboostlevel_required", "user"},
        "boost",
    )
    assert errors == []

    # Invalid event type
    errors = validate_variables({"user"}, "invalid_event")
    assert len(errors) == 1


def test_get_available_placeholders():
    welcome_placeholders = get_available_placeholders("welcome")
    names = [p["name"] for p in welcome_placeholders]
    assert "user" in names
    assert "server_name" in names
    assert "server_nextboostlevel" not in names

    boost_placeholders = get_available_placeholders("boost")
    boost_names = [p["name"] for p in boost_placeholders]
    assert "user" in boost_names
    assert "server_nextboostlevel" in boost_names


def test_resolve_placeholders():
    context = {
        "user": "<@123>",
        "server_name": "Purgito Server",
        "server_membercount": "100",
    }
    template = "Hola {user}, bienvenido a {server_name}! Somos {server_membercount}."
    resolved = resolve_placeholders(template, context)
    assert resolved == "Hola <@123>, bienvenido a Purgito Server! Somos 100."

    # Unknown placeholder stays as is
    assert resolve_placeholders("{desconocido}", context) == "{desconocido}"


def test_resolve_content_placeholders_embed_and_layout():
    context = {
        "user": "<@123>",
        "user_name": "Isa",
        "user_avatar": "https://cdn.discord.com/avatar.png",
        "server_name": "Purgito Server",
        "server_membercount": "1.284",
    }

    # Embed
    embed = {
        "title": "Bienvenido {user_name}!",
        "description": "Entraste a {server_name}",
        "thumbnail": {"url": "{user_avatar}"},
        "fields": [{"name": "Miembros", "value": "{server_membercount}"}],
    }
    resolved_embeds = resolve_content_placeholders(
        "classic_embed", [embed], context
    )
    assert resolved_embeds[0]["title"] == "Bienvenido Isa!"
    assert resolved_embeds[0]["description"] == "Entraste a Purgito Server"
    assert resolved_embeds[0]["thumbnail"]["url"] == "https://cdn.discord.com/avatar.png"
    assert resolved_embeds[0]["fields"][0]["value"] == "1.284"

    # Layout V2
    layout = {
        "blocks": [
            {
                "type": "container",
                "children": [
                    {"type": "text", "content": "Bienvenido {user}!"},
                    {
                        "type": "section",
                        "texts": ["Servidor: {server_name}"],
                        "accessory": {
                            "type": "thumbnail",
                            "url": "{user_avatar}",
                            "description": "Avatar de {user_name}",
                        },
                    },
                ],
            }
        ]
    }
    resolved_layout = resolve_content_placeholders(
        "layout_v2", layout, context
    )
    container_children = resolved_layout["blocks"][0]["children"]
    assert container_children[0]["content"] == "Bienvenido <@123>!"
    assert container_children[1]["texts"][0] == "Servidor: Purgito Server"
    assert container_children[1]["accessory"]["url"] == "https://cdn.discord.com/avatar.png"
    assert container_children[1]["accessory"]["description"] == "Avatar de Isa"


def test_get_preview_context():
    ctx = get_preview_context("welcome", locale="es")
    assert ctx["user"] == "@Usuario de prueba"
    assert ctx["server_name"] == "Servidor de prueba"
    assert ctx["server_membercount"] == "1.284"
    assert ctx["server_membercount_ordinal"] == "#1.284"
    assert "user_avatar" in ctx
    assert "date" in ctx


def test_build_event_context():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123456
    guild.name = "Real Guild"
    guild.member_count = 50
    guild.members = [MagicMock()]
    guild.icon = MagicMock()
    guild.icon.url = "https://cdn.discordapp.com/icons/123/icon.png"
    guild.owner_id = 999
    guild.owner = MagicMock()
    guild.owner.display_name = "GuildOwner"
    guild.created_at = datetime.datetime(2021, 5, 10, tzinfo=datetime.timezone.utc)
    guild.roles = [MagicMock(), MagicMock()]
    guild.channels = [MagicMock(), MagicMock(), MagicMock()]
    guild.premium_tier = 1
    guild.premium_subscription_count = 3

    member = MagicMock(spec=discord.Member)
    member.id = 777
    member.name = "punky"
    member.mention = "<@777>"
    member.discriminator = "0"
    member.display_name = "Punky Display"
    member.nick = "Punky Nick"
    member.display_avatar = MagicMock()
    member.display_avatar.url = "https://cdn.discordapp.com/avatars/777/avatar.png"
    member.created_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    member.joined_at = datetime.datetime(2022, 2, 2, tzinfo=datetime.timezone.utc)
    member.premium_since = None

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 444
    channel.name = "llegadas"
    channel.mention = "<#444>"

    ctx = build_event_context(
        "welcome", guild, member, channel=channel, locale="es"
    )
    assert ctx["user"] == "<@777>"
    assert ctx["user_name"] == "punky"
    assert ctx["user_nick"] == "Punky Nick"
    assert ctx["user_displayname"] == "Punky Display"
    assert ctx["server_name"] == "Real Guild"
    assert ctx["server_membercount"] == "50"
    assert ctx["server_membercount_ordinal"] == "#50"
    assert ctx["channel_name"] == "llegadas"
    assert ctx["channel"] == "<#444>"
    assert ctx["server_boostlevel"] == "1"
    assert ctx["server_boostcount"] == "3"
    assert ctx["server_nextboostlevel"] == "2"
    assert ctx["server_nextboostlevel_required"] == "7"
    assert ctx["server_nextboostlevel_until_required"] == "4"
    assert ctx["user_boost_since"] == "N/A"


def test_date_fallbacks_no_booster_returns_na():
    """SEC-06: Un usuario sin boost o sin fecha de ingreso devuelve N/A en lugar de la fecha de hoy."""
    guild = MagicMock(spec=discord.Guild, id=1, name="G", member_count=10, premium_tier=0, premium_subscription_count=0, roles=[], channels=[], owner=None, owner_id=1, created_at=None, icon=None)
    member = MagicMock(spec=discord.Member, id=2, name="u", mention="<@2>", display_name="u", nick=None, created_at=None, joined_at=None, premium_since=None)

    ctx = build_event_context("welcome", guild, member, locale="es")
    assert ctx["user_boost_since"] == "N/A"
    assert ctx["user_joined_at"] == "N/A"
    assert ctx["user_created_at"] == "N/A"


def test_resolve_corrupt_structures_safe():
    """SEC-07: Estructuras con elementos None o tipos no esperados se procesan sin romper ni lanzar excepciones."""
    ctx = {"user": "@User", "server_name": "Guild"}

    # Embeds con None y no-dicts
    corrupt_embeds = [None, 123, {"title": "Title with {user}"}, None]
    res_embeds = resolve_content_placeholders("classic_embed", corrupt_embeds, ctx)
    assert isinstance(res_embeds, list)
    assert res_embeds[0] == {}
    assert res_embeds[2]["title"] == "Title with @User"

    # Layout V2 con None en bloques
    corrupt_layout = {
        "blocks": [
            None,
            123,
            {"type": "section", "texts": [None, 456, "Hello {user}"]},
            {"type": "media_gallery", "items": [None, {"url": "http://example.com/img.png"}]},
        ]
    }
    res_layout = resolve_content_placeholders("layout_v2", corrupt_layout, ctx)
    assert isinstance(res_layout, dict)
    assert res_layout["blocks"][0] == {}
    assert res_layout["blocks"][2]["texts"] == ["Hello @User"]
