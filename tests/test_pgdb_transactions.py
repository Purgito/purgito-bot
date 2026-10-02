"""Semántica transaccional de `async with db_lock` (ver docstring de pgdb).

Cubre las trampas que PostgreSQL tiene y SQLite no: un statement fallido que
aborta toda la transacción, el uso concurrente de la única conexión del bloque
y tareas que sobreviven al bloque. Más una revisión estática del código real:
ningún `try/except` dentro de un lock sin SAVEPOINT, ningún `gather`/
`create_task` dentro de un lock.
"""

import ast
import asyncio
import glob
import os

import asyncpg
import pytest

import pg_support
import pgdb

SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")


async def _db_y_lock(max_size=3):
    d = await pg_support.connect(min_size=1, max_size=max_size)
    return d, pgdb.TransactionLock(lambda: d)


async def _filas(d, tabla="ignored_channels"):
    cur = await d.execute(f"SELECT count(*) FROM {tabla}")
    return (await cur.fetchone())[0]


INS = "INSERT INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)"


def test_statement_fallido_aborta_la_transaccion_y_el_bloque_la_deshace():
    async def run():
        d, lock = await _db_y_lock()
        with pytest.raises(asyncpg.InFailedSQLTransactionError):
            async with lock:
                await d.execute(INS, (1, 1))
                with pytest.raises(asyncpg.UniqueViolationError):
                    await d.execute(INS, (1, 1))  # PK duplicada
                # Atrapar el error NO rescata la transacción:
                await d.execute(INS, (1, 2))
        # Todo el bloque se deshizo, incluido lo que iba bien.
        assert await _filas(d) == 0
        # Y la conexión volvió limpia al pool.
        assert d.pool.get_idle_size() == d.pool.get_size()
        await d.close()

    asyncio.run(run())


def test_savepoint_permite_que_el_bloque_siga_tras_un_subpaso_fallido():
    async def run():
        d, lock = await _db_y_lock()
        async with lock:
            await d.execute(INS, (1, 1))
            with pytest.raises(asyncpg.UniqueViolationError):
                async with d.savepoint():
                    await d.execute(INS, (1, 2))  # esto se deshace con el savepoint
                    await d.execute(INS, (1, 1))  # falla
            await d.execute(INS, (1, 3))  # la transacción sigue viva
        cur = await d.execute(
            "SELECT channel_id FROM ignored_channels ORDER BY channel_id"
        )
        assert [r[0] for r in await cur.fetchall()] == [1, 3]  # el 2 se deshizo
        await d.close()

    asyncio.run(run())


def test_savepoint_exitoso_confirma_y_fuera_de_transaccion_es_noop():
    async def run():
        d, lock = await _db_y_lock()
        async with d.savepoint():  # sin transacción: no hace nada
            await d.execute(INS, (9, 9))
        async with lock:
            async with d.savepoint():
                await d.execute(INS, (1, 1))
        assert await _filas(d) == 2
        await d.close()

    asyncio.run(run())


def test_gather_dentro_del_lock_se_serializa_en_vez_de_fallar():
    async def run():
        d, lock = await _db_y_lock()
        async with lock:
            res = await asyncio.gather(
                *[d.execute(INS, (1, i)) for i in range(10)],
                d.execute("SELECT pg_sleep(0.05)"),
            )
            assert len(res) == 11
            await d.commit()
            await asyncio.gather(*[d.execute("SELECT 1") for _ in range(5)])
        assert await _filas(d) == 10
        assert d.pool.get_idle_size() == d.pool.get_size()
        await d.close()

    asyncio.run(run())


