"""Tests del backfill (scripts/reconcile_gif_objects.py).

Lo que tiene que sostener: las tres generaciones de objetos que conviven hoy en
el bucket (legacy por guild, content-addressed sin optimizar, y ya normalizado)
se normalizan todas a la misma regla -- sha256 de los bytes optimizados -- y
convergen al mismo objeto cuando son el mismo archivo.

Lo peligroso acá no es dejar un duplicado sin borrar, es borrar de más: el
bucket comparte espacio con las imágenes del pool de memes, que también pueden
tener extensión .gif. Por eso hay un test dedicado a que no las toque.

Bucket y DB son falsos/en memoria: no se habla con R2 ni con data/bot.db.
"""

import hashlib
import sqlite3
import sys

import pytest

import db
import r2

sys.path.insert(0, "scripts")
import reconcile_gif_objects as rec  # noqa: E402

_PUBLIC = "https://cdn.example.com"
_GUILD_A = 1
_GUILD_B = 2

# Dos archivos distintos. optimize_gif_bytes (falso, ver fixture) les saca el
# sufijo "-crudo", así que el "mismo archivo" en dos generaciones distintas
# converge al mismo contenido optimizado.
_FILE_A = b"GIF89a-archivo-A-crudo"
_FILE_B = b"GIF89a-archivo-B-crudo"


def _optimized(raw: bytes) -> bytes:
    return raw.replace(b"-crudo", b"")


def _hash(raw: bytes) -> str:
    return hashlib.sha256(_optimized(raw)).hexdigest()


