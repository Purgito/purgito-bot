"""Tests del backfill de fingerprint perceptual (scripts/backfill_gif_phashes.py).

Lo que tiene que sostener: los objetos sin fingerprint lo calculan y lo
guardan siempre (aditivo, no depende de --apply); el clustering agrupa bien
clusters de 1/2/3+ objetos usando el mismo criterio AND estricto que
r2.fingerprint_distance (nunca agrupa por dHash solo, sin importar la
estructura); y la fusión con --apply reescribe corpus_gifs hacia el canónico
sin romper el UNIQUE(guild_id, url) ni perder referencias de otros guilds.

Bucket y DB son falsos/en memoria: no se habla con R2 ni con data/bot.db.
Mismo estilo que test_reconcile_gif_objects.py.
"""

import io
import json
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


def _fp(phashes=(_H0,), frame_count=1, width=16, height=16, duration_ms=100):
    """Fingerprint de prueba. Con los defaults, dos llamadas con distinto
    `phashes` son estructuralmente compatibles entre sí -- para probar
    incompatibilidad, variar frame_count/width/height/duration_ms."""
    return r2.GifFingerprint(
        frame_count=frame_count,
        width=width,
        height=height,
        duration_ms=duration_ms,
        phashes=phashes,
    )


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
    conn,
    content_hash,
    key,
    fingerprint=None,
    size_bytes=10,
    created_at="2024-01-01",
):
    """fingerprint=None deja el objeto sin fingerprint (fase 1 lo completa).
    Los tests de fase 4 (fusión) no necesitan un fingerprint real: arman los
    clusters a mano, así que alcanza con la fila base."""
    if fingerprint is None:
        conn.execute(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes, created_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (content_hash, key, size_bytes, created_at),
        )
    else:
        conn.execute(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes, "
            "frame_count, width, height, duration_ms, phashes, created_at) "
            "VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            (
                content_hash,
                key,
                size_bytes,
                fingerprint.frame_count,
                fingerprint.width,
                fingerprint.height,
                fingerprint.duration_ms,
                json.dumps(list(fingerprint.phashes)),
                created_at,
            ),
        )
    conn.commit()


def _add_gif(conn, guild_id, content_hash, key):
    conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (guild_id, _url(key), content_hash),
    )
    conn.commit()


# ---------- fase 1: backfill de fingerprints faltantes ----------------------


def test_backfill_computes_and_saves_missing_fingerprints(conn, monkeypatch):
    bucket = _FakeBucket({"gifs/aa/a.gif": b"contenido-a"})
    _add_object(conn, "a" * 64, "gifs/aa/a.gif")
    fp = _fp(phashes=("1234567890abcdef",), frame_count=2, width=8, height=8)
    monkeypatch.setattr(r2, "compute_gif_fingerprint", lambda data: fp)

    done, failed = bf.backfill_missing_fingerprints(bucket, "bucket", conn)

    assert (done, failed) == (1, 0)
    row = conn.execute(
        "SELECT frame_count, width, height, duration_ms, phashes "
        "FROM gif_objects WHERE content_hash=?",
        ("a" * 64,),
    ).fetchone()
    assert tuple(row[:4]) == (2, 8, 8, 100)
    assert json.loads(row[4]) == ["1234567890abcdef"]


def test_backfill_leaves_object_without_fingerprint_when_undecodable(conn, monkeypatch):
    """Puramente aditivo: si no se puede calcular, la fila se deja como está
    (no rompe nada, la próxima corrida la vuelve a intentar)."""
    bucket = _FakeBucket({"gifs/aa/a.gif": b"no es un gif"})
    _add_object(conn, "a" * 64, "gifs/aa/a.gif")
    monkeypatch.setattr(r2, "compute_gif_fingerprint", lambda data: None)

    done, failed = bf.backfill_missing_fingerprints(bucket, "bucket", conn)

    assert (done, failed) == (0, 1)
    row = conn.execute(
        "SELECT phashes FROM gif_objects WHERE content_hash=?", ("a" * 64,)
    ).fetchone()
    assert row[0] is None


def test_backfill_skips_objects_that_already_have_a_fingerprint(conn, monkeypatch):
    bucket = _FakeBucket({"gifs/aa/a.gif": b"contenido-a"})
    _add_object(conn, "a" * 64, "gifs/aa/a.gif", fingerprint=_fp())
    called = []
    monkeypatch.setattr(
        r2, "compute_gif_fingerprint", lambda data: called.append(1) or _fp()
    )

    bf.backfill_missing_fingerprints(bucket, "bucket", conn)

    assert called == []


