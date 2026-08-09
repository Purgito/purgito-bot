"""Test de /vote (cogs/general.py): comando simple sin opciones ni cooldown
que solo manda un embed con el link de voto de top.gg.

Mismo patrón que test_error_handler.py: fake mínimo con SimpleNamespace,
asyncio.run para el flujo async, sin bot ni red.
"""

import asyncio
from types import SimpleNamespace

from cogs.general import VOTE_URL, General


class FakeInteraction:
    def __init__(self):
        self.sent: list[dict] = []

        async def _send_message(**kwargs):
            self.sent.append(kwargs)

        self.response = SimpleNamespace(send_message=_send_message)


def test_vote_responde_con_embed_y_link():
    cog = General(SimpleNamespace())
    inter = FakeInteraction()
    asyncio.run(cog.vote.callback(cog, inter))

    assert len(inter.sent) == 1
    embed = inter.sent[0]["embed"]
    assert VOTE_URL in embed.description
    assert "12 hora" in embed.description
