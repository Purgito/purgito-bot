"""generate_response decide entre frase especial y Markov (Fase 3):
- Con frase_probability=1.0 (100%), la frase es OBLIGATORIA. Si no está disponible
  (sin frases, en cooldown o canal no permitido), NUNCA cae silenciosamente a Markov:
  retorna GenerationResult(None, True, reason=...) para emitir el fallback explicativo.
- Con probabilidades intermedias (0.0 < p < 1.0), si la frase no se puede usar cae
  normalmente a Markov.
- Con probabilidad 0.0, nunca intenta frases y genera Markov directamente.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

import db
import generation


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    generation._special_phrase_cooldowns.clear()
    generation._empty_frase_cooldowns.clear()

    async def fake_markov(guild_id, **kwargs):
        return "markov"

    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)


def _force_special_phrase_roll(monkeypatch):
    """random() = 0.0 siempre cae del lado de la frase especial (probability > 0)."""
    monkeypatch.setattr(generation.random, "random", lambda: 0.0)


# ─── 1. 100% + frase disponible ───────────────────────────────────────────────


def test_100_con_frase_disponible_devuelve_frase_y_no_markov(temp_db, monkeypatch):
    markov_mock = AsyncMock(return_value="markov")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))

    res = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    text, is_special = res
    assert (text, is_special) == ("hola especial", True)
    assert res.reason is None
    markov_mock.assert_not_called()


# ─── 2. 100% + frase no disponible (sin frases guardadas) ─────────────────────


def test_100_sin_frases_no_genera_markov_y_retorna_estado_no_phrases(
    temp_db, monkeypatch
):
    markov_mock = AsyncMock(return_value="markov")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    res = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    text, is_special = res
    assert text is None
    assert is_special is True
    assert res.reason == "no_phrases"
    markov_mock.assert_not_called()


# ─── 3. 100% + cooldown ───────────────────────────────────────────────────────


def test_100_con_cooldown_activo_no_genera_markov_y_retorna_estado_cooldown(
    temp_db, monkeypatch
):
    markov_mock = AsyncMock(return_value="markov")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    monkeypatch.setattr(generation.time, "monotonic", lambda: 10_000.0)

    # Primer llamado: consume la frase y activa el cooldown
    primera = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert primera == ("hola especial", True)

    # Segundo llamado dentro del cooldown de 40 min:
    segunda = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert segunda.text is None
    assert segunda.is_special is True
    assert segunda.reason == "cooldown"
    markov_mock.assert_not_called()


# ─── 4. 100% + canal no permitido (whitelist) ─────────────────────────────────


def test_100_canal_no_permitido_no_genera_markov_y_retorna_estado_channel_not_allowed(
    temp_db, monkeypatch
):
    markov_mock = AsyncMock(return_value="markov")
    monkeypatch.setattr(generation, "generate_markov_reply", markov_mock)

    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    asyncio.run(db.add_frase_channel(1, 20))  # solo el canal 20 tiene frases permitidas

    res = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert res.text is None
    assert res.is_special is True
    assert res.reason == "channel_not_allowed"
    markov_mock.assert_not_called()


def test_100_canal_dentro_de_la_whitelist_si_puede_salir_frase(temp_db, monkeypatch):
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    asyncio.run(db.add_frase_channel(1, 10))

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("hola especial", True)


def test_100_canal_con_pack_asignado_solo_ve_frases_de_ese_pack(temp_db, monkeypatch):
    async def setup():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.add_frase_especial(1, 1, "u", "de navidad", pack_id=pack_id)
        await db.add_frase_especial(1, 1, "u", "default")
        await db.assign_pack_to_channel(1, 10, pack_id)

    asyncio.run(setup())

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("de navidad", True)


def test_100_canal_sin_pack_asignado_usa_el_pool_default(temp_db, monkeypatch):
    async def setup():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.add_frase_especial(1, 1, "u", "de navidad", pack_id=pack_id)
        await db.add_frase_especial(1, 1, "u", "default")

    asyncio.run(setup())

    text, is_special = asyncio.run(
        generation.generate_response(1, 20, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("default", True)


# ─── 5. 50% / valor intermedio: mantiene caída a Markov ───────────────────────


def test_50_intermedia_sin_frases_cae_a_markov(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=0.5)
    )
    assert (text, is_special) == ("markov", False)


def test_50_intermedia_con_cooldown_cae_a_markov(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    monkeypatch.setattr(generation.time, "monotonic", lambda: 10_000.0)

    primera = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=0.5)
    )
    assert primera == ("hola especial", True)

    segunda = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=0.5)
    )
    assert segunda == ("markov", False)


def test_50_intermedia_canal_fuera_de_whitelist_cae_a_markov(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    asyncio.run(db.add_frase_channel(1, 20))  # solo canal 20 permitido

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=0.5)
    )
    assert (text, is_special) == ("markov", False)


# ─── 6. 0%: nunca intenta frase y genera Markov ───────────────────────────────


def test_0_nunca_intenta_frase_y_siempre_genera_markov(temp_db, monkeypatch):
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=0.0)
    )
    assert (text, is_special) == ("markov", False)


# ─── 7. Fallback throttled ───────────────────────────────────────────────────


def test_empty_frase_reply_throttled(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(generation.time, "monotonic", lambda: now)

    # throttle=False (/generar): siempre emite el aviso
    msg1 = generation.empty_frase_reply(1, "no_phrases", "es", throttle=False)
    msg2 = generation.empty_frase_reply(1, "no_phrases", "es", throttle=False)
    assert msg1 is not None and "No tengo ninguna frase configurada" in msg1
    assert msg2 == msg1

    # throttle=True (menciones): primera vez responde, segunda vez retorna None (silencio)
    msg_m1 = generation.empty_frase_reply(2, "cooldown", "es", throttle=True)
    msg_m2 = generation.empty_frase_reply(2, "cooldown", "es", throttle=True)
    assert msg_m1 is not None and "Usé una frase hace poco" in msg_m1
    assert msg_m2 is None

    # Tras pasar el cooldown de throttle (15 min = 900s), vuelve a avisar
    now += 901.0
    msg_m3 = generation.empty_frase_reply(2, "cooldown", "es", throttle=True)
    assert msg_m3 is not None and "Usé una frase hace poco" in msg_m3
