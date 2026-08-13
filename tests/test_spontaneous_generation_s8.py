"""Tests de generación espontánea y protección del recurso compartido (S8).

Cubre:
- probability=1.0 explícito (siempre dispara al cumplir every).
- Contador every=1 (reseteo y avance).
- Cooldown por canal (45 s).
- Corpus insuficiente (<50 mensajes) mantiene silencio sin romper.
- Canal no permitido en corpus o spontaneous_channels.
- Límite global de concurrencia (MarkovConcurrencyLimiter / S8).
- Múltiples guilds/canales concurrentes: descarte inmediato sin saturar executor.
- Tareas descartadas no quedan encoladas en asyncio.to_thread / executor.
- Caso end-to-end perfecto (every=1, prob=1.0, corpus>=50, canales ok, sin cooldown).
"""

import asyncio
import itertools
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import cogs.chat as chat_mod
from cogs.chat import Chat
import generation
from markov_engine import SimpleMarkov

_next_msg_id = itertools.count(1000)


class FakeChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.name = f"channel-{channel_id}"
        self.mention = f"<#{channel_id}>"
        self.sent: list[str] = []

    async def send(self, content, **kwargs):
        self.sent.append(content)


class FakeMessage:
    def __init__(
        self,
        guild_id: int = 1,
        channel_id: int = 10,
        content: str = "mensaje de prueba",
    ):
        self.id = next(_next_msg_id)
        self.author = SimpleNamespace(
            bot=False,
            id=42,
            display_name="tester",
            mention="<@42>",
            roles=[],
        )
        self.guild = SimpleNamespace(id=guild_id, name="Test Guild")
        self.channel = FakeChannel(channel_id)
        self.content = content
        self.raw_mentions = []
        self.reference = None
        self.replies: list[str] = []
        self.reactions: list[str] = []

    async def reply(self, text, **kwargs):
        self.replies.append(text)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


@pytest.fixture(autouse=True)
def clean_state():
    """Limpia caches y cooldowns entre tests."""
    chat_mod._spontaneous_cooldowns.clear()
    chat_mod._recent_message_ids.clear()
    generation._message_counter.clear()
    generation._channel_activity.clear()
    generation._markov_cache.clear()
    generation._corpus_insert_counter.clear()


# ─── 1. Tests de probabilidad y contador ─────────────────────────────────────


def test_probability_1_0_dispara_siempre():
    """Con probability=1.0 configurado, note_message_for_auto_generate retorna True."""
    for _ in range(20):
        res = generation.note_message_for_auto_generate(
            guild_id=1, channel_id=10, every=1, probability=1.0
        )
        assert res is True


def test_every_contador_avanza_y_resetea():
    """Con every=3, devuelve False en mensaje 1 y 2, y True en el mensaje 3."""
    res1 = generation.note_message_for_auto_generate(
        guild_id=1, channel_id=10, every=3, probability=1.0
    )
    assert res1 is False

    res2 = generation.note_message_for_auto_generate(
        guild_id=1, channel_id=10, every=3, probability=1.0
    )
    assert res2 is False

    res3 = generation.note_message_for_auto_generate(
        guild_id=1, channel_id=10, every=3, probability=1.0
    )
    assert res3 is True

    # El siguiente vuelve a empezar
    res4 = generation.note_message_for_auto_generate(
        guild_id=1, channel_id=10, every=3, probability=1.0
    )
    assert res4 is False


# ─── 2. Tests de Cooldown por Canal (45 s) ───────────────────────────────────


def test_cooldown_por_canal_frena_segundo_mensaje_inmediato(monkeypatch):
    """Primer check pasa; segundo check antes de 45s es bloqueado."""
    t0 = 1000.0
    monkeypatch.setattr(chat_mod.time, "monotonic", lambda: t0)

    assert chat_mod._check_spontaneous_cooldown(guild_id=1, channel_id=10) is True

    # 10 segundos después en el mismo canal -> bloqueado
    monkeypatch.setattr(chat_mod.time, "monotonic", lambda: t0 + 10.0)
    assert chat_mod._check_spontaneous_cooldown(guild_id=1, channel_id=10) is False

    # 46 segundos después en el mismo canal -> permitido
    monkeypatch.setattr(chat_mod.time, "monotonic", lambda: t0 + 46.0)
    assert chat_mod._check_spontaneous_cooldown(guild_id=1, channel_id=10) is True


