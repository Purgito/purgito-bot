"""Tests de /imitar_mezcla: generation.generate_markov_for_users combina el
user_corpus de dos autores en un solo modelo Markov, sin cachear (a
diferencia de generate_markov_for_user) porque es una combinación puntual
por par de usuarios."""

import asyncio

import pytest

import db
import generation

_GUILD = 5001
_USER_A = 6001
_USER_B = 6002


@pytest.fixture
def memory_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_bot.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    asyncio.run(db.init_db())
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()
    yield
    asyncio.run(db.close_db())
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()


async def _seed_user_messages(guild_id, author_id, count, prefix="mensaje"):
    for i in range(count):
        await db.save_corpus_and_user_message(
            guild_id=guild_id,
            channel_id=1,
            author_id=author_id,
            author_name=f"user{author_id}",
            content=f"{prefix} numero {i} de prueba para el corpus mezclado",
            message_id=author_id * 100_000 + i,
        )


def test_ninguno_tiene_suficientes_mensajes_por_si_solo_pero_juntos_si(memory_db):
    """El caso real de la feature: cada usuario individualmente tiene menos
    de 30 mensajes (no calificaría para /imitar solo), pero combinados sí
    alcanzan el mínimo."""

    async def _run():
        await _seed_user_messages(_GUILD, _USER_A, 20, prefix="A dice")
        await _seed_user_messages(_GUILD, _USER_B, 20, prefix="B dice")

        assert await db.count_user_messages(_GUILD, _USER_A) == 20
        assert await db.count_user_messages(_GUILD, _USER_B) == 20

        return await generation.generate_markov_for_users(_GUILD, (_USER_A, _USER_B))

    result = asyncio.run(_run())
    assert result is not None
    assert isinstance(result, str)
    assert result.strip() != ""


def test_corpus_combinado_insuficiente_devuelve_none(memory_db):
    async def _run():
        await _seed_user_messages(_GUILD, _USER_A, 5)
        await _seed_user_messages(_GUILD, _USER_B, 5)
        return await generation.generate_markov_for_users(_GUILD, (_USER_A, _USER_B))

    assert asyncio.run(_run()) is None


def test_un_usuario_excluido_de_aprendizaje_bloquea_la_mezcla(memory_db):
    """Igual que generate_markov_for_user: un usuario excluido no puede
    colarse en una generación ni siquiera mezclado con otro que sí
    aprende."""

    async def _run():
        await _seed_user_messages(_GUILD, _USER_A, 40)
        await _seed_user_messages(_GUILD, _USER_B, 40)
        await db.set_user_exclusion(
            _GUILD, _USER_A, exclude_interaction=False, exclude_learning=True
        )
        return await generation.generate_markov_for_users(_GUILD, (_USER_A, _USER_B))

    assert asyncio.run(_run()) is None


def test_no_cachea_entre_llamadas(memory_db, monkeypatch):
    """A diferencia de generate_markov_for_user, cada llamada reconstruye el
    modelo -- no debe aparecer ninguna entrada nueva en _user_markov_cache
    (que crecería sin cota real, una por cada par posible de usuarios)."""

    async def _run():
        await _seed_user_messages(_GUILD, _USER_A, 20)
        await _seed_user_messages(_GUILD, _USER_B, 20)
        await generation.generate_markov_for_users(_GUILD, (_USER_A, _USER_B))

    asyncio.run(_run())
    assert len(generation._user_markov_cache) == 0
