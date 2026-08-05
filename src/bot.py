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
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands

import config  # ejecuta load_dotenv() al importarse
import r2
import webapi
from db import close_db, get_lifecycle_state, init_db, set_lifecycle_state

# Configurar logging
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_PATH = os.path.join(_BASE_DIR, "data", "bot.log")
os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)

_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
_fh = RotatingFileHandler(
    _LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

EXTENSIONS = [
    "cogs.premium",  # primero: expone is_premium_guild al resto
    "cogs.chat",
    "cogs.gifs",
    "cogs.memes",
    "cogs.youtube",
    "cogs.anuncios",
    "cogs.general",
    "cogs.settings",
    "cogs.layout_buttons",
]

intents = discord.Intents.default()
intents.message_content = config.ENABLE_MESSAGE_CONTENT


class PurgitoBot(commands.Bot):
    async def setup_hook(self) -> None:
        await init_db()
        for extension in EXTENSIONS:
            await self.load_extension(extension)
            log.info("Extensión cargada: %s", extension)

    async def close(self) -> None:
        await webapi.stop_web_server()
        log.info("Cerrando conexión a la base de datos...")
        await close_db()
        await super().close()


bot = PurgitoBot(command_prefix="!", intents=intents)
bot.remove_command("help")


_commands_synced = False


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


async def _handle_shutdown_signal(sig: signal.Signals) -> None:
    """SIGTERM (systemctl stop/restart) o SIGINT (Ctrl+C en desarrollo):
    marca el apagado como intencional ANTES de cerrar, para que el próximo
    arranque no lo reporte como caída. Se ejecuta como máximo una vez."""
    global _shutdown_in_progress
    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True
    log.info("Señal %s recibida: apagado intencional", sig.name)

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
    if not r2.available():
        log.warning(
            "R2 no configurado: las imágenes de Discord CDN se guardarán con su URL original "
            "(pueden expirar). Configura R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
            "R2_BUCKET_NAME y R2_PUBLIC_URL para persistencia permanente."
        )

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

    # Después de on_ready los guilds ya están cacheados; start_web_server es
    # idempotente, así que reconexiones (on_ready repetido) no lo duplican.
    try:
        await webapi.start_web_server(bot)
    except Exception:
        log.exception("Error iniciando el servidor web")

    await _report_lifecycle()


async def _main() -> None:
    # Los handlers de SIGTERM/SIGINT se registran ANTES de arrancar el bot:
    # si la señal llega apenas conectado (o incluso antes), igual se marca
    # clean_shutdown y se intenta cerrar en vez de morir sin avisar.
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
