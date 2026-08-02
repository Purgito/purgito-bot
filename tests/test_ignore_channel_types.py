"""El selector de canales a ignorar tiene que ofrecer también los de anuncios.

Discord filtra el menú por `channel_types`: si `news` no está en la lista, un
canal de anuncios no aparece y no hay forma de excluirlo del corpus, aunque el
bot sí aprenda de él (discord.py los modela como TextChannel).

No arranca el bot ni toca la DB: `build_items` solo lee `panel.locale` para
armar los componentes; los awaits a la DB viven dentro de los callbacks.
"""

import asyncio
from types import SimpleNamespace

import discord

from cogs.settings import CorpusCategory


def _items():
    panel = SimpleNamespace(locale="es", guild=SimpleNamespace(id=1))
    return asyncio.run(CorpusCategory().build_items(panel))


def test_ignore_select_offers_text_and_announcement_channels():
    select = next(i for i in _items() if isinstance(i, discord.ui.ChannelSelect))
    assert set(select.channel_types) == {
        discord.ChannelType.text,
        discord.ChannelType.news,
    }, select.channel_types
