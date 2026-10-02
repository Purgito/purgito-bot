"""Capa de acceso a PostgreSQL (asyncpg) con la forma que ya usaba db.py.

db.py nació sobre una única conexión aiosqlite compartida: ``await
db.execute(sql, params)``, ``async with db.execute(...) as cur``,
``cur.fetchone()/fetchall()/rowcount/lastrowid`` y ``await db.commit()``.
Este módulo conserva esa interfaz sobre un *pool* de asyncpg, así las ~330
queries de db.py no se reescriben y la semántica transaccional sigue siendo
explícita:

* Fuera de una transacción, cada ``execute`` toma una conexión del pool, corre
  UN statement (autocommit) y la devuelve. Las lecturas sueltas no se bloquean
  entre sí.
* ``async with db_lock:`` (ver ``TransactionLock``) abre una transacción en una
  conexión del pool y la deja disponible para todo ``execute`` del mismo
  contexto (ContextVar). ``commit()`` la confirma y abre otra; salir del bloque
  por una excepción hace ROLLBACK, salir bien confirma lo pendiente.

Reglas de uso de ``async with db_lock:`` (la transacción vive en un
ContextVar, así que la ven TODAS las tareas que nazcan dentro del bloque):

* Un statement que falla aborta TODA la transacción (PostgreSQL); los
  siguientes levantan ``InFailedSQLTransactionError``. Si un subpaso puede
  fallar y el bloque debe seguir, envuélvelo en ``async with db.savepoint():``.
* Los statements de una transacción se serializan sobre su única conexión:
  ``asyncio.gather`` dentro del bloque es seguro pero NO paraleliza.
* Una tarea (``create_task``) creada dentro del bloque no puede sobrevivirlo:
  si usa la base cuando la transacción ya terminó, ``execute`` levanta
  ``RuntimeError`` (en vez de tocar una conexión que ya volvió al pool).
* No hagas red, ``sleep`` ni nada lento dentro del bloque: retiene el lock
  global y una conexión del pool.
* Las lecturas sueltas (sin ``async with db_lock``) usan el pool y no ven lo
  que la transacción abierta aún no confirmó.

Dialecto: las queries se escriben en PostgreSQL con dos azúcares que traduce
``translate()`` -- el placeholder ``?`` (-> ``$1``, ``$2``...) y ``INSERT OR
IGNORE`` (-> ``ON CONFLICT DO NOTHING``).
"""

import asyncio
import contextlib
import contextvars
import functools
import logging
import re

import asyncpg

log = logging.getLogger(__name__)

# Cuánto espera un execute()/bloque transaccional por una conexión libre del
# pool antes de fallar con TimeoutError. Sin tope, un pool agotado cuelga todo
# el bot sin dejar rastro en el log (y bajo TransactionLock, con el lock global
# tomado). 30 s es la mitad del command_timeout (60 s): holgado para un pico de
# carga, pero un pool realmente agotado se nota en el log en vez de congelarse.
ACQUIRE_TIMEOUT = 30.0

