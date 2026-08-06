"""Tests del playground del dashboard (Fase 7): simulate_message en
cogs/chat.py tiene que reflejar la misma decisión que on_message (triggers,
frase-vs-Markov, templating) pero SIN efectos secundarios reales -- ni
cooldown de frases especiales, ni contadores, ni corpus, ni mandar nada a
Discord. Eso último se prueba explícito: simular no puede alterar el estado
que sí usa el bot de verdad.
"""

import asyncio
from types import SimpleNamespace

import pytest

import cogs.chat as chat_mod
import generation


def _ctx(user_mention="<@5>", chan_name="general", guild_id=1):
    return {
        "author": SimpleNamespace(mention=user_mention, display_name="Ana"),
        "channel": SimpleNamespace(name=chan_name, mention="<#10>"),
        "guild": SimpleNamespace(id=guild_id, name="PURG4TORY"),
    }


def _simulate(content, guild_id=1, channel_id=10, **ctx_overrides):
    ctx = _ctx(guild_id=guild_id, **ctx_overrides)
    return asyncio.run(chat_mod.simulate_message(guild_id, channel_id, content, **ctx))


_SETTINGS = {
    "enabled": True,
    "auto_generate_every": 15,
    "auto_generate_probability": 0.6,
    "reaction_probability": 0.05,
    "gif_response_probability": 0.45,
    "frase_probability": 0.0,
}


def _patch_effective_settings(monkeypatch, **overrides):
    settings = {**_SETTINGS, **overrides}

    async def fake(guild_id, channel_id):
        return settings

    monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake)


def _patch_no_triggers(monkeypatch):
    async def fake(guild_id, channel_id):
        return []

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake)


def _patch_not_ignored(monkeypatch):
    async def fake(guild_id, channel_id):
        return False

    monkeypatch.setattr(chat_mod, "is_channel_ignored", fake)


@pytest.fixture(autouse=True)
def base_patches(monkeypatch):
    _patch_effective_settings(monkeypatch)
    _patch_no_triggers(monkeypatch)
    _patch_not_ignored(monkeypatch)


# ─── Canal ignorado corta todo ────────────────────────────────────────────────


def test_canal_ignorado_no_responde(monkeypatch):
    async def fake_ignored(guild_id, channel_id):
        return True

    monkeypatch.setattr(chat_mod, "is_channel_ignored", fake_ignored)

    result = _simulate("hola")
    assert result == {"would_respond": False, "reason": "canal_ignorado", "text": None}


# ─── Sin triggers: frase vs Markov ────────────────────────────────────────────


def test_sin_corpus_no_responde(monkeypatch):
    async def fake_markov(guild_id):
        return None

    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)

    result = _simulate("hola")
    assert result == {
        "would_respond": False,
        "reason": "sin_corpus_suficiente",
        "text": None,
    }


def test_responde_con_markov_post_procesado(monkeypatch):
    async def fake_markov(guild_id):
        return "  UN TEXTO GENERADO.  "

    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)

    result = _simulate("hola")
    assert result["would_respond"] is True
    assert result["reason"] == "markov"
    assert result["text"] == generation.post_process_reply("  UN TEXTO GENERADO.  ")


def test_responde_con_frase_especial_y_la_renderiza(monkeypatch):
    _patch_effective_settings(monkeypatch, frase_probability=1.0)
    monkeypatch.setattr(chat_mod.random, "random", lambda: 0.0)

    async def fake_frase(guild_id, pack_id):
        return "hola {{user.mention}}"

    async def fake_allowed(guild_id, channel_id):
        return True

    async def fake_pool(guild_id, channel_id):
        return None

    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)
    monkeypatch.setattr(chat_mod, "is_frase_allowed", fake_allowed)
    monkeypatch.setattr(chat_mod, "get_effective_frase_pool", fake_pool)

    result = _simulate("hola", user_mention="<@777>")
    assert result == {
        "would_respond": True,
        "reason": "frase_especial",
        "text": "hola <@777>",
    }


def test_no_gasta_el_cooldown_real_de_frases_especiales(monkeypatch):
    """La pieza más importante de la fase: simular no puede tener efectos
    secundarios sobre el bot real."""
    _patch_effective_settings(monkeypatch, frase_probability=1.0)
    monkeypatch.setattr(chat_mod.random, "random", lambda: 0.0)

    async def fake_frase(guild_id, pack_id):
        return "una frase"

    async def fake_allowed(guild_id, channel_id):
        return True

    async def fake_pool(guild_id, channel_id):
        return None

    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)
    monkeypatch.setattr(chat_mod, "is_frase_allowed", fake_allowed)
    monkeypatch.setattr(chat_mod, "get_effective_frase_pool", fake_pool)
    generation._special_phrase_cooldowns.clear()

    _simulate("hola")

    assert 1 not in generation._special_phrase_cooldowns


# ─── Triggers tienen prioridad ────────────────────────────────────────────────


def test_trigger_que_matchea_gana_y_no_llega_a_frase_vs_markov(monkeypatch):
    async def fake_triggers(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "frase_de_pack",
                "pack_id": None,
            }
        ]

    async def fake_frase(guild_id, pack_id):
        return "respuesta del trigger"

    async def fail_if_called(guild_id):
        raise AssertionError("no debería llegar a generar Markov")

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_triggers)
    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)
    monkeypatch.setattr(generation, "generate_markov_reply", fail_if_called)

    result = _simulate("hola")
    assert result == {
        "would_respond": True,
        "reason": "trigger",
        "trigger_id": 1,
        "text": "respuesta del trigger",
    }


def test_trigger_que_no_matchea_cae_a_frase_vs_markov(monkeypatch):
    async def fake_triggers(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "otra cosa",
                "action": "markov",
                "pack_id": None,
            }
        ]

    async def fake_markov(guild_id):
        return "markov normal"

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_triggers)
    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)

    result = _simulate("hola")
    assert result["reason"] == "markov"


def test_trigger_frase_de_pack_sin_frases_devuelve_sin_contenido(monkeypatch):
    async def fake_triggers(guild_id, channel_id):
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

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_triggers)
    monkeypatch.setattr(chat_mod, "get_random_frase_especial", fake_frase)

    result = _simulate("hola")
    assert result == {
        "would_respond": False,
        "reason": "trigger_sin_contenido",
        "trigger_id": 1,
        "text": None,
    }


def test_trigger_markov_no_se_templatea(monkeypatch):
    """Un trigger de acción 'markov' nunca pasa por render_frase_template
    -- el texto generado no es contenido que un admin escribió."""

    async def fake_triggers(guild_id, channel_id):
        return [
            {
                "id": 1,
                "match_type": "exact",
                "pattern": "hola",
                "action": "markov",
                "pack_id": None,
            }
        ]

    async def fake_markov(guild_id):
        return "{{user.mention}} literal"

    monkeypatch.setattr(chat_mod, "list_channel_triggers", fake_triggers)
    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)

    result = _simulate("hola")
    assert result["text"] == generation.post_process_reply("{{user.mention}} literal")
