"""Tests del manejador global de errores de slash commands (cogs/general.py).

Mismo patrón que test_chat_muted.py: fakes mínimos con SimpleNamespace,
asyncio.run para el flujo async, sin bot ni red.
"""

import asyncio
import logging
from types import SimpleNamespace

import discord
from discord import app_commands

from cogs.general import General


class FakeInteraction:
    def __init__(self, done=False, rtype=None):
        self.command = SimpleNamespace(name="prueba")
        self.guild = None
        self.edited: list[str] = []
        self.followup_sent: list[tuple] = []
        self.resp_sent: list[tuple] = []

        async def _send_message(msg, ephemeral=False):
            self.resp_sent.append((msg, ephemeral))

        self.response = SimpleNamespace(
            is_done=lambda: done,
            type=rtype,
            send_message=_send_message,
        )

        async def _followup_send(msg, ephemeral=False):
            self.followup_sent.append((msg, ephemeral))

        self.followup = SimpleNamespace(send=_followup_send)

    async def edit_original_response(self, content=None, embed=None, view=None):
        self.edited.append(content)


def _cog() -> General:
    return General(SimpleNamespace())


def _wrap(exc: Exception) -> app_commands.CommandInvokeError:
    cmd = SimpleNamespace(name="prueba", qualified_name="prueba")
    return app_commands.CommandInvokeError(cmd, exc)


def test_unwraps_original_before_logging(caplog):
    original = ValueError("boom")
    inter = FakeInteraction(done=False)
    with caplog.at_level(logging.ERROR, logger="cogs.general"):
        asyncio.run(_cog().on_app_command_error(inter, _wrap(original)))
    rec = next(r for r in caplog.records if "slash command" in r.getMessage())
    # Se loguea la causa real, no el wrapper CommandInvokeError.
    assert rec.exc_info[1] is original


def test_not_done_uses_ephemeral_send_message():
    inter = FakeInteraction(done=False)
    asyncio.run(_cog().on_app_command_error(inter, _wrap(ValueError())))
    assert len(inter.resp_sent) == 1
    assert inter.resp_sent[0][1] is True  # ephemeral
    assert inter.edited == [] and inter.followup_sent == []


def test_pending_defer_edits_original_response():
    # Caso normal del "pensando…" colgado: defer sin contenido real todavía.
    inter = FakeInteraction(
        done=True, rtype=discord.InteractionResponseType.deferred_channel_message
    )
    asyncio.run(_cog().on_app_command_error(inter, _wrap(ValueError())))
    assert len(inter.edited) == 1
    assert inter.followup_sent == [] and inter.resp_sent == []


def test_error_handler_does_not_clobber_existing_response():
    # El comando ya respondió con contenido real (ej. /help y su embed) y el
    # error llega después: la respuesta buena queda intacta, el error va aparte.
    inter = FakeInteraction(
        done=True, rtype=discord.InteractionResponseType.channel_message
    )
    asyncio.run(_cog().on_app_command_error(inter, _wrap(ValueError())))
    assert inter.edited == []  # NO se editó el mensaje existente
    assert len(inter.followup_sent) == 1
    assert inter.followup_sent[0][1] is True  # ephemeral


def test_expired_interaction_logs_debug_and_swallows(caplog):
    inter = FakeInteraction(done=False)

    async def _expired(msg, ephemeral=False):
        raise discord.NotFound(
            SimpleNamespace(status=404, reason="Not Found"), "unknown interaction"
        )

    inter.response.send_message = _expired
    with caplog.at_level(logging.DEBUG, logger="cogs.general"):
        # No debe propagar la NotFound.
        asyncio.run(_cog().on_app_command_error(inter, _wrap(ValueError())))
    assert any(
        r.levelno == logging.DEBUG and "No se pudo avisar" in r.getMessage()
        for r in caplog.records
    )
