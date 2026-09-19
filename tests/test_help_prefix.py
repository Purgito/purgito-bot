"""/help mostraba los comandos de prefijo ("!ping", "!dl", los filtros de
imagen) con el símbolo "!" fijo aunque el guild hubiera personalizado el
prefix (settings.custom_prefix, ver db.get_guild_prefix) -- bug reportado:
un admin cambiaba el símbolo y el menú de ayuda seguía mostrando el viejo.
CATEGORIES (help_view.py) usa el placeholder "{prefix}" y build_category_embed/
HelpView lo resuelven con el prefix real del guild."""

import asyncio
from types import SimpleNamespace

import cogs.general as general_mod
from cogs.general import General
from help_view import build_category_embed


class _FakeResponse:
    def __init__(self):
        self.sent: dict | None = None

    async def send_message(self, **kwargs):
        self.sent = kwargs


class _FakeInteraction:
    def __init__(self, guild_id=1, guild_name="Mi Server"):
        self.guild = SimpleNamespace(id=guild_id, name=guild_name)
        self.user = SimpleNamespace(id=42)
        self.response = _FakeResponse()

    async def original_response(self):
        return SimpleNamespace()


def _cog():
    return General(SimpleNamespace())


def _run_help(monkeypatch, interaction, custom_prefix):
    async def fake_guild_locale(guild_id):
        return "es"

    async def fake_get_guild_prefix(guild_id):
        return custom_prefix

    monkeypatch.setattr(general_mod, "guild_locale", fake_guild_locale)
    monkeypatch.setattr(general_mod, "get_guild_prefix", fake_get_guild_prefix)
    cog = _cog()
    asyncio.run(cog.help.callback(cog, interaction))
    return interaction.response.sent["view"]


def test_help_usa_el_prefix_personalizado_del_guild(monkeypatch):
    view = _run_help(monkeypatch, _FakeInteraction(), custom_prefix="$")
    assert view.prefix == "$"


def test_help_cae_al_prefix_default_sin_personalizar(monkeypatch):
    view = _run_help(monkeypatch, _FakeInteraction(), custom_prefix=None)
    assert view.prefix == "!"


def test_help_sin_guild_usa_el_prefix_default():
    """DMs (interaction.guild is None): no hay guild_id para resolver un
    custom_prefix, igual que bot.py:get_prefix."""
    cog = _cog()
    interaction = _FakeInteraction()
    interaction.guild = None

    asyncio.run(cog.help.callback(cog, interaction))

    assert interaction.response.sent["view"].prefix == "!"


def test_build_category_embed_admin_refleja_el_prefix_custom():
    embed = build_category_embed("admin", "Mi Server", "$")
    assert "$ping" in embed.description
    assert "!ping" not in embed.description


def test_build_category_embed_imagen_refleja_el_prefix_custom():
    embed = build_category_embed("imagen", "Mi Server", "$")
    assert "$caption" in embed.description
    assert "$gif" in embed.description
    assert "!" not in embed.description
