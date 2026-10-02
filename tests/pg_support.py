"""Soporte de tests para PostgreSQL.

Los tests corren contra la base `purgito_test` (TEST_DATABASE_URL en .env o en
el entorno), NUNCA contra la de producción: conftest.py fija DATABASE_URL a esa
base antes de importar nada y se niega a seguir si no está definida.
"""

import os

import pgdb

TEST_URL = os.environ.get("TEST_DATABASE_URL", "")


async def connect(*, min_size: int = 1, max_size: int = 4) -> pgdb.Database:
    """Base limpia con el esquema aplicado (reemplaza al viejo
    `aiosqlite.connect(":memory:")` + `executescript(db.SCHEMA)`)."""
    import db  # import diferido: db lee DATABASE_URL al usarse, no al importarse

    conn = await pgdb.Database.connect(TEST_URL, min_size=min_size, max_size=max_size)
    await conn.apply_schema(db.SCHEMA)
    return conn


def sync_connect():
    """Conexión síncrona (pgsync) a la base de tests, vacía y con el esquema
    aplicado: reemplaza al viejo `sqlite3.connect(":memory:")` +
    `executescript(db.SCHEMA)` de los tests de scripts/."""
    import db
    import pgsync

    conn = pgsync.connect(TEST_URL)
    names = [
        r[0]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    ]
    if names:
        conn.executescript(
            "TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " RESTART IDENTITY"
        )
    conn.executescript(db.SCHEMA)
    conn.commit()
    return conn
