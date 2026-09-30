"""R2 con tres buckets: imágenes, GIFs y backups (ver src/r2.py).

Cada test mira QUÉ BUCKET toca cada operación (FakeS3.calls / .buckets): el
punto de la separación es que un GIF nunca caiga en el bucket de imágenes, una
imagen nunca en el de GIFs y un backup nunca en ninguno de los dos públicos.
"""

import asyncio
import inspect

import pytest
from fake_s3 import FakeS3

import r2

IMAGES_BUCKET = "purgito-images"
GIFS_BUCKET = "purgito-gifs"
BACKUP_BUCKET = "purgito-backups"
IMAGES_URL = "https://img.example.com"
GIFS_URL = "https://gif.example.com"
OLD_URL = "https://pub-viejo.r2.dev"

# Bytes que no son un GIF decodificable a propósito: sin fingerprint, la subida
# no consulta la DB (el matching perceptual lo cubre test_gif_dedup.py).
GIF_BYTES = b"GIF89a-bytes-de-prueba"


@pytest.fixture
def s3(monkeypatch):
    """Cliente falso con los tres buckets y la configuración nueva completa."""
    fake = FakeS3(IMAGES_BUCKET, GIFS_BUCKET, BACKUP_BUCKET)
    monkeypatch.setattr(r2, "get_client", lambda: fake)
    monkeypatch.setenv("R2_IMAGES_BUCKET", IMAGES_BUCKET)
    monkeypatch.setenv("R2_IMAGES_PUBLIC_URL", IMAGES_URL)
    monkeypatch.setenv("R2_GIFS_BUCKET", GIFS_BUCKET)
    monkeypatch.setenv("R2_GIFS_PUBLIC_URL", GIFS_URL)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BACKUP_BUCKET)
    monkeypatch.setattr(r2, "optimize_gif_bytes", lambda data: data)
    return fake


