"""Sección 3, primera pasada: instancias del patrón "lock no atómico" que ya
tumbó al watermark de premium (Sección 2), encontradas en otras secuencias
read-modify-write de db.py. Las tres acá comparten la misma forma: una
lectura que decide QUÉ filas tocar vivía separada (sin lock, o con su propio
lock independiente) de la escritura que las tocaba de verdad -- dos
corrutinas concurrentes para el mismo guild podían intercalarse en esa
ventana.

`asyncio.gather` simula la concurrencia real, igual que en Sección 2. Los
fixtures resetean `_db_lock` (ver el comentario largo en
test_polar_webhook_hardening.py): `asyncio.Lock` se ata al primer event loop
que genera contención real sobre él, y estos son tests que generan
contención real a propósito.
"""

import asyncio

import aiosqlite
import pytest

import db
import r2


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    monkeypatch.setattr(db, "_db_lock", asyncio.Lock())

    deleted_keys: list[str] = []
    deleted_urls: list[str] = []

    async def fake_delete_key(key):
        deleted_keys.append(key)

    async def fake_delete_url(url):
        deleted_urls.append(url)

    monkeypatch.setattr(r2, "delete_key", fake_delete_key)
    monkeypatch.setattr(r2, "delete_url", fake_delete_url)
    conn.deleted_keys = deleted_keys
    conn.deleted_urls = deleted_urls
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _seed_gif(conn, guild_id, url, content_hash, ref_count=1):
    await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (guild_id, url, content_hash),
    )
    await conn.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
        "VALUES (?, ?, ?, 10)",
        (content_hash, r2.gif_key(content_hash), ref_count),
    )
    await conn.commit()


async def _gif_object_ref_count(conn, content_hash) -> int | None:
    async with conn.execute(
        "SELECT ref_count FROM gif_objects WHERE content_hash=?", (content_hash,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def _corpus_gif_count(conn, guild_id, content_hash) -> int:
    async with conn.execute(
        "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=? AND content_hash=?",
        (guild_id, content_hash),
    ) as cur:
        row = await cur.fetchone()
    return row[0]


# ── wipe_gifs: no debe dejar referencias fantasma en gif_objects ──────────


def test_wipe_gifs_concurrente_con_save_no_deja_referencia_fantasma(memory_db):
    """Un save_gif_url para un content_hash NUEVO (sin relación con lo que se
    está borrando) que cae justo en la ventana de wipe_gifs no puede
    resultar en un gif_objects con ref_count>0 sin ninguna fila de
    corpus_gifs que lo respalde -- esa combinación es una referencia
    fantasma: el barrido periódico (get_live_gif_keys) confía en ref_count,
    así que nunca la va a detectar ni corregir sola."""
    guild = 1
    h_wiped = "a" * 64
    h_new = "b" * 64

    async def seed():
        await _seed_gif(memory_db, guild, "https://x/1.gif", h_wiped)

    asyncio.run(seed())

    async def run():
        await asyncio.gather(
            db.wipe_gifs(guild),
            db.save_gif_url(
                guild, "https://x/2.gif", content_hash=h_new, size_bytes=10
            ),
        )
        corpus_count = await _corpus_gif_count(memory_db, guild, h_new)
        ref_count = await _gif_object_ref_count(memory_db, h_new)
        return corpus_count, ref_count

    corpus_count, ref_count = asyncio.run(run())
    # O el gif nuevo sobrevivió limpio (1 fila, ref_count 1), o -- si algún
    # día se reintrodujera el bug -- quedaría ref_count>0 con 0 filas: eso es
    # justo lo que este assert prohíbe.
    assert (corpus_count > 0) == bool(ref_count and ref_count > 0)


def test_wipe_gifs_sigue_liberando_las_referencias_reales(memory_db):
    """Caso base sin concurrencia: wipe_gifs libera de verdad lo que borra."""
    guild = 1
    h = "c" * 64

    async def run():
        await _seed_gif(memory_db, guild, "https://x/1.gif", h)
        deleted = await db.wipe_gifs(guild)
        ref_count = await _gif_object_ref_count(memory_db, h)
        return deleted, ref_count

    deleted, ref_count = asyncio.run(run())
    assert deleted == 1
    assert ref_count is None  # la fila de gif_objects se borró (ref_count llegó a 0)
    assert memory_db.deleted_keys == [r2.gif_key(h)]


# ── block_gif: no debe sobrevivir una copia del contenido bloqueado ───────


def test_block_gif_concurrente_con_save_del_mismo_hash_no_deja_copia_viva(
    memory_db,
):
    """Alguien comparte otra copia del MISMO gif justo mientras un admin lo
    bloquea. Pase lo que pase con el orden, al terminar no puede quedar
    ninguna fila de corpus_gifs con ese content_hash -- si quedara una,
    el bloqueo fue incompleto: el bot podría seguir sorteando el contenido
    que el admin acaba de vetar."""
    guild = 1
    h = "d" * 64

    async def seed():
        await _seed_gif(memory_db, guild, "https://x/1.gif", h)

    asyncio.run(seed())

    async def run():
        await asyncio.gather(
            db.block_gif(guild, h, "https://x/1.gif"),
            db.save_gif_url(guild, "https://x/2.gif", content_hash=h, size_bytes=10),
        )
        return await _corpus_gif_count(memory_db, guild, h)

    remaining = asyncio.run(run())
    assert remaining == 0


def test_block_gif_sigue_borrando_todas_las_copias_conocidas(memory_db):
    """Caso base: dos filas con el mismo content_hash, block_gif las borra
    ambas y libera cada referencia."""
    guild = 1
    h = "e" * 64

    async def run():
        await _seed_gif(memory_db, guild, "https://x/1.gif", h, ref_count=2)
        await memory_db.execute(
            "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
            (guild, "https://x/2.gif", h),
        )
        await memory_db.commit()
        await db.block_gif(guild, h, "https://x/1.gif")
        remaining = await _corpus_gif_count(memory_db, guild, h)
        ref_count = await _gif_object_ref_count(memory_db, h)
        return remaining, ref_count

    remaining, ref_count = asyncio.run(run())
    assert remaining == 0
    assert ref_count is None


# ── add_shared_embed: el límite diario no puede saltarse con concurrencia ──


def test_add_shared_embed_concurrente_no_supera_el_limite_diario(memory_db):
    """N requests casi simultáneos con un límite de 1 no pueden terminar los
    N insertando -- a lo sumo 1 tiene que ganar, el resto tiene que ver
    None (límite alcanzado)."""
    guild = 1

    async def run():
        results = await asyncio.gather(
            *[db.add_shared_embed("{}", guild, daily_limit=1) for _ in range(5)]
        )
        async with memory_db.execute(
            "SELECT COUNT(*) FROM shared_embeds WHERE created_guild_id=?", (guild,)
        ) as cur:
            row = await cur.fetchone()
        return results, row[0]

    results, total_rows = asyncio.run(run())
    successes = [r for r in results if r is not None]
    assert len(successes) == 1
    assert total_rows == 1


def test_add_shared_embed_sigue_funcionando_bajo_el_limite(memory_db):
    async def run():
        first = await db.add_shared_embed("{}", 1, daily_limit=2)
        second = await db.add_shared_embed("{}", 1, daily_limit=2)
        third = await db.add_shared_embed("{}", 1, daily_limit=2)
        return first, second, third

    first, second, third = asyncio.run(run())
    assert first is not None
    assert second is not None
    assert third is None
