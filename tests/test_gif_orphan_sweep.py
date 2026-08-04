"""Tests del barrido periódico de huérfanos (cogs.gifs.run_gif_orphan_sweep).

Es la única pieza del sistema que borra objetos de R2 sin que nadie se lo haya
pedido, así que lo que se testea acá es sobre todo lo que NO tiene que borrar:
nada fuera del prefijo `gifs/` (ahí viven las imágenes de memes y las subidas
del editor de embeds), nada recién subido, nada referenciado por corpus_gifs
aunque gif_objects diga lo contrario, y nunca más de ORPHAN_MAX_DELETES por
corrida.

Mismo estilo que test_gif_health.py: DB en memoria inyectada en db._db y
monkeypatch de r2.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

import db
import r2
from cogs import gifs

_PUBLIC = "https://cdn.example.com"
_GUILD = 1
_HASH = "a" * 64
_OTHER_HASH = "b" * 64

_VIEJO = datetime.now(timezone.utc) - timedelta(days=30)
_RECIEN = datetime.now(timezone.utc) - timedelta(minutes=5)


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    monkeypatch.setattr(r2, "public_url", lambda: _PUBLIC)
    monkeypatch.setattr(r2, "available", lambda: True)
    yield conn
    asyncio.run(conn.close())


@pytest.fixture
def deleted(monkeypatch):
    keys: list[str] = []

    async def fake_delete_key(key):
        keys.append(key)

    monkeypatch.setattr(r2, "delete_key", fake_delete_key)
    return keys


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


def _bucket(monkeypatch, objects):
    """objects: lista de (key, size, last_modified)."""
    monkeypatch.setattr(r2, "list_keys_sync", lambda prefix: list(objects))


async def _add_object(conn, content_hash, ref_count):
    await conn.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
        "VALUES (?, ?, ?, 0)",
        (content_hash, r2.gif_key(content_hash), ref_count),
    )
    await conn.commit()


async def _add_gif_row(conn, key, content_hash=None):
    await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (_GUILD, f"{_PUBLIC}/{key}", content_hash),
    )
    await conn.commit()


def test_deletes_object_nobody_references(memory_db, deleted, monkeypatch):
    _bucket(monkeypatch, [(r2.gif_key(_HASH), 1234, _VIEJO)])

    assert asyncio.run(gifs.run_gif_orphan_sweep()) == 1
    assert deleted == [r2.gif_key(_HASH)]


def test_keeps_object_with_live_ref_count(memory_db, deleted, monkeypatch):
    async def run():
        await _add_object(memory_db, _HASH, 2)
        _bucket(monkeypatch, [(r2.gif_key(_HASH), 1234, _VIEJO)])
        assert await gifs.run_gif_orphan_sweep() == 0

    asyncio.run(run())
    assert deleted == []


def test_keeps_object_referenced_by_corpus_gifs_even_if_refcount_is_zero(
    memory_db, deleted, monkeypatch
):
    """La segunda fuente de verdad: si un ref_count quedó mal en cero por un
    bug, la fila de corpus_gifs tiene que alcanzar para salvar el objeto.
    Borrarlo sería irreversible."""

    async def run():
        await _add_object(memory_db, _HASH, 0)
        await _add_gif_row(memory_db, r2.gif_key(_HASH), _HASH)
        _bucket(monkeypatch, [(r2.gif_key(_HASH), 1234, _VIEJO)])
        assert await gifs.run_gif_orphan_sweep() == 0

    asyncio.run(run())
    assert deleted == []


def test_respects_grace_period_for_recent_uploads(memory_db, deleted, monkeypatch):
    """Un objeto recién subido puede tener su fila a medio guardar: no se toca
    hasta que pase la ventana de gracia."""
    _bucket(monkeypatch, [(r2.gif_key(_HASH), 1234, _RECIEN)])

    assert asyncio.run(gifs.run_gif_orphan_sweep()) == 0
    assert deleted == []


def test_only_looks_under_the_gif_prefix(memory_db, deleted, monkeypatch):
    """El listado se pide con el prefijo de GIFs: las imágenes de memes
    (`{guild_id}/...`) no entran ni en la lista de candidatos."""
    prefixes = []

    def fake_list(prefix):
        prefixes.append(prefix)
        return []

    monkeypatch.setattr(r2, "list_keys_sync", fake_list)
    asyncio.run(gifs.run_gif_orphan_sweep())
    assert prefixes == [r2.GIF_KEY_PREFIX]


def test_stops_at_the_delete_cap(memory_db, deleted, monkeypatch):
    """Tope por corrida: si el conjunto de keys vivas saliera vacío por un
    bug, el daño queda acotado en vez de llevarse el bucket entero."""
    monkeypatch.setattr(gifs, "ORPHAN_MAX_DELETES", 3)
    _bucket(
        monkeypatch,
        [(f"gifs/aa/{i:064x}.gif", 10, _VIEJO) for i in range(10)],
    )

    assert asyncio.run(gifs.run_gif_orphan_sweep()) == 3
    assert len(deleted) == 3


def test_mixed_bucket_deletes_only_the_orphan(memory_db, deleted, monkeypatch):
    async def run():
        await _add_object(memory_db, _HASH, 1)
        _bucket(
            monkeypatch,
            [
                (r2.gif_key(_HASH), 100, _VIEJO),  # vivo
                (r2.gif_key(_OTHER_HASH), 200, _VIEJO),  # huérfano
                (r2.gif_key("c" * 64), 300, _RECIEN),  # reciente
            ],
        )
        assert await gifs.run_gif_orphan_sweep() == 1

    asyncio.run(run())
    assert deleted == [r2.gif_key(_OTHER_HASH)]


def test_no_op_when_r2_is_not_configured(memory_db, deleted, monkeypatch):
    monkeypatch.setattr(r2, "available", lambda: False)

    def boom(prefix):
        raise AssertionError("no debería listar el bucket")

    monkeypatch.setattr(r2, "list_keys_sync", boom)
    assert asyncio.run(gifs.run_gif_orphan_sweep()) == 0


def test_live_keys_ignores_external_gif_urls(memory_db, deleted, monkeypatch):
    """Los GIFs de tenor/giphy no tienen objeto propio: no deben aportar keys
    inventadas al conjunto de vivos."""

    async def run():
        await memory_db.execute(
            "INSERT INTO corpus_gifs (guild_id, url) VALUES (?, ?)",
            (_GUILD, "https://tenor.com/view/algo"),
        )
        await memory_db.commit()
        assert await db.get_live_gif_keys() == set()

    asyncio.run(run())
