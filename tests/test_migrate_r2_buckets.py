"""scripts/migrate_r2_buckets.py: copia del bucket único a imágenes + GIFs.

Las garantías que sostienen el procedimiento de DEPLOY.md: clasifica por la DB
y no por la extensión, se puede correr las veces que haga falta, NUNCA borra
nada y no pisa un destino que ya tiene otro contenido.
"""

import importlib.util
import json
import pathlib
import pg_support
import stat
import subprocess

import pytest
from fake_s3 import FakeS3

import r2

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "migrate_r2_buckets", ROOT / "scripts" / "migrate_r2_buckets.py"
)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

OLD = "old-bucket"
GIFS = "purgito-gifs"
IMAGES = "purgito-images"
BACKUPS = "purgito-backups"
OLD_URL = "https://pub-viejo.r2.dev"
GIFS_URL = "https://gif.example.com"
IMAGES_URL = "https://img.example.com"
DEST = {"gifs": GIFS, "images": IMAGES}

H = "ab" * 32
GIF_KEY = f"gifs/ab/{H}.gif"
ORPHAN_GIF = "gifs/zz/" + "zz" * 32 + ".gif"
LEGACY_GIF = "123/0aa1.gif"  # generación 1: un GIF sin el prefijo gifs/
IMG_PNG = "123/meme.png"
IMG_GIF = "123/imagen-que-es-un.gif"  # .gif pero imagen según la DB
EMBED_IMG = "456/subida-del-editor.webp"
BLOB_IMG = "456/dentro-del-json.png"
ORPHAN_IMG = "999/huerfana.png"
BOTH = "777/compartida.gif"


@pytest.fixture
def s3():
    fake = FakeS3(OLD, GIFS, IMAGES, BACKUPS)
    cache = "public, max-age=31536000, immutable"
    fake.seed(OLD, GIF_KEY, b"GIF89a-uno", ContentType="image/gif", CacheControl=cache)
    fake.seed(
        OLD, ORPHAN_GIF, b"GIF89a-huerfano", ContentType="image/gif", CacheControl=cache
    )
    fake.seed(OLD, LEGACY_GIF, b"GIF89a-legacy", ContentType="image/gif")
    fake.seed(OLD, IMG_PNG, b"png", ContentType="image/png", CacheControl=cache)
    fake.seed(OLD, IMG_GIF, b"GIF89a-imagen", ContentType="image/gif")
    fake.seed(
        OLD, EMBED_IMG, b"webp", ContentType="image/webp", Metadata={"origen": "panel"}
    )
    fake.seed(OLD, BLOB_IMG, b"png2", ContentType="image/png")
    fake.seed(OLD, ORPHAN_IMG, b"png3", ContentType="image/png")
    fake.seed(OLD, BOTH, b"GIF89a-ambos", ContentType="image/gif")
    return fake


@pytest.fixture
def conn():
    c = pg_support.sync_connect()
    c.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count) VALUES (?, ?, 1)",
        (H, GIF_KEY),
    )
    rows = [
        ("corpus_gifs", f"{OLD_URL}/{GIF_KEY}"),
        ("corpus_gifs", f"{OLD_URL}/{LEGACY_GIF}"),
        ("corpus_gifs", f"{OLD_URL}/{BOTH}"),
        ("corpus_gifs", "https://media.tenor.com/x/y.gif"),  # externo: se ignora
        ("corpus_images", f"{OLD_URL}/{IMG_PNG}"),
        ("corpus_images", f"{OLD_URL}/{IMG_GIF}"),
        ("corpus_images", f"{OLD_URL}/{BOTH}"),
        ("embed_uploaded_images", f"{OLD_URL}/{EMBED_IMG}"),
    ]
    for table, url in rows:
        c.execute(f"INSERT INTO {table} (guild_id, url) VALUES (1, ?)", (url,))
    c.execute(
        "INSERT INTO embed_templates (guild_id, name, embed_json) VALUES (1, 'x', ?)",
        (json.dumps({"image": {"url": f"{OLD_URL}/{BLOB_IMG}"}}),),
    )
    c.commit()
    yield c
    c.close()