def test_cooldown_es_por_canal_independiente(monkeypatch):
    """Canal 10 habla; canal 20 puede hablar de inmediato sin esperar 45s."""
    t0 = 1000.0
    monkeypatch.setattr(chat_mod.time, "monotonic", lambda: t0)

    assert chat_mod._check_spontaneous_cooldown(guild_id=1, channel_id=10) is True
    assert chat_mod._check_spontaneous_cooldown(guild_id=1, channel_id=20) is True


# ─── 3. Tests de Semáforo y Concurrencia Global (S8) ──────────────────────────


def test_markov_concurrency_limiter_slots():
    """El limiter permite hasta max_concurrent y rechaza de inmediato con wait=False."""

    async def run():
        limiter = generation.MarkovConcurrencyLimiter(max_concurrent=2)

        async with limiter.slot(wait=False) as ok1:
            assert ok1 is True
            async with limiter.slot(wait=False) as ok2:
                assert ok2 is True
                # Tercer intento con wait=False: rechazado inmediatamente sin bloquear
                async with limiter.slot(wait=False) as ok3:
                    assert ok3 is False

            # Al salir de slot 2, slot 4 puede adquirir
            async with limiter.slot(wait=False) as ok4:
                assert ok4 is True

    asyncio.run(run())


def test_markov_concurrency_limiter_wait_true():
    """Con wait=True (comandos explícitos), espera hasta que haya slot disponible."""

    async def run():
        limiter = generation.MarkovConcurrencyLimiter(max_concurrent=1)
        order = []

        async def task_holder():
            async with limiter.slot(wait=False) as ok:
                assert ok is True
                order.append("holder_started")
                await asyncio.sleep(0.05)
                order.append("holder_finished")

        async def task_waiter():
            await asyncio.sleep(0.01)
            async with limiter.slot(wait=True) as ok:
                assert ok is True
                order.append("waiter_acquired")

        await asyncio.gather(task_holder(), task_waiter())
        assert order == ["holder_started", "holder_finished", "waiter_acquired"]

    asyncio.run(run())


def test_spontaneous_discarded_when_limiter_full_does_not_queue(monkeypatch):
    """Si el limiter está lleno, generate_response(wait=False) retorna None inmediatamente
    sin llamar a to_thread ni build_markov_model."""

    async def run():
        # Ocupamos todos los slots del markov_limiter global
        sem = generation.markov_limiter._get_sem()
        sem._value = 0  # simular que está 100% saturado

        mock_build = AsyncMock()
        monkeypatch.setattr(generation, "build_markov_model", mock_build)

        text, is_special = await generation.generate_response(
            guild_id=1, channel_id=10, special_phrase_probability=0.0, wait=False
        )
        assert text is None
        assert is_special is False
        # Verificamos que jamás se llamó a build_markov_model ni se despachó trabajo
        mock_build.assert_not_called()

        # Restaurar semáforo
        sem._value = generation._MAX_CONCURRENT_MARKOV_TASKS

    asyncio.run(run())


def test_multiples_guilds_generando_simultaneamente(monkeypatch):
    """10 llamadas simultáneas con wait=False bajo max_concurrent=4:
    exactamente 4 adquieren y 6 se descartan inmediatamente."""

    async def run():
        limiter = generation.MarkovConcurrencyLimiter(max_concurrent=4)
        monkeypatch.setattr(generation, "markov_limiter", limiter)

        acquired_count = 0
        discarded_count = 0

        async def fake_worker(guild_id: int):
            nonlocal acquired_count, discarded_count
            async with limiter.slot(wait=False) as ok:
                if ok:
                    acquired_count += 1
                    await asyncio.sleep(0.05)
                else:
                    discarded_count += 1

        tasks = [fake_worker(i) for i in range(10)]
        await asyncio.gather(*tasks)

        assert acquired_count == 4
        assert discarded_count == 6

    asyncio.run(run())


# ─── 4. Tests de Gating de Generación y End-to-End ───────────────────────────


def test_corpus_insuficiente_mantiene_silencio(monkeypatch):
    """Con menos de 50 mensajes en el corpus, generate_response retorna None y no manda nada."""

    async def run():
        monkeypatch.setattr(
            generation,
            "get_corpus_messages",
            AsyncMock(return_value=["hola"] * 20),
        )
        text, is_special = await generation.generate_response(
            guild_id=1,
            channel_id=10,
            special_phrase_probability=0.0,
            wait=False,
        )
        assert text is None
        assert is_special is False

    asyncio.run(run())


