"""Sección 3, segunda pasada: guild_cleanup_task (cogs/general.py) borraba
los GIFs de un guild expirado con r2.delete_url(url) directo -- pero los
GIFs con content_hash son objetos content-addressed COMPARTIDOS entre
guilds (ver el comentario de gif_objects en db.py), y r2.delete_url() por
url exacta borra el objeto físico sin mirar si otro guild todavía lo
referencia. El propio docstring de r2.delete_url ya avisaba de esto
("para GIFs con content_hash usar db.release_gif_reference") -- el bug era
que guild_cleanup_task no le hacía caso.
"""

import asyncio

import pytest

import db
import r2
from cogs.general import General


class _FakeBot:
    """get_guild refleja la membresía ACTUAL del bot -- no None a secas,
    porque el fix de la ronda 1 de Sección 5 depende de poder consultarlo."""

    def __init__(self, active_guild_ids=()):
        self._active = set(active_guild_ids)

    def get_guild(self, guild_id):
        return object() if guild_id in self._active else None


class _RejoiningBot:
    """get_guild devuelve None (guild ausente) en las primeras `flip_after`
    consultas y pasa a "activo" de ahí en adelante -- simula un guild que se
    reincorpora A MITAD del loop de liberación de GIFs, no antes de que
    arranque (eso ya lo cubre _FakeBot / el test de más abajo)."""

    def __init__(self, flip_after):
        self._calls = 0
        self._flip_after = flip_after

    def get_guild(self, guild_id):
        self._calls += 1
        return object() if self._calls > self._flip_after else None


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


@pytest.fixture
def fake_r2(monkeypatch):
    calls = {"delete_key": [], "delete_url": []}

    async def fake_delete_key(key):
        calls["delete_key"].append(key)

    async def fake_delete_url(url):
        calls["delete_url"].append(url)

    monkeypatch.setattr(r2, "available", lambda: True)
    monkeypatch.setattr(r2, "public_url", lambda: "https://cdn.example.com")
    # cogs/general.py llama a r2.delete_url directo; db.py (release_gif_reference)
    # importa r2 como módulo propio -- hay que parchear ambas referencias.
    monkeypatch.setattr(r2, "delete_key", fake_delete_key)
    monkeypatch.setattr(r2, "delete_url", fake_delete_url)
    monkeypatch.setattr(db.r2, "delete_key", fake_delete_key)
    monkeypatch.setattr(db.r2, "delete_url", fake_delete_url)
    return calls


async def _seed_shared_gif(conn, guild_a, guild_b, content_hash, url, ref_count=2):
    """Dos guilds distintos referenciando el MISMO objeto de R2 -- exactamente
    el escenario que gif_objects existe para modelar."""
    await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (guild_a, url, content_hash),
    )
    await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (guild_b, url, content_hash),
    )
    await conn.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
        "VALUES (?, ?, ?, 10)",
        (content_hash, r2.gif_key(content_hash), ref_count),
    )
    await conn.commit()


async def _mark_departed(conn, guild_id, days_ago=40):
    await conn.execute(
        "INSERT INTO guild_departures (guild_id, left_at) "
        "VALUES (?, datetime('now', ?))",
        (guild_id, f"-{days_ago} days"),
    )
    await conn.commit()


def test_guild_cleanup_no_borra_el_gif_de_un_guild_que_sigue_activo(temp_db, fake_r2):
    """Guild A (expirado, se purga) y guild B (activo) comparten el mismo
    GIF. Purgar A no puede dejar a B con un link roto: el objeto de R2 solo
    se borra de verdad cuando NINGÚN guild lo referencia más."""
    guild_a, guild_b = 111, 222
    content_hash = "f" * 64
    url = f"https://cdn.example.com/{r2.gif_key(content_hash)}"

    async def run():
        conn = await db.get_db()
        await _seed_shared_gif(conn, guild_a, guild_b, content_hash, url)
        await _mark_departed(conn, guild_a)

        cog = General(bot=_FakeBot())
        await cog.guild_cleanup_task.coro(cog)

        async with conn.execute(
            "SELECT ref_count FROM gif_objects WHERE content_hash=?", (content_hash,)
        ) as cur:
            ref_row = await cur.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=? AND content_hash=?",
            (guild_b, content_hash),
        ) as cur:
            b_count = (await cur.fetchone())[0]
        return ref_row, b_count

    ref_row, b_still_has_it = asyncio.run(run())

    assert fake_r2["delete_key"] == []  # el objeto de R2 no se borró
    assert fake_r2["delete_url"] == []  # ya no se usa el borrado directo para gifs
    assert ref_row is not None
    assert ref_row[0] == 1  # se liberó SOLO la referencia de A
    assert b_still_has_it == 1  # la fila de B sigue intacta


def test_guild_cleanup_libera_el_objeto_cuando_nadie_mas_lo_referencia(
    temp_db, fake_r2
):
    """Caso base: un solo guild tenía el GIF -- al purgarlo, el objeto de R2
    sí se borra de verdad (ref_count llega a 0)."""
    guild_a = 111
    content_hash = "a" * 64
    url = f"https://cdn.example.com/{r2.gif_key(content_hash)}"

    async def run():
        conn = await db.get_db()
        await conn.execute(
            "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
            (guild_a, url, content_hash),
        )
        await conn.execute(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
            "VALUES (?, ?, 1, 10)",
            (content_hash, r2.gif_key(content_hash)),
        )
        await conn.commit()
        await _mark_departed(conn, guild_a)

        cog = General(bot=_FakeBot())
        await cog.guild_cleanup_task.coro(cog)

        async with conn.execute(
            "SELECT 1 FROM gif_objects WHERE content_hash=?", (content_hash,)
        ) as cur:
            return await cur.fetchone()

    assert asyncio.run(run()) is None  # la fila de gif_objects desapareció
    assert fake_r2["delete_key"] == [r2.gif_key(content_hash)]


