"""Lecturas consistentes y agregadas. Nunca devuelve claves de servidor."""

from datetime import timedelta

from .model import (
    ACTIVE_SOURCES,
    BOUNDS,
    COVERAGE_COMPLETE,
    COVERAGE_PARTIAL,
    FEATURES,
    parse_time,
    period,
    utcnow,
)

_HIST = ",".join(f"COALESCE(sum(histogram[{i}]),0)::bigint" for i in range(1, 12))
_STATS = f"""COALESCE(sum(n),0)::bigint AS uses,
 COALESCE(sum(n) FILTER(WHERE result='ok'),0)::bigint AS successes,
 COALESCE(sum(n) FILTER(WHERE result='error'),0)::bigint AS errors,
 COALESCE(sum(n) FILTER(WHERE result='rejected'),0)::bigint AS rejected,
 COALESCE(sum(n) FILTER(WHERE result='refused'),0)::bigint AS refused,
 count(DISTINCT guild_key) FILTER(WHERE result='ok' AND source=ANY($6::text[])) AS active,
 count(DISTINCT guild_key) FILTER(WHERE result='ok') AS served,
 COALESCE(sum(duration_n),0)::bigint AS samples,
 COALESCE(sum(duration_sum),0)::float8 AS duration_sum, ARRAY[{_HIST}] AS histogram"""


def stats(row):
    row = dict(row)
    hist = row.pop("histogram")
    total = row.pop("duration_sum")
    samples = row["samples"]
    row["mean_ms"] = round(total / samples, 2) if samples else None
    threshold = samples * 0.95
    cumulative = 0
    row["p95_ms_upper_bound"] = None
    row["p95_over_30000_ms"] = False
    if samples:
        for i, n in enumerate(hist):
            cumulative += n
            if cumulative >= threshold:
                if i < len(BOUNDS):
                    row["p95_ms_upper_bound"] = BOUNDS[i]
                else:
                    row["p95_over_30000_ms"] = True
                break
    attempted = row["successes"] + row["errors"]
    row["error_pct"] = round(100 * row["errors"] / attempted, 2) if attempted else None
    # Rechazos operativos de Discord sobre todo intento de entrega; no entran en error_pct.
    delivered = attempted + row["refused"]
    row["refused_pct"] = (
        round(100 * row["refused"] / delivered, 2) if delivered else None
    )
    return row


def coverage_status(ratio, dropped):
    """complete: >=99,5 % y sin descartes. partial: >=90 %. unavailable: el resto."""
    if ratio < COVERAGE_PARTIAL:
        return "unavailable"
    if ratio >= COVERAGE_COMPLETE and not dropped:
        return "complete"
    return "partial"


async def _coverage(c, start, end):
    """Cuantifica qué parte [start, end) tiene captura confirmada. No rellena huecos."""
    rows = await c.fetch(
        """WITH m AS (SELECT range_agg(tstzrange(started_at,flushed_until,'[)'))
             * tstzmultirange(tstzrange($1,$2,'[)')) AS r FROM studio_sessions
             WHERE started_at < $2 AND flushed_until > $1)
           SELECT lower(x) AS s, upper(x) AS e FROM m, unnest(m.r) AS x ORDER BY 1""",
        start,
        end,
    )
    dropped = await c.fetchval(
        "SELECT COALESCE(sum(dropped),0)::bigint FROM studio_sessions WHERE started_at < $2 AND flushed_until > $1",
        start,
        end,
    )
    gaps, position = [], start
    for row in rows:
        if row["s"] > position:
            gaps.append((position, row["s"]))
        position = max(position, row["e"])
    if position < end:
        gaps.append((position, end))
    window = (end - start).total_seconds()
    missing = sum((b - a).total_seconds() for a, b in gaps)
    ratio = round((window - missing) / window, 6) if window > 0 else 0.0
    return {
        "status": coverage_status(ratio, dropped),
        "ratio": ratio,
        "window_seconds": int(window),
        "covered_seconds": int(window - missing),
        "gap_count": len(gaps),
        "gap_seconds": int(missing),
        "longest_gap_seconds": int(max((b - a).total_seconds() for a, b in gaps))
        if gaps
        else 0,
        "gaps": [
            {"start": a, "end": b, "seconds": int((b - a).total_seconds())}
            for a, b in gaps[:20]
        ],
        "dropped": dropped,
    }


