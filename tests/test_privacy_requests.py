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
            for t in (
                "privacy_requests",
                "privacy_request_log",
                "user_corpus",
                "corpus_messages",
                "gif_senders",
                "member_boost_records",
                "frases_especiales",
                "excluded_users",
                "deleted_user_tombstones",
            ):
                await conn.execute(f"DELETE FROM {t}")
            await conn.commit()

    async def _clean_all():
        await _clean()
        conn = await db.get_db()
        async with db._db_lock:
            for t in (
                "deleted_message_tombstones",
                "deleted_channel_tombstones",
                "audit_log",
                "scheduled_announcements",
            ):
                await conn.execute(f"DELETE FROM {t}")
            await conn.commit()

    asyncio.run(_clean_all())
    yield
    asyncio.run(
        _clean_all()
    )  # estas tablas las leen otros tests (p. ej. el registro externo)
    asyncio.run(db.close_db())


async def _seed_user(uid, guild=10):
    await db.save_corpus_and_user_message(
        guild, 1, uid, "x", "hola mundo cruel", message_id=uid
    )
    conn = await db.get_db()
    async with db._db_lock:
        await conn.execute(
            "INSERT INTO gif_senders (gif_id, guild_id, user_id) VALUES (1, ?, ?)",
            (guild, uid),
        )
        await conn.execute(
            "INSERT INTO member_boost_records (guild_id, user_id, premium_since) VALUES (?, ?, '2026-01-01')",
            (guild, uid),
        )
        await conn.execute(
            "INSERT INTO frases_especiales (guild_id, user_id, user_name, frase) VALUES (?, ?, 'n', 'f')",
            (guild, uid),
        )
        await conn.commit()


async def _count(table, uid_col="user_id", uid=77):
    conn = await db.get_db()
    async with conn.execute(
        f"SELECT count(*) FROM {table} WHERE {uid_col}=?", (uid,)
    ) as c:
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
        for table, col in (
            ("user_corpus", "author_id"),
            ("gif_senders", "user_id"),
            ("member_boost_records", "user_id"),
            ("frases_especiales", "user_id"),
        ):
            assert await _count(table, col) == 0, table
        # La frase es del servidor: se queda, sin el nombre de quien la agregó.
        conn = await db.get_db()
        async with conn.execute(
            "SELECT user_id, user_name, frase FROM frases_especiales"
        ) as c:
            assert await c.fetchall() == [(0, "[eliminado]", "f")]
        assert (
            await _count("deleted_user_tombstones") == 1
        )  # lápida para el registro externo
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
        assert (await pr.process_due(forget, now=T0 + timedelta(seconds=30)))[
            "failed"
        ] == 0
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
        claimed = await pr.claim_due(
            now=T0
        )  # el proceso "cae" aquí, sin complete ni fail
        assert len(claimed) == 1
        assert (
            await pr.claim_due(now=T0 + timedelta(minutes=1)) == []
        )  # arrendamiento vigente
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
        assert kinds(await pr.pending_alerts(T0 + timedelta(minutes=1))) == [
            "failed"
        ]  # sigue pendiente
        assert await pr.dispatch_alerts(sale, T0 + timedelta(minutes=2)) == 1
        assert await pr.pending_alerts(T0 + timedelta(minutes=3)) == []  # ya avisado

        near = T0 + timedelta(days=5, hours=1)  # faltan < 48 h
        assert kinds(await pr.pending_alerts(near)) == ["due_soon"]
        await pr.dispatch_alerts(sale, near)
        over = T0 + timedelta(days=7, minutes=1)
        assert kinds(await pr.pending_alerts(over)) == ["overdue"]
        await pr.dispatch_alerts(sale, over)
        assert await pr.pending_alerts(over + timedelta(hours=1)) == []
        assert kinds(await pr.pending_alerts(over + timedelta(hours=25))) == [
            "overdue"
        ]  # se repite
        assert sent == ["failed", "due_soon", "overdue"]

    asyncio.run(_run())


