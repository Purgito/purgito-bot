"""Sección 3, tercera pasada: rollback explícito cuando algo falla a mitad
de una secuencia de escrituras bajo `_db_lock`.

Antes de este fix, `_db_lock` era un asyncio.Lock liso: su `__aexit__`
libera el lock pase lo que pase, pero NO deshace nada en la conexión de
SQLite. El disparador real (identificado en la ronda anterior) es disco
lleno a mitad de un INSERT/UPDATE, antes del commit() -- la transacción
queda abierta y sin confirmar en `_db`, la única conexión compartida, y el
PRÓXIMO caller que tome el lock terminaría confirmando también esos restos
a medio aplicar junto con su propio commit().

`_db_lock` ahora es una `_RollbackOnErrorLock` (subclase de asyncio.Lock):
si el bloque `async with` termina por una excepción, hace `_db.rollback()`
antes de soltar el lock -- una sola adquisición del lock nunca deja basura
para la siguiente.
"""

import asyncio

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    monkeypatch.setattr(db, "_db_lock", db._RollbackOnErrorLock())
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def test_db_lock_es_una_rollback_on_error_lock():
    """El propio módulo tiene que usar la subclase, no un asyncio.Lock liso
    -- si alguna vez alguien "simplifica" esto de vuelta a asyncio.Lock(),
    este test lo agarra."""
    assert isinstance(db._db_lock, db._RollbackOnErrorLock)


def test_rollback_automatico_si_algo_falla_a_mitad_de_una_secuencia(temp_db):
    """Dos adquisiciones separadas de _db_lock: la primera hace un insert y
    después tira una excepción ANTES de llegar al commit() (disco lleno a
    mitad de una secuencia de dos execute(), como pidió la consigna). La
    segunda es una escritura totalmente distinta. Si el rollback no
    hubiera pasado, el commit() de la segunda confirmaría TAMBIÉN el resto
    a medio aplicar de la primera."""

    async def run():
        conn = await db.get_db()
        await conn.execute(
            "INSERT INTO guild_counters (guild_id, name, count) VALUES (1, 'seed', 1)"
        )
        await conn.commit()

        with pytest.raises(RuntimeError, match="disco lleno"):
            async with db._db_lock:
                await conn.execute(
                    "INSERT INTO guild_counters (guild_id, name, count) VALUES (2, 'x', 1)"
                )
                raise RuntimeError("simulando disco lleno a mitad de la secuencia")
                # nunca llega al segundo execute() ni al commit()

        async with db._db_lock:
            await conn.execute(
                "INSERT INTO guild_counters (guild_id, name, count) VALUES (3, 'y', 1)"
            )
            await conn.commit()

        async with conn.execute(
            "SELECT guild_id FROM guild_counters ORDER BY guild_id"
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    # guild_id=2 nunca se confirmó -- el rollback lo descartó antes de que
    # el commit() de la operación siguiente pudiera arrastrarlo.
    assert asyncio.run(run()) == [1, 3]


def test_rollback_no_afecta_secuencias_que_terminan_bien(temp_db):
    """Que el mecanismo exista no puede romper el camino feliz: una
    secuencia de dos execute() + commit() sin excepción sigue confirmando
    todo con normalidad."""

    async def run():
        conn = await db.get_db()
        async with db._db_lock:
            await conn.execute(
                "INSERT INTO guild_counters (guild_id, name, count) VALUES (1, 'a', 1)"
            )
            await conn.execute(
                "INSERT INTO guild_counters (guild_id, name, count) VALUES (1, 'b', 2)"
            )
            await conn.commit()
        async with conn.execute(
            "SELECT name, count FROM guild_counters WHERE guild_id=1 ORDER BY name"
        ) as cur:
            return await cur.fetchall()

    rows = asyncio.run(run())
    assert rows == [("a", 1), ("b", 2)]


def test_rollback_deja_la_conexion_usable_para_la_proxima_escritura(temp_db):
    """No alcanza con que no arrastre basura -- la conexión tiene que seguir
    funcionando con total normalidad después del rollback (mismo caso que
    ya se probó a mano contra aiosqlite directo antes de implementar esto)."""

    async def run():
        conn = await db.get_db()
        with pytest.raises(ValueError):
            async with db._db_lock:
                await conn.execute(
                    "INSERT INTO guild_counters (guild_id, name, count) VALUES (9, 'roto', 1)"
                )
                raise ValueError("boom")

        # bump_counter es una función real de db.py -- confirma que el
        # resto del módulo sigue operando normal después del rollback, no
        # solo que el SQL crudo funcione.
        await db.bump_counter(9, "ok")
        return await db.get_counters(9)

    assert asyncio.run(run()) == {"ok": 1}


def test_falla_real_en_una_secuencia_de_dos_execute_de_una_funcion_real(
    temp_db, monkeypatch
):
    """Mismo escenario que pidió la consigna pero contra una función real de
    db.py (save_corpus_and_user_message, dos INSERT OR IGNORE en secuencia):
    se mockea el segundo execute() para que tire, y se confirma que ni
    siquiera el primer insert (corpus_messages) quedó confirmado."""
    call_count = 0

    async def run():
        conn = await db.get_db()
        real_execute = conn.execute

        def flaky_execute(sql, params=()):
            nonlocal call_count
            call_count += 1
            if call_count == 2 and "user_corpus" in sql:
                raise RuntimeError("disco lleno simulado en el segundo execute()")
            return real_execute(sql, params)

        # Se parchea la instancia de la conexión (no la clase Connection):
        # así no afecta a las conexiones de otros tests que corren en el
        # mismo proceso.
        monkeypatch.setattr(conn, "execute", flaky_execute)
        with pytest.raises(RuntimeError, match="disco lleno simulado"):
            await db.save_corpus_and_user_message(1, 1, 1, "autor", "hola mundo")
        monkeypatch.setattr(conn, "execute", real_execute)

        async with conn.execute("SELECT COUNT(*) FROM corpus_messages") as cur:
            corpus_count = (await cur.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM user_corpus") as cur:
            user_count = (await cur.fetchone())[0]
        return corpus_count, user_count

    corpus_count, user_count = asyncio.run(run())
    # NINGUNO de los dos insert quedó confirmado -- el primero (corpus_messages)
    # se deshizo con el rollback, aunque el que falló fue el segundo.
    assert corpus_count == 0
    assert user_count == 0
