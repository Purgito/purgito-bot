#!/usr/bin/env python3
"""Migra data/bot.db (SQLite) a PostgreSQL y verifica el resultado.

Reproducible: toma un SNAPSHOT consistente de la SQLite (API backup() de
sqlite3, sirve aunque el bot esté corriendo en WAL), crea el esquema
(src/schema_pg.sql) en PostgreSQL, copia cada tabla con COPY dentro de UNA
transacción (si algo falla, PostgreSQL queda como estaba), reconstruye las
secuencias de los ids y recién entonces compara contra el snapshot.

La SQLite original NO se modifica nunca (se abre en solo lectura).

Uso:
    .venv/bin/python scripts/migrate_sqlite_to_postgres.py            # migra + verifica
    .venv/bin/python scripts/migrate_sqlite_to_postgres.py --verify-only
    .venv/bin/python scripts/migrate_sqlite_to_postgres.py --truncate --yes   # reintento sobre una base ya cargada

Variables: DATABASE_URL (destino), o --dsn. Origen: --sqlite (default data/bot.db).
Si el destino ya tiene filas, se niega salvo --truncate --yes.

Qué se verifica (sale con código != 0 ante cualquier diferencia):
  * mismas tablas migradas (las que existen en ambos esquemas) y cuáles se omiten
  * filas por tabla y filas por (tabla, guild_id)
  * checksum SHA-256 del contenido completo de cada tabla, fila por fila
  * unicidad de claves primarias / UNIQUE ya la impone PostgreSQL al cargar
  * huérfanos lógicos (la base no declara FKs: se comparan las relaciones que
    el código da por buenas) -- mismos conteos en origen y destino
  * secuencias: la próxima id generada es mayor que cualquier id existente y no
    reutiliza ids que SQLite ya había emitido
"""

import argparse
import asyncio
import hashlib
import os
import sqlite3
import sys
import shutil
import tempfile
import time

import asyncpg
from dotenv import dotenv_values

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_SQL = os.path.join(ROOT, "src", "schema_pg.sql")
DEFAULT_SQLITE = os.path.join(ROOT, "data", "bot.db")
BATCH = 20000

# (hijo, columna, padre, columna_padre): relaciones lógicas que el código asume.
LOGICAL_FKS = [
    ("frases_especiales", "pack_id", "frase_packs", "id"),
    ("frase_pack_channels", "pack_id", "frase_packs", "id"),
    ("channel_triggers", "pack_id", "frase_packs", "id"),
    ("gif_senders", "gif_id", "corpus_gifs", "id"),
    ("server_events", "template_id", "embed_templates", "id"),
    ("corpus_gifs", "content_hash", "gif_objects", "content_hash"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def snapshot_sqlite(src_path: str, dest_path: str) -> None:
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = sqlite3.connect(dest_path)
    try:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise SystemExit(f"integrity_check del snapshot: {ok}")
    finally:
        dst.close()
        src.close()


def sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


async def pg_columns(pg: asyncpg.Connection) -> dict[str, list[tuple[str, str, bool]]]:
    rows = await pg.fetch(
        "SELECT table_name, column_name, data_type, is_identity = 'YES' AS ident "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position"
    )
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r["table_name"], []).append(
            (r["column_name"], r["data_type"], r["ident"])
        )
    return out


class Coercions:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, str, str], int] = {}

    def note(self, table: str, col: str, what: str) -> None:
        k = (table, col, what)
        self.counts[k] = self.counts.get(k, 0) + 1


