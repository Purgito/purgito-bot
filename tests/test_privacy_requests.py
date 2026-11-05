"""Centro de Privacidad: solicitudes de eliminación persistentes, procesamiento diferido,
reintentos, avisos y registro verificable; restauración con el registro externo."""

import asyncio
import importlib.util
import os
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import db
import pgsync
import privacy_alerts
import privacy_ledger
import privacy_requests as pr

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "reapply_deletions", _ROOT / "scripts" / "reapply_deletions.py"
)
reapply_deletions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reapply_deletions)

T0 = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def memory_db():
    asyncio.run(db.init_db())

    async def _clean():
        conn = await db.get_db()
        async with db._db_lock:
            for t in ("privacy_requests", "privacy_request_log", "user_corpus",
                      "corpus_messages", "gif_senders", "member_boost_records",
                      "frases_especiales", "excluded_users", "deleted_user_tombstones"):
                await conn.execute(f"DELETE FROM {t}")
            await conn.commit()

    asyncio.run(_clean())
    yield
    asyncio.run(db.close_db())


async def _seed_user(uid, guild=10):
    await db.save_corpus_and_user_message(guild, 1, uid, "x", "hola mundo cruel", message_id=uid)
    conn = await db.get_db()
    async with db._db_lock:
        await conn.execute("INSERT INTO gif_senders (gif_id, guild_id, user_id) VALUES (1, ?, ?)", (guild, uid))
        await conn.execute("INSERT INTO member_boost_records (guild_id, user_id, premium_since) VALUES (?, ?, '2026-01-01')", (guild, uid))
        await conn.execute("INSERT INTO frases_especiales (guild_id, user_id, user_name, frase) VALUES (?, ?, 'n', 'f')", (guild, uid))
        await conn.commit()


async def _count(table, uid_col="user_id", uid=77):
    conn = await db.get_db()
    async with conn.execute(f"SELECT count(*) FROM {table} WHERE {uid_col}=?", (uid,)) as c:
        return (await c.fetchone())[0]


def test_crear_es_idempotente_y_fija_plazo_de_7_dias(memory_db):
    async def _run():
        a, created = await pr.create_request(77, now=T0)
        b, created2 = await pr.create_request(77, now=T0 + timedelta(hours=1))
        assert created and not created2 and a["id"] == b["id"]
        assert a["due_at"] == (T0 + timedelta(days=7)).strftime(pr.FMT)

    asyncio.run(_run())


def test_procesar_borra_todo_y_registra_sin_ids(memory_db):
    async def _run():
        import generation

        await _seed_user(77)
        req, _ = await pr.create_request(77, now=T0)
        res = await pr.process_due(generation.forget_user, now=T0)
        assert res == {"completed": 1, "failed": 0}
        for table, col in (("user_corpus", "author_id"), ("gif_senders", "user_id"),
                           ("member_boost_records", "user_id"), ("frases_especiales", "user_id")):
            assert await _count(table, col) == 0, table
        assert await _count("deleted_user_tombstones") == 1  # lápida para el registro externo
        assert (await pr.user_requests(77))[0]["status"] == "completed"
        log = await pr.request_log(req["id"])
        assert [e["event"] for e in log] == ["created", "attempt_started", "completed"]
        assert "77" not in str(log)  # el registro no lleva el id de la persona
        assert (await pr.verify_log())["ok"] is True

    asyncio.run(_run())


def test_un_fallo_reintenta_con_espera_y_no_cancela(memory_db):
    async def _run():
        await pr.create_request(5, now=T0)
        boom = {"n": 0}

        async def forget(uid):
            boom["n"] += 1
            if boom["n"] == 1:
                raise RuntimeError("secreto-que-no-debe-guardarse")
            return {"guild_ids": [], "user_corpus_deleted": 0}

        assert (await pr.process_due(forget, now=T0))["failed"] == 1
        # antes de la espera no se reintenta
        assert (await pr.process_due(forget, now=T0 + timedelta(seconds=30)))["failed"] == 0
        assert boom["n"] == 1
        later = T0 + timedelta(minutes=2)
        assert (await pr.process_due(forget, now=later))["completed"] == 1
        req = (await pr.user_requests(5))[0]
        assert req["status"] == "completed" and req["attempts"] == 2
        conn = await db.get_db()
        async with conn.execute("SELECT detail FROM privacy_request_log") as c:
            assert "secreto" not in " ".join(r[0] for r in await c.fetchall())

    asyncio.run(_run())


