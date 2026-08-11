"""Auditoría de voz/tono, ronda 3: /generar, /imitar, /refeed, /refeed_channels
y /corpus_info tenían sus respuestas hardcodeadas en español directo en vez de
pasar por i18n.t(), pese a que ya existían claves equivalentes en el JSON --
ignoraban por completo el idioma configurado del servidor. Este test cubre
el caso más simple (/corpus_info) para confirmar que ahora sí lo respetan.
"""

import asyncio
from types import SimpleNamespace

import cogs.chat as chat_mod
from cogs.chat import Chat


class FakeInteraction:
    def __init__(self, guild_id=1, channel_id=10):
        self.guild = SimpleNamespace(id=guild_id)
        self.channel = SimpleNamespace(id=channel_id)
        self.sent: list[str] = []

        async def _send_message(text, **kwargs):
            self.sent.append(text)

        self.response = SimpleNamespace(send_message=_send_message)


def test_corpus_info_respeta_el_idioma_configurado_del_servidor(monkeypatch):
    async def fake_locale(guild_id):
        return "en"

    async def fake_count(guild_id, channel_id):
        return 5

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale)
    monkeypatch.setattr(chat_mod, "count_corpus_messages", fake_count)

    cog = Chat(SimpleNamespace())
    inter = FakeInteraction()
    asyncio.run(cog.corpus_info.callback(cog, inter))

    assert inter.sent == [
        "📊 This channel's corpus has 5 messages.\n"
        "⚠️ Needs at least 50 messages to generate well."
    ]
