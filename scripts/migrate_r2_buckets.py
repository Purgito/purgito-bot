"""Migra los objetos del bucket único de R2 a los buckets de imágenes y de GIFs.

Herramienta de mantenimiento manual: el bot NO la corre ni al arrancar ni nunca.
Procedimiento completo en DEPLOY.md § "Migrar a tres buckets de R2".

    python scripts/migrate_r2_buckets.py copy                   # dry-run: solo informa
    python scripts/migrate_r2_buckets.py copy --apply           # copia de verdad
    python scripts/migrate_r2_buckets.py verify                 # ¿está todo en los destinos?
    python scripts/migrate_r2_buckets.py rewrite-db-urls        # dry-run: URLs viejas en la DB
    python scripts/migrate_r2_buckets.py rewrite-db-urls --apply  # opcional, ver abajo

## Qué hace `copy`

Recorre el bucket viejo (R2_BUCKET_NAME) y copia cada objeto, con CopyObject del
lado del servidor (los bytes no pasan por acá), a:

- R2_GIFS_BUCKET    los GIFs,
- R2_IMAGES_BUCKET  las imágenes.

NUNCA borra nada: no hay ninguna llamada a delete en este archivo, ni en el
origen ni en los destinos. El bucket viejo queda intacto y se elimina a mano,
mucho después, desde el dashboard de Cloudflare.

Es idempotente: un objeto que ya está en el destino con el mismo tamaño (y el
mismo ETag, cuando los dos son md5 simples) se salta; se puede correr las veces
que haga falta, y conviene una vez más después de reiniciar el bot con los
buckets nuevos para alcanzar lo que se subió en el medio. Un destino que existe
con contenido DISTINTO no se pisa: se informa como "distinto" y el script sale
con error, para que una persona decida. Se conservan ContentType, CacheControl,
ContentDisposition, ContentEncoding, ContentLanguage y los metadatos propios del
objeto, tal cual están en el origen.

Antes de copiar comprueba que el origen y los dos destinos existen y se pueden
leer (head_bucket), y se niega a correr si alguno coincide con otro o con el
bucket de backups. Sin --apply no escribe nada (las comprobaciones y los head
de lectura sí se hacen, así el informe es exacto).

## Cómo decide qué es un GIF y qué es una imagen

Por la DB, no por la extensión (`.gif` es válido para una imagen del pool de
memes o del editor de embeds):

1. GIF: la key está en gif_objects.r2_key o la apunta alguna corpus_gifs.url.
2. Imagen: la apunta corpus_images.url, embed_uploaded_images.url,
   guild_bot_style (avatar/banner) o está dentro del JSON/texto de las
   plantillas de embeds, los anuncios y los embeds compartidos.
3. Referenciada por ambos lados (no debería pasar): se copia a los DOS buckets.
4. Sin referencia: el prefijo `gifs/` es exclusivo de los GIFs content-addressed
   (un GIF huérfano, va a GIFs); todo lo demás va a imágenes. --skip-unreferenced
   los omite en vez de copiarlos.

Hace falta la URL pública del bucket viejo para leer las URLs de la DB
(R2_PUBLIC_URL, o --source-public-url). La DB se abre siempre en solo lectura
salvo en `rewrite-db-urls --apply`.

## `rewrite-db-urls` (opcional, por separado)

La DB guarda las URLs completas, con el host del bucket viejo. Mientras R2_PUBLIC_URL
siga en el .env el bot las sigue reconociendo (alias transitorio, ver src/r2.py) y el
host viejo las sigue sirviendo, pero hay que reescribirlas antes de borrar el bucket
viejo o dejar de definir R2_PUBLIC_URL. Este paso cambia la DB, por eso es explícito:

- dry-run por defecto; con --apply primero deja una copia de la DB al lado
  (`purgito-pre-r2-rewrite-<fecha>.dump` en BACKUP_DIR, 0600) y escribe todo en una sola transacción;
- cambia solo el host: `<viejo>/gifs/...` y las URLs de corpus_gifs/gif_blocklist
  pasan al host de GIFs, el resto al de imágenes;
- una fila que chocaría con otra ya existente (UNIQUE) se deja como está y se
  informa; es idempotente;
- parar el bot antes de --apply (`sudo systemctl stop bot-purg`).

## Salida

Código 0 si no hubo errores ni diferencias, 1 si los hubo, 2 si la configuración
no alcanza para correr. --report archivo.jsonl deja una línea por decisión.
"""

