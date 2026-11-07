"""Guardián de restauración + retención por antigüedad del corpus."""

import asyncio
import importlib.util
import os
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import db
import pgsync
import privacy_guard as pg
import privacy_ledger

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "reapply_deletions", _ROOT / "scripts" / "reapply_deletions.py"
)
reapply_deletions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reapply_deletions)

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture
def mem(monkeypatch, tmp_path):
    monkeypatch.setenv("PRIVACY_WATERMARK_PATH", str(tmp_path / "wm"))
    asyncio.run(db.init_db())

    async def _clean():
        conn = await db.get_db()
        async with db._db_lock:
            for t in ("privacy_state", "corpus_messages", "user_corpus", "gif_senders"):
                await conn.execute(f"DELETE FROM {t}")
            await conn.commit()

    asyncio.run(_clean())
    yield tmp_path / "wm"
    asyncio.run(_clean())
    asyncio.run(db.close_db())


def _set_db_hb(when):
    async def go():
        conn = await db.get_db()
        async with db._db_lock:
            await conn.execute(
                "INSERT INTO privacy_state (key, value) VALUES ('heartbeat_at', ?) "
                "ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                (when.strftime(FMT),),
            )
            await conn.commit()

    asyncio.run(go())


def test_primer_arranque_se_acepta_y_empieza_a_latir(mem):
    assert "primer arranque" in asyncio.run(pg.check_startup(NOW))
    asyncio.run(pg.beat(NOW))
    assert mem.read_text() == NOW.strftime(FMT)
    assert "continuación" in asyncio.run(
        pg.check_startup(NOW + timedelta(hours=9))
    )  # parada larga normal


def test_una_base_mas_antigua_que_lo_ultimo_visto_no_arranca(mem):
    asyncio.run(pg.beat(NOW))
    _set_db_hb(NOW - timedelta(days=1))  # "backup de ayer restaurado"
    with pytest.raises(pg.RestoreNotReconciled, match="MÁS ANTIGUA"):
        asyncio.run(pg.check_startup(NOW + timedelta(minutes=2)))


def test_una_base_sin_latido_en_un_servidor_que_ya_latia_no_arranca(mem):
    asyncio.run(pg.beat(NOW))
    _sync(
        lambda c: c.execute("DELETE FROM privacy_state")
    )  # backup anterior a la guardia
    with pytest.raises(pg.RestoreNotReconciled, match="anterior a la guardia"):
        asyncio.run(pg.check_startup(NOW))


def test_servidor_nuevo_con_base_de_procedencia_desconocida_no_arranca(mem):
    _set_db_hb(NOW - timedelta(hours=3))  # no hay archivo local
    with pytest.raises(pg.RestoreNotReconciled, match="procedencia desconocida"):
        asyncio.run(pg.check_startup(NOW))
    _set_db_hb(NOW - timedelta(minutes=3))  # recién reconciliada
    assert "reconciliada" in asyncio.run(pg.check_startup(NOW))


def _sync(fn):
    c = pgsync.connect(os.environ["TEST_DATABASE_URL"])
    try:
        out = fn(c)
        c.commit()
        return out
    finally:
        c.close()


def test_solo_la_reconciliacion_con_un_registro_valido_pone_la_base_al_dia(
    mem, tmp_path
):
    asyncio.run(pg.beat(datetime.now(timezone.utc)))
    _set_db_hb(datetime.now(timezone.utc) - timedelta(days=1))
    with pytest.raises(pg.RestoreNotReconciled):
        asyncio.run(pg.check_startup(datetime.now(timezone.utc)))
    dsn = os.environ["TEST_DATABASE_URL"]
    led = tmp_path / "led.jsonl"
    led.write_text(
        privacy_ledger.dumps(
            privacy_ledger.snapshot_from_rows([], [], [], datetime.now(timezone.utc))
        )
    )
    # dry-run no sella
    assert reapply_deletions.main(["--dsn", dsn, "--ledger", str(led)]) == 0
    with pytest.raises(pg.RestoreNotReconciled):
        asyncio.run(pg.check_startup(datetime.now(timezone.utc)))
    # con --apply sí
    assert reapply_deletions.main(["--dsn", dsn, "--ledger", str(led), "--apply"]) == 0
    assert asyncio.run(pg.check_startup(datetime.now(timezone.utc)))
    assert (
        _sync(
            lambda c: c.execute(
                "SELECT value FROM privacy_state WHERE key='reconciled_with'"
            ).fetchone()
        )[0]
        == "ledger"
    )


