"""Tests de db.delete_user_data (Right to be Forgotten individual, núcleo):
borrado GLOBAL por author_id de user_corpus + la copia colectiva
correspondiente en corpus_messages cuando existe una correspondencia
inequívoca por (guild_id, message_id). Ver el docstring de la función en
db.py para el algoritmo completo y las garantías de no-ambigüedad
(UNIQUE(guild_id, message_id) en ambas tablas).

Usa una DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db
(que está trackeada en git). Para la atomicidad usa _RollbackOnErrorLock
real (no se reemplaza _db_lock), igual que tests/test_db_rollback.py."""

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


async def _seed(
    conn,
    guild_id,
    channel_id,
    author_id,
    message_id,
    author_name="user",
    content="c",
    with_corpus_message=True,
):
    """Simula lo que hace save_corpus_and_user_message: una fila en
    corpus_messages (opcional, para poder crear a mano el caso UNKNOWN) y
    una en user_corpus con channel_id ya poblado."""
    if with_corpus_message:
        await conn.execute(
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
            "VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, message_id, content),
        )
    await conn.execute(
        "INSERT INTO user_corpus (guild_id, author_id, author_name, channel_id, message_id, content) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            guild_id,
            author_id,
            author_name,
            channel_id if with_corpus_message else None,
            message_id,
            content,
        ),
    )
    await conn.commit()


async def _user_corpus_count(conn, author_id=None):
    if author_id is None:
        cur = await conn.execute("SELECT COUNT(*) FROM user_corpus")
    else:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM user_corpus WHERE author_id=?", (author_id,)
        )
    return (await cur.fetchone())[0]


async def _corpus_messages_count(conn):
    cur = await conn.execute("SELECT COUNT(*) FROM corpus_messages")
    return (await cur.fetchone())[0]


def test_varias_filas_de_un_usuario_en_un_guild_se_eliminan_todas(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 2)
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 3)
        report = await db.delete_user_data(_AUTHOR_A)
        assert report["user_corpus_deleted"] == 3
        assert await _user_corpus_count(memory_db, _AUTHOR_A) == 0

    asyncio.run(run())


def test_usuario_en_varios_guilds_se_borra_globalmente(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        await _seed(memory_db, _GUILD_B, _CHANNEL_2, _AUTHOR_A, 2)
        report = await db.delete_user_data(_AUTHOR_A)
        assert report["user_corpus_deleted"] == 2
        assert sorted(report["guild_ids"]) == [_GUILD_A, _GUILD_B]
        assert await _user_corpus_count(memory_db, _AUTHOR_A) == 0

    asyncio.run(run())


def test_borrar_autor_a_no_afecta_autor_b_mismo_guild(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_B, 2)
        await db.delete_user_data(_AUTHOR_A)
        assert await _user_corpus_count(memory_db, _AUTHOR_A) == 0
        assert await _user_corpus_count(memory_db, _AUTHOR_B) == 1

    asyncio.run(run())


def test_mismo_message_id_en_guilds_distintos_no_se_cruza(memory_db):
    async def run():
        # Autor A escribió el mensaje 42 en el guild A; en el guild B el
        # mensaje 42 es de otra persona (autor B) por pura coincidencia de id.
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 42)
        await _seed(memory_db, _GUILD_B, _CHANNEL_2, _AUTHOR_B, 42)
        await db.delete_user_data(_AUTHOR_A)
        assert await _user_corpus_count(memory_db, _AUTHOR_A) == 0
        assert await _user_corpus_count(memory_db, _AUTHOR_B) == 1
        # La copia colectiva del guild B (mensaje 42 de otra persona) debe
        # seguir intacta.
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=? AND message_id=?",
            (_GUILD_B, 42),
        )
        assert (await cur.fetchone())[0] == 1

    asyncio.run(run())


