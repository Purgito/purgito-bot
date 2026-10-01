"""Crédito "Enviado por <usuario>" (src/sent_by.py): cuándo se agrega y cuándo
no. Los tests de cada cog (test_download_cog.py, test_imagefx.py,
test_meme_reply_command.py) cubren que cada sitio de subida lo use; acá se
fija la regla en sí, sin depender de ningún comando.
"""

import asyncio
import io
from types import SimpleNamespace

import discord
import pytest

import i18n
from sent_by import reply_with_file, sent_by_credit


class FakeCtx:
    def __init__(self, interaction=None, guild=SimpleNamespace(id=1)):
        self.interaction = interaction
        self.guild = guild
        self.author = SimpleNamespace(id=42, mention="<@42>")
        self.calls: list[dict] = []

    async def reply(self, content=None, **kwargs):
        self.calls.append({"content": content, **kwargs})


def _file():
    return discord.File(io.BytesIO(b"x"), filename="a.png")


def test_por_comando_de_texto_en_un_servidor_lleva_credito():
    ctx = FakeCtx()

    asyncio.run(reply_with_file(ctx, "es", _file()))

    assert len(ctx.calls) == 1
    assert ctx.calls[0]["content"] == i18n.t("general.sent_by", "es", user="<@42>")
    assert ctx.calls[0]["file"] is not None


def test_el_credito_respeta_el_idioma_del_servidor():
    ctx = FakeCtx()

    asyncio.run(reply_with_file(ctx, "en", _file()))

    assert ctx.calls[0]["content"] == "Sent by <@42>"


def test_como_slash_no_lleva_credito():
    # Discord ya pega "<usuario> usó /comando" a la respuesta de un slash.
    ctx = FakeCtx(interaction=SimpleNamespace())

    asyncio.run(reply_with_file(ctx, "es", _file()))

    assert ctx.calls[0]["content"] is None
    assert "allowed_mentions" not in ctx.calls[0]


def test_en_un_dm_no_lleva_credito():
    ctx = FakeCtx(guild=None)

    asyncio.run(reply_with_file(ctx, "es", _file()))

    assert ctx.calls[0]["content"] is None
    assert "allowed_mentions" not in ctx.calls[0]


def test_el_credito_no_suma_pings_pero_conserva_el_del_reply():
    # Quien pidió el archivo ya recibe el ping del reply: la mención del texto
    # no debe sumar otro, ni abrir la puerta a pings de everyone/roles.
    kwargs = sent_by_credit("es", SimpleNamespace(mention="<@42>"))

    assert kwargs["allowed_mentions"].to_dict() == {
        "replied_user": True,
        "parse": [],
    }


@pytest.mark.parametrize("lang", ["es", "en"])
def test_la_clave_existe_en_los_dos_idiomas(lang):
    text = i18n.t("general.sent_by", lang, user="<@1>")

    assert "<@1>" in text
    assert text != "general.sent_by"
