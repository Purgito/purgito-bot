"""db.run_from_thread: consultas de db desde un hilo de trabajo.

r2._closest_fingerprint_match corre dentro de asyncio.to_thread y necesita leer
gif_objects. El pool de asyncpg vive en el loop del bot, así que un
`asyncio.run(...)` desde el hilo falla ("another operation is in progress") y la
deduplicación por similitud se desactivaba en silencio.
"""

import asyncio
import time

import pytest

import pg_support

import db
import pgdb


def test_consulta_desde_hilo_usa_el_loop_del_pool():
    async def run():
        conn = await pg_support.connect()
        db._db = conn
        db._db_loop = asyncio.get_running_loop()
        try:
            await db.get_all_gif_fingerprints()  # el pool ya hizo su primer uso
            return await asyncio.to_thread(
                lambda: db.run_from_thread(db.get_all_gif_fingerprints())
            )
        finally:
            db._db = None
            db._db_loop = None
            await conn.close()

    assert asyncio.run(run()) == []


def test_sin_loop_del_pool_cae_a_asyncio_run():
    async def uno():
        return 1

    db._db_loop = None
    assert db.run_from_thread(uno()) == 1


# --- fallar rápido en vez de congelar ---------------------------------------


def _con_pool_en_este_loop():
    async def abrir():
        conn = await pg_support.connect()
        db._db = conn
        db._db_loop = asyncio.get_running_loop()
        return conn

    return abrir


def test_desde_el_hilo_del_loop_se_rechaza_en_vez_de_colgar():
    async def run():
        conn = await _con_pool_en_este_loop()()
        try:
            coro = db.get_all_gif_fingerprints()
            with pytest.raises(RuntimeError, match="solo para hilos de trabajo"):
                db.run_from_thread(coro)
            # La corrutina rechazada se cerró: no queda "never awaited".
            assert coro.cr_frame is None
        finally:
            db._db = None
            db._db_loop = None
            await conn.close()

    asyncio.run(run())


def test_timeout_si_el_loop_no_responde():
    async def run():
        conn = await _con_pool_en_este_loop()()
        cancelada = asyncio.Event()

        async def lenta():
            try:
                await asyncio.sleep(30)
            finally:
                cancelada.set()

        try:
            t0 = time.monotonic()
            with pytest.raises(TimeoutError, match="no respondió"):
                await asyncio.to_thread(db.run_from_thread, lenta(), 0.3)
            assert time.monotonic() - t0 < 5
            await asyncio.wait_for(cancelada.wait(), 2)  # se canceló, no queda huérfana
        finally:
            db._db = None
            db._db_loop = None
            await conn.close()

    asyncio.run(run())


def test_las_excepciones_de_la_corrutina_se_propagan():
    async def run():
        conn = await _con_pool_en_este_loop()()

        async def rota():
            raise ValueError("falló la consulta")

        async def timeout_propio():
            raise TimeoutError("timeout de la query")

        try:
            with pytest.raises(ValueError, match="falló la consulta"):
                await asyncio.to_thread(db.run_from_thread, rota())
            # Un TimeoutError que viene de la propia corrutina conserva su mensaje.
            with pytest.raises(TimeoutError, match="timeout de la query"):
                await asyncio.to_thread(db.run_from_thread, timeout_propio())
        finally:
            db._db = None
            db._db_loop = None
            await conn.close()

    asyncio.run(run())


def test_loop_cerrado_o_detenido_falla_rapido():
    loop = asyncio.new_event_loop()  # existe pero no corre
    db._db_loop = loop
    try:

        async def uno():
            return 1

        with pytest.raises(RuntimeError, match="ya no corre"):
            db.run_from_thread(uno())
    finally:
        db._db_loop = None
        loop.close()


def test_no_hereda_la_transaccion_del_hilo_que_llama():
    """Un to_thread lanzado dentro de `async with _db_lock` copia el contexto;
    la corrutina no puede terminar usando la conexión de esa transacción."""

    async def run():
        conn = await _con_pool_en_este_loop()()
        lock = pgdb.TransactionLock(lambda: conn)

        async def ve_tx():
            return pgdb._tx_state.get()

        try:
            async with lock:
                assert pgdb._tx_state.get() is not None
                visto = await asyncio.to_thread(lambda: db.run_from_thread(ve_tx()))
            assert visto is None
        finally:
            db._db = None
            db._db_loop = None
            await conn.close()

    asyncio.run(run())