def convert(value, pg_type: str, table: str, col: str, co: Coercions):
    """SQLite es de tipado flexible; PostgreSQL no. Convierte lo que se pueda de
    forma inequívoca y deja constancia; lo demás aborta la migración."""
    if value is None:
        return None
    if pg_type == "bigint":
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            co.note(table, col, "float->int")
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            co.note(table, col, "text->int")
            return int(value)
        raise ValueError(f"{table}.{col}: {value!r} no es un entero")
    if pg_type == "double precision":
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            co.note(table, col, "text->float")
            return float(value)
        raise ValueError(f"{table}.{col}: {value!r} no es un número")
    if pg_type == "text":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            co.note(table, col, "num->text")
            return str(value)
        if isinstance(value, (bytes, bytearray)):
            co.note(table, col, "blob->text")
            return bytes(value).decode("utf-8")
    raise ValueError(f"{table}.{col}: tipo {pg_type} / valor {type(value)}")


def canon(value) -> str:
    """Representación canónica para checksum, igual de ambos lados."""
    if value is None:
        return "\x00N"
    if isinstance(value, float):
        return "f" + repr(value)
    if isinstance(value, int):
        return "i" + str(value)
    return "s" + str(value)


def order_by(cols: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


def sqlite_digest(
    conn: sqlite3.Connection, table: str, cols: list[str]
) -> tuple[int, str]:
    h = hashlib.sha256()
    n = 0
    cur = conn.execute(
        f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}" '
        f"ORDER BY {order_by(cols)}"
    )
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        for row in rows:
            h.update("\x1f".join(canon(v) for v in row).encode() + b"\n")
            n += 1
    return n, h.hexdigest()


async def pg_digest(
    pg: asyncpg.Connection, table: str, cols: list[str], types: dict[str, str]
) -> tuple[int, str]:
    h = hashlib.sha256()
    n = 0
    # Mismo orden que SQLite: NULL primero y texto byte a byte (COLLATE "C").
    order = ", ".join(
        f'"{c}"' + (' COLLATE "C"' if types[c] == "text" else "") + " NULLS FIRST"
        for c in cols
    )
    async with pg.transaction():
        cur = pg.cursor(
            f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}" '
            f"ORDER BY {order}",
            prefetch=BATCH,
        )
        async for row in cur:
            h.update("\x1f".join(canon(v) for v in row).encode() + b"\n")
            n += 1
    return n, h.hexdigest()


