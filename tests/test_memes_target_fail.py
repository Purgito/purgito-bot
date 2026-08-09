"""Tests del feedback de la reacción 🎯 (cogs/memes.py, on_raw_reaction_add).

Verifican que cada causa de fallo reacciona con ❌ y explica la razón correcta
por DM, y que un DM rechazado (Forbidden, DMs cerrados) no se loguea como
error. isinstance(channel, discord.TextChannel) se satisface parcheando
discord.TextChannel por la clase fake durante el test (monkeypatch lo restaura).
"""

import asyncio
import io
import logging
from types import SimpleNamespace

import discord
import pytest
from PIL import Image

import cogs.memes as memes_mod
from cogs.memes import Memes
from config import MEME_MAX_BYTES


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(buf, format="PNG")
    return buf.getvalue()


class FakeUser:
    def __init__(self, forbid_dm=False):
        self.sent: list[str] = []
        self.forbid_dm = forbid_dm

    async def send(self, text):
        if self.forbid_dm:
            raise discord.Forbidden(
                SimpleNamespace(status=403, reason="Forbidden"), "DMs cerrados"
            )
        self.sent.append(text)


class FakeChannel:
    def __init__(self, message):
        self._message = message

    async def fetch_message(self, message_id):
        return self._message


class FakeMessage:
    def __init__(self, attachments):
        self.id = 1
        self.author = SimpleNamespace(bot=False)
        self.attachments = attachments
        self.reactions: list[str] = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


def _att(filename, size=100, content=None):
    att = SimpleNamespace(filename=filename, size=size, url=f"http://cdn/{filename}")

    async def read():
        return content if content is not None else _png_bytes()

    att.read = read
    return att


def _payload():
    return SimpleNamespace(
        emoji="🎯", guild_id=1, channel_id=10, message_id=99, user_id=5
    )


@pytest.fixture
def setup(monkeypatch):
    """Arma el cog con todo parcheado. Retorna (cog, message, user) por caso."""

    def make(attachments, premium=True, duplicate=False, forbid_dm=False):
        message = FakeMessage(attachments)
        user = FakeUser(forbid_dm=forbid_dm)
        channel = FakeChannel(message)
        monkeypatch.setattr(memes_mod.discord, "TextChannel", FakeChannel)
        monkeypatch.setattr(memes_mod, "is_premium_guild", lambda gid: premium)
        monkeypatch.setattr(memes_mod, "r2", SimpleNamespace(available=lambda: False))

        async def fake_guild_locale(guild_id):
            return "es"

        monkeypatch.setattr(memes_mod, "guild_locale", fake_guild_locale)

        async def fake_save(guild_id, url):
            return not duplicate

        monkeypatch.setattr(memes_mod, "save_image_url", fake_save)
        bot = SimpleNamespace(
            get_channel=lambda cid: channel,
            get_user=lambda uid: user,
        )
        return Memes(bot), message, user

    return make


def _run(cog):
    asyncio.run(cog.on_raw_reaction_add(_payload()))


def test_non_premium_reacts_and_dms(setup):
    cog, message, user = setup([], premium=False)
    _run(cog)
    assert message.reactions == ["❌"]
    assert len(user.sent) == 1 and "premium" in user.sent[0]


def test_no_image_attachment(setup):
    cog, message, user = setup([])
    _run(cog)
    assert message.reactions == ["❌"]
    assert "ninguna imagen adjunta" in user.sent[0]


def test_unsupported_extension(setup):
    cog, message, user = setup([_att("nota.txt")])
    _run(cog)
    assert message.reactions == ["❌"]
    assert "formato no es compatible" in user.sent[0]


def test_oversized_image(setup):
    cog, message, user = setup([_att("foto.png", size=MEME_MAX_BYTES + 1)])
    _run(cog)
    assert message.reactions == ["❌"]
    assert "supera el límite" in user.sent[0]


def test_duplicate_image(setup):
    cog, message, user = setup([_att("foto.png")], duplicate=True)
    _run(cog)
    assert message.reactions == ["❌"]
    assert "ya estaba en el pool" in user.sent[0]


def test_fake_image_content_rejected(setup):
    # Extensión válida pero el contenido no es una imagen real (magic bytes):
    # debe rechazarse igual que un formato no soportado, no colarse al pool.
    cog, message, user = setup([_att("foto.png", content=b"esto no es un png")])
    _run(cog)
    assert message.reactions == ["❌"]
    assert "formato no es compatible" in user.sent[0]


def test_valid_image_reacts_ok(setup):
    # Contraste: una imagen válida y nueva sigue recibiendo ✅, sin DM.
    cog, message, user = setup([_att("foto.png")])
    _run(cog)
    assert message.reactions == ["✅"]
    assert user.sent == []


def test_dm_forbidden_is_silent(setup, caplog):
    cog, message, user = setup([], forbid_dm=True)
    with caplog.at_level(logging.DEBUG, logger="cogs.memes"):
        _run(cog)  # no debe propagar la Forbidden
    assert message.reactions == ["❌"]  # la señal mínima sale igual
    # DMs cerrados es un caso esperado: nada de warning/error en el log.
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