def test_sobrevive_a_un_reinicio_a_mitad_de_un_intento(memory_db):
    async def _run():
        await pr.create_request(9, now=T0)
        claimed = await pr.claim_due(now=T0)  # el proceso "cae" aquí, sin complete ni fail
        assert len(claimed) == 1
        assert await pr.claim_due(now=T0 + timedelta(minutes=1)) == []  # arrendamiento vigente
        again = await pr.claim_due(now=T0 + timedelta(minutes=pr.LEASE_MINUTES + 1))
        assert len(again) == 1 and again[0]["attempts"] == 2
        events = [e["event"] for e in await pr.request_log(again[0]["id"])]
        assert "lease_expired" in events

    asyncio.run(_run())


def test_avisos_fallo_proximo_y_vencido_una_vez_y_solo_si_salen(memory_db):
    async def _run():
        req, _ = await pr.create_request(3, now=T0)
        await pr.claim_due(now=T0)
        await pr.fail(req["id"], RuntimeError("x"), now=T0)
        kinds = lambda al: sorted(a["kind"] for a in al)  # noqa: E731
        assert kinds(await pr.pending_alerts(T0 + timedelta(minutes=1))) == ["failed"]

        sent = []

        async def no_sale(alert):
            return False

        async def sale(alert):
            sent.append(alert["kind"])
            return True

        assert await pr.dispatch_alerts(no_sale, T0 + timedelta(minutes=1)) == 0
        assert kinds(await pr.pending_alerts(T0 + timedelta(minutes=1))) == ["failed"]  # sigue pendiente
        assert await pr.dispatch_alerts(sale, T0 + timedelta(minutes=2)) == 1
        assert await pr.pending_alerts(T0 + timedelta(minutes=3)) == []  # ya avisado

        near = T0 + timedelta(days=5, hours=1)  # faltan < 48 h
        assert kinds(await pr.pending_alerts(near)) == ["due_soon"]
        await pr.dispatch_alerts(sale, near)
        over = T0 + timedelta(days=7, minutes=1)
        assert kinds(await pr.pending_alerts(over)) == ["overdue"]
        await pr.dispatch_alerts(sale, over)
        assert await pr.pending_alerts(over + timedelta(hours=1)) == []
        assert kinds(await pr.pending_alerts(over + timedelta(hours=25))) == ["overdue"]  # se repite
        assert sent == ["failed", "due_soon", "overdue"]

    asyncio.run(_run())


def test_el_aviso_no_lleva_ids_de_persona(memory_db):
    subject, body = privacy_alerts.format_alert(
        {"kind": "overdue", "id": 4, "status": "failed", "created_at": "a", "due_at": "b",
         "attempts": 3, "last_error": "RuntimeError", "user_id": 123456789012345678}
    )
    assert "123456789012345678" not in subject + body and "#4" in subject
    assert privacy_alerts.configured() in (True, False)


def test_el_registro_detecta_manipulacion(memory_db):
    async def _run():
        await pr.create_request(1, now=T0)
        await pr.create_request(2, now=T0)
        assert (await pr.verify_log())["ok"] is True
        conn = await db.get_db()
        async with db._db_lock:
            await conn.execute("UPDATE privacy_request_log SET event='completed' WHERE seq=(SELECT min(seq) FROM privacy_request_log)")
            await conn.commit()
        bad = await pr.verify_log()
        assert bad["ok"] is False and bad["bad_seq"] is not None

    asyncio.run(_run())


def test_la_purga_borra_solo_solicitudes_terminadas_viejas(memory_db):
    async def _run():
        import generation

        await pr.create_request(1, now=T0)
        await pr.process_due(generation.forget_user, now=T0)
        await pr.create_request(2, now=T0)
        assert await pr.purge_old(T0 + timedelta(days=pr.RETENTION_DAYS - 1)) == 0
        assert await pr.purge_old(T0 + timedelta(days=pr.RETENTION_DAYS + 1)) == 1
        assert len(await pr.user_requests(2)) == 1
        assert (await pr.verify_log())["ok"] is True

    asyncio.run(_run())


