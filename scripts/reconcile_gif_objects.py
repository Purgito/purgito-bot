"""Reconcilia el bucket de GIFs con el storage content-addressed de db.gif_objects.

Herramienta de mantenimiento manual, no la corre el bot. Dry-run por default:
sin --apply no escribe nada, ni en R2 ni en la DB.

    python scripts/reconcile_gif_objects.py            # solo informa
    python scripts/reconcile_gif_objects.py --apply    # ejecuta de verdad

Conviene parar el bot mientras corre (`sudo systemctl stop bot-purg`): reescribe
filas de corpus_gifs y mueve objetos, y una subida en paralelo puede quedar
apuntando a una key que el script está por borrar.

## Las tres generaciones de objetos que hay hoy en el bucket

1. Legacy, anteriores a la deduplicación: key `{guild_id}/{md5(url)}.gif`. Un
   objeto por servidor y por repost, sin content_hash en la fila.
2. Content-addressed sin optimizar (subidos entre la Fase 1 y la Fase 3): key
   `gifs/xx/{sha256}.gif`, pero el hash es de los bytes crudos, de antes de
   que la subida pasara por gifsicle.
3. Ya normalizados: key derivada del sha256 de los bytes **optimizados**, que
   es la regla que aplica r2.upload_gif_sync de ahora en adelante.

El script trata a las tres igual: normaliza cada objeto a la regla actual
(optimizar con la misma r2.optimize_gif_bytes que usa la subida, y hashear el
resultado) y, si la key que le corresponde no es la que tiene, lo re-sube a la
key correcta y borra la vieja. La clasificación sale sola de comparar keys:

    key == gif_key(sha256(optimize(bytes)))  ->  ya normalizado (gen 3)
    key == gif_key(sha256(bytes))            ->  content-addressed sin optimizar (gen 2)
    cualquier otra cosa                      ->  legacy por guild (gen 1)

Como la gen 2 y la gen 3 del mismo archivo convergen al mismo hash después de
pasar por gifsicle, se deduplican entre sí, que es justamente el objetivo.

## Qué NO toca

Solo se procesan objetos referenciados por alguna fila de corpus_gifs y por
ninguna de corpus_images. Es una precaución concreta, no teórica: las imágenes
del pool de memes y las subidas del editor de embeds viven en el MISMO bucket
con keys `{guild_id}/{md5}.ext`, y `.gif` es una extensión válida para ellas,
así que por forma de la key son indistinguibles de un GIF legacy. Los objetos
sin referencia se informan como huérfanos pero no se borran: eso es trabajo del
barrido periódico, que tiene el registro de gif_objects para decidir bien.

## Correrlo más de una vez

Es idempotente: en la segunda corrida todos los objetos ya están normalizados,
ningún grupo necesita re-subida y no hay nada que borrar. Se apoya en que
gifsicle sea determinista y en que optimize_gif_bytes devuelva los bytes
originales cuando el resultado no es más chico.
"""

import argparse
import hashlib
import logging
import os
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import config  # noqa: F401,E402  -- carga .env / limits.env al importarse
import r2  # noqa: E402

log = logging.getLogger("reconcile")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db"
)


def _public_prefix() -> str:
    return r2.public_url().rstrip("/")


def _url_for(key: str) -> str:
    return f"{_public_prefix()}/{key}"


def _key_of(url: str) -> str | None:
    """Key del objeto si la URL es de nuestro bucket, None si es externa
    (tenor/giphy, que no ocupan storage propio)."""
    pre = _public_prefix() + "/"
    return url[len(pre) :] if url.startswith(pre) else None


def iter_bucket_keys(client, bucket: str):
    """Lista el bucket paginado, cediendo solo metadata: el contenido se baja
    de a un objeto por vez y no se guarda."""
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"]


def load_references(conn) -> tuple[dict[str, list[int]], set[str]]:
    """(keys referenciadas por corpus_gifs -> ids de fila, keys de corpus_images)."""
    gif_keys: dict[str, list[int]] = defaultdict(list)
    for row_id, url in conn.execute("SELECT id, url FROM corpus_gifs"):
        key = _key_of(url)
        if key:
            gif_keys[key].append(row_id)

    image_keys = set()
    for (url,) in conn.execute("SELECT url FROM corpus_images"):
        key = _key_of(url)
        if key:
            image_keys.add(key)
    return gif_keys, image_keys