def test_tarea_que_sobrevive_al_bloque_falla_claro_y_no_toca_el_pool():
    async def run():
        d, lock = await _db_y_lock()
        listo = asyncio.Event()
        resultado: list = []

        async def rezagada():
            await listo.wait()  # corre cuando la transacción ya terminó
            try:
                await d.execute("SELECT 1")
            except Exception as e:  # noqa: BLE001
                resultado.append(e)

        async with lock:
            tarea = asyncio.create_task(rezagada())  # hereda el contexto
            await d.execute(INS, (1, 1))
        listo.set()
        await tarea
        assert len(resultado) == 1
        assert isinstance(resultado[0], RuntimeError)
        assert "ya terminó" in str(resultado[0])
        # Ni siquiera intentó usar la conexión (que ya es de otro): pool íntegro.
        assert d.pool.get_idle_size() == d.pool.get_size()
        assert await _filas(d) == 1
        await d.close()

    asyncio.run(run())


def test_commit_y_rollback_explicitos_dentro_del_bloque():
    async def run():
        d, lock = await _db_y_lock()
        async with lock:
            await d.execute(INS, (1, 1))
            await d.commit()
            await d.execute(INS, (1, 2))
            await d.rollback()  # deshace solo lo posterior al commit
            await d.execute(INS, (1, 3))
        cur = await d.execute("SELECT channel_id FROM ignored_channels ORDER BY 1")
        assert [r[0] for r in await cur.fetchall()] == [1, 3]
        await d.close()

    asyncio.run(run())


def test_sin_transacciones_abiertas_tras_excepciones_variadas():
    async def run():
        d, lock = await _db_y_lock()
        for exc in (ValueError, asyncpg.UniqueViolationError, asyncio.CancelledError):
            try:
                async with lock:
                    await d.execute(INS, (5, 5))
                    raise exc("x")
            except BaseException:  # noqa: BLE001
                pass
        async with d.pool.acquire() as c:
            abiertas = await c.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
            )
        assert abiertas == 0
        assert await _filas(d) == 0
        await d.close()

    asyncio.run(run())


# --- revisión estática del código real --------------------------------------


def _bloques_con_lock():
    for path in sorted(
        glob.glob(os.path.join(SRC, "*.py"))
        + glob.glob(os.path.join(SRC, "cogs", "*.py"))
    ):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncWith) and any(
                "_db_lock" in ast.unparse(i.context_expr) for i in node.items
            ):
                yield os.path.relpath(path, SRC), node


def test_ningun_try_dentro_de_un_lock_atrapa_sin_savepoint():
    """Regla: un `except` que NO relanza, dentro de un lock, solo es válido si
    el `try` envuelve un `db.savepoint()`; si no, deja la transacción abortada."""
    malos = []
    for rel, bloque in _bloques_con_lock():
        for n in ast.walk(bloque):
            if not isinstance(n, ast.Try):
                continue
            usa_db = any(
                isinstance(c, ast.Call)
                and ast.unparse(c.func).endswith(("execute", "executemany"))
                for b in n.body
                for c in ast.walk(b)
            )
            savepoint = any("savepoint" in ast.unparse(b) for b in n.body)
            relanza = all(
                any(isinstance(x, ast.Raise) for x in ast.walk(h)) for h in n.handlers
            )
            if usa_db and not savepoint and n.handlers and not relanza:
                malos.append(f"{rel}:{n.lineno}")
    assert not malos, f"except sin savepoint dentro de _db_lock: {malos}"


def test_ningun_lock_lanza_tareas_paralelas_ni_hace_red():
    prohibidos = (
        "gather",
        "create_task",
        "ensure_future",
        "_spawn",
        "to_thread",
        "sleep",
    )
    malos = []
    for rel, bloque in _bloques_con_lock():
        for n in ast.walk(bloque):
            if isinstance(n, ast.Call) and any(
                ast.unparse(n.func).endswith(p) for p in prohibidos
            ):
                malos.append(f"{rel}:{n.lineno} {ast.unparse(n.func)}")
    assert not malos, f"patrón prohibido dentro de _db_lock: {malos}"


def test_la_revision_estatica_encuentra_los_bloques():
    # Si el AST dejara de reconocer el lock, los dos tests de arriba pasarían en vacío.
    assert sum(1 for _ in _bloques_con_lock()) > 100
