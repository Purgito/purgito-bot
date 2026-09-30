"""resolve_gifs_task tomaba `ORDER BY id LIMIT 25` de los GIFs sin media_url,
sin backoff ni tope de reintentos: 25 GIFs permanentemente irresolubles (link
muerto, host no soportado) ocupaban TODA la cola en cada corrida, cada 90
segundos, para siempre -- y los GIFs nuevos (id más alto) nunca llegaban a
entrar. Ahora cada fallo suma un intento con espera creciente y, agotados los
intentos, el GIF sale de la cola."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import aiosqlite
import pytest

import db
from cogs import gifs as gifs_mod

_GUILD = 1


@pytest.fixture
def memory_db(monkeypatch):
    async def open_db():
        conn = await aiosqlite.connect(":memory:")
        await conn.executescript(db.SCHEMA)
        await conn.commit()
        return conn

    conn = asyncio.run(open_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _add(conn, n, media_url=None, attempts=0, retry_at=None):
    await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, media_url, resolve_attempts, resolve_retry_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (_GUILD, f"https://tenor.com/view/g-{n}", media_url, attempts, retry_at),
    )
    await conn.commit()


async def _row(conn, n):
    async with conn.execute(
        "SELECT resolve_attempts, resolve_retry_at, media_url FROM corpus_gifs WHERE url=?",
        (f"https://tenor.com/view/g-{n}",),
    ) as cur:
        return await cur.fetchone()


async def _ids(limit=25):
    return [
        g["url"].rsplit("-", 1)[1] for g in await db.get_unresolved_gifs(limit=limit)
    ]


def test_un_gif_nuevo_entra_en_la_cola(memory_db):
    async def run():
        await _add(memory_db, 1)
        return await _ids()

    assert asyncio.run(run()) == ["1"]


def test_los_gifs_muertos_ya_no_le_quitan_el_lugar_a_los_nuevos(memory_db):
    """El bug original: 30 irresolubles con id bajo + 1 GIF nuevo."""

    async def run():
        for n in range(1, 31):
            await _add(memory_db, n, attempts=db.MAX_GIF_RESOLVE_ATTEMPTS)
        await _add(memory_db, 99)
        return await _ids(limit=25)

    assert asyncio.run(run()) == ["99"]


def test_un_fallo_agenda_el_reintento_con_espera_creciente(memory_db):
    async def run():
        await _add(memory_db, 1)
        gid = (await db.get_unresolved_gifs())[0]["id"]
        esperas = []
        for _ in range(4):
            antes = datetime.now(timezone.utc)
            await db.mark_gif_resolve_failed(gid)
            attempts, retry_at, _ = await _row(memory_db, 1)
            esperas.append((attempts, datetime.fromisoformat(retry_at) - antes))
        return esperas

    esperas = asyncio.run(run())
    assert [a for a, _ in esperas] == [1, 2, 3, 4]
    minutos = [round(e.total_seconds() / 60) for _, e in esperas]
    assert minutos == [15, 30, 60, 120]


def test_la_espera_tiene_techo(memory_db):
    async def run():
        await _add(memory_db, 1, attempts=db.MAX_GIF_RESOLVE_ATTEMPTS - 1)
        gid = (await db.get_unresolved_gifs())[0]["id"]
        antes = datetime.now(timezone.utc)
        await db.mark_gif_resolve_failed(gid)
        _, retry_at, _ = await _row(memory_db, 1)
        return datetime.fromisoformat(retry_at) - antes

    assert asyncio.run(run()) <= timedelta(hours=12, seconds=5)


def test_no_se_reintenta_antes_de_que_venza_la_espera(memory_db):
    async def run():
        futuro = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        pasado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await _add(memory_db, 1, attempts=1, retry_at=futuro)
        await _add(memory_db, 2, attempts=1, retry_at=pasado)
        return await _ids()

    assert asyncio.run(run()) == ["2"]


def test_agotados_los_intentos_sale_de_la_cola_para_siempre(memory_db):
    async def run():
        await _add(memory_db, 1)
        gid = (await db.get_unresolved_gifs())[0]["id"]
        for _ in range(db.MAX_GIF_RESOLVE_ATTEMPTS):
            await memory_db.execute(
                "UPDATE corpus_gifs SET resolve_retry_at=NULL WHERE id=?", (gid,)
            )
            await memory_db.commit()
            assert await _ids() == ["1"]  # todavía reintenta
            await db.mark_gif_resolve_failed(gid)
        await memory_db.execute(
            "UPDATE corpus_gifs SET resolve_retry_at=NULL WHERE id=?", (gid,)
        )
        await memory_db.commit()
        return await _ids()

    assert asyncio.run(run()) == []


def test_los_reintentos_van_despues_de_los_gifs_nuevos(memory_db):
    async def run():
        pasado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await _add(memory_db, 1, attempts=3, retry_at=pasado)  # id bajo, ya reintentado
        await _add(memory_db, 2)  # nuevo
        return await _ids()

    assert asyncio.run(run()) == ["2", "1"]


def test_marcar_un_gif_borrado_no_levanta(memory_db):
    asyncio.run(db.mark_gif_resolve_failed(12345))


def test_la_consulta_por_guild_sigue_ignorando_el_backoff(memory_db):
    """La variante por guild (con guild_id) no es la cola de la tarea: devuelve
    todos los pendientes del servidor."""

    async def run():
        await _add(memory_db, 1, attempts=db.MAX_GIF_RESOLVE_ATTEMPTS)
        return [g["url"] for g in await db.get_unresolved_gifs(_GUILD)]

    assert asyncio.run(run()) == ["https://tenor.com/view/g-1"]


@pytest.mark.parametrize(
    "url, esperado",
    [
        ("https://media.tenor.com/x.png", True),
        ("https://media.tenor.com/x.JPG", True),
        ("https://media.tenor.com/x.webp", True),
        ("https://media.tenor.com/x.gif", False),
        ("https://media.tenor.com/x.mp4", False),
        (None, False),
        ("", False),
    ],
)
def test_is_static_media_url(url, esperado):
    assert db.is_static_media_url(url) is esperado


# ── la tarea ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sin_esperas(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(gifs_mod.asyncio, "sleep", no_sleep)


def _correr_tarea(resultado):
    async def fake_resolve(url):
        return resultado

    cog = gifs_mod.Gifs(SimpleNamespace())

    async def run():
        orig = gifs_mod.resolve_media_url
        gifs_mod.resolve_media_url = fake_resolve
        try:
            await cog.resolve_gifs_task.coro(cog)
        finally:
            gifs_mod.resolve_media_url = orig

    asyncio.run(run())


def test_tarea_sin_resultado_cuenta_un_intento(memory_db, sin_esperas):
    asyncio.run(_add(memory_db, 1))
    _correr_tarea(None)
    attempts, retry_at, media = asyncio.run(_row(memory_db, 1))
    assert attempts == 1 and retry_at is not None and media is None


def test_tarea_con_gif_animado_resuelve_sin_contar_intento(memory_db, sin_esperas):
    asyncio.run(_add(memory_db, 1))
    _correr_tarea("https://media1.tenor.com/m/x.gif")
    attempts, retry_at, media = asyncio.run(_row(memory_db, 1))
    assert attempts == 0 and retry_at is None
    assert media == "https://media1.tenor.com/m/x.gif"


def test_tarea_con_miniatura_estatica_guarda_y_cuenta_intento(memory_db, sin_esperas):
    """Si solo se consigue una miniatura .png, el GIF seguiría "sin resolver"
    para siempre: tiene que contar como intento, igual que un fallo."""
    asyncio.run(_add(memory_db, 1))
    _correr_tarea("https://media.tenor.com/x.png")
    attempts, _, media = asyncio.run(_row(memory_db, 1))
    assert attempts == 1
    assert media == "https://media.tenor.com/x.png"
