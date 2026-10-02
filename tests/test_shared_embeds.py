"""Tests de shared_embeds (db.py): ciclo de vida de un link compartido —
crear, leer más de una vez, expirar, purgar — y el conteo diario para el
límite por guild. DB SQLite en memoria inyectada en db._db, igual que
test_anuncios.py."""

import asyncio

import pgdb  # noqa: F401
import pg_support
import pytest

import db


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> pgdb.Database:
    conn = await pg_support.connect()
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


def _expire(conn, share_id):
    """Vence un link a mano (expires_at en el pasado)."""
    asyncio.run(
        conn.execute(
            "UPDATE shared_embeds SET expires_at=to_char(timezone('utc', now()) - interval '1 day', 'YYYY-MM-DD HH24:MI:SS') "
            "WHERE share_id=?",
            (share_id,),
        )
    )
    asyncio.run(conn.commit())


def test_share_roundtrip_multiuso(memory_db):
    payload = '{"embeds": [{"title": "hola"}]}'
    share_id, expires_at = asyncio.run(db.add_shared_embed(payload, guild_id=1))
    assert share_id.isalnum() and len(share_id) >= 8
    assert expires_at  # formato "YYYY-MM-DD HH:MM:SS"
    # Se puede leer más de una vez: no se borra al primer uso.
    assert asyncio.run(db.get_shared_embed(share_id)) == payload
    assert asyncio.run(db.get_shared_embed(share_id)) == payload


def test_share_vencido_o_inexistente_devuelve_none(memory_db):
    assert asyncio.run(db.get_shared_embed("noexiste1")) is None
    share_id, _ = asyncio.run(db.add_shared_embed("{}", guild_id=1))
    _expire(memory_db, share_id)
    assert asyncio.run(db.get_shared_embed(share_id)) is None


def test_purge_borra_solo_vencidos(memory_db):
    vivo, _ = asyncio.run(db.add_shared_embed("{}", guild_id=1))
    muerto, _ = asyncio.run(db.add_shared_embed("{}", guild_id=1))
    _expire(memory_db, muerto)
    assert asyncio.run(db.purge_expired_shared_embeds()) == 1
    assert asyncio.run(db.get_shared_embed(vivo)) == "{}"


def test_conteo_diario_por_guild(memory_db):
    for _ in range(3):
        asyncio.run(db.add_shared_embed("{}", guild_id=1))
    asyncio.run(db.add_shared_embed("{}", guild_id=2))
    assert asyncio.run(db.count_shared_embeds_today(1)) == 3
    assert asyncio.run(db.count_shared_embeds_today(2)) == 1


def test_share_id_reintenta_si_colisiona(memory_db, monkeypatch):
    # Fuerza la colisión: secrets.choice devuelve siempre 'a', así el primer
    # intento (8 chars) choca con la fila pre-insertada y el segundo sale con 9.
    asyncio.run(
        memory_db.execute(
            "INSERT INTO shared_embeds (share_id, payload, created_at, expires_at) "
            "VALUES ('aaaaaaaa', '{}', utc_now(), to_char(timezone('utc', now()) + interval '1 day', 'YYYY-MM-DD HH24:MI:SS'))"
        )
    )
    asyncio.run(memory_db.commit())
    monkeypatch.setattr(db.secrets, "choice", lambda seq: "a")
    assert asyncio.run(db.generate_unique_share_id()) == "a" * 9
