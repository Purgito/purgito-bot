"""Pool de PostgreSQL: ninguna conexión adquirida por TransactionLock puede
quedar retenida, falle lo que falle, y un pool agotado tiene que fallar con
TimeoutError en vez de colgar al bot."""

import asyncio

import pytest

import pg_support
import pgdb


async def _estados_de_transaccion(conn_db: pgdb.Database) -> int:
    """Conexiones del pool en 'idle in transaction' (o abortada) según el servidor."""
    async with conn_db.pool.acquire() as c:
        return await c.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
        )


def test_begin_fallido_no_fuga_conexiones(monkeypatch):
    async def run():
        d = await pg_support.connect(min_size=1, max_size=3)
        lock = pgdb.TransactionLock(lambda: d)
        real_begin = pgdb._Tx.begin

        async def begin_roto(self):
            raise ConnectionResetError("BEGIN simulado roto")

        monkeypatch.setattr(pgdb._Tx, "begin", begin_roto)
        # Más fallos que max_size: con la fuga, el pool quedaba agotado.
        for _ in range(7):
            with pytest.raises(ConnectionResetError):
                async with lock:
                    pytest.fail("no debería entrar al bloque")
            assert not lock.locked()
        monkeypatch.setattr(pgdb._Tx, "begin", real_begin)

        # Todas las conexiones volvieron: el pool entero está libre...
        assert d.pool.get_idle_size() == d.pool.get_size()
        # ...sigue siendo usable, en lectura y en transacción...
        cur = await asyncio.wait_for(d.execute("SELECT 1"), 5)
        assert await cur.fetchone() == (1,)
        async with lock:
            await d.execute(
                "INSERT INTO ignored_channels (guild_id, channel_id) VALUES (1, 1)"
            )
        cur = await d.execute("SELECT count(*) FROM ignored_channels")
        assert await cur.fetchone() == (1,)
        # ...y no quedó ninguna transacción abierta en el servidor.
        assert await _estados_de_transaccion(d) == 0
        await d.close()

    asyncio.run(run())


def test_begin_cancelado_no_fuga_la_conexion():
    async def run():
        d = await pg_support.connect(min_size=1, max_size=2)
        lock = pgdb.TransactionLock(lambda: d)
        # Otra tarea sostiene el pool entero mientras la cancelamos esperando.
        async with d.pool.acquire() as a, d.pool.acquire():
            t = asyncio.create_task(_entrar(lock))
            await asyncio.sleep(0.1)
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t
            assert not lock.locked()
            del a
        assert d.pool.get_idle_size() == d.pool.get_size()
        await d.close()

    async def _entrar(lock):
        async with lock:
            pass

    asyncio.run(run())


def test_pool_agotado_falla_con_timeout_y_libera_el_lock():
    async def run():
        d = await pg_support.connect(min_size=1, max_size=1)
        d.acquire_timeout = 0.3
        lock = pgdb.TransactionLock(lambda: d)
        async with d.pool.acquire():  # el único slot, retenido
            with pytest.raises(asyncio.TimeoutError):
                await d.execute("SELECT 1")
            with pytest.raises(asyncio.TimeoutError):
                async with lock:
                    pytest.fail("no debería entrar al bloque")
            assert not lock.locked()
        # Liberado el slot, todo vuelve a funcionar.
        cur = await d.execute("SELECT 1")
        assert await cur.fetchone() == (1,)
        async with lock:
            await d.execute("SELECT 1")
        await d.close()

    asyncio.run(run())


def test_el_timeout_por_defecto_es_razonable():
    # Ni tan corto que falle bajo un pico normal, ni tan largo que parezca colgado.
    assert 10 <= pgdb.ACQUIRE_TIMEOUT <= 60