import argparse
import itertools
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import asyncpg  # noqa: E402
import config  # noqa: F401,E402  -- carga .env / limits.env al importarse
import pgsync  # noqa: E402
import r2  # noqa: E402

log = logging.getLogger("migrate_r2_buckets")

GIFS = "gifs"
IMAGES = "images"

# Metadata que se copia tal cual del objeto de origen.
_PRESERVED_HEAD_FIELDS = (
    "ContentType",
    "CacheControl",
    "ContentDisposition",
    "ContentEncoding",
    "ContentLanguage",
)

# Columnas de la DB que pueden llevar URLs del bucket viejo.
_GIF_URL_COLUMNS = (
    ("corpus_gifs", "url"),
    ("corpus_gifs", "media_url"),
    ("gif_blocklist", "url"),
)
_IMAGE_URL_COLUMNS = (
    ("corpus_images", "url"),
    ("embed_uploaded_images", "url"),
    ("guild_bot_style", "avatar_url"),
    ("guild_bot_style", "banner_url"),
)
# Texto libre con URLs adentro (JSON de embeds, mensajes de anuncios...).
_TEXT_COLUMNS = (
    ("embed_templates", "embed_json"),
    ("embed_templates", "message"),
    ("scheduled_announcements", "embed_json"),
    ("scheduled_announcements", "message"),
    ("shared_embeds", "payload"),
    ("server_events", "embed_json"),
    ("server_events", "message"),
    ("layout_button_actions", "action_data"),
)


class ConfigError(Exception):
    """La configuración no alcanza para correr (código de salida 2)."""


# ─── Lectura de la DB ─────────────────────────────────────────────────────────


def _select(conn, sql: str, params: tuple = ()) -> list[tuple]:
    """Filas de `sql`, o [] si la tabla/columna no existe (una DB más vieja que
    el esquema actual no tiene por qué tener todas). Los nombres de tabla y
    columna son constantes de este archivo; todo lo demás va por parámetros."""
    try:
        with conn.savepoint():
            return conn.execute(sql, params).fetchall()
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return []


def _key_under(url, base: str) -> str | None:
    prefix = base + "/"
    if isinstance(url, str) and url.startswith(prefix) and len(url) > len(prefix):
        return url[len(prefix) :]
    return None


def _keys_in_text(text, base: str) -> set[str]:
    """Keys de las URLs `<base>/<key>` que aparecen dentro de un texto libre."""
    if not isinstance(text, str) or base not in text:
        return set()
    pattern = re.escape(base) + r"/([^\s\"'<>()\\]+)"
    return set(re.findall(pattern, text))


def load_references(conn, source_base: str) -> tuple[set[str], set[str]]:
    """(keys de GIFs, keys de imágenes) referenciadas por la DB."""
    gif_keys: set[str] = set()
    image_keys: set[str] = set()

    for (key,) in _select(conn, "SELECT r2_key FROM gif_objects"):
        if key:
            gif_keys.add(key)
    for table, column in _GIF_URL_COLUMNS:
        for (url,) in _select(conn, f"SELECT {column} FROM {table}"):
            key = _key_under(url, source_base)
            if key:
                gif_keys.add(key)
    for table, column in _IMAGE_URL_COLUMNS:
        for (url,) in _select(conn, f"SELECT {column} FROM {table}"):
            key = _key_under(url, source_base)
            if key:
                image_keys.add(key)
    for table, column in _TEXT_COLUMNS:
        for (text,) in _select(conn, f"SELECT {column} FROM {table}"):
            image_keys |= _keys_in_text(text, source_base)
    return gif_keys, image_keys


def classify(
    key: str, gif_keys: set[str], image_keys: set[str]
) -> tuple[tuple[str, ...], str]:
    """(destinos, motivo) de una key del bucket viejo. Ver el docstring del
    módulo: manda la DB; el prefijo `gifs/` solo desempata lo no referenciado,
    y la extensión no cuenta nunca."""
    in_gifs, in_images = key in gif_keys, key in image_keys
    if in_gifs and in_images:
        return (GIFS, IMAGES), "ambos"
    if in_gifs:
        return (GIFS,), "db-gif"
    if in_images:
        return (IMAGES,), "db-imagen"
    if key.startswith(r2.GIF_KEY_PREFIX):
        return (GIFS,), "prefijo-gifs"
    return (IMAGES,), "sin-referencia"