def compare(current, previous):
    """comparable: ambas completas. partial: ambas >=90 %, con sesgo declarado.
    not_comparable: cualquiera por debajo; no se calcula diferencia ni porcentaje."""
    a, b = current["coverage"], previous["coverage"]
    if "unavailable" in (a["status"], b["status"]):
        status = "not_comparable"
        reason = "Un período tiene menos del 90 % de cobertura confirmada."
    elif a["status"] == b["status"] == "complete":
        status, reason = "comparable", None
    else:
        status = "partial"
        reason = (
            "Parte de uno o ambos períodos no se midió (o hubo registros descartados): "
            "la variación compara solo lo observado y no es una estimación representativa."
        )
    return {
        "status": status,
        "reason": reason,
        "current_ratio": a["ratio"],
        "previous_ratio": b["ratio"],
    }


async def _window(c, start, end, params):
    args = [
        start,
        end,
        params.get("version") or None,
        params.get("feature") or None,
        params.get("result") or None,
        list(ACTIVE_SOURCES),
    ]
    where = "hour >= $1 AND hour < $2 AND ($3::text IS NULL OR version=$3) AND ($4::text IS NULL OR feature=$4) AND ($5::text IS NULL OR result=$5)"
    summary = stats(
        await c.fetchrow(f"SELECT {_STATS} FROM studio_usage WHERE {where}", *args)
    )

    async def grouped(column, limit):
        rows = await c.fetch(
            f"SELECT {column}, {_STATS} FROM studio_usage WHERE {where} GROUP BY {column} ORDER BY uses DESC LIMIT {limit}",
            *args,
        )
        return [stats(r) for r in rows]

    features = await grouped("feature", 50)
    commands = await grouped("command,source", 500)
    versions = await grouped("version", 100)
    daily = [
        stats(r)
        for r in await c.fetch(
            f"SELECT hour::date AS day,{_STATS} FROM studio_usage WHERE {where} GROUP BY hour::date ORDER BY day",
            *args,
        )
    ]
    for row in daily:
        row["day"] = row["day"].isoformat()
    # Ventanas cortas: una serie por horas (si no, 72 h serían solo 3-4 puntos).
    hourly = []
    if end - start <= timedelta(hours=72):
        hourly = [
            stats(r)
            for r in await c.fetch(
                f"SELECT hour AS at,{_STATS} FROM studio_usage WHERE {where} GROUP BY hour ORDER BY hour",
                *args,
            )
        ]
    denominator = await c.fetchval(
        """SELECT count(DISTINCT p.guild_key) FROM studio_presence p JOIN studio_inventory i USING(day)
      WHERE day >= $1::date AND day <= $2::date AND ($3::text IS NULL OR i.version=$3)""",
        start.date(),
        (end - timedelta(microseconds=1)).date(),
        params.get("version") or None,
    )
    coverage = await _coverage(c, start, end)
    for row in features:
        row["label"] = FEATURES.get(row["feature"], row["feature"])
        row["adoption_pct"] = (
            round(100 * row["served"] / denominator, 2)
            if denominator and row["served"] <= denominator
            else None
        )
    return {
        "summary": summary,
        "features": features,
        "commands": [r for r in commands if r["command"]],
        "versions": versions,
        "daily": daily,
        "hourly": hourly,
        "observed_communities": denominator,
        "coverage": coverage,
        "coverage_complete": coverage["status"] == "complete",
    }


