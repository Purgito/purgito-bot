"""PostgreSQL real, callbacks sin red de Discord y acceso privado extremo a extremo."""

import asyncio
from datetime import timedelta
import json
import math
from types import SimpleNamespace
import uuid

import asyncpg
from aiohttp import BasicAuth, web
from aiohttp.test_utils import TestClient, TestServer
import pytest

import pg_support
from studio import runtime
from studio.http import register, encode
from studio.local_server import application
from studio.model import Settings, period, utcnow
from studio.report import report
from studio.runtime import Collector
from studio.store import Store
from observability.runtime import internal_access

KEY = "studio-test-only-hmac-key-0123456789abcdef"
TOKEN = "studio-test-only-observability-token"


@pytest.fixture
def backend():
    database = asyncio.run(pg_support.connect())
    settings = Settings(enabled=True, key=KEY, version="v1")
    store = Store(database, settings)
    yield store, settings
    asyncio.run(database.close())


def setup(store, settings, at):
    clock = [at]
    collector = Collector(store, settings, clock=lambda: clock[0])
    asyncio.run(store.start(collector.session_id, at))
    return collector, clock


def test_private_aggregates_idempotence_restart_and_key_safety(backend):
    store, settings = backend
    at = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(days=2)
    c, clock = setup(store, settings, at)
    c.observe_inventory([123456789123456789, 2])
    assert c.record(123456789123456789, "chat", source="mention", duration_ms=37)
    assert c.record(123456789123456789, "chat", source="mention", duration_ms=120)
    assert not c.record(1, "content of a message", source="mention")
    assert not c.record(1, "chat", command="x" * 200)
    c.membership(2, "join")
    c.membership(2, "join")
    c.membership(2, "leave")
    c.membership(2, "join")
    clock[0] += timedelta(hours=1)
    assert asyncio.run(c.flush())
    batch = {
        "id": uuid.uuid4(),
        "at": clock[0],
        "usage": {},
        "lifecycle": [],
        "inventory": None,
    }
    asyncio.run(store.write(batch, c.session_id))
    asyncio.run(store.write(batch, c.session_id))

    async def check():
        async with store.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM studio_usage")
            assert row["n"] == 2 and row["duration_n"] == 2
            assert row["duration_sum"] == 157
            assert sum(row["histogram"]) == 2
            assert row["guild_key"] == settings.guild_key(123456789123456789)
            assert "123456789123456789" not in str(dict(row))
            assert await conn.fetchval("SELECT count(*) FROM studio_lifecycle") == 3
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM studio_lifecycle WHERE action='rejoin'"
                )
                == 1
            )
            assert await conn.fetchval("SELECT installed FROM studio_inventory") == 2
        # Reabrir con un pool real nuevo: no usar el fixture que trunca al conectar.
        pool = await asyncpg.create_pool(pg_support.TEST_URL, min_size=1, max_size=2)
        try:
            reopened = Store(SimpleNamespace(pool=pool), settings)
            await reopened.start(uuid.uuid4(), clock[0])
            async with pool.acquire() as conn:
                assert await conn.fetchval("SELECT sum(n) FROM studio_usage") == 2
            with pytest.raises(ValueError, match="cambió"):
                await Store(
                    SimpleNamespace(pool=pool), Settings(enabled=True, key="x" * 32)
                ).start(uuid.uuid4(), clock[0])
        finally:
            await pool.close()

    asyncio.run(check())


def test_retry_after_commit_does_not_duplicate(backend):
    store, settings = backend
    at = utcnow() - timedelta(days=1)
    c, clock = setup(store, settings, at)
    c.record(1, "general", source="slash", command="help")
    real = store.write
    first = [True]

    async def ambiguous(*args):
        await real(*args)
        if first[0]:
            first[0] = False
            raise ConnectionError("commit confirmado en DB, respuesta perdida")

    store.write = ambiguous
    assert not asyncio.run(c.flush())
    assert c.inflight
    c.record(1, "general", source="slash", command="help")
    assert asyncio.run(c.flush())
    assert asyncio.run(c.flush())

    async def count():
        async with store.pool.acquire() as conn:
            return await conn.fetchval("SELECT sum(n) FROM studio_usage")

    assert asyncio.run(count()) == 2


