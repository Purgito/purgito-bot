"""Algoritmo de retención ORIGINAL (una consulta de elegibilidad por cohorte y horizonte).

Se conserva solo como referencia ejecutable: las pruebas exigen que el algoritmo
agrupado devuelva exactamente los mismos porcentajes y elegibilidad.
"""

from datetime import timedelta

from studio.model import ACTIVE_SOURCES


async def _retention_reference(c, start, end, params, now):
    # Mismo filtro de versión/función define la cohorte, no limita el retorno tras actualizar el bot.
    args = [
        start.date(),
        (end - timedelta(microseconds=1)).date(),
        params.get("version") or None,
        params.get("feature") or None,
        list(ACTIVE_SOURCES),
    ]
    out = []
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
        fields = []
        for days in (1, 7, 28):
            fields += [
                f"count(*) FILTER(WHERE EXISTS(SELECT 1 FROM studio_usage u WHERE u.guild_key=q.guild_key AND u.hour >= (q.day+{days})::timestamptz AND u.hour < (q.day+{days}+1)::timestamptz AND u.result='ok' AND u.source=ANY($5::text[]) AND ($4::text IS NULL OR u.feature=$4))) AS active_{days}",
                f"count(*) FILTER(WHERE EXISTS(SELECT 1 FROM studio_presence p WHERE p.guild_key=q.guild_key AND p.day=q.day+{days})) AS installed_{days}",
            ]
        rows = await c.fetch(
            f"""WITH q AS ({cohort}) SELECT q.day,count(*) AS size,{",".join(fields)} FROM q WHERE day >= $1 AND day <= $2 GROUP BY q.day ORDER BY q.day""",
            *args,
        )
        for row in rows:
            item = {
                "kind": kind,
                "day": row["day"].isoformat(),
                "size": row["size"],
                "horizons": [],
            }
            for days in (1, 7, 28):
                target = row["day"] + timedelta(days=days)
                eligible = target < now.date() and await c.fetchval(
                    """SELECT EXISTS(SELECT 1 FROM studio_inventory WHERE day=$1::date)
                  AND COALESCE((SELECT range_agg(tstzrange(started_at,flushed_until,'[)')) @> tstzrange($1::date::timestamptz,($1::date+1)::timestamptz,'[)') AND bool_and(dropped=0) FROM studio_sessions WHERE started_at < ($1::date+1)::timestamptz AND flushed_until > $1::date::timestamptz),FALSE)""",
                    target,
                )
                item["horizons"].append(
                    {
                        "days": days,
                        "eligible": bool(eligible),
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
