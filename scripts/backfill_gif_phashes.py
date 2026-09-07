"""Backfill de fingerprint perceptual y fusión de GIFs casi-duplicados.

Complementa a reconcile_gif_objects.py: ese script deduplica por content_hash
exacto (mismos bytes). Este detecta el mismo meme reposteado con distinta
compresión/recorte/origen -- bytes distintos, content_hash distinto, pero
visualmente el mismo archivo -- comparando la huella estructural completa de
cada objeto (r2.GifFingerprint: cantidad de frames, dimensiones, duración
total y dHash de varios frames muestreados).

Herramienta de mantenimiento manual, no la corre el bot. El backfill de
fingerprints faltantes (fase 1) se escribe SIEMPRE, tenga o no --apply: es
puramente aditivo (llena columnas vacías), no borra ni fusiona nada. La
fusión de clusters (fase 4) sí respeta --apply, igual que reconcile_gif_objects.py.

    python scripts/backfill_gif_phashes.py            # backfill + reporte, sin fusionar
    python scripts/backfill_gif_phashes.py --apply     # además fusiona los clusters

Conviene parar el bot mientras corre (`sudo systemctl stop bot-purg`): una
subida en paralelo puede quedar apuntando a un content_hash que este script
está por fusionar en otro.

## Umbral y criterio de "mismo meme"

GIF_PHASH_MAX_DISTANCE (limits.env) es la distancia de Hamming máxima, por
frame muestreado, para considerar dos GIFs el mismo meme -- pero la
distancia sola no alcanza: dos objetos solo califican si además tienen la
misma cantidad de frames, el mismo aspect ratio y una duración total
parecida (ver r2.fingerprint_distance, compartido con el matching en
caliente de r2.py para que este script nunca pueda fusionar algo que la
subida normal habría rechazado). Aun así, correr primero SIN --apply y
revisar a ojo el reporte de clusters -- un umbral mal calibrado igual puede
fusionar memes distintos que casualmente comparten estructura. Recién
después de confiar en el reporte conviene correr con --apply.

## Cómo se agrupan los clusters

Union-find sobre pares que califican según r2.fingerprint_distance. Es
transitivo (si A~B y B~C, A/B/C quedan en el mismo cluster aunque A~C no
califique), a propósito: el reporte marca explícitamente los pares que
quedaron unidos solo por transitividad, para poder detectarlos a ojo antes
de fusionar. A la escala de un bucket de GIFs (miles de objetos) la
comparación por fuerza bruta O(n^2) no necesita ninguna estructura de
indexado.

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

Es idempotente: en la segunda corrida los objetos ya tienen fingerprint
(fase 1 no hace nada) y cada cluster fusionado quedó como un único objeto
(fase 2 no encuentra grupos de 2+ para ese contenido).
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import config  # noqa: F401,E402  -- carga .env / limits.env al importarse
import r2  # noqa: E402

log = logging.getLogger("backfill_phashes")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db"
)


def _max_distance() -> int:
    """Mismo patrón que r2._env_int / db._env_int: cada módulo se lee su
    propia copia de las env vars, no hay un lugar compartido para esto.
    Default alineado con r2._phash_max_distance."""
    try:
        v = int(os.getenv("GIF_PHASH_MAX_DISTANCE", "") or 4)
        return v if v > 0 else 4
    except (ValueError, TypeError):
        return 4


# ---------- fase 1: backfill de fingerprints faltantes ----------------------


def backfill_missing_fingerprints(client, bucket, conn, sleep=0.1) -> tuple[int, int]:
    """Baja y calcula el fingerprint de los objetos con phashes NULL. Se
    escribe siempre, tenga o no --apply el resto del script (ver docstring
    del módulo). Devuelve (calculados, fallidos)."""
    rows = conn.execute(
        "SELECT content_hash, r2_key FROM gif_objects WHERE phashes IS NULL"
    ).fetchall()
    done = failed = 0
    for content_hash, r2_key in rows:
        try:
            data = client.get_object(Bucket=bucket, Key=r2_key)["Body"].read()
        except Exception:
            log.warning(
                "No se pudo bajar %s: se deja sin fingerprint", r2_key, exc_info=True
            )
            failed += 1
            continue
        time.sleep(sleep)
        fp = r2.compute_gif_fingerprint(data)
        if fp is None:
            log.warning(
                "No se pudo calcular el fingerprint de %s: se deja para la próxima corrida",
                r2_key,
            )
            failed += 1
            continue
        conn.execute(
            "UPDATE gif_objects SET frame_count=?, width=?, height=?, "
            "duration_ms=?, phashes=? WHERE content_hash=?",
            (
                fp.frame_count,
                fp.width,
                fp.height,
                fp.duration_ms,
                json.dumps(list(fp.phashes)),
                content_hash,
            ),
        )
        done += 1
    conn.commit()
    log.info(
        "Backfill de fingerprint: %d calculados, %d sin poder calcular (se dejan para la próxima corrida)",
        done,
        failed,
    )
    return done, failed


def _fingerprint_from_row(
    frame_count, width, height, duration_ms, phashes_json
) -> "r2.GifFingerprint | None":
    if phashes_json is None:
        return None
    try:
        phashes = tuple(json.loads(phashes_json))
    except (TypeError, ValueError):
        return None
    return r2.GifFingerprint(frame_count, width, height, duration_ms, phashes)


# ---------- fase 2: clustering por fingerprint -------------------------------


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


def cluster_by_fingerprint(
    objects: list[tuple[str, str, "r2.GifFingerprint | None"]], max_distance: int
) -> list[list[str]]:
    """objects: (content_hash, r2_key, fingerprint) de todo gif_objects.
    Devuelve los grupos (listas de content_hash) con 2 o más objetos; los
    que no tienen fingerprint completo no participan.

    Usa r2.fingerprint_distance -- el mismo criterio AND estricto (misma
    cantidad de frames, aspect ratio y duración, más TODOS los dHash
    muestreados dentro de max_distance) que el matching en caliente de
    upload_gif_bytes_sync, para que este script nunca pueda fusionar algo
    que la subida normal habría rechazado.
    """
    with_fp = [(h, fp) for h, _key, fp in objects if fp is not None]
    uf = _UnionFind([h for h, _ in with_fp])
    for i in range(len(with_fp)):
        h1, fp1 = with_fp[i]
        for j in range(i + 1, len(with_fp)):
            h2, fp2 = with_fp[j]
            if r2.fingerprint_distance(fp1, fp2, max_distance) is not None:
                uf.union(h1, h2)

    groups: dict[str, list[str]] = defaultdict(list)
    for h, _ in with_fp:
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


def _cluster_pair_stats(cluster, fingerprints) -> tuple[int, int]:
    """(distancia máxima entre pares directamente compatibles, cantidad de
    pares que quedaron en el cluster solo por transitividad -- no
    calificaron entre sí, los unió un tercer objeto puente). Un cluster con
    pares incompatibles es justo el caso que el reporte tiene que hacer
    fácil de detectar a ojo antes de fusionar con --apply."""
    worst = 0
    incompatible_pairs = 0
    # 64: mayor que cualquier distancia de Hamming real entre dHash de 64
    # bits -- fuerza a que fingerprint_distance solo devuelva None por
    # incompatibilidad estructural (frame_count/aspect/duración), nunca por
    # el umbral configurado, que acá no es lo que se quiere medir.
    for i in range(len(cluster)):
        for j in range(i + 1, len(cluster)):
            d = r2.fingerprint_distance(
                fingerprints[cluster[i]], fingerprints[cluster[j]], max_distance=64
            )
            if d is None:
                incompatible_pairs += 1
            elif d > worst:
                worst = d
    return worst, incompatible_pairs


def report_clusters(
    conn,
    clusters: list[list[str]],
    fingerprints: dict[str, "r2.GifFingerprint"],
    keys_by_hash: dict[str, str],
) -> None:
    for cluster in clusters:
        refs = _references(conn, cluster)
        worst, incompatible_pairs = _cluster_pair_stats(cluster, fingerprints)
        log.info(
            "CLUSTER de %d objetos (distancia máxima entre pares compatibles: %d; "
            "%d pares unidos solo por transitividad -- revisar a ojo si es > 0):",
            len(cluster),
            worst,
            incompatible_pairs,
        )
        for content_hash in cluster:
            guilds = sorted(set(refs.get(content_hash, [])))
            fp = fingerprints[content_hash]
            log.info(
                "  %s (key=%s, %dx%d, %d frames, %dms): %d filas de corpus_gifs, guilds=%s",
                content_hash,
                keys_by_hash.get(content_hash, "?"),
                fp.width,
                fp.height,
                fp.frame_count,
                fp.duration_ms,
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
            "=== DRY-RUN: no se fusiona nada (el backfill de fingerprints SÍ se "
            "escribe siempre). Usar --apply para fusionar. ==="
        )

    client = r2.get_client()
    if client is None or not r2.public_url():
        log.error("R2 no está configurado (faltan R2_* en .env)")
        return 1
    bucket = os.getenv("R2_BUCKET_NAME", "").strip()

    conn = sqlite3.connect(args.db)
    try:
        backfill_missing_fingerprints(client, bucket, conn, sleep=args.sleep)

        objects = conn.execute(
            "SELECT content_hash, r2_key, frame_count, width, height, "
            "duration_ms, phashes FROM gif_objects"
        ).fetchall()
        created_by_hash = dict(
            conn.execute("SELECT content_hash, created_at FROM gif_objects").fetchall()
        )
        objects_by_hash = {
            row[0]: (row[1], created_by_hash.get(row[0])) for row in objects
        }
        keys_by_hash = {row[0]: row[1] for row in objects}
        fingerprints = {row[0]: _fingerprint_from_row(*row[2:]) for row in objects}

        max_distance = _max_distance()
        cluster_input = [(h, keys_by_hash[h], fp) for h, fp in fingerprints.items()]
        clusters = cluster_by_fingerprint(cluster_input, max_distance)
        log.info(
            "%d clusters de casi-duplicados (distancia <= %d por frame muestreado)",
            len(clusters),
            max_distance,
        )
        report_clusters(conn, clusters, fingerprints, keys_by_hash)

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
