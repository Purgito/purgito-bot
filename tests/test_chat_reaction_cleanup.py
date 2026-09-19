"""Reacción aleatoria del chat (reaction_pool): un emoji custom borrado del
servidor de origen hace que Discord responda 'Unknown Emoji' (400/10014) cada
vez que se sortea -- para siempre, ya que nunca va a volver a existir. Estos
tests cubren que ese caso puntual se auto-limpia del pool en vez de reintentar
por siempre, y que ningún error de Discord al reaccionar tira abajo el resto
de _on_message_impl."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import db
from cogs.chat import Chat


@pytest.fixture
def memory_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_bot.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def _make_message(guild_id, channel_id, author_id):
    channel = MagicMock()
    channel.id = channel_id
    channel.is_nsfw.return_value = False

    msg = MagicMock()
    msg.id = 993
    msg.guild.id = guild_id
    msg.channel = channel
    msg.author.bot = False
    msg.author.id = author_id
    msg.author.display_name = "User"
    msg.content = "Un mensaje cualquiera bastante normal para el corpus de prueba."
    msg.raw_mentions = []
    msg.reference = None
    return msg


async def _run_on_message_with_reaction_error(cog, msg, add_reaction_exc):
    with (
        patch(
            "cogs.chat.is_channel_ignored", new_callable=AsyncMock, return_value=False
        ),
        patch(
            "cogs.chat.is_corpus_allowed", new_callable=AsyncMock, return_value=False
        ),
        patch.object(
            cog, "_handle_trigger", new_callable=AsyncMock, return_value=False
        ),
        patch.object(
            msg, "add_reaction", new_callable=AsyncMock, side_effect=add_reaction_exc
        ),
    ):
        await cog._on_message_impl(msg)  # no debe propagar la excepción


def test_unknown_emoji_reaction_is_removed_from_pool(memory_db, caplog):
    async def _run():
        bot = MagicMock()
        bot.user.id = 12345
        cog = Chat(bot)
        guild_id = 5301

        await db.add_reaction_to_pool(guild_id, "<:borrado:123456789012345678>")
        await db.set_chat_tunables(guild_id, {"reaction_probability": 1.0})

        msg = _make_message(guild_id, 7301, 6301)
        exc = discord.HTTPException(
            SimpleNamespace(status=400, reason=""),
            {"code": 10014, "message": "Unknown Emoji"},
        )

        with caplog.at_level(logging.WARNING, logger="cogs.chat"):
            await _run_on_message_with_reaction_error(cog, msg, exc)

        # El emoji borrado nunca va a volver a funcionar: sale del pool solo.
        assert await db.list_reaction_pool(guild_id) == []
        # Foreseeable (ya se maneja): warning conciso, no traceback de ERROR.
        assert any(r.levelname == "WARNING" for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

    asyncio.run(_run())


def test_other_reaction_error_keeps_pool_entry(memory_db, caplog):
    async def _run():
        bot = MagicMock()
        bot.user.id = 12345
        cog = Chat(bot)
        guild_id = 5302

        await db.add_reaction_to_pool(guild_id, "👍")
        await db.set_chat_tunables(guild_id, {"reaction_probability": 1.0})

        msg = _make_message(guild_id, 7302, 6302)
        exc = discord.Forbidden(
            SimpleNamespace(status=403, reason=""), "Missing Permissions"
        )

        with caplog.at_level(logging.WARNING, logger="cogs.chat"):
            await _run_on_message_with_reaction_error(cog, msg, exc)

        # Forbidden es sobre permisos del bot, no del emoji: la reacción
        # sigue siendo válida y no se saca del pool.
        pool = await db.list_reaction_pool(guild_id)
        assert len(pool) == 1
        assert any(r.levelname == "WARNING" for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

    asyncio.run(_run())