def test_el_aviso_no_lleva_ids_de_persona(memory_db):
    subject, body = privacy_alerts.format_alert(
        {
            "kind": "overdue",
            "id": 4,
            "status": "failed",
            "created_at": "a",
            "due_at": "b",
            "attempts": 3,
            "last_error": "RuntimeError",
            "user_id": 123456789012345678,
        }
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
            await conn.execute(
                "UPDATE privacy_request_log SET event='completed' WHERE seq=(SELECT min(seq) FROM privacy_request_log)"
            )
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


def test_una_persona_excluida_no_entra_al_corpus_ni_con_un_llamador_olvidadizo(
    memory_db,
):
    async def _run():
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 55, True, True)
        assert await db.save_corpus_and_user_message(
            10, 1, 55, "n", "texto que no debe guardarse", message_id=1
        ) == (False, False)
        assert await _count("user_corpus", "author_id", 55) == 0
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 55, False, False)
        assert (
            await db.save_corpus_and_user_message(
                10, 1, 55, "n", "texto que sí se guarda", message_id=2
            )
        )[1] is True

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
    assert (
        len(back) == 1 and back[0]["due_at"] == req["due_at"]
    )  # conserva el plazo original
    # idempotente
    assert (
        _sync(lambda c: reapply_deletions.merge_ledger(c, ledger))["solicitudes"] == 0
    )
    assert asyncio.run(pr.verify_log())["ok"] is True


