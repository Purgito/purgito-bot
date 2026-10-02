import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

# --- PostgreSQL de tests ----------------------------------------------------
# Los tests jamás tocan la base real: TEST_DATABASE_URL (en .env o en el
# entorno) apunta a una base aparte (`purgito_test`) y se vuelca en
# DATABASE_URL ANTES de importar config/db.
from dotenv import dotenv_values  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(__file__))
_test_url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(
    os.path.join(_ROOT, ".env")
).get("TEST_DATABASE_URL")
if not _test_url:
    raise pytest.UsageError(
        "Falta TEST_DATABASE_URL: los tests de Purgito corren contra una base "
        "PostgreSQL de pruebas (ver CONTRIBUTING.md § Tests)."
    )
os.environ["TEST_DATABASE_URL"] = _test_url
os.environ["DATABASE_URL"] = _test_url

import asyncio  # noqa: E402

import pgdb  # noqa: E402

# asyncpg ata cada conexión al event loop que la creó, y estos tests usan
# `asyncio.run()` varias veces por test (armar la base en uno, ejercitar en
# otro). Un único loop persistente para toda la sesión evita el "attached to a
# different loop" sin reescribir 1600 llamadas.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro, *, debug=None):
    return _LOOP.run_until_complete(coro)


asyncio.run = _run  # type: ignore[assignment]

_real_connect = pgdb.Database.connect.__func__


async def _connect_vaciando(cls, dsn, **kw):
    """Cada conexión nueva a la base de tests arranca VACÍA (TRUNCATE de lo que
    haya), así ningún test hereda datos del anterior."""
    database = await _real_connect(cls, dsn, **kw)
    async with database.pool.acquire() as conn:
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        if tables:
            names = ", ".join(f'"{t[0]}"' for t in tables)
            await conn.execute(f"TRUNCATE {names} RESTART IDENTITY")
    return database


pgdb.Database.connect = classmethod(_connect_vaciando)

_R2_ENV_VARS = (
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_IMAGES_BUCKET",
    "R2_IMAGES_PUBLIC_URL",
    "R2_GIFS_BUCKET",
    "R2_GIFS_PUBLIC_URL",
    "R2_BACKUP_BUCKET",
    # Esquema viejo de un solo bucket: lo lee el fallback transitorio de r2.py.
    "R2_BUCKET_NAME",
    "R2_PUBLIC_URL",
)


@pytest.fixture(autouse=True)
def _r2_env_aislado(monkeypatch):
    """Ningún test hereda la configuración de R2 del .env de quien lo corre
    (importar `config` ejecuta load_dotenv): cada test que necesite un bucket
    lo declara con monkeypatch.setenv. El cliente cacheado también se descarta,
    para que uno creado con las credenciales de un test no pase al siguiente."""
    for name in _R2_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    import r2

    monkeypatch.setattr(r2, "_client", None)
    monkeypatch.setattr(r2, "_checked", False)