def _refs(conn):
    return mig.load_references(conn, OLD_URL)


def _run(s3, conn, **kw):
    gif_keys, image_keys = _refs(conn)
    kw.setdefault("apply", True)
    return mig.migrate(s3, OLD, DEST, gif_keys, image_keys, progress_every=0, **kw)


# ─── Clasificación: manda la DB, no la extensión ──────────────────────────────


def test_clasificacion_por_la_db(conn):
    gif_keys, image_keys = _refs(conn)
    c = lambda key: mig.classify(key, gif_keys, image_keys)  # noqa: E731

    assert c(GIF_KEY) == (("gifs",), "db-gif")
    assert c(LEGACY_GIF) == (("gifs",), "db-gif")  # GIF legacy, sin prefijo gifs/
    assert c(IMG_PNG) == (("images",), "db-imagen")
    assert c(IMG_GIF) == (("images",), "db-imagen")  # .gif, pero la DB dice imagen
    assert c(EMBED_IMG) == (("images",), "db-imagen")
    assert c(BLOB_IMG) == (("images",), "db-imagen")  # solo aparece dentro de un JSON
    assert c(BOTH) == (("gifs", "images"), "ambos")
    assert c(ORPHAN_GIF) == (("gifs",), "prefijo-gifs")
    assert c(ORPHAN_IMG) == (("images",), "sin-referencia")
    # la extensión sola nunca manda: un .gif sin prefijo ni referencia es imagen
    assert c("555/suelto.gif") == (("images",), "sin-referencia")


def test_load_references_tolera_una_db_sin_algunas_tablas():
    c = pg_support.sync_connect()
    # una base más vieja que el esquema actual: solo corpus_gifs
    for (name,) in c.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename <> 'corpus_gifs'"
    ).fetchall():
        c.execute(f'DROP TABLE "{name}"')
    c.execute(
        "INSERT INTO corpus_gifs (guild_id, url) VALUES (1, ?)",
        (f"{OLD_URL}/gifs/aa/x.gif",),
    )
    c.commit()

    try:
        assert mig.load_references(c, OLD_URL) == ({"gifs/aa/x.gif"}, set())
    finally:
        c.close()


# ─── La copia ─────────────────────────────────────────────────────────────────


def test_copia_cada_objeto_a_su_bucket(s3, conn):
    stats = _run(s3, conn)

    assert s3.keys(GIFS) == {GIF_KEY, ORPHAN_GIF, LEGACY_GIF, BOTH}
    assert s3.keys(IMAGES) == {IMG_PNG, IMG_GIF, EMBED_IMG, BLOB_IMG, ORPHAN_IMG, BOTH}
    assert stats["vistos"] == 9
    assert stats["copiado"] == 10  # BOTH va a los dos
    assert stats["error"] == 0


def test_nunca_borra_nada_ni_en_el_origen_ni_en_los_destinos(s3, conn):
    before = {k: dict(v) for k, v in s3.buckets[OLD].items()}

    _run(s3, conn)
    _run(s3, conn)

    assert s3.ops("delete_object") == []
    assert {k: dict(v) for k, v in s3.buckets[OLD].items()} == before


def test_el_script_no_contiene_ninguna_llamada_de_borrado():
    src = (ROOT / "scripts" / "migrate_r2_buckets.py").read_text(encoding="utf-8")
    assert "delete_object" not in src and "delete_objects" not in src
    assert "delete_bucket" not in src


def test_es_idempotente(s3, conn):
    _run(s3, conn)
    snapshot = {
        b: {k: dict(o) for k, o in objs.items()} for b, objs in s3.buckets.items()
    }
    calls_before = len(s3.calls)

    stats = _run(s3, conn)

    assert stats["copiado"] == 0 and stats["error"] == 0
    assert stats["ya-estaba"] == 10
    new_calls = s3.calls[calls_before:]
    assert [op for op, _b, _k in new_calls if op in ("copy_object", "put_object")] == []
    assert {
        b: {k: dict(o) for k, o in objs.items()} for b, objs in s3.buckets.items()
    } == snapshot