def test_un_registro_viejo_o_ausente_no_pone_la_base_al_dia(mem, tmp_path):
    asyncio.run(pg.beat(datetime.now(timezone.utc)))
    _set_db_hb(datetime.now(timezone.utc) - timedelta(days=1))
    dsn = os.environ["TEST_DATABASE_URL"]
    assert (
        reapply_deletions.main(["--dsn", dsn, "--apply"]) == 1
    )  # sin --ledger ni --sin-registro
    old = tmp_path / "old.jsonl"
    old.write_text(
        privacy_ledger.dumps(
            privacy_ledger.snapshot_from_rows(
                [], [], [], datetime.now(timezone.utc) - timedelta(hours=6)
            )
        )
    )
    assert reapply_deletions.main(["--dsn", dsn, "--ledger", str(old), "--apply"]) == 1
    with pytest.raises(pg.RestoreNotReconciled):
        asyncio.run(pg.check_startup(datetime.now(timezone.utc)))


def test_el_restore_crea_las_tablas_nuevas_que_un_backup_antiguo_no_trae(mem, tmp_path):
    _sync(lambda c: c.execute("DROP TABLE privacy_state"))
    _sync(lambda c: c.execute("DROP TABLE deleted_message_tombstones"))
    dsn = os.environ["TEST_DATABASE_URL"]
    led = tmp_path / "led.jsonl"
    led.write_text(
        privacy_ledger.dumps(
            privacy_ledger.snapshot_from_rows([], [], [], datetime.now(timezone.utc))
        )
    )
    assert reapply_deletions.main(["--dsn", dsn, "--ledger", str(led), "--apply"]) == 0
    assert (
        _sync(
            lambda c: c.execute(
                "SELECT count(*) FROM deleted_message_tombstones"
            ).fetchone()
        )[0]
        == 0
    )


# ─── Retención por antigüedad ─────────────────────────────────────────────────


def test_la_retencion_borra_solo_lo_vencido_y_avisa_de_los_servidores(mem):
    async def go():
        conn = await db.get_db()
        old = (NOW - timedelta(days=200)).strftime(FMT)
        new = (NOW - timedelta(days=10)).strftime(FMT)
        async with db._db_lock:
            for i, (ts, gid) in enumerate(((old, 1), (new, 1), (old, 2))):
                await conn.execute(
                    "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content, created_at) VALUES (?, 1, ?, 'x', ?)",
                    (gid, i, ts),
                )
                await conn.execute(
                    "INSERT INTO user_corpus (guild_id, author_id, author_name, message_id, content, created_at) VALUES (?, 5, 'n', ?, 'x', ?)",
                    (gid, i, ts),
                )
            await conn.execute(
                "INSERT INTO gif_senders (gif_id, guild_id, user_id, last_seen) VALUES (1, 1, 5, ?), (2, 1, 5, ?)",
                (old, new),
            )
            await conn.commit()
        res = await db.purge_expired_corpus(180, now=NOW)
        assert (res["corpus_messages"], res["user_corpus"], res["gif_senders"]) == (
            2,
            2,
            1,
        )
        assert res["guild_ids"] == [1, 2]
        async with conn.execute("SELECT count(*) FROM corpus_messages") as c:
            assert (await c.fetchone())[0] == 1
        # idempotente
        again = await db.purge_expired_corpus(180, now=NOW)
        assert again["guild_ids"] == [] and again["corpus_messages"] == 0

    asyncio.run(go())


def test_la_retencion_tiene_un_minimo_de_30_dias(mem):
    async def go():
        conn = await db.get_db()
        async with db._db_lock:
            await conn.execute(
                "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content, created_at) VALUES (1, 1, 1, 'x', ?)",
                ((NOW - timedelta(days=10)).strftime(FMT),),
            )
            await conn.commit()
        # aunque alguien configure 1 día, no se borra lo de hace 10
        assert (await db.purge_expired_corpus(1, now=NOW))["corpus_messages"] == 0

    asyncio.run(go())


