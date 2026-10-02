"""Lápidas de /borrar_mis_datos y reaplicación de borrados tras un restore.

Una lápida es solo (user_id, deleted_at, expires_at): sin contenido y sin
servidores. Existe para que un backup anterior al borrado no "resucite" los
datos de un usuario al restaurarlo.
"""

import asyncio
import importlib.util
import os
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import pg_support
import pgsync
import db

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "reapply_deletions", ROOT / "scripts" / "reapply_deletions.py"
)
reapply_deletions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reapply_deletions)

FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture
def conn(monkeypatch):
    c = asyncio.run(pg_support.connect())
    monkeypatch.setattr(db, "_db", c)
    yield c
    asyncio.run(c.close())


def _sql(conn, sql, params=()):
    return asyncio.run(conn.execute(sql, params))


async def _fetch(conn, sql, params):
    cur = await conn.execute(sql, params)
    return await cur.fetchall()


def _rows(conn, sql, params=()):
    return asyncio.run(_fetch(conn, sql, params))


def _seed_user(conn, guild, user, n=2):
    for i in range(n):
        mid = guild * 1000 + user * 10 + i
        _sql(
            conn,
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) VALUES (?, 1, ?, 'x')",
            (guild, mid),
        )
        _sql(
            conn,
            "INSERT INTO user_corpus (guild_id, author_id, author_name, channel_id, message_id, content) "
            "VALUES (?, ?, 'n', 1, ?, 'x')",
            (guild, user, mid),
        )


def _tombstones(conn):
    return _rows(
        conn, "SELECT user_id, deleted_at, expires_at FROM deleted_user_tombstones"
    )


def _count(conn, table, user=None):
    if user is None:
        return _rows(conn, f"SELECT count(*) FROM {table}")[0][0]
    return _rows(conn, f"SELECT count(*) FROM {table} WHERE author_id=?", (user,))[0][0]


# --- se crea al borrar -------------------------------------------------------


def test_borrar_deja_una_lapida_con_solo_lo_imprescindible(conn):
    _seed_user(conn, 1, 10)
    _seed_user(conn, 2, 10)

    asyncio.run(db.delete_user_data(10))

    ((user_id, deleted_at, expires_at),) = _tombstones(conn)
    assert user_id == 10
    d = datetime.strptime(deleted_at, FMT)
    e = datetime.strptime(expires_at, FMT)
    assert e - d == timedelta(days=15)
    # la tabla no guarda nada más que eso: ni contenido ni servidores
    cols = [
        r[0]
        for r in _rows(
            conn,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='deleted_user_tombstones' ORDER BY ordinal_position",
        )
    ]
    assert cols == ["user_id", "deleted_at", "expires_at"]


def test_la_lapida_se_escribe_aunque_el_usuario_no_tuviera_filas_vivas(conn):
    asyncio.run(db.delete_user_data(77))  # un backup viejo podría tenerlas

    assert [t[0] for t in _tombstones(conn)] == [77]


def test_borrar_dos_veces_renueva_la_misma_lapida(conn):
    asyncio.run(db.delete_user_data(10))
    _sql(conn, "UPDATE deleted_user_tombstones SET expires_at='2000-01-01 00:00:00'")

    asyncio.run(db.delete_user_data(10))

    ((_, _, expires_at),) = _tombstones(conn)
    assert expires_at > datetime.now(timezone.utc).strftime(FMT)
    assert len(_tombstones(conn)) == 1


def test_el_plazo_sale_de_la_configuracion(conn, monkeypatch):
    monkeypatch.setenv("DELETION_TOMBSTONE_RETENTION_DAYS", "20")

    asyncio.run(db.delete_user_data(5))

    ((_, d, e),) = _tombstones(conn)
    assert datetime.strptime(e, FMT) - datetime.strptime(d, FMT) == timedelta(days=20)


def test_si_el_borrado_falla_no_queda_lapida_ni_se_borra_nada(conn, monkeypatch):
    _seed_user(conn, 1, 10)
    real = conn.execute

    def falla_en_la_lapida(sql, params=()):
        if "deleted_user_tombstones" in sql:
            raise RuntimeError("disco lleno")
        return real(sql, params)

    monkeypatch.setattr(conn, "execute", falla_en_la_lapida)
    with pytest.raises(RuntimeError):
        asyncio.run(db.delete_user_data(10))
    monkeypatch.setattr(conn, "execute", real)

    assert _tombstones(conn) == []  # todo o nada, en la misma transacción
    assert _count(conn, "user_corpus", 10) == 2
    assert _count(conn, "corpus_messages") == 2