def test_retention_cohorts_comparisons_versions_and_no_invented_history(backend):
    store, settings = backend
    day = (utcnow() - timedelta(days=10)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    c, clock = setup(store, settings, day - timedelta(seconds=1))
    clock[0] = day + timedelta(hours=1)
    c.observe_inventory([1, 2])
    for gid in (1, 2):
        c.membership(gid, "join")
        c.record(gid, "chat", source="mention", duration_ms=20)
    assert asyncio.run(c.flush())
    # Día 7: el retorno puede ocurrir con una versión nueva.
    newer = Settings(enabled=True, key=KEY, version="v2")
    c2, clock2 = setup(store, newer, day + timedelta(days=7))
    clock2[0] = day + timedelta(days=7, hours=1)
    c2.record(1, "chat", source="mention")
    c2.record(2, "youtube", source="background")
    c2.observe_inventory([1])
    assert asyncio.run(c2.flush())
    clock[0] = utcnow()
    assert asyncio.run(c.flush())
    params = {
        "start": day.isoformat(),
        "end": (day + timedelta(days=1)).isoformat(),
        "version": "v1",
    }
    result = asyncio.run(report(store, params, now=utcnow()))
    assert result["current"]["summary"]["active"] == 2
    assert result["current"]["summary"]["uses"] == 2
    assert result["delta"]["uses"] is None, (
        "sin cobertura anterior no se inventa crecimiento"
    )
    assert result["latest_inventory"]["installed"] == 1
    assert len(result["growth"]) == 1
    assert result["growth"][0]["n"] == 2
    cohort = next(r for r in result["retention"] if r["kind"] == "activity")
    d7 = next(h for h in cohort["horizons"] if h["days"] == 7)
    assert d7["eligible"] and d7["active_pct"] == 50 and d7["installed_pct"] == 50
    d28 = next(h for h in cohort["horizons"] if h["days"] == 28)
    assert not d28["eligible"] and d28["active_pct"] is None
    encoded = json.dumps(result, default=encode)
    assert settings.guild_key(1) not in encoded
    assert "guild_key" not in encoded


def test_cleanup_bounds_and_graceful_shutdown(backend):
    store, settings = backend
    at = utcnow() - timedelta(days=100)
    c, clock = setup(store, settings, at)
    c.record(1, "chat")
    c.membership(1, "join")
    c.observe_inventory([1])
    assert asyncio.run(c.flush())
    asyncio.run(store.cleanup())

    async def count():
        async with store.pool.acquire() as conn:
            for table in (
                "studio_usage",
                "studio_lifecycle",
                "studio_inventory",
                "studio_presence",
                "studio_batches",
                "studio_sessions",
            ):
                assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0

    asyncio.run(count())
    c, clock = setup(store, settings, utcnow())
    c.record(1, "chat")
    assert asyncio.run(c.stop())

    async def stopped():
        async with store.pool.acquire() as conn:
            assert await conn.fetchval(
                "SELECT clean FROM studio_sessions WHERE id=$1", c.session_id
            )
            assert await conn.fetchval("SELECT sum(n) FROM studio_usage") == 1

    asyncio.run(stopped())
    tiny = Collector(store, Settings(enabled=True, key=KEY, max_pending=1))
    tiny.record(1, "chat")
    assert not tiny.record(2, "chat")
    assert tiny.dropped == 1
    assert tiny.record(1, "chat", duration_ms=math.nan)


def test_private_http_and_companion_ui(backend, monkeypatch):
    store, settings = backend
    c, clock = setup(store, settings, utcnow() - timedelta(days=1))
    monkeypatch.setattr(runtime, "_current", c)

    async def run():
        app = web.Application()
        register(
            app,
            lambda req: (
                None
                if internal_access(req.headers, TOKEN) == "ok"
                else web.json_response(
                    {"error": "denied"},
                    status=404
                    if any(
                        h in req.headers
                        for h in (
                            "Forwarded",
                            "X-Forwarded-For",
                            "CF-Connecting-IP",
                            "X-Real-IP",
                        )
                    )
                    else 401,
                )
            ),
        )
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/internal/studio/report")).status == 401
            auth = {"Authorization": f"Bearer {TOKEN}"}
            assert (
                await client.get("/internal/studio/report", headers=auth)
            ).status == 200
            assert (
                await client.get(
                    "/internal/studio/report",
                    headers={**auth, "Host": "public.example"},
                )
            ).status == 404
            for proxy in (
                "Forwarded",
                "X-Forwarded-For",
                "CF-Connecting-IP",
                "X-Real-IP",
            ):
                assert (
                    await client.get(
                        "/internal/studio/report", headers={**auth, proxy: "127.0.0.1"}
                    )
                ).status == 404
            assert (
                await client.get(
                    "/internal/studio/report?feature=unknown", headers=auth
                )
            ).status == 400
            assert (
                await client.post(
                    "/internal/studio/annotations",
                    json={"at": utcnow().isoformat(), "title": "sin autorización"},
                )
            ).status == 401
            response = await client.post(
                "/internal/studio/annotations",
                headers=auth,
                json={
                    "at": (utcnow() - timedelta(minutes=1)).isoformat(),
                    "title": "Release <script>",
                    "note": "No se interpreta HTML",
                    "version": "v1",
                },
            )
            assert response.status == 201
            report_response = await (
                await client.get("/internal/studio/report", headers=auth)
            ).json()
            assert report_response["annotations"][0]["title"] == "Release <script>"
            assert report_response["current"]["summary"]["uses"] == 0
            # Backend real y companion sobre socket loopback; no credenciales de Discord.
            companion = application(TOKEN, backend_port=client.server.port)
            async with TestClient(TestServer(companion)) as ui:
                host = {"Host": "127.0.0.1:18081"}
                assert (await ui.get("/", headers=host)).status == 401
                valid = {**host, "Authorization": BasicAuth("admin", TOKEN).encode()}
                page = await ui.get("/", headers=valid)
                assert page.status == 200
                assert "Purgito Studio" in await page.text()
                assert (
                    "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
                )
                assert (
                    await ui.get("/internal/studio/report", headers=valid)
                ).status == 200
                for asset in (
                    "/js/main.mjs",
                    "/css/studio.css",
                    "/fonts/outfit-latin.woff2",
                    "/favicon.svg",
                ):
                    assert (await ui.get(asset, headers=valid)).status == 200, asset
                assert (
                    await ui.get(
                        "/js/main.mjs",
                        headers={**valid, "Origin": "https://evil.example"},
                    )
                ).status == 403
                assert (
                    await ui.post(
                        "/internal/studio/annotations", headers=valid, json={}
                    )
                ).status == 403

    asyncio.run(run())


def test_period_contract():
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    a, b, c, d = period({}, now)
    assert b - a == d - c == timedelta(days=28)
    with pytest.raises(ValueError):
        period({"start": (now - timedelta(days=91)).isoformat()}, now)
    with pytest.raises(ValueError):
        period({"start": "2026-01-01T00:00:00"}, now)


def test_command_adapters_rejections_deduplication_and_deliveries(backend, monkeypatch):
    import discord
    from discord import app_commands
    from discord.ext import commands
    import db

    store, settings = backend
    monkeypatch.setenv("STUDIO_ENABLED", "true")
    monkeypatch.setenv("STUDIO_HMAC_KEY", KEY)
    monkeypatch.setenv("STUDIO_VERSION", "adapter-test")
    monkeypatch.setattr(runtime, "_current", None)

    async def get_database():
        return SimpleNamespace(pool=store.pool)

    monkeypatch.setattr(db, "get_db", get_database)

    async def callback(ctx):
        return None

    callback.__module__ = "cogs.general"

    async def slash_callback(interaction: discord.Interaction):
        return None

    slash_callback.__module__ = "cogs.chat"

    async def run():
        bot = commands.Bot(
            command_prefix="!",
            intents=discord.Intents.none(),
            tree_cls=runtime.StudioTree,
        )
        command = commands.Command(callback, name="ping")
        bot.add_command(command)
        slash = app_commands.Command(
            name="generar", description="test", callback=slash_callback
        )
        bot.tree.add_command(slash)
        await runtime.start(bot)
        collector = runtime.get()
        assert collector and ("prefix", "ping") in collector.catalog
        collector.observe_inventory([1, 2])
        ctx = SimpleNamespace(command=command, guild=SimpleNamespace(id=1))
        await bot._before_invoke(ctx)
        await bot.extra_events["on_command_completion"][0](ctx)
        await bot.extra_events["on_command_completion"][0](ctx)
        interaction = SimpleNamespace(
            command=slash, guild=SimpleNamespace(id=2), extras={}
        )
        await bot.tree.interaction_check(interaction)
        runtime.finish_command(
            interaction,
            error=app_commands.MissingPermissions(["manage_guild"]),
            slash=True,
        )
        with pytest.raises(RuntimeError):
            with runtime.measure_delivery(1, "youtube", source="background"):
                raise RuntimeError("contenido privado que nunca se almacena")
        with runtime.measure_delivery(1, "rss", source="trigger"):
            pass
        await runtime.stop()
        async with store.pool.acquire() as conn:
            assert await conn.fetchval("SELECT sum(n) FROM studio_usage") == 4
            assert (
                await conn.fetchval(
                    "SELECT sum(n) FROM studio_usage WHERE result='rejected'"
                )
                == 1
            )
            assert (
                await conn.fetchval(
                    "SELECT sum(n) FROM studio_usage WHERE result='error'"
                )
                == 1
            )
            assert await conn.fetchval("SELECT count(*) FROM studio_lifecycle") == 0, (
                "inventario inicial no simula instalaciones"
            )
            assert "contenido privado" not in str(
                await conn.fetch("SELECT * FROM studio_usage")
            )
        await bot.close()

    asyncio.run(run())


def test_filters_latency_and_complete_period_delta(backend):
    store, settings = backend
    start = (utcnow() - timedelta(days=3)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    c, clock = setup(store, settings, start - timedelta(days=1))
    clock[0] = start - timedelta(hours=1)
    c.record(1, "general", source="prefix", command="ping", duration_ms=25, count=2)
    assert asyncio.run(c.flush())
    clock[0] = start + timedelta(hours=1)
    c.observe_inventory([1, 2])
    c.record(1, "general", source="prefix", command="ping", duration_ms=100, count=3)
    c.record(2, "chat", source="spontaneous", duration_ms=2000)
    c.record(2, "chat", source="mention", result="error")
    clock[0] = start + timedelta(days=1)
    assert asyncio.run(c.flush())
    params = {
        "start": start.isoformat(),
        "end": clock[0].isoformat(),
        "feature": "general",
        "version": "v1",
    }
    r = asyncio.run(report(store, params, now=utcnow()))
    assert r["current"]["summary"]["uses"] == 3
    assert r["current"]["summary"]["mean_ms"] == 100
    assert r["current"]["summary"]["p95_ms_upper_bound"] == 100
    assert r["current"]["summary"]["active"] == 1
    assert r["delta"]["uses"] == {
        "difference": 1,
        "pct": 50.0,
        "status": "comparable",
    }
    assert [f["feature"] for f in r["current"]["features"]] == ["general"]
    automated = dict(params, feature="chat")
    row = asyncio.run(report(store, automated, now=utcnow()))["current"]["features"][0]
    assert row["served"] == 1 and row["active"] == 0
    assert row["adoption_pct"] == 50.0
    params["result"] = "error"
    assert (
        asyncio.run(report(store, params, now=utcnow()))["current"]["summary"]["uses"]
        == 0
    )


def test_committed_batch_survives_abrupt_process_exit(backend):
    """Proceso distinto muere sin stop(): lo confirmado sigue en PostgreSQL."""
    import os
    import subprocess
    import sys

    store, settings = backend
    child = """
import asyncio, os
from types import SimpleNamespace
import asyncpg
from studio.model import Settings, utcnow
from studio.runtime import Collector
from studio.store import Store
async def main():
    pool = await asyncpg.create_pool(os.environ["STUDIO_TEST_DATABASE_URL"], min_size=1, max_size=1)
    settings = Settings(enabled=True, key=os.environ["STUDIO_TEST_KEY"], version="restart-test")
    store = Store(SimpleNamespace(pool=pool), settings)
    collector = Collector(store, settings)
    await store.start(collector.session_id, utcnow())
    collector.record(42, "general", source="slash", command="help")
    assert await collector.flush()
    os._exit(23)
asyncio.run(main())
"""
    env = dict(os.environ)
    env["STUDIO_TEST_DATABASE_URL"] = pg_support.TEST_URL
    env["STUDIO_TEST_KEY"] = settings.key
    from pathlib import Path

    env["PYTHONPATH"] = str(Path(runtime.__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", child], env=env, capture_output=True, timeout=20
    )
    assert result.returncode == 23, result.stderr.decode()

    async def check():
        async with store.pool.acquire() as conn:
            assert await conn.fetchval("SELECT sum(n) FROM studio_usage") == 1
            assert await conn.fetchval("SELECT count(*) FROM studio_batches") == 1
            assert not await conn.fetchval("SELECT clean FROM studio_sessions")

    asyncio.run(check())


def test_gateway_disconnect_censors_coverage_instead_of_inventing_zero(backend):
    store, settings = backend
    at = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(days=3)
    c, clock = setup(store, settings, at)
    ready = [False]
    c.bot = SimpleNamespace(is_ready=lambda: ready[0], guilds=[])
    clock[0] += timedelta(hours=1)
    assert asyncio.run(c.sample())
    ready[0] = True
    assert asyncio.run(c.sample())
    clock[0] += timedelta(hours=1)
    assert asyncio.run(c.sample())
    ready[0] = False
    clock[0] += timedelta(hours=1)
    assert asyncio.run(c.sample())
    ready[0] = True
    clock[0] += timedelta(hours=1)
    assert asyncio.run(c.sample())
    clock[0] += timedelta(hours=1)
    assert asyncio.run(c.sample())

    async def check():
        async with store.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT started_at,flushed_until FROM studio_sessions ORDER BY started_at"
            )
            assert [(r["started_at"], r["flushed_until"]) for r in rows] == [
                (at, at),
                (at + timedelta(hours=1), at + timedelta(hours=2)),
                (at + timedelta(hours=4), at + timedelta(hours=5)),
            ]

    asyncio.run(check())


def test_idle_flushes_do_not_churn_ledger_or_presence(backend):
    store, settings = backend
    at = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    c, clock = setup(store, settings, at)
    guilds = [SimpleNamespace(id=n) for n in (11, 22, 33)]
    c.bot = SimpleNamespace(is_ready=lambda: True, guilds=guilds)

    async def counts():
        async with store.pool.acquire() as conn:
            return (
                await conn.fetchval("SELECT count(*) FROM studio_batches"),
                await conn.fetchval("SELECT count(*) FROM studio_presence"),
                await conn.fetchval(
                    "SELECT max(xmin::text::bigint) FROM studio_presence"
                ),
                await conn.fetchval("SELECT max(flushed_until) FROM studio_sessions"),
            )

    clock[0] += timedelta(minutes=1)
    assert asyncio.run(c.sample())
    first = asyncio.run(counts())
    for _ in range(20):  # 20 ciclos de 10 s sin ningún evento ni cambio de inventario
        clock[0] += timedelta(seconds=10)
        assert asyncio.run(c.sample())
    batches, presence, xmin, covered = asyncio.run(counts())
    assert (batches, presence, xmin) == first[:3]  # sin ledger ni filas reescritas
    assert covered == clock[0]  # pero la cobertura sí avanza

    guilds.append(SimpleNamespace(id=44))  # un cambio real sí se registra
    clock[0] += timedelta(seconds=10)
    assert asyncio.run(c.sample())
    assert asyncio.run(counts())[1] == 4


# ---------------------------------------------------------------- retención agrupada


class CountingConnection:
    """Cuenta los viajes a PostgreSQL de una conexión real."""

    def __init__(self, conn):
        self.conn, self.queries = conn, 0

    def __getattr__(self, name):
        target = getattr(self.conn, name)
        if name not in {"fetch", "fetchval", "fetchrow", "execute"}:
            return target

        async def counted(*args, **kwargs):
            self.queries += 1
            return await target(*args, **kwargs)

        return counted


async def seed_history(conn, settings, now, days=75, guilds=36):
    """Historia determinista con casos límite: huecos, descartes, días sin inventario."""
    import random

    rng = random.Random(7)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first = today - timedelta(days=days)
    sessions = [  # (inicio, fin, descartes)
        (first, first + timedelta(days=22), 0),
        (
            first + timedelta(days=22, hours=6),
            first + timedelta(days=44),
            0,
        ),  # hueco 6 h
        (first + timedelta(days=45), first + timedelta(days=58), 5),  # con descartes
        (first + timedelta(days=58), now, 0),
    ]
    for n, (a, b, dropped) in enumerate(sessions):
        await conn.execute(
            "INSERT INTO studio_sessions(id,version,started_at,flushed_until,dropped) VALUES($1,'v1',$2,$3,$4)",
            uuid.UUID(int=n + 1),
            a,
            b,
            dropped,
        )
    keys = [settings.guild_key(g) for g in range(1, guilds + 1)]
    for d in range(days):
        day = first + timedelta(days=d)
        if d == 30:  # día sin inventario
            continue
        present = [k for i, k in enumerate(keys) if i < 8 + d // 2]
        await conn.execute(
            "INSERT INTO studio_inventory VALUES($1,$2,'v1',$3)",
            day.date(),
            day + timedelta(hours=1),
            len(present),
        )
        await conn.executemany(
            "INSERT INTO studio_presence VALUES($1,$2)",
            [(day.date(), k) for k in present],
        )
        for i, key in enumerate(present):
            if rng.random() < 0.45:  # los inactivos quedan sin filas de uso
                source = rng.choice(["mention", "slash", "background", "spontaneous"])
                feature = rng.choice(["chat", "gifs", "youtube"])
                await conn.execute(
                    "INSERT INTO studio_usage VALUES($1,$2,$3,'',$4,$5,$6,1,0,0,$7)",
                    day + timedelta(hours=rng.randrange(24)),
                    key,
                    feature,
                    source,
                    rng.choice(["ok", "ok", "ok", "error"]),
                    rng.choice(["v1", "v1", "v2"]),
                    [0] * 11,
                )
            if i % 5 == 0 and d == i:  # entradas reales repartidas en el tiempo
                await conn.execute(
                    "INSERT INTO studio_lifecycle(id,at,guild_key,action,version) VALUES($1,$2,$3,'join','v1')",
                    uuid.uuid4(),
                    day + timedelta(hours=2),
                    key,
                )


def strip_new_fields(rows):
    return [
        {k: v for k, v in r.items() if k not in {"baseline", "joined_observed"}}
        for r in rows
    ]


def test_grouped_retention_matches_original_algorithm_with_far_fewer_queries(backend):
    import time
    from studio import report as report_module
    from studio_retention_reference import _retention_reference

    store, settings = backend
    now = utcnow()

    async def run():
        async with store.pool.acquire() as raw:
            await seed_history(raw, settings, now)
        cases = [
            {},
            {"version": "v1"},
            {"version": "v2", "feature": "chat"},
            {"feature": "youtube"},
        ]
        windows = [  # incluye el límite de retención de 90 días y ventanas cortas
            (now - timedelta(days=75), now),
            (now - timedelta(days=30), now - timedelta(days=2)),
            (now - timedelta(days=75), now - timedelta(days=60)),
            (now - timedelta(days=1), now),
        ]
        old_queries = new_queries = 0
        old_time = new_time = 0.0
        compared = eligible_seen = ineligible_seen = 0
        for params in cases:
            for start, end in windows:
                start = start.replace(minute=0, second=0, microsecond=0)
                end = end.replace(minute=0, second=0, microsecond=0)
                async with store.pool.acquire() as raw:
                    async with raw.transaction(
                        isolation="repeatable_read", readonly=True
                    ):
                        await raw.execute("SET LOCAL TIME ZONE 'UTC'")
                        old, new = CountingConnection(raw), CountingConnection(raw)
                        t = time.perf_counter()
                        expected = await _retention_reference(
                            old, start, end, params, now
                        )
                        old_time += time.perf_counter() - t
                        t = time.perf_counter()
                        actual = await report_module._retention(
                            new, start, end, params, now
                        )
                        new_time += time.perf_counter() - t
                assert strip_new_fields(actual) == expected, (params, start, end)
                old_queries += old.queries
                new_queries += new.queries
                assert new.queries <= 3
                compared += len(expected)
                for item in expected:
                    for h in item["horizons"]:
                        eligible_seen += h["eligible"]
                        ineligible_seen += not h["eligible"]
        return (
            old_queries,
            new_queries,
            old_time,
            new_time,
            compared,
            eligible_seen,
            ineligible_seen,
        )

    oq, nq, ot, nt, compared, ok, not_ok = asyncio.run(run())
    assert compared > 100 and ok > 50 and not_ok > 50  # ambos caminos ejercitados
    assert nq <= 3 * 16 and oq > 10 * nq
    print(
        f"\nretención: consultas {oq} -> {nq}; tiempo {ot * 1000:.0f} -> {nt * 1000:.0f} ms"
    )


# ---------------------------------------------------------------- política de cobertura


def test_coverage_status_thresholds_are_explicit():
    from studio.report import coverage_status

    assert coverage_status(1.0, 0) == "complete"
    assert coverage_status(0.995, 0) == "complete"
    assert coverage_status(0.9949, 0) == "partial"
    assert coverage_status(1.0, 3) == "partial"  # descartes: nunca completa
    assert coverage_status(0.90, 0) == "partial"
    assert coverage_status(0.8999, 0) == "unavailable"
    assert coverage_status(0.0, 0) == "unavailable"


def add_sessions(store, spans):
    async def go():
        async with store.pool.acquire() as c:
            for n, (a, b, dropped) in enumerate(spans):
                await c.execute(
                    "INSERT INTO studio_sessions(id,version,started_at,flushed_until,dropped) VALUES($1,'v1',$2,$3,$4)",
                    uuid.UUID(int=n + 100),
                    a,
                    b,
                    dropped,
                )
            await c.execute(
                "INSERT INTO studio_usage VALUES($1,$2,'chat','','mention','ok','v1',10,0,0,$3)",
                spans[-1][1] - timedelta(hours=2),
                "k" * 64,
                [0] * 11,
            )

    asyncio.run(go())


def hour_floor(moment):
    return moment.replace(minute=0, second=0, microsecond=0)


def test_restart_keeps_comparison_and_gaps_stay_visible_and_quantified(backend):
    store, _ = backend
    end = hour_floor(utcnow())
    start = end - timedelta(days=28)
    prev = start - timedelta(days=28)
    restart = start + timedelta(days=10)
    add_sessions(
        store,
        [  # un reinicio de 90 s en el período actual; el anterior es continuo
            (prev - timedelta(hours=1), restart, 0),
            (restart + timedelta(seconds=90), end + timedelta(minutes=5), 0),
        ],
    )
    r = asyncio.run(report(store, {"start": start.isoformat(), "end": end.isoformat()}))
    cov = r["current"]["coverage"]
    assert cov["status"] == "complete" and r["current"]["coverage_complete"]
    assert cov["gap_count"] == 1 and cov["gap_seconds"] == 90
    assert cov["longest_gap_seconds"] == 90 and cov["gaps"][0]["seconds"] == 90
    assert cov["covered_seconds"] + cov["gap_seconds"] == cov["window_seconds"]
    assert r["comparison"]["status"] == "comparable"
    assert r["delta"]["uses"]["status"] == "comparable"


def test_partial_and_not_comparable_windows_never_invent_values(backend):
    store, _ = backend
    end = hour_floor(utcnow())
    start = end - timedelta(days=28)
    prev = start - timedelta(days=28)
    # Actual: 2 días sin captura de 28 (92,9 %) -> parcial. Anterior: continuo.
    add_sessions(
        store,
        [
            (prev - timedelta(hours=1), start + timedelta(days=10), 0),
            (start + timedelta(days=12), end + timedelta(minutes=5), 0),
        ],
    )
    r = asyncio.run(report(store, {"start": start.isoformat(), "end": end.isoformat()}))
    cov = r["current"]["coverage"]
    assert cov["status"] == "partial" and 0.92 < cov["ratio"] < 0.93
    assert cov["gap_seconds"] == 2 * 86400 and not r["current"]["coverage_complete"]
    assert r["comparison"]["status"] == "partial"
    assert r["delta"]["uses"]["status"] == "partial"
    assert r["comparison"]["reason"]
    # Una función sin registros no es un cero verificado cuando la cobertura es parcial.
    silent = next(f for f in r["current"]["features"] if f["feature"] == "premium")
    assert silent["adoption_pct"] is None

    # Un hueco de 5 días (82 %) vuelve no comparable: sin diferencia ni porcentaje.
    asyncio.run(_truncate_sessions(store))
    add_sessions(
        store,
        [
            (prev - timedelta(hours=1), start + timedelta(days=10), 0),
            (start + timedelta(days=15), end + timedelta(minutes=5), 0),
        ],
    )
    r = asyncio.run(report(store, {"start": start.isoformat(), "end": end.isoformat()}))
    assert r["current"]["coverage"]["status"] == "unavailable"
    assert r["comparison"]["status"] == "not_comparable"
    assert all(v is None for v in r["delta"].values())
    assert (
        r["current"]["summary"]["uses"] == 10
    )  # lo observado sigue visible, sin relleno

    # Sin ninguna sesión: cobertura 0, nunca cero de uso.
    asyncio.run(_truncate_sessions(store))
    r = asyncio.run(report(store, {"start": start.isoformat(), "end": end.isoformat()}))
    assert (
        r["current"]["coverage"]["ratio"] == 0
        and r["current"]["coverage"]["gap_count"] == 1
    )


async def _truncate_sessions(store):
    async with store.pool.acquire() as c:
        await c.execute("TRUNCATE studio_sessions, studio_usage CASCADE")


def test_dropped_records_downgrade_completeness(backend):
    store, _ = backend
    end = hour_floor(utcnow())
    start = end - timedelta(days=7)
    add_sessions(store, [(start - timedelta(days=8), end + timedelta(minutes=5), 4)])
    r = asyncio.run(report(store, {"start": start.isoformat(), "end": end.isoformat()}))
    assert r["current"]["coverage"]["ratio"] == 1
    assert r["current"]["coverage"]["status"] == "partial"
    assert r["current"]["coverage"]["dropped"] == 4


# ---------------------------------------------------------------- errores de Discord


def make_http(cls, status):
    return cls(SimpleNamespace(status=status, reason="x"), "x")


def test_discord_refusals_are_separated_from_internal_errors():
    import discord
    from discord import app_commands
    from discord.ext import commands

    classify = runtime.classify_error
    assert classify(make_http(discord.Forbidden, 403)) == "refused"
    assert classify(make_http(discord.NotFound, 404)) == "refused"
    assert classify(commands.BotMissingPermissions(["send_messages"])) == "refused"
    assert classify(app_commands.BotMissingPermissions(["send_messages"])) == "refused"
    # Envolturas de comandos: se mira la causa real.
    assert (
        classify(commands.CommandInvokeError(make_http(discord.Forbidden, 403)))
        == "refused"
    )
    assert classify(commands.CommandInvokeError(ValueError("bug"))) == "error"
    # Lo que es culpa de Purgito o de la disponibilidad sigue contando como fallo.
    assert (
        classify(make_http(discord.HTTPException, 400)) == "error"
    )  # payload inválido
    assert classify(make_http(discord.HTTPException, 429)) == "error"
    assert classify(make_http(discord.DiscordServerError, 503)) == "error"
    assert classify(RuntimeError("x")) == "error"
    # Validaciones previas siguen siendo rechazos del usuario, no de Discord.
    assert classify(commands.MissingPermissions(["manage_guild"])) == "rejected"
    assert classify(commands.CommandOnCooldown(None, 1, None)) == "rejected"


def test_delivery_refusal_is_reported_apart_from_failure_rate(backend, monkeypatch):
    import discord

    store, settings = backend
    c, clock = setup(store, settings, hour_floor(utcnow()) - timedelta(hours=3))
    monkeypatch.setattr(runtime, "_current", c)
    for exc in (
        make_http(discord.Forbidden, 403),
        make_http(discord.Forbidden, 403),
        ValueError(),
    ):
        with pytest.raises(type(exc)):
            with runtime.measure_delivery(1, "youtube", source="background"):
                raise exc
    with runtime.measure_delivery(1, "youtube", source="background"):
        pass
    clock[0] += timedelta(hours=2)
    assert asyncio.run(c.flush())
    r = asyncio.run(
        report(
            store,
            {
                "start": (hour_floor(utcnow()) - timedelta(days=1)).isoformat(),
                "end": hour_floor(utcnow()).isoformat(),
            },
        )
    )
    s = r["current"]["summary"]
    assert (s["successes"], s["errors"], s["refused"]) == (1, 1, 2)
    assert (
        s["error_pct"] == 50.0
    )  # 1 fallo / (1 éxito + 1 fallo): los rechazos no inflan
    assert s["refused_pct"] == 50.0  # 2 / 4 intentos
    only = asyncio.run(
        report(
            store,
            {
                "start": (hour_floor(utcnow()) - timedelta(days=1)).isoformat(),
                "end": hour_floor(utcnow()).isoformat(),
                "result": "refused",
            },
        )
    )
    assert only["current"]["summary"]["uses"] == 2  # visible y filtrable, no oculto


# ---------------------------------------------------------------- cohortes y línea base


def test_first_observed_activity_is_not_reported_as_installation(backend):
    store, settings = backend
    first = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=12
    )
    c, clock = setup(store, settings, first)
    clock[0] = first + timedelta(hours=2)
    c.observe_inventory([1, 2, 3])
    for gid in (1, 2):  # existían antes de medir: no hay entrada observada
        c.record(gid, "chat", source="mention")
    assert asyncio.run(c.flush())
    clock[0] = first + timedelta(days=5, hours=2)
    c.observe_inventory([1, 2, 3, 4])
    c.membership(4, "join")  # entrada real observada
    c.record(4, "chat", source="mention")
    c.record(3, "chat", source="mention")  # estaba, pero no se sabía su origen
    clock[0] = first + timedelta(days=11)
    assert asyncio.run(c.flush())
    r = asyncio.run(
        report(
            store,
            {
                "start": first.isoformat(),
                "end": (first + timedelta(days=11)).isoformat(),
            },
        )
    )
    cohorts = {x["day"]: x for x in r["retention"] if x["kind"] == "activity"}
    base = cohorts[first.date().isoformat()]
    later = cohorts[(first + timedelta(days=5)).date().isoformat()]
    assert base["baseline"] is True and base["joined_observed"] == 0
    assert later["baseline"] is False and later["size"] == 2
    assert later["joined_observed"] == 1  # solo uno con entrada verificable
    install = [x for x in r["retention"] if x["kind"] == "installation"]
    assert [x["size"] for x in install] == [1]
    assert r["observed_since"] == first


def test_data_expired_by_retention_does_not_make_old_servers_new(backend):
    store, settings = backend  # retención 90 días
    now = utcnow().replace(hour=12, minute=0, second=0, microsecond=0)  # reloj fijo
    c, clock = setup(store, settings, now - timedelta(days=100))
    clock[0] = now - timedelta(days=95)
    c.record(3, "chat", source="mention")  # actividad que expirará
    assert asyncio.run(c.flush())
    clock[0] = now - timedelta(days=90) + timedelta(hours=1)
    c.record(1, "chat", source="mention")  # primer dato que sobrevive al límite
    clock[0] = now - timedelta(days=80) + timedelta(hours=1)
    c.record(2, "chat", source="mention")  # servidor realmente incorporado después
    clock[0] = now - timedelta(days=79)
    assert asyncio.run(c.flush())
    asyncio.run(store.cleanup(now))
    r = asyncio.run(
        report(
            store,
            {
                "start": (now - timedelta(days=91)).isoformat(),
                "end": (now - timedelta(days=79)).isoformat(),
            },
            now=now,
        )
    )
    assert r["observed_since"] == now - timedelta(days=90)  # recortado a la retención
    cohorts = {x["day"]: x for x in r["retention"] if x["kind"] == "activity"}
    edge = cohorts[(now - timedelta(days=90)).date().isoformat()]
    later = cohorts[(now - timedelta(days=80)).date().isoformat()]
    assert edge["baseline"] is True and edge["size"] == 1  # línea base, no «nuevo»
    assert later["baseline"] is False
    assert sum(x["size"] for x in cohorts.values()) == 2  # el expirado no reaparece


def test_join_of_server_already_in_an_inventory_is_a_rejoin(backend):
    store, settings = backend
    at = hour_floor(utcnow()) - timedelta(days=4)
    c, clock = setup(store, settings, at)
    clock[0] = at + timedelta(hours=1)
    c.observe_inventory([5])  # presente en el inventario inicial
    assert asyncio.run(c.flush())
    clock[0] = at + timedelta(days=2)
    c.membership(
        5, "join"
    )  # la salida ocurrió con el bot apagado: no es una comunidad nueva
    c.membership(6, "join")  # nunca vista: entrada real
    assert asyncio.run(c.flush())

    async def actions():
        async with store.pool.acquire() as conn:
            return {
                r["guild_key"]: r["action"]
                for r in await conn.fetch(
                    "SELECT guild_key,action FROM studio_lifecycle"
                )
            }

    got = asyncio.run(actions())
    assert got[settings.guild_key(5)] == "rejoin"
    assert got[settings.guild_key(6)] == "join"


# ---------------------------------------------------------------- ciclo de vida del bot


class FakeBot:
    """Lo mínimo que usa runtime.start(); registra qué engancha Studio al bot."""

    def __init__(self):
        self.listeners, self.before = [], []
        self.tree = SimpleNamespace(walk_commands=lambda: [])

    def walk_commands(self):
        return []

    def add_listener(self, callback, name):
        self.listeners.append(name)

    def before_invoke(self, callback):
        self.before.append(callback)

    def is_ready(self):
        return True

    guilds = []


def _clear_studio_env(monkeypatch):
    for name in (
        "STUDIO_ENABLED",
        "STUDIO_HMAC_KEY",
        "STUDIO_VERSION",
        "STUDIO_RETENTION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_disabled_by_default_hooks_nothing_and_writes_nothing(backend, monkeypatch):
    store, _ = backend
    _clear_studio_env(monkeypatch)
    bot = FakeBot()

    async def run():
        await runtime.start(bot)
        assert runtime.get() is None
        assert bot.listeners == [] and bot.before == []
        # Las funciones que usan los cogs son inertes sin colector.
        runtime.delivery(1, "chat")
        with runtime.measure_delivery(1, "chat"):
            pass
        runtime.finish_command(SimpleNamespace(guild=SimpleNamespace(id=1)))
        await runtime.stop()  # idempotente aunque nunca arrancara
        async with store.pool.acquire() as c:
            assert await c.fetchval("SELECT count(*) FROM studio_sessions") == 0
            assert await c.fetchval("SELECT count(*) FROM studio_usage") == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "env",
    [
        {"STUDIO_ENABLED": "true", "STUDIO_HMAC_KEY": "corta"},
        {"STUDIO_ENABLED": "true"},
        {
            "STUDIO_ENABLED": "true",
            "STUDIO_HMAC_KEY": KEY,
            "STUDIO_RETENTION_DAYS": "1",
        },
        {
            "STUDIO_ENABLED": "true",
            "STUDIO_HMAC_KEY": KEY,
            "STUDIO_VERSION": "<script>",
        },
        {"STUDIO_RETENTION_DAYS": "no-es-un-numero"},
    ],
)
def test_bad_configuration_never_breaks_the_bot_startup(backend, monkeypatch, env):
    _clear_studio_env(monkeypatch)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    bot = FakeBot()

    async def run():
        await runtime.start(bot)  # no debe propagar ninguna excepción
        assert runtime.get() is None and bot.listeners == []

    asyncio.run(run())


def test_database_failure_at_startup_leaves_bot_running_without_studio(
    backend, monkeypatch
):
    import db

    _clear_studio_env(monkeypatch)
    monkeypatch.setenv("STUDIO_ENABLED", "true")
    monkeypatch.setenv("STUDIO_HMAC_KEY", KEY)

    async def unavailable():
        raise ConnectionError("base de datos no disponible")

    monkeypatch.setattr(db, "get_db", unavailable)
    bot = FakeBot()

    async def run():
        await runtime.start(bot)
        assert runtime.get() is None and bot.listeners == []
        await runtime.stop()

    asyncio.run(run())


def test_enabled_start_stop_closes_writer_task_and_final_flush(backend, monkeypatch):
    store, settings = backend
    _clear_studio_env(monkeypatch)
    monkeypatch.setenv("STUDIO_ENABLED", "true")
    monkeypatch.setenv("STUDIO_HMAC_KEY", KEY)
    monkeypatch.setenv("STUDIO_VERSION", "lifecycle-test")
    bot = FakeBot()

    async def run():
        import db

        async def current():
            return SimpleNamespace(pool=store.pool)

        monkeypatch.setattr(db, "get_db", current)
        await runtime.start(bot)
        collector = runtime.get()
        assert collector is not None and not collector.task.done()
        assert {"on_disconnect", "on_guild_join", "on_guild_remove"} <= set(
            bot.listeners
        )
        collector.record(5, "chat", source="mention")
        task = collector.task
        await runtime.stop()
        assert task.done() and runtime.get() is None  # tarea de escritura cerrada
        async with store.pool.acquire() as c:
            assert await c.fetchval("SELECT sum(n) FROM studio_usage") == 1
            assert await c.fetchval("SELECT clean FROM studio_sessions") is True
        # Tras el apagado, los hooks de los cogs vuelven a ser inertes.
        runtime.delivery(5, "chat")
        await runtime.stop()

    asyncio.run(run())


def test_cancelled_delivery_is_not_recorded_as_success(backend, monkeypatch):
    store, settings = backend
    c, _ = setup(store, settings, utcnow() - timedelta(hours=1))
    monkeypatch.setattr(runtime, "_current", c)

    async def run():
        async def send():
            with runtime.measure_delivery(1, "youtube", source="background"):
                await asyncio.sleep(30)

        task = asyncio.create_task(send())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert c.usage == {}  # ni éxito ni fallo


def test_remote_peer_is_refused_even_with_valid_token_and_loopback_host(
    backend, monkeypatch
):
    """Si 8080 llegara a quedar expuesto, un peer no loopback sigue sin acceso."""
    from aiohttp.test_utils import make_mocked_request

    store, settings = backend
    c, _ = setup(store, settings, utcnow() - timedelta(hours=1))
    monkeypatch.setattr(runtime, "_current", c)
    app = web.Application()
    register(app, lambda request: None)  # puerta existente permisiva: aísla la propia
    handlers = {
        (r.method, r.resource.canonical): r.handler for r in app.router.routes()
    }

    class Transport:
        def __init__(self, peer):
            self.peer = peer

        def get_extra_info(self, name, default=None):
            return self.peer if name == "peername" else default

    async def call(method, path, peer, host):
        request = make_mocked_request(
            method,
            path,
            headers={"Host": host, "Authorization": f"Bearer {TOKEN}"},
            transport=Transport(peer),
            app=app,
        )
        return (await handlers[(method, path)](request)).status

    async def run():
        for peer in (("203.0.113.9", 4000), ("10.0.0.5", 4000), ("2001:db8::1", 4000)):
            for host in ("127.0.0.1:8080", "localhost:8080", "purgito.app"):
                for method, path in (
                    ("GET", "/internal/studio/report"),
                    ("POST", "/internal/studio/annotations"),
                ):
                    assert await call(method, path, peer, host) == 404
        # Referencia: el peer loopback con Host loopback sí llega al informe.
        assert (
            await call(
                "GET", "/internal/studio/report", ("127.0.0.1", 4000), "127.0.0.1:8080"
            )
            == 200
        )

    asyncio.run(run())


def test_hourly_series_only_for_short_windows(backend):
    store, settings = backend
    end = hour_floor(utcnow())
    c, clock = setup(store, settings, end - timedelta(days=5))
    for hours_ago, count in ((30, 2), (5, 3)):
        clock[0] = end - timedelta(hours=hours_ago)
        c.record(1, "chat", source="mention", count=count)
    clock[0] = end + timedelta(minutes=5)
    assert asyncio.run(c.flush())
    short = asyncio.run(
        report(
            store,
            {"start": (end - timedelta(hours=48)).isoformat(), "end": end.isoformat()},
        )
    )
    assert [(r["at"].hour, r["uses"]) for r in short["current"]["hourly"]] == [
        ((end - timedelta(hours=30)).hour, 2),
        ((end - timedelta(hours=5)).hour, 3),
    ]
    assert short["previous"]["hourly"] == []
    assert sum(r["uses"] for r in short["current"]["daily"]) == 5  # daily intacto
    long = asyncio.run(
        report(
            store,
            {"start": (end - timedelta(days=10)).isoformat(), "end": end.isoformat()},
        )
    )
    assert long["current"]["hourly"] == []  # ventana larga: solo diario
    assert "guild_key" not in json.dumps(short, default=encode)


def test_annotation_saved_now_is_listed_even_if_window_ended_earlier(backend):
    store, settings = backend
    end = hour_floor(utcnow()) - timedelta(hours=5)  # ventana cerrada antes de «ahora»
    c, _ = setup(store, settings, end - timedelta(days=3))
    asyncio.run(
        store.annotate(
            utcnow() - timedelta(minutes=1), "Desplegado hoy", "", "v9", "release"
        )
    )
    asyncio.run(store.annotate(end - timedelta(days=1), "Anterior", "", "", "change"))
    r = asyncio.run(
        report(
            store,
            {"start": (end - timedelta(days=2)).isoformat(), "end": end.isoformat()},
        )
    )
    assert [n["title"] for n in r["annotations"]] == ["Anterior", "Desplegado hoy"]
    older = asyncio.run(
        report(
            store,
            {"start": (end - timedelta(hours=6)).isoformat(), "end": end.isoformat()},
        )
    )
    assert [n["title"] for n in older["annotations"]] == [
        "Desplegado hoy"
    ]  # fuera del inicio: no


def test_static_assets_use_a_closed_allowlist_without_path_traversal(tmp_path):
    from studio.local_server import asset_index

    root = tmp_path / "studio"
    (root / "js").mkdir(parents=True)
    (root / "css").mkdir()
    (root / "fonts").mkdir()
    (root / "other").mkdir()
    (root / "js" / ".oculto").mkdir()
    for name in (
        "index.html",
        "favicon.svg",
        "js/main.mjs",
        "js/test_x.mjs",
        "css/a.css",
        "fonts/f.woff2",
        "other/x.css",
        "js/.hidden.mjs",
        "js/.oculto/y.mjs",
        "js/notes.txt",
        "Development.Dockerfile",
    ):
        (root / name).write_text("x")
    (tmp_path / "secret.css").write_text("secreto")
    (root / "js" / "link.mjs").symlink_to(tmp_path / "secret.css")
    index = asset_index(root)
    served = set(index)
    assert served == {
        "/",
        "/index.html",
        "/favicon.svg",
        "/js/main.mjs",
        "/css/a.css",
        "/fonts/f.woff2",
    }
    assert all(root.resolve() in f.parents for f in index.values())
    # Cualquier otra cosa que pida un cliente es simplemente una clave que no existe.
    for bad in (
        "/js/test_x.mjs",
        "/other/x.css",
        "/js/.hidden.mjs",
        "/js/.oculto/y.mjs",
        "/js/notes.txt",
        "/Development.Dockerfile",
        "/../secret.css",
        "/js/../../secret.css",
        "/js/../secret.css",
        "/js/%2e%2e/secret.css",
        "/js/link.mjs",  # enlace simbólico hacia fuera
        "/js\\..\\secret.css",
        "/js/main.mjs\x00.css",
        "/nope.html",
        "/js/",
        "//etc/passwd",
        "",
    ):
        assert index.get(bad) is None, bad
    # Lo que aparezca después de arrancar no se sirve hasta reiniciar: la lista no se reconstruye por petición.
    (root / "js" / "nuevo.mjs").write_text("x")
    assert "/js/nuevo.mjs" not in index and "/js/nuevo.mjs" in asset_index(root)