def test_guild_cleanup_no_purga_un_guild_que_volvio_a_estar_activo(temp_db, fake_r2):
    """Sección 5, ronda 1: expired se arma con UNA lectura al principio del
    loop. Si el bot vuelve a este guild mientras el loop todavía no llegó a
    su turno (on_guild_join ya limpió guild_departures, pero esa lectura
    vieja no se entera), purgarlo igual sería borrar de forma irreversible
    el corpus/GIFs/config de un guild que volvió a estar activo. La fuente
    de verdad tiene que ser la membresía ACTUAL (bot.get_guild), no la lista
    ya leída."""
    guild_id = 333
    content_hash = "c" * 64
    url = f"https://cdn.example.com/{r2.gif_key(content_hash)}"

    async def run():
        conn = await db.get_db()
        await conn.execute(
            "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
            (guild_id, url, content_hash),
        )
        await conn.execute(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
            "VALUES (?, ?, 1, 10)",
            (content_hash, r2.gif_key(content_hash)),
        )
        await conn.commit()
        await _mark_departed(conn, guild_id)

        # El bot está de nuevo en este guild (simula on_guild_join habiendo
        # corrido antes de que el loop de purga llegara a su turno).
        cog = General(bot=_FakeBot(active_guild_ids=[guild_id]))
        await cog.guild_cleanup_task.coro(cog)

        async with conn.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=?", (guild_id,)
        ) as cur:
            gif_count = (await cur.fetchone())[0]
        async with conn.execute(
            "SELECT 1 FROM gif_objects WHERE content_hash=?", (content_hash,)
        ) as cur:
            object_row = await cur.fetchone()
        async with conn.execute(
            "SELECT 1 FROM guild_departures WHERE guild_id=?", (guild_id,)
        ) as cur:
            departure_row = await cur.fetchone()
        return gif_count, object_row, departure_row

    gif_count, object_row, departure_row = asyncio.run(run())

    assert fake_r2["delete_key"] == []  # nada se tocó en R2
    assert fake_r2["delete_url"] == []
    assert gif_count == 1  # el corpus del guild sigue intacto
    assert object_row is not None  # el objeto de R2 sigue referenciado
    assert departure_row is not None  # la fila de partida no se limpió acá
    # (clear_guild_departure es responsabilidad de on_guild_join, no de esta
    # tarea -- este test solo cubre que la purga se saltee, no que la
    # limpie; en producción on_guild_join ya la habría limpiado.)


def test_guild_cleanup_aborta_a_mitad_del_loop_si_el_guild_reaparece(temp_db, fake_r2):
    """Sección 3, cuarta pasada: el test de arriba solo cubre un rejoin ANTES
    de que el loop de liberación arranque. Acá el guild sigue ausente en ese
    primer chequeo (pasa el guard de arriba) pero vuelve a aparecer DESPUÉS
    de liberar el primer GIF y ANTES del segundo -- justo el hueco que un
    único chequeo al principio no puede ver, porque liberar cada GIF es un
    await real (a R2) que le da tiempo al bot de reconectarse mientras tanto.

    Sin el re-chequeo por ítem, los tres GIFs se liberarían igual y
    purge_guild_data correría igual, borrando de forma irreversible el
    corpus de un guild que ya está activo de nuevo. Con el fix, el daño
    queda acotado al primer GIF (la ventana que un único await todavía deja
    abierta, documentada en el propio código) y ni corpus_gifs ni el resto
    de la DB del guild se tocan."""
    guild_id = 444
    hashes = ["1" * 64, "2" * 64, "3" * 64]
    urls = [f"https://cdn.example.com/{r2.gif_key(h)}" for h in hashes]

    async def run():
        conn = await db.get_db()
        for h, u in zip(hashes, urls):
            await conn.execute(
                "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
                (guild_id, u, h),
            )
            await conn.execute(
                "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
                "VALUES (?, ?, 1, 10)",
                (h, r2.gif_key(h)),
            )
        await conn.commit()
        await _mark_departed(conn, guild_id)

        # flip_after=2: el chequeo de arriba del loop (llamada 1) y el
        # re-chequeo antes del primer GIF (llamada 2) todavía ven al guild
        # ausente -- recién la llamada 3 (antes del segundo GIF) lo ve activo
        # de nuevo, simulando el rejoin ocurriendo mientras se liberaba el
        # primero.
        cog = General(bot=_RejoiningBot(flip_after=2))
        await cog.guild_cleanup_task.coro(cog)

        async with conn.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=?", (guild_id,)
        ) as cur:
            gif_count = (await cur.fetchone())[0]
        async with conn.execute("SELECT content_hash FROM gif_objects") as cur:
            remaining_objects = {r[0] for r in await cur.fetchall()}
        return gif_count, remaining_objects

    gif_count, remaining_objects = asyncio.run(run())

    # Solo el primer GIF se liberó (y su objeto de R2 se borró de verdad);
    # el segundo y el tercero nunca se tocaron.
    assert fake_r2["delete_key"] == [r2.gif_key(hashes[0])]
    assert remaining_objects == {hashes[1], hashes[2]}
    # purge_guild_data NUNCA corrió: las tres filas de corpus_gifs siguen
    # ahí, aunque la primera ya apunte a un objeto de R2 borrado -- ese
    # residuo puntual es el precio de detectar el rejoin por ítem en vez de
    # solo al principio, no una purga completa perdida.
    assert gif_count == 3
