"""Botones de layout V2 con acción funcional (Fase 3 del editor de embeds).

A diferencia de Discohook (que solo genera mensajes vía webhook), Purgito es
un bot real y puede procesar el click. v1 acotado a un solo tipo de acción:
alternar un rol (asignar si no lo tiene, quitar si ya lo tiene). Formularios,
respuestas configurables o acciones encadenadas quedan para una fase futura.

Persistencia: los custom_id de botones ya enviados en mensajes viejos necesitan
que discord.py sepa qué callback correr tras un reinicio (`bot.add_view` con
`timeout=None`). Como los layouts son dinámicos (no hay una clase de View fija
por mensaje — el usuario arma el layout en el panel), se registra UNA vista
"despachadora" genérica con un botón por cada fila de layout_button_actions:
discord.py rutea la interacción por custom_id, no le importa que el botón no
sea el mismo objeto Python que el que se mandó originalmente en el mensaje."""

import json
import logging

import discord
from discord.ext import commands

import db
from i18n import guild_locale, t

log = logging.getLogger(__name__)


async def _role_toggle(
    interaction: discord.Interaction, guild_id: int, role_id: int
) -> None:
    guild = interaction.guild
    locale = await guild_locale(guild.id if guild else None)
    if (
        guild is None
        or guild.id != guild_id
        or not isinstance(interaction.user, discord.Member)
    ):
        await interaction.response.send_message(
            t("layout_buttons.invalid_context", locale), ephemeral=True
        )
        return
    role = guild.get_role(role_id)
    if role is None:
        await interaction.response.send_message(
            t("layout_buttons.role_gone", locale), ephemeral=True
        )
        return
    me = guild.me
    if not me.guild_permissions.manage_roles or role.position >= me.top_role.position:
        await interaction.response.send_message(
            t("layout_buttons.missing_permissions", locale),
            ephemeral=True,
        )
        return
    member = interaction.user
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Purgito: botón de rol (panel)")
            await interaction.response.send_message(
                t("layout_buttons.role_removed", locale, role=role.mention),
                ephemeral=True,
            )
        else:
            await member.add_roles(role, reason="Purgito: botón de rol (panel)")
            await interaction.response.send_message(
                t("layout_buttons.role_assigned", locale, role=role.mention),
                ephemeral=True,
            )
    except discord.Forbidden:
        await interaction.response.send_message(
            t("layout_buttons.role_change_forbidden", locale), ephemeral=True
        )


def _dispatcher_view(rows: list[dict]) -> discord.ui.View:
    """Un botón "dummy" por fila (mismo custom_id, callback real) — nunca se
    muestra en ningún mensaje, solo existe para que discord.py tenga adónde
    despachar el click cuando llega la interacción."""
    view = discord.ui.View(timeout=None)
    for row in rows:
        if row["action_type"] != "role_toggle":
            continue
        try:
            role_id = int(json.loads(row["action_data"])["role_id"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            log.warning(
                "layout_button_actions fila con action_data inválido: %s",
                row["custom_id"],
            )
            continue
        guild_id = row["guild_id"]
        btn: discord.ui.Button = discord.ui.Button(
            style=discord.ButtonStyle.secondary, custom_id=row["custom_id"]
        )

        async def _cb(
            interaction: discord.Interaction, guild_id=guild_id, role_id=role_id
        ):
            await _role_toggle(interaction, guild_id, role_id)

        btn.callback = _cb
        view.add_item(btn)
    return view


async def register_button_actions(bot: commands.Bot, rows: list[dict]) -> None:
    """Registra (bot.add_view) una vista persistente para las filas dadas.

    Se usa en dos momentos: al arrancar el bot (todas las filas guardadas, ver
    cog_load) y en caliente apenas se crea un botón de rol nuevo (webapi.py) —
    así funciona de inmediato sin esperar el próximo reinicio."""
    if not rows:
        return
    bot.add_view(_dispatcher_view(rows))


class LayoutButtons(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        rows = await db.list_button_actions()
        await register_button_actions(self.bot, rows)
        if rows:
            log.info("Registrados %d botones de layout persistentes", len(rows))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LayoutButtons(bot))