def test_retoma_donde_quedo_si_una_corrida_se_interrumpio(s3, conn):
    _run(s3, conn, limit=3)
    primera = len(s3.ops("copy_object"))

    stats = _run(s3, conn)

    assert primera > 0
    assert stats["copiado"] + primera == 10  # 10 copias en total, ninguna repetida
    assert s3.keys(GIFS) == {GIF_KEY, ORPHAN_GIF, LEGACY_GIF, BOTH}


def test_preserva_content_type_cache_control_y_metadata(s3, conn):
    _run(s3, conn)

    for bucket, key in (
        (GIFS, GIF_KEY),
        (IMAGES, IMG_PNG),
        (IMAGES, EMBED_IMG),
        (GIFS, LEGACY_GIF),
    ):
        src, dst = (
            s3.head_object(Bucket=OLD, Key=key),
            s3.head_object(Bucket=bucket, Key=key),
        )
        for field in ("ContentType", "CacheControl", "Metadata"):
            assert dst.get(field) == src.get(field), (key, field)
    assert s3.head_object(Bucket=IMAGES, Key=EMBED_IMG)["Metadata"] == {
        "origen": "panel"
    }


def test_dry_run_no_escribe_nada(s3, conn):
    stats = _run(s3, conn, apply=False)

    assert s3.ops("copy_object", "put_object", "delete_object") == []
    assert s3.keys(GIFS) == s3.keys(IMAGES) == set()
    assert stats["se-copiaría"] == 10 and stats["copiado"] == 0
    assert stats["bytes:gifs"] > 0 and stats["bytes:images"] > 0


def test_no_pisa_un_destino_con_otro_contenido(s3, conn):
    s3.seed(GIFS, GIF_KEY, b"GIF89a-OTRO-CONTENIDO")

    stats = _run(s3, conn)

    assert stats["distinto"] == 1
    assert s3.buckets[GIFS][GIF_KEY]["Body"] == b"GIF89a-OTRO-CONTENIDO"
    assert (GIFS, GIF_KEY) not in [(b, k) for op, b, k in s3.ops("copy_object")]


def test_un_error_en_un_objeto_no_frena_el_resto(s3, conn, monkeypatch):
    real = s3.copy_object

    def falla_una(Bucket, Key, **kw):
        if Key == IMG_PNG:
            raise RuntimeError("red caída")
        return real(Bucket=Bucket, Key=Key, **kw)

    monkeypatch.setattr(s3, "copy_object", falla_una)

    stats = _run(s3, conn)

    assert stats["error"] == 1
    assert IMG_PNG not in s3.keys(IMAGES)
    assert stats["copiado"] == 9
    # y al reintentar (ya sano) completa lo que faltaba
    monkeypatch.setattr(s3, "copy_object", real)
    assert _run(s3, conn)["copiado"] == 1


def test_skip_unreferenced_omite_lo_que_la_db_no_conoce(s3, conn):
    stats = _run(s3, conn, skip_unreferenced=True)

    assert ORPHAN_IMG not in s3.keys(IMAGES)
    assert ORPHAN_GIF in s3.keys(GIFS)  # el prefijo gifs/ sí lo identifica
    assert stats["omitido-sin-referencia"] == 1


def test_el_reporte_deja_una_linea_por_decision(s3, conn, tmp_path):
    path = tmp_path / "reporte.jsonl"
    with open(path, "w", encoding="utf-8") as report:
        _run(s3, conn, report=report)

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 10
    assert {"key", "destino", "rol", "motivo", "accion"} <= set(lines[0])
    assert {(d["key"], d["rol"]) for d in lines if d["motivo"] == "ambos"} == {
        (BOTH, "gifs"),
        (BOTH, "images"),
    }


# ─── Comprobaciones previas ───────────────────────────────────────────────────


def test_verifica_que_los_destinos_existen_antes_de_copiar():
    fake = FakeS3(OLD, GIFS)  # falta el de imágenes

    with pytest.raises(mig.ConfigError, match="images"):
        mig.check_buckets(fake, {"origen": OLD, "gifs": GIFS, "images": IMAGES})
    assert fake.ops("copy_object", "put_object") == []