def test_traceable_borra_user_corpus_y_corpus_messages(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        report = await db.delete_user_data(_AUTHOR_A)
        assert report["user_corpus_deleted"] == 1
        assert report["corpus_messages_deleted"] == 1
        assert report["traceable_deleted"] == 1
        assert report["unknown_deleted"] == 0
        assert await _corpus_messages_count(memory_db) == 0

    asyncio.run(run())


def test_unknown_borra_user_corpus_sin_fallar_y_sin_tocar_corpus_messages_ajeno(
    memory_db,
):
    async def run():
        # UNKNOWN: mensaje del autor A que nunca tuvo (o ya perdió) su copia
        # en corpus_messages.
        await _seed(
            memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 999, with_corpus_message=False
        )
        # Copia colectiva ajena (de otro mensaje) que no debe tocarse.
        await memory_db.execute(
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
            "VALUES (?, ?, ?, ?)",
            (_GUILD_A, _CHANNEL_1, 555, "ajeno"),
        )
        await memory_db.commit()

        report = await db.delete_user_data(_AUTHOR_A)

        assert report["user_corpus_deleted"] == 1
        assert report["corpus_messages_deleted"] == 0
        assert report["unknown_deleted"] == 1
        assert await _user_corpus_count(memory_db, _AUTHOR_A) == 0
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_messages WHERE message_id=555"
        )
        assert (await cur.fetchone())[0] == 1

    asyncio.run(run())


def test_mezcla_de_trazables_y_unknown_en_el_mismo_usuario(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)  # trazable
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 2)  # trazable
        await _seed(
            memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 3, with_corpus_message=False
        )  # UNKNOWN

        report = await db.delete_user_data(_AUTHOR_A)

        assert report["user_corpus_deleted"] == 3
        assert report["corpus_messages_deleted"] == 2
        assert report["traceable_deleted"] == 2
        assert report["unknown_deleted"] == 1

    asyncio.run(run())


def test_usuario_sin_datos_devuelve_cero_sin_fallar(memory_db):
    async def run():
        return await db.delete_user_data(999_999)

    report = asyncio.run(run())
    assert report["user_corpus_deleted"] == 0
    assert report["corpus_messages_deleted"] == 0
    assert report["unknown_deleted"] == 0
    assert report["guild_ids"] == []


def test_ejecutar_dos_veces_es_idempotente(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        await _seed(
            memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 2, with_corpus_message=False
        )
        report1 = await db.delete_user_data(_AUTHOR_A)
        report2 = await db.delete_user_data(_AUTHOR_A)
        remaining = await _user_corpus_count(memory_db)
        return report1, report2, remaining

    report1, report2, remaining = asyncio.run(run())
    assert report1["user_corpus_deleted"] == 2
    assert report2["user_corpus_deleted"] == 0
    assert report2["corpus_messages_deleted"] == 0
    assert report2["guild_ids"] == []
    assert remaining == 0


def test_atomicidad_fallo_a_mitad_no_deja_borrado_parcial(memory_db, monkeypatch):
    """Se mockea el segundo DELETE (user_corpus) para que tire -- ni siquiera
    el primer DELETE (corpus_messages) debe quedar confirmado, mismo patrón
    que test_db_rollback.py::test_falla_real_en_una_secuencia_de_dos_execute_de_una_funcion_real."""

    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)

        real_execute = memory_db.execute
        call_count = 0

        def flaky_execute(sql, params=()):
            nonlocal call_count
            if sql.strip().startswith("DELETE FROM user_corpus"):
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("disco lleno simulado")
            return real_execute(sql, params)

        monkeypatch.setattr(memory_db, "execute", flaky_execute)
        with pytest.raises(RuntimeError, match="disco lleno simulado"):
            await db.delete_user_data(_AUTHOR_A)
        monkeypatch.setattr(memory_db, "execute", real_execute)

        corpus_count = await _corpus_messages_count(memory_db)
        user_count = await _user_corpus_count(memory_db)
        return corpus_count, user_count

    corpus_count, user_count = asyncio.run(run())
    # El DELETE de corpus_messages sí se ejecutó antes del fallo, pero el
    # rollback automático de _RollbackOnErrorLock debe deshacerlo también.
    assert corpus_count == 1
    assert user_count == 1


