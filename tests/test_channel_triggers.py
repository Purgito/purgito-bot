"""Tests de la Fase 4 en db.py: CRUD de channel_triggers y sus validaciones
(match_type/action inválidos, regex que no compila, límite por guild).
El matching en sí (exact/starts_with/regex + el timeout real) se prueba en
test_trigger_matching.py, contra cogs/chat.py.
"""

import asyncio

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def test_crear_y_listar_un_trigger(temp_db):
    async def run():
        trigger_id = await db.add_channel_trigger(1, 10, "exact", "hola", "markov")
        return trigger_id, await db.list_channel_triggers(1, 10)

    trigger_id, triggers = asyncio.run(run())
    assert trigger_id is not None
    assert len(triggers) == 1
    assert triggers[0]["id"] == trigger_id
    assert triggers[0]["match_type"] == "exact"
    assert triggers[0]["pattern"] == "hola"
    assert triggers[0]["action"] == "markov"
    assert triggers[0]["pack_id"] is None


def test_match_type_invalido_se_rechaza(temp_db):
    assert (
        asyncio.run(db.add_channel_trigger(1, 10, "algo_raro", "x", "markov")) is None
    )


def test_action_invalida_se_rechaza(temp_db):
    assert asyncio.run(db.add_channel_trigger(1, 10, "exact", "x", "algo_raro")) is None


def test_pattern_vacio_se_rechaza(temp_db):
    assert asyncio.run(db.add_channel_trigger(1, 10, "exact", "   ", "markov")) is None


def test_regex_invalido_no_compila_y_se_rechaza(temp_db):
    assert asyncio.run(db.add_channel_trigger(1, 10, "regex", "(", "markov")) is None


def test_pattern_largo_se_rechaza(temp_db):
    """Sin tope, un patrón de varios MB queda guardado y se evalúa contra cada
    mensaje del canal. Se rechaza en vez de recortarlo: un regex recortado es
    OTRO regex (o directamente no compila), así que lo que corría contra los
    mensajes no era lo que el admin escribió ni lo que la API validó."""

    async def run():
        trigger_id = await db.add_channel_trigger(1, 10, "exact", "x" * 5000, "markov")
        triggers = await db.list_channel_triggers(1, 10)
        return trigger_id, triggers

    trigger_id, triggers = asyncio.run(run())
    assert trigger_id is None
    assert triggers == []


def test_pattern_en_el_limite_exacto_se_acepta(temp_db):
    async def run():
        return await db.add_channel_trigger(
            1, 10, "exact", "x" * db.MAX_TRIGGER_PATTERN, "markov"
        )

    assert asyncio.run(run()) is not None


def test_regex_valido_se_acepta(temp_db):
    trigger_id = asyncio.run(
        db.add_channel_trigger(1, 10, "regex", r"^hola.*mundo$", "markov")
    )
    assert trigger_id is not None