_ELIGIBLE = """SELECT d AS day,
  EXISTS(SELECT 1 FROM studio_inventory WHERE day=d)
  AND COALESCE((SELECT range_agg(tstzrange(started_at,flushed_until,'[)')) @> tstzrange(d::timestamptz,(d+1)::timestamptz,'[)') AND bool_and(dropped=0)
     FROM studio_sessions WHERE started_at < (d+1)::timestamptz AND flushed_until > d::timestamptz),FALSE) AS ok
  FROM unnest($1::date[]) AS t(d)"""


async def _retention(c, start, end, params, now, observed_since=None):
    """Tres consultas en total (dos cohortes y una elegibilidad para todos los días objetivo)."""
    # Mismo filtro de versión/función define la cohorte, no limita el retorno tras actualizar el bot.
    args = [
        start.date(),
        (end - timedelta(microseconds=1)).date(),
        params.get("version") or None,
        params.get("feature") or None,
        list(ACTIVE_SOURCES),
    ]
    found = []
    for kind, cohort in [
        (
            "activity",
            "SELECT guild_key,min(hour)::date AS day FROM studio_usage WHERE result='ok' AND source=ANY($5::text[]) AND ($3::text IS NULL OR version=$3) AND ($4::text IS NULL OR feature=$4) GROUP BY guild_key",
        ),
        (
            "installation",
            "SELECT guild_key,min(at)::date AS day FROM studio_lifecycle WHERE action='join' AND ($3::text IS NULL OR version=$3) GROUP BY guild_key",
        ),
    ]:
        fields = [
            "count(*) FILTER(WHERE EXISTS(SELECT 1 FROM studio_lifecycle l WHERE l.guild_key=q.guild_key AND l.action='join')) AS joined_observed"
        ]
        for days in (1, 7, 28):
            fields += [
                f"count(*) FILTER(WHERE EXISTS(SELECT 1 FROM studio_usage u WHERE u.guild_key=q.guild_key AND u.hour >= (q.day+{days})::timestamptz AND u.hour < (q.day+{days}+1)::timestamptz AND u.result='ok' AND u.source=ANY($5::text[]) AND ($4::text IS NULL OR u.feature=$4))) AS active_{days}",
                f"count(*) FILTER(WHERE EXISTS(SELECT 1 FROM studio_presence p WHERE p.guild_key=q.guild_key AND p.day=q.day+{days})) AS installed_{days}",
            ]
        rows = await c.fetch(
            f"""WITH q AS ({cohort}) SELECT q.day,count(*) AS size,{",".join(fields)} FROM q WHERE day >= $1 AND day <= $2 GROUP BY q.day ORDER BY q.day""",
            *args,
        )
        found.append((kind, rows))
    targets = sorted(
        {
            row["day"] + timedelta(days=days)
            for _, rows in found
            for row in rows
            for days in (1, 7, 28)
            if row["day"] + timedelta(days=days) < now.date()
        }
    )
    mature = (
        {r["day"]: r["ok"] for r in await c.fetch(_ELIGIBLE, targets)}
        if targets
        else {}
    )
    out = []
    for kind, rows in found:
        for row in rows:
            item = {
                "kind": kind,
                "day": row["day"].isoformat(),
                "size": row["size"],
                "horizons": [],
            }
            if kind == "activity":
                # Primera actividad observada no es incorporación del bot. La entrada
                # solo es verificable si hay un guild_join retenido; en la línea base
                # (inicio de la medición o límite de retención) no se sabe cuándo empezó.
                item["baseline"] = bool(
                    observed_since and row["day"] <= observed_since.date()
                )
                item["joined_observed"] = row["joined_observed"]
            for days in (1, 7, 28):
                target = row["day"] + timedelta(days=days)
                eligible = bool(mature.get(target))
                item["horizons"].append(
                    {
                        "days": days,
                        "eligible": eligible,
                        "active_pct": round(
                            100 * row[f"active_{days}"] / row["size"], 2
                        )
                        if eligible
                        else None,
                        "installed_pct": round(
                            100 * row[f"installed_{days}"] / row["size"], 2
                        )
                        if eligible
                        else None,
                        "reason": None
                        if eligible
                        else "Día aún no maduro o sin cobertura completa e inventario",
                    }
                )
            out.append(item)
    return out


