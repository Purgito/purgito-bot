"""Usa el pool existente. Batch idempotente y transaccional; sin red externa."""

import hashlib
import uuid
from datetime import timedelta

from .model import utcnow


class Store:
    def __init__(self, database, settings):
        self.pool = database.pool
        self.settings = settings

    async def start(self, session_id, at):
        fingerprint = hashlib.sha256(self.settings.key.encode()).hexdigest()
        async with self.pool.acquire(timeout=3) as c, c.transaction():
            await c.execute(
                "INSERT INTO studio_meta VALUES('key_fingerprint',$1) ON CONFLICT DO NOTHING",
                fingerprint,
            )
            old = await c.fetchval(
                "SELECT value FROM studio_meta WHERE key='key_fingerprint'"
            )
            if old != fingerprint:
                raise ValueError(
                    "STUDIO_HMAC_KEY cambió; no mezclar identidades. Ver documentación de reinicio de cobertura."
                )
            await c.execute(
                "INSERT INTO studio_sessions(id,version,started_at,flushed_until) VALUES($1,$2,$3,$3)",
                session_id,
                self.settings.version,
                at,
            )

    async def write(self, batch, session_id, dropped=0):
        idle = not (batch["usage"] or batch["lifecycle"] or batch["inventory"])
        async with self.pool.acquire(timeout=3) as c, c.transaction():
            await c.execute("SET LOCAL statement_timeout = '5s'")
            # Un lote sin datos solo avanza la cobertura (UPDATE idempotente): no
            # necesita fila de ledger, que si no crecería 8.640 filas al día en reposo.
            new = idle or await c.fetchval(
                "INSERT INTO studio_batches VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING id",
                batch["id"],
                batch["at"],
            )
            if not new:
                return
            rows = [(*key, *values) for key, values in batch["usage"].items()]
            if rows:
                await c.executemany(
                    """INSERT INTO studio_usage VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                  ON CONFLICT(hour,guild_key,feature,command,source,result,version) DO UPDATE SET
                  n=studio_usage.n+excluded.n, duration_n=studio_usage.duration_n+excluded.duration_n,
                  duration_sum=studio_usage.duration_sum+excluded.duration_sum,
                  histogram=ARRAY(SELECT a+b FROM unnest(studio_usage.histogram,excluded.histogram) AS x(a,b))""",
                    rows,
                )
            for event_id, at, guild, action in batch["lifecycle"]:
                # Duplicados del gateway no son instalaciones nuevas.
                prior = await c.fetchrow(
                    "SELECT action FROM studio_lifecycle WHERE guild_key=$1 ORDER BY sequence DESC LIMIT 1",
                    guild,
                )
                if prior and ((action == "leave") == (prior["action"] == "leave")):
                    continue
                if action == "join" and prior and prior["action"] == "leave":
                    action = "rejoin"
                elif (
                    action == "join"
                    and not prior
                    and await c.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM studio_presence WHERE guild_key=$1 AND day < $2)",
                        guild,
                        at.date(),
                    )
                ):
                    # Ya figuraba en un inventario anterior (p. ej. la salida ocurrió
                    # con el bot apagado o expiró): es un reingreso, no una comunidad nueva.
                    action = "rejoin"
                await c.execute(
                    "INSERT INTO studio_lifecycle(id,at,guild_key,action,version) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
                    event_id,
                    at,
                    guild,
                    action,
                    self.settings.version,
                )
            if batch["inventory"] is not None:
                at, guilds = batch["inventory"]
                day = at.date()
                await c.execute(
                    "INSERT INTO studio_inventory VALUES($1,$2,$3,$4) ON CONFLICT(day) DO UPDATE SET observed_at=excluded.observed_at,version=excluded.version,installed=excluded.installed",
                    day,
                    at,
                    self.settings.version,
                    len(guilds),
                )
                await c.execute("DELETE FROM studio_presence WHERE day=$1", day)
                if guilds:
                    await c.executemany(
                        "INSERT INTO studio_presence VALUES($1,$2)",
                        [(day, g) for g in guilds],
                    )
            await c.execute(
                "UPDATE studio_sessions SET flushed_until=$2,dropped=$3 WHERE id=$1",
                session_id,
                batch.get("coverage_until", batch["at"]),
                dropped,
            )

    async def finish(self, session_id):
        async with self.pool.acquire(timeout=3) as c:
            await c.execute(
                "UPDATE studio_sessions SET clean=TRUE WHERE id=$1", session_id
            )

    async def cleanup(self, now=None):
        cutoff = (now or utcnow()) - timedelta(days=self.settings.retention_days)
        async with self.pool.acquire(timeout=3) as c, c.transaction():
            for sql in (
                "DELETE FROM studio_usage WHERE hour < $1",
                "DELETE FROM studio_lifecycle WHERE at < $1",
                "DELETE FROM studio_batches WHERE at < $1",
                "DELETE FROM studio_annotations WHERE at < $1",
                "DELETE FROM studio_inventory WHERE observed_at < $1",
                "DELETE FROM studio_sessions WHERE flushed_until < $1",
            ):
                await c.execute(sql, cutoff)

    async def annotate(self, at, title, note="", version="", kind="change"):
        if (
            not isinstance(title, str)
            or not 1 <= len(title.strip()) <= 120
            or not isinstance(note, str)
            or len(note) > 1000
        ):
            raise ValueError("Título de 1–120 caracteres; nota de hasta 1000")
        if (
            kind not in {"release", "change", "manual_observation"}
            or not isinstance(version, str)
            or len(version) > 80
        ):
            raise ValueError("Tipo o versión inválidos")
        if at > utcnow() or at < utcnow() - timedelta(
            days=self.settings.retention_days
        ):
            raise ValueError(
                "La anotación debe estar dentro de la ventana de retención"
            )
        ident = uuid.uuid4()
        async with self.pool.acquire(timeout=3) as c:
            await c.execute(
                "INSERT INTO studio_annotations VALUES($1,$2,$3,$4,$5,$6)",
                ident,
                at,
                title.strip(),
                note.strip(),
                version,
                kind,
            )
        return str(ident)