def _args(**kw):
    import argparse

    base = dict(
        source_bucket=OLD,
        source_public_url=OLD_URL,
        gifs_bucket=GIFS,
        images_bucket=IMAGES,
    )
    return argparse.Namespace(**{**base, **kw})


def test_no_corre_si_origen_y_destino_son_el_mismo_bucket(s3, monkeypatch):
    monkeypatch.setattr(r2, "get_client", lambda: s3)

    with pytest.raises(mig.ConfigError, match="distintos"):
        mig._resolve_settings(_args(images_bucket=OLD))
    with pytest.raises(mig.ConfigError, match="distintos"):
        mig._resolve_settings(_args(gifs_bucket=IMAGES))


def test_no_acepta_el_bucket_de_backups_como_origen_ni_destino(s3, monkeypatch):
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BACKUPS)

    with pytest.raises(mig.ConfigError, match="backups"):
        mig._resolve_settings(_args(images_bucket=BACKUPS))
    with pytest.raises(mig.ConfigError, match="backups"):
        mig._resolve_settings(_args(source_bucket=BACKUPS))


def test_no_usa_el_fallback_legacy_para_los_destinos(s3, monkeypatch):
    """Sin R2_IMAGES_BUCKET el destino NO cae en R2_BUCKET_NAME (que es el
    origen): la migración se niega en vez de copiar un bucket sobre sí mismo."""
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setenv("R2_BUCKET_NAME", OLD)

    with pytest.raises(mig.ConfigError, match="R2_IMAGES_BUCKET"):
        mig._resolve_settings(
            _args(source_bucket=None, images_bucket=None, gifs_bucket=GIFS)
        )


def test_pide_la_url_publica_vieja_para_poder_clasificar(s3, monkeypatch):
    monkeypatch.setattr(r2, "get_client", lambda: s3)

    with pytest.raises(mig.ConfigError, match="URL pública"):
        mig._resolve_settings(_args(source_public_url=None))


# ─── verify ───────────────────────────────────────────────────────────────────


def test_verify_ok_despues_de_copiar_y_detecta_lo_que_falta(s3, conn):
    _run(s3, conn)
    gif_keys, image_keys = _refs(conn)

    ok = mig.verify(s3, OLD, DEST, gif_keys, image_keys)
    assert ok["ok"] == 10 and ok["faltan"] == 0 and ok["tamaño-distinto"] == 0

    del s3.buckets[IMAGES][IMG_PNG]
    s3.buckets[GIFS][GIF_KEY]["Body"] = b"GIF89a-mas-largo-que-el-original"
    bad = mig.verify(s3, OLD, DEST, gif_keys, image_keys)
    assert bad["faltan"] == 1 and bad["tamaño-distinto"] == 1


def test_verify_solo_lee(s3, conn):
    gif_keys, image_keys = _refs(conn)

    mig.verify(s3, OLD, DEST, gif_keys, image_keys)

    assert s3.ops("copy_object", "put_object", "delete_object") == []


# ─── rewrite-db-urls (paso opcional) ──────────────────────────────────────────


def _rewrite(conn, apply=True):
    return mig.rewrite_urls(conn, OLD_URL, IMAGES_URL, GIFS_URL, apply=apply)


def test_rewrite_dry_run_no_cambia_la_db(conn):
    before = conn.execute("SELECT url FROM corpus_gifs ORDER BY id").fetchall()

    stats = _rewrite(conn, apply=False)

    assert conn.execute("SELECT url FROM corpus_gifs ORDER BY id").fetchall() == before
    assert stats["corpus_gifs.url:coincide"] == 3
    assert not any(k.endswith(":reescrita") for k in stats)


