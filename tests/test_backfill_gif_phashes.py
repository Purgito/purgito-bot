"""Tests del backfill de phash perceptual (scripts/backfill_gif_phashes.py).

Lo que tiene que sostener: los objetos sin phash lo calculan y lo guardan
siempre (aditivo, no depende de --apply); el clustering por distancia de
Hamming agrupa bien clusters de 1/2/3+ objetos; y la fusión con --apply
reescribe corpus_gifs hacia el canónico sin romper el UNIQUE(guild_id, url)
ni perder referencias de otros guilds.

Bucket y DB son falsos/en memoria: no se habla con R2 ni con data/bot.db.
Mismo estilo que test_reconcile_gif_objects.py.
"""

import io
import sqlite3
import sys

import pytest

import db
import r2

sys.path.insert(0, "scripts")
import backfill_gif_phashes as bf  # noqa: E402

_PUBLIC = "https://cdn.example.com"

# Hashes de 16 hex chars (64 bits, hash_size=8 de dHash) con distancias
# conocidas entre sí: _H0 es todo ceros, _H1 difiere en 1 bit, _H_FAR difiere
# en los 64 bits.
_H0 = "0" * 16
_H1 = "1" + "0" * 15
_H_FAR = "f" * 16


class _FakeBucket:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts: list[str] = []
        self.deletes: list[str] = []

    def get_object(self, Bucket=None, Key=None):
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket=None, Key=None, Body=None, **kw):
        self.objects[Key] = Body
        self.puts.append(Key)

    def delete_object(self, Bucket=None, Key=None):
        self.objects.pop(Key, None)
        self.deletes.append(Key)


@pytest.fixture(autouse=True)
def fake_r2(monkeypatch):
    monkeypatch.setattr(r2, "public_url", lambda: _PUBLIC)
    monkeypatch.setattr(bf.time, "sleep", lambda *a: None)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(db.SCHEMA)
    return c


def _url(key: str) -> str:
    return f"{_PUBLIC}/{key}"


def _add_object(
    conn, content_hash, key, phash=None, size_bytes=10, created_at="2024-01-01"
):
    conn.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes, phash, created_at) "
        "VALUES (?, ?, 0, ?, ?, ?)",
        (content_hash, key, size_bytes, phash, created_at),
    )
    conn.commit()


def _add_gif(conn, guild_id, content_hash, key):
    conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (guild_id, _url(key), content_hash),
    )
    conn.commit()


# ---------- fase 1: backfill de phashes faltantes --------------------------


def test_backfill_computes_and_saves_missing_phashes(conn, monkeypatch):
    bucket = _FakeBucket({"gifs/aa/a.gif": b"contenido-a"})
    _add_object(conn, "a" * 64, "gifs/aa/a.gif", phash=None)
    monkeypatch.setattr(r2, "compute_phash", lambda data: "1234567890abcdef")

    done, failed = bf.backfill_missing_phashes(bucket, "bucket", conn)

    assert (done, failed) == (1, 0)
    row = conn.execute(
        "SELECT phash FROM gif_objects WHERE content_hash=?", ("a" * 64,)
    ).fetchone()
    assert row[0] == "1234567890abcdef"


def test_backfill_leaves_object_without_phash_when_undecodable(conn, monkeypatch):
    """Puramente aditivo: si no se puede calcular, la fila se deja como está
    (no rompe nada, la próxima corrida la vuelve a intentar)."""
    bucket = _FakeBucket({"gifs/aa/a.gif": b"no es un gif"})
    _add_object(conn, "a" * 64, "gifs/aa/a.gif", phash=None)
    monkeypatch.setattr(r2, "compute_phash", lambda data: None)

    done, failed = bf.backfill_missing_phashes(bucket, "bucket", conn)

    assert (done, failed) == (0, 1)
    row = conn.execute(
        "SELECT phash FROM gif_objects WHERE content_hash=?", ("a" * 64,)
    ).fetchone()
    assert row[0] is None


def test_backfill_skips_objects_that_already_have_a_phash(conn, monkeypatch):
    bucket = _FakeBucket({"gifs/aa/a.gif": b"contenido-a"})
    _add_object(conn, "a" * 64, "gifs/aa/a.gif", phash="ya-calculado")
    called = []
    monkeypatch.setattr(r2, "compute_phash", lambda data: called.append(1) or "x")

    bf.backfill_missing_phashes(bucket, "bucket", conn)

    assert called == []


# ---------- fase 2: clustering ----------------------------------------------


def test_cluster_of_one_is_not_reported():
    objs = [("a" * 64, "k1", _H0)]
    assert bf.cluster_by_phash(objs, max_distance=6) == []


def test_cluster_of_two_within_distance():
    objs = [("a" * 64, "k1", _H0), ("b" * 64, "k2", _H1)]
    clusters = bf.cluster_by_phash(objs, max_distance=6)
    assert len(clusters) == 1
    assert set(clusters[0]) == {"a" * 64, "b" * 64}


def test_objects_too_far_apart_are_not_clustered():
    objs = [("a" * 64, "k1", _H0), ("b" * 64, "k2", _H_FAR)]
    assert bf.cluster_by_phash(objs, max_distance=6) == []


