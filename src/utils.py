"""Utilidades pequeñas compartidas entre cogs."""

import logging
from collections import OrderedDict

import discord

log = logging.getLogger(__name__)


class LRUDict(OrderedDict):
    """Dict con política LRU: al superar maxsize expulsa la entrada menos usada."""

    def __init__(self, maxsize: int):
        super().__init__()
        self._maxsize = maxsize

    def get(self, key, default=None):
        if key not in self:
            return default
        self.move_to_end(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self._maxsize:
            self.popitem(last=False)


def has_admin_permission(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return interaction.user.guild_permissions.manage_guild


async def report_component_error(
    interaction: discord.Interaction, error: BaseException, source: str
) -> None:
    """`on_error` compartido para botones/selects/modals sin manejador propio.

    `bot.tree.on_error` (ver `cogs/general.py::on_app_command_error`) solo
    cubre slash commands -- es un mecanismo separado de `View.on_error` /
    `Modal.on_error`, y el default de discord.py para estos dos últimos se
    limita a loguear, nunca responde a la interacción. Sin esto, cualquier
    excepción en un callback de botón/select o en `Modal.on_submit` deja al
    usuario viendo el "Esta interacción falló" nativo de Discord, sin
    ninguna explicación -- el mismo problema que el hallazgo #1 de
    AUDITORIA_UX.md (slash commands sin handler global), pero para
    componentes.

    Import de `i18n` diferido adentro de la función: `i18n.py` importa de
    este módulo (`LRUDict`), así que un import a nivel de módulo acá
    generaría un ciclo.
    """
    from i18n import guild_locale, t

    log.error("Error no atajado en %s", source, exc_info=error)
    locale = await guild_locale(interaction.guild.id if interaction.guild else None)
    msg = t("general.error.generic", locale)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        elif (
            interaction.response.type
            is discord.InteractionResponseType.deferred_channel_message
        ):
            await interaction.edit_original_response(content=msg, embed=None, view=None)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except (discord.HTTPException, discord.ClientException):
        log.debug("No se pudo avisar el error de %s al usuario", source, exc_info=True)


class SafeView(discord.ui.View):
    """`discord.ui.View` con `on_error` conectado a `report_component_error`.

    Base para cualquier View del bot en vez de `discord.ui.View` directo:
    así una subclase no tiene que acordarse de definir `on_error` por su
    cuenta (ni un descuido futuro puede dejarlo afuera de nuevo)."""

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        await report_component_error(
            interaction, error, f"{type(self).__name__} (item={item})"
        )


class SafeModal(discord.ui.Modal):
    """Igual que `SafeView` pero para `discord.ui.Modal` (`on_submit`)."""

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        await report_component_error(interaction, error, type(self).__name__)


def chunk_message(text: str, max_length: int = 1900) -> list[str]:
    """Divide un texto largo en fragmentos que Discord pueda aceptar, intentando no cortar palabras."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        chunk = text[:max_length]
        last_newline = chunk.rfind("\n")
        last_space = chunk.rfind(" ")
        cut_index = (
            last_newline
            if last_newline > 0
            else (last_space if last_space > 0 else max_length)
        )
        chunks.append(text[:cut_index].strip())
        text = text[cut_index:].strip()
    return chunks
