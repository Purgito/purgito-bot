"""generate_response decide entre frase especial y Markov (Fase 3): ahora
resuelve el pool efectivo (pack del canal o default) y respeta la whitelist
de frase_allowed_channels, además del cooldown y la probabilidad que ya
tenía. DB real (in-memory vía tmp_path) para is_frase_allowed/
get_effective_frase_pool/get_random_frase_especial; generate_markov_reply
se reemplaza por un stub porque no hace falta un corpus real acá.
"""

import asyncio

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

    async def fake_markov(guild_id):
        return "markov"

    monkeypatch.setattr(generation, "generate_markov_reply", fake_markov)


def _force_special_phrase_roll(monkeypatch):
    """random() = 0.0 siempre cae del lado de la frase especial (probability > 0)."""
    monkeypatch.setattr(generation.random, "random", lambda: 0.0)


def test_con_probabilidad_1_y_una_frase_devuelve_la_frase(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("hola especial", True)


def test_con_probabilidad_0_nunca_sale_una_frase(temp_db, monkeypatch):
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=0.0)
    )
    assert (text, is_special) == ("markov", False)


def test_canal_fuera_de_la_whitelist_cae_a_markov(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    asyncio.run(db.add_frase_channel(1, 20))  # solo el 20 puede tener frases

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("markov", False)


def test_canal_dentro_de_la_whitelist_si_puede_salir_frase(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    asyncio.run(db.add_frase_channel(1, 10))

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("hola especial", True)


def test_canal_con_pack_asignado_solo_ve_frases_de_ese_pack(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)

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


def test_canal_sin_pack_asignado_usa_el_pool_default(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)

    async def setup():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.add_frase_especial(1, 1, "u", "de navidad", pack_id=pack_id)
        await db.add_frase_especial(1, 1, "u", "default")

    asyncio.run(setup())

    text, is_special = asyncio.run(
        generation.generate_response(1, 20, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("default", True)


def test_cooldown_bloquea_una_segunda_frase_seguida(temp_db, monkeypatch):
    _force_special_phrase_roll(monkeypatch)
    asyncio.run(db.add_frase_especial(1, 1, "u", "hola especial"))
    # >= SPECIAL_PHRASE_COOLDOWN partiendo de 0.0: si no, ya el primer
    # llamado quedaría "en cooldown" antes de haber disparado nunca.
    monkeypatch.setattr(generation.time, "monotonic", lambda: 10_000.0)

    primera = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert primera == ("hola especial", True)

    segunda = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert segunda == ("markov", False)


def test_sin_frases_guardadas_cae_a_markov_aunque_la_probabilidad_sea_1(
    temp_db, monkeypatch
):
    _force_special_phrase_roll(monkeypatch)

    text, is_special = asyncio.run(
        generation.generate_response(1, 10, special_phrase_probability=1.0)
    )
    assert (text, is_special) == ("markov", False)