async def migrate(args) -> int:
    dsn = (
        args.dsn
        or os.environ.get("DATABASE_URL")
        or dotenv_values(os.path.join(ROOT, ".env")).get("DATABASE_URL")
    )
    if not dsn:
        raise SystemExit("Falta DATABASE_URL (o --dsn).")

    # El snapshot va junto a la SQLite (disco), no en /tmp: en muchos servidores
    # /tmp es tmpfs (RAM) y una copia de cientos de MB puede disparar el OOM killer.
    tmpdir = tempfile.mkdtemp(
        prefix=".purgito-mig-", dir=os.path.dirname(os.path.abspath(args.sqlite))
    )
    snap = os.path.join(tmpdir, "snapshot.db")
    t0 = time.time()
    log(f"[1/6] Snapshot de {args.sqlite} -> {snap}")
    snapshot_sqlite(args.sqlite, snap)
    log(
        f"      ok (integrity_check=ok, {os.path.getsize(snap) / 1e6:.0f} MB, {time.time() - t0:.1f}s)"
    )

    lite = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    pg = await asyncpg.connect(dsn)
    try:
        if not args.verify_only:
            log("[2/6] Esquema PostgreSQL")
            await pg.execute(open(SCHEMA_SQL, encoding="utf-8").read())

        pgcols = await pg_columns(pg)
        lite_tabs = sqlite_tables(lite)
        common = [t for t in lite_tabs if t in pgcols]
        skipped = [t for t in lite_tabs if t not in pgcols]
        extra = [t for t in pgcols if t not in lite_tabs]
        log(
            f"      tablas SQLite={len(lite_tabs)} PostgreSQL={len(pgcols)} migrables={len(common)}"
        )
        for t in skipped:
            n = lite.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            log(
                f"      OMITIDA (sin tabla en PostgreSQL, feature eliminada): {t} ({n} filas, queda en la SQLite/backup)"
            )
        for t in extra:
            log(f"      solo en PostgreSQL (vacía): {t}")

        if not args.verify_only:
            existing = 0
            for t in common:
                existing += await pg.fetchval(f'SELECT COUNT(*) FROM "{t}"')
            if existing:
                if not (args.truncate and args.yes):
                    raise SystemExit(
                        f"El destino ya tiene {existing} filas. Para reintentar desde cero: "
                        "--truncate --yes (borra SOLO las tablas de Purgito en la base destino)."
                    )
                log(
                    f"[3/6] TRUNCATE de {len(common)} tablas del destino (--truncate --yes)"
                )
                names = ", ".join(f'"{t}"' for t in common)
                await pg.execute(f"TRUNCATE {names} RESTART IDENTITY")
            else:
                log("[3/6] Destino vacío")

            log("[4/6] Copia de datos (una sola transacción)")
            co = Coercions()
            async with pg.transaction():
                for t in common:
                    cols = [c for c, _, _ in pgcols[t]]
                    types = {c: ty for c, ty, _ in pgcols[t]}
                    lite_cols = [
                        r[1] for r in lite.execute(f'PRAGMA table_info("{t}")')
                    ]
                    missing = [c for c in lite_cols if c not in types]
                    if missing:
                        raise SystemExit(
                            f"{t}: columnas de SQLite sin destino: {missing}"
                        )
                    # columnas solo de PG (con default) se omiten del COPY
                    use = [c for c in cols if c in lite_cols]
                    total = lite.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    cur = lite.execute(
                        f'SELECT {", ".join(chr(34) + c + chr(34) for c in use)} FROM "{t}"'
                    )
                    done = 0
                    ts = time.time()
                    while True:
                        rows = cur.fetchmany(BATCH)
                        if not rows:
                            break
                        recs = [
                            tuple(
                                convert(v, types[c], t, c, co) for v, c in zip(row, use)
                            )
                            for row in rows
                        ]
                        await pg.copy_records_to_table(t, records=recs, columns=use)
                        done += len(recs)
                        if total > BATCH:
                            log(f"      {t}: {done}/{total}")
                    log(f"      {t:36s} {done:>8d} filas ({time.time() - ts:.1f}s)")
                    if done != total:
                        raise SystemExit(f"{t}: copiadas {done} != {total}")

                log("[5/6] Secuencias de ids")
                seq_src = {}
                if "sqlite_sequence" in [
                    r[0] for r in lite.execute("SELECT name FROM sqlite_master")
                ]:
                    seq_src = dict(
                        lite.execute("SELECT name, seq FROM sqlite_sequence")
                    )
                for t in common:
                    if any(ident for _, _, ident in pgcols[t]):
                        mx = await pg.fetchval(
                            f'SELECT COALESCE(MAX(id), 0) FROM "{t}"'
                        )
                        nxt = max(mx, int(seq_src.get(t, 0))) + 1
                        await pg.execute(
                            f'ALTER TABLE "{t}" ALTER COLUMN id RESTART WITH {nxt}'
                        )
                        log(f"      {t:36s} próxima id = {nxt}")
            if co.counts:
                log("      conversiones de tipo aplicadas:")
                for (t, c, w), n in sorted(co.counts.items()):
                    log(f"        {t}.{c}: {w} x{n}")
            else:
                log(
                    "      sin conversiones de tipo (todos los valores ya eran del tipo correcto)"
                )
        else:
            log("[2-5/6] --verify-only: sin copiar")

        log("[6/6] Verificación SQLite vs PostgreSQL")
        problems: list[str] = []

        for t in common:
            cols = [c for c, _, _ in pgcols[t]]
            lite_cols = [r[1] for r in lite.execute(f'PRAGMA table_info("{t}")')]
            cols = [c for c in cols if c in lite_cols]
            ln, lh = sqlite_digest(lite, t, cols)
            pn, ph = await pg_digest(pg, t, cols, {c: ty for c, ty, _ in pgcols[t]})
            status = "OK " if (ln == pn and lh == ph) else "DIF"
            log(
                f"      {status} {t:36s} filas {ln:>8d}/{pn:<8d} sha256 {lh[:12]}/{ph[:12]}"
            )
            if ln != pn:
                problems.append(f"{t}: filas {ln} != {pn}")
            elif lh != ph:
                problems.append(f"{t}: checksum distinto")

        log("      -- filas por (tabla, guild_id)")
        gcount = 0
        for t in common:
            if "guild_id" not in [c for c, _, _ in pgcols[t]]:
                continue
            a = dict(
                lite.execute(f'SELECT guild_id, COUNT(*) FROM "{t}" GROUP BY guild_id')
            )
            b = {
                r[0]: r[1]
                for r in await pg.fetch(
                    f'SELECT guild_id, COUNT(*) FROM "{t}" GROUP BY guild_id'
                )
            }
            gcount += 1
            if a != b:
                problems.append(f"{t}: conteos por guild_id difieren")
        log(f"      {gcount} tablas con guild_id comparadas por servidor")

        log("      -- huérfanos lógicos (la base no declara FKs)")
        for child, ccol, parent, pcol in LOGICAL_FKS:
            if child not in common or parent not in common:
                continue
            q = (
                f'SELECT COUNT(*) FROM "{child}" c WHERE c."{ccol}" IS NOT NULL AND NOT EXISTS '
                f'(SELECT 1 FROM "{parent}" p WHERE p."{pcol}" = c."{ccol}")'
            )
            a = lite.execute(q).fetchone()[0]
            b = await pg.fetchval(q)
            tag = "OK " if a == b else "DIF"
            log(
                f"      {tag} {child}.{ccol} -> {parent}.{pcol}: huérfanos origen={a} destino={b}"
            )
            if a != b:
                problems.append(f"huérfanos {child}.{ccol}: {a} != {b}")

        log("      -- claves primarias / únicas")
        pk = await pg.fetch(
            "SELECT c.relname FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
            "WHERE k.contype='p' AND c.relnamespace='public'::regnamespace"
        )
        have_pk = {r[0] for r in pk}
        no_pk = [t for t in common if t not in have_pk]
        log(
            f"      {len(have_pk)} tablas con PRIMARY KEY; sin PK: {no_pk or 'ninguna'}"
        )
        idx = await pg.fetchval(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public'"
        )
        sidx = lite.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        log(
            f"      índices explícitos: SQLite={sidx} PostgreSQL(total, incluye PK/UNIQUE)={idx}"
        )

        log("      -- secuencias")
        seq_ok = True
        for t in common:
            if any(ident for _, _, ident in pgcols[t]):
                mx = await pg.fetchval(f'SELECT COALESCE(MAX(id), 0) FROM "{t}"')
                seqname = await pg.fetchval(
                    "SELECT pg_get_serial_sequence($1, 'id')", t
                )
                row = await pg.fetchrow(f"SELECT last_value, is_called FROM {seqname}")
                next_id = row["last_value"] + (1 if row["is_called"] else 0)
                if next_id <= mx:
                    seq_ok = False
                    problems.append(f"{t}: próxima id {next_id} <= max {mx}")
        log(
            "      secuencias OK (próxima id > max(id) en todas)"
            if seq_ok
            else "      PROBLEMAS en secuencias"
        )

        if problems:
            log("\nRESULTADO: FALLÓ LA VERIFICACIÓN")
            for p in problems:
                log(f"  - {p}")
            return 1
        log(f"\nRESULTADO: OK ({len(common)} tablas, {time.time() - t0:.0f}s)")
        return 0
    finally:
        await pg.close()
        lite.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE)
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--truncate", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    return asyncio.run(migrate(args))


if __name__ == "__main__":
    sys.exit(main())