def test_rewrite_cambia_solo_el_host_y_manda_cada_url_a_su_bucket(conn):
    _rewrite(conn)
    conn.commit()

    gifs = {r[0] for r in conn.execute("SELECT url FROM corpus_gifs")}
    assert gifs == {
        f"{GIFS_URL}/{GIF_KEY}",
        f"{GIFS_URL}/{LEGACY_GIF}",  # un GIF legacy sin prefijo igual va al host de GIFs
        f"{GIFS_URL}/{BOTH}",
        "https://media.tenor.com/x/y.gif",  # lo externo no se toca
    }
    images = {r[0] for r in conn.execute("SELECT url FROM corpus_images")}
    assert images == {
        f"{IMAGES_URL}/{IMG_PNG}",
        f"{IMAGES_URL}/{IMG_GIF}",
        f"{IMAGES_URL}/{BOTH}",
    }
    assert conn.execute("SELECT url FROM embed_uploaded_images").fetchone() == (
        f"{IMAGES_URL}/{EMBED_IMG}",
    )
    (blob,) = conn.execute("SELECT embed_json FROM embed_templates").fetchone()
    assert json.loads(blob) == {"image": {"url": f"{IMAGES_URL}/{BLOB_IMG}"}}
    # gif_objects guarda solo la key: no cambia
    assert conn.execute("SELECT r2_key FROM gif_objects").fetchone() == (GIF_KEY,)


def test_rewrite_en_texto_separa_gifs_de_imagenes_en_una_pasada():
    text = f"a {OLD_URL}/gifs/ab/x.gif b {OLD_URL}/1/i.png c {OLD_URL}/gifs/cd/y.gif"

    assert mig._rewrite_text(text, OLD_URL, IMAGES_URL, GIFS_URL) == (
        f"a {GIFS_URL}/gifs/ab/x.gif b {IMAGES_URL}/1/i.png c {GIFS_URL}/gifs/cd/y.gif"
    )


def test_rewrite_es_idempotente(conn):
    _rewrite(conn)
    conn.commit()
    snapshot = conn.execute("SELECT url FROM corpus_gifs ORDER BY id").fetchall()

    stats = _rewrite(conn)

    assert (
        conn.execute("SELECT url FROM corpus_gifs ORDER BY id").fetchall() == snapshot
    )
    assert not any(v for k, v in stats.items() if k.endswith(":coincide"))


def test_rewrite_no_pisa_una_fila_que_chocaria_por_unique(conn):
    # El bot ya guardó, con los buckets nuevos, la misma URL que tendría la vieja.
    conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url) VALUES (1, ?)",
        (f"{GIFS_URL}/{GIF_KEY}",),
    )
    conn.commit()

    stats = _rewrite(conn)

    assert stats["corpus_gifs.url:choque"] == 1
    # la fila vieja queda como estaba, sin borrarse
    assert conn.execute(
        "SELECT COUNT(*) FROM corpus_gifs WHERE url=?", (f"{OLD_URL}/{GIF_KEY}",)
    ).fetchone() == (1,)


def test_rewrite_no_adivina_una_key_de_gif_guardada_como_imagen(conn):
    conn.execute(
        "INSERT INTO corpus_images (guild_id, url) VALUES (1, ?)",
        (f"{OLD_URL}/{GIF_KEY}",),
    )
    conn.commit()

    stats = _rewrite(conn)

    assert stats["corpus_images.url:ambigua"] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM corpus_images WHERE url=?", (f"{OLD_URL}/{GIF_KEY}",)
    ).fetchone() == (1,)


def test_count_old_urls_llega_a_cero_despues_de_reescribir(conn):
    antes = mig.count_old_urls(conn, OLD_URL)
    assert antes["corpus_gifs.url"] == 3 and antes["embed_templates.embed_json"] == 1

    _rewrite(conn)
    conn.commit()

    assert not any(mig.count_old_urls(conn, OLD_URL).values())


# ─── CLI de punta a punta ─────────────────────────────────────────────────────


@pytest.fixture
def dsn(conn):
    """La base de tests, ya cargada por `conn` (commiteada), para --dsn."""
    return pg_support.TEST_URL


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def cli_env(s3, monkeypatch):
    monkeypatch.setattr(r2, "get_client", lambda: s3)
    monkeypatch.setenv("R2_BUCKET_NAME", OLD)
    monkeypatch.setenv("R2_PUBLIC_URL", OLD_URL)
    monkeypatch.setenv("R2_GIFS_BUCKET", GIFS)
    monkeypatch.setenv("R2_IMAGES_BUCKET", IMAGES)
    monkeypatch.setenv("R2_GIFS_PUBLIC_URL", GIFS_URL)
    monkeypatch.setenv("R2_IMAGES_PUBLIC_URL", IMAGES_URL)
    return s3