async def report(store, params, catalog=None, now=None):
    now = now or utcnow()
    start, end, cstart, cend = period(params, now)
    async with (
        store.pool.acquire(timeout=3) as c,
        c.transaction(isolation="repeatable_read", readonly=True),
    ):
        await c.execute("SET LOCAL statement_timeout = '5s'")
        await c.execute("SET LOCAL TIME ZONE 'UTC'")
        current = await _window(c, start, end, params)
        previous = await _window(c, cstart, cend, params)
        inventory = [
            dict(r)
            for r in await c.fetch(
                "SELECT day,observed_at,installed,version FROM studio_inventory WHERE day >= $1 AND day <= $2 AND ($3::text IS NULL OR version=$3) ORDER BY day",
                start.date(),
                (end - timedelta(microseconds=1)).date(),
                params.get("version") or None,
            )
        ]
        growth = [
            dict(r)
            for r in await c.fetch(
                """SELECT at::date AS day,action,count(*)::int AS n FROM studio_lifecycle WHERE at >= $1 AND at < $2 AND ($3::text IS NULL OR version=$3) GROUP BY at::date,action ORDER BY day""",
                start,
                end,
                params.get("version") or None,
            )
        ]
        latest = await c.fetchrow(
            "SELECT installed,observed_at,version FROM studio_inventory ORDER BY observed_at DESC LIMIT 1"
        )
        notes = [
            dict(r)
            for r in await c.fetch(
                "SELECT * FROM studio_annotations WHERE at >= $1 AND at <= $2 ORDER BY at",
                start,
                # Hasta ahora, no hasta el fin de la ventana: una nota guardada hoy debe verse aunque
                # el período termine en la medianoche anterior. Nunca hay notas futuras (se validan al crear).
                max(now, parse_time(params["end"])) if params.get("end") else now,
            )
        ]
        versions = [
            r[0]
            for r in await c.fetch(
                "SELECT DISTINCT version FROM studio_sessions ORDER BY version"
            )
        ]
        first = await c.fetchval("SELECT min(started_at) FROM studio_sessions")
        # Antes de esta fecha no hay datos: o no existía la medición o expiró por retención.
        observed_since = (
            max(first, now - timedelta(days=store.settings.retention_days))
            if first
            else None
        )
        cohorts = await _retention(c, start, end, params, now, observed_since)
    comparison = compare(current, previous)
    delta = {}
    for key in ("uses", "active", "errors", "successes", "refused"):
        a, b = current["summary"][key], previous["summary"][key]
        delta[key] = (
            {
                "difference": a - b,
                "pct": round(100 * (a - b) / b, 2) if b else None,
                "status": comparison["status"],
            }
            if comparison["status"] != "not_comparable"
            else None
        )
    command_features = set((catalog or {}).values())
    delivery_features = {"chat", "gifs", "memes", "youtube", "twitch", "rss"}
    for row in current["features"]:
        row["coverage"] = (
            "commands_and_deliveries"
            if row["feature"] in delivery_features
            and row["feature"] in command_features
            else "deliveries"
            if row["feature"] in delivery_features
            else "commands"
            if row["feature"] in command_features
            else "explicit_events"
        )
    seen = {r["feature"] for r in current["features"]}
    current["features"] += [
        {
            "feature": f,
            "label": name,
            "uses": 0,
            "active": 0,
            "served": 0,
            "successes": 0,
            "errors": 0,
            "rejected": 0,
            "refused": 0,
            "adoption_pct": 0
            if current["observed_communities"] and current["coverage_complete"]
            else None,
            "mean_ms": None,
        }
        for f, name in FEATURES.items()
        if f not in seen and (not params.get("feature") or f == params["feature"])
    ]
    for row in current["features"]:
        if "coverage" not in row:
            row["coverage"] = (
                "deliveries"
                if row["feature"] in delivery_features
                else "commands"
                if row["feature"] in command_features
                else "not_instrumented"
            )
            if row["coverage"] == "not_instrumented":
                row.update(
                    uses=None,
                    active=None,
                    served=None,
                    successes=None,
                    errors=None,
                    rejected=None,
                    refused=None,
                    adoption_pct=None,
                )
    previous_features = {row["feature"]: row for row in previous["features"]}
    for row in current["features"]:
        old = previous_features.get(row["feature"])
        base = (
            old["adoption_pct"]
            if old
            else 0
            if previous["coverage_complete"] and previous["observed_communities"]
            else None
        )
        comparable = (
            comparison["status"] != "not_comparable"
            and row["adoption_pct"] is not None
            and base is not None
        )
        row["previous_adoption_pct"] = base if comparable else None
        row["adoption_change_pp"] = (
            round(row["adoption_pct"] - base, 2) if comparable else None
        )
    return {
        "generated_at": now,
        "period": {
            "start": start,
            "end": end,
            "compare_start": cstart,
            "compare_end": cend,
        },
        "current": current,
        "previous": previous,
        "delta": delta,
        "comparison": comparison,
        "observed_since": observed_since,
        "inventory": inventory,
        "latest_inventory": dict(latest) if latest else None,
        "growth": growth,
        "retention": cohorts,
        "annotations": notes,
        "versions": versions,
        "catalog": [
            {"source": s, "command": cmd, "feature": f}
            for (s, cmd), f in (catalog or {}).items()
            if not params.get("feature") or f == params["feature"]
        ],
        "coverage_started_at": first,
        "definitions": {
            "installed": "Servidores presentes en un inventario completo observado. No equivale a actividad. El inventario inicial no cuenta como instalaciones nuevas.",
            "active": "Comunidades distintas con al menos un comando, mención o trigger terminado correctamente en el período. Excluye avisos de fondo y mensajes espontáneos.",
            "adoption": "Comunidades con una ejecución o entrega exitosa de la función (incluido fondo) / comunidades distintas observadas en inventarios de los días del período. No mide elegibilidad por permisos ni Premium.",
            "retention": "D1/D7/D28: actividad exitosa o presencia observada en el día UTC exacto después de la cohorte. Solo días maduros con cobertura continua e inventario. Primera actividad significa primera observada en los datos retenidos, no instalación ni primer uso de toda la vida: la cohorte de la línea base (inicio de la medición o límite de retención) agrupa servidores que ya existían, y solo las entradas con evento real verificado son incorporaciones comprobadas.",
            "errors": "Fallos de ejecución instrumentados / (éxitos + fallos). Se cuentan aparte, sin entrar en la tasa: rechazos de Discord (403/404 o el bot sin permiso: configuración del servidor, visibles y filtrables) y validaciones previas (permisos de quien invoca, argumentos, cooldown).",
            "latency": "Comandos: desde el hook previo hasta finalizar; entregas: tiempo del envío instrumentado. Media ponderada y límite superior aproximado del bucket p95. No mide todo el recorrido de Discord.",
            "coverage": "Sin datos no significa cero y los huecos nunca se rellenan. Cobertura = fracción del período con captura confirmada: completa (≥ 99,5 % y sin registros descartados), parcial (≥ 90 %) o insuficiente (< 90 %). Comparable: ambos períodos completos. Solo lo observado: ambos ≥ 90 % pero alguno parcial; lo observado es un mínimo del uso real, no se extrapola y no es una estimación representativa. Ninguna variación incluye prueba de significancia: son diferencias descriptivas. No comparable: alguno < 90 %, sin diferencia ni porcentaje. Los huecos se listan con su duración. Las métricas de crecimiento no usan el filtro de función.",
            "scope": "Comandos y adaptadores explícitos: no se leen conversaciones, ni se cuentan todas las líneas de logs como uso. Una función con cero registros no se declara ignorada fuera de esta cobertura.",
        },
    }
