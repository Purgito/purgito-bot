"""Tests del matching y ejecución de triggers en cogs/chat.py (Fase 4).

La pieza más delicada es el timeout real del regex: un patrón con
backtracking catastrófico corriendo con `re` de stdlib nunca vuelve (lo
confirmamos a mano: >5s y hay que matar el proceso). Acá se prueba contra
el mismo patrón que se validó manualmente que sí cuelga a `re`, para
demostrar que _regex_search_with_timeout corta de verdad y no por
casualidad de que el patrón sea manejable.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

import cogs.chat as chat_mod
from cogs.chat import Chat

BOT_ID = 999


# ─── _trigger_matches ────────────────────────────────────────────────────────


def test_exact_es_case_insensitive():
    trigger = {"match_type": "exact", "pattern": "Hola Mundo"}
    assert asyncio.run(chat_mod._trigger_matches(trigger, "hola mundo")) is True
    assert asyncio.run(chat_mod._trigger_matches(trigger, "hola mundo extra")) is False


def test_starts_with_es_case_insensitive():
    trigger = {"match_type": "starts_with", "pattern": "!ban"}
    assert asyncio.run(chat_mod._trigger_matches(trigger, "!BAN a alguien")) is True
    assert asyncio.run(chat_mod._trigger_matches(trigger, "no empieza así")) is False


def test_regex_matchea_en_cualquier_parte_del_mensaje():
    trigger = {"match_type": "regex", "pattern": r"\bhola\b"}
    assert asyncio.run(chat_mod._trigger_matches(trigger, "che hola qué tal")) is True
    assert asyncio.run(chat_mod._trigger_matches(trigger, "holamundo")) is False


# ─── Timeout real del regex catastrófico ─────────────────────────────────────


def test_regex_catastrofico_no_cuelga_gracias_al_timeout():
    """Mismo patrón que se confirmó a mano que cuelga `re` de stdlib más de
    5 segundos (backtracking exponencial de alternancia ambigua). Acá tiene
    que volver False bien por debajo de eso -- el timeout de _TRIGGER_
    REGEX_TIMEOUT (0.5s) es lo que corta, no que el patrón sea manejable."""
    pattern = r"^(a|a)+$"
    content = "a" * 40 + "X"

    start = time.monotonic()
    result = chat_mod._regex_search_with_timeout(pattern, content)
    elapsed = time.monotonic() - start

    assert result is False
    assert elapsed < 2.0


def test_regex_invalido_no_rompe_el_matching():
    assert chat_mod._regex_search_with_timeout("(", "cualquier cosa") is False


def test_trigger_matches_regex_corre_en_un_hilo_aparte(monkeypatch):
    """No debe llamar a regex.search en el hilo del event loop: tiene que
    pasar por asyncio.to_thread (ver _trigger_matches)."""
    calls = []

    async def fake_to_thread(fn, *args):
        calls.append((fn, args))
        return fn(*args)

    monkeypatch.setattr(chat_mod.asyncio, "to_thread", fake_to_thread)
    trigger = {"match_type": "regex", "pattern": "hola"}

    asyncio.run(chat_mod._trigger_matches(trigger, "hola"))

    assert calls and calls[0][0] is chat_mod._regex_search_with_timeout


# ─── _handle_trigger / _run_trigger_action ───────────────────────────────────


class FakeMessage:
    def __init__(self, content, channel_id=10, guild_id=1):
        self.content = content
        self.guild = SimpleNamespace(id=guild_id, name="Guild")
        self.channel = SimpleNamespace(
            id=channel_id, send=self._send, name="canal", mention=f"<#{channel_id}>"
        )
        self.author = SimpleNamespace(mention="<@5>", display_name="user")
        self.sent: list[str] = []

    async def _send(self, text):
        self.sent.append(text)


@pytest.fixture
def chat_cog():
    return Chat(SimpleNamespace(user=SimpleNamespace(id=BOT_ID)))


_SETTINGS = {"frase_probability": 0.0}


def test_sin_triggers_configurados_no_hace_nada(chat_cog, monkeypatch):
    async def fake_list(guild_id, channel_id):
        return []

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_list)

    handled = asyncio.run(chat_cog._handle_trigger(FakeMessage("hola"), _SETTINGS))
    assert handled is False


def test_primer_trigger_que_matchea_gana_no_se_prueban_los_demas(chat_cog, monkeypatch):
    async def fake_list(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "markov",
                "pack_id": None,
            },
            {
                "id": 2,
                "match_type": "starts_with",
                "pattern": "h",
                "action": "frase_de_pack",
                "pack_id": None,
            },
        ]

    async def fake_markov(guild_id):
        return "respuesta markov"

    async def fail_if_called(*a, **k):
        raise AssertionError("no debería probarse el segundo trigger")

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_list)
    monkeypatch.setattr(chat_mod.generation, "generate_markov_reply", fake_markov)
    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fail_if_called)
    monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)
    monkeypatch.setattr(chat_mod, "_trigger_markov_cooldowns", chat_mod.LRUDict(64))

    message = FakeMessage("hola")
    handled = asyncio.run(chat_cog._handle_trigger(message, _SETTINGS))

    assert handled is True
    assert message.sent == ["respuesta markov"]


def test_action_markov_respeta_el_cooldown_por_canal(chat_cog, monkeypatch):
    """Sin esto, cualquier miembro del canal (no solo el admin que configuró
    el trigger) puede spamear el patrón en loop y forzar generación real de
    Markov sin ningún freno -- Sección 8 de la auditoría de seguridad."""

    async def fake_list(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "markov",
                "pack_id": None,
            }
        ]

    calls = []

    async def fake_markov(guild_id):
        calls.append(guild_id)
        return "respuesta markov"

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_list)
    monkeypatch.setattr(chat_mod.generation, "generate_markov_reply", fake_markov)
    monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)
    monkeypatch.setattr(chat_mod, "_trigger_markov_cooldowns", chat_mod.LRUDict(64))

    message = FakeMessage("hola")
    first = asyncio.run(chat_cog._handle_trigger(message, _SETTINGS))
    second = asyncio.run(chat_cog._handle_trigger(FakeMessage("hola"), _SETTINGS))

    assert first is True
    assert second is False
    assert calls == [1]


def test_action_frase_de_pack_manda_una_frase_del_pack(chat_cog, monkeypatch):
    async def fake_list(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "frase_de_pack",
                "pack_id": 5,
            }
        ]

    async def fake_frase(guild_id, pack_id):
        assert pack_id == 5
        return "frase del pack"

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_list)
    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)
    monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

    message = FakeMessage("hola")
    handled = asyncio.run(chat_cog._handle_trigger(message, _SETTINGS))

    assert handled is True
    assert message.sent == ["frase del pack"]


def test_action_frase_de_pack_sin_frases_no_manda_nada(chat_cog, monkeypatch):
    async def fake_list(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "frase_de_pack",
                "pack_id": 5,
            }
        ]

    async def fake_frase(guild_id, pack_id):
        return None

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_list)
    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)

    message = FakeMessage("hola")
    handled = asyncio.run(chat_cog._handle_trigger(message, _SETTINGS))

    assert handled is False
    assert message.sent == []


def test_action_mezcla_usa_el_pack_del_trigger_no_el_del_canal(chat_cog, monkeypatch):
    async def fake_list(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "mezcla",
                "pack_id": 7,
            }
        ]

    async def fake_frase(guild_id, pack_id):
        assert pack_id == 7
        return "frase del trigger"

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_list)
    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)
    monkeypatch.setattr(chat_mod, "random", SimpleNamespace(random=lambda: 0.0))
    monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

    message = FakeMessage("hola")
    handled = asyncio.run(chat_cog._handle_trigger(message, {"frase_probability": 1.0}))

    assert handled is True
    assert message.sent == ["frase del trigger"]


def test_action_mezcla_no_respeta_el_cooldown_de_frases_espontaneas(
    chat_cog, monkeypatch
):
    """El cooldown de 40 min es para las apariciones espontáneas, no para
    una regla explícita del admin -- un trigger 'mezcla' tiene que poder
    disparar la parte de frase aunque el cooldown global esté activo."""
    chat_mod.generation._special_phrase_cooldowns[1] = (
        chat_mod.generation.time.monotonic()
    )

    async def fake_list(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "mezcla",
                "pack_id": None,
            }
        ]

    async def fake_frase(guild_id, pack_id):
        return "frase pese al cooldown"

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_list)
    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)
    monkeypatch.setattr(chat_mod, "random", SimpleNamespace(random=lambda: 0.0))
    monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

    message = FakeMessage("hola")
    handled = asyncio.run(chat_cog._handle_trigger(message, {"frase_probability": 1.0}))

    assert handled is True
    assert message.sent == ["frase pese al cooldown"]
    chat_mod.generation._special_phrase_cooldowns.clear()


async def _noop_counter(guild_id, name, by=1):
    return None