def _hash(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


# ─── 1-4: cada recurso va a su bucket y arma la URL de su bucket ──────────────


def test_gif_va_al_bucket_de_gifs(s3):
    up = r2.upload_gif_bytes_sync(GIF_BYTES)

    key = r2.gif_key(_hash(GIF_BYTES))
    assert up.content_hash == _hash(GIF_BYTES)
    assert s3.keys(GIFS_BUCKET) == {key}
    assert s3.keys(IMAGES_BUCKET) == set()
    assert s3.keys(BACKUP_BUCKET) == set()
    # y ninguna operación, ni siquiera de lectura, toca otro bucket
    assert {bucket for _op, bucket, _key in s3.calls} == {GIFS_BUCKET}


def test_imagen_va_al_bucket_de_imagenes(s3):
    url = r2.upload_image_bytes_sync(
        "https://cdn.discordapp.com/x.png", b"png", 42, ".png"
    )

    assert url is not None
    assert len(s3.keys(IMAGES_BUCKET)) == 1
    assert s3.keys(GIFS_BUCKET) == set()
    assert s3.keys(BACKUP_BUCKET) == set()
    assert {bucket for _op, bucket, _key in s3.calls} == {IMAGES_BUCKET}


def test_una_imagen_gif_va_al_bucket_de_imagenes_no_al_de_gifs(s3):
    """La extensión no decide: un .gif del pool de memes o del editor de embeds
    es una imagen. El bucket de GIFs es para los GIFs content-addressed."""
    url = r2.upload_image_bytes_sync("panel-upload:abc", b"GIF89a", 7, ".gif")

    assert url.startswith(f"{IMAGES_URL}/7/")
    assert len(s3.keys(IMAGES_BUCKET)) == 1
    assert s3.keys(GIFS_BUCKET) == set()


def test_la_url_del_gif_usa_la_url_publica_de_gifs(s3):
    up = r2.upload_gif_bytes_sync(GIF_BYTES)

    assert up.url == f"{GIFS_URL}/{r2.gif_key(up.content_hash)}"
    assert IMAGES_URL not in up.url


def test_la_url_de_la_imagen_usa_la_url_publica_de_imagenes(s3):
    url = r2.upload_image_bytes_sync("https://x/i.png", b"png", 42, ".png")

    assert url.startswith(f"{IMAGES_URL}/42/")
    assert url.endswith(".png")
    assert GIFS_URL not in url


def test_las_keys_conservan_el_esquema_actual(s3):
    up = r2.upload_gif_bytes_sync(GIF_BYTES)
    assert (
        r2.gif_key(up.content_hash)
        == f"gifs/{up.content_hash[:2]}/{up.content_hash}.gif"
    )

    url = r2.upload_image_bytes_sync("https://x/i.png", b"png", 42, ".png")
    key = url[len(IMAGES_URL) + 1 :]
    guild, _, name = key.partition("/")
    assert guild == "42" and name.endswith(".png") and len(name) == 32 + len(".png")


def test_cache_control_y_content_type_siguen_iguales(s3):
    r2.upload_gif_bytes_sync(GIF_BYTES)
    r2.upload_image_bytes_sync("https://x/i.webp", b"webp", 1, ".webp")

    gif = s3.buckets[GIFS_BUCKET][r2.gif_key(_hash(GIF_BYTES))]
    (img,) = s3.buckets[IMAGES_BUCKET].values()
    assert gif["ContentType"] == "image/gif"
    assert img["ContentType"] == "image/webp"
    assert (
        gif["CacheControl"]
        == img["CacheControl"]
        == "public, max-age=1209600, immutable"
    )


def test_public_url_unica_ya_no_existe():
    """La URL pública ambigua desapareció: hay que elegir imágenes o GIFs."""
    assert not hasattr(r2, "public_url")
    assert not hasattr(r2, "_bucket")
    assert not hasattr(r2, "available")


# ─── 7: la deduplicación de GIFs sigue igual, sobre el bucket de GIFs ─────────


def test_dedup_exacta_no_vuelve_a_subir(s3):
    a = r2.upload_gif_bytes_sync(GIF_BYTES)
    b = r2.upload_gif_bytes_sync(GIF_BYTES)

    assert a.content_hash == b.content_hash and a.url == b.url
    assert len(s3.ops("put_object")) == 1
    # el head que decide si subir mira el bucket de GIFs, no el de imágenes
    assert {bucket for _op, bucket, _k in s3.ops("head_object")} == {GIFS_BUCKET}


def test_un_gif_del_bucket_de_imagenes_no_cuenta_como_ya_subido(s3):
    """Mismo nombre de key en el bucket equivocado no puede hacer creer que el
    GIF ya está: el head va al de GIFs."""
    key = r2.gif_key(_hash(GIF_BYTES))
    s3.seed(IMAGES_BUCKET, key, GIF_BYTES)

    r2.upload_gif_bytes_sync(GIF_BYTES)

    assert key in s3.keys(GIFS_BUCKET)


# ─── 8-10: borrar, listar y leer GIFs actúa sobre el bucket de GIFs ───────────


def test_delete_gif_key_borra_del_bucket_de_gifs(s3):
    key = r2.gif_key(_hash(GIF_BYTES))
    s3.seed(GIFS_BUCKET, key, GIF_BYTES)
    s3.seed(IMAGES_BUCKET, key, b"otra-cosa-con-la-misma-key")

    asyncio.run(r2.delete_gif_key(key))

    assert key not in s3.keys(GIFS_BUCKET)
    assert key in s3.keys(IMAGES_BUCKET)
    assert s3.ops("delete_object") == [("delete_object", GIFS_BUCKET, key)]


def test_delete_gif_url_y_delete_image_url_respetan_su_bucket(s3):
    gif_key = r2.gif_key(_hash(GIF_BYTES))
    s3.seed(GIFS_BUCKET, gif_key)
    s3.seed(IMAGES_BUCKET, "42/abc.png")

    # cruzadas: no-op, cada URL solo la borra quien la reconoce
    asyncio.run(r2.delete_gif_url(f"{IMAGES_URL}/42/abc.png"))
    asyncio.run(r2.delete_image_url(f"{GIFS_URL}/{gif_key}"))
    assert s3.ops("delete_object") == []

    asyncio.run(r2.delete_gif_url(f"{GIFS_URL}/{gif_key}"))
    asyncio.run(r2.delete_image_url(f"{IMAGES_URL}/42/abc.png"))
    assert s3.ops("delete_object") == [
        ("delete_object", GIFS_BUCKET, gif_key),
        ("delete_object", IMAGES_BUCKET, "42/abc.png"),
    ]
    assert s3.keys(GIFS_BUCKET) == s3.keys(IMAGES_BUCKET) == set()


def test_delete_ignora_urls_externas(s3):
    asyncio.run(r2.delete_gif_url("https://media.tenor.com/x/y.gif"))
    asyncio.run(r2.delete_image_url("https://cdn.discordapp.com/attachments/1/2/i.png"))
    assert s3.ops("delete_object") == []


def test_list_gif_keys_lista_solo_el_bucket_de_gifs(s3):
    s3.seed(GIFS_BUCKET, "gifs/aa/1.gif", b"1")
    s3.seed(GIFS_BUCKET, "gifs/bb/2.gif", b"22")
    s3.seed(GIFS_BUCKET, "gifs/cc/3.gif", b"333")
    s3.seed(IMAGES_BUCKET, "gifs/zz/intruso.gif", b"x")
    s3.seed(IMAGES_BUCKET, "42/meme.png", b"x")

    keys = [k for k, _size, _mtime in r2.list_gif_keys_sync(r2.GIF_KEY_PREFIX)]

    assert keys == ["gifs/aa/1.gif", "gifs/bb/2.gif", "gifs/cc/3.gif"]
    assert {bucket for _op, bucket, _k in s3.calls} <= {GIFS_BUCKET}


def test_get_gif_bytes_lee_del_bucket_de_gifs(s3):
    key = r2.gif_key(_hash(GIF_BYTES))
    s3.seed(GIFS_BUCKET, key, GIF_BYTES)
    s3.seed(IMAGES_BUCKET, key, b"los-bytes-del-bucket-equivocado")

    assert r2.get_gif_bytes_sync(key) == GIF_BYTES
    assert s3.ops("get_object") == [("get_object", GIFS_BUCKET, key)]


# ─── Las keys cruzadas se rechazan al escribir (segunda llave) ────────────────


def test_put_object_rechaza_una_key_que_no_es_del_bucket(s3):
    with pytest.raises(ValueError):
        r2._put_object(r2.GIFS, "42/meme.gif", b"x", "image/gif")
    with pytest.raises(ValueError):
        r2._put_object(r2.IMAGES, "gifs/aa/h.gif", b"x", "image/gif")
    with pytest.raises(ValueError):
        r2._put_object(r2.BACKUPS, "bot-1.db", b"x", "application/octet-stream")
    assert s3.ops("put_object") == []


def test_ninguna_funcion_mezcla_los_stores():
    """Guardia estática: el código de cada recurso nombra solo SU store."""
    gif_fns = (
        r2.upload_gif_bytes_sync,
        r2.upload_gif_sync,
        r2.get_gif_bytes_sync,
        r2.list_gif_keys_sync,
        r2.delete_gif_key,
        r2.delete_gif_url,
        r2._gif_object_exists,
    )
    for fn in gif_fns:
        src = inspect.getsource(fn)
        assert "IMAGES" not in src and "images" not in src.lower().replace(
            "imágenes", ""
        ), fn
    for fn in (r2.upload_image_bytes_sync, r2.delete_image_url):
        src = inspect.getsource(fn)
        assert "GIFS" not in src and "public_gifs_url" not in src, fn
    for fn in (
        r2.upload_backup_file_sync,
        r2.list_backups_sync,
        r2.download_backup_sync,
        r2._backup_client_and_bucket,
    ):
        src = inspect.getsource(fn)
        assert "IMAGES" not in src and "GIFS" not in src and "public_" not in src, fn


# ─── 6 y 15 (parte de r2): backups al bucket privado ──────────────────────────


def test_backup_va_al_bucket_de_backups_y_solo_a_ese(s3, tmp_path):
    db = tmp_path / "bot-20260812-031700.db"
    db.write_bytes(b"SQLite format 3\x00" + b"x" * 100)

    key = r2.upload_backup_file_sync(str(db))

    assert key == "bot-20260812-031700.db"
    assert s3.keys(BACKUP_BUCKET) == {key}
    assert s3.keys(IMAGES_BUCKET) == s3.keys(GIFS_BUCKET) == set()
    assert {bucket for _op, bucket, _k in s3.calls} == {BACKUP_BUCKET}
    obj = s3.buckets[BACKUP_BUCKET][key]
    # nada pensado para servirse: sin Cache-Control ni URL
    assert "CacheControl" not in obj
    assert obj["Metadata"]["sha256"] == _hash(db.read_bytes())


def test_backup_no_necesita_url_publica(s3, tmp_path, monkeypatch):
    monkeypatch.delenv("R2_IMAGES_PUBLIC_URL")
    monkeypatch.delenv("R2_GIFS_PUBLIC_URL")
    f = tmp_path / "bot-1.db"
    f.write_bytes(b"datos")

    assert r2.backups_available()
    assert r2.upload_backup_file_sync(str(f)) == "bot-1.db"
    with pytest.raises(ValueError):
        r2.public_base(r2.BACKUPS)
    assert r2.BACKUPS.public_var is None


def test_el_bucket_de_backups_nunca_cae_en_el_bucket_viejo(monkeypatch):
    monkeypatch.setenv("R2_BUCKET_NAME", "bucket-viejo")
    monkeypatch.setenv("R2_PUBLIC_URL", OLD_URL)

    assert r2.bucket_for(r2.BACKUPS) == ""
    assert r2.bucket_for(r2.BACKUPS, legacy=False) == ""


def test_backup_falla_fuerte_si_put_object_falla(s3, tmp_path):
    f = tmp_path / "bot-1.db"
    f.write_bytes(b"datos")
    s3.fail_put = True

    with pytest.raises(r2.BackupError):
        r2.upload_backup_file_sync(str(f))


def test_backup_falla_si_el_objeto_queda_truncado(s3, tmp_path, monkeypatch):
    f = tmp_path / "bot-1.db"
    f.write_bytes(b"datos-completos")
    real_head = s3.head_object
    monkeypatch.setattr(
        s3, "head_object", lambda **kw: {**real_head(**kw), "ContentLength": 3}
    )

    with pytest.raises(r2.BackupError, match="bytes"):
        r2.upload_backup_file_sync(str(f))


def test_backup_sin_bucket_configurado_falla_sin_tocar_nada(s3, tmp_path, monkeypatch):
    monkeypatch.delenv("R2_BACKUP_BUCKET")
    f = tmp_path / "bot-1.db"
    f.write_bytes(b"datos")

    assert not r2.backups_available()
    with pytest.raises(r2.BackupError, match="R2_BACKUP_BUCKET"):
        r2.upload_backup_file_sync(str(f))
    assert s3.calls == []


def test_backup_download_verifica_el_sha256(s3, tmp_path):
    f = tmp_path / "bot-1.db"
    f.write_bytes(b"contenido")
    r2.upload_backup_file_sync(str(f))

    dest = tmp_path / "bajado.db"
    r2.download_backup_sync("bot-1.db", str(dest))
    assert dest.read_bytes() == b"contenido"
    assert oct(dest.stat().st_mode & 0o777) == "0o600"

    s3.buckets[BACKUP_BUCKET]["bot-1.db"]["Body"] = b"corrupto!!"
    with pytest.raises(r2.BackupError, match="sha256"):
        r2.download_backup_sync("bot-1.db", str(tmp_path / "otro.db"))


def test_list_backups_ordena_por_fecha(s3):
    for name in (
        "bot-20260812-031700.db",
        "bot-20260811-031700.db",
        "bot-20260813-031700.db",
    ):
        s3.seed(BACKUP_BUCKET, name)

    assert [k for k, _s, _m in r2.list_backups_sync()] == [
        "bot-20260811-031700.db",
        "bot-20260812-031700.db",
        "bot-20260813-031700.db",
    ]


# ─── 11: configuración incompleta -> falla o degrada de forma segura ──────────


@pytest.mark.parametrize(
    "falta",
    [
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    ],
)
def test_sin_credenciales_no_hay_cliente_ni_r2_disponible(monkeypatch, falta):
    for name, value in {
        "R2_ENDPOINT_URL": "https://acc.r2.cloudflarestorage.com",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
        "R2_IMAGES_BUCKET": IMAGES_BUCKET,
        "R2_IMAGES_PUBLIC_URL": IMAGES_URL,
        "R2_GIFS_BUCKET": GIFS_BUCKET,
        "R2_GIFS_PUBLIC_URL": GIFS_URL,
        "R2_BACKUP_BUCKET": BACKUP_BUCKET,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(falta)

    assert r2.get_client() is None
    assert not (r2.images_available() or r2.gifs_available() or r2.backups_available())
    assert r2.upload_gif_bytes_sync(GIF_BYTES) is None
    assert r2.upload_image_bytes_sync("u", b"x", 1, ".png") is None
    assert r2.config_warnings()


def test_con_credenciales_el_cliente_se_crea_sin_bucket(monkeypatch):
    """El cliente es de la cuenta: no depende de ningún bucket."""
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://acc.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "s")

    assert r2.get_client() is not None
    assert not r2.gifs_available() and not r2.images_available()


@pytest.mark.parametrize(
    "borrar, cae",
    [
        ("R2_GIFS_BUCKET", "gifs"),
        ("R2_GIFS_PUBLIC_URL", "gifs"),
        ("R2_IMAGES_BUCKET", "images"),
        ("R2_IMAGES_PUBLIC_URL", "images"),
    ],
)
def test_un_store_incompleto_se_apaga_solo_ese(s3, monkeypatch, borrar, cae):
    monkeypatch.delenv(borrar)

    assert r2.gifs_available() is (cae != "gifs")
    assert r2.images_available() is (cae != "images")
    if cae == "gifs":
        assert r2.upload_gif_bytes_sync(GIF_BYTES) is None
        assert r2.upload_gif_sync("https://cdn.discordapp.com/x.gif") is None
        assert r2.upload_image_bytes_sync("u", b"png", 1, ".png") is not None
    else:
        assert r2.upload_image_bytes_sync("u", b"png", 1, ".png") is None
        assert r2.upload_gif_bytes_sync(GIF_BYTES) is not None
    assert any(cae in w for w in r2.config_warnings())


def test_sin_url_publica_no_se_guarda_una_url_rota(s3, monkeypatch):
    """Sin R2_GIFS_PUBLIC_URL la URL sería '/gifs/xx/h.gif': mejor no subir."""
    monkeypatch.delenv("R2_GIFS_PUBLIC_URL")

    assert r2.upload_gif_bytes_sync(GIF_BYTES) is None
    assert s3.ops("put_object") == []


def test_configuracion_completa_no_genera_avisos(s3):
    assert r2.config_warnings() == []


# ─── 12: fallback de las variables viejas, solo como transición ───────────────


@pytest.fixture
def solo_legacy(monkeypatch):
    fake = FakeS3("bucket-viejo")
    monkeypatch.setattr(r2, "get_client", lambda: fake)
    monkeypatch.setenv("R2_BUCKET_NAME", "bucket-viejo")
    monkeypatch.setenv("R2_PUBLIC_URL", OLD_URL + "/")
    monkeypatch.setattr(r2, "optimize_gif_bytes", lambda data: data)
    return fake


def test_fallback_legacy_reproduce_el_comportamiento_de_un_solo_bucket(solo_legacy):
    """Desplegar el código nuevo sin tocar el .env deja todo como estaba."""
    up = r2.upload_gif_bytes_sync(GIF_BYTES)
    img = r2.upload_image_bytes_sync("https://x/i.png", b"png", 9, ".png")

    assert r2.gifs_available() and r2.images_available()
    assert up.url == f"{OLD_URL}/{r2.gif_key(up.content_hash)}"
    assert img.startswith(f"{OLD_URL}/9/")
    assert {b for _op, b, _k in solo_legacy.calls} == {"bucket-viejo"}
    assert r2.legacy_vars_set() == ["R2_BUCKET_NAME", "R2_PUBLIC_URL"]
    assert any(
        "R2_BUCKET_NAME" in w and "R2_PUBLIC_URL" in w for w in r2.config_warnings()
    )


def test_las_variables_nuevas_mandan_sobre_las_viejas(s3, monkeypatch):
    monkeypatch.setenv("R2_BUCKET_NAME", "bucket-viejo")
    monkeypatch.setenv("R2_PUBLIC_URL", OLD_URL)

    assert r2.bucket_for(r2.GIFS) == GIFS_BUCKET
    assert r2.bucket_for(r2.IMAGES) == IMAGES_BUCKET
    assert r2.public_gifs_url() == GIFS_URL
    assert r2.public_images_url() == IMAGES_URL
    up = r2.upload_gif_bytes_sync(GIF_BYTES)
    assert up.url.startswith(GIFS_URL + "/")
    assert "bucket-viejo" not in {b for _op, b, _k in s3.calls}


def test_la_url_vieja_sigue_reconocida_como_alias_mientras_este_definida(
    s3, monkeypatch
):
    monkeypatch.setenv("R2_PUBLIC_URL", OLD_URL)
    gif = f"{OLD_URL}/gifs/ab/{'ab' * 32}.gif"
    legacy_gif = f"{OLD_URL}/123/abc.gif"
    img = f"{OLD_URL}/123/abc.png"

    assert r2.gif_key_from_url(gif) == f"gifs/ab/{'ab' * 32}.gif"
    assert r2.gif_key_from_url(legacy_gif) == "123/abc.gif"
    assert r2.image_key_from_url(img) == "123/abc.png"
    # un GIF content-addressed nunca es una imagen, ni por el host compartido
    assert r2.image_key_from_url(gif) is None
    assert r2.gif_public_bases() == (GIFS_URL, OLD_URL)

    # borrar por una URL vieja actúa sobre el bucket NUEVO
    s3.seed(GIFS_BUCKET, "gifs/ab/" + "ab" * 32 + ".gif")
    asyncio.run(r2.delete_gif_url(gif))
    assert s3.ops("delete_object") == [
        ("delete_object", GIFS_BUCKET, "gifs/ab/" + "ab" * 32 + ".gif")
    ]


def test_sin_las_variables_viejas_no_queda_ningun_fallback(s3):
    """El estado final de la migración: nada del esquema viejo."""
    assert r2.legacy_vars_set() == []
    assert r2.gif_public_bases() == (GIFS_URL,)
    assert r2.image_public_bases() == (IMAGES_URL,)
    assert r2.gif_key_from_url(f"{OLD_URL}/gifs/ab/x.gif") is None
    assert r2.image_key_from_url(f"{OLD_URL}/1/x.png") is None
    assert r2.config_warnings() == []


def test_sin_nuevas_ni_viejas_no_hay_r2(monkeypatch):
    assert not r2.gifs_available() and not r2.images_available()
    assert r2.gif_public_bases() == ()


def test_solo_r2py_lee_las_variables_viejas_en_src():
    """La dependencia de R2_BUCKET_NAME / R2_PUBLIC_URL vive en UN solo lugar
    (el fallback de r2.py): borrarlas del .env no puede romper nada más."""
    import pathlib

    src = pathlib.Path(r2.__file__).parent
    offenders = [
        p.name
        for p in src.rglob("*.py")
        if p.name != "r2.py"
        and (
            "R2_BUCKET_NAME" in p.read_text(encoding="utf-8")
            or "R2_PUBLIC_URL" in p.read_text(encoding="utf-8")
        )
    ]
    assert offenders == []


def test_el_prefijo_exige_la_barra_final_contra_hosts_que_empiezan_igual(s3):
    """Medida de seguridad que ya existía en webapi: 'https://gif.example.com.evil.com/x'
    no puede pasar por una URL del bucket, ni una URL sin key."""
    for evil in (
        f"{GIFS_URL}.evil.com/gifs/ab/x.gif",
        f"{GIFS_URL}evil/gifs/ab/x.gif",
        f"{GIFS_URL}/",
        GIFS_URL,
    ):
        assert r2.gif_key_from_url(evil) is None, evil
    assert r2.image_key_from_url(f"{IMAGES_URL}.evil.com/1/x.png") is None
    assert r2.gif_key_from_url(None) is None
    assert r2.gif_key_from_url(f"{GIFS_URL}/gifs/ab/x.gif") == "gifs/ab/x.gif"
