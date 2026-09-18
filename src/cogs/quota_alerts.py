"""Avisa en el canal de actualizaciones cuando un servidor se acerca o llega
al tope de un cupo que bloquea agregar más contenido (GIFs, frases
especiales). El corpus de mensajes aprendidos queda afuera a propósito: al
llegar a su límite simplemente rota los mensajes más viejos en vez de
trabar nada, así que no hay ninguna acción urgente que avisar ahí (mismo
criterio que ya usa el punto de cupo de la sidebar del dashboard, ver
QUOTA_ALERT_MODULES en dash.js)."""

import logging
import time

import discord
from discord.ext import commands, tasks

import i18n
from db import (
    count_gif_urls,
    frases_limit,
    gifs_limit,
    list_all_updates_channels,
    list_frases_especiales,
)
from utils import LRUDict

log = logging.getLogger(__name__)

# Mismo umbral que ya usa el dashboard para pintar "cerca del cupo" (ver
# _api_stats en webapi.py): 90% = cerca, 100% = lleno.
_NEAR_RATIO = 0.9

# No repetir el mismo aviso en cada corrida del loop mientras el servidor
# siga en la misma franja -- in-memory a propósito, mismo patrón que el
# resto de los cooldowns del bot (GROQ_GUILD_COOLDOWN, _EXPORT_COOLDOWN_SECONDS,
# etc.): perder el historial en un restart cuesta como mucho un aviso de
# más cada tanto, no justifica una tabla nueva solo para esto.
_ALERT_COOLDOWN_SECONDS = 24 * 60 * 60
_alert_cooldowns: LRUDict = LRUDict(2048)


def _quota_status(used: int, cap: int) -> str | None:
    if cap <= 0:
        return None
    if used >= cap:
        return "full"
    if used >= cap * _NEAR_RATIO:
        return "near"
    return None


class QuotaAlerts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.check_quotas.start()

    async def cog_unload(self) -> None:
        self.check_quotas.cancel()

    @tasks.loop(hours=6)
    async def check_quotas(self):
        # Reusa la lista de canales de updates ya configurados: no tiene
        # sentido calcular el cupo de un servidor que no tiene dónde
        # recibir el aviso, y así un admin no tiene que configurar un
        # segundo canal solo para esto (el canal de updates ya se describe
        # en el dashboard como "avisos importantes", no solo relanzamientos
        # oficiales del bot).
        destinations = await list_all_updates_channels()
        for dest in destinations:
            guild_id = dest.get("guild_id")
            channel_id = dest.get("channel_id")
            if not guild_id or not channel_id:
                continue
            try:
                await self._check_guild(guild_id, channel_id)
            except Exception:
                log.exception("Error chequeando cupos del guild %s", guild_id)

    async def _check_guild(self, guild_id: int, channel_id: int) -> None:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            return
        bot_member = getattr(guild, "me", None)
        if bot_member is None or not channel.permissions_for(bot_member).send_messages:
            return

        checks = [
            ("gifs", await count_gif_urls(guild_id), gifs_limit(guild_id)),
            (
                "frases",
                len(await list_frases_especiales(guild_id)),
                frases_limit(guild_id),
            ),
        ]

        locale = await i18n.guild_locale(guild_id)
        for quota_type, used, cap in checks:
            status = _quota_status(used, cap)
            if status is None:
                continue

            key = (guild_id, quota_type, status)
            now = time.monotonic()
            last = _alert_cooldowns.get(key)
            if last is not None and now - last < _ALERT_COOLDOWN_SECONDS:
                continue
            _alert_cooldowns[key] = now

            try:
                await channel.send(
                    i18n.t(
                        f"quota_alerts.{status}",
                        locale,
                        quota=i18n.t(f"quota_alerts.type.{quota_type}", locale),
                        used=f"{used:,}",
                        cap=f"{cap:,}",
                    )
                )
            except discord.Forbidden:
                log.warning(
                    "Sin permiso para avisar cupo en guild %s canal %s",
                    guild_id,
                    channel_id,
                )
            except discord.HTTPException:
                log.exception(
                    "Error de Discord avisando cupo en guild %s canal %s",
                    guild_id,
                    channel_id,
                )

    @check_quotas.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    @check_quotas.error
    async def _on_check_quotas_error(self, error: BaseException) -> None:
        # Sin este handler, una excepción fuera del set que discord.py
        # reintenta solo (ver Loop._valid_exception) mata el loop para
        # siempre en silencio -- acá tarda hasta 6h en notarse.
        log.exception("check_quotas se cayó, reiniciando el loop", exc_info=error)
        self.check_quotas.restart()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuotaAlerts(bot))
