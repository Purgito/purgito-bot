"""Meme por respuesta (cogs/memes.py:handle_meme_command): "purgito generar"
respondiendo a un mensaje con una imagen. El bot vuelve a subir esa imagen con
un caption como mensaje nuevo, así que si borran el comando no queda rastro de
quién lo pidió -- el mensaje del bot lleva "Enviado por <usuario>" (ver
src/sent_by.py). Los avisos de error, en cambio, no se atribuyen.

Mockea todo lo que toca red, Groq, la DB y Pillow: solo interesa qué se manda.
"""

import asyncio
from types import SimpleNamespace

import pytest

import cogs.memes as memes_mod
import i18n


class FakeRef:
    """Hace pasar isinstance(ref, discord.Message) -- ver fake_discord_message."""

    def __init__(self, attachments):
        self.id = 2
        self.attachments = attachments


class FakeMessage:
    def __init__(self, ref):
        self.id = 1
        self.content = "purgito generar"
        self.author = SimpleNamespace(id=7, mention="<@7>", bot=False)
        self.guild = SimpleNamespace(id=1)
        self.reference = SimpleNamespace(message_id=2, resolved=ref)
        self.channel = SimpleNamespace()
        self.replies: list[dict] = []

    async def reply(self, content=None, **kwargs):
        self.replies.append({"content": content, **kwargs})


def _image_attachment():
    async def read():
        return b"png-bytes"

    return SimpleNamespace(filename="foto.png", size=100, read=read)


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    async def fake_locale(guild_id):
        return "es"

    async def fake_markov(guild_id):
        return SimpleNamespace(is_empty=False)

    monkeypatch.setattr(memes_mod, "guild_locale", fake_locale)
    monkeypatch.setattr(memes_mod, "is_premium_guild", lambda guild_id: True)
    monkeypatch.setattr(memes_mod, "_check_meme_cooldown", lambda g, u: None)
    monkeypatch.setattr(memes_mod, "_groq_client", None)
    monkeypatch.setattr(memes_mod, "build_markov_model", fake_markov)
    monkeypatch.setattr(memes_mod, "_try_short_sentence", lambda model: "hola")
    monkeypatch.setattr(memes_mod, "render_caption", lambda img, text: b"meme-bytes")
    # handle_meme_command exige isinstance(ref, discord.Message).
    monkeypatch.setattr(memes_mod.discord, "Message", FakeRef)


def test_meme_por_respuesta_firma_quien_lo_pidio():
    message = FakeMessage(FakeRef([_image_attachment()]))

    asyncio.run(memes_mod.handle_meme_command(message))

    assert len(message.replies) == 1
    reply = message.replies[0]
    assert reply["file"].filename == "meme.png"
    assert reply["content"] == i18n.t("general.sent_by", "es", user="<@7>")


def test_meme_por_respuesta_firma_sin_ping_extra_pero_conserva_el_del_reply():
    message = FakeMessage(FakeRef([_image_attachment()]))

    asyncio.run(memes_mod.handle_meme_command(message))

    mentions = message.replies[0]["allowed_mentions"]
    assert mentions.to_dict() == {"replied_user": True, "parse": []}


def test_meme_por_respuesta_no_firma_los_avisos_de_error(monkeypatch):
    # Sin ningún texto para el meme no se sube nada: el aviso no es contenido
    # que haya que atribuir.
    async def no_model(guild_id):
        return None

    monkeypatch.setattr(memes_mod, "build_markov_model", no_model)
    message = FakeMessage(FakeRef([_image_attachment()]))

    asyncio.run(memes_mod.handle_meme_command(message))

    assert message.replies == [{"content": i18n.t("memes.caption_missing", "es")}]
