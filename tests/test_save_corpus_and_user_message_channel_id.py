"""Tests de save_corpus_and_user_message (db.py): desde esta fase, el INSERT
de user_corpus graba channel_id directo -- ya no depende de que corra
backfill_user_corpus_channel_id() en el próximo restart para que un mensaje
recién aprendido quede trazable. Ver tests/test_user_corpus_channel_backfill.py
para la migración retroactiva de filas viejas.

Usa una DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db
(que está trackeada en git)."""

import asyncio

import aiosqlite
import pytest

import db

_GUILD_A = 1
_GUILD_B = 2
_AUTHOR_A = 10
_AUTHOR_B = 20
_CHANNEL_1 = 100
_CHANNEL_2 = 200


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.execute("ALTER TABLE user_corpus ADD COLUMN channel_id INTEGER")
    await conn.commit()
    return conn


async def _user_corpus_row(conn, guild_id, message_id):
    cur = await conn.execute(
        "SELECT author_id, author_name, channel_id, content FROM user_corpus "
        "WHERE guild_id=? AND message_id IS ?",
        (guild_id, message_id),
    )
    return await cur.fetchone()


def test_nuevo_mensaje_queda_con_channel_id_correcto(memory_db):
    async def run():
        await db.save_corpus_and_user_message(
            _GUILD_A, _CHANNEL_1, _AUTHOR_A, "Fulano", "hola mundo", message_id=1
        )
        row = await _user_corpus_row(memory_db, _GUILD_A, 1)
        assert row == (_AUTHOR_A, "Fulano", _CHANNEL_1, "hola mundo")

    asyncio.run(run())


def test_no_depende_de_correr_el_backfill(memory_db):
    """Sin llamar a backfill_user_corpus_channel_id(), channel_id ya debe
    estar poblado -- esa es la ventana que esta fase cierra."""

    async def run():
        await db.save_corpus_and_user_message(
            _GUILD_A, _CHANNEL_2, _AUTHOR_A, "Fulano", "sin backfill", message_id=2
        )
        row = await _user_corpus_row(memory_db, _GUILD_A, 2)
        assert row[2] == _CHANNEL_2

    asyncio.run(run())


def test_conserva_deduplicacion_por_message_id(memory_db):
    """INSERT OR IGNORE + UNIQUE(guild_id, message_id): reinsertar el mismo
    message_id (aunque cambie de canal) no debe crear una fila duplicada ni
    pisar la existente."""

    async def run():
        inserted1 = await db.save_corpus_and_user_message(
            _GUILD_A, _CHANNEL_1, _AUTHOR_A, "Fulano", "primero", message_id=3
        )
        inserted2 = await db.save_corpus_and_user_message(
            _GUILD_A, _CHANNEL_2, _AUTHOR_B, "Mengano", "segundo", message_id=3
        )
        assert inserted1 == (True, True)
        assert inserted2 == (False, False)

        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM user_corpus WHERE guild_id=? AND message_id=?",
            (_GUILD_A, 3),
        )
        assert (await cur.fetchone())[0] == 1

        row = await _user_corpus_row(memory_db, _GUILD_A, 3)
        assert row == (_AUTHOR_A, "Fulano", _CHANNEL_1, "primero")

    asyncio.run(run())


def test_no_altera_datos_de_otros_guilds_o_autores(memory_db):
    async def run():
        await db.save_corpus_and_user_message(
            _GUILD_A, _CHANNEL_1, _AUTHOR_A, "A", "msg de A", message_id=10
        )
        await db.save_corpus_and_user_message(
            _GUILD_B, _CHANNEL_2, _AUTHOR_B, "B", "msg de B", message_id=10
        )

        row_a = await _user_corpus_row(memory_db, _GUILD_A, 10)
        row_b = await _user_corpus_row(memory_db, _GUILD_B, 10)
        assert row_a == (_AUTHOR_A, "A", _CHANNEL_1, "msg de A")
        assert row_b == (_AUTHOR_B, "B", _CHANNEL_2, "msg de B")

    asyncio.run(run())


def test_corpus_messages_y_user_corpus_siguen_atomicos_bajo_un_solo_lock(memory_db):
    """corpus_messages y user_corpus deben seguir entrando en la misma
    adquisición de _db_lock -- si el segundo INSERT falla, el rollback
    automático (_RollbackOnErrorLock) deshace también el primero. Mismo
    patrón que test_db_rollback.py::test_falla_real_en_una_secuencia_de_dos_execute_de_una_funcion_real,
    repetido acá para dejar la garantía explícita junto al resto de tests de
    esta función."""

    async def run():
        real_execute = memory_db.execute
        call_count = 0

        def flaky_execute(sql, params=()):
            nonlocal call_count
            call_count += 1
            if call_count == 2 and "user_corpus" in sql:
                raise RuntimeError("boom en el segundo execute")
            return real_execute(sql, params)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(memory_db, "execute", flaky_execute)
        try:
            with pytest.raises(RuntimeError, match="boom en el segundo execute"):
                await db.save_corpus_and_user_message(
                    _GUILD_A, _CHANNEL_1, _AUTHOR_A, "A", "atomico", message_id=99
                )
        finally:
            monkeypatch.undo()

        cur = await memory_db.execute("SELECT COUNT(*) FROM corpus_messages")
        corpus_count = (await cur.fetchone())[0]
        cur = await memory_db.execute("SELECT COUNT(*) FROM user_corpus")
        user_count = (await cur.fetchone())[0]
        return corpus_count, user_count

    corpus_count, user_count = asyncio.run(run())
    assert corpus_count == 0
    assert user_count == 0
