"""Sistema premium_guilds: estado compartido, gestionado desde el panel de administración."""

import logging

from discord.ext import commands

from config import PANEL_URL, PURGATORY_GUILD_ID
from db import apply_premium_webhook_change, list_premium_guilds
from i18n import DEFAULT_LOCALE, t

log = logging.getLogger(__name__)

# Set poblado desde la tabla premium_guilds al cargar el cog; consultado por
# el resto de cogs en cada feature premium.
_premium_guild_ids: set[int] = set()


def is_premium_guild(guild_id: int | None) -> bool:
    """Retorna True si el guild tiene acceso a features premium (memes, pool de imágenes, etc.)."""
    if guild_id == PURGATORY_GUILD_ID:
        return True
    if guild_id is None:
        return False
    return guild_id in _premium_guild_ids


def premium_required_message(locale: str = DEFAULT_LOCALE) -> str:
    """Texto estándar del gate de premium; único lugar donde se redacta."""
    return t("premium.required_message", locale, url=PANEL_URL)


def discard_premium_guild(guild_id: int) -> None:
    _premium_guild_ids.discard(guild_id)


async def set_premium(
    guild_id: int, note: str | None = None, event_at: str | None = None
) -> bool | None:
    """Agrega un guild a premium: escribe en DB y sincroniza el set en memoria.

    `event_at` (timestamp ISO del webhook de Polar que dispara esto, si
    aplica) se pasa a apply_premium_webhook_change para el chequeo de orden
    -- ver su docstring. Retorna None si el evento se descartó por viejo
    (nada que sincronizar), o True/False si era nuevo (igual que antes)."""
    added = await apply_premium_webhook_change(
        guild_id, activate=True, note=note, event_at=event_at
    )
    if added is None:
        return None
    _premium_guild_ids.add(guild_id)
    return added


async def unset_premium(guild_id: int, event_at: str | None = None) -> bool | None:
    """Quita un guild de premium: escribe en DB y sincroniza el set en memoria.

    Mismo contrato que set_premium respecto a event_at y al None de retorno."""
    removed = await apply_premium_webhook_change(
        guild_id, activate=False, note=None, event_at=event_at
    )
    if removed is None:
        return None
    _premium_guild_ids.discard(guild_id)
    return removed


class Premium(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        global _premium_guild_ids
        _premium_guild_ids = {g["guild_id"] for g in await list_premium_guilds()}
        log.info("Servidores premium cargados: %s", _premium_guild_ids)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Premium(bot))
