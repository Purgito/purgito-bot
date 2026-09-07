"""Tests de scripts/audit_cross_guild_gifs.py.

Lo que tiene que sostener: detecta bien qué content_hash están compartidos
entre 2+ servidores (y ningún otro); ordena las filas por antigüedad para
que el reporte señale al probable dueño original; y --apply (vía
apply_keep_guild) borra únicamente las filas de los servidores que NO se
conservan, sin tocar el objeto físico ni las referencias de otros
content_hash, y recalculando ref_count desde corpus_gifs.

DB en memoria: no se habla con data/bot.db real. Mismo estilo que
test_backfill_gif_phashes.py.
"""

import sqlite3
import sys

import pytest

import db

sys.path.insert(0, "scripts")
import audit_cross_guild_gifs as audit  # noqa: E402


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(db.SCHEMA)
    return c


def _add_object(conn, content_hash, key="gifs/aa/x.gif", ref_count=0):
    conn.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
        "VALUES (?, ?, ?, 10)",
        (content_hash, key, ref_count),
    )
    conn.commit()


def _add_gif(conn, guild_id, content_hash, url, created_at="2024-01-01"):
    conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash, created_at) "
        "VALUES (?, ?, ?, ?)",
        (guild_id, url, content_hash, created_at),
    )
    conn.commit()


def test_find_shared_content_hashes_ignores_single_guild(conn):
    _add_gif(conn, 1, "a" * 64, "https://x/a")
    assert audit.find_shared_content_hashes(conn) == []


def test_find_shared_content_hashes_detects_multi_guild(conn):
    _add_gif(conn, 1, "a" * 64, "https://x/a")
    _add_gif(conn, 2, "a" * 64, "https://x/a-repost")
    _add_gif(conn, 3, "b" * 64, "https://x/b")
    assert audit.find_shared_content_hashes(conn) == [("a" * 64, 2)]


def test_find_shared_content_hashes_orders_by_guild_count_desc(conn):
    _add_gif(conn, 1, "a" * 64, "https://x/a1")
    _add_gif(conn, 2, "a" * 64, "https://x/a2")
    _add_gif(conn, 1, "b" * 64, "https://x/b1")
    _add_gif(conn, 2, "b" * 64, "https://x/b2")
    _add_gif(conn, 3, "b" * 64, "https://x/b3")

    result = audit.find_shared_content_hashes(conn)

    assert result == [("b" * 64, 3), ("a" * 64, 2)]


def test_rows_for_content_hash_orders_by_created_at():
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SCHEMA)
    _add_gif(conn, 2, "a" * 64, "https://x/segundo", created_at="2024-06-01")
    _add_gif(conn, 1, "a" * 64, "https://x/primero", created_at="2024-01-01")

    rows = audit.rows_for_content_hash(conn, "a" * 64)

    assert [r["guild_id"] for r in rows] == [1, 2]
    assert rows[0]["url"] == "https://x/primero"


def test_apply_keep_guild_removes_other_guilds_rows_only(conn):
    _add_object(conn, "a" * 64, ref_count=3)
    _add_gif(conn, 1, "a" * 64, "https://x/a1", created_at="2024-01-01")
    _add_gif(conn, 2, "a" * 64, "https://x/a2", created_at="2024-01-02")
    _add_gif(conn, 3, "a" * 64, "https://x/a3", created_at="2024-01-03")
    _add_gif(conn, 1, "b" * 64, "https://x/b1")  # otro content_hash: no se toca

    summary = audit.apply_keep_guild(conn, "a" * 64, keep_guild=1)

    assert summary == {"removed_rows": 2, "kept_guild": 1}
    remaining = conn.execute(
        "SELECT guild_id FROM corpus_gifs WHERE content_hash=?", ("a" * 64,)
    ).fetchall()
    assert remaining == [(1,)]
    # El otro content_hash no se ve afectado.
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE content_hash=?", ("b" * 64,)
        ).fetchone()[0]
        == 1
    )


def test_apply_keep_guild_recomputes_ref_count(conn):
    _add_object(conn, "a" * 64, ref_count=99)  # deliberadamente desincronizado
    _add_gif(conn, 1, "a" * 64, "https://x/a1")
    _add_gif(conn, 2, "a" * 64, "https://x/a2")
    _add_gif(conn, 3, "a" * 64, "https://x/a3")

    audit.apply_keep_guild(conn, "a" * 64, keep_guild=1)

    ref_count = conn.execute(
        "SELECT ref_count FROM gif_objects WHERE content_hash=?", ("a" * 64,)
    ).fetchone()[0]
    assert ref_count == 1  # solo queda la fila de guild 1


def test_apply_keep_guild_rejects_guild_that_does_not_reference_the_hash(conn):
    _add_object(conn, "a" * 64)
    _add_gif(conn, 1, "a" * 64, "https://x/a1")
    _add_gif(conn, 2, "a" * 64, "https://x/a2")

    with pytest.raises(ValueError, match="no está entre los servidores"):
        audit.apply_keep_guild(conn, "a" * 64, keep_guild=999)

    # No debe haber borrado nada al fallar la validación.
    remaining = conn.execute(
        "SELECT COUNT(*) FROM corpus_gifs WHERE content_hash=?", ("a" * 64,)
    ).fetchone()[0]
    assert remaining == 2
