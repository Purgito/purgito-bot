"""Backfill de phash perceptual (dHash) y fusión de GIFs casi-duplicados.

Complementa a reconcile_gif_objects.py: ese script deduplica por content_hash
exacto (mismos bytes). Este detecta el mismo meme reposteado con distinta
compresión/recorte/origen -- bytes distintos, content_hash distinto, pero
visualmente el mismo archivo -- comparando el dHash de cada objeto.

Herramienta de mantenimiento manual, no la corre el bot. El backfill de
phashes faltantes (fase 1) se escribe SIEMPRE, tenga o no --apply: es
puramente aditivo (llena una columna vacía), no borra ni fusiona nada. La
fusión de clusters (fase 4) sí respeta --apply, igual que reconcile_gif_objects.py.

    python scripts/backfill_gif_phashes.py            # backfill + reporte, sin fusionar
    python scripts/backfill_gif_phashes.py --apply     # además fusiona los clusters

Conviene parar el bot mientras corre (`sudo systemctl stop bot-purg`): una
subida en paralelo puede quedar apuntando a un content_hash que este script
está por fusionar en otro.

## Umbral

GIF_PHASH_MAX_DISTANCE (limits.env) es la distancia de Hamming máxima entre
dos phash para considerarlos el mismo meme. Correr primero SIN --apply y
revisar a ojo el reporte de clusters -- un umbral mal calibrado fusiona
memes que en realidad son distintos. Recién después de confiar en el
reporte conviene correr con --apply.

## Cómo se agrupan los clusters

Union-find sobre pares con distancia <= GIF_PHASH_MAX_DISTANCE. Es
transitivo (si A~B y B~C, A/B/C quedan en el mismo cluster aunque A~C supere
el umbral), a propósito: es lo que reporta el script como "distancia máxima
dentro del cluster", para poder detectar ese caso a ojo antes de fusionar.
A la escala de un bucket de GIFs (miles de objetos) la comparación por
fuerza bruta O(n^2) no necesita ninguna estructura de indexado.

## Fusión (--apply)

Por cada cluster de 2+ objetos: el canónico es el que más filas de
corpus_gifs referencia en total (así se reescriben menos filas); empate ->
el más viejo. Los demás objetos del cluster reescriben sus filas de
corpus_gifs hacia el canónico (UPDATE OR IGNORE; lo que choca contra el
UNIQUE(guild_id, url) porque ese guild ya tenía el canónico se borra en vez
de reescribirse -- mismo motivo que en reconcile_gif_objects.py), se borran
de R2 y de gif_objects, y al final se recalcula ref_count de gif_objects
contando corpus_gifs por content_hash.

## Correrlo más de una vez

Es idempotente: en la segunda corrida los objetos ya tienen phash (fase 1 no
hace nada) y cada cluster fusionado quedó como un único objeto (fase 2 no
encuentra grupos de 2+ para ese contenido).
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import config  # noqa: F401,E402  -- carga .env / limits.env al importarse
import imagehash  # noqa: E402
import r2  # noqa: E402

log = logging.getLogger("backfill_phashes")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db"
)


def _max_distance() -> int:
    """Mismo patrón que r2._env_int / db._env_int: cada módulo se lee su
    propia copia de las env vars, no hay un lugar compartido para esto."""
    try:
        v = int(os.getenv("GIF_PHASH_MAX_DISTANCE", "") or 6)
        return v if v > 0 else 6
    except (ValueError, TypeError):
        return 6


# ---------- fase 1: backfill de phashes faltantes ---------------------------


def backfill_missing_phashes(client, bucket, conn, sleep=0.1) -> tuple[int, int]:
    """Baja y hashea los objetos con phash NULL. Se escribe siempre, tenga o
    no --apply el resto del script (ver docstring del módulo). Devuelve
    (calculados, fallidos)."""
    rows = conn.execute(
        "SELECT content_hash, r2_key FROM gif_objects WHERE phash IS NULL"
    ).fetchall()
    done = failed = 0
    for content_hash, r2_key in rows:
        try:
            data = client.get_object(Bucket=bucket, Key=r2_key)["Body"].read()
        except Exception:
            log.warning("No se pudo bajar %s: se deja sin phash", r2_key, exc_info=True)
            failed += 1
            continue
        time.sleep(sleep)
        phash = r2.compute_phash(data)
        if phash is None:
            log.warning("No se pudo calcular el phash de %s: se deja sin phash", r2_key)
            failed += 1
            continue
        conn.execute(
            "UPDATE gif_objects SET phash=? WHERE content_hash=?",
            (phash, content_hash),
        )
        done += 1
    conn.commit()
    log.info(
        "Backfill de phash: %d calculados, %d sin poder calcular (se dejan para la próxima corrida)",
        done,
        failed,
    )
    return done, failed


# ---------- fase 2: clustering por distancia de Hamming ---------------------


class _UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def cluster_by_phash(
    objects: list[tuple[str, str, str | None]], max_distance: int
) -> list[list[str]]:
    """objects: (content_hash, r2_key, phash) de todo gif_objects. Devuelve
    los grupos (listas de content_hash) con 2 o más objetos; los que no
    tienen phash no participan."""
    with_hash = [(h, phash) for h, _key, phash in objects if phash]
    hashes = {h: imagehash.hex_to_hash(phash) for h, phash in with_hash}
    uf = _UnionFind([h for h, _ in with_hash])
    for i in range(len(with_hash)):
        h1 = with_hash[i][0]
        for j in range(i + 1, len(with_hash)):
            h2 = with_hash[j][0]
            if hashes[h1] - hashes[h2] <= max_distance:
                uf.union(h1, h2)

    groups: dict[str, list[str]] = defaultdict(list)
    for h, _ in with_hash:
        groups[uf.find(h)].append(h)
    return [g for g in groups.values() if len(g) > 1]


# ---------- fase 3: reporte --------------------------------------------------


def _references(conn, content_hashes: list[str]) -> dict[str, list[int]]:
    """content_hash -> guild_ids de corpus_gifs que lo referencian."""
    if not content_hashes:
        return {}
    placeholders = ",".join("?" * len(content_hashes))
    rows = conn.execute(
        f"SELECT content_hash, guild_id FROM corpus_gifs WHERE content_hash IN ({placeholders})",
        content_hashes,
    ).fetchall()
    out: dict[str, list[int]] = defaultdict(list)
    for content_hash, guild_id in rows:
        out[content_hash].append(guild_id)
    return out


def _max_distance_in_cluster(cluster, hashes) -> int:
    worst = 0
    for i in range(len(cluster)):
        for j in range(i + 1, len(cluster)):
            d = hashes[cluster[i]] - hashes[cluster[j]]
            if d > worst:
                worst = d
    return worst


def report_clusters(
    conn,
    clusters: list[list[str]],
    hashes: dict[str, imagehash.ImageHash],
    keys_by_hash: dict[str, str],
) -> None:
    for cluster in clusters:
        refs = _references(conn, cluster)
        worst = _max_distance_in_cluster(cluster, hashes)
        log.info("CLUSTER de %d objetos (distancia máxima %d):", len(cluster), worst)
        for content_hash in cluster:
            guilds = sorted(set(refs.get(content_hash, [])))
            log.info(
                "  %s (key=%s): %d filas de corpus_gifs, guilds=%s",
                content_hash,
                keys_by_hash.get(content_hash, "?"),
                len(refs.get(content_hash, [])),
                guilds,
            )


# ---------- fase 4: fusión (--apply) -----------------------------------------


def _public_prefix() -> str:
    return r2.public_url().rstrip("/")


def _url_for(key: str) -> str:
    return f"{_public_prefix()}/{key}"


def apply_merges(
    client,
    bucket: str,
    conn,
    clusters: list[list[str]],
    objects_by_hash: dict[str, tuple[str, str | None]],
) -> dict:
    """objects_by_hash: content_hash -> (r2_key, created_at). Fusiona cada
    cluster de 2+ objetos hacia su canónico. Devuelve contadores."""
    merged_objects = rewritten_rows = deleted_rows = 0
    for cluster in clusters:
        rows_per_hash = {
            h: conn.execute(
                "SELECT COUNT(*) FROM corpus_gifs WHERE content_hash=?", (h,)
            ).fetchone()[0]
            for h in cluster
        }
        canonical = min(
            cluster,
            key=lambda h: (-rows_per_hash[h], objects_by_hash[h][1] or ""),
        )
        canonical_key = objects_by_hash[canonical][0]
        canonical_url = _url_for(canonical_key)

        for content_hash in cluster:
            if content_hash == canonical:
                continue
            old_key = objects_by_hash[content_hash][0]

            updated = conn.execute(
                "UPDATE OR IGNORE corpus_gifs SET url=?, content_hash=? "
                "WHERE content_hash=?",
                (canonical_url, canonical, content_hash),
            ).rowcount
            leftover = conn.execute(
                "DELETE FROM corpus_gifs WHERE content_hash=?", (content_hash,)
            ).rowcount
            rewritten_rows += updated
            deleted_rows += leftover
            log.info(
                "FUSIONAR %s -> %s (%d filas reescritas, %d filas duplicadas borradas)",
                content_hash,
                canonical,
                updated,
                leftover,
            )

            client.delete_object(Bucket=bucket, Key=old_key)
            conn.execute(
                "DELETE FROM gif_objects WHERE content_hash=?", (content_hash,)
            )
            merged_objects += 1

    # Reconstruir ref_count desde corpus_gifs (igual que el paso 4 de
    # reconcile_gif_objects.py, pero sin borrar las filas: acá gif_objects ya
    # quedó consistente arriba y esto solo recalcula el contador).
    conn.execute("UPDATE gif_objects SET ref_count=0")
    counts = conn.execute(
        "SELECT content_hash, COUNT(*) FROM corpus_gifs "
        "WHERE content_hash IS NOT NULL GROUP BY content_hash"
    ).fetchall()
    conn.executemany(
        "UPDATE gif_objects SET ref_count=? WHERE content_hash=?",
        [(n, h) for h, n in counts],
    )
    conn.commit()

    return {
        "merged_objects": merged_objects,
        "rewritten_rows": rewritten_rows,
        "deleted_rows": deleted_rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply",
        action="store_true",
        help="fusiona los clusters encontrados; sin esta bandera solo informa (default)",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.1,
        help="segundos de espera entre llamadas a R2 (default: 0.1)",
    )
    ap.add_argument("--db", default=DB_PATH, help=f"ruta de la DB (default: {DB_PATH})")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if not args.apply:
        log.info(
            "=== DRY-RUN: no se fusiona nada (el backfill de phashes SÍ se "
            "escribe siempre). Usar --apply para fusionar. ==="
        )

    client = r2.get_client()
    if client is None or not r2.public_url():
        log.error("R2 no está configurado (faltan R2_* en .env)")
        return 1
    bucket = os.getenv("R2_BUCKET_NAME", "").strip()

    conn = sqlite3.connect(args.db)
    try:
        backfill_missing_phashes(client, bucket, conn, sleep=args.sleep)

        objects = conn.execute(
            "SELECT content_hash, r2_key, phash FROM gif_objects"
        ).fetchall()
        created_by_hash = dict(
            conn.execute("SELECT content_hash, created_at FROM gif_objects").fetchall()
        )
        objects_by_hash = {
            h: (r2_key, created_by_hash.get(h)) for h, r2_key, _phash in objects
        }
        keys_by_hash = {h: r2_key for h, r2_key, _phash in objects}
        hashes = {
            h: imagehash.hex_to_hash(phash) for h, _key, phash in objects if phash
        }

        max_distance = _max_distance()
        clusters = cluster_by_phash(objects, max_distance)
        log.info(
            "%d clusters de casi-duplicados (distancia <= %d)",
            len(clusters),
            max_distance,
        )
        report_clusters(conn, clusters, hashes, keys_by_hash)

        if args.apply:
            summary = apply_merges(client, bucket, conn, clusters, objects_by_hash)
            log.info(
                "APLICADO: %d objetos fusionados, %d filas reescritas, "
                "%d filas duplicadas borradas",
                summary["merged_objects"],
                summary["rewritten_rows"],
                summary["deleted_rows"],
            )
        else:
            log.info("DRY-RUN: no se fusionó nada. Usar --apply para ejecutar.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