def test_canal_no_permitido_en_corpus_no_cuenta_ni_genera(monkeypatch):
    """Si el canal no está en corpus_allowed_channels, no entra al corpus ni genera."""

    async def run():
        bot = SimpleNamespace(user=SimpleNamespace(id=999))
        cog = Chat(bot)

        async def fake_effective(*a):
            return {
                "auto_generate_every": 1,
                "auto_generate_probability": 1.0,
                "reaction_probability": 0.0,
                "gif_response_probability": 0.0,
                "frase_probability": 0.0,
                "mention_rate_limit": 0,
            }

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(
            chat_mod, "is_channel_ignored", AsyncMock(return_value=False)
        )
        # NO está permitido en corpus
        monkeypatch.setattr(
            chat_mod, "is_corpus_allowed", AsyncMock(return_value=False)
        )
        save_mock = AsyncMock()
        monkeypatch.setattr(cog, "_save_message_to_corpus", save_mock)

        msg = FakeMessage(guild_id=1, channel_id=10, content="mensaje de usuario")
        await cog._on_message_impl(msg)

        save_mock.assert_not_called()
        assert msg.channel.sent == []

    asyncio.run(run())


def test_canal_no_permitido_en_spontaneous_no_genera(monkeypatch):
    """Si el canal no está en spontaneous_channels, auto_generate=True pero se bloquea."""

    async def run():
        bot = SimpleNamespace(user=SimpleNamespace(id=999))
        cog = Chat(bot)

        async def fake_effective(*a):
            return {
                "auto_generate_every": 1,
                "auto_generate_probability": 1.0,
                "reaction_probability": 0.0,
                "gif_response_probability": 0.0,
                "frase_probability": 0.0,
                "mention_rate_limit": 0,
            }

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(
            chat_mod, "is_channel_ignored", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(chat_mod, "is_corpus_allowed", AsyncMock(return_value=True))
        # Solo canal 99 permitido para espontáneo, mensaje viene de canal 10
        monkeypatch.setattr(
            chat_mod, "list_spontaneous_channels", AsyncMock(return_value=[99])
        )
        monkeypatch.setattr(
            chat_mod,
            "save_corpus_and_user_message",
            AsyncMock(return_value=(True, True)),
        )

        msg = FakeMessage(
            guild_id=1, channel_id=10, content="este es un mensaje de prueba"
        )
        await cog._on_message_impl(msg)

        assert msg.channel.sent == []

    asyncio.run(run())


def test_caso_completo_every_1_prob_1_genera_exitosamente(monkeypatch):
    """Condiciones óptimas:
    every=1, prob=1.0, corpus>=50, canales permitidos, sin cooldown.
    El bot debe enviar respuesta al canal."""

    async def run():
        bot = SimpleNamespace(user=SimpleNamespace(id=999))
        cog = Chat(bot)

        async def fake_effective(*a):
            return {
                "auto_generate_every": 1,
                "auto_generate_probability": 1.0,
                "reaction_probability": 0.0,
                "gif_response_probability": 0.0,
                "frase_probability": 0.0,
                "mention_rate_limit": 0,
            }

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(
            chat_mod, "is_channel_ignored", AsyncMock(return_value=False)
        )
        monkeypatch.setattr(chat_mod, "is_corpus_allowed", AsyncMock(return_value=True))
        monkeypatch.setattr(
            chat_mod, "list_spontaneous_channels", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            chat_mod,
            "save_corpus_and_user_message",
            AsyncMock(return_value=(True, True)),
        )
        monkeypatch.setattr(chat_mod, "bump_counter", AsyncMock())

        # Mock del modelo Markov
        markov = SimpleMarkov()
        markov.add_many(["este es un mensaje de prueba para entrenar markov"] * 50)
        monkeypatch.setattr(
            generation, "build_markov_model", AsyncMock(return_value=markov)
        )

        msg = FakeMessage(
            guild_id=1,
            channel_id=10,
            content="este es un mensaje de prueba normal",
        )
        await cog._on_message_impl(msg)

        assert len(msg.channel.sent) == 1
        assert isinstance(msg.channel.sent[0], str)
        assert len(msg.channel.sent[0]) > 0

    asyncio.run(run())