_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
_INSERT_OR_IGNORE_RE = re.compile(r"^(\s*)INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)
_READ_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_STATUS_COUNT_RE = re.compile(r"(\d+)\s*$")


def _replace_placeholders(sql: str) -> str:
    """``?`` -> ``$n`` salteando literales de texto ('...') y comentarios."""
    out: list[str] = []
    n = 0
    i = 0
    length = len(sql)
    while i < length:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < length:
                if sql[j] == "'":
                    if j + 1 < length and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j = length if j == -1 else j
            out.append(sql[i:j])
            i = j
        elif ch == "?":
            n += 1
            out.append(f"${n}")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


@functools.lru_cache(maxsize=1024)
def translate(sql: str) -> str:
    sql = sql.rstrip().rstrip(";")
    if _INSERT_OR_IGNORE_RE.match(sql):
        sql = _INSERT_OR_IGNORE_RE.sub(r"\1INSERT INTO", sql, count=1)
        sql += " ON CONFLICT DO NOTHING"
    return _replace_placeholders(sql)


_INT_TYPES = {"int2", "int4", "int8"}
_FLOAT_TYPES = {"float4", "float8", "numeric"}
_TEXT_TYPES = {"text", "varchar", "bpchar"}


def _coerce(stmt, params: tuple) -> tuple:
    """Afinidad de tipos a la SQLite: SQLite aceptaba un int en una columna TEXT
    y un "123" en una INTEGER; asyncpg es estricto y levanta DataError. El
    código de Purgito (sobre todo webapi, con IDs que llegan como string del
    JSON) depende de esa flexibilidad, así que se normaliza acá, una sola vez,
    contra los tipos que el servidor declara para cada parámetro."""
    expected = stmt.get_parameters()
    if len(expected) != len(params):
        return params  # que lo reporte asyncpg con su mensaje habitual
    out = []
    for typ, val in zip(expected, params):
        name = typ.name
        if val is None or isinstance(val, bool) and name not in _INT_TYPES:
            pass
        elif name in _INT_TYPES:
            if isinstance(val, bool):
                val = int(val)
            elif isinstance(val, str):
                try:
                    val = int(val.strip())
                except ValueError:
                    pass
            elif isinstance(val, float) and val.is_integer():
                val = int(val)
        elif name in _TEXT_TYPES:
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                val = str(val)
        elif name in _FLOAT_TYPES:
            if isinstance(val, (int, str)) and not isinstance(val, bool):
                try:
                    val = float(val)
                except ValueError:
                    pass
        out.append(val)
    return tuple(out)


def _rowcount(status: str) -> int:
    """'INSERT 0 1' / 'UPDATE 3' / 'DELETE 0' -> cantidad de filas."""
    m = _STATUS_COUNT_RE.search(status or "")
    return int(m.group(1)) if m else -1


class Cursor:
    """Resultado ya materializado de un execute() (como aiosqlite.Cursor)."""

    def __init__(self, rows=None, rowcount: int = -1, lastrowid: int | None = None):
        self._rows = [tuple(r) for r in (rows or [])]
        self._pos = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    async def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    async def fetchall(self):
        rows = self._rows[self._pos :]
        self._pos = len(self._rows)
        return rows

    async def close(self):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        row = await self.fetchone()
        if row is None:
            raise StopAsyncIteration
        return row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Execution:
    """``await db.execute(...)`` y ``async with db.execute(...) as cur`` a la vez."""

    def __init__(self, coro):
        self._coro = coro
        self._cursor: Cursor | None = None

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        self._cursor = await self._coro
        return self._cursor

    async def __aexit__(self, *exc):
        return False


class Database:
    """Pool de PostgreSQL con la interfaz de una conexión aiosqlite."""

    def __init__(self, pool: "asyncpg.Pool", acquire_timeout: float = ACQUIRE_TIMEOUT):
        self.pool = pool
        self.acquire_timeout = acquire_timeout

    def _acquire(self):
        """``async with self._acquire() as conn``: conexión del pool con tope de
        espera (ver ACQUIRE_TIMEOUT)."""
        return self.pool.acquire(timeout=self.acquire_timeout)

    @classmethod
    async def connect(
        cls, dsn: str, *, min_size: int = 2, max_size: int = 10
    ) -> "Database":
        pool = await asyncpg.create_pool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=60,
            max_inactive_connection_lifetime=300,
        )
        return cls(pool)

    async def close(self):
        await self.pool.close()

    # -- ejecución ---------------------------------------------------------
    def execute(self, sql: str, params=()) -> _Execution:
        return _Execution(self._execute(sql, tuple(params or ())))

    @contextlib.asynccontextmanager
    async def _conn(self):
        """Conexión para un statement: la de la transacción abierta (con su
        mutex, ver _Tx) o una suelta del pool."""
        txs = _tx_state.get()
        if txs is not None:
            txs.check_open()
            async with txs.mutex:
                yield txs.conn
            return
        async with self._acquire() as conn:
            yield conn

    async def _execute(self, sql: str, params: tuple) -> Cursor:
        async with self._conn() as conn:
            return await self._run(conn, sql, params)

    @staticmethod
    async def _run(conn: "asyncpg.Connection", sql: str, params: tuple) -> Cursor:
        pg_sql = translate(sql)
        m = _INSERT_RE.match(pg_sql)
        wants_id = (
            m is not None
            and "RETURNING" not in pg_sql.upper()
            and m.group(1).lower() in _IDENTITY_TABLES
        )
        if wants_id:
            pg_sql += " RETURNING id"
        stmt = await conn.prepare(pg_sql)  # asyncpg cachea el statement por SQL
        rows = await stmt.fetch(*_coerce(stmt, params))
        if _READ_RE.match(pg_sql):
            return Cursor(rows)
        if wants_id:
            return Cursor(
                None, rowcount=len(rows), lastrowid=rows[0][0] if rows else None
            )
        if "RETURNING" in pg_sql.upper():
            return Cursor(rows, rowcount=len(rows))
        return Cursor(None, rowcount=_rowcount(stmt.get_statusmsg()))

    async def executemany(self, sql: str, seq_params) -> None:
        pg_sql = translate(sql)
        rows = [tuple(p) for p in seq_params]
        if not rows:
            return
        async with self._conn() as conn:
            await self._many(conn, pg_sql, rows)

    @staticmethod
    async def _many(conn, pg_sql, rows):
        stmt = await conn.prepare(pg_sql)
        await conn.executemany(pg_sql, [_coerce(stmt, r) for r in rows])

    async def apply_schema(self, script: str, upgrades=()) -> None:
        """Aplica el esquema (idempotente) y registra qué tablas tienen `id`
        identity, para que execute() devuelva ``lastrowid`` en sus INSERT."""
        await self.executescript(script)
        for stmt in upgrades:
            await self.execute(stmt)
        async with self._acquire() as conn:
            rows = await conn.fetch(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND column_name = 'id' "
                "AND is_identity = 'YES'"
            )
        _IDENTITY_TABLES.clear()
        _IDENTITY_TABLES.update(r[0] for r in rows)

    async def executescript(self, script: str) -> None:
        """DDL multi-statement (sin parámetros): asyncpg lo acepta en un solo
        ``execute``."""
        async with self._conn() as conn:
            await conn.execute(script)

    # -- transacciones -----------------------------------------------------
    @contextlib.asynccontextmanager
    async def savepoint(self):
        """SAVEPOINT dentro de la transacción abierta: si el bloque falla, solo
        se deshace lo suyo y el resto de la transacción sigue viva. En
        PostgreSQL un statement fallido deja abortada TODA la transacción (en
        SQLite no), así que un `try/except` alrededor de un execute() que puede
        fallar necesita esto. Fuera de una transacción es un no-op."""
        txs = _tx_state.get()
        if txs is None:
            yield
            return
        txs.check_open()
        sp = txs.conn.transaction()
        async with txs.mutex:
            await sp.start()
        try:
            yield
        except BaseException:
            async with txs.mutex:
                await sp.rollback()
            raise
        else:
            async with txs.mutex:
                await sp.commit()

    async def commit(self):
        """Confirma la transacción abierta por ``TransactionLock`` (si hay) y
        abre otra para lo que siga dentro del mismo bloque. Fuera de un bloque
        no hace nada: cada statement ya se confirmó solo."""
        txs = _tx_state.get()
        if txs is None:
            return
        txs.check_open()
        async with txs.mutex:
            await txs.commit()
            await txs.begin()

    async def rollback(self):
        txs = _tx_state.get()
        if txs is None:
            return
        txs.check_open()
        async with txs.mutex:
            await txs.rollback()
            await txs.begin()


