"""Vuelve a aplicar los eliminación de datos (Centro de Privacidad) después de restaurar un backup.

Un backup anterior a un borrado todavía tiene los datos del usuario. Cada
eliminación de datos (Centro de Privacidad) deja una "lápida" (deleted_user_tombstones: solo el id del
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
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import db  # noqa: E402
import pgsync  # noqa: E402
import privacy_ledger  # noqa: E402
import privacy_requests  # noqa: E402


# Frescura exigida al registro externo: se exporta cada pocos minutos, así que uno más viejo que
# esto indica que el exportador falló y puede faltar algo reciente. Se prefiere fallar.
MAX_LEDGER_AGE_HOURS = 2
_TS = "%Y-%m-%d %H:%M:%S"


def _parse_ts(text):
    try:
        return datetime.strptime(str(text), _TS).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def check_ledger_freshness(conn, ledger: dict, now: datetime | None = None) -> str | None:
    """Motivo por el que el registro NO sirve para reconciliar esta base, o None si sirve."""
    now = now or datetime.now(timezone.utc)
    exported = _parse_ts(ledger.get("exported_at"))
    if exported is None:
        return "el registro no trae una fecha de exportación válida"
    if now - exported > timedelta(hours=MAX_LEDGER_AGE_HOURS):
        return (
            f"el registro tiene más de {MAX_LEDGER_AGE_HOURS} h ({ledger['exported_at']} UTC): "
            "faltarían las eliminaciones posteriores"
        )
    row = conn.execute("SELECT value FROM privacy_state WHERE key='heartbeat_at'").fetchone()
    db_hb = _parse_ts(row[0]) if row else None
    if db_hb is not None and exported < db_hb - timedelta(minutes=5):
        return (
            f"el registro ({ledger['exported_at']}) es ANTERIOR a la base ({row[0]}): "
            "no puede contener lo que ocurrió después"
        )
    return None


def stamp_reconciled(conn, how: str) -> None:
    """Marca la base como reconciliada: el latido que lee privacy_guard pasa a 'ahora'."""
    now = datetime.now(timezone.utc).strftime(_TS)
    for key, value in (("heartbeat_at", now), ("reconciled_at", now), ("reconciled_with", how)):
        conn.execute(
            "INSERT INTO privacy_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now),
        )


def merge_ledger(conn, ledger: dict) -> dict:
    """Funde una instantánea (privacy_ledger.loads) en la base, dentro de la
    transacción del llamador. Solo lápidas vigentes; conserva la expiración más
    lejana; las exclusiones solo se suman (GREATEST), nunca se quitan."""
    now = conn.execute("SELECT utc_now()").fetchone()[0]
    stats = {
        "lapidas_usuario": 0,
        "lapidas_servidor": 0,
        "exclusiones": 0,
        "solicitudes": 0,
        "mensajes_registrados": 0,
        "canales_registrados": 0,
    }
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
    # Lápidas de mensajes sueltos y de canales eliminados (solo vigentes, y no de servidores que
    # se purgan enteros).
    msg_rows = [
        (r["guild_id"], r["message_id"], r["deleted_at"], r["expires_at"])
        for r in ledger.get("message_tombstones", [])
        if r["expires_at"] > now and r["guild_id"] not in live_guilds
    ]
    if msg_rows:
        conn.executemany(
            "INSERT INTO deleted_message_tombstones (guild_id, message_id, deleted_at, expires_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (guild_id, message_id) DO UPDATE SET "
            "expires_at=GREATEST(deleted_message_tombstones.expires_at, excluded.expires_at)",
            msg_rows,
        )
    chan_rows = [
        (r["guild_id"], r["channel_id"], r["deleted_at"], r["expires_at"])
        for r in ledger.get("channel_tombstones", [])
        if r["expires_at"] > now and r["guild_id"] not in live_guilds
    ]
    if chan_rows:
        conn.executemany(
            "INSERT INTO deleted_channel_tombstones (guild_id, channel_id, deleted_at, expires_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (guild_id, channel_id) DO UPDATE SET "
            "expires_at=GREATEST(deleted_channel_tombstones.expires_at, excluded.expires_at)",
            chan_rows,
        )
    stats["mensajes_registrados"] = len(msg_rows)
    stats["canales_registrados"] = len(chan_rows)
    # Solicitudes del Centro de Privacidad que seguían abiertas al exportar: se recrean (con
    # su fecha límite original) para que el trabajador las procese al arrancar el bot.
    for rec in ledger.get("deletion_requests", []):
        if conn.execute(
            "SELECT 1 FROM privacy_requests WHERE user_id=? AND kind='delete' "
            "AND status <> 'completed'",
            (rec["user_id"],),
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO privacy_requests (user_id, kind, status, source, created_at, "
            "due_at, next_attempt_at) VALUES (?, 'delete', 'pending', 'restore', ?, ?, ?)",
            (rec["user_id"], rec["created_at"], rec["due_at"], now),
        )
        new_id = conn.execute(
            "SELECT id FROM privacy_requests WHERE user_id=? AND kind='delete' "
            "AND status <> 'completed'",
            (rec["user_id"],),
        ).fetchone()[0]
        privacy_requests.append_log_sync(
            conn, new_id, "restored_from_ledger", {"due_at": rec["due_at"]}, now
        )
        stats["solicitudes"] += 1
    return stats


def reapply(conn, *, apply: bool, cutoffs=()) -> dict:
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
                db._SQL_DELETE_CORPUS_OF_AUTHOR, (user_id, user_id)
            ).rowcount
            stats["user_corpus"] += conn.execute(
                db._SQL_DELETE_USER_CORPUS_OF_AUTHOR, (user_id,)
            ).rowcount
            conn.execute(db._SQL_DELETE_GIF_SENDERS_OF_USER, (user_id,))
            conn.execute(db._SQL_DELETE_BOOSTS_OF_USER, (user_id,))
            for sql, repeat in db._PSEUDONYMIZE_STATEMENTS:
                conn.execute(sql, (user_id,) * repeat)
        else:
            stats["user_corpus"] += conn.execute(
                "SELECT count(*) FROM user_corpus WHERE author_id=?", (user_id,)
            ).fetchone()[0]
            stats["corpus_messages"] += conn.execute(
                "SELECT count(*) FROM corpus_messages cm WHERE cm.author_id=? OR EXISTS ("
                "SELECT 1 FROM user_corpus uc WHERE uc.author_id=? "
                "AND uc.guild_id=cm.guild_id AND uc.message_id=cm.message_id)",
                (user_id, user_id),
            ).fetchone()[0]
    stats["mensajes_sueltos"] = 0
    stats["canales"] = 0
    for table, key in (("deleted_message_tombstones", "message_id"), ("deleted_channel_tombstones", "channel_id")):
        stat = "mensajes_sueltos" if key == "message_id" else "canales"
        for corpus in ("corpus_messages", "user_corpus"):
            if apply:
                n = conn.execute(
                    f"DELETE FROM {corpus} c USING {table} t WHERE t.expires_at > ? "
                    f"AND c.guild_id = t.guild_id AND c.{key} = t.{key}",
                    (now,),
                ).rowcount
            else:
                n = conn.execute(
                    f"SELECT count(*) FROM {corpus} c JOIN {table} t ON t.expires_at > ? "
                    f"AND c.guild_id = t.guild_id AND c.{key} = t.{key}",
                    (now,),
                ).fetchone()[0]
            stats[stat] += n
    # Un backup anterior a author_id devuelve mensajes sin autor: se atribuyen SOLO por el vínculo exacto con
    # user_corpus y los que no se puedan atribuir se eliminan (mismo criterio que db.reconcile_corpus_authors).
    stats["sin_autor"] = 0
    if apply:
        conn.execute(
            "UPDATE corpus_messages SET author_id = uc.author_id FROM user_corpus uc "
            "WHERE corpus_messages.author_id IS NULL AND uc.guild_id = corpus_messages.guild_id "
            "AND uc.message_id = corpus_messages.message_id"
        )
        stats["sin_autor"] = conn.execute(
            "DELETE FROM corpus_messages WHERE author_id IS NULL"
        ).rowcount
    else:
        stats["sin_autor"] = conn.execute(
            "SELECT count(*) FROM corpus_messages cm WHERE cm.author_id IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM user_corpus uc WHERE uc.guild_id = cm.guild_id AND uc.message_id = cm.message_id)"
        ).fetchone()[0]
    # Cortes por servidor (desbordamiento del registro): se borra TODO lo aprendido antes del corte.
    stats["servidores_cortados"] = len(cutoffs)
    stats["filas_cortadas"] = 0
    for rec in cutoffs:
        for corpus in ("corpus_messages", "user_corpus"):
            if apply:
                stats["filas_cortadas"] += conn.execute(
                    f"DELETE FROM {corpus} WHERE guild_id=? AND created_at <= ?",
                    (rec["guild_id"], rec["cutoff"]),
                ).rowcount
            else:
                stats["filas_cortadas"] += conn.execute(
                    f"SELECT count(*) FROM {corpus} WHERE guild_id=? AND created_at <= ?",
                    (rec["guild_id"], rec["cutoff"]),
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
        conn.execute("DELETE FROM deleted_message_tombstones WHERE expires_at <= ?", (now,))
        conn.execute("DELETE FROM deleted_channel_tombstones WHERE expires_at <= ?", (now,))
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
    ap.add_argument(
        "--aceptar-truncado",
        action="store_true",
        help="seguir aunque el registro marque lápidas de mensajes truncadas por el tope",
    )
    ap.add_argument(
        "--aceptar-registro-antiguo",
        action="store_true",
        help=f"aceptar un registro de más de {MAX_LEDGER_AGE_HOURS} h o anterior a la base "
        "(se pueden haber perdido eliminaciones recientes)",
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
        if ledger["truncated"] and not args.aceptar_truncado:
            print(
                "ERROR: el registro está TRUNCADO (hubo más lápidas de mensajes que el tope): "
                "algunos mensajes borrados podrían reaparecer. No se tocó nada. Si lo aceptas, "
                "repite con --aceptar-truncado.",
                file=sys.stderr,
            )
            return 1
    conn = pgsync.connect(args.dsn)
    try:
        # Un backup anterior a las tablas nuevas (privacy_state, lápidas de mensajes...) no las
        # tiene y el bot, que las crearía, no puede arrancar hasta reconciliar: se crean acá
        # (el esquema es idempotente: CREATE ... IF NOT EXISTS).
        conn.executescript(db.SCHEMA)
        if ledger is not None:
            reason = check_ledger_freshness(conn, ledger)
            if reason and not args.aceptar_registro_antiguo:
                conn.rollback()
                print(
                    f"ERROR: {reason}. No se tocó nada. Si lo aceptas conscientemente, repite con "
                    "--aceptar-registro-antiguo.",
                    file=sys.stderr,
                )
                return 1
            if reason:
                print(f"AVISO (aceptado): {reason}", file=sys.stderr)
            merged = merge_ledger(conn, ledger)
            print(
                f"registro externo ({ledger['exported_at']}): "
                f"lápidas de usuario={merged['lapidas_usuario']} "
                f"de servidor={merged['lapidas_servidor']} "
                f"exclusiones restauradas={merged['exclusiones']} "
                f"solicitudes recreadas={merged['solicitudes']} "
                f"mensajes={merged['mensajes_registrados']} canales={merged['canales_registrados']}"
                f"{'' if args.apply else ' (dry-run: no se guarda)'}"
            )
        stats = reapply(
            conn,
            apply=args.apply,
            cutoffs=(ledger or {}).get("guild_cutoffs", []),
        )
        if args.apply:
            stamp_reconciled(conn, "ledger" if ledger is not None else "none")
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
    print(f"mensajes sin autor atribuible {verbo}: {stats['sin_autor']}")
    if stats["servidores_cortados"]:
        print(
            f"servidores con corte (registro desbordado): {stats['servidores_cortados']} | "
            f"filas {verbo}: {stats['filas_cortadas']}"
        )
    print(
        f"mensajes sueltos {verbo}: {stats['mensajes_sueltos']} | "
        f"canales eliminados {verbo}: {stats['canales']}"
    )
    print(
        f"servidores purgados vigentes: {stats['lapidas_servidor_vigentes']} | "
        f"filas {verbo}: {stats['filas_servidores']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
