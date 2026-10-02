"""Conexión PostgreSQL SÍNCRONA para los scripts operativos (scripts/*.py).

Mismo dialecto y misma forma que usaba sqlite3 en esos scripts
(``conn.execute(sql, params).fetchall()``, ``conn.commit()``), pero sobre
asyncpg: reutiliza ``pgdb.translate`` (``?`` -> ``$n``, INSERT OR IGNORE) y
``pgdb._coerce`` (afinidad de tipos), y corre en un event loop privado. El bot
NO usa este módulo; usa pgdb.Database.

Una transacción se abre sola con el primer statement y termina en
``commit()``/``rollback()``/``close()`` (sin commit, close() descarta).
"""

import asyncio
import contextlib
import os
import subprocess
from urllib.parse import unquote, urlparse

import asyncpg

import pgdb


class SyncCursor:
    def __init__(self, rows, rowcount, lastrowid=None):
        self._rows = [tuple(r) for r in rows]
        self._pos = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        self._pos += 1
        return self._rows[self._pos - 1]

    def fetchall(self):
        rows = self._rows[self._pos :]
        self._pos = len(self._rows)
        return rows

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


class SyncConnection:
    def __init__(self, dsn: str):
        self._loop = asyncio.new_event_loop()
        self._conn: asyncpg.Connection = self._run(asyncpg.connect(dsn))
        self._tx = None
        self._run(self._load_identity_tables())

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    async def _load_identity_tables(self):
        rows = await self._conn.fetch(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND column_name = 'id' "
            "AND is_identity = 'YES'"
        )
        pgdb._IDENTITY_TABLES.clear()
        pgdb._IDENTITY_TABLES.update(r[0] for r in rows)

    async def _begin(self):
        if self._tx is None:
            self._tx = self._conn.transaction()
            await self._tx.start()

    def execute(self, sql: str, params=()) -> SyncCursor:
        async def go():
            # Como sqlite3: la transacción se abre con el primer statement que
            # escribe; las lecturas sueltas no dejan una transacción colgada.
            if not pgdb._READ_RE.match(sql):
                await self._begin()
            cur = await pgdb.Database._run(self._conn, sql, tuple(params or ()))
            return SyncCursor(cur._rows, cur.rowcount, cur.lastrowid)

        return self._run(go())

    def executemany(self, sql: str, seq_params) -> None:
        async def go():
            await self._begin()
            await pgdb.Database._many(
                self._conn, pgdb.translate(sql), [tuple(p) for p in seq_params]
            )

        self._run(go())

    def executescript(self, script: str) -> None:
        self._run(self._conn.execute(script))

    def commit(self) -> None:
        if self._tx is not None:
            tx, self._tx = self._tx, None
            self._run(tx.commit())

    def rollback(self) -> None:
        if self._tx is not None:
            tx, self._tx = self._tx, None
            self._run(tx.rollback())

    def close(self) -> None:
        try:
            self.rollback()
            self._run(self._conn.close())
        finally:
            self._loop.close()

    @contextlib.contextmanager
    def savepoint(self):
        """SAVEPOINT: si el bloque falla solo se deshace lo suyo (en PostgreSQL
        un statement fallido aborta toda la transacción, en SQLite no)."""
        self._run(self._begin())
        sp = self._conn.transaction()
        self._run(sp.start())
        try:
            yield
        except BaseException:
            self._run(sp.rollback())
            raise
        else:
            self._run(sp.commit())


def connect(dsn: str | None = None, *, read_only: bool = False) -> SyncConnection:
    dsn = dsn or os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("Falta DATABASE_URL (postgresql://usuario:clave@host/base)")
    conn = SyncConnection(dsn)
    if read_only:
        conn.executescript("SET default_transaction_read_only = on")
    return conn


def pg_env(dsn: str) -> dict:
    """Variables PG* para los clientes de línea de comandos (pg_dump,
    pg_restore, psql): así la clave no aparece en `ps`."""
    u = urlparse(dsn)
    env = dict(os.environ)
    env.update(
        PGHOST=u.hostname or "127.0.0.1",
        PGPORT=str(u.port or 5432),
        PGUSER=unquote(u.username or ""),
        PGDATABASE=(u.path or "/").lstrip("/"),
    )
    if u.password:
        env["PGPASSWORD"] = unquote(u.password)
    return env


def dump(dsn: str, dest: str) -> str:
    """pg_dump en formato custom (restaurable con pg_restore), 0600."""
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        subprocess.run(
            ["pg_dump", "-Fc", "--no-owner", "-f", dest],
            env=pg_env(dsn),
            check=True,
        )
    except BaseException:
        os.unlink(dest)
        raise
    return dest