def test_rollback_no_afecta_datos_de_otros_usuarios(memory_db, monkeypatch):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_B, 2)

        real_execute = memory_db.execute
        call_count = 0

        def flaky_execute(sql, params=()):
            nonlocal call_count
            if sql.strip().startswith("DELETE FROM user_corpus"):
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("boom")
            return real_execute(sql, params)

        monkeypatch.setattr(memory_db, "execute", flaky_execute)
        with pytest.raises(RuntimeError, match="boom"):
            await db.delete_user_data(_AUTHOR_A)
        monkeypatch.setattr(memory_db, "execute", real_execute)

        return await _user_corpus_count(memory_db, _AUTHOR_B)

    assert asyncio.run(run()) == 1


def test_guilds_afectados_devueltos_correctamente(memory_db):
    async def run():
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        await _seed(memory_db, _GUILD_B, _CHANNEL_2, _AUTHOR_A, 2)
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_B, 3)  # otro autor
        return await db.delete_user_data(_AUTHOR_A)

    report = asyncio.run(run())
    assert sorted(report["guild_ids"]) == [_GUILD_A, _GUILD_B]


def test_guilds_afectados_incluye_guilds_solo_con_datos_unknown(memory_db):
    """Debe reportarse un guild aunque TODAS las filas del autor ahí sean
    UNKNOWN -- el llamador necesita invalidar igual el cache de ese guild."""

    async def run():
        await _seed(
            memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1, with_corpus_message=False
        )
        return await db.delete_user_data(_AUTHOR_A)

    report = asyncio.run(run())
    assert report["guild_ids"] == [_GUILD_A]
    assert report["corpus_messages_deleted"] == 0
    assert report["unknown_deleted"] == 1


def test_no_toca_contenido_ajeno_ni_configuracion_del_guild(memory_db):
    """Otras tablas de config del guild (settings, corpus_allowed_channels)
    y el corpus de otro autor deben quedar exactamente como estaban."""

    async def run():
        await memory_db.execute(
            "INSERT INTO settings (guild_id, chat_mode_enabled) VALUES (?, 1)",
            (_GUILD_A,),
        )
        await memory_db.execute(
            "INSERT INTO corpus_allowed_channels (guild_id, channel_id) VALUES (?, ?)",
            (_GUILD_A, _CHANNEL_1),
        )
        await memory_db.commit()

        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 1)
        await _seed(memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_B, 2)

        await db.delete_user_data(_AUTHOR_A)

        cur = await memory_db.execute(
            "SELECT chat_mode_enabled FROM settings WHERE guild_id=?", (_GUILD_A,)
        )
        settings_row = await cur.fetchone()
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_allowed_channels WHERE guild_id=?",
            (_GUILD_A,),
        )
        allowed_count = (await cur.fetchone())[0]
        return (
            settings_row,
            allowed_count,
            await _user_corpus_count(memory_db, _AUTHOR_B),
        )

    settings_row, allowed_count, other_author_count = asyncio.run(run())
    assert settings_row == (1,)
    assert allowed_count == 1
    assert other_author_count == 1


def test_usuario_con_filas_unknown_historicas_del_backfill(memory_db):
    """Escenario real de producción: filas UNKNOWN que ya pasaron por
    backfill_user_corpus_channel_id() y quedaron con channel_id NULL porque
    su message_id nunca apareció en corpus_messages."""

    async def run():
        await _seed(
            memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 111, with_corpus_message=False
        )
        await _seed(
            memory_db, _GUILD_A, _CHANNEL_1, _AUTHOR_A, 222, with_corpus_message=False
        )
        backfill_report = await db.backfill_user_corpus_channel_id()
        assert backfill_report["unknown"] == 2

        delete_report = await db.delete_user_data(_AUTHOR_A)
        assert delete_report["user_corpus_deleted"] == 2
        assert delete_report["unknown_deleted"] == 2
        assert await _user_corpus_count(memory_db, _AUTHOR_A) == 0

    asyncio.run(run())
