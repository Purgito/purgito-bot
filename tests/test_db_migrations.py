"""Las migraciones de columnas de init_db (`ALTER TABLE ... ADD COLUMN`) corren
en cada arranque y casi siempre la columna ya existe. Antes cada una estaba
envuelta en `except Exception: log.debug("... ya existe")`, así que también
tragaban un disco lleno o una base bloqueada -- a nivel debug, invisible con
el logging en INFO de producción -- y el bot arrancaba con el schema a
medias. Ahora solo "duplicate column name" se ignora."""

import asyncio
import sqlite3

import aiosqlite
import pytest

import db


def test_duplicate_column_se_ignora():
    db._ignore_duplicate_column(sqlite3.OperationalError("duplicate column name: x"))


@pytest.mark.parametrize(
    "mensaje",
    [
        "database or disk is full",
        "database is locked",
        "attempt to write a readonly database",
        "no such table: foo",
    ],
)
def test_cualquier_otro_error_operacional_se_propaga(mensaje):
    with pytest.raises(sqlite3.OperationalError, match=mensaje):
        db._ignore_duplicate_column(sqlite3.OperationalError(mensaje))


def _patch_db_path(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)


def test_init_db_es_idempotente_sobre_una_base_ya_migrada(tmp_path, monkeypatch):
    """El segundo arranque encuentra TODAS las columnas ya creadas: tiene que
    pasar de largo sin levantar nada."""
    _patch_db_path(monkeypatch, tmp_path)

    async def run():
        await db.init_db()
        await db.close_db()
        await db.init_db()  # segunda vez: todas las ALTER dan "duplicate column"
        await db.close_db()

    asyncio.run(run())


def test_init_db_falla_a_la_vista_si_una_migracion_no_puede_escribir(
    tmp_path, monkeypatch
):
    _patch_db_path(monkeypatch, tmp_path)
    original_execute = aiosqlite.Connection.execute

    async def execute_con_disco_lleno(self, sql, *args, **kwargs):
        if str(sql).startswith("ALTER TABLE"):
            raise sqlite3.OperationalError("database or disk is full")
        return await original_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, "execute", execute_con_disco_lleno)

    async def run():
        try:
            with pytest.raises(sqlite3.OperationalError, match="disk is full"):
                await db.init_db()
        finally:
            if db._db is not None:
                await db._db.close()
                db._db = None

    asyncio.run(run())
