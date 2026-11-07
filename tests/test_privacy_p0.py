"""P0/P1 de privacidad: exclusión global, borrado de GIFs y boosts del usuario,
manejadores de edición/borrado masivo/canal eliminado y restore que exige el registro."""

import asyncio
import importlib.util
import os
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db
import generation
from cogs.chat import Chat

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "reapply_deletions", _ROOT / "scripts" / "reapply_deletions.py"
)
reapply_deletions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reapply_deletions)


@pytest.fixture
def memory_db():
    asyncio.run(db.init_db())
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()
    yield
    asyncio.run(db.close_db())


def test_la_exclusion_global_vale_en_cualquier_servidor(memory_db):
    async def _run():
        assert not await db.is_user_excluded_from_learning(111, 5)
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 5, True, True)
        for guild in (111, 222, 333):
            assert await db.is_user_excluded_from_learning(guild, 5)
            assert await db.is_user_excluded_from_interaction(guild, 5)
        assert not await db.is_user_excluded_from_learning(111, 6)
        # Un servidor purgado no se lleva la exclusión global del usuario.
        await db.purge_guild_data(111)
        assert await db.is_user_excluded_from_learning(222, 5)
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 5, False, False)
        assert not await db.is_user_excluded_from_learning(222, 5)

    asyncio.run(_run())


def test_borrar_mis_datos_tambien_borra_gif_senders_y_boosts(memory_db):
    async def _run():
        conn = await db.get_db()
        async with db._db_lock:
            await conn.execute(
                "INSERT INTO gif_senders (gif_id, guild_id, user_id) VALUES (1, 10, 77), (1, 10, 88)"
            )
            await conn.execute(
                "INSERT INTO member_boost_records (guild_id, user_id, premium_since) "
                "VALUES (10, 77, '2026-01-01'), (10, 88, '2026-01-02')"
            )
            await conn.commit()
        report = await db.delete_user_data(77)
        assert report["gif_senders_deleted"] == 1 and report["boosts_deleted"] == 1
        async with conn.execute("SELECT user_id FROM gif_senders") as c:
            assert [r[0] for r in await c.fetchall()] == [88]
        async with conn.execute("SELECT user_id FROM member_boost_records") as c:
            assert [r[0] for r in await c.fetchall()] == [88]

    asyncio.run(_run())


def _chat():
    return Chat(MagicMock())


def test_editar_un_mensaje_lo_quita_del_corpus_pero_un_embed_no():
    cog = _chat()
    with (
        patch(
            "cogs.chat.delete_message_from_corpus",
            new=AsyncMock(return_value={"corpus_messages": 1, "user_corpus": 1}),
        ) as dele,
        patch("cogs.chat.generation.reset_guild_caches") as reset,
    ):
        payload = MagicMock(guild_id=1, message_id=9, data={"embeds": []})
        asyncio.run(cog.on_raw_message_edit(payload))
        dele.assert_not_called()
        payload.data = {"content": "nuevo"}
        asyncio.run(cog.on_raw_message_edit(payload))
        dele.assert_awaited_once_with(
            1, 9, include_gifs=False
        )  # editar no retira los GIFs
        reset.assert_called_once_with(1)


def test_borrado_masivo_y_canal_eliminado_limpian_el_corpus():
    cog = _chat()
    with (
        patch(
            "cogs.chat.delete_message_from_corpus",
            new=AsyncMock(return_value={"corpus_messages": 1, "user_corpus": 0}),
        ) as dele,
        patch(
            "cogs.chat.delete_channel_corpus",
            new=AsyncMock(return_value={"corpus_messages": 3, "user_corpus": 3}),
        ) as chan,
        patch("cogs.chat.generation.reset_guild_caches"),
    ):
        asyncio.run(
            cog.on_raw_bulk_message_delete(MagicMock(guild_id=1, message_ids={1, 2, 3}))
        )
        assert dele.await_count == 3
        asyncio.run(
            cog.on_guild_channel_delete(MagicMock(guild=MagicMock(id=1), id=55))
        )
        asyncio.run(cog.on_raw_thread_delete(MagicMock(guild_id=1, thread_id=66)))
        assert [c.args for c in chan.await_args_list] == [(1, 55), (1, 66)]


def test_el_restore_exige_el_registro_externo(capsys):
    rc = reapply_deletions.main(["--dsn", os.environ["TEST_DATABASE_URL"], "--apply"])
    assert rc == 1
    assert "falta --ledger" in capsys.readouterr().err


def test_privacidad_bloquea_el_aprendizaje_por_todas_las_rutas(memory_db):
    """Con la exclusión global activa: el guardado en vivo descarta, la imitación no genera
    y nada queda en user_corpus ni corpus_messages, en ningún servidor."""
    from types import SimpleNamespace

    async def _run():
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 31, True, True)
        cog = Chat(MagicMock())
        for guild in (900, 901):
            msg = SimpleNamespace(
                id=guild,
                channel=SimpleNamespace(id=5),
                author=SimpleNamespace(id=31, display_name="x"),
                content="una frase larga suficiente para entrar al corpus",
            )
            assert await cog._save_message_to_corpus(guild, msg) == "discarded"
        assert await generation.generate_markov_for_user(900, 31) is None
        conn = await db.get_db()
        for table, col in (
            ("user_corpus", "author_id"),
            ("corpus_messages", "guild_id"),
        ):
            if table == "user_corpus":
                async with conn.execute(
                    f"SELECT count(*) FROM {table} WHERE {col}=31"
                ) as c:
                    assert (await c.fetchone())[0] == 0
        async with conn.execute(
            "SELECT count(*) FROM corpus_messages WHERE guild_id IN (900, 901)"
        ) as c:
            assert (await c.fetchone())[0] == 0
        # Al volver a participar, el mismo mensaje sí se guarda.
        await db.set_user_exclusion(db.GLOBAL_EXCLUSION_GUILD_ID, 31, False, False)
        msg = SimpleNamespace(
            id=1,
            channel=SimpleNamespace(id=5),
            author=SimpleNamespace(id=31, display_name="x"),
            content="una frase larga suficiente para entrar al corpus",
        )
        assert await cog._save_message_to_corpus(900, msg) == "saved"

    asyncio.run(_run())
