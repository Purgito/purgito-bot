"""Auditoría de GIFs cuyo contenido está compartido entre servidores.

Contexto: hasta el fix de upload_gif_bytes_sync (ver r2.GifFingerprint), el
matching perceptual de GIFs comparaba un único dHash del primer frame contra
los de TODOS los servidores, con un umbral relativamente laxo. Un falso
positivo ahí hacía que un servidor terminara con una fila de corpus_gifs
apuntando al objeto físico que otro servidor había subido -- mismo guild_id
correcto en la fila, pero el contenido real detrás de esa URL era ajeno.

Esta auditoría NO puede diferenciar automáticamente esos casos de la
deduplicación exacta legítima: dos servidores subiendo, de buena fe, el
mismo archivo byte a byte (el mismo meme viral reposteado tal cual) es el
comportamiento normal y esperado de gif_objects (ver su comentario en
db.SCHEMA) -- ESO no hay que tocarlo. Por eso este script solo REPORTA por
default; --apply exige indicar a mano un content_hash y qué guild se queda
con él, nunca hace un barrido automático.

Señal más fuerte de sospecha (pero no concluyente): revisar los logs
históricos del bot (journalctl o los logs rotados) por la línea "GIF
casi-duplicado detectado" -- un content_hash que aparece ahí sí pasó por
matching perceptual (no por dedup exacto), lo que descarta que sea
coincidencia legítima. Sin esos logs, la única heurística disponible acá es
de antigüedad: la fila más vieja de corpus_gifs para ese content_hash es,
con más probabilidad, la del servidor que lo subió originalmente -- pero es
una pista para revisar a mano, no una prueba.

    python scripts/audit_cross_guild_gifs.py                                    # reporta, no toca nada
    python scripts/audit_cross_guild_gifs.py --content-hash HASH                 # detalle de un solo content_hash
    python scripts/audit_cross_guild_gifs.py --apply --content-hash HASH --keep-guild ID
                                                                                  # borra las filas de corpus_gifs
                                                                                  # de ese content_hash en TODOS
                                                                                  # los guilds salvo --keep-guild

--apply solo opera sobre un content_hash a la vez, elegido a mano después de
revisar el reporte -- nunca un barrido masivo. No hay forma de recuperar el
GIF que un servidor afectado quiso guardar originalmente (nunca llegó a
subirse a R2, y el link de Discord ya expiró): lo único que --apply puede
hacer es dejar de servirle a ese servidor el contenido ajeno. El servidor
vuelve a tener su propio GIF recién cuando alguien lo vuelva a postear.
"""

import argparse
import os
import sqlite3
import sys

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db"
)


def find_shared_content_hashes(conn) -> list[tuple[str, int]]:
    """(content_hash, cantidad de guilds distintos) para cada content_hash
    referenciado por 2+ guild_id en corpus_gifs, de mayor a menor."""
    rows = conn.execute(
        "SELECT content_hash, COUNT(DISTINCT guild_id) AS n_guilds "
        "FROM corpus_gifs WHERE content_hash IS NOT NULL "
        "GROUP BY content_hash HAVING n_guilds > 1 "
        "ORDER BY n_guilds DESC, content_hash"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def rows_for_content_hash(conn, content_hash: str) -> list[dict]:
    """(guild_id, url, created_at, id) de cada fila que referencia este
    content_hash, ordenadas por antigüedad -- la primera es la más probable
    de ser el servidor que lo subió originalmente."""
    rows = conn.execute(
        "SELECT guild_id, url, created_at, id FROM corpus_gifs "
        "WHERE content_hash=? ORDER BY created_at ASC, id ASC",
        (content_hash,),
    ).fetchall()
    return [
        {"guild_id": r[0], "url": r[1], "created_at": r[2], "id": r[3]} for r in rows
    ]


def print_report(conn, shared: list[tuple[str, int]]) -> None:
    if not shared:
        print("No hay ningún content_hash referenciado por más de un servidor.")
        return
    print(
        f"{len(shared)} content_hash compartidos entre 2+ servidores "
        "(esto incluye tanto dedup exacto legítimo como posible contaminación "
        "-- revisar caso por caso, ver docstring del módulo):\n"
    )
    for content_hash, n_guilds in shared:
        rows = rows_for_content_hash(conn, content_hash)
        print(f"content_hash={content_hash} ({n_guilds} servidores)")
        for row in rows:
            marca = " <- más antiguo, probable dueño original" if row is rows[0] else ""
            print(
                f"  guild={row['guild_id']} id={row['id']} "
                f"created_at={row['created_at']} url={row['url']}{marca}"
            )
        print()


def apply_keep_guild(conn, content_hash: str, keep_guild: int) -> dict:
    """Borra las filas de corpus_gifs de `content_hash` en todo guild que no
    sea `keep_guild`, y recalcula ref_count de gif_objects contando
    corpus_gifs por content_hash (mismo patrón que apply_merges en
    backfill_gif_phashes.py). Nunca toca el objeto físico en R2: keep_guild
    sigue necesitándolo."""
    rows = rows_for_content_hash(conn, content_hash)
    guilds = {r["guild_id"] for r in rows}
    if keep_guild not in guilds:
        raise ValueError(
            f"--keep-guild {keep_guild} no está entre los servidores que "
            f"referencian {content_hash}: {sorted(guilds)}"
        )
    removed = conn.execute(
        "DELETE FROM corpus_gifs WHERE content_hash=? AND guild_id<>?",
        (content_hash, keep_guild),
    ).rowcount

    conn.execute(
        "UPDATE gif_objects SET ref_count=("
        "  SELECT COUNT(*) FROM corpus_gifs WHERE corpus_gifs.content_hash=gif_objects.content_hash"
        ") WHERE content_hash=?",
        (content_hash,),
    )
    conn.commit()
    return {"removed_rows": removed, "kept_guild": keep_guild}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--content-hash",
        help="limita el reporte (o la limpieza) a un solo content_hash",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="borra las filas de otros servidores para --content-hash, dejando --keep-guild",
    )
    ap.add_argument(
        "--keep-guild",
        type=int,
        help="guild_id que se queda con el content_hash (con --apply)",
    )
    ap.add_argument("--db", default=DB_PATH, help=f"ruta de la DB (default: {DB_PATH})")
    args = ap.parse_args()

    if args.apply and not (args.content_hash and args.keep_guild):
        print(
            "--apply exige --content-hash y --keep-guild: nunca un barrido "
            "masivo, siempre un caso revisado a mano.",
            file=sys.stderr,
        )
        return 1

    conn = sqlite3.connect(args.db)
    try:
        if args.apply:
            summary = apply_keep_guild(conn, args.content_hash, args.keep_guild)
            print(
                f"content_hash={args.content_hash}: {summary['removed_rows']} "
                f"filas borradas de otros servidores, guild={summary['kept_guild']} conserva el GIF."
            )
            return 0

        if args.content_hash:
            rows = rows_for_content_hash(conn, args.content_hash)
            if len(rows) < 2:
                print(
                    f"content_hash={args.content_hash} no está compartido entre "
                    "servidores (0 o 1 referencias)."
                )
                return 0
            print_report(
                conn, [(args.content_hash, len({r["guild_id"] for r in rows}))]
            )
        else:
            print_report(conn, find_shared_content_hashes(conn))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
