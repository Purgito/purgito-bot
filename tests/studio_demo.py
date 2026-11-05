"""Datos SINTÉTICOS de desarrollo para ver y probar la interfaz. Nunca se usan en producción.

Escribe directamente en las tablas studio_* de una base de pruebas: un historial plausible con ciclo
diario, dos versiones, fallos y rechazos de Discord, un hueco de cobertura (un reinicio de 25 minutos),
entradas y salidas, e inventarios diarios.
"""

import random
import uuid
from datetime import timedelta

FEATURES = {
    "chat": (["", "", "ping"], ["mention", "spontaneous", "trigger"], 60),
    "gifs": (["gif", "gifs"], ["prefix", "slash", "spontaneous"], 14),
    "youtube": ([""], ["background"], 5),
    "general": (["ayuda", "ping", "info"], ["prefix", "slash"], 10),
    "download": (["descargar"], ["slash"], 4),
    "settings": (["config"], ["slash"], 3),
}
BOUNDS = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000)


def histogram(ms, n):
    bucket = next((i for i, b in enumerate(BOUNDS) if ms <= b), len(BOUNDS))
    hist = [0] * 11
    hist[bucket] = n
    return hist


async def seed_demo(conn, settings, now, days=21, guilds=140):
    rng = random.Random(2026)
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    keys = [settings.guild_key(1000 + i) for i in range(guilds)]
    v_old, v_new = "9a1c0f2", "7ee712b"
    switch = start + timedelta(days=days * 0.62)
    outage = (
        start + timedelta(days=days * 0.62, hours=-1),
        start + timedelta(days=days * 0.62, minutes=-35),
    )

    sessions = [(start, outage[0]), (outage[1], end + timedelta(minutes=2))]
    for n, (a, b) in enumerate(sessions):
        await conn.execute(
            "INSERT INTO studio_sessions(id,version,started_at,flushed_until,dropped,clean) VALUES($1,$2,$3,$4,0,$5)",
            uuid.UUID(int=900 + n),
            v_old if n == 0 else v_new,
            a,
            b,
            n == 0,
        )

    weights = [rng.random() ** 2 for _ in keys]  # pocas comunidades concentran el uso
    rows = []
    hour = start
    while hour < end:
        if outage[0] <= hour < outage[1]:
            hour += timedelta(hours=1)
            continue
        day_frac = (hour - start).total_seconds() / (days * 86400)
        wave = 0.35 + 0.65 * max(
            0.0, __import__("math").sin((hour.hour - 6) / 24 * 2 * 3.14159)
        )
        for _ in range(int(7 + 14 * wave + 10 * day_frac)):
            guild = rng.choices(range(guilds), weights)[0]
            if guild > 60 + day_frac * 70:  # el inventario crece con el tiempo
                continue
            feature = rng.choices(list(FEATURES), [FEATURES[f][2] for f in FEATURES])[0]
            commands, sources, _ = FEATURES[feature]
            source = rng.choice(sources)
            command = rng.choice(commands) if source in ("prefix", "slash") else ""
            roll = rng.random()
            result = (
                "ok"
                if roll < 0.955
                else "error"
                if roll < 0.968
                else "refused"
                if roll < 0.99
                else "rejected"
            )
            if feature == "download" and rng.random() < 0.12:
                result = "error"
            ms = rng.choice([18, 40, 80, 190, 420, 900, 2100]) * (
                3 if feature == "download" else 1
            )
            n = rng.randint(1, 4)
            rows.append(
                (
                    hour,
                    keys[guild],
                    feature,
                    command,
                    source,
                    result,
                    v_old if hour < switch else v_new,
                    n,
                    n,
                    float(ms * n),
                    histogram(ms, n),
                )
            )
        hour += timedelta(hours=1)
    merged = {}
    for r in rows:
        k = r[:7]
        if k in merged:
            m = merged[k]
            merged[k] = (
                *m[:7],
                m[7] + r[7],
                m[8] + r[8],
                m[9] + r[9],
                [a + b for a, b in zip(m[10], r[10])],
            )
        else:
            merged[k] = r
    await conn.executemany(
        "INSERT INTO studio_usage VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
        list(merged.values()),
    )

    day = start.replace(hour=0)
    for d in range(days + 1):
        present = int(62 + (d / max(1, days)) * 68)
        t = day + timedelta(days=d)
        if t > end:
            break
        await conn.execute(
            "INSERT INTO studio_inventory VALUES($1,$2,$3,$4)",
            t.date(),
            t + timedelta(hours=2),
            v_old if t < switch else v_new,
            present,
        )
        await conn.executemany(
            "INSERT INTO studio_presence VALUES($1,$2)",
            [(t.date(), k) for k in keys[:present]],
        )
    for d in range(1, days):
        for action, count in (
            ("join", rng.choice([0, 1, 2, 3])),
            ("leave", rng.choice([0, 0, 1])),
            ("rejoin", rng.choice([0, 0, 0, 1])),
        ):
            for _ in range(count):
                await conn.execute(
                    "INSERT INTO studio_lifecycle(id,at,guild_key,action,version) VALUES($1,$2,$3,$4,$5)",
                    uuid.uuid4(),
                    day + timedelta(days=d, hours=rng.randrange(24)),
                    rng.choice(keys),
                    action,
                    v_old if d < days * 0.62 else v_new,
                )
    notes = [
        (
            start + timedelta(days=2, hours=9),
            "Primer despliegue medido",
            "Studio empieza a registrar uso.",
            v_old,
            "release",
        ),
        (
            switch - timedelta(hours=1),
            "Despliegue 7ee712b",
            "Dependencias actualizadas y avisos de lifecycle eliminados.",
            v_new,
            "release",
        ),
        (
            start + timedelta(days=days * 0.8),
            "Cambio en el límite de GIFs",
            "Sube el máximo gratuito de GIFs por servidor.",
            "",
            "change",
        ),
    ]
    for at, title, note, version, kind in notes:
        await conn.execute(
            "INSERT INTO studio_annotations VALUES($1,$2,$3,$4,$5,$6)",
            uuid.uuid4(),
            at,
            title,
            note,
            version,
            kind,
        )
    return {"start": start, "end": end, "outage": outage, "switch": switch}
