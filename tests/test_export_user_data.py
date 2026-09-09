"""Tests de db.export_user_data: complemento de solo lectura de
delete_user_data, para /mis_datos (cogs/privacy.py)."""

import asyncio

import pytest

import db


@pytest.fixture
def memory_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_bot.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


async def _save(guild_id, channel_id, author_id, message_id, content):
    await db.save_corpus_and_user_message(
        guild_id=guild_id,
        channel_id=channel_id,
        author_id=author_id,
        author_name="tester",
        content=content,
        message_id=message_id,
    )


def test_agrupa_por_guild_y_conserva_el_contenido(memory_db):
    async def _run():
        await _save(1, 10, 999, 1, "hola desde guild 1")
        await _save(1, 11, 999, 2, "otro mensaje del mismo guild")
        await _save(2, 20, 999, 3, "hola desde guild 2")
        return await db.export_user_data(999)

    by_guild = asyncio.run(_run())

    assert set(by_guild.keys()) == {1, 2}
    assert len(by_guild[1]) == 2
    assert len(by_guild[2]) == 1
    assert {row["content"] for row in by_guild[1]} == {
        "hola desde guild 1",
        "otro mensaje del mismo guild",
    }
    assert by_guild[2][0]["channel_id"] == 20


def test_usuario_sin_datos_devuelve_vacio(memory_db):
    assert asyncio.run(db.export_user_data(12345)) == {}


def test_no_incluye_datos_de_otro_autor(memory_db):
    async def _run():
        await _save(1, 10, 111, 1, "mensaje de A")
        await _save(1, 10, 222, 2, "mensaje de B")
        return await db.export_user_data(111)

    by_guild = asyncio.run(_run())
    assert list(by_guild.keys()) == [1]
    assert len(by_guild[1]) == 1
    assert by_guild[1][0]["content"] == "mensaje de A"


def test_no_borra_ni_modifica_nada(memory_db):
    """Es de solo lectura -- llamarla dos veces devuelve lo mismo, a
    diferencia de delete_user_data."""

    async def _run():
        await _save(1, 10, 999, 1, "hola")
        first = await db.export_user_data(999)
        second = await db.export_user_data(999)
        return first, second

    first, second = asyncio.run(_run())
    assert first == second
    assert len(first[1]) == 1