def test_pack_id_se_guarda_para_frase_de_pack(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        trigger_id = await db.add_channel_trigger(
            1, 10, "exact", "feliz", "frase_de_pack", pack_id=pack_id
        )
        triggers = await db.list_channel_triggers(1, 10)
        return pack_id, trigger_id, triggers

    pack_id, trigger_id, triggers = asyncio.run(run())
    assert triggers[0]["pack_id"] == pack_id


def test_pack_id_de_otro_guild_se_rechaza(temp_db):
    """Sección 6, ronda 1: pack_id es un autoincrement global -- mismo IDOR
    que assign_pack_to_channel/set_frase_pack. Un guild no debe poder crear
    un trigger apuntando al pack_id de OTRO servidor."""

    async def run():
        guild_a, guild_b = 1, 2
        ajeno = await db.add_frase_pack(guild_b, "Pack de B")
        trigger_id = await db.add_channel_trigger(
            guild_a, 10, "exact", "feliz", "frase_de_pack", pack_id=ajeno
        )
        return trigger_id, await db.list_channel_triggers(guild_a, 10)

    trigger_id, triggers = asyncio.run(run())
    assert trigger_id is None
    assert triggers == []  # no se creó nada, ni siquiera con pack_id NULL


def test_triggers_se_recortan_al_limite(temp_db, monkeypatch):
    monkeypatch.setenv("MAX_CHANNEL_TRIGGERS_PER_GUILD_FREE", "2")

    async def run():
        a = await db.add_channel_trigger(1, 10, "exact", "a", "markov")
        b = await db.add_channel_trigger(1, 10, "exact", "b", "markov")
        c = await db.add_channel_trigger(1, 10, "exact", "c", "markov")
        return a, b, c

    a, b, c = asyncio.run(run())
    assert a is not None and b is not None
    assert c is None


def test_el_limite_es_por_guild_no_por_canal(temp_db, monkeypatch):
    """Sumando triggers de dos canales distintos del mismo guild igual pega
    contra el mismo tope -- el límite es sobre el guild entero."""
    monkeypatch.setenv("MAX_CHANNEL_TRIGGERS_PER_GUILD_FREE", "1")

    async def run():
        a = await db.add_channel_trigger(1, 10, "exact", "a", "markov")
        b = await db.add_channel_trigger(1, 20, "exact", "b", "markov")
        return a, b

    a, b = asyncio.run(run())
    assert a is not None
    assert b is None


def test_listar_esta_scopeado_a_guild_y_canal(temp_db):
    async def run():
        await db.add_channel_trigger(1, 10, "exact", "a", "markov")
        await db.add_channel_trigger(1, 20, "exact", "b", "markov")
        await db.add_channel_trigger(2, 10, "exact", "c", "markov")
        return await db.list_channel_triggers(1, 10)

    triggers = asyncio.run(run())
    assert len(triggers) == 1
    assert triggers[0]["pattern"] == "a"


def test_list_guild_triggers_trae_todos_los_canales(temp_db):
    async def run():
        await db.add_channel_trigger(1, 10, "exact", "a", "markov")
        await db.add_channel_trigger(1, 20, "exact", "b", "markov")
        return await db.list_guild_triggers(1)

    triggers = asyncio.run(run())
    assert {t["pattern"] for t in triggers} == {"a", "b"}
    assert {t["channel_id"] for t in triggers} == {10, 20}


def test_orden_de_listado_es_por_id_de_creacion(temp_db):
    """El primero que matchea gana en cogs/chat.py -- tiene que salir
    primero en la lista, es decir, en el orden en que se crearon."""

    async def run():
        await db.add_channel_trigger(1, 10, "exact", "primero", "markov")
        await db.add_channel_trigger(1, 10, "exact", "segundo", "markov")
        return await db.list_channel_triggers(1, 10)

    triggers = asyncio.run(run())
    assert [t["pattern"] for t in triggers] == ["primero", "segundo"]


def test_borrar_un_trigger(temp_db):
    async def run():
        trigger_id = await db.add_channel_trigger(1, 10, "exact", "a", "markov")
        deleted = await db.delete_channel_trigger(1, trigger_id)
        return deleted, await db.list_channel_triggers(1, 10)

    deleted, triggers = asyncio.run(run())
    assert deleted is True
    assert triggers == []


def test_borrar_un_trigger_de_otro_guild_no_hace_nada(temp_db):
    async def run():
        trigger_id = await db.add_channel_trigger(1, 10, "exact", "a", "markov")
        deleted = await db.delete_channel_trigger(999, trigger_id)
        return deleted, await db.list_channel_triggers(1, 10)

    deleted, triggers = asyncio.run(run())
    assert deleted is False
    assert len(triggers) == 1


def test_purge_guild_data_borra_los_triggers(temp_db):
    async def run():
        await db.add_channel_trigger(7, 10, "exact", "a", "markov")
        await db.purge_guild_data(7)
        return await db.list_channel_triggers(7, 10)

    assert asyncio.run(run()) == []
