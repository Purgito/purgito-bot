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

        cog = General(bot=None)
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

        cog = General(bot=None)
        await cog.guild_cleanup_task.coro(cog)

        async with conn.execute(
            "SELECT 1 FROM gif_objects WHERE content_hash=?", (content_hash,)
        ) as cur:
            return await cur.fetchone()

    assert asyncio.run(run()) is None  # la fila de gif_objects desapareció
    assert fake_r2["delete_key"] == [r2.gif_key(content_hash)]