def classify(key: str, raw: bytes, optimized: bytes) -> str:
    """Generación del objeto, deducida de su propia key (ver docstring)."""
    if key == r2.gif_key(hashlib.sha256(optimized).hexdigest()):
        return "normalizado"
    if key == r2.gif_key(hashlib.sha256(raw).hexdigest()):
        return "sin-optimizar"
    return "legacy"


def _normalized_hash(client, bucket: str, key: str, sleep: float) -> tuple[str, bytes]:
    """Baja el objeto, lo optimiza y devuelve (hash, bytes optimizados)."""
    raw = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    time.sleep(sleep)
    optimized = r2.optimize_gif_bytes(raw)
    return hashlib.sha256(optimized).hexdigest(), optimized


def reconcile(client, bucket, conn, apply=False, sleep=0.1, limit=0) -> dict:
    """Devuelve un resumen con los contadores de lo hecho (o de lo que se haría)."""
    gif_keys, image_keys = load_references(conn)
    log.info(
        "corpus_gifs referencia %d objetos; corpus_images, %d",
        len(gif_keys),
        len(image_keys),
    )

    # --- 1. Recorrer el bucket y normalizar cada objeto referenciado ---------
    # Solo se acumula metadata: nada de bytes. Los grupos que necesiten una
    # re-subida vuelven a bajar su objeto fuente en la pasada 2.
    groups: dict[str, list[str]] = defaultdict(list)  # hash -> keys
    sizes: dict[str, int] = {}  # hash -> tamaño ya optimizado
    generations: dict[str, int] = defaultdict(int)
    orphans: list[tuple[str, int]] = []
    # Keys que el bucket sí tiene: es lo que separa una fila colgada de una
    # que simplemente cambió de key en esta misma corrida.
    present: set[str] = set()
    skipped_images = failed = seen = 0

    for key, size in iter_bucket_keys(client, bucket):
        if key in image_keys:
            skipped_images += 1
            continue
        if key not in gif_keys:
            orphans.append((key, size))
            continue
        if limit and seen >= limit:
            continue
        seen += 1

        try:
            raw = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception:
            log.warning("No se pudo bajar %s: se deja como está", key, exc_info=True)
            # Existe en el bucket aunque no se haya podido bajar: no es una
            # fila colgada, así que no hay que tocarle el content_hash.
            present.add(key)
            failed += 1
            continue
        time.sleep(sleep)
        present.add(key)

        optimized = r2.optimize_gif_bytes(raw)
        content_hash = hashlib.sha256(optimized).hexdigest()
        generations[classify(key, raw, optimized)] += 1
        groups[content_hash].append(key)
        sizes[content_hash] = len(optimized)

    dupes = sum(len(k) - 1 for k in groups.values())
    reclaimed = sum(sizes[h] * (len(k) - 1) for h, k in groups.items())
    log.info(
        "Objetos: %d procesados (%s), %d de imágenes salteados, %d huérfanos, %d con error",
        seen,
        ", ".join(f"{k}={v}" for k, v in sorted(generations.items())) or "-",
        skipped_images,
        len(orphans),
        failed,
    )
    log.info(
        "%d objetos únicos, %d copias redundantes (~%.1f MB a recuperar)",
        len(groups),
        dupes,
        reclaimed / 1024 / 1024,
    )

    # --- 2. Consolidar cada grupo en su key canónica ------------------------
    moved = deleted = 0
    for content_hash, keys in groups.items():
        canonical = r2.gif_key(content_hash)
        canonical_url = _url_for(canonical)

        if canonical not in keys:
            # El objeto más viejo del grupo hace de fuente. Se vuelve a bajar
            # en vez de haber guardado los bytes en la pasada 1: son hasta
            # 8 MB por objeto y no entran en memoria todos juntos.
            source = keys[0]
            log.info("SUBIR %s (desde %s)", canonical, source)
            if apply:
                rehash, payload = _normalized_hash(client, bucket, source, sleep)
                if rehash != content_hash:
                    log.error(
                        "SALTEADO %s: el hash cambió entre pasadas (%s -> %s)",
                        source,
                        content_hash,
                        rehash,
                    )
                    continue
                client.put_object(
                    Bucket=bucket,
                    Key=canonical,
                    Body=payload,
                    ContentType="image/gif",
                    CacheControl="public, max-age=31536000, immutable",
                )
                time.sleep(sleep)
            moved += 1

        old_urls = [_url_for(k) for k in keys if k != canonical]
        if apply:
            # OR IGNORE por el UNIQUE(guild_id, url): si un guild tenía dos
            # copias del mismo archivo, la segunda choca contra la primera y
            # queda con su URL vieja, así que la borra el DELETE de abajo --
            # era un duplicado dentro del mismo servidor igual.
            conn.execute(
                "UPDATE OR IGNORE corpus_gifs SET url=?, content_hash=? "
                f"WHERE url IN ({','.join('?' * len(keys))})",
                [canonical_url, content_hash, *(_url_for(k) for k in keys)],
            )
            if old_urls:
                conn.execute(
                    f"DELETE FROM corpus_gifs WHERE url IN ({','.join('?' * len(old_urls))})",
                    old_urls,
                )

        for key in keys:
            if key == canonical:
                continue
            log.info("BORRAR %s (redundante, canónico: %s)", key, canonical)
            if apply:
                client.delete_object(Bucket=bucket, Key=key)
                time.sleep(sleep)
            deleted += 1

    # --- 3. Filas que apuntan a objetos que ya no están en el bucket --------
    # Con --limit la mayoría de las keys no se miraron, así que este cálculo
    # no significaría nada.
    dangling: list[int] = []
    if not limit:
        dangling = [
            row_id
            for key, ids in gif_keys.items()
            if key not in present and key not in image_keys
            for row_id in ids
        ]
        if dangling and apply:
            conn.executemany(
                "UPDATE corpus_gifs SET content_hash=NULL WHERE id=?",
                [(i,) for i in dangling],
            )
        log.info("%d filas apuntan a objetos que no están en el bucket", len(dangling))

    # --- 4. Reconstruir gif_objects desde corpus_gifs ------------------------
    rebuilt = 0
    if limit:
        log.info("--limit activo: no se reconstruye gif_objects (quedaría parcial)")
    elif apply:
        conn.execute("DELETE FROM gif_objects")
        rows = conn.execute(
            "SELECT content_hash, COUNT(*) FROM corpus_gifs "
            "WHERE content_hash IS NOT NULL GROUP BY content_hash"
        ).fetchall()
        conn.executemany(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes) "
            "VALUES (?, ?, ?, ?)",
            [(h, r2.gif_key(h), n, sizes.get(h, 0)) for h, n in rows],
        )
        conn.commit()
        rebuilt = len(rows)
        log.info("gif_objects reconstruida: %d objetos", rebuilt)

    for key, size in orphans[:50]:
        log.info("HUÉRFANO (no se toca) %s (%d bytes)", key, size)
    if len(orphans) > 50:
        log.info("... y %d huérfanos más", len(orphans) - 50)

    log.info(
        "%s: %d objetos re-subidos a su key canónica, %d borrados",
        "APLICADO" if apply else "DRY-RUN (nada de esto se hizo)",
        moved,
        deleted,
    )
    return {
        "seen": seen,
        "unique": len(groups),
        "moved": moved,
        "deleted": deleted,
        "orphans": len(orphans),
        "skipped_images": skipped_images,
        "failed": failed,
        "dangling": len(dangling),
        "rebuilt": rebuilt,
        "generations": dict(generations),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply",
        action="store_true",
        help="ejecuta los cambios; sin esta bandera solo informa (default)",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.1,
        help="segundos de espera entre llamadas a R2 (default: 0.1)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="procesar como mucho N objetos, para una corrida de prueba",
    )
    ap.add_argument("--db", default=DB_PATH, help=f"ruta de la DB (default: {DB_PATH})")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if not args.apply:
        log.info("=== DRY-RUN: no se escribe nada. Usar --apply para ejecutar. ===")

    client = r2.get_client()
    if client is None or not r2.public_url():
        log.error("R2 no está configurado (faltan R2_* en .env)")
        return 1

    conn = sqlite3.connect(args.db)
    try:
        reconcile(
            client,
            os.getenv("R2_BUCKET_NAME", "").strip(),
            conn,
            apply=args.apply,
            sleep=args.sleep,
            limit=args.limit,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
