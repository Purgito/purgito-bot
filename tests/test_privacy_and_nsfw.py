"""Tests para borrado de mensajes (on_raw_message_delete), ciclo de vida de caché y bloqueo NSFW."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.chat import Chat
import db
import generation
import webapi


@pytest.fixture
def memory_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_bot.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    asyncio.run(db.init_db())
    # Limpiar cachés de generación
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()
    yield
    asyncio.run(db.close_db())
    generation._markov_cache.clear()
    generation._user_markov_cache.clear()


def test_delete_message_from_corpus(memory_db):
    async def _run():
        guild_id = 111
        channel_id = 222
        author_id = 333
        message_id = 444

        # 1. Guardar mensaje
        c_ins, u_ins = await db.save_corpus_and_user_message(
            guild_id=guild_id,
            channel_id=channel_id,
            author_id=author_id,
            author_name="testuser",
            content="este es un mensaje privado",
            message_id=message_id,
        )
        assert c_ins is True
        assert u_ins is True

        # 2. Borrar mensaje por message_id
        res = await db.delete_message_from_corpus(guild_id, message_id)
        assert res["corpus_messages"] == 1
        assert res["user_corpus"] == 1

        # 3. Verificar que ya no existe en la base de datos
        db_conn = await db.get_db()
        async with db_conn.execute(
            "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=? AND message_id=?",
            (guild_id, message_id),
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == 0

        async with db_conn.execute(
            "SELECT COUNT(*) FROM user_corpus WHERE guild_id=? AND message_id=?",
            (guild_id, message_id),
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == 0

    asyncio.run(_run())


def test_delete_message_invalidates_cache_and_removes_from_markov(memory_db):
    """Prueba el flujo completo:
    1. Guardar 50 mensajes normales + 1 mensaje con frase sensible.
    2. Construir modelo Markov en memoria (queda cacheado en _markov_cache).
    3. Confirmar que la transición sensible existe en el modelo cacheado.
    4. Eliminar el mensaje sensible mediante on_raw_message_delete.
    5. Confirmar que SQLite ya no contiene el registro.
    6. Confirmar que _markov_cache[guild_id] fue invalidada.
    7. Reconstruir modelo y confirmar que la transición ya no existe en el nuevo modelo.
    """

    async def _run():
        guild_id = 555
        channel_id = 666
        author_id = 777
        sensitive_msg_id = 99999

        # 1. Sembrar 55 mensajes normales
        for i in range(55):
            await db.save_corpus_and_user_message(
                guild_id=guild_id,
                channel_id=channel_id,
                author_id=author_id,
                author_name="testuser",
                content=f"mensaje de prueba numero {i} para el corpus",
                message_id=1000 + i,
            )

        # Sembrar el mensaje sensible
        await db.save_corpus_and_user_message(
            guild_id=guild_id,
            channel_id=channel_id,
            author_id=author_id,
            author_name="testuser",
            content="palabraclavesecreta unicatoken en mi cuenta",
            message_id=sensitive_msg_id,
        )

        # 2. Construir modelo Markov (se almacena en _markov_cache)
        model1 = await generation.build_markov_model(guild_id)
        assert model1 is not None
        assert guild_id in generation._markov_cache

        # 3. Confirmar que la transición sensible existe en el modelo cacheado
        assert ("palabraclavesecreta", "unicatoken") in model1.transitions_order2

        # 4. Eliminar el mensaje sensible mediante on_raw_message_delete
        bot = MagicMock()
        cog = Chat(bot)
        payload = MagicMock(spec=discord.RawMessageDeleteEvent)
        payload.guild_id = guild_id
        payload.message_id = sensitive_msg_id

        await cog.on_raw_message_delete(payload)

        # 5. Confirmar que SQLite ya no contiene el mensaje sensible
        db_conn = await db.get_db()
        async with db_conn.execute(
            "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=? AND message_id=?",
            (guild_id, sensitive_msg_id),
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == 0

        # 6. Confirmar que la caché del guild fue invalidada
        assert guild_id not in generation._markov_cache

        # 7. Reconstruir modelo nuevo
        model2 = await generation.build_markov_model(guild_id)
        assert model2 is not None

        # 8. Confirmar que la transición sensible NO existe en el nuevo modelo
        assert ("palabraclavesecreta", "unicatoken") not in model2.transitions_order2
        assert "palabraclavesecreta" not in model2.transitions_order1

    asyncio.run(_run())


def test_sfw_to_nsfw_transition_purges_corpus_and_invalidates_cache(memory_db):
    """Prueba que si un canal pasa de SFW a NSFW en on_guild_channel_update:
    1. Se eliminan todos los mensajes de ese channel_id de SQLite.
    2. Se invalida la caché del guild en RAM.
    """

    async def _run():
        guild_id = 100
        channel_id = 200

        # Sembrar 60 mensajes en el canal
        for i in range(60):
            await db.save_corpus_and_user_message(
                guild_id=guild_id,
                channel_id=channel_id,
                author_id=1,
                author_name="u",
                content=f"hola canal sfw mensaje {i}",
                message_id=i,
            )

        # Construir y cachear modelo
        model = await generation.build_markov_model(guild_id)
        assert model is not None
        assert guild_id in generation._markov_cache

        # Simular cambio en Discord: canal pasa a NSFW
        bot = MagicMock()
        cog = Chat(bot)

        guild_mock = MagicMock(spec=discord.Guild)
        guild_mock.id = guild_id
        guild_mock.me = MagicMock()

        before = MagicMock(spec=discord.TextChannel)
        before.id = channel_id
        before.guild = guild_mock
        before.is_nsfw.return_value = False

        after = MagicMock(spec=discord.TextChannel)
        after.id = channel_id
        after.name = "general-nsfw"
        after.guild = guild_mock
        after.is_nsfw.return_value = True

        await cog.on_guild_channel_update(before, after)

        # 1. Comprobar que la base de datos está vacía para ese canal
        db_conn = await db.get_db()
        async with db_conn.execute(
            "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == 0

        # 2. Comprobar que la caché fue invalidada
        assert guild_id not in generation._markov_cache

    asyncio.run(_run())


def test_nsfw_channel_blocked_on_live_message(memory_db):
    async def _run():
        bot = MagicMock()
        cog = Chat(bot)

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 555
        channel.is_nsfw.return_value = True

        msg = MagicMock(spec=discord.Message)
        msg.id = 777
        msg.guild.id = 111
        msg.channel = channel
        msg.author.bot = False
        msg.content = "contenido explicito en canal nsfw"

        with (
            patch(
                "cogs.chat.is_channel_ignored",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "cogs.chat.is_corpus_allowed", new_callable=AsyncMock, return_value=True
            ),
            patch.object(
                cog, "_save_message_to_corpus", new_callable=AsyncMock
            ) as mock_save,
        ):
            await cog._on_message_impl(msg)
            mock_save.assert_not_called()

    asyncio.run(_run())


def test_nsfw_channel_blocked_on_refeed():
    async def _run():
        bot = MagicMock()
        cog = Chat(bot)

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 555
        channel.is_nsfw.return_value = True

        res = await cog._refeed_channel_locked(111, channel, max_messages=100)
        assert res["saved"] == 0
        assert res["backfill_complete"] is False

    asyncio.run(_run())


def test_api_rejects_nsfw_channel():
    async def _run():
        class FakeRequest:
            def __init__(self, channel_id):
                self._body = {"channel_id": channel_id}
                self.match_info = {"guild_id": "123"}
                self.headers = {}
                self.remote = "1.2.3.4"

            async def json(self):
                return self._body

        request = FakeRequest(channel_id=999)

        guild = MagicMock(spec=discord.Guild)
        channel_nsfw = MagicMock(spec=discord.TextChannel)
        channel_nsfw.id = 999
        channel_nsfw.is_nsfw.return_value = True
        guild.get_channel.return_value = channel_nsfw

        with (
            patch(
                "webapi.get_session",
                new_callable=AsyncMock,
                return_value={"user_id": "1", "username": "admin"},
            ),
            patch(
                "webapi.check_guild_access", new_callable=AsyncMock, return_value=None
            ),
            patch("webapi._bot_guild", return_value=guild),
            patch("webapi._rate_post", webapi.LRUDict(64)),
        ):
            resp = await webapi._api_corpus_post(request)
            assert resp.status == 400
            assert "nsfw" in resp.text.lower()

    asyncio.run(_run())


def test_forget_user_invalidates_both_user_and_guild_caches(memory_db):
    """Verifica que forget_user purga DB y todas las entradas de caché de usuario y de guild."""

    async def _run():
        guild_id = 700
        author_id = 800

        for i in range(55):
            await db.save_corpus_and_user_message(
                guild_id=guild_id,
                channel_id=1,
                author_id=author_id,
                author_name="victim",
                content=f"mi mensaje {i} que sera olvidado",
                message_id=5000 + i,
            )

        # Cachear modelo general y modelo de usuario
        await generation.build_markov_model(guild_id)
        await generation.generate_markov_for_user(guild_id, author_id)

        assert guild_id in generation._markov_cache
        assert (guild_id, author_id) in generation._user_markov_cache

        # Ejecutar forget_user
        report = await generation.forget_user(author_id)
        assert report["user_corpus_deleted"] == 55

        # Ambas cachés deben estar completamente limpias
        assert guild_id not in generation._markov_cache
        assert (guild_id, author_id) not in generation._user_markov_cache

    asyncio.run(_run())