# Tablas con `id` identity: un INSERT sobre ellas devuelve el id generado como
# ``lastrowid`` (RETURNING id). db.init_db la llena leyendo el catálogo.
_IDENTITY_TABLES: set[str] = set()


class _Tx:
    def __init__(self, conn: "asyncpg.Connection"):
        self.conn = conn
        # Una conexión de asyncpg solo admite una operación a la vez: las
        # tareas que comparten esta transacción (p. ej. un gather dentro del
        # bloque) se turnan en vez de fallar con "another operation is in
        # progress".
        self.mutex = asyncio.Lock()
        self.closed = False
        self.tx: "asyncpg.transaction.Transaction | None" = None

    def check_open(self):
        if self.closed:
            raise RuntimeError(
                "La transacción de `async with db_lock` ya terminó: una tarea "
                "creada dentro del bloque lo sobrevivió y quiere usar la base. "
                "Haz la consulta antes de salir del bloque o espérala dentro."
            )

    async def begin(self):
        self.tx = self.conn.transaction()
        await self.tx.start()

    async def commit(self):
        if self.tx is not None:
            tx, self.tx = self.tx, None
            await tx.commit()

    async def rollback(self):
        if self.tx is not None:
            tx, self.tx = self.tx, None
            await tx.rollback()


_tx_state: contextvars.ContextVar["_Tx | None"] = contextvars.ContextVar(
    "pgdb_tx_state", default=None
)


class TransactionLock(asyncio.Lock):
    """Lock global de escritura + transacción de PostgreSQL.

    ``async with lock:`` serializa las escrituras como antes (db.py cuenta con
    esa exclusión para sus read-modify-write: ref_count de GIFs, topes de
    corpus, etc.), toma una conexión del pool y abre una transacción que ven
    todos los ``execute`` del bloque. Excepción -> ROLLBACK; salida normal ->
    COMMIT de lo pendiente. ``get_database`` es un callable que devuelve el
    ``Database`` activo (el módulo db lo reemplaza al abrir/cerrar)."""

    def __init__(self, get_database):
        super().__init__()
        self._get_database = get_database
        self._release_stack: list = []

    async def __aenter__(self):
        await super().__aenter__()
        try:
            database = self._get_database()
            conn = await database.pool.acquire(timeout=database.acquire_timeout)
            try:
                tx = _Tx(conn)
                await tx.begin()
            except BaseException:
                # BEGIN falló (o se canceló): la conexión ya salió del pool y
                # nadie más la va a devolver. release() la resetea (descarta
                # cualquier transacción a medias) o la cierra si está rota.
                await database.pool.release(conn)
                raise
        except BaseException:
            super().release()
            raise
        self._release_stack.append((database, conn, tx, _tx_state.set(tx)))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        database, conn, tx, tok_state = self._release_stack.pop()
        try:
            async with tx.mutex:
                if exc_type is not None:
                    try:
                        await tx.rollback()
                    except Exception:
                        log.exception("Fallo haciendo rollback bajo db_lock")
                else:
                    await tx.commit()
        finally:
            tx.closed = True
            _tx_state.reset(tok_state)
            try:
                await database.pool.release(conn)
            finally:
                super().release()
        return False
