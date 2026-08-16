"""Tests para la funcionalidad de exclusión de usuarios (interacción y aprendizaje)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

import db
import generation
import webapi
from cogs.chat import Chat
from cogs.memes import Memes


@pytest.fixture
def memory_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_bot.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    asyncio.run(db.init_db())
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()
    yield
    asyncio.run(db.close_db())
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()


def test_db_crud_excluded_users(memory_db):
    async def _run():
        guild1 = 1001
        guild2 = 1002
        user1 = 2001
        user2 = 2002

        # Inicialmente vacio
        assert await db.list_excluded_users(guild1) == []
        assert not await db.is_user_excluded_from_interaction(guild1, user1)
        assert not await db.is_user_excluded_from_learning(guild1, user1)

        # Agregar exclusion completa
        saved = await db.set_user_exclusion(guild1, user1, exclude_interaction=True, exclude_learning=True)
        assert saved["exclude_interaction"] is True
        assert saved["exclude_learning"] is True

        # Verificar consultas
        assert await db.is_user_excluded_from_interaction(guild1, user1) is True
        assert await db.is_user_excluded_from_learning(guild1, user1) is True

        # Aislamiento por servidor (en guild2 no está excluido)
        assert await db.is_user_excluded_from_interaction(guild2, user1) is False
        assert await db.is_user_excluded_from_learning(guild2, user1) is False

        # Agregar solo interaccion para user2
        await db.set_user_exclusion(guild1, user2, exclude_interaction=True, exclude_learning=False)
        assert await db.is_user_excluded_from_interaction(guild1, user2) is True
        assert await db.is_user_excluded_from_learning(guild1, user2) is False

        # Listar
        listed = await db.list_excluded_users(guild1)
        assert len(listed) == 2
        uids = [u["user_id"] for u in listed]
        assert user1 in uids and user2 in uids

        # Actualizar user1 a solo aprendizaje
        await db.set_user_exclusion(guild1, user1, exclude_interaction=False, exclude_learning=True)
        exc1 = await db.get_user_exclusion(guild1, user1)
        assert exc1 is not None
        assert exc1["exclude_interaction"] is False
        assert exc1["exclude_learning"] is True

        # Eliminar exclusion explicitamente
        assert await db.remove_user_exclusion(guild1, user1) is True
        assert await db.get_user_exclusion(guild1, user1) is None
        assert await db.is_user_excluded_from_learning(guild1, user1) is False

        # Desactivar ambos flags auto-elimina
        await db.set_user_exclusion(guild1, user2, exclude_interaction=False, exclude_learning=False)
        assert await db.get_user_exclusion(guild1, user2) is None

    asyncio.run(_run())


def test_corpus_filtering_when_user_excluded_from_learning(memory_db):
    async def _run():
        guild_id = 2001
        channel_id = 3001
        user_normal = 4001
        user_excluded = 4002

        # Guardar mensajes previos de ambos usuarios
        await db.save_corpus_and_user_message(guild_id, channel_id, user_normal, "UserNormal", "primer mensaje normal de prueba", message_id=101)
        await db.save_corpus_and_user_message(guild_id, channel_id, user_normal, "UserNormal", "segundo mensaje normal de prueba", message_id=102)
        await db.save_corpus_and_user_message(guild_id, channel_id, user_excluded, "UsuarioExcluido", "primer mensaje prohibido para aprender", message_id=103)
        await db.save_corpus_and_user_message(guild_id, channel_id, user_excluded, "UsuarioExcluido", "segundo mensaje prohibido para aprender", message_id=104)

        # Sin exclusion: aparecen todos
        msgs = await db.get_corpus_messages(guild_id)
        assert len(msgs) == 4
        user_msgs = await db.get_user_messages(guild_id, user_excluded)
        assert len(user_msgs) == 2
        assert await db.count_user_messages(guild_id, user_excluded) == 2

        # Excluir a user_excluded de aprendizaje
        await db.set_user_exclusion(guild_id, user_excluded, exclude_interaction=False, exclude_learning=True)

        # Con exclusion: los mensajes de user_excluded se filtran dinamicamente (sin borrarlos fisicamente)
        msgs_filtered = await db.get_corpus_messages(guild_id)
        assert len(msgs_filtered) == 2
        assert not any("prohibido" in m for m in msgs_filtered)
        assert any("normal" in m for m in msgs_filtered)

        # get_user_messages y count_user_messages retornan vacio/0
        assert await db.get_user_messages(guild_id, user_excluded) == []
        assert await db.count_user_messages(guild_id, user_excluded) == 0

        # Si se des-excluye, los mensajes vuelven a estar disponibles
        await db.remove_user_exclusion(guild_id, user_excluded)
        msgs_restored = await db.get_corpus_messages(guild_id)
        assert len(msgs_restored) == 4

    asyncio.run(_run())


def test_purge_guild_data_removes_excluded_users(memory_db):
    async def _run():
        guild_id = 9999
        user_id = 8888
        await db.set_user_exclusion(guild_id, user_id, exclude_interaction=True, exclude_learning=True)
        assert await db.get_user_exclusion(guild_id, user_id) is not None

        await db.purge_guild_data(guild_id)
        assert await db.get_user_exclusion(guild_id, user_id) is None

    asyncio.run(_run())


def test_save_message_to_corpus_blocks_learning_excluded_user(memory_db):
    async def _run():
        bot = MagicMock()
        cog = Chat(bot)
        guild_id = 5001
        user_id = 6001

        await db.set_user_exclusion(guild_id, user_id, exclude_interaction=False, exclude_learning=True)

        msg = MagicMock()
        msg.id = 991
        msg.author.id = user_id
        msg.author.display_name = "User"
        msg.channel.id = 7001
        msg.content = "Este es un mensaje nuevo que no debe guardarse"

        status = await cog._save_message_to_corpus(guild_id, msg)
        assert status == "discarded"

        count = await db.count_corpus_messages(guild_id, 7001)
        assert count == 0

    asyncio.run(_run())


def test_on_message_blocks_interaction_excluded_user(memory_db):
    async def _run():
        bot = MagicMock()
        bot.user.id = 12345
        cog = Chat(bot)
        guild_id = 5002
        user_id = 6002
        channel_id = 7002

        await db.set_user_exclusion(guild_id, user_id, exclude_interaction=True, exclude_learning=False)

        channel = MagicMock()
        channel.id = channel_id
        channel.is_nsfw.return_value = False

        msg = MagicMock()
        msg.id = 992
        msg.guild.id = guild_id
        msg.channel = channel
        msg.author.bot = False
        msg.author.id = user_id
        msg.author.display_name = "ExcludedUser"
        msg.content = "Este es un mensaje normal y largo de conversación en el canal."
        msg.raw_mentions = [12345]
        msg.reference = None

        with patch("cogs.chat.is_channel_ignored", new_callable=AsyncMock, return_value=False), \
             patch("cogs.chat.is_corpus_allowed", new_callable=AsyncMock, return_value=True), \
             patch.object(cog, "_handle_trigger", new_callable=AsyncMock) as mock_trigger, \
             patch.object(msg, "add_reaction", new_callable=AsyncMock) as mock_react, \
             patch.object(msg, "reply", new_callable=AsyncMock) as mock_reply:

            await cog._on_message_impl(msg)

            # No debe responder ni reaccionar ni evaluar triggers
            mock_reply.assert_not_called()
            mock_react.assert_not_called()
            mock_trigger.assert_not_called()

        # Como exclude_learning era False, el mensaje sí se guardó en el corpus
        count = await db.count_corpus_messages(guild_id, channel_id)
        assert count == 1

    asyncio.run(_run())


def test_simulator_reports_excluded_user_avisos(memory_db):
    async def _run():
        from cogs.chat import _entrega_avisos
        guild_id = 8001
        channel_id = 9001
        user_id = 7001

        settings = {
            "enabled": True,
            "mention_rate_limit": 0,
        }

        # Sin exclusion
        avisos = await _entrega_avisos(guild_id, channel_id, user_id, settings)
        assert "usuario_excluido_interaccion" not in avisos
        assert "usuario_excluido_aprendizaje" not in avisos

        # Con ambas exclusiones
        await db.set_user_exclusion(guild_id, user_id, exclude_interaction=True, exclude_learning=True)
        avisos_exc = await _entrega_avisos(guild_id, channel_id, user_id, settings)
        assert "usuario_excluido_interaccion" in avisos_exc
        assert "usuario_excluido_aprendizaje" in avisos_exc

    asyncio.run(_run())


def test_imitar_command_with_learning_excluded_user(memory_db):
    async def _run():
        guild_id = 3333
        author_id = 4444

        await db.set_user_exclusion(guild_id, author_id, exclude_interaction=False, exclude_learning=True)
        result = await generation.generate_markov_for_user(guild_id, author_id)
        assert result is None

    asyncio.run(_run())


def test_memes_interaction_exclusion(memory_db):
    async def _run():
        bot = MagicMock()
        bot.user.id = 11111
        cog = Memes(bot)
        guild_id = 4444
        user_id = 5555

        await db.set_user_exclusion(guild_id, user_id, exclude_interaction=True, exclude_learning=False)

        # Mensaje con trigger de meme
        msg = MagicMock()
        msg.author.bot = False
        msg.author.id = user_id
        msg.guild.id = guild_id
        msg.content = "purgito momo"

        with patch("cogs.memes.handle_meme_command", new_callable=AsyncMock) as mock_momo:
            await cog.on_message(msg)
            mock_momo.assert_not_called()

        # Reaccion 🎯 en raw reaction add
        payload = MagicMock()
        payload.emoji = "🎯"
        payload.guild_id = guild_id
        payload.user_id = user_id

        with patch.object(bot, "get_channel") as mock_get_chan:
            await cog.on_raw_reaction_add(payload)
            mock_get_chan.assert_not_called()

    asyncio.run(_run())


def test_webapi_excluded_users_endpoints(memory_db):
    async def _run():
        guild_id = 7777
        user_id = 8888

        # Fake member
        member = MagicMock()
        member.id = user_id
        member.bot = False
        member.name = "testuser"
        member.display_name = "TestUser"
        member.display_avatar.url = "https://cdn.discordapp.com/avatars/test.png"

        guild = MagicMock()
        guild.id = guild_id
        guild.get_member.return_value = member
        guild.members = [member]

        bot = MagicMock()
        bot.user.id = 12345
        bot.get_guild.return_value = guild
        bot.get_user.return_value = None

        def make_req(method, path, body=None, match_info=None):
            req = MagicMock(spec=web.Request)
            req.method = method
            req.path = path
            req.match_info = match_info or {"guild_id": str(guild_id)}
            req.app = {"bot": bot}
            req.query = {}
            req.headers = {}
            req.remote = "127.0.0.1"

            async def json_data():
                return body
            req.json = json_data
            return req

        with patch("webapi._session_logged_in", new_callable=AsyncMock, return_value=True), \
             patch("webapi.check_guild_access", new_callable=AsyncMock, return_value=None), \
             patch("webapi._bot_guild", return_value=guild), \
             patch("webapi._log_audit", new_callable=AsyncMock):

            # 1. GET inicial
            req_get = make_req("GET", f"/api/server/{guild_id}/settings/excluded-users")
            res_get = await webapi._api_excluded_users_get(req_get)
            assert res_get.status == 200
            data = json.loads(res_get.body)
            assert data["users"] == []

            # 2. POST (Añadir)
            req_post = make_req(
                "POST",
                f"/api/server/{guild_id}/settings/excluded-users",
                body={"user_id": user_id, "exclude_interaction": True, "exclude_learning": True}
            )
            res_post = await webapi._api_excluded_users_post(req_post)
            assert res_post.status == 200
            data_post = json.loads(res_post.body)
            assert data_post["ok"] is True
            assert data_post["saved"]["exclude_interaction"] is True
            assert data_post["saved"]["exclude_learning"] is True

            # 3. PUT (Actualizar)
            req_put = make_req(
                "PUT",
                f"/api/server/{guild_id}/settings/excluded-users/{user_id}",
                body={"exclude_interaction": False, "exclude_learning": True},
                match_info={"guild_id": str(guild_id), "user_id": str(user_id)}
            )
            res_put = await webapi._api_excluded_users_put(req_put)
            assert res_put.status == 200
            data_put = json.loads(res_put.body)
            assert data_put["saved"]["exclude_interaction"] is False
            assert data_put["saved"]["exclude_learning"] is True

            # 4. GET para ver la lista con el usuario
            res_get2 = await webapi._api_excluded_users_get(req_get)
            data_get2 = json.loads(res_get2.body)
            assert len(data_get2["users"]) == 1
            assert data_get2["users"][0]["user_name"] == "TestUser"

            # 5. Members Search
            req_search = make_req("GET", f"/api/server/{guild_id}/members/search")
            req_search.query = {"q": "Test"}
            res_search = await webapi._api_members_search(req_search)
            data_search = json.loads(res_search.body)
            assert len(data_search["members"]) == 1
            assert data_search["members"][0]["id"] == str(user_id)

            # 6. DELETE (Eliminar)
            req_del = make_req(
                "DELETE",
                f"/api/server/{guild_id}/settings/excluded-users/{user_id}",
                match_info={"guild_id": str(guild_id), "user_id": str(user_id)}
            )
            res_del = await webapi._api_excluded_users_delete(req_del)
            assert res_del.status == 200
            data_del = json.loads(res_del.body)
            assert data_del["removed"] is True

            # 7. GET final vacio
            res_get3 = await webapi._api_excluded_users_get(req_get)
            data_get3 = json.loads(res_get3.body)
            assert data_get3["users"] == []

    asyncio.run(_run())