def test_cluster_of_three_or_more():
    h_a, h_b, h_c = "a" * 64, "b" * 64, "c" * 64
    objs = [(h_a, "k1", _H0), (h_b, "k2", _H1), (h_c, "k3", _H1)]
    clusters = bf.cluster_by_phash(objs, max_distance=6)
    assert len(clusters) == 1
    assert set(clusters[0]) == {h_a, h_b, h_c}


def test_objects_without_phash_do_not_participate():
    objs = [("a" * 64, "k1", _H0), ("b" * 64, "k2", None)]
    assert bf.cluster_by_phash(objs, max_distance=6) == []


# ---------- fase 4: fusión (--apply) ----------------------------------------


def test_apply_merges_picks_the_object_with_more_references_as_canonical(conn):
    h_a, h_b = "a" * 64, "b" * 64
    key_a, key_b = "gifs/aa/a.gif", "gifs/bb/b.gif"
    _add_object(conn, h_a, key_a, phash=_H0, created_at="2024-01-01")
    _add_object(conn, h_b, key_b, phash=_H1, created_at="2024-01-02")
    _add_gif(conn, 1, h_a, key_a)
    _add_gif(conn, 2, h_b, key_b)
    _add_gif(conn, 3, h_b, key_b)  # h_b tiene más referencias -> canónico

    bucket = _FakeBucket({key_a: b"x", key_b: b"y"})
    objects_by_hash = {h_a: (key_a, "2024-01-01"), h_b: (key_b, "2024-01-02")}

    summary = bf.apply_merges(bucket, "bucket", conn, [[h_a, h_b]], objects_by_hash)

    assert summary["merged_objects"] == 1
    rows = conn.execute("SELECT content_hash FROM corpus_gifs").fetchall()
    assert all(r[0] == h_b for r in rows)
    assert bucket.deletes == [key_a]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM gif_objects WHERE content_hash=?", (h_a,)
        ).fetchone()[0]
        == 0
    )
    ref_count = conn.execute(
        "SELECT ref_count FROM gif_objects WHERE content_hash=?", (h_b,)
    ).fetchone()[0]
    assert ref_count == 3


def test_apply_merges_breaks_tie_by_oldest_created_at(conn):
    h_a, h_b = "a" * 64, "b" * 64
    key_a, key_b = "gifs/aa/a.gif", "gifs/bb/b.gif"
    _add_object(conn, h_a, key_a, phash=_H0, created_at="2024-06-01")
    _add_object(conn, h_b, key_b, phash=_H1, created_at="2024-01-01")  # más viejo
    _add_gif(conn, 1, h_a, key_a)
    _add_gif(conn, 2, h_b, key_b)

    bucket = _FakeBucket({key_a: b"x", key_b: b"y"})
    objects_by_hash = {h_a: (key_a, "2024-06-01"), h_b: (key_b, "2024-01-01")}

    bf.apply_merges(bucket, "bucket", conn, [[h_a, h_b]], objects_by_hash)

    rows = conn.execute("SELECT content_hash FROM corpus_gifs").fetchall()
    assert all(r[0] == h_b for r in rows)


def test_apply_merges_drops_duplicate_row_colliding_with_canonical_in_same_guild(conn):
    """Si un guild ya tenía el canónico Y el no-canónico (dos copias del
    mismo meme con distinto content_hash), la reescritura choca contra el
    UNIQUE(guild_id, url) y la fila vieja se borra en vez de reescribirse."""
    h_a, h_b = "a" * 64, "b" * 64  # b es el canónico (más referencias)
    key_a, key_b = "gifs/aa/a.gif", "gifs/bb/b.gif"
    _add_object(conn, h_a, key_a, phash=_H0, created_at="2024-01-01")
    _add_object(conn, h_b, key_b, phash=_H1, created_at="2024-01-01")
    _add_gif(conn, 1, h_a, key_a)  # guild 1 tenía el no-canónico...
    _add_gif(conn, 1, h_b, key_b)  # ...y también el canónico
    _add_gif(conn, 2, h_b, key_b)

    bucket = _FakeBucket({key_a: b"x", key_b: b"y"})
    objects_by_hash = {h_a: (key_a, "2024-01-01"), h_b: (key_b, "2024-01-01")}

    bf.apply_merges(bucket, "bucket", conn, [[h_a, h_b]], objects_by_hash)

    rows = conn.execute(
        "SELECT guild_id, content_hash FROM corpus_gifs ORDER BY guild_id"
    ).fetchall()
    assert rows == [(1, h_b), (2, h_b)]  # sin IntegrityError ni fila duplicada


def test_idempotent_second_pass_finds_no_more_clusters(conn):
    h_a, h_b = "a" * 64, "b" * 64
    key_a, key_b = "gifs/aa/a.gif", "gifs/bb/b.gif"
    _add_object(conn, h_a, key_a, phash=_H0, created_at="2024-01-01")
    _add_object(conn, h_b, key_b, phash=_H1, created_at="2024-01-02")
    _add_gif(conn, 1, h_a, key_a)
    _add_gif(conn, 2, h_b, key_b)

    bucket = _FakeBucket({key_a: b"x", key_b: b"y"})
    objects_by_hash = {h_a: (key_a, "2024-01-01"), h_b: (key_b, "2024-01-02")}
    bf.apply_merges(bucket, "bucket", conn, [[h_a, h_b]], objects_by_hash)

    remaining = conn.execute(
        "SELECT content_hash, r2_key, phash FROM gif_objects"
    ).fetchall()
    assert bf.cluster_by_phash(remaining, max_distance=6) == []
