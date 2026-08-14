"""Tests de integración para frase_probability=100% con fallback explicativo.

Cubre:
1. 100% + frase disponible → devuelve frase, no Markov.
2. 100% + sin frases → responde con aviso explicativo de no_phrases (no Markov).
3. 100% + cooldown → responde con aviso explicativo de cooldown (no Markov).
4. 100% + canal no permitido → responde con aviso explicativo de channel_not_allowed (no Markov).
5. 50% intermedio → cae a Markov si la frase no está disponible.
6. 0% → nunca intenta frase y genera Markov.
7. Throttling de fallbacks en menciones → avisa una vez, luego guarda silencio.
8. /generar con 100% sin frases → siempre emite el aviso completo.
9. Generación espontánea con 100% sin frases → guarda silencio y no envía nada.
"""

import asyncio
import itertools
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import db
import generation
import i18n
import cogs.chat as chat_mod
from cogs.chat import Chat
from config import get_dashboard_url

BOT_ID = 999
_msg_seq = itertools.count(100)


class FakeMessage:
    def __init__(self, mention=True, guild_id=1, channel_id=10, content="hola"):
        self.id = next(_msg_seq)
        self.author = SimpleNamespace(
            bot=False,
            id=5,
            display_name="user",
            mention="<@5>",
            roles=[],
        )
        self.guild = SimpleNamespace(id=guild_id, name="Guild")
        self.channel_sent: list[str] = []
        self.channel = SimpleNamespace(
            id=channel_id,
            send=self._channel_send,
            name="canal",
            mention=f"<#{channel_id}>",
        )
        self.content = content + (f" <@{BOT_ID}>" if mention else "")
        self.raw_mentions = [BOT_ID] if mention else []
        self.reference = None
        self.replies: list[str] = []
        self.reactions: list[str] = []

    async def _channel_send(self, text, **kwargs):
        self.channel_sent.append(text)

    async def reply(self, text, **kwargs):
        self.replies.append(text)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


class FakeInteraction:
    def __init__(self, guild_id=1, channel_id=10):
        self.guild = SimpleNamespace(id=guild_id, name="Guild")
        self.user = SimpleNamespace(id=5, display_name="user", mention="<@5>")
        self.channel = SimpleNamespace(
            id=channel_id, name="canal", mention=f"<#{channel_id}>"
        )
        self.response = SimpleNamespace(
            defer=AsyncMock(),
            send_message=AsyncMock(),
        )
        self.followup_sent: list[str] = []
        self.followup = SimpleNamespace(send=self._followup_send)

    async def _followup_send(self, text, **kwargs):
        self.followup_sent.append(text)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


@pytest.fixture
def chat_cog(temp_db, monkeypatch):
    bot = SimpleNamespace(user=SimpleNamespace(id=BOT_ID))
    cog = Chat(bot)

    generation._special_phrase_cooldowns.clear()
    generation._empty_frase_cooldowns.clear()
    generation._empty_reply_cooldowns.clear()

    async def _fake_i18n(guild_id):
        return "es"

    monkeypatch.setattr(i18n, "guild_locale", _fake_i18n)

    async def _fake_bump(guild_id, name, by=1):
        pass

    async def _fake_save(guild_id, channel_id, author_id, name, text, message_id=None):
        return (False, False)

    monkeypatch.setattr(chat_mod, "save_corpus_and_user_message", _fake_save)

    return cog


def test_mencion_100_con_frase_disponible_responde_frase(chat_cog, monkeypatch):
    """1. 100% + frase disponible: responde con la frase renderizada, no con Markov."""
    asyncio.run(db.add_frase_especial(1, 1, "u", "frase de prueba"))
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 1.0}))

    markov_mock = AsyncMock(return_value="markov reply")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    msg = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg))

    assert msg.replies == ["frase de prueba"]
    markov_mock.assert_not_called()


def test_mencion_100_sin_frases_emite_fallback_no_phrases(chat_cog, monkeypatch):
    """2. 100% + sin frases en pool: emite fallback explicativo con deep-link, no Markov."""
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 1.0}))

    markov_mock = AsyncMock(return_value="markov reply")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    msg = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg))

    assert len(msg.replies) == 1
    expected_url = get_dashboard_url(1, "es", "chat#contenido")
    assert (
        i18n.t("chat.frase_fallback.no_phrases", "es", url=expected_url)
        in msg.replies[0]
    )
    markov_mock.assert_not_called()