def test_cli_copy_dry_run_y_luego_apply_y_verify(cli_env, dsn):
    s3 = cli_env

    assert mig.main(["copy", "--dsn", dsn]) == 0
    assert s3.keys(GIFS) == s3.keys(IMAGES) == set()  # dry-run por defecto

    assert mig.main(["copy", "--apply", "--dsn", dsn]) == 0
    assert len(s3.keys(GIFS)) == 4 and len(s3.keys(IMAGES)) == 6

    assert mig.main(["verify", "--dsn", dsn]) == 0
    del s3.buckets[GIFS][GIF_KEY]
    assert mig.main(["verify", "--dsn", dsn]) == 1


def test_cli_la_db_se_abre_en_solo_lectura(cli_env, dsn, conn):
    """copy y verify solo leen la base: ni una fila cambia."""
    before = conn.execute(
        "SELECT md5(string_agg(url, ',' ORDER BY id)) FROM corpus_gifs"
    ).fetchone()
    conn.commit()

    mig.main(["copy", "--apply", "--dsn", dsn])
    mig.main(["verify", "--dsn", dsn])

    after = conn.execute(
        "SELECT md5(string_agg(url, ',' ORDER BY id)) FROM corpus_gifs"
    ).fetchone()
    conn.commit()
    assert after == before


def test_cli_sale_con_2_si_falta_un_bucket_destino(cli_env, dsn):
    del cli_env.buckets[IMAGES]

    assert mig.main(["copy", "--apply", "--dsn", dsn]) == 2
    assert cli_env.ops("copy_object") == []


def test_cli_sale_con_1_si_un_destino_tiene_otro_contenido(cli_env, dsn):
    cli_env.seed(IMAGES, IMG_PNG, b"otro-contenido")

    assert mig.main(["copy", "--apply", "--dsn", dsn]) == 1