class _Conn:
    """Solo lo que usa check_ledger_freshness: execute(...).fetchone() del latido de la base."""

    def __init__(self, heartbeat):
        self.heartbeat = heartbeat

    def execute(self, *_a):
        hb = self.heartbeat

        class _Cur:
            def fetchone(self):
                return (hb,) if hb else None

        return _Cur()


def test_el_registro_rechaza_una_base_mas_vieja_que_la_ventana_de_lapidas():
    ledger = {"exported_at": "2026-11-20 12:00:00"}
    now = datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc)
    check = reapply_deletions.check_ledger_freshness
    assert (
        check(_Conn("2026-11-10 03:17:00"), ledger, now) is None
    )  # 10 días: las lápidas llegan
    motivo = check(
        _Conn("2026-11-04 03:17:00"), ledger, now
    )  # 16 días: se perdería lo intermedio
    assert motivo and "más de 15 días" in motivo


def test_la_ventana_del_restaurador_es_la_vida_de_una_lapida():
    assert (
        reapply_deletions.TOMBSTONE_WINDOW_DAYS == db.DELETION_TOMBSTONE_RETENTION_DAYS
    )


# ─── Retención de 30 días para mensajes/estilo; los remitentes de GIF conservan su plazo ───────


def test_los_mensajes_vencen_a_los_30_dias_pero_los_remitentes_de_gif_a_los_180(mem):
    async def go():
        conn = await db.get_db()
        d40 = (NOW - timedelta(days=40)).strftime(FMT)
        d10 = (NOW - timedelta(days=10)).strftime(FMT)
        d200 = (NOW - timedelta(days=200)).strftime(FMT)
        async with db._db_lock:
            for i, ts in enumerate((d40, d10)):
                await conn.execute(
                    "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content, created_at) VALUES (1, 1, ?, 'x', ?)",
                    (i, ts),
                )
                await conn.execute(
                    "INSERT INTO user_corpus (guild_id, author_id, author_name, message_id, content, created_at) VALUES (1, 5, 'n', ?, 'x', ?)",
                    (i, ts),
                )
            await conn.execute(
                "INSERT INTO gif_senders (gif_id, guild_id, user_id, last_seen) VALUES (1, 1, 5, ?), (2, 1, 5, ?)",
                (d40, d200),
            )
            await conn.commit()
        antes = await db.count_expired_corpus(30, 180, now=NOW)
        assert (
            antes["corpus_messages"],
            antes["user_corpus"],
            antes["gif_senders"],
        ) == (1, 1, 1)
        assert (antes["corpus_messages_total"], antes["user_corpus_total"]) == (2, 2)
        # contar no borra nada
        assert (await db.count_expired_corpus(30, 180, now=NOW))["corpus_messages"] == 1

        res = await db.purge_expired_corpus(30, now=NOW, gif_days=180)
        assert (res["corpus_messages"], res["user_corpus"], res["gif_senders"]) == (
            1,
            1,
            1,
        )
        assert res["guild_ids"] == [1]
        async with conn.execute("SELECT count(*) FROM corpus_messages") as c:
            assert (await c.fetchone())[0] == 1
        async with conn.execute("SELECT gif_id FROM gif_senders") as c:
            assert [r[0] for r in await c.fetchall()] == [
                1
            ]  # el de 40 días sigue: su plazo es 180

    asyncio.run(go())


def test_el_aprendizaje_y_la_relectura_no_admiten_mensajes_de_mas_de_30_dias(mem):
    from types import SimpleNamespace

    from cogs import chat

    def msg(days_old, mid):
        return SimpleNamespace(
            id=mid,
            content="una frase suficientemente larga para entrar al corpus",
            created_at=datetime.now(timezone.utc) - timedelta(days=days_old),
            author=SimpleNamespace(id=7, display_name="ana"),
            channel=SimpleNamespace(id=3),
        )

    async def go():
        save = chat.Chat._save_message_to_corpus
        assert await save(None, 1, msg(45, 1001)) == "discarded"
        assert await save(None, 1, msg(31, 1002)) == "discarded"
        assert await save(None, 1, msg(5, 1003)) == "saved"
        conn = await db.get_db()
        async with conn.execute(
            "SELECT message_id FROM corpus_messages WHERE guild_id=1"
        ) as c:
            assert [r[0] for r in await c.fetchall()] == [1003]

    asyncio.run(go())
