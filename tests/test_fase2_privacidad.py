"""Fase 2 de privacidad: atribución del corpus, GIFs trazables y eliminables, solicitudes de derechos,
captura de GIFs restringida y ausencia de comandos de Discord para gestionar datos."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db
import generation
import privacy_rights
from cogs import gifs as gifs_cog
from cogs.privacy import Privacy


@pytest.fixture
def memory_db():
    asyncio.run(db.init_db())
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()
    yield
    asyncio.run(db.close_db())


async def _q(sql, params=()):
    conn = await db.get_db()
    async with conn.execute(sql, params) as cur:
        return await cur.fetchall()


async def _x(sql, params=()):
    conn = await db.get_db()
    async with db._db_lock:
        await conn.execute(sql, params)
        await conn.commit()


# ---------- atribución del corpus ----------
def test_cada_mensaje_nuevo_guarda_su_autor_y_se_borra_por_autor(memory_db):
    async def run():
        await db.save_corpus_and_user_message(10, 1, 77, "ana", "hola mundo", 1001)
        await db.save_corpus_and_user_message(10, 1, 88, "beto", "otro texto", 1002)
        rows = await _q(
            "SELECT message_id, author_id FROM corpus_messages ORDER BY message_id"
        )
        assert [(r[0], r[1]) for r in rows] == [(1001, 77), (1002, 88)]
        # un mensaje cuyo user_corpus se recortó: igual se borra por author_id
        await _x("DELETE FROM user_corpus WHERE message_id=1001")
        report = await db.delete_user_data(77)
        assert report["corpus_messages_deleted"] == 1
        left = await _q("SELECT author_id FROM corpus_messages")
        assert [r[0] for r in left] == [88]

    asyncio.run(run())


def test_migracion_atribuye_solo_por_vinculo_exacto_y_elimina_el_resto(memory_db):
    async def run():
        # heredados: sin author_id
        await _x(
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) VALUES (10,1,1,'con vinculo'),(10,1,2,'sin vinculo'),(10,1,3,'otro servidor')"
        )
        await _x(
            "INSERT INTO user_corpus (guild_id, author_id, author_name, channel_id, message_id, content) VALUES (10,55,'x',1,1,'con vinculo')"
        )
        # mismo message_id en OTRO servidor: no cuenta como vínculo
        await _x(
            "INSERT INTO user_corpus (guild_id, author_id, author_name, channel_id, message_id, content) VALUES (99,66,'y',1,3,'otro servidor')"
        )
        dry = await db.reconcile_corpus_authors(apply=False)
        assert (
            dry["total"] == 3 and dry["atribuibles"] == 1 and dry["no_atribuibles"] == 2
        )
        assert (await _q("SELECT COUNT(*) FROM corpus_messages"))[0][
            0
        ] == 3  # el dry-run no tocó nada
        res = await db.reconcile_corpus_authors(apply=True)
        assert (
            res["atribuidos"] == 1
            and res["eliminados"] == 2
            and res["sin_autor_despues"] == 0
        )
        rows = await _q("SELECT message_id, author_id FROM corpus_messages")
        assert [(r[0], r[1]) for r in rows] == [(1, 55)]

    asyncio.run(run())


# ---------- GIFs ----------
async def _gif(gif_id, guild, url, hash_, senders):
    await _x(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count) VALUES (?, ?, 1) ON CONFLICT (content_hash) DO NOTHING",
        (hash_, f"gifs/{hash_}.gif"),
    )
    await _x(
        "INSERT INTO corpus_gifs (id, guild_id, url, content_hash) VALUES (?, ?, ?, ?)",
        (gif_id, guild, url, hash_),
    )
    for user, msg in senders:
        await _x(
            "INSERT INTO gif_senders (gif_id, guild_id, user_id, channel_id, message_id) VALUES (?, ?, ?, 1, ?)",
            (gif_id, guild, user, msg),
        )


def test_borrar_el_mensaje_retira_el_gif_solo_si_nadie_mas_lo_comparte(memory_db):
    async def run():
        await _gif(1, 10, "u1", "h1", [(77, 500)])
        await _gif(2, 10, "u2", "h2", [(77, 501), (88, 502)])
        with patch("db.r2.delete_gif_key", new=AsyncMock()) as del_key:
            r = await db.delete_message_from_corpus(10, 500)
            assert r["gifs_deleted"] == 1
            assert [c.args[0] for c in del_key.await_args_list] == ["gifs/h1.gif"]
            r = await db.delete_message_from_corpus(
                10, 501
            )  # el GIF 2 tiene otro remitente: se conserva
            assert r["gifs_deleted"] == 0 and r["gif_senders"] == 1
            assert del_key.await_count == 1
        assert [x[0] for x in await _q("SELECT id FROM corpus_gifs ORDER BY id")] == [2]
        assert [x[0] for x in await _q("SELECT user_id FROM gif_senders")] == [88]

    asyncio.run(run())


def test_editar_un_mensaje_no_retira_sus_gifs(memory_db):
    async def run():
        await _gif(1, 10, "u1", "h1", [(77, 500)])
        with patch("db.r2.delete_gif_key", new=AsyncMock()) as del_key:
            r = await db.delete_message_from_corpus(10, 500, include_gifs=False)
            assert r["gifs_deleted"] == 0 and del_key.await_count == 0
        assert len(await _q("SELECT * FROM corpus_gifs")) == 1

    asyncio.run(run())


def test_eliminar_los_datos_de_una_persona_retira_sus_gifs_exclusivos_y_respeta_los_compartidos(
    memory_db,
):
    async def run():
        await _gif(1, 10, "u1", "h1", [(77, 1)])  # solo ella
        await _gif(2, 10, "u2", "h2", [(77, 2), (88, 3)])  # compartido
        await _x(
            "INSERT INTO corpus_gifs (id, guild_id, url) VALUES (3, 10, 'admin')"
        )  # añadido por un admin, sin remitentes
        with (
            patch("db.r2.delete_gif_key", new=AsyncMock()) as del_key,
            patch("db.r2.delete_gif_url", new=AsyncMock()),
        ):
            report = await db.delete_user_data(77)
            assert (
                report["gifs_deleted"] == 1 and report["gif_senders_deleted"] == 1
            )  # el otro registro cayó con el GIF exclusivo
            assert [c.args[0] for c in del_key.await_args_list] == ["gifs/h1.gif"]
            # idempotente: repetir no borra nada más
            again = await db.delete_user_data(77)
            assert again["gifs_deleted"] == 0
        assert sorted(x[0] for x in await _q("SELECT id FROM corpus_gifs")) == [2, 3]
        assert [x[0] for x in await _q("SELECT user_id FROM gif_senders")] == [88]

    asyncio.run(run())


def test_dos_servidores_con_el_mismo_archivo_conservan_el_objeto_de_r2(memory_db):
    async def run():
        await _x(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count) VALUES ('hh','gifs/hh.gif',2)"
        )
        for gid, guild, user in ((1, 10, 77), (2, 20, 88)):
            await _x(
                "INSERT INTO corpus_gifs (id, guild_id, url, content_hash) VALUES (?, ?, ?, 'hh')",
                (gid, guild, f"u{gid}"),
            )
            await _x(
                "INSERT INTO gif_senders (gif_id, guild_id, user_id, channel_id, message_id) VALUES (?, ?, ?, 1, ?)",
                (gid, guild, user, gid),
            )
        with patch("db.r2.delete_gif_key", new=AsyncMock()) as del_key:
            await db.delete_user_data(77)
            assert del_key.await_count == 0  # sigue una referencia en el otro servidor
            await db.delete_user_data(88)
            assert del_key.await_count == 1

    asyncio.run(run())


def _channel(nsfw=False, view=True, guild=True):
    perms = SimpleNamespace(view_channel=view)
    g = SimpleNamespace(default_role=object()) if guild else None
    return SimpleNamespace(
        is_nsfw=lambda: nsfw, guild=g, permissions_for=lambda role: perms
    )


def test_la_captura_de_gifs_omite_canales_nsfw_y_restringidos():
    assert gifs_cog.channel_allows_gif_capture(_channel())
    assert not gifs_cog.channel_allows_gif_capture(_channel(nsfw=True))
    assert not gifs_cog.channel_allows_gif_capture(_channel(view=False))
    assert not gifs_cog.channel_allows_gif_capture(_channel(guild=False))
    broken = SimpleNamespace(is_nsfw=lambda: (_ for _ in ()).throw(RuntimeError()))
    assert not gifs_cog.channel_allows_gif_capture(broken)


def test_save_gif_candidates_no_guarda_en_canales_restringidos():
    msg = SimpleNamespace(
        channel=_channel(view=False),
        content="https://tenor.com/view/x-1",
        attachments=[],
        author=SimpleNamespace(id=1),
        id=1,
    )
    with patch.object(
        gifs_cog, "_save_one_gif", new=AsyncMock(return_value=True)
    ) as save:
        assert asyncio.run(gifs_cog.save_gif_candidates(10, msg)) == 0
        assert save.await_count == 0


# ---------- solicitudes de derechos ----------
def test_solicitud_de_derechos_valida_y_limita(memory_db):
    async def run():
        r = await privacy_rights.create(
            5, "access", "  quiero saber qué tienen de mí  "
        )
        assert r["status"] == "open" and r["note"].startswith("quiero")
        assert r["due_at"] > r["created_at"]
        with pytest.raises(privacy_rights.RightsError):
            await privacy_rights.create(5, "borrar_todo")
        with pytest.raises(privacy_rights.RightsError):
            await privacy_rights.create(5, "other", "x" * (privacy_rights.NOTE_MAX + 1))
        for _ in range(privacy_rights.MAX_OPEN_PER_USER - 1):
            await privacy_rights.create(5, "other")
        with pytest.raises(privacy_rights.RightsError):
            await privacy_rights.create(5, "other")
        # cada persona solo ve las suyas
        assert await privacy_rights.user_requests(6) == []
        # vencida: aparece como tal para el operador; contestar la cierra
        from datetime import datetime, timedelta, timezone

        late = datetime.now(timezone.utc) + timedelta(days=31)
        assert any(x["overdue"] for x in await privacy_rights.open_requests(late))
        with pytest.raises(privacy_rights.RightsError):
            await privacy_rights.mark_answered(r["id"], "   ")
        assert await privacy_rights.mark_answered(r["id"], "Aquí está tu información.")
        assert not await privacy_rights.mark_answered(r["id"], "otra vez")
        mine = [x for x in await privacy_rights.user_requests(5) if x["id"] == r["id"]][
            0
        ]
        assert (
            mine["status"] == "answered"
            and mine["response"] == "Aquí está tu información."
        )
        # eliminar los datos de la persona borra también sus solicitudes
        await db.delete_user_data(5)
        assert await privacy_rights.user_requests(5) == []

    asyncio.run(run())


def test_el_cog_de_privacidad_ya_no_registra_comandos_de_barra():
    cog = Privacy(MagicMock())
    assert cog.get_app_commands() == []
    assert not hasattr(cog, "borrar_mis_datos") and not hasattr(cog, "mis_datos")


def test_bloqueo_temporal_vence_en_dos_dias_y_la_denegacion_informa_el_reclamo_ante_la_agencia(
    memory_db,
):
    async def run():
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
        b = await privacy_rights.create(9, "blocking", "", None, now)
        a = await privacy_rights.create(9, "access", "", None, now)
        assert b["due_at"] == (now + timedelta(days=2)).strftime(privacy_rights.FMT)
        assert a["due_at"] == (now + timedelta(days=30)).strftime(privacy_rights.FMT)
        assert await privacy_rights.mark_answered(
            a["id"], "No procede por X.", denied=True
        )
        got = [x for x in await privacy_rights.user_requests(9) if x["id"] == a["id"]][
            0
        ]
        assert (
            got["status"] == "denied"
            and "treinta días hábiles" in got["response"]
            and "Agencia" in got["response"]
        )

    asyncio.run(run())


def test_el_correo_para_la_respuesta_es_opcional_se_valida_y_se_borra_al_contestar(
    memory_db,
):
    async def run():
        with pytest.raises(privacy_rights.RightsError):
            await privacy_rights.create(3, "access", "", "no-es-un-correo")
        r = await privacy_rights.create(3, "access", "", "persona@example.org")
        assert await privacy_rights.requester_of(r["id"]) == (3, "persona@example.org")
        await privacy_rights.mark_answered(r["id"], "ok")
        assert await privacy_rights.requester_of(r["id"]) == (3, None)

    asyncio.run(run())