def test_mencion_100_en_cooldown_emite_fallback_cooldown(chat_cog, monkeypatch):
    """3. 100% + cooldown activo: emite fallback explicativo de cooldown, no Markov."""
    asyncio.run(db.add_frase_especial(1, 1, "u", "frase de prueba"))
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 1.0}))

    monkeypatch.setattr(generation.time, "monotonic", lambda: 10_000.0)

    markov_mock = AsyncMock(return_value="markov reply")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    # Primer mensaje: sale la frase
    msg1 = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg1))
    assert msg1.replies == ["frase de prueba"]

    # Segundo mensaje en cooldown: fallback de cooldown
    msg2 = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg2))
    assert len(msg2.replies) == 1
    assert i18n.t("chat.frase_fallback.cooldown", "es") in msg2.replies[0]
    markov_mock.assert_not_called()


def test_mencion_100_canal_no_permitido_emite_fallback_channel_not_allowed(
    chat_cog, monkeypatch
):
    """4. 100% + canal fuera de whitelist: emite fallback channel_not_allowed."""
    asyncio.run(db.add_frase_especial(1, 1, "u", "frase de prueba"))
    asyncio.run(db.add_frase_channel(1, 20))  # solo canal 20
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 1.0}))

    markov_mock = AsyncMock(return_value="markov reply")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    msg = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg))

    assert len(msg.replies) == 1
    expected_url = get_dashboard_url(1, "es", "chat#canales")
    assert (
        i18n.t("chat.frase_fallback.channel_not_allowed", "es", url=expected_url)
        in msg.replies[0]
    )
    markov_mock.assert_not_called()


def test_mencion_50_intermedio_cae_a_markov(chat_cog, monkeypatch):
    """5. 50% intermedio: si no hay frases disponibles, cae a Markov normalmente."""
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 0.5}))

    async def fake_markov(guild_id, **kwargs):
        return "markov respuesta"

    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)

    msg = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg))

    assert msg.replies == ["markov respuesta"]


def test_mencion_0_siempre_genera_markov(chat_cog, monkeypatch):
    """6. 0%: nunca intenta frases y genera Markov directamente."""
    asyncio.run(db.add_frase_especial(1, 1, "u", "frase de prueba"))
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 0.0}))

    async def fake_markov(guild_id, **kwargs):
        return "markov siempre"

    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)

    msg = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg))

    assert msg.replies == ["markov siempre"]


def test_mencion_fallback_throttled_evita_spam(chat_cog):
    """7. Múltiples menciones consecutivas con 100% sin frase: avisa la primera vez y luego guarda silencio."""
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 1.0}))

    # Primera mención: avisa
    msg1 = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg1))
    assert len(msg1.replies) == 1
    assert "No tengo ninguna frase" in msg1.replies[0]

    # Segunda mención: silenciado por throttle para no spamear el canal
    msg2 = FakeMessage(mention=True, guild_id=1, channel_id=10)
    asyncio.run(chat_cog.on_message(msg2))
    assert msg2.replies == []


def test_generar_slash_command_100_sin_frases_siempre_explica(chat_cog):
    """8. /generar con 100% sin frases: siempre explica el motivo sin ser throttled."""
    asyncio.run(db.set_channel_tunables(1, 10, {"frase_probability": 1.0}))

    interaction = FakeInteraction(guild_id=1, channel_id=10)
    asyncio.run(chat_cog.generar.callback(chat_cog, interaction))

    assert len(interaction.followup_sent) == 1
    assert "No tengo ninguna frase configurada" in interaction.followup_sent[0]


def test_spontaneous_generation_100_sin_frases_guarda_silencio(chat_cog, monkeypatch):
    """9. Generación espontánea con 100% sin frases: no envía nada ni spamea el chat."""
    asyncio.run(
        db.set_channel_tunables(
            1,
            10,
            {
                "frase_probability": 1.0,
                "auto_generate_probability": 1.0,
                "auto_generate_every": 1,
            },
        )
    )

    markov_mock = AsyncMock(return_value="markov spontaneous")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)
    monkeypatch.setattr(chat_mod, "_check_spontaneous_cooldown", lambda g, c: True)

    msg = FakeMessage(mention=False, guild_id=1, channel_id=10, content="hola grupo")
    asyncio.run(chat_cog.on_message(msg))

    assert msg.channel_sent == []
    assert msg.replies == []
    markov_mock.assert_not_called()
