"""Vuelve a aplicar los /borrar_mis_datos después de restaurar un backup.

Un backup anterior a un borrado todavía tiene los datos del usuario. Cada
/borrar_mis_datos deja una "lápida" (deleted_user_tombstones: solo el id del
usuario y dos fechas, sin contenido) que dura DELETION_TOMBSTONE_RETENTION_DAYS,
más que la vida de los backups. Tras un restore, este script:

  1. borra de user_corpus y de corpus_messages (con el MISMO SQL que
     db.delete_user_data) los datos de cada usuario con lápida vigente;
  2. elimina las lápidas vencidas.

    .venv/bin/python scripts/reapply_deletions.py            # dry-run: solo cuenta
    .venv/bin/python scripts/reapply_deletions.py --apply    # lo hace

Va DESPUÉS de pg_restore y ANTES de arrancar el bot (`sudo systemctl stop bot-purg`
mientras tanto). Una sola transacción. Idempotente. No imprime ids de usuario,
solo cantidades: las lápidas son datos personales y tampoco van a los logs.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import db  # noqa: E402
import pgsync  # noqa: E402


def reapply(conn, *, apply: bool) -> dict:
    now = conn.execute("SELECT utc_now()").fetchone()[0]
    live = [
        r[0]
        for r in conn.execute(
            "SELECT user_id FROM deleted_user_tombstones WHERE expires_at > ?", (now,)
        ).fetchall()
    ]
    expired = conn.execute(
        "SELECT count(*) FROM deleted_user_tombstones WHERE expires_at <= ?", (now,)
    ).fetchone()[0]
    stats = {
        "lapidas_vigentes": len(live),
        "lapidas_vencidas": expired,
        "user_corpus": 0,
        "corpus_messages": 0,
    }
    for user_id in live:
        if apply:
            stats["corpus_messages"] += conn.execute(
                db._SQL_DELETE_CORPUS_OF_AUTHOR, (user_id,)
            ).rowcount
            stats["user_corpus"] += conn.execute(
                db._SQL_DELETE_USER_CORPUS_OF_AUTHOR, (user_id,)
            ).rowcount
        else:
            stats["user_corpus"] += conn.execute(
                "SELECT count(*) FROM user_corpus WHERE author_id=?", (user_id,)
            ).fetchone()[0]
            stats["corpus_messages"] += conn.execute(
                "SELECT count(*) FROM corpus_messages cm WHERE EXISTS ("
                "SELECT 1 FROM user_corpus uc WHERE uc.author_id=? "
                "AND uc.guild_id=cm.guild_id AND uc.message_id=cm.message_id)",
                (user_id,),
            ).fetchone()[0]
    if apply:
        conn.execute(
            "DELETE FROM deleted_user_tombstones WHERE expires_at <= ?", (now,)
        )
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", help="default: DATABASE_URL")
    ap.add_argument("--apply", action="store_true", help="aplica los borrados")
    args = ap.parse_args(argv)
    conn = pgsync.connect(args.dsn)
    try:
        stats = reapply(conn, apply=args.apply)
        if args.apply:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    verbo = "borradas" if args.apply else "a borrar (dry-run)"
    print(
        f"lápidas vigentes: {stats['lapidas_vigentes']} | vencidas: {stats['lapidas_vencidas']}"
        f"{' (eliminadas)' if args.apply else ''}"
    )
    print(
        f"filas {verbo}: user_corpus={stats['user_corpus']} "
        f"corpus_messages={stats['corpus_messages']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
