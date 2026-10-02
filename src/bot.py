"""Punto de entrada de Purgito.

Toda la funcionalidad vive en extensiones (src/cogs/); aquí solo se configura
logging, se inicializa la DB y se cargan las extensiones.
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

import discord
from discord.ext import commands

import config  # ejecuta load_dotenv() al importarse
import i18n
import r2
import webapi
from observability import events as obs_events
from observability import hooks as obs_hooks
from observability import logging_setup as obs_logging
from observability import runtime as obs_runtime
from observability import service_state as obs_state
from db import (
    DEFAULT_COMMAND_PREFIX,
    close_db,
    get_guild_prefix,
    get_lifecycle_state,
    init_db,
    set_lifecycle_state,
)

# Configurar logging (texto legible + redacción de secretos; los JSONL de
# eventos se activan en _main, ver observability/runtime.py)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
obs_logging.setup_text_logging(_DATA_DIR)

log = logging.getLogger(__name__)

EXTENSIONS = [
    "cogs.premium",  # primero: expone is_premium_guild al resto
    "cogs.chat",
    "cogs.gifs",
    "cogs.memes",
    "cogs.youtube",
    "cogs.twitch",
    "cogs.rss",
    "cogs.anuncios",
    "cogs.general",
    "cogs.download",
    "cogs.imagefx",
    "cogs.settings",
    "cogs.layout_buttons",
    "cogs.privacy",
    "cogs.updates",
    "cogs.quota_alerts",
    "cogs.events",
]

intents = discord.Intents.default()
intents.message_content = config.ENABLE_MESSAGE_CONTENT
intents.members = True


class PurgitoBot(commands.Bot):
    async def setup_hook(self) -> None:
        try:
            await init_db()
        except Exception as exc:
            obs_hooks.db_connection_failed(exc, "init_db")
            raise
        await self.tree.set_translator(i18n.CommandTranslator())
        for extension in EXTENSIONS:
            await self.load_extension(extension)
            log.info("Extensión cargada: %s", extension)

    async def close(self) -> None:
        await webapi.stop_web_server()
        log.info("Cerrando conexión a la base de datos...")
        await close_db()
        await super().close()
        _mark_stopped()


async def get_prefix(_bot: commands.Bot, message: discord.Message) -> list[str]:
    """Símbolo (custom por guild, default "!") + prefijo de palabra fijo
    ("purgito ", de config.BOT_TRIGGER_NAME) -- mismo trigger que ya usa el
    texto de memes ("purgito generar"), así no hay un segundo concepto de
    "palabra mágica" por separado. Fuera de un guild (DM) solo el símbolo
    default: no hay guild_id para resolver un custom_prefix.

    El prefijo de palabra se busca sin importar mayúsculas/minúsculas (igual
    que is_meme_trigger en cogs/memes.py) pero se devuelve con el casing
    exacto que escribió el usuario ("Purgito dl", "PURGITO dl", etc.):
    discord.py compara cada prefijo devuelto contra message.content con un
    startswith case-sensitive, así que un "purgito " fijo en minúsculas
    dejaría afuera cualquier variante con mayúsculas."""
    symbol = DEFAULT_COMMAND_PREFIX
    if message.guild is not None:
        symbol = await get_guild_prefix(message.guild.id) or DEFAULT_COMMAND_PREFIX
    word_prefix = f"{config.BOT_TRIGGER_NAME} "
    content = message.content or ""
    if content.lower().startswith(word_prefix):
        word_prefix = content[: len(word_prefix)]
    return [symbol, word_prefix]


bot = PurgitoBot(command_prefix=get_prefix, intents=intents)
bot.remove_command("help")


_commands_synced = False


def _mark_stopped() -> None:
    """Cierre limpio en el archivo de estado -- SOLO si el apagado fue
    intencional (SIGTERM/SIGINT). Un close() por error fatal no lo marca, así
    el próximo arranque lo detecta como caída."""
    if not _shutdown_in_progress:
        return
    state = obs_state.get()
    if state is not None:
        state.stop_heartbeat()
        state.set_state("stopped")
    obs_events.log_event("service.stopped")


def _format_downtime(since_iso: str) -> str:
    try:
        since = datetime.fromisoformat(since_iso)
    except ValueError:
        return "un tiempo"
    seconds = max(0, int((datetime.now(timezone.utc) - since).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h"
    days = hours // 24
    return f"{days} día{'s' if days != 1 else ''}"


async def _send_lifecycle_notice(content: str) -> None:
    """Best-effort: nunca propaga -- ni el arranque ni el apagado deben
    trabarse porque Discord no responda o el canal no exista."""
    if config.LIFECYCLE_ANNOUNCE_CHANNEL_ID is None:
        return  # avisos apagados (LIFECYCLE_ANNOUNCE_CHANNEL_ID vacío o 0)
    channel = bot.get_channel(config.LIFECYCLE_ANNOUNCE_CHANNEL_ID)
    if channel is None:
        try:
            channel = await asyncio.wait_for(
                bot.fetch_channel(config.LIFECYCLE_ANNOUNCE_CHANNEL_ID), timeout=3
            )
        except Exception:
            log.warning(
                "No se pudo obtener el canal de lifecycle %s",
                config.LIFECYCLE_ANNOUNCE_CHANNEL_ID,
            )
            return
    try:
        await asyncio.wait_for(channel.send(content), timeout=3)
    except Exception:
        log.warning("No se pudo enviar el aviso de lifecycle", exc_info=True)


_lifecycle_reported = False


async def _report_lifecycle() -> None:
    """Compara contra el último estado guardado para avisar si el bot volvió
    de un apagado intencional o de una caída inesperada, y deja la marca en
    False (corriendo) para la próxima vez. Solo una vez por proceso -- on_ready
    también se dispara al reconectar."""
    global _lifecycle_reported
    if _lifecycle_reported:
        return
    _lifecycle_reported = True

    try:
        prev = await get_lifecycle_state()
    except Exception:
        log.exception("No se pudo leer lifecycle_state")
        prev = None

    if prev is not None:
        downtime = _format_downtime(prev["updated_at"])
        if prev["clean_shutdown"]:
            msg = f"✅ Purgito volvió (reinicio intencional) — estuvo abajo {downtime}."
        else:
            msg = f"⚠️ Purgito volvió después de una caída inesperada — estuvo abajo {downtime}."
        await _send_lifecycle_notice(msg)

    try:
        await set_lifecycle_state(clean_shutdown=False)
    except Exception:
        log.exception("No se pudo escribir lifecycle_state al arrancar")


_shutdown_in_progress = False
_previous_run: dict = {}


async def _handle_shutdown_signal(sig: signal.Signals) -> None:
    """SIGTERM (systemctl stop/restart) o SIGINT (Ctrl+C en desarrollo):
    marca el apagado como intencional ANTES de cerrar, para que el próximo
    arranque no lo reporte como caída. Se ejecuta como máximo una vez."""
    global _shutdown_in_progress
    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True
    log.info("Señal %s recibida: apagado intencional", sig.name)
    obs_events.log_event("service.stopping", signal=sig.name)
    state = obs_state.get()
    if state is not None:
        state.set_state("stopping")

    try:
        await set_lifecycle_state(clean_shutdown=True)
    except Exception:
        log.exception("No se pudo marcar clean_shutdown antes de apagar")

    await _send_lifecycle_notice(
        "🛑 Purgito se está apagando (parada/reinicio intencional)."
    )
    await bot.close()


def _register_shutdown_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.ensure_future(_handle_shutdown_signal(s))
            )
        except NotImplementedError:
            # Windows: loop.add_signal_handler no está soportado ahí: Ctrl+C
            # local sigue funcionando por el KeyboardInterrupt normal de asyncio.run().
            log.debug(
                "No se pudo registrar el handler de apagado para %s en este SO",
                sig.name,
            )


@bot.event
async def on_ready():
    global _commands_synced
    for warning in r2.config_warnings():
        log.warning(warning)

    # Solo una vez por proceso: on_ready también se dispara al reconectar, y
    # re-sincronizar en cada reconexión puede agotar el rate limit de Discord.
    if not _commands_synced:
        try:
            log.info("Iniciando sincronización de comandos")

            # Sync global siempre — necesario para que cualquier servidor nuevo reciba los comandos.
            synced = await bot.tree.sync()
            log.info("Sync global: %s", [c.name for c in synced])

            if config.GUILD_ID_ENV:
                # Sync instantáneo adicional a tu servidor de desarrollo (no reemplaza al global).
                guild_obj = discord.Object(id=int(config.GUILD_ID_ENV))
                bot.tree.copy_global_to(guild=guild_obj)
                guild_synced = await bot.tree.sync(guild=guild_obj)
                log.info(
                    "Sync instantáneo al servidor %s: %s",
                    config.GUILD_ID_ENV,
                    [c.name for c in guild_synced],
                )

            _commands_synced = True
        except Exception:
            log.exception("Error en la sincronización de comandos")

    log.info("Bot listo como %s", bot.user)
    obs_events.log_event("discord.ready", guilds=len(bot.guilds))

    # Después de on_ready los guilds ya están cacheados; start_web_server es
    # idempotente, así que reconexiones (on_ready repetido) no lo duplican.
    try:
        await webapi.start_web_server(bot)
    except Exception:
        log.exception("Error iniciando el servidor web")

    await _report_lifecycle()
    _announce_started_once()


_started_announced = False


def _announce_started_once() -> None:
    """service.started: una vez por proceso, cuando ya está todo arriba."""
    global _started_announced
    if _started_announced:
        return
    _started_announced = True
    state = obs_state.get()
    if state is not None:
        state.set_state("running")
    obs_runtime.announce_start(_previous_run)


@bot.event
async def on_disconnect():
    obs_events.log_event("discord.disconnected")


async def _main() -> None:
    # Los handlers de SIGTERM/SIGINT se registran ANTES de arrancar el bot:
    # si la señal llega apenas conectado (o incluso antes), igual se marca
    # clean_shutdown y se intenta cerrar en vez de morir sin avisar.
    global _previous_run
    _previous_run = obs_runtime.init(_DATA_DIR)
    state = obs_state.get()
    if state is not None:
        state.start_heartbeat()
    loop = asyncio.get_running_loop()
    _register_shutdown_handlers(loop)
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    if not config.TOKEN:
        log.critical(
            "Falta DISCORD_TOKEN en .env. Copia .env.example a .env e introduce tu token."
        )
        sys.exit(1)
    try:
        asyncio.run(_main())
    except discord.errors.LoginFailure:
        log.critical("Token inválido. Verifica DISCORD_TOKEN en .env.")
        sys.exit(1)
    except KeyboardInterrupt:
        # Solo llega acá si add_signal_handler no está disponible (Windows);
        # en Linux el SIGINT ya lo maneja _handle_shutdown_signal.
        pass
