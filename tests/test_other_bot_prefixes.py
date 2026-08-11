"""Un mensaje que empieza con un prefijo de comando (el propio "!" o uno
típico de otro bot) no debe entrar al corpus ni disparar respuesta, ni
siquiera si de paso menciona a Purgito -- ver OTHER_BOT_PREFIXES en
cogs/chat.py.

Mismo patrón de test que test_chat_muted.py: sin bot ni red, db/i18n
parcheados con monkeypatch, discord.Message simulado con un fake mínimo.
"""

import asyncio
import itertools
from types import SimpleNamespace

import pytest

import cogs.chat as chat_mod
from cogs.chat import Chat, OTHER_BOT_PREFIXES

BOT_ID = 999
_next_message_id = itertools.count(1)


class FakeMessage:
    def __init__(self, content, mention=True, guild_id=1, channel_id=10):
        # IDs únicas de verdad: on_message deduplica por message.id (ver
        # _recent_message_ids en cogs/chat.py).
        self.id = next(_next_message_id)
        self.author = SimpleNamespace(bot=False, id=5, display_name="user", roles=[])
        self.guild = SimpleNamespace(id=guild_id)
        self.channel_sent: list[str] = []
        self.channel = SimpleNamespace(id=channel_id, send=self._channel_send)
        self.content = content + (f" <@{BOT_ID}>" if mention else "")
        self.raw_mentions = [BOT_ID] if mention else []
        self.reference = None
        self.replies: list[str] = []
        self.reactions: list[str] = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def _channel_send(self, text, **kwargs):
        self.channel_sent.append(text)


@pytest.fixture
def cog(monkeypatch):
    chat_mod._muted_reply_cooldowns.clear()
    chat_mod._mention_hits.clear()
    chat_mod._recent_message_ids.clear()
    # random() = 1.0: nunca dispara la reacción aleatoria ni el GIF.
    monkeypatch.setattr(chat_mod, "random", SimpleNamespace(random=lambda: 1.0))

    saved: list[str] = []

    async def fake_save(guild_id, channel_id, author_id, name, text, message_id=None):
        saved.append(text)
        return (True, True)

    async def fake_settings(guild_id, channel_id):
        return {
            "enabled": True,
            "channel_id": None,
            "mention_rate_limit": 0,
            "auto_generate_every": 15,
            "auto_generate_probability": 0.6,
            "reaction_probability": 0.05,
            "gif_response_probability": 0.0,
            "frase_probability": 0.0,
        }

    async def fake_true(*a, **k):
        return True

    async def fake_empty_list(*a, **k):
        return []

    async def fake_generate(guild_id, channel_id, *, special_phrase_probability=None):
        return "respuesta", True

    monkeypatch.setattr(chat_mod, "save_corpus_and_user_message", fake_save)
    monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_settings)
    monkeypatch.setattr(chat_mod, "is_channel_ignored", fake_empty_list)
    monkeypatch.setattr(chat_mod, "is_corpus_allowed", fake_true)
    monkeypatch.setattr(chat_mod, "list_mention_channels", fake_empty_list)
    monkeypatch.setattr(chat_mod, "list_spontaneous_channels", fake_empty_list)
    monkeypatch.setattr(chat_mod, "list_exempt_roles", fake_empty_list)
    monkeypatch.setattr(chat_mod, "list_exempt_channels", fake_empty_list)
    monkeypatch.setattr(chat_mod.generation, "generate_response", fake_generate)

    bot = SimpleNamespace(user=SimpleNamespace(id=BOT_ID))
    return Chat(bot), saved


@pytest.mark.parametrize("prefix", OTHER_BOT_PREFIXES)
def test_mensaje_con_prefijo_de_bot_no_entra_al_corpus_ni_responde(cog, prefix):
    chat, saved = cog

    # Con mención al bot de por medio: igual tiene que quedar mudo.
    m = FakeMessage(f"{prefix}play algo", mention=True)
    asyncio.run(chat.on_message(m))

    assert saved == []
    assert m.replies == []
    assert m.reactions == []
    assert m.channel_sent == []


def test_espacio_inicial_antes_del_prefijo_tambien_se_detecta(cog):
    chat, saved = cog

    m = FakeMessage("   !ban @alguien", mention=False)
    asyncio.run(chat.on_message(m))

    assert saved == []


def test_mensaje_sin_prefijo_se_procesa_normal(cog):
    """Control de regresión: sin esto, un cambio que amplíe demasiado la
    lista rompería la charla real en silencio."""
    chat, saved = cog

    m = FakeMessage("hola a todos", mention=True)
    asyncio.run(chat.on_message(m))

    assert saved == ["hola a todos"]
    assert m.replies == ["respuesta"]


def test_asterisco_de_roleplay_no_se_bloquea(cog):
    """*acción* es charla real (roleplay/énfasis), no un comando -- excluido
    a propósito de OTHER_BOT_PREFIXES (ver el comentario ahí)."""
    chat, saved = cog

    m = FakeMessage("*se ríe*", mention=False)
    asyncio.run(chat.on_message(m))

    assert saved == ["*se ríe*"]