def _raw_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class _FakeBucket:
    """Bucket en memoria con la parte de la API de boto3 que usa el script."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = dict(objects)
        self.puts: list[str] = []
        self.deletes: list[str] = []

    def get_paginator(self, _name):
        outer = self

        class _P:
            def paginate(self, **kw):
                yield {
                    "Contents": [
                        {"Key": k, "Size": len(v)}
                        for k, v in sorted(outer.objects.items())
                    ]
                }

        return _P()

    def get_object(self, Bucket=None, Key=None):
        import io

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
    monkeypatch.setattr(r2, "optimize_gif_bytes", _optimized)
    monkeypatch.setattr(rec.time, "sleep", lambda *a: None)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(db.SCHEMA)
    return c


def _url(key: str) -> str:
    return f"{_PUBLIC}/{key}"


def _add_gif(conn, guild_id, key, content_hash=None):
    conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url, content_hash) VALUES (?, ?, ?)",
        (guild_id, _url(key), content_hash),
    )
    conn.commit()


def _legacy_key(guild_id, url):
    return f"{guild_id}/{hashlib.md5(url.encode()).hexdigest()}.gif"


# ---------- clasificación de generaciones ----------


def test_classify_recognises_the_three_generations():
    raw, opt = _FILE_A, _optimized(_FILE_A)
    assert rec.classify(r2.gif_key(_hash(raw)), raw, opt) == "normalizado"
    assert rec.classify(r2.gif_key(_raw_hash(raw)), raw, opt) == "sin-optimizar"
    assert rec.classify("123/abc.gif", raw, opt) == "legacy"


# ---------- reconciliación ----------


def test_three_generations_of_the_same_file_converge(conn):
    """Un legacy, un content-addressed sin optimizar y uno ya normalizado, los
    tres del mismo archivo: tienen que terminar en un único objeto."""
    canonical = r2.gif_key(_hash(_FILE_A))
    legacy = _legacy_key(_GUILD_A, "https://cdn.discordapp.com/x.gif")
    unopt = r2.gif_key(_raw_hash(_FILE_A))

    bucket = _FakeBucket(
        {
            legacy: _FILE_A,
            unopt: _FILE_A,
            canonical: _optimized(_FILE_A),
        }
    )
    _add_gif(conn, _GUILD_A, legacy)
    _add_gif(conn, _GUILD_B, unopt, _raw_hash(_FILE_A))
    _add_gif(conn, 3, canonical, _hash(_FILE_A))

    summary = rec.reconcile(bucket, "b", conn, apply=True)

    assert summary["unique"] == 1
    assert summary["deleted"] == 2
    assert set(bucket.objects) == {canonical}
    assert summary["generations"] == {
        "legacy": 1,
        "sin-optimizar": 1,
        "normalizado": 1,
    }
    # Las tres filas ahora apuntan al mismo objeto, con el hash correcto.
    rows = conn.execute("SELECT url, content_hash FROM corpus_gifs").fetchall()
    assert rows == [(_url(canonical), _hash(_FILE_A))] * 3


def test_legacy_only_group_gets_reuploaded_to_canonical_key(conn):
    """Si ningún objeto del grupo está en la key canónica hay que subirlo:
    los bytes optimizados no existen todavía en el bucket."""
    legacy = _legacy_key(_GUILD_A, "https://cdn.discordapp.com/x.gif")
    bucket = _FakeBucket({legacy: _FILE_A})
    _add_gif(conn, _GUILD_A, legacy)

    summary = rec.reconcile(bucket, "b", conn, apply=True)

    canonical = r2.gif_key(_hash(_FILE_A))
    assert summary["moved"] == 1
    assert bucket.puts == [canonical]
    assert bucket.objects[canonical] == _optimized(_FILE_A)
    assert bucket.deletes == [legacy]


def test_dry_run_touches_nothing(conn):
    legacy = _legacy_key(_GUILD_A, "https://cdn.discordapp.com/x.gif")
    bucket = _FakeBucket({legacy: _FILE_A, r2.gif_key(_raw_hash(_FILE_A)): _FILE_A})
    _add_gif(conn, _GUILD_A, legacy)
    _add_gif(conn, _GUILD_B, r2.gif_key(_raw_hash(_FILE_A)))

    summary = rec.reconcile(bucket, "b", conn, apply=False)

    assert summary["deleted"] == 2  # informa lo que haría...
    assert bucket.puts == [] and bucket.deletes == []  # ...pero no lo hace
    assert set(bucket.objects) == {legacy, r2.gif_key(_raw_hash(_FILE_A))}
    rows = conn.execute("SELECT content_hash FROM corpus_gifs").fetchall()
    assert rows == [(None,), (None,)]
    assert conn.execute("SELECT COUNT(*) FROM gif_objects").fetchone()[0] == 0


def test_never_touches_objects_referenced_by_corpus_images(conn):
    """Una imagen del pool de memes con extensión .gif es indistinguible de un
    GIF legacy por la forma de la key: si el script la tocara, rompería los
    memes del servidor."""
    image_key = f"{_GUILD_A}/deadbeef.gif"
    legacy = _legacy_key(_GUILD_A, "https://cdn.discordapp.com/x.gif")
    bucket = _FakeBucket({image_key: _FILE_A, legacy: _FILE_A})
    _add_gif(conn, _GUILD_A, legacy)
    conn.execute(
        "INSERT INTO corpus_images (guild_id, url) VALUES (?, ?)",
        (_GUILD_A, _url(image_key)),
    )
    conn.commit()

    summary = rec.reconcile(bucket, "b", conn, apply=True)

    assert summary["skipped_images"] == 1
    assert image_key in bucket.objects
    assert image_key not in bucket.deletes
    # Y la fila de corpus_images sigue apuntando adonde apuntaba.
    assert conn.execute("SELECT url FROM corpus_images").fetchone() == (
        _url(image_key),
    )


def test_orphans_are_reported_but_not_deleted(conn):
    """Borrar huérfanos es trabajo del barrido periódico, que tiene
    gif_objects para decidir; acá solo se informan."""
    bucket = _FakeBucket({"gifs/aa/" + "a" * 64 + ".gif": _FILE_A})

    summary = rec.reconcile(bucket, "b", conn, apply=True)

    assert summary["orphans"] == 1
    assert summary["seen"] == 0
    assert bucket.deletes == []


def test_duplicate_within_same_guild_collapses_to_one_row(conn):
    """Dos objetos del mismo archivo en el MISMO servidor: el UNIQUE(guild_id,
    url) impide repuntar los dos a la URL canónica, así que la fila que choca
    se borra en vez de quedar apuntando a un objeto ya borrado."""
    legacy_1 = _legacy_key(_GUILD_A, "https://cdn.discordapp.com/uno.gif")
    legacy_2 = _legacy_key(_GUILD_A, "https://cdn.discordapp.com/dos.gif")
    bucket = _FakeBucket({legacy_1: _FILE_A, legacy_2: _FILE_A})
    _add_gif(conn, _GUILD_A, legacy_1)
    _add_gif(conn, _GUILD_A, legacy_2)

    rec.reconcile(bucket, "b", conn, apply=True)

    canonical = r2.gif_key(_hash(_FILE_A))
    rows = conn.execute("SELECT url, content_hash FROM corpus_gifs").fetchall()
    assert rows == [(_url(canonical), _hash(_FILE_A))]
    assert set(bucket.objects) == {canonical}


def test_rebuilds_gif_objects_with_real_ref_counts(conn):
    canonical_a = r2.gif_key(_hash(_FILE_A))
    canonical_b = r2.gif_key(_hash(_FILE_B))
    legacy = _legacy_key(_GUILD_B, "https://cdn.discordapp.com/x.gif")
    bucket = _FakeBucket(
        {
            canonical_a: _optimized(_FILE_A),
            legacy: _FILE_A,
            canonical_b: _optimized(_FILE_B),
        }
    )
    # A lo referencian dos servidores (uno por la key vieja); B, uno solo.
    _add_gif(conn, _GUILD_A, canonical_a, _hash(_FILE_A))
    _add_gif(conn, _GUILD_B, legacy)
    _add_gif(conn, _GUILD_A, canonical_b, _hash(_FILE_B))
    # Un GIF de tenor no tiene objeto propio: no debe entrar en gif_objects.
    conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url) VALUES (?, ?)",
        (_GUILD_A, "https://tenor.com/view/algo"),
    )
    conn.commit()

    summary = rec.reconcile(bucket, "b", conn, apply=True)

    assert summary["rebuilt"] == 2
    rows = dict(
        (h, (k, n, s))
        for h, k, n, s in conn.execute(
            "SELECT content_hash, r2_key, ref_count, size_bytes FROM gif_objects"
        )
    )
    assert rows[_hash(_FILE_A)] == (canonical_a, 2, len(_optimized(_FILE_A)))
    assert rows[_hash(_FILE_B)] == (canonical_b, 1, len(_optimized(_FILE_B)))


def test_rerun_is_idempotent(conn):
    legacy = _legacy_key(_GUILD_A, "https://cdn.discordapp.com/x.gif")
    bucket = _FakeBucket({legacy: _FILE_A, r2.gif_key(_raw_hash(_FILE_A)): _FILE_A})
    _add_gif(conn, _GUILD_A, legacy)
    _add_gif(conn, _GUILD_B, r2.gif_key(_raw_hash(_FILE_A)))

    first = rec.reconcile(bucket, "b", conn, apply=True)
    before = dict(bucket.objects)
    rows_before = conn.execute(
        "SELECT url, content_hash FROM corpus_gifs ORDER BY id"
    ).fetchall()

    second = rec.reconcile(bucket, "b", conn, apply=True)

    assert first["deleted"] == 2
    assert (second["moved"], second["deleted"]) == (0, 0)
    assert bucket.objects == before
    assert (
        conn.execute("SELECT url, content_hash FROM corpus_gifs ORDER BY id").fetchall()
        == rows_before
    )


def test_dangling_rows_lose_their_stale_hash(conn):
    """Fila que apunta a un objeto que ya no está: su content_hash viejo no
    debe sobrevivir a la reconstrucción de gif_objects."""
    _add_gif(conn, _GUILD_A, "gifs/ff/" + "f" * 64 + ".gif", "f" * 64)
    bucket = _FakeBucket({})

    summary = rec.reconcile(bucket, "b", conn, apply=True)

    assert summary["dangling"] == 1
    assert conn.execute("SELECT content_hash FROM corpus_gifs").fetchone() == (None,)
    assert conn.execute("SELECT COUNT(*) FROM gif_objects").fetchone()[0] == 0