def test_cli_rewrite_dry_run_no_toca_la_db_y_apply_deja_una_copia_0600(
    cli_env, dsn, conn, tmp_path, monkeypatch
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", dsn)
    _run(cli_env, conn)  # los objetos ya están en los buckets nuevos (copy --apply)
    assert any(mig.count_old_urls(conn, OLD_URL).values())
    conn.commit()
    assert mig.main(["rewrite-db-urls", "--dsn", dsn]) == 0
    assert any(mig.count_old_urls(conn, OLD_URL).values())
    conn.commit()
    assert list(tmp_path.glob("purgito-pre-r2-rewrite-*")) == []

    assert mig.main(["rewrite-db-urls", "--apply", "--dsn", dsn]) == 0
    conn.commit()  # cerrar la transacción de lectura para ver lo que escribió el script

    (backup,) = tmp_path.glob("purgito-pre-r2-rewrite-*.dump")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert not any(mig.count_old_urls(conn, OLD_URL).values())
    # la copia previa es un dump válido y restaurable
    listing = subprocess.run(
        ["pg_restore", "--list", str(backup)], capture_output=True, text=True
    )
    assert listing.returncode == 0 and "corpus_gifs" in listing.stdout

    # segunda corrida: no hay nada que hacer, y no deja otra copia de la DB
    assert mig.main(["rewrite-db-urls", "--apply", "--dsn", dsn]) == 0
    assert len(list(tmp_path.glob("purgito-pre-r2-rewrite-*"))) == 1


# ─── rewrite-db-urls: nunca apunta a un objeto que no está en el destino ──────


def _exists(s3):
    return lambda dest, key: mig._head(s3, DEST[dest], key) is not None


def _rw(conn, s3, apply=True):
    return mig.rewrite_urls(
        conn, OLD_URL, IMAGES_URL, GIFS_URL, apply=apply, exists=_exists(s3)
    )


def _old_urls(conn):
    return sum(mig.count_old_urls(conn, OLD_URL).values())


def test_rewrite_sin_copia_previa_no_toca_nada(s3, conn):
    antes = _old_urls(conn)
    assert antes > 0

    stats = _rw(conn, s3)
    conn.commit()

    assert not any(k.endswith(":reescrita") for k in stats)
    assert stats["corpus_gifs.url:destino-faltante"] == 3
    assert stats["embed_templates.embed_json:destino-faltante"] == 1
    assert _old_urls(conn) == antes  # la DB quedó idéntica


def test_rewrite_tras_copiar_reescribe_todo_y_no_quedan_urls_viejas(s3, conn):
    _run(s3, conn)

    stats = _rw(conn, s3)
    conn.commit()

    assert not any(k.endswith(":destino-faltante") for k in stats)
    assert _old_urls(conn) == 0
    # y cada URL nueva existe de verdad en su bucket
    for (url,) in conn.execute(
        "SELECT url FROM corpus_gifs WHERE url LIKE ?", (GIFS_URL + "/%",)
    ):
        assert mig._head(s3, GIFS, url[len(GIFS_URL) + 1 :]) is not None
    for (url,) in conn.execute("SELECT url FROM corpus_images"):
        assert mig._head(s3, IMAGES, url[len(IMAGES_URL) + 1 :]) is not None


def test_rewrite_con_un_objeto_faltante_salta_solo_esa_fila(s3, conn):
    _run(s3, conn)
    del s3.buckets[GIFS][LEGACY_GIF]

    stats = _rw(conn, s3)
    conn.commit()

    assert stats["corpus_gifs.url:destino-faltante"] == 1
    urls = {r[0] for r in conn.execute("SELECT url FROM corpus_gifs")}
    assert f"{OLD_URL}/{LEGACY_GIF}" in urls  # esa quedó como estaba
    assert f"{GIFS_URL}/{GIF_KEY}" in urls  # las demás sí pasaron


def test_rewrite_cubre_media_url_y_avatares(s3, conn):
    _run(s3, conn)
    conn.execute(
        "UPDATE corpus_gifs SET media_url=? WHERE url=?",
        (f"{OLD_URL}/{GIF_KEY}", f"{OLD_URL}/{GIF_KEY}"),
    )
    conn.execute(
        "INSERT INTO guild_bot_style (guild_id, avatar_url, banner_url) VALUES (1, ?, ?)",
        (f"{OLD_URL}/{IMG_PNG}", f"{OLD_URL}/{EMBED_IMG}"),
    )
    conn.commit()
    assert _old_urls(conn) > 0

    stats = _rw(conn, s3)
    conn.commit()

    assert stats["corpus_gifs.media_url:reescrita"] == 1
    assert stats["guild_bot_style.avatar_url:reescrita"] == 1
    assert stats["guild_bot_style.banner_url:reescrita"] == 1
    assert _old_urls(conn) == 0


def test_rewrite_texto_con_un_objeto_faltante_no_se_toca_a_medias(s3, conn):
    _run(s3, conn)
    conn.execute(
        "UPDATE embed_templates SET embed_json=?",
        (json.dumps({"a": f"{OLD_URL}/{BLOB_IMG}", "b": f"{OLD_URL}/{IMG_PNG}"}),),
    )
    conn.commit()
    del s3.buckets[IMAGES][IMG_PNG]

    stats = _rw(conn, s3)
    conn.commit()

    assert stats["embed_templates.embed_json:destino-faltante"] == 1
    (blob,) = conn.execute("SELECT embed_json FROM embed_templates").fetchone()
    assert OLD_URL in blob and IMAGES_URL not in blob  # ni una de las dos


def test_destino_no_configurado_es_un_error_y_no_se_asume_que_todo_esta(
    s3, monkeypatch
):
    monkeypatch.setattr(r2, "get_client", lambda: None)
    with pytest.raises(mig.ConfigError, match="no se puede comprobar"):
        mig._dest_exists_checker(_args())


def test_cli_rewrite_sin_copia_previa_sale_con_error_y_no_toca_la_db(
    cli_env, dsn, conn, tmp_path, monkeypatch
):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", dsn)
    antes = mig.count_old_urls(conn, OLD_URL)
    conn.commit()

    assert mig.main(["rewrite-db-urls", "--apply", "--dsn", dsn]) == 1

    conn.commit()
    assert mig.count_old_urls(conn, OLD_URL) == antes