# ─── Copia ────────────────────────────────────────────────────────────────────


def _is_not_found(exc: Exception) -> bool:
    resp = getattr(exc, "response", None) or {}
    code = str(resp.get("Error", {}).get("Code", ""))
    status = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ("404", "NoSuchKey", "NotFound", "NoSuchBucket") or status == 404


def _head(client, bucket: str, key: str) -> dict | None:
    """head_object, o None si el objeto no existe. Cualquier otro error se
    propaga: un permiso faltante no se puede confundir con "no está"."""
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception as e:
        if _is_not_found(e):
            return None
        raise


def _simple_etag(head: dict) -> str | None:
    etag = str(head.get("ETag", "")).strip('"')
    return etag if etag and "-" not in etag else None


def _same_object(src: dict, dst: dict) -> bool:
    if src.get("ContentLength") != dst.get("ContentLength"):
        return False
    a, b = _simple_etag(src), _simple_etag(dst)
    return a is None or b is None or a == b


def _copy_args(src_head: dict) -> dict:
    args = {f: src_head[f] for f in _PRESERVED_HEAD_FIELDS if src_head.get(f)}
    args["Metadata"] = dict(src_head.get("Metadata") or {})
    return args


def copy_object(client, source_bucket: str, dest_bucket: str, key: str, apply: bool):
    """Copia una key al destino. Devuelve la acción: "copiado", "ya-estaba",
    "se-copiaría" (dry-run) o "distinto" (existe con otro contenido: no se
    pisa). Levanta ante un error real (permisos, red)."""
    src_head = _head(client, source_bucket, key)
    if src_head is None:
        raise FileNotFoundError(f"{key} ya no está en el bucket de origen")
    dst_head = _head(client, dest_bucket, key)
    if dst_head is not None:
        return "ya-estaba" if _same_object(src_head, dst_head) else "distinto"
    if not apply:
        return "se-copiaría"
    client.copy_object(
        Bucket=dest_bucket,
        Key=key,
        CopySource={"Bucket": source_bucket, "Key": key},
        # REPLACE con lo leído del origen: metadata explícita en vez de confiar
        # en lo que cada implementación S3 haga por defecto con COPY.
        MetadataDirective="REPLACE",
        **_copy_args(src_head),
    )
    copied = _head(client, dest_bucket, key)
    if copied is None or copied.get("ContentLength") != src_head.get("ContentLength"):
        raise RuntimeError(f"{key}: el objeto copiado no coincide con el origen")
    return "copiado"


def iter_keys(client, bucket: str):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"]


def check_buckets(client, buckets: dict[str, str]) -> None:
    """Todos los buckets tienen que existir y poder leerse, o no se hace nada."""
    for role, name in buckets.items():
        try:
            client.head_bucket(Bucket=name)
        except Exception as e:
            raise ConfigError(
                f"el bucket de {role} '{name}' no existe o el token no tiene "
                f"acceso ({e}). Créalo y dale al token Object Read & Write sobre él."
            ) from e