def test_buildexport_incluye_gifs_boosts_frases_y_exclusiones(memory_db):
    async def _run():
        await _seed_user(77)
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 77, True, True)
        await pr.create_request(77, now=T0)
        data = await db.build_user_export(77)
        assert len(data["messages_by_guild"][10]) == 1
        assert len(data["gifs"]) == 1 and len(data["boosts"]) == 1
        assert len(data["special_phrases"]) == 1
        assert data["exclusions"][0]["scope"] == "global"
        assert data["deletion_requests"][0]["status"] == "pending"
        other = await db.build_user_export(78)
        assert not (other["gifs"] or other["boosts"] or other["exclusions"])

    asyncio.run(_run())


def test_una_persona_excluida_no_entra_al_corpus_ni_con_un_llamador_olvidadizo(memory_db):
    async def _run():
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 55, True, True)
        assert await db.save_corpus_and_user_message(10, 1, 55, "n", "texto que no debe guardarse", message_id=1) == (False, False)
        assert await _count("user_corpus", "author_id", 55) == 0
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 55, False, False)
        assert (await db.save_corpus_and_user_message(10, 1, 55, "n", "texto que sí se guarda", message_id=2))[1] is True

    asyncio.run(_run())


def _sync(fn):
    c = pgsync.connect(os.environ["TEST_DATABASE_URL"])
    try:
        out = fn(c)
        c.commit()
        return out
    finally:
        c.close()


def test_el_registro_externo_recrea_la_solicitud_abierta_tras_un_restore(memory_db):
    req, _ = asyncio.run(pr.create_request(88, now=T0))
    rows = _sync(lambda c: c.execute(privacy_ledger.REQUESTS_SQL).fetchall())
    records = privacy_ledger.snapshot_from_rows([], [], [], T0, rows)
    ledger = privacy_ledger.loads(privacy_ledger.dumps(records))
    assert [r["user_id"] for r in ledger["deletion_requests"]] == [88]

    # "Restore": la solicitud desaparece de la base; el merge del registro la recrea.
    _sync(lambda c: c.execute("DELETE FROM privacy_requests"))
    assert asyncio.run(pr.user_requests(88)) == []
    merged = _sync(lambda c: reapply_deletions.merge_ledger(c, ledger))
    assert merged["solicitudes"] == 1
    back = asyncio.run(pr.user_requests(88))
    assert len(back) == 1 and back[0]["due_at"] == req["due_at"]  # conserva el plazo original
    # idempotente
    assert _sync(lambda c: reapply_deletions.merge_ledger(c, ledger))["solicitudes"] == 0
    assert asyncio.run(pr.verify_log())["ok"] is True


def test_un_registro_antiguo_sin_solicitudes_sigue_siendo_valido():
    old = privacy_ledger.dumps(
        [
            {"type": "header", "version": 1, "exported_at": "2026-11-01 00:00:00"},
            {"type": "footer", "counts": {"user_tombstone": 0, "guild_tombstone": 0, "exclusion": 0}},
        ]
    )
    assert privacy_ledger.loads(old)["deletion_requests"] == []


def test_un_restore_antiguo_vuelve_a_borrar_todo_con_el_registro_externo(memory_db):
    """Borrado -> el backup viejo "resucita" los datos y la base pierde sus lápidas ->
    el registro externo + reapply los borra otra vez (corpus, GIFs, boosts y frases)."""
    import generation

    async def _antes():
        await _seed_user(77)
        await pr.create_request(77, now=T0)
        await pr.process_due(generation.forget_user, now=T0)

    asyncio.run(_antes())
    # El registro externo se exporta mientras la lápida existe.
    ledger_text = privacy_ledger.dumps(
        _sync(lambda c: privacy_ledger.build_snapshot(c, T0 + timedelta(minutes=1)))
    )
    ledger = privacy_ledger.loads(ledger_text)
    assert [r["user_id"] for r in ledger["user_tombstones"]] == [77]

    # "Restore de un backup anterior": vuelven los datos y no hay lápidas.
    asyncio.run(_seed_user(77))
    _sync(lambda c: c.execute("DELETE FROM deleted_user_tombstones"))
    assert asyncio.run(_count("gif_senders")) == 1

    def _restaurar(c):
        reapply_deletions.merge_ledger(c, ledger)
        return reapply_deletions.reapply(c, apply=True)

    _sync(_restaurar)
    for table, col in (("user_corpus", "author_id"), ("gif_senders", "user_id"),
                       ("member_boost_records", "user_id"), ("frases_especiales", "user_id")):
        assert asyncio.run(_count(table, col)) == 0, table