def test_un_registro_antiguo_sin_solicitudes_sigue_siendo_valido():
    old = privacy_ledger.dumps(
        [
            {"type": "header", "version": 1, "exported_at": "2026-11-01 00:00:00"},
            {
                "type": "footer",
                "counts": {"user_tombstone": 0, "guild_tombstone": 0, "exclusion": 0},
            },
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
    for table, col in (
        ("user_corpus", "author_id"),
        ("gif_senders", "user_id"),
        ("member_boost_records", "user_id"),
        ("frases_especiales", "user_id"),
    ):
        assert asyncio.run(_count(table, col)) == 0, (
            table
        )  # frases: ya sin su autor (user_id=0)


# ─── Mensajes sueltos y canales: no reaparecen tras restaurar un backup antiguo ───────────────


async def _corpus_count(table, where, params=()):
    conn = await db.get_db()
    async with conn.execute(f"SELECT count(*) FROM {table} WHERE {where}", params) as c:
        return (await c.fetchone())[0]


def _clean_tombstones():
    _sync(lambda c: c.execute("DELETE FROM deleted_message_tombstones"))
    _sync(lambda c: c.execute("DELETE FROM deleted_channel_tombstones"))


def test_borrar_un_mensaje_o_un_canal_deja_lapida_solo_si_estaba_en_el_corpus(
    memory_db,
):
    _clean_tombstones()

    async def _run():
        await db.save_corpus_and_user_message(
            10, 1, 5, "n", "mensaje uno largo", message_id=100
        )
        await db.save_corpus_and_user_message(
            10, 2, 5, "n", "mensaje dos largo", message_id=200
        )
        assert (await db.delete_message_from_corpus(10, 999))[
            "corpus_messages"
        ] == 0  # no estaba
        assert await _corpus_count("deleted_message_tombstones", "1=1") == 0
        assert (await db.delete_message_from_corpus(10, 100))["corpus_messages"] == 1
        assert (
            await _corpus_count(
                "deleted_message_tombstones", "guild_id=10 AND message_id=100"
            )
            == 1
        )
        await db.delete_channel_corpus(10, 2)
        assert (
            await _corpus_count(
                "deleted_channel_tombstones", "guild_id=10 AND channel_id=2"
            )
            == 1
        )

    asyncio.run(_run())


def test_un_restore_antiguo_no_devuelve_mensajes_ni_canales_borrados(memory_db):
    _clean_tombstones()

    async def _antes():
        await db.save_corpus_and_user_message(
            10, 1, 5, "n", "mensaje borrado a mano", message_id=100
        )
        await db.save_corpus_and_user_message(
            10, 2, 6, "n", "mensaje del canal borrado", message_id=200
        )
        await db.save_corpus_and_user_message(
            10, 3, 7, "n", "mensaje que se queda aqui", message_id=300
        )
        await db.delete_message_from_corpus(10, 100)
        await db.delete_channel_corpus(10, 2)

    asyncio.run(_antes())
    ledger = privacy_ledger.loads(
        privacy_ledger.dumps(_sync(lambda c: privacy_ledger.build_snapshot(c, T0)))
    )
    # build_snapshot usa "ahora" real para las lápidas vigentes; con T0 en el futuro cercano valen igual
    assert (
        len(ledger["message_tombstones"]) == 1
        and len(ledger["channel_tombstones"]) == 1
    )

    # "Backup antiguo": vuelven los tres mensajes y no hay lápidas.
    async def _restore():
        await db.save_corpus_and_user_message(
            10, 1, 5, "n", "mensaje borrado a mano", message_id=100
        )
        await db.save_corpus_and_user_message(
            10, 2, 6, "n", "mensaje del canal borrado", message_id=200
        )

    asyncio.run(_restore())
    _clean_tombstones()
    assert asyncio.run(_corpus_count("corpus_messages", "guild_id=10")) == 3

    def _aplicar(c):
        reapply_deletions.merge_ledger(c, ledger)
        return reapply_deletions.reapply(c, apply=True)

    stats = _sync(_aplicar)
    assert stats["mensajes_sueltos"] >= 1 and stats["canales"] >= 1
    assert (
        asyncio.run(_corpus_count("corpus_messages", "guild_id=10 AND message_id=100"))
        == 0
    )
    assert (
        asyncio.run(_corpus_count("corpus_messages", "guild_id=10 AND channel_id=2"))
        == 0
    )
    assert (
        asyncio.run(_corpus_count("user_corpus", "guild_id=10 AND channel_id=2")) == 0
    )
    assert (
        asyncio.run(_corpus_count("corpus_messages", "guild_id=10 AND message_id=300"))
        == 1
    )  # intacto


def test_un_servidor_purgado_se_lleva_sus_lapidas_de_mensajes(memory_db):
    _clean_tombstones()

    async def _run():
        await db.save_corpus_and_user_message(
            77, 1, 5, "n", "mensaje del servidor", message_id=1
        )
        await db.delete_message_from_corpus(77, 1)
        assert await _corpus_count("deleted_message_tombstones", "guild_id=77") == 1
        await db.purge_guild_data(77)
        assert await _corpus_count("deleted_message_tombstones", "guild_id=77") == 0

    asyncio.run(_run())


def _rows_msgs(guild_counts):
    out = []
    for gid, n in guild_counts.items():
        out += [
            (gid, i, "2026-11-06 12:00:00", "2099-01-01 00:00:00") for i in range(n)
        ]
    return out


def test_el_desbordamiento_se_resuelve_con_cortes_por_servidor_no_con_truncado(
    memory_db,
):
    cap = privacy_ledger.MAX_MESSAGE_TOMBSTONES
    # El servidor 1 es enorme; los otros dos caben juntos con holgura.
    rows = _rows_msgs({1: cap + 10, 2: 5, 3: 7})
    records = privacy_ledger.snapshot_from_rows([], [], [], T0, messages=rows)
    foot = records[-1]
    assert "truncated" not in foot
    assert (
        foot["counts"]["guild_cutoff"] == 1
        and foot["counts"]["message_tombstone"] == 12
    )
    snap = privacy_ledger.loads(privacy_ledger.dumps(records))
    assert [c["guild_id"] for c in snap["guild_cutoffs"]] == [1]
    assert {r["guild_id"] for r in snap["message_tombstones"]} == {
        2,
        3,
    }  # nada se pierde en silencio


def test_el_corte_por_servidor_borra_todo_lo_aprendido_antes_del_corte(memory_db):
    snap = privacy_ledger.loads(
        privacy_ledger.dumps(
            privacy_ledger.snapshot_from_rows(
                [],
                [],
                [],
                datetime.now(timezone.utc),
                messages=_rows_msgs({4242: privacy_ledger.MAX_MESSAGE_TOMBSTONES + 1}),
            )
        )
    )

    async def _seed():
        await db.save_corpus_and_user_message(
            4242, 1, 5, "n", "mensaje viejo del servidor", message_id=1
        )
        await db.save_corpus_and_user_message(
            4343, 1, 5, "n", "mensaje de otro servidor", message_id=2
        )

    asyncio.run(_seed())
    # La instantánea se tomó "después" de aprender esos mensajes.
    snap["guild_cutoffs"][0]["cutoff"] = "2099-01-01 00:00:00"
    stats = _sync(
        lambda c: reapply_deletions.reapply(
            c, apply=True, cutoffs=snap["guild_cutoffs"]
        )
    )
    assert stats["servidores_cortados"] == 1 and stats["filas_cortadas"] >= 2
    assert asyncio.run(_corpus_count("corpus_messages", "guild_id=4242")) == 0
    assert asyncio.run(_corpus_count("user_corpus", "guild_id=4242")) == 0
    assert (
        asyncio.run(_corpus_count("corpus_messages", "guild_id=4343")) == 1
    )  # otros servidores, intactos


def test_un_registro_marcado_truncado_hace_fallar_el_restore(
    memory_db, tmp_path, capsys
):
    rows = _rows_msgs({1: privacy_ledger.HARD_MESSAGE_ROWS + 1})
    records = privacy_ledger.snapshot_from_rows(
        [], [], [], datetime.now(timezone.utc), messages=rows
    )
    assert records[-1]["truncated"] == ["message_tombstone"]
    path = tmp_path / "snap.jsonl"
    path.write_text(privacy_ledger.dumps(records))
    dsn = os.environ["TEST_DATABASE_URL"]
    assert reapply_deletions.main(["--dsn", dsn, "--ledger", str(path)]) == 1
    assert "TRUNCADO" in capsys.readouterr().err


def test_el_restore_rechaza_un_registro_viejo_o_anterior_a_la_base(
    memory_db, tmp_path, capsys
):
    dsn = os.environ["TEST_DATABASE_URL"]
    old = privacy_ledger.dumps(
        privacy_ledger.snapshot_from_rows(
            [], [], [], datetime.now(timezone.utc) - timedelta(hours=5)
        )
    )
    f = tmp_path / "old.jsonl"
    f.write_text(old)
    assert reapply_deletions.main(["--dsn", dsn, "--ledger", str(f)]) == 1
    assert "más de 2 h" in capsys.readouterr().err
    # aceptándolo de forma explícita sí sigue (dry-run)
    assert (
        reapply_deletions.main(
            ["--dsn", dsn, "--ledger", str(f), "--aceptar-registro-antiguo"]
        )
        == 0
    )
    # un registro anterior al latido de la base tampoco sirve
    _sync(
        lambda c: c.execute(
            "INSERT INTO privacy_state (key, value) VALUES ('heartbeat_at', '2099-01-01 00:00:00') "
            "ON CONFLICT (key) DO UPDATE SET value=excluded.value"
        )
    )
    fresh = tmp_path / "fresh.jsonl"
    fresh.write_text(
        privacy_ledger.dumps(
            privacy_ledger.snapshot_from_rows([], [], [], datetime.now(timezone.utc))
        )
    )
    assert reapply_deletions.main(["--dsn", dsn, "--ledger", str(fresh)]) == 1
    assert "ANTERIOR a la base" in capsys.readouterr().err
    _sync(lambda c: c.execute("DELETE FROM privacy_state"))


# ─── Datos administrativos: seudonimizar, no borrar ───────────────────────────────────────────


def test_borrar_mis_datos_seudonimiza_audit_log_y_anuncios_sin_perder_integridad(
    memory_db,
):
    async def _run():
        import generation

        conn = await db.get_db()
        async with db._db_lock:
            for t in ("audit_log", "scheduled_announcements"):
                await conn.execute(f"DELETE FROM {t}")
            await conn.execute(
                "INSERT INTO audit_log (guild_id, user_id, user_name, action, detail) VALUES (10, 12, 'Ana', 'gifs.add', 'u')"
            )
            await conn.execute(
                "INSERT INTO audit_log (guild_id, user_id, user_name, action, detail) VALUES (10, 99, 'Otro', 'excluded_users.add', 'user_id=12 interaction=True learning=True')"
            )
            await conn.execute(
                "INSERT INTO audit_log (guild_id, user_id, user_name, action, detail, previous_detail) VALUES (10, 99, 'Otro', 'excluded_users.update', 'user_id=123 interaction=True', 'user_id=12')"
            )
            await conn.execute(
                "INSERT INTO scheduled_announcements (guild_id, channel_id, message, mode, created_by) VALUES (10, 1, 'hola', 'once', 12)"
            )
            await conn.commit()

        # Exportación: ve sus acciones (actor) y las que lo mencionan (target), no las de id 123.
        data = await db.build_user_export(12)
        assert sorted(e["role"] for e in data["audit_log"]) == [
            "actor",
            "target",
            "target",
        ]
        assert len(data["scheduled_announcements"]) == 1
        assert data["scheduled_announcements"][0]["message"] == "hola"
        exported = str(data["audit_log"])
        assert (
            "user_id=123" not in exported and "otra persona" in exported
        )  # nunca el id de otra persona

        report = await generation.forget_user(12)
        assert report["admin_rows_pseudonymized"] >= 4

        async with conn.execute(
            "SELECT user_id, user_name, action, detail, previous_detail FROM audit_log ORDER BY id"
        ) as c:
            rows = await c.fetchall()
        assert rows[0][:3] == (
            0,
            "[eliminado]",
            "gifs.add",
        )  # la acción y su fecha se conservan
        assert rows[1][3] == "user_id=[eliminado] interaction=True learning=True"
        assert rows[1][0] == 99  # el admin que actuó sobre ella NO se toca
        assert (
            rows[2][3] == "user_id=123 interaction=True"
        )  # un id más largo no se toca
        assert rows[2][4] == "user_id=[eliminado]"
        async with conn.execute(
            "SELECT created_by, message FROM scheduled_announcements"
        ) as c:
            assert await c.fetchall() == [
                (0, "hola")
            ]  # el anuncio sigue siendo del servidor
        assert (await db.build_user_export(12))["audit_log"] == []

    asyncio.run(_run())


# ─── Ancla externa del registro encadenado ────────────────────────────────────────────────────


def _log_rows():
    return _sync(
        lambda c: c.execute(
            "SELECT seq, request_id, at, event, detail, prev_hash, hash FROM privacy_request_log ORDER BY seq"
        ).fetchall()
    )


def _rewrite_whole_chain():
    """Un atacante con control de la base reescribe una fila Y recalcula toda la cadena."""
    rows = _log_rows()
    prev = pr.GENESIS_HASH
    stmts = []
    for i, (seq, rid, at, event, detail, _p, _h) in enumerate(rows):
        if i == 0:
            event = "completed"  # historia falsa
        h = pr.chain_hash(prev, rid, at, event, detail)
        stmts.append((event, prev, h, seq))
        prev = h

    def _apply(c):
        for event, p, h, seq in stmts:
            c.execute(
                "UPDATE privacy_request_log SET event=?, prev_hash=?, hash=? WHERE seq=?",
                (event, p, h, seq),
            )

    _sync(_apply)


def test_el_ancla_detecta_una_cadena_reescrita_entera(memory_db):
    asyncio.run(pr.create_request(1, now=T0))
    asyncio.run(pr.create_request(2, now=T0))
    snap = privacy_ledger.loads(
        privacy_ledger.dumps(_sync(lambda c: privacy_ledger.build_snapshot(c, T0)))
    )
    anchors = [(a["seq"], a["hash"]) for a in snap["log_anchors"]]
    assert len(anchors) == 1

    assert pr.check_anchors(_log_rows(), anchors)["ok"] is True
    # Sin ancla, la cadena reescrita parece perfecta...
    _rewrite_whole_chain()
    assert asyncio.run(pr.verify_log())["ok"] is True
    # ...con ancla externa, no.
    res = pr.check_anchors(_log_rows(), anchors)
    assert res["ok"] is False and res["altered"] and res["chain_ok"] is True


def test_ancla_posterior_a_la_base_es_un_aviso_no_una_alteracion(memory_db):
    asyncio.run(pr.create_request(1, now=T0))
    rows = _log_rows()
    res = pr.check_anchors(rows, [(rows[-1][0] + 5, "f" * 64)])
    assert res["ahead"] and res["ok"] is True


def test_el_script_de_verificacion_usa_las_instantaneas(memory_db, tmp_path):
    verify = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location(
            "verify_privacy_log", _ROOT / "scripts" / "verify_privacy_log.py"
        )
    )
    verify.__spec__.loader.exec_module(verify)
    asyncio.run(pr.create_request(1, now=T0))
    snap = tmp_path / "ancla.jsonl"
    snap.write_text(
        privacy_ledger.dumps(_sync(lambda c: privacy_ledger.build_snapshot(c, T0)))
    )
    dsn = os.environ["TEST_DATABASE_URL"]
    assert verify.main(["--dsn", dsn, "--anchor", str(snap)]) == 0
    _rewrite_whole_chain()
    assert verify.main(["--dsn", dsn, "--anchor", str(snap)]) == 1
    assert verify.main(["--dsn", dsn, "--anchor", str(tmp_path / "no-existe")]) == 3


# ─── Idempotencia: un trabajador retrasado no pisa al que retomó la solicitud ─────────────────


def test_un_intento_zombi_no_cierra_ni_degrada_lo_que_otro_retomo(memory_db):
    async def _run():
        req, _ = await pr.create_request(41, now=T0)
        a = (await pr.claim_due(now=T0))[0]  # intento 1 (se retrasa)
        later = T0 + timedelta(minutes=pr.LEASE_MINUTES + 1)
        b = (await pr.claim_due(now=later))[0]  # intento 2 retoma
        assert (a["attempts"], b["attempts"]) == (1, 2)
        # El intento 1 despierta tarde: ni completa ni falla.
        assert (
            await pr.complete(req["id"], {"guild_ids": []}, later, a["attempts"])
            is False
        )
        assert (
            await pr.fail(req["id"], RuntimeError("x"), later, a["attempts"]) is False
        )
        assert (await pr.user_requests(41))[0]["status"] == "processing"
        # El intento 2 sí cierra, una sola vez.
        assert (
            await pr.complete(req["id"], {"guild_ids": []}, later, b["attempts"])
            is True
        )
        assert (
            await pr.complete(req["id"], {"guild_ids": []}, later, b["attempts"])
            is False
        )
        events = [e["event"] for e in await pr.request_log(req["id"])]
        assert events.count("completed") == 1 and (await pr.verify_log())["ok"] is True

    asyncio.run(_run())
