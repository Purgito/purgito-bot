"""Tests de privacidad y resiliencia para la integración de Groq y fallback a Markov.

Valida:
1. GROQ_API_KEY ausente -> Groq no se invoca, retorna None.
2. Fallback a Markov cuando no hay Groq configurado.
3. Fallback a Markov cuando Groq falla, tiene timeout o rate limit (429).
4. La muestra del corpus enviada a Groq está estrictamente acotada (máx 25 cortos + 15 largos = máx 40)
   y nunca envía el corpus completo.
5. Coherencia documental: ni la landing ni los docs afirman falsamente que no se usan modelos externos
   cuando Groq está disponible para memes.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import cogs.memes as memes_mod
from cogs.memes import _generate_caption, generate_groq_meme_caption


def test_groq_absent_returns_none(monkeypatch):
    """Si no hay cliente Groq configurado, generate_groq_meme_caption retorna None inmediatamente."""
    monkeypatch.setattr(memes_mod, "_groq_client", None)
    caption = asyncio.run(
        generate_groq_meme_caption(b"fake_image_bytes", ["hola", "mundo"], guild_id=100)
    )
    assert caption is None


def test_fallback_to_markov_when_groq_absent(monkeypatch):
    """Cuando no hay cliente de Groq, _generate_caption usa directamente el modelo Markov local."""
    monkeypatch.setattr(memes_mod, "_groq_client", None)

    fake_model = SimpleNamespace(is_empty=False)

    async def fake_build_markov(guild_id):
        assert guild_id == 123
        return fake_model

    def fake_short_sentence(model):
        assert model is fake_model
        return "caption desde markov local"

    monkeypatch.setattr(memes_mod, "build_markov_model", fake_build_markov)
    monkeypatch.setattr(memes_mod, "_try_short_sentence", fake_short_sentence)

    caption = asyncio.run(_generate_caption(123, b"fake_img", ["mensaje1", "mensaje2"]))
    assert caption == "caption desde markov local"


def test_fallback_to_markov_when_groq_fails_or_rate_limited(monkeypatch):
    """Cuando Groq arroja 429 rate limit o excepción, se captura y hace fallback a Markov sin fallar."""
    fake_groq = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(side_effect=Exception("429 rate_limit exceeded"))
            )
        )
    )
    monkeypatch.setattr(memes_mod, "_groq_client", fake_groq)
    monkeypatch.setattr(memes_mod, "_groq_cooldowns", {})

    fake_model = SimpleNamespace(is_empty=False)

    async def fake_build_markov(guild_id):
        return fake_model

    def fake_short_sentence(model):
        return "caption de rescate markov"

    monkeypatch.setattr(memes_mod, "build_markov_model", fake_build_markov)
    monkeypatch.setattr(memes_mod, "_try_short_sentence", fake_short_sentence)

    caption = asyncio.run(
        _generate_caption(456, b"\x89PNG\r\n\x1a\nfake", ["un mensaje"])
    )
    assert caption == "caption de rescate markov"


def test_groq_sample_is_strictly_bounded_and_never_sends_full_corpus(monkeypatch):
    """La muestra enviada a Groq debe estar estrictamente limitada a 25 cortos + 15 largos (máx 40)
    incluso si se le entrega una muestra de 500 mensajes."""
    captured_payload = {}

    async def fake_create(**kwargs):
        captured_payload.update(kwargs)
        choice = SimpleNamespace(
            message=SimpleNamespace(content="caption generado por groq")
        )
        return SimpleNamespace(choices=[choice])

    fake_groq = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    monkeypatch.setattr(memes_mod, "_groq_client", fake_groq)
    monkeypatch.setattr(memes_mod, "_groq_cooldowns", {})

    # Crear 100 mensajes cortos (<= 5 palabras) y 100 mensajes largos (> 5 palabras)
    short_corpus = [f"corto {i}" for i in range(100)]
    long_corpus = [
        f"este es un mensaje bastante largo numero {i} para el corpus"
        for i in range(100)
    ]
    full_corpus = short_corpus + long_corpus

    img_bytes = b"\x89PNG\r\n\x1a\nfake_image_content"
    caption = asyncio.run(
        generate_groq_meme_caption(img_bytes, full_corpus, guild_id=789)
    )

    assert caption == "caption generado por groq"
    assert captured_payload["model"] == "meta-llama/llama-4-scout-17b-16e-instruct"

    messages = captured_payload["messages"]
    user_content = messages[1]["content"]

    # 1. Verificar imagen en base64
    image_part = next(p for p in user_content if p["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")

    # 2. Verificar que el texto del prompt solo contiene como máximo 25 cortos y 15 largos
    text_part = next(p for p in user_content if p["type"] == "text")
    prompt_text = text_part["text"]

    # Los primeros 25 cortos deben estar presentes
    for i in range(25):
        assert f"corto {i}" in prompt_text
    # El corto 26 NO debe estar presente
    assert "corto 25" not in prompt_text

    # Los primeros 15 largos deben estar presentes
    for i in range(15):
        assert (
            f"este es un mensaje bastante largo numero {i} para el corpus"
            in prompt_text
        )
    # El largo 16 NO debe estar presente
    assert (
        "este es un mensaje bastante largo numero 15 para el corpus" not in prompt_text
    )


def test_no_contradictory_privacy_claims_in_landing_or_docs():
    """Verifica que no queden afirmaciones contradictorias en el repositorio."""
    root = Path(__file__).resolve().parents[1]
    landing_es = root / "landing" / "es"

    forbidden_patterns = [
        "no utiliza modelos de inteligencia artificial externos ni envía tus mensajes a terceros",
        "Sin IA comercial",
    ]

    for html_file in landing_es.rglob("*.html"):
        content = html_file.read_text("utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in content, (
                f"Patrón prohibido '{pattern}' encontrado en {html_file}"
            )

    # Verificar que la política de privacidad explique adecuadamente a Groq
    privacy_html = (landing_es / "privacidad" / "index.html").read_text("utf-8")
    assert "Groq API" in privacy_html
    assert "cadenas de Markov" in privacy_html
    assert "muestra limitada del corpus" in privacy_html
