"""on_command_error (cogs/general.py): el manejador global de errores de los
comandos de prefijo.

Antes solo respondía a 3 excepciones (MissingPermissions, CommandNotFound,
MissingRequiredArgument); cualquier otra -- un argumento inválido, un
cooldown, un check que falla, una excepción dentro del comando -- se
logueaba y el usuario no veía nada. Mismo patrón de fakes que
test_error_handler.py (el de slash commands)."""

import asyncio
import logging
from types import SimpleNamespace

import discord
from discord.ext import commands

from cogs.general import General
from i18n import t


class FakeCtx:
    def __init__(self, has_handler=False, send_error=None):
        self.guild = None
        self.command = SimpleNamespace(
            name="prueba", has_error_handler=lambda: has_handler
        )
        self.sent: list[str] = []
        self._send_error = send_error

    async def send(self, msg):
        if self._send_error:
            raise self._send_error
        self.sent.append(msg)


def _handle(ctx, error):
    asyncio.run(General(SimpleNamespace()).on_command_error(ctx, error))


def _msg(key, **kw):
    return t(key, "es", **kw)


def test_command_not_found_no_responde():
    ctx = FakeCtx()
    _handle(ctx, commands.CommandNotFound())
    assert ctx.sent == []


def test_missing_permissions_avisa_sin_permiso():
    ctx = FakeCtx()
    _handle(ctx, commands.MissingPermissions(["manage_guild"]))
    assert ctx.sent == [_msg("general.error.no_permission")]


def test_missing_argument_avisa_que_faltan_argumentos():
    ctx = FakeCtx()
    param = SimpleNamespace(name="url", displayed_name=None)
    _handle(ctx, commands.MissingRequiredArgument(param))
    assert ctx.sent == [_msg("general.error.missing_argument")]


def test_bad_argument_ahora_responde():
    ctx = FakeCtx()
    _handle(ctx, commands.BadArgument("no es un número"))
    assert ctx.sent == [_msg("general.error.bad_argument")]


def test_cooldown_avisa_cuanto_esperar():
    ctx = FakeCtx()
    error = commands.CommandOnCooldown(
        commands.Cooldown(1, 10), 4.6, commands.BucketType.user
    )
    _handle(ctx, error)
    assert ctx.sent == [_msg("general.error.cooldown", seconds=5)]


def test_check_failure_generico_se_trata_como_falta_de_permiso():
    ctx = FakeCtx()
    _handle(ctx, commands.NotOwner())
    assert ctx.sent == [_msg("general.error.no_permission")]


def test_excepcion_dentro_del_comando_responde_generico_y_loguea_la_causa(caplog):
    ctx = FakeCtx()
    original = ValueError("boom")
    error = commands.CommandInvokeError(original)
    with caplog.at_level(logging.ERROR, logger="cogs.general"):
        _handle(ctx, error)
    assert ctx.sent == [_msg("general.error.generic")]
    rec = next(r for r in caplog.records if "Error en comando" in r.getMessage())
    assert rec.exc_info[1] is original  # la causa real, no el wrapper


def test_comando_con_handler_propio_no_recibe_un_segundo_mensaje():
    """!dl y !gif ya responden en su propio @cmd.error: si este también lo
    hiciera, el usuario vería dos mensajes por el mismo fallo."""
    ctx = FakeCtx(has_handler=True)
    _handle(ctx, commands.CommandInvokeError(ValueError("x")))
    _handle(ctx, commands.BadArgument("x"))
    assert ctx.sent == []


def test_dl_y_gif_tienen_handler_propio_de_verdad():
    """Si alguien les quita el @error, este test avisa: el catch-all de arriba
    pasaría a responderles y los mensajes específicos (cooldown, "ocupado")
    se perderían."""
    from cogs.download import Download
    from cogs.imagefx import ImageFx

    assert Download.dl.has_error_handler()
    assert ImageFx.gif_cmd.has_error_handler()


def test_no_poder_escribir_en_el_canal_no_propaga(caplog):
    forbidden = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "x")
    ctx = FakeCtx(send_error=forbidden)
    _handle(ctx, commands.BadArgument("x"))  # no debe levantar