# --- caducidad ---------------------------------------------------------------


def test_purge_elimina_solo_las_vencidas(conn):
    now = datetime.now(timezone.utc)
    for uid, delta in ((1, -timedelta(days=1)), (2, timedelta(days=3))):
        _sql(
            conn,
            "INSERT INTO deleted_user_tombstones (user_id, deleted_at, expires_at) VALUES (?, ?, ?)",
            (uid, now.strftime(FMT), (now + delta).strftime(FMT)),
        )

    assert asyncio.run(db.purge_expired_deletion_tombstones()) == 1
    assert [t[0] for t in _tombstones(conn)] == [2]
    assert asyncio.run(db.purge_expired_deletion_tombstones()) == 0


# --- restore + reaplicación --------------------------------------------------


def _restaurar_un_backup_viejo(conn):
    """Estado de un backup tomado ANTES del borrado: datos de A y B presentes, y
    la lápida (que sí está en la base viva y en backups posteriores)."""
    for guild in (1, 2):
        _seed_user(conn, guild, 10)  # usuario que luego se borró
        _seed_user(conn, guild, 20)  # otro usuario: no se debe tocar


def test_reaplicar_borra_lo_del_usuario_con_lapida_y_no_toca_a_los_demas(conn):
    _restaurar_un_backup_viejo(conn)
    now = datetime.now(timezone.utc)
    _sql(
        conn,
        "INSERT INTO deleted_user_tombstones VALUES (10, ?, ?)",
        (now.strftime(FMT), (now + timedelta(days=5)).strftime(FMT)),
    )

    stats = _reapply(apply=False)
    assert stats["user_corpus"] == 4 and stats["corpus_messages"] == 4
    assert _count(conn, "user_corpus", 10) == 4  # el dry-run no tocó nada

    stats = _reapply(apply=True)

    assert stats["lapidas_vigentes"] == 1
    assert _count(conn, "user_corpus", 10) == 0
    assert _count(conn, "user_corpus", 20) == 4
    assert _count(conn, "corpus_messages") == 4  # solo quedan los del usuario 20


def test_reaplicar_elimina_las_vencidas_y_no_borra_por_ellas(conn):
    _restaurar_un_backup_viejo(conn)
    _sql(
        conn,
        "INSERT INTO deleted_user_tombstones VALUES (10, '2020-01-01 00:00:00', '2020-01-16 00:00:00')",
    )

    stats = _reapply(apply=True)

    assert stats["lapidas_vencidas"] == 1 and stats["lapidas_vigentes"] == 0
    assert _count(conn, "user_corpus", 10) == 4  # vencida: ya no se reaplica
    assert _tombstones(conn) == []  # y se limpia


def test_reaplicar_es_idempotente(conn):
    _restaurar_un_backup_viejo(conn)
    now = datetime.now(timezone.utc)
    _sql(
        conn,
        "INSERT INTO deleted_user_tombstones VALUES (10, ?, ?)",
        (now.strftime(FMT), (now + timedelta(days=5)).strftime(FMT)),
    )

    _reapply(apply=True)
    segunda = _reapply(apply=True)

    assert segunda["user_corpus"] == 0 and segunda["corpus_messages"] == 0


def test_el_script_no_imprime_ids_de_usuario(conn, capsys):
    now = datetime.now(timezone.utc)
    _sql(
        conn,
        "INSERT INTO deleted_user_tombstones VALUES (123456789012345678, ?, ?)",
        (now.strftime(FMT), (now + timedelta(days=5)).strftime(FMT)),
    )

    import os

    assert (
        reapply_deletions.main(["--dsn", os.environ["TEST_DATABASE_URL"], "--apply"])
        == 0
    )

    out = capsys.readouterr().out
    assert "123456789012345678" not in out
    assert "lápidas vigentes: 1" in out


def _reapply(apply):
    c = pgsync.connect(os.environ["TEST_DATABASE_URL"])
    try:
        stats = reapply_deletions.reapply(c, apply=apply)
        c.commit()
    finally:
        c.close()
    return stats
