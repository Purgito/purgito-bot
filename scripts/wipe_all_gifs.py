"""Borra TODOS los GIFs guardados de TODOS los servidores (DB + R2).

Contexto: antes del fix de matching perceptual en r2.upload_gif_bytes_sync
(ver GifFingerprint / _fingerprints_compatible), un falso positivo del dedup
podía dejar la fila de corpus_gifs de un servidor apuntando al objeto físico
que otro servidor había subido -- la fila queda con su guild_id correcto,
pero el contenido real detrás de la URL es ajeno. El fix impide que pase de
nuevo, pero no repara retroactivamente lo que ya quedó mal antes de esa fecha.

scripts/audit_cross_guild_gifs.py existe para localizar y corregir esos casos
uno por uno sin tocar el resto de la base (recomendado si se puede
diferenciar contaminación de dedup exacto legítimo, por ejemplo cruzando con
los logs de "GIF casi-duplicado detectado"). Este script es la alternativa
nuclear cuando se prefiere no arriesgar ningún residuo: borra el corpus de
GIFs entero, de todos los servidores, sin distinguir contaminado de
legítimo. No
hay forma de deshacer esto -- cada servidor vuelve a completar su pool de
GIFs solo a medida que su gente vuelve a postear.

No toca corpus_images ni ninguna otra tabla: separado a propósito de
db.purge_guild_data, que borra un guild entero para siempre y no es lo que
se pide acá (los servidores siguen existiendo, solo pierden sus GIFs).

Cubre las tres generaciones de objetos que puede haber en el bucket (ver el
docstring de reconcile_gif_objects.py): recorre TODO el prefijo `gifs/`
(gen. 2 y 3, content-addressed, sin importar si gif_objects quedó
consistente) y además cada URL propia que quede en corpus_gifs fuera de ese
prefijo (gen. 1, legacy `{guild_id}/{md5}.gif`) -- así una fila huérfana o un
ref_count corrido no deja nada físico atrás.

Dry-run por default: sin --apply solo cuenta. Con --apply hace falta pasar
además --confirm-count con el número EXACTO de servidores afectados que
reportó el dry-run -- fuerza a leer ese número antes de ejecutar, en vez de
copiar un comando con --apply a ciegas.

Conviene parar el bot mientras corre (`sudo systemctl stop bot-purg`): borra
filas de corpus_gifs y objetos de R2 por debajo del bot, y una subida en
paralelo podría reinsertar algo a mitad de camino.

    python scripts/wipe_all_gifs.py                              # solo informa
    python scripts/wipe_all_gifs.py --apply --confirm-count N    # borra todo
"""

import argparse
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import config  # noqa: F401,E402  -- carga .env / limits.env al importarse
import r2  # noqa: E402

log = logging.getLogger("wipe_all_gifs")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db"
)


def _legacy_keys(conn, pub: str) -> set[str]:
    """Keys de corpus_gifs que apuntan al propio bucket pero NO caen bajo el
    prefijo content-addressed `gifs/` -- generación 1, legacy por guild."""
    content_prefix = f"{pub}/{r2.GIF_KEY_PREFIX}"
    rows = conn.execute(
        "SELECT url FROM corpus_gifs WHERE url LIKE ? AND url NOT LIKE ?",
        (pub + "/%", content_prefix + "%"),
    ).fetchall()
    return {r[0][len(pub) + 1 :] for r in rows}


def gather(conn) -> dict:
    n_rows, n_guilds = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT guild_id) FROM corpus_gifs"
    ).fetchone()
    n_objects = conn.execute("SELECT COUNT(*) FROM gif_objects").fetchone()[0]

    pub = r2.public_url().rstrip("/")
    content_keys = {key for key, _size, _mtime in r2.list_keys_sync(r2.GIF_KEY_PREFIX)}
    legacy_keys = _legacy_keys(conn, pub) if pub else set()
    keys = content_keys | legacy_keys

    return {
        "n_rows": n_rows,
        "n_guilds": n_guilds,
        "n_objects": n_objects,
        "keys": keys,
    }


def apply_wipe(conn, keys: set[str]) -> None:
    client = r2.get_client()
    if client is not None:
        for key in keys:
            try:
                client.delete_object(Bucket=r2._bucket(), Key=key)
            except Exception:
                log.warning("No se pudo borrar objeto de R2: %s", key)
    else:
        log.warning(
            "Cliente de R2 no disponible: se borran las filas de la DB igual, "
            "pero %d objeto(s) físico(s) van a quedar huérfanos en el bucket.",
            len(keys),
        )

    conn.execute("DELETE FROM corpus_gifs")
    conn.execute("DELETE FROM gif_objects")
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply",
        action="store_true",
        help="ejecuta el borrado (default: solo informa)",
    )
    ap.add_argument(
        "--confirm-count",
        type=int,
        help="cantidad exacta de servidores afectados reportada por el dry-run -- "
        "obligatorio junto con --apply",
    )
    ap.add_argument("--db", default=DB_PATH, help=f"ruta de la DB (default: {DB_PATH})")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = sqlite3.connect(args.db)
    try:
        info = gather(conn)
        print(
            f"{info['n_rows']} fila(s) de corpus_gifs en {info['n_guilds']} servidor(es), "
            f"{info['n_objects']} objeto(s) en gif_objects, "
            f"{len(info['keys'])} objeto(s) físico(s) en R2 bajo GIFs."
        )

        if not args.apply:
            print(
                "Dry-run: no se borró nada. Repetir con "
                f"--apply --confirm-count {info['n_guilds']} para borrar todo."
            )
            return 0

        if args.confirm_count != info["n_guilds"]:
            print(
                f"--confirm-count no coincide con los {info['n_guilds']} servidor(es) "
                "afectados ahora mismo -- no se borró nada. Volvé a correr sin --apply "
                "para ver el número actual antes de confirmar.",
                file=sys.stderr,
            )
            return 1

        apply_wipe(conn, info["keys"])
        print(
            f"Borrado: {info['n_rows']} fila(s) de {info['n_guilds']} servidor(es) y "
            f"{len(info['keys'])} objeto(s) físico(s) de R2."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
