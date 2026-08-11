"""Tests del playground del dashboard (Fase 7): simulate_message en
cogs/chat.py tiene que reflejar la misma decisión que on_message (triggers,
frase-vs-Markov, templating) pero SIN efectos secundarios reales -- ni
cooldown de frases especiales, ni contadores, ni corpus, ni mandar nada a
Discord. Eso último se prueba explícito: simular no puede alterar el estado
que sí usa el bot de verdad.
"""

import asyncio
import time
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
    "mention_rate_limit": 10,
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


def _patch_sin_frenos(monkeypatch):
    """Allowlists vacías (= sin restricción) y ningún cooldown en curso: el
    escenario donde `avisos` sale vacío. Los tests de avisos pisan lo que
    necesiten encima de esto."""

    async def fake_lista(guild_id):
        return []

    monkeypatch.setattr(chat_mod, "list_mention_channels", fake_lista)
    monkeypatch.setattr(chat_mod, "list_spontaneous_channels", fake_lista)
    monkeypatch.setattr(chat_mod, "list_exempt_channels", fake_lista)
    chat_mod._mention_hits.clear()
    chat_mod._spontaneous_cooldowns.clear()


@pytest.fixture(autouse=True)
def base_patches(monkeypatch):
    _patch_effective_settings(monkeypatch)
    _patch_no_triggers(monkeypatch)
    _patch_not_ignored(monkeypatch)
    _patch_sin_frenos(monkeypatch)


# ─── Canal ignorado corta todo ────────────────────────────────────────────────


def test_canal_ignorado_no_responde(monkeypatch):
    async def fake_ignored(guild_id, channel_id):
        return True

    monkeypatch.setattr(chat_mod, "is_channel_ignored", fake_ignored)

    result = _simulate("hola")
    assert result == {
        "would_respond": False,
        "reason": "canal_ignorado",
        "text": None,
        "avisos": [],
    }


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
        "avisos": [],
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
        "avisos": [],
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
        "avisos": [],
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
        "avisos": [],
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


# ─── Avisos: los frenos que actúan ANTES del motor de generación ─────────────
#
# El Playground contestaba solo por el motor (triggers, frase-vs-Markov) y no
# decía nada de lo que frena al mensaje antes de llegar ahí -- justo las causas
# más comunes de "no me contesta". No pueden ser un `reason` único porque cada
# freno aplica a una vía de entrega distinta (mención vs. hablar solo) y el
# playground no pregunta por cuál llegaría el mensaje: por eso salen como lista.


def _patch_markov(monkeypatch):
    async def fake_markov(guild_id):
        return "texto"

    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)


def _avisos(monkeypatch, author_id=5):
    """Avisos de una simulación en el canal 10 del guild 1, como el autor
    `author_id` (el admin logueado hace de autor en el playground real)."""
    _patch_markov(monkeypatch)
    result = asyncio.run(
        chat_mod.simulate_message(
            1,
            10,
            "hola",
            author=SimpleNamespace(mention="<@5>", display_name="Ana", id=author_id),
            channel=SimpleNamespace(name="general", mention="<#10>"),
            guild=SimpleNamespace(id=1, name="PURG4TORY"),
        )
    )
    return result["avisos"]


def _patch_lista(monkeypatch, nombre, valor):
    async def fake(guild_id):
        return valor

    monkeypatch.setattr(chat_mod, nombre, fake)


def _agotar_cupo(guild_id=1, user_id=5, count=10):
    chat_mod._mention_hits[(guild_id, user_id)] = (time.monotonic(), count)


def test_sin_frenos_no_hay_avisos(monkeypatch):
    assert _avisos(monkeypatch) == []


def test_chat_desactivado_avisa(monkeypatch):
    """`enabled` gatea SOLO la rama de menciones en on_message: el aviso lo
    dice, para que el admin no crea que apagó también los espontáneos."""
    _patch_effective_settings(monkeypatch, enabled=False)
    assert _avisos(monkeypatch) == ["chat_desactivado"]


def test_canal_fuera_del_allowlist_de_menciones_avisa(monkeypatch):
    _patch_lista(monkeypatch, "list_mention_channels", [999])
    assert _avisos(monkeypatch) == ["canal_sin_menciones"]


def test_canal_fuera_del_allowlist_espontaneo_avisa(monkeypatch):
    _patch_lista(monkeypatch, "list_spontaneous_channels", [999])
    assert _avisos(monkeypatch) == ["canal_sin_espontaneo"]


def test_allowlist_que_incluye_el_canal_no_avisa(monkeypatch):
    """Lista no vacía pero con este canal adentro: no es un freno."""
    _patch_lista(monkeypatch, "list_mention_channels", [10])
    _patch_lista(monkeypatch, "list_spontaneous_channels", [10])
    assert _avisos(monkeypatch) == []


def test_cupo_horario_agotado_avisa(monkeypatch):
    _agotar_cupo()
    assert _avisos(monkeypatch) == ["cupo_horario_agotado"]


def test_cupo_de_otro_usuario_no_afecta(monkeypatch):
    """El tope es por usuario: el cupo agotado de otro no frena al que prueba."""
    _agotar_cupo(user_id=777)
    assert _avisos(monkeypatch, author_id=5) == []


def test_ventana_vencida_no_avisa_por_cupo(monkeypatch):
    """Contador viejo de una ventana ya cerrada: no es un freno vigente."""
    chat_mod._mention_hits[(1, 5)] = (
        time.monotonic() - chat_mod._MENTION_RATE_WINDOW - 1,
        10,
    )
    assert _avisos(monkeypatch) == []


def test_canal_exento_no_avisa_por_cupo(monkeypatch):
    _agotar_cupo()
    _patch_lista(monkeypatch, "list_exempt_channels", [10])
    assert _avisos(monkeypatch) == []


def test_tope_en_cero_no_avisa_por_cupo(monkeypatch):
    """mention_rate_limit=0 es "sin límite": nunca puede ser el freno."""
    _patch_effective_settings(monkeypatch, mention_rate_limit=0)
    _agotar_cupo()
    assert _avisos(monkeypatch) == []


def test_simular_no_consume_el_cupo_de_menciones(monkeypatch):
    """Mismo contrato que el resto del playground: mirar no gasta nada."""
    chat_mod._mention_hits.clear()
    _avisos(monkeypatch)
    assert (1, 5) not in chat_mod._mention_hits


def test_cooldown_espontaneo_en_curso_avisa(monkeypatch):
    chat_mod._spontaneous_cooldowns[(1, 10)] = time.monotonic()
    assert _avisos(monkeypatch) == ["cooldown_espontaneo"]


def test_simular_no_gasta_el_cooldown_espontaneo(monkeypatch):
    chat_mod._spontaneous_cooldowns.clear()
    _avisos(monkeypatch)
    assert (1, 10) not in chat_mod._spontaneous_cooldowns


def test_varios_frenos_se_listan_juntos(monkeypatch):
    _patch_effective_settings(monkeypatch, enabled=False)
    _patch_lista(monkeypatch, "list_mention_channels", [999])
    _patch_lista(monkeypatch, "list_spontaneous_channels", [999])
    chat_mod._spontaneous_cooldowns[(1, 10)] = time.monotonic()

    assert _avisos(monkeypatch) == [
        "chat_desactivado",
        "canal_sin_menciones",
        "canal_sin_espontaneo",
        "cooldown_espontaneo",
    ]