def migrate(
    client,
    source_bucket: str,
    dest: dict[str, str],
    gif_keys: set[str],
    image_keys: set[str],
    *,
    apply: bool,
    limit: int = 0,
    sleep: float = 0.0,
    skip_unreferenced: bool = False,
    report=None,
    progress_every: int = 200,
) -> Counter:
    """Copia el bucket viejo a `dest` ({"gifs": bucket, "images": bucket}).
    Devuelve contadores por acción y motivo."""
    stats: Counter = Counter()
    seen = 0
    for key, size in iter_keys(client, source_bucket):
        if limit and seen >= limit:
            break
        seen += 1
        targets, reason = classify(key, gif_keys, image_keys)
        if reason == "sin-referencia" and skip_unreferenced:
            stats["omitido-sin-referencia"] += 1
            continue
        stats[f"motivo:{reason}"] += 1
        for role in targets:
            try:
                action = copy_object(client, source_bucket, dest[role], key, apply)
            except Exception as e:
                action = "error"
                log.error("ERROR %s -> %s: %s", key, dest[role], e)
            stats[action] += 1
            if action in ("copiado", "se-copiaría"):
                stats[f"bytes:{role}"] += size
            if action == "distinto":
                log.warning(
                    "DISTINTO %s existe en %s con otro contenido: no se pisa",
                    key,
                    dest[role],
                )
            if report is not None:
                report.write(
                    json.dumps(
                        {
                            "key": key,
                            "destino": dest[role],
                            "rol": role,
                            "motivo": reason,
                            "accion": action,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            if sleep and action == "copiado":
                time.sleep(sleep)
        if progress_every and seen % progress_every == 0:
            log.info(
                "%d objetos vistos (%d copiados, %d ya estaban, %d errores)",
                seen,
                stats["copiado"],
                stats["ya-estaba"],
                stats["error"],
            )
    stats["vistos"] = seen
    return stats


# ─── Verificación ─────────────────────────────────────────────────────────────


def verify(
    client,
    source_bucket: str,
    dest: dict[str, str],
    gif_keys: set[str],
    image_keys: set[str],
    *,
    skip_unreferenced: bool = False,
    limit: int = 0,
) -> Counter:
    """Comprueba que cada objeto del origen está en su(s) destino(s) con el
    mismo tamaño. Solo lee."""
    stats: Counter = Counter()
    present: set[str] = set()
    for key, size in iter_keys(client, source_bucket):
        if limit and stats["vistos"] >= limit:
            break
        stats["vistos"] += 1
        present.add(key)
        targets, reason = classify(key, gif_keys, image_keys)
        if reason == "sin-referencia" and skip_unreferenced:
            continue
        for role in targets:
            try:
                head = _head(client, dest[role], key)
            except Exception as e:
                stats["error"] += 1
                log.error("ERROR al leer %s en %s: %s", key, dest[role], e)
                continue
            if head is None:
                stats["faltan"] += 1
                log.error("FALTA %s en %s", key, dest[role])
            elif head.get("ContentLength") != size:
                stats["tamaño-distinto"] += 1
                log.error(
                    "DISTINTO %s en %s (%s bytes vs %s)",
                    key,
                    dest[role],
                    head.get("ContentLength"),
                    size,
                )
            else:
                stats["ok"] += 1
    if not limit:
        # Filas de la DB que apuntan a un objeto que el bucket viejo ya no tiene:
        # no es culpa de la migración, pero conviene saberlo.
        stats["colgadas-en-db"] = len((gif_keys | image_keys) - present)
    return stats


def count_old_urls(conn, source_base: str) -> dict[str, int]:
    """Filas de la DB que todavía llevan el host del bucket viejo, por
    tabla.columna. Todo en 0 == se puede dejar de definir R2_PUBLIC_URL."""
    out = {}
    cols = _GIF_URL_COLUMNS + _IMAGE_URL_COLUMNS + _TEXT_COLUMNS
    for table, column in cols:
        rows = _select(conn, f"SELECT {column} FROM {table}")
        out[f"{table}.{column}"] = sum(
            1 for (v,) in rows if isinstance(v, str) and (source_base + "/") in v
        )
    return out


# ─── Reescritura de URLs en la DB ─────────────────────────────────────────────


def _rewrite_text(text: str, source_base: str, images_base: str, gifs_base: str) -> str:
    """Cambia el host viejo dentro de un texto en una sola pasada: `gifs/...`
    al host de GIFs y todo lo demás al de imágenes."""
    pattern = re.compile(re.escape(source_base) + r"/(gifs/)?")
    return pattern.sub(
        lambda m: f"{gifs_base}/gifs/" if m.group(1) else f"{images_base}/", text
    )


def rewrite_urls(
    conn,
    source_base: str,
    images_base: str,
    gifs_base: str,
    *,
    apply: bool,
    exists=None,
) -> Counter:
    """Reescribe el host de las URLs guardadas. No hace commit: lo hace el
    llamador, para que sea una sola transacción.

    `exists(destino, key) -> bool` (destino: GIFS o IMAGES) dice si el objeto ya
    está en el bucket nuevo. Una URL cuyo objeto NO está en el destino no se
    reescribe (quedaría apuntando a la nada): se cuenta como ":destino-faltante"
    y se deja como estaba. Sin `exists` se asume que todo está (solo tests)."""
    stats: Counter = Counter()

    def present(dest: str, key: str) -> bool:
        return True if exists is None else bool(exists(dest, key))

    def plain(table: str, column: str, new_base: str) -> None:
        rows = _select(
            conn,
            f"SELECT ctid::text, {column} FROM {table} WHERE substr({column}, 1, ?) = ?",
            (len(source_base) + 1, source_base + "/"),
        )
        for rowid, url in rows:
            new_url = new_base + url[len(source_base) :]
            label = f"{table}.{column}"
            if new_base == images_base and url[len(source_base) + 1 :].startswith(
                r2.GIF_KEY_PREFIX
            ):
                # Una key de GIF guardada como imagen: no hay a dónde mandarla sin adivinar.
                stats[f"{label}:ambigua"] += 1
                log.warning("AMBIGUA %s rowid=%s: %s", label, rowid, url)
                continue
            stats[f"{label}:coincide"] += 1
            dest = GIFS if new_base == gifs_base else IMAGES
            if not present(dest, url[len(source_base) + 1 :]):
                stats[f"{label}:destino-faltante"] += 1
                log.warning("DESTINO FALTANTE %s rowid=%s: %s", label, rowid, url)
                continue
            if not apply:
                continue
            try:
                with conn.savepoint():
                    conn.execute(
                        f"UPDATE {table} SET {column}=? WHERE ctid=(?::text)::tid",
                        (new_url, rowid),
                    )
                stats[f"{label}:reescrita"] += 1
            except asyncpg.UniqueViolationError:
                # Ya hay una fila con la URL nueva (UNIQUE): no se pisa ni se borra.
                stats[f"{label}:choque"] += 1
                log.warning("CHOQUE %s rowid=%s: %s ya existe", label, rowid, new_url)

    for table, column in _GIF_URL_COLUMNS:
        plain(table, column, gifs_base)
    for table, column in _IMAGE_URL_COLUMNS:
        plain(table, column, images_base)

    for table, column in _TEXT_COLUMNS:
        rows = _select(
            conn,
            f"SELECT ctid::text, {column} FROM {table} WHERE position(? in {column}) > 0",
            (source_base + "/",),
        )
        for rowid, text in rows:
            label = f"{table}.{column}"
            stats[f"{label}:coincide"] += 1
            faltan = [
                k
                for k in _keys_in_text(text, source_base)
                if not present(GIFS if k.startswith(r2.GIF_KEY_PREFIX) else IMAGES, k)
            ]
            if faltan:
                # Una fila de texto se reescribe entera o no se toca.
                stats[f"{label}:destino-faltante"] += 1
                log.warning("DESTINO FALTANTE %s rowid=%s: %s", label, rowid, faltan)
                continue
            if apply:
                new_text = _rewrite_text(text, source_base, images_base, gifs_base)
                conn.execute(
                    f"UPDATE {table} SET {column}=? WHERE ctid=(?::text)::tid",
                    (new_text, rowid),
                )
                stats[f"{label}:reescrita"] += 1
    return stats


def backup_db_file(dsn: str) -> str:
    """pg_dump de la base junto a los backups, antes de tocarla (0600)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.environ.get(
        "BACKUP_DIR", os.path.join(os.path.expanduser("~"), "purgito-bot-backups")
    )
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    # O_EXCL (dentro de pgsync.dump): una copia anterior no se pisa nunca; si el
    # nombre ya existe (dos corridas en el mismo segundo) se le suma un número.
    for n in itertools.count():
        dest = os.path.join(
            backup_dir,
            f"purgito-pre-r2-rewrite-{stamp}" + (f"-{n}" if n else "") + ".dump",
        )
        if not os.path.exists(dest):
            return pgsync.dump(dsn, dest)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _resolve_settings(args) -> dict:
    """Origen y destinos, con sus nombres resueltos y validados."""
    client = r2.get_client()
    if client is None:
        raise ConfigError(
            "R2 no está configurado (faltan R2_ENDPOINT_URL, R2_ACCESS_KEY_ID o R2_SECRET_ACCESS_KEY)"
        )
    # legacy=False: acá origen y destino son cosas distintas, y el fallback al
    # bucket viejo haría que un destino sin configurar apuntara al origen.
    source_bucket = args.source_bucket or os.getenv(r2.LEGACY_BUCKET_VAR, "").strip()
    source_base = (
        (args.source_public_url or os.getenv(r2.LEGACY_PUBLIC_VAR, ""))
        .strip()
        .rstrip("/")
    )
    dest = {
        GIFS: args.gifs_bucket or r2.bucket_for(r2.GIFS, legacy=False),
        IMAGES: args.images_bucket or r2.bucket_for(r2.IMAGES, legacy=False),
    }
    if not source_bucket:
        raise ConfigError("falta el bucket de origen: R2_BUCKET_NAME o --source-bucket")
    if not source_base:
        raise ConfigError(
            "falta la URL pública del bucket viejo (R2_PUBLIC_URL o --source-public-url): "
            "sin ella no se pueden leer las URLs de la DB para clasificar"
        )
    for role, name in dest.items():
        if not name:
            var = r2.GIFS.bucket_var if role == GIFS else r2.IMAGES.bucket_var
            raise ConfigError(f"falta el bucket de {role}: {var} o --{role}-bucket")
    names = [source_bucket, *dest.values()]
    if len(set(names)) != len(names):
        raise ConfigError(
            f"origen y destinos tienen que ser tres buckets distintos: {names}"
        )
    backups = r2.bucket_for(r2.BACKUPS)
    if backups and backups in names:
        raise ConfigError(
            f"el bucket de backups '{backups}' no puede ser origen ni destino de esta migración"
        )
    return {
        "client": client,
        "source": source_bucket,
        "source_base": source_base,
        "dest": dest,
    }


def _open_db(dsn: str | None, writable: bool = False):
    # Solo lectura de verdad: aunque este código tuviera un bug, no podría escribir.
    return pgsync.connect(dsn, read_only=not writable)


def _log_stats(title: str, stats: Counter) -> None:
    log.info("=== %s ===", title)
    for name in sorted(stats):
        log.info("  %-28s %s", name, stats[name])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument(
            "--dsn", default=None, help="URL de PostgreSQL (default: DATABASE_URL)"
        )
        p.add_argument("--source-bucket", help="bucket viejo (default: R2_BUCKET_NAME)")
        p.add_argument(
            "--source-public-url",
            help="URL pública del bucket viejo (default: R2_PUBLIC_URL)",
        )
        p.add_argument("--gifs-bucket", help="default: R2_GIFS_BUCKET")
        p.add_argument("--images-bucket", help="default: R2_IMAGES_BUCKET")

    cp = sub.add_parser("copy", help="copia los objetos a los buckets nuevos")
    common(cp)
    cp.add_argument(
        "--apply", action="store_true", help="copiar de verdad (default: dry-run)"
    )
    cp.add_argument(
        "--limit", type=int, default=0, help="como mucho N objetos (prueba)"
    )
    cp.add_argument("--sleep", type=float, default=0.0, help="segundos entre copias")
    cp.add_argument(
        "--skip-unreferenced",
        action="store_true",
        help="no copiar lo que la DB no referencia",
    )
    cp.add_argument("--report", help="archivo .jsonl con una línea por decisión")

    vf = sub.add_parser("verify", help="comprueba que los destinos tienen todo")
    common(vf)
    vf.add_argument("--limit", type=int, default=0)
    vf.add_argument("--skip-unreferenced", action="store_true")

    rw = sub.add_parser(
        "rewrite-db-urls", help="reescribe en la DB el host viejo (opcional)"
    )
    common(rw)
    rw.add_argument("--images-public-url", help="default: R2_IMAGES_PUBLIC_URL")
    rw.add_argument("--gifs-public-url", help="default: R2_GIFS_PUBLIC_URL")
    rw.add_argument(
        "--apply", action="store_true", help="escribir de verdad (default: dry-run)"
    )

    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    try:
        if args.command == "rewrite-db-urls":
            return _main_rewrite(args)
        s = _resolve_settings(args)
        check_buckets(
            s["client"], {"origen": s["source"], **{k: v for k, v in s["dest"].items()}}
        )
        conn = _open_db(args.dsn)
        try:
            gif_keys, image_keys = load_references(conn, s["source_base"])
        finally:
            conn.close()
        log.info(
            "DB: %d keys de GIFs y %d de imágenes referenciadas (host %s)",
            len(gif_keys),
            len(image_keys),
            s["source_base"],
        )
        if args.command == "copy":
            if not args.apply:
                log.info(
                    "=== DRY-RUN: no se copia nada. Usar --apply para ejecutar. ==="
                )
            report = open(args.report, "w", encoding="utf-8") if args.report else None
            try:
                stats = migrate(
                    s["client"],
                    s["source"],
                    s["dest"],
                    gif_keys,
                    image_keys,
                    apply=args.apply,
                    limit=args.limit,
                    sleep=args.sleep,
                    skip_unreferenced=args.skip_unreferenced,
                    report=report,
                )
            finally:
                if report:
                    report.close()
            _log_stats("copy" if args.apply else "copy (dry-run)", stats)
            return 1 if stats["error"] or stats["distinto"] else 0
        stats = verify(
            s["client"],
            s["source"],
            s["dest"],
            gif_keys,
            image_keys,
            skip_unreferenced=args.skip_unreferenced,
            limit=args.limit,
        )
        _log_stats("verify", stats)
        conn = _open_db(args.dsn)
        try:
            old = count_old_urls(conn, s["source_base"])
        finally:
            conn.close()
        for name, n in old.items():
            if n:
                log.info("  filas con el host viejo en %s: %d", name, n)
        if not any(old.values()):
            log.info("  la DB ya no referencia el host viejo")
        bad = stats["faltan"] + stats["tamaño-distinto"] + stats["error"]
        log.info("VERIFICACIÓN %s", "FALLÓ" if bad else "OK")
        return 1 if bad else 0
    except ConfigError as e:
        log.error("%s", e)
        return 2


def _dest_exists_checker(args):
    """exists(destino, key) contra los buckets NUEVOS (head_object, con caché).
    Obligatorio: rewrite-db-urls no apunta URLs a objetos que no están."""
    client = r2.get_client()
    if client is None:
        raise ConfigError("R2 no está configurado: no se puede comprobar el destino")
    buckets = {
        GIFS: args.gifs_bucket or r2.bucket_for(r2.GIFS, legacy=False),
        IMAGES: args.images_bucket or r2.bucket_for(r2.IMAGES, legacy=False),
    }
    for role, name in buckets.items():
        if not name:
            raise ConfigError(f"falta el bucket de {role} para comprobar el destino")
    cache: dict[tuple[str, str], bool] = {}

    def exists(dest: str, key: str) -> bool:
        k = (dest, key)
        if k not in cache:
            cache[k] = _head(client, buckets[dest], key) is not None
        return cache[k]

    return exists


def _main_rewrite(args) -> int:
    source_base = (
        (args.source_public_url or os.getenv(r2.LEGACY_PUBLIC_VAR, ""))
        .strip()
        .rstrip("/")
    )
    images_base = (
        args.images_public_url or r2.public_base(r2.IMAGES, legacy=False)
    ).rstrip("/")
    gifs_base = (args.gifs_public_url or r2.public_base(r2.GIFS, legacy=False)).rstrip(
        "/"
    )
    if not (source_base and images_base and gifs_base):
        raise ConfigError(
            "hacen falta las tres URLs públicas: R2_PUBLIC_URL (o --source-public-url), "
            "R2_IMAGES_PUBLIC_URL y R2_GIFS_PUBLIC_URL"
        )
    if source_base in (images_base, gifs_base):
        raise ConfigError(
            "la URL vieja coincide con una nueva: no hay nada que reescribir"
        )
    exists = _dest_exists_checker(args)
    if not args.apply:
        log.info("=== DRY-RUN: no se escribe nada. Usar --apply para ejecutar. ===")
    conn = _open_db(args.dsn, writable=args.apply)
    try:
        if args.apply:
            # Sin nada que reescribir no se toca la DB ni se deja una copia más.
            pending = rewrite_urls(
                conn, source_base, images_base, gifs_base, apply=False, exists=exists
            )
            if not any(k.endswith(":coincide") for k in pending):
                log.info(
                    "La DB no tiene URLs del host viejo: no hay nada que reescribir."
                )
                return 0
            backup = backup_db_file(args.dsn or os.environ["DATABASE_URL"])
            log.info("Copia de la DB antes de reescribir: %s", backup)
        stats = rewrite_urls(
            conn, source_base, images_base, gifs_base, apply=args.apply, exists=exists
        )
        if args.apply:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _log_stats("rewrite-db-urls" if args.apply else "rewrite-db-urls (dry-run)", stats)
    return (
        1
        if any(k.endswith((":choque", ":ambigua", ":destino-faltante")) for k in stats)
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
