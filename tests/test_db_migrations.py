"""init_db sobre PostgreSQL: el esquema se aplica en cada arranque, así que
tiene que ser idempotente, y un fallo al aplicarlo tiene que verse (antes de
publicar la conexión), no dejar el bot arrancando con el schema a medias."""

import asyncio

import pytest

import db


def test_init_db_es_idempotente_sobre_una_base_ya_migrada(monkeypatch):
    monkeypatch.setattr(db, "_db", None)

    async def run():
        await db.init_db()
        await db.close_db()
        await db.init_db()  # segundo arranque: todo ya existe, no puede fallar
        cur = await (await db.get_db()).execute("SELECT COUNT(*) FROM settings")
        data = await cur.fetchone()
        await db.close_db()
        return data

    assert asyncio.run(run()) == (0,)


def test_init_db_falla_a_la_vista_si_el_esquema_no_se_puede_aplicar(monkeypatch):
    monkeypatch.setattr(db, "_db", None)
    monkeypatch.setattr(db, "SCHEMA", "CREATE TABLE definitivamente (roto")

    async def run():
        with pytest.raises(Exception):
            await db.init_db()

    asyncio.run(run())
    assert db._db is None  # no quedó una conexión a medio inicializar


def test_init_db_sin_database_url_da_un_error_claro(monkeypatch):
    monkeypatch.setattr(db, "_db", None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    async def run():
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            await db.init_db()

    asyncio.run(run())


def test_el_esquema_declara_las_columnas_que_antes_eran_alter_table():
    """Antes de PostgreSQL esas columnas se sumaban con ALTER TABLE al
    arrancar; ahora tienen que venir en schema_pg.sql."""
    for col in (
        "manager_role_id",
        "custom_prefix",
        "frase_probability",
        "previous_detail",
        "weekdays",
        "resolve_retry_at",
        "phashes",
    ):
        assert col in db.SCHEMA, col
