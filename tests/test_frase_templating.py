"""Tests del templating de frases especiales (Fase 5): reemplazo de tags
{{...}} por string matching simple (str.replace), whitelist cerrada -- ver
TEMPLATE_TAGS y render_frase_template en cogs/chat.py.

Sin motor de templates real: nunca se evalúa nada, un tag que no está en la
whitelist queda tal cual como texto literal. Eso incluye, a propósito,
cualquier tag de mención de rol -- ver el comentario junto a TEMPLATE_TAGS
sobre por qué no se agrega sin avisar antes.
"""

import asyncio
from types import SimpleNamespace

import cogs.chat as chat_mod
import generation


def _ctx(
    user_mention="<@5>",
    user_name="Ana",
    chan_name="general",
    chan_mention="<#10>",
    guild_name="PURG4TORY",
):
    return {
        "author": SimpleNamespace(mention=user_mention, display_name=user_name),
        "channel": SimpleNamespace(name=chan_name, mention=chan_mention),
        "guild": SimpleNamespace(id=1, name=guild_name),
    }


def _render(text, **ctx_overrides):
    ctx = _ctx(**ctx_overrides)
    return asyncio.run(chat_mod.render_frase_template(text, **ctx))


# ─── Atajo sin tags ───────────────────────────────────────────────────────────


def test_texto_sin_tags_no_se_toca(monkeypatch):
    async def fail_if_called(guild_id):
        raise AssertionError("no debería generar Markov sin el tag")

    monkeypatch.setattr(generation, "generate_markov_word", fail_if_called)
    monkeypatch.setattr(generation, "generate_markov_reply", fail_if_called)

    assert _render("hola, ¿cómo estás?") == "hola, ¿cómo estás?"


# ─── Tags literales (sin Markov) ──────────────────────────────────────────────


def test_user_mention():
    assert _render("hola {{user.mention}}", user_mention="<@777>") == "hola <@777>"


def test_user_name():
    assert _render("hola {{user.name}}", user_name="Frambuesa") == "hola Frambuesa"


def test_channel_name():
    assert (
        _render("bienvenido a {{channel.name}}", chan_name="anuncios")
        == "bienvenido a anuncios"
    )


def test_channel_mention():
    assert _render("mira {{channel.mention}}", chan_mention="<#999>") == "mira <#999>"


def test_guild_name():
    assert (
        _render("bienvenido a {{guild.name}}", guild_name="Mi Server")
        == "bienvenido a Mi Server"
    )


def test_mismo_tag_repetido_se_reemplaza_en_todas_las_apariciones():
    result = _render(
        "{{user.mention}} y de nuevo {{user.mention}}", user_mention="<@1>"
    )
    assert result == "<@1> y de nuevo <@1>"


def test_varios_tags_distintos_en_el_mismo_texto():
    result = _render(
        "{{user.mention}} en {{channel.name}} de {{guild.name}}",
        user_mention="<@1>",
        chan_name="general",
        guild_name="PURG4TORY",
    )
    assert result == "<@1> en general de PURG4TORY"


def test_tag_desconocido_queda_literal():
    assert _render("hola {{esto.no.existe}}") == "hola {{esto.no.existe}}"


def test_ningun_tag_de_mencion_de_rol_esta_en_la_whitelist():
    """Regresión de seguridad: un tag de mención de rol sobre texto que
    escribe un admin es una forma fácil de esconder un @everyone/@here en
    una frase que dispara sola. No se agrega sin avisar antes."""
    for tag in chat_mod.TEMPLATE_TAGS:
        assert "role" not in tag
        assert "everyone" not in tag
        assert "here" not in tag


# ─── Tags de Markov (lazy, solo si están presentes) ──────────────────────────


def test_markov_word_se_reemplaza(monkeypatch):
    async def fake_word(guild_id):
        return "palabra"

    monkeypatch.setattr(generation, "generate_markov_word", fake_word)
    assert _render("una {{markov.word}} random") == "una palabra random"


def test_markov_sentence_se_reemplaza(monkeypatch):
    async def fake_sentence(guild_id):
        return "una frase generada"

    monkeypatch.setattr(generation, "generate_markov_reply", fake_sentence)
    assert _render("dice: {{markov.sentence}}") == "dice: una frase generada"


def test_markov_word_sin_corpus_suficiente_reemplaza_por_vacio(monkeypatch):
    async def fake_none(guild_id):
        return None

    monkeypatch.setattr(generation, "generate_markov_word", fake_none)
    assert _render("una {{markov.word}} random") == "una  random"


def test_markov_no_se_genera_si_el_tag_no_esta_presente(monkeypatch):
    async def fail_if_called(guild_id):
        raise AssertionError("no debería llamarse: el texto no tiene el tag")

    monkeypatch.setattr(generation, "generate_markov_word", fail_if_called)
    monkeypatch.setattr(generation, "generate_markov_reply", fail_if_called)

    assert _render("hola {{user.mention}}", user_mention="<@1>") == "hola <@1>"


# ─── generation.generate_markov_word ─────────────────────────────────────────


def test_generate_markov_word_sin_corpus_devuelve_none(monkeypatch):
    async def fake_build(guild_id):
        return None

    monkeypatch.setattr(generation, "build_markov_model", fake_build)
    assert asyncio.run(generation.generate_markov_word(1)) is None


def test_generate_markov_word_devuelve_una_sola_palabra(monkeypatch):
    class FakeModel:
        is_empty = False

        def generate(self, max_words, max_attempts, min_words):
            assert max_words == 1
            return "unapalabra"

    async def fake_build(guild_id):
        return FakeModel()

    monkeypatch.setattr(generation, "build_markov_model", fake_build)
    assert asyncio.run(generation.generate_markov_word(1)) == "unapalabra"
