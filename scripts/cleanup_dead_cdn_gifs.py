"""Limpia de corpus_gifs los links crudos de cdn.discordapp.com que ya no resuelven.

Antes del fix en cogs/gifs.py::save_gif_candidates, si la subida a R2 de un
GIF de Discord fallaba (por ejemplo un 404 porque el link firmado ya había
expirado al momento del /refeed), el código guardaba igual la URL cruda de
cdn.discordapp.com en vez de descartar el GIF. Esos links están firmados y
expiran solos con el tiempo, así que terminan siendo "This content is no
longer available" en cualquier servidor donde se haya corrido /refeed o
/refeed_all sobre mensajes viejos -- no es un problema de un guild puntual.

Dry-run por default: sin --apply solo cuenta y desglosa por guild, sin tocar
nada.

    python scripts/cleanup_dead_cdn_gifs.py            # solo informa
    python scripts/cleanup_dead_cdn_gifs.py --apply    # borra las confirmadas muertas

Seguro para correr con el bot en marcha: solo hace SELECT/DELETE sobre
corpus_gifs y gif_objects (las mismas tablas y el mismo chequeo HTTP que usa
el ciclo de salud diario del bot -- ver run_gif_health_check en cogs/gifs.py),
sin tocar nada del corpus de texto ni pisar ninguna corrida en curso.

## Criterio de borrado

Cada URL se chequea con r2.check_gif_url_health (mismo chequeo que el ciclo
de salud periódico): "dead" (404/410 confirmado, o Content-Type que no es de
imagen/video) se borra; "unreachable" (timeout o error de red puntual, no
concluyente) se deja tal cual -- puede ser una caída transitoria del CDN, y
el ciclo de salud diario del bot la va a revisar de nuevo solo; "ok" no se
toca -- alguna URL firmada podría seguir vigente todavía.

Estas filas casi nunca tienen content_hash (el bug las guardaba sin subir
nada a R2), pero por las dudas el borrado libera la referencia en
gif_objects igual que db.release_gif_reference, para no dejar un huérfano si
alguna fila más vieja sí lo tenía.
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
import r2  # noqa: E402

log = logging.getLogger("cleanup_dead_cdn_gifs")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db"
)
CHECK_SLEEP = 1.0


def release_reference(conn, client, content_hash: str | None) -> None:
    """Decrementa ref_count en gif_objects y borra el objeto de R2 si llega a
    0. No-op si content_hash es None (el caso normal para estas filas)."""
    if not content_hash:
        return
    conn.execute(
        "UPDATE gif_objects SET ref_count = ref_count - 1 "
        "WHERE content_hash=? AND ref_count > 0",
        (content_hash,),
    )
    row = conn.execute(
        "SELECT r2_key, ref_count FROM gif_objects WHERE content_hash=?",
        (content_hash,),
    ).fetchone()
    if row and row[1] <= 0:
        conn.execute("DELETE FROM gif_objects WHERE content_hash=?", (content_hash,))
        if client is not None:
            try:
                client.delete_object(Bucket=r2._bucket(), Key=row[0])
            except Exception:
                log.warning("No se pudo borrar objeto de R2: %s", row[0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply",
        action="store_true",
        help="borra las confirmadas muertas; sin esta bandera solo informa (default)",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=CHECK_SLEEP,
        help=f"segundos entre chequeos HTTP (default: {CHECK_SLEEP})",
    )
    ap.add_argument("--db", default=DB_PATH, help=f"ruta de la DB (default: {DB_PATH})")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if not args.apply:
        log.info("=== DRY-RUN: no se borra nada. Usar --apply para ejecutar. ===")

    client = r2.get_client()

    conn = sqlite3.connect(args.db)
    try:
        rows = conn.execute(
            "SELECT id, guild_id, url, content_hash FROM corpus_gifs "
            "WHERE url LIKE '%cdn.discordapp.com%'"
        ).fetchall()
        n_guilds = len({r[1] for r in rows})
        log.info(
            "%d fila(s) con URL cruda de cdn.discordapp.com en %d guild(s)",
            len(rows),
            n_guilds,
        )
        if not rows:
            return 0

        dead: list[tuple[int, str | None]] = []
        unreachable = ok = 0
        per_guild_dead: dict[int, int] = defaultdict(int)

        for gif_id, guild_id, url, content_hash in rows:
            status = r2.check_gif_url_health(url)
            if status == "dead":
                dead.append((gif_id, content_hash))
                per_guild_dead[guild_id] += 1
            elif status == "unreachable":
                unreachable += 1
            else:
                ok += 1
            time.sleep(args.sleep)

        log.info(
            "Resultado: %d muertas (confirmadas), %d inalcanzables (no concluyente), %d todavía vivas",
            len(dead),
            unreachable,
            ok,
        )
        for guild_id, n in sorted(per_guild_dead.items(), key=lambda kv: -kv[1]):
            log.info("  guild %s: %d muerta(s)", guild_id, n)

        if not args.apply:
            log.info(
                "Dry-run: no se borró nada. Repetir con --apply para borrar las %d confirmadas muertas.",
                len(dead),
            )
            return 0

        for gif_id, content_hash in dead:
            conn.execute("DELETE FROM corpus_gifs WHERE id=?", (gif_id,))
            release_reference(conn, client, content_hash)
        conn.commit()
        log.info("Borradas %d fila(s).", len(dead))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
