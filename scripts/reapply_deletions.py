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

Además de las lápidas de la propia base (que un backup anterior no tiene), acepta la
instantánea del registro de privacidad exportada fuera del servidor
(scripts/export_privacy_ledger.py, src/privacy_ledger.py) con --ledger:

    age -d -i <clave> instantanea.jsonl.age | ssh servidor \\
        '.venv/bin/python scripts/reapply_deletions.py --ledger - --apply'

La instantánea trae lápidas de usuarios y de servidores purgados, y las exclusiones
activas. Se funde con la base (nunca se quita una restricción), se borra lo de cada
usuario/servidor con lápida vigente y se restauran las exclusiones. Con `-` lee de la
entrada estándar: así el registro en claro no toca el disco del servidor.

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
import privacy_ledger  # noqa: E402


def merge_ledger(conn, ledger: dict) -> dict:
    """Funde una instantánea (privacy_ledger.loads) en la base, dentro de la
    transacción del llamador. Solo lápidas vigentes; conserva la expiración más
    lejana; las exclusiones solo se suman (GREATEST), nunca se quitan."""
    now = conn.execute("SELECT utc_now()").fetchone()[0]
    stats = {"lapidas_usuario": 0, "lapidas_servidor": 0, "exclusiones": 0}
    for rec in ledger["user_tombstones"]:
        if rec["expires_at"] <= now:
            continue
        conn.execute(
            "INSERT INTO deleted_user_tombstones (user_id, deleted_at, expires_at) "
            "VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET "
            "expires_at=GREATEST(deleted_user_tombstones.expires_at, excluded.expires_at)",
            (rec["user_id"], rec["deleted_at"], rec["expires_at"]),
        )
        stats["lapidas_usuario"] += 1
    live_guilds = set()
    for rec in ledger["guild_tombstones"]:
        if rec["expires_at"] <= now:
            continue
        conn.execute(
            "INSERT INTO purged_guild_tombstones (purged_guild_id, purged_at, expires_at) "
            "VALUES (?, ?, ?) ON CONFLICT (purged_guild_id) DO UPDATE SET "
            "expires_at=GREATEST(purged_guild_tombstones.expires_at, excluded.expires_at)",
            (rec["guild_id"], rec["purged_at"], rec["expires_at"]),
        )
        live_guilds.add(rec["guild_id"])
        stats["lapidas_servidor"] += 1
    for rec in ledger["exclusions"]:
        if rec["guild_id"] in live_guilds:
            continue  # el servidor se purga entero; su exclusión no tiene sentido
        conn.execute(
            "INSERT INTO excluded_users (guild_id, user_id, exclude_interaction, "
            "exclude_learning, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET "
            "exclude_interaction=GREATEST(excluded_users.exclude_interaction, excluded.exclude_interaction), "
            "exclude_learning=GREATEST(excluded_users.exclude_learning, excluded.exclude_learning)",
            (
                rec["guild_id"],
                rec["user_id"],
                rec["exclude_interaction"],
                rec["exclude_learning"],
                rec["created_at"],
            ),
        )
        stats["exclusiones"] += 1
    return stats


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
            conn.execute(db._SQL_DELETE_GIF_SENDERS_OF_USER, (user_id,))
            conn.execute(db._SQL_DELETE_BOOSTS_OF_USER, (user_id,))
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
    live_guilds = [
        r[0]
        for r in conn.execute(
            "SELECT purged_guild_id FROM purged_guild_tombstones WHERE expires_at > ?",
            (now,),
        ).fetchall()
    ]
    stats["lapidas_servidor_vigentes"] = len(live_guilds)
    stats["filas_servidores"] = 0
    for guild_id in live_guilds:
        for table in db._GUILD_PURGE_TABLES:
            if apply:
                stats["filas_servidores"] += conn.execute(
                    f"DELETE FROM {table} WHERE guild_id=?", (guild_id,)
                ).rowcount
            else:
                stats["filas_servidores"] += conn.execute(
                    f"SELECT count(*) FROM {table} WHERE guild_id=?", (guild_id,)
                ).fetchone()[0]
    if apply:
        conn.execute(
            "DELETE FROM deleted_user_tombstones WHERE expires_at <= ?", (now,)
        )
        conn.execute(
            "DELETE FROM purged_guild_tombstones WHERE expires_at <= ?", (now,)
        )
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", help="default: DATABASE_URL")
    ap.add_argument("--apply", action="store_true", help="aplica los borrados")
    ap.add_argument(
        "--ledger",
        metavar="ARCHIVO",
        help="instantánea del registro de privacidad ya descifrada (JSONL); "
        "'-' lee de la entrada estándar",
    )
    ap.add_argument(
        "--sin-registro",
        action="store_true",
        help="restaurar SIN el registro externo (solo lápidas del propio backup); "
        "por defecto se exige --ledger: sin él se pueden resucitar borrados",
    )
    args = ap.parse_args(argv)
    if not args.ledger and not args.sin_registro:
        print(
            "ERROR: falta --ledger (registro externo de eliminaciones). Sin él un "
            "backup viejo puede devolver datos ya borrados. Si de verdad no hay "
            "registro, repite con --sin-registro. No se tocó nada.",
            file=sys.stderr,
        )
        return 1
    ledger = None
    if args.ledger:
        try:
            raw = (
                sys.stdin.read()
                if args.ledger == "-"
                else open(args.ledger, encoding="utf-8").read()
            )
            ledger = privacy_ledger.loads(raw)
        except (OSError, privacy_ledger.LedgerError) as e:
            print(f"ERROR: instantánea inválida: {e}", file=sys.stderr)
            return 1
    conn = pgsync.connect(args.dsn)
    try:
        if ledger is not None:
            merged = merge_ledger(conn, ledger)
            print(
                f"registro externo ({ledger['exported_at']}): "
                f"lápidas de usuario={merged['lapidas_usuario']} "
                f"de servidor={merged['lapidas_servidor']} "
                f"exclusiones restauradas={merged['exclusiones']}"
                f"{'' if args.apply else ' (dry-run: no se guarda)'}"
            )
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
    print(
        f"servidores purgados vigentes: {stats['lapidas_servidor_vigentes']} | "
        f"filas {verbo}: {stats['filas_servidores']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