# ---------- fase 2: clustering -----------------------------------------------


def test_cluster_of_one_is_not_reported():
    objs = [("a" * 64, "k1", _fp(phashes=(_H0,)))]
    assert bf.cluster_by_fingerprint(objs, max_distance=6) == []


def test_cluster_of_two_within_distance():
    objs = [
        ("a" * 64, "k1", _fp(phashes=(_H0,))),
        ("b" * 64, "k2", _fp(phashes=(_H1,))),
    ]
    clusters = bf.cluster_by_fingerprint(objs, max_distance=6)
    assert len(clusters) == 1
    assert set(clusters[0]) == {"a" * 64, "b" * 64}


def test_objects_too_far_apart_are_not_clustered():
    objs = [
        ("a" * 64, "k1", _fp(phashes=(_H0,))),
        ("b" * 64, "k2", _fp(phashes=(_H_FAR,))),
    ]
    assert bf.cluster_by_fingerprint(objs, max_distance=6) == []


def test_cluster_of_three_or_more():
    h_a, h_b, h_c = "a" * 64, "b" * 64, "c" * 64
    objs = [
        (h_a, "k1", _fp(phashes=(_H0,))),
        (h_b, "k2", _fp(phashes=(_H1,))),
        (h_c, "k3", _fp(phashes=(_H1,))),
    ]
    clusters = bf.cluster_by_fingerprint(objs, max_distance=6)
    assert len(clusters) == 1
    assert set(clusters[0]) == {h_a, h_b, h_c}


def test_objects_without_fingerprint_do_not_participate():
    objs = [("a" * 64, "k1", _fp(phashes=(_H0,))), ("b" * 64, "k2", None)]
    assert bf.cluster_by_fingerprint(objs, max_distance=6) == []


def test_objects_with_close_hash_but_different_structure_are_not_clustered():
    """Mismo caso que el bug real que motivó el fingerprint completo: un
    dHash parecido (o hasta idéntico) no alcanza si la estructura difiere
    -- acá, cantidad de frames distinta."""
    objs = [
        ("a" * 64, "k1", _fp(phashes=(_H0,), frame_count=1)),
        ("b" * 64, "k2", _fp(phashes=(_H0,), frame_count=5)),
    ]
    assert bf.cluster_by_fingerprint(objs, max_distance=6) == []


# ---------- fase 4: fusión (--apply) ----------------------------------------


def test_apply_merges_picks_the_object_with_more_references_as_canonical(conn):
    h_a, h_b = "a" * 64, "b" * 64
    key_a, key_b = "gifs/aa/a.gif", "gifs/bb/b.gif"
    _add_object(conn, h_a, key_a, created_at="2024-01-01")
    _add_object(conn, h_b, key_b, created_at="2024-01-02")
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
    _add_object(conn, h_a, key_a, created_at="2024-06-01")
    _add_object(conn, h_b, key_b, created_at="2024-01-01")  # más viejo
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
    _add_object(conn, h_a, key_a, created_at="2024-01-01")
    _add_object(conn, h_b, key_b, created_at="2024-01-01")
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
    _add_object(
        conn, h_a, key_a, fingerprint=_fp(phashes=(_H0,)), created_at="2024-01-01"
    )
    _add_object(
        conn, h_b, key_b, fingerprint=_fp(phashes=(_H1,)), created_at="2024-01-02"
    )
    _add_gif(conn, 1, h_a, key_a)
    _add_gif(conn, 2, h_b, key_b)

    bucket = _FakeBucket({key_a: b"x", key_b: b"y"})
    objects_by_hash = {h_a: (key_a, "2024-01-01"), h_b: (key_b, "2024-01-02")}
    bf.apply_merges(bucket, "bucket", conn, [[h_a, h_b]], objects_by_hash)

    remaining = conn.execute(
        "SELECT content_hash, r2_key, frame_count, width, height, "
        "duration_ms, phashes FROM gif_objects"
    ).fetchall()
    remaining_input = [
        (row[0], row[1], bf._fingerprint_from_row(*row[2:])) for row in remaining
    ]
    # Solo queda un objeto (el otro se fusionó y se borró): sin un segundo
    # objeto compatible, cluster_by_fingerprint no puede formar un grupo de
    # 2+ por más que el que sobrevive tenga un fingerprint válido.
    assert bf.cluster_by_fingerprint(remaining_input, max_distance=6) == []
