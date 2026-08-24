"""Botones de layout V2 con acción funcional (editor de embeds).

A diferencia de Discohook (que solo genera mensajes vía webhook), Purgito es
un bot real y puede procesar el click. Soporta dos tipos de acción funcional:
- role_toggle: alternar un rol (asignar si no lo tiene, quitar si ya lo tiene).
- open_modal: abrir un modal interactivo (formulario emergente) en Discord.

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


class DynamicLayoutModal(discord.ui.Modal):
    def __init__(
        self,
        title: str,
        fields: list[dict] | None = None,
        destination: dict | None = None,
        response_message: str | None = None,
    ):
        super().__init__(title=title[:45] if title else "Formulario")
        self.destination = destination or {"type": "dm_confirmation"}
        self.response_message = response_message
        self.field_inputs: list[tuple[dict, discord.ui.TextInput]] = []
        fields = fields or []
        if not fields:
            inp = discord.ui.TextInput(
                label=title[:45] if title else "Mensaje",
                style=discord.TextStyle.paragraph,
                required=True,
                max_length=1000,
            )
            self.field_inputs.append(
                ({"label": title[:45] if title else "Mensaje"}, inp)
            )
            self.add_item(inp)
        else:
            for f in fields[:5]:
                style = (
                    discord.TextStyle.paragraph
                    if f.get("style") == "paragraph"
                    else discord.TextStyle.short
                )
                kwargs = {
                    "label": str(f.get("label") or "Campo")[:45],
                    "style": style,
                    "placeholder": f.get("placeholder"),
                    "default": f.get("default") or f.get("value"),
                    "required": f.get("required", True),
                    "min_length": f.get("min_length"),
                    "max_length": f.get("max_length") or 1000,
                }
                if f.get("custom_id"):
                    kwargs["custom_id"] = str(f["custom_id"])
                inp = discord.ui.TextInput(**kwargs)
                self.field_inputs.append((f, inp))
                self.add_item(inp)

    @property
    def inputs(self) -> list[discord.ui.TextInput]:
        return [inp for _, inp in self.field_inputs]

    async def on_submit(self, interaction: discord.Interaction):
        locale = await guild_locale(interaction.guild_id)
        guild = interaction.guild

        dest_type = self.destination.get("type", "dm_confirmation")
        if dest_type == "channel" and guild:
            channel_id = self.destination.get("channel_id")
            if channel_id:
                try:
                    cid = int(channel_id)
                    channel = guild.get_channel(cid)
                    if channel is None:
                        try:
                            channel = await guild.fetch_channel(cid)
                        except Exception:
                            channel = None
                    if channel and hasattr(channel, "send"):
                        embed = discord.Embed(
                            title=t(
                                "layout_buttons.modal_response_title",
                                locale,
                                title=self.title,
                            ),
                            color=0x8B6EF5,
                            timestamp=discord.utils.utcnow(),
                        )
                        user = interaction.user
                        avatar_url = (
                            user.display_avatar.url
                            if hasattr(user, "display_avatar")
                            else None
                        )
                        embed.set_author(
                            name=f"{user.display_name} ({user.name})",
                            icon_url=avatar_url,
                        )
                        embed.set_footer(text=f"User ID: {user.id}")

                        for f_cfg, inp in self.field_inputs:
                            flabel = f_cfg.get("label") or "Campo"
                            val = (inp.value or "").strip() or "-"
                            embed.add_field(
                                name=str(flabel)[:256],
                                value=str(val)[:1024],
                                inline=False,
                            )

                        await channel.send(
                            embed=embed,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                except Exception as e:
                    log.warning(
                        "Error al enviar respuesta de modal al canal %s: %s",
                        channel_id,
                        e,
                    )

        msg = self.response_message or t("layout_buttons.modal_submitted", locale)
        await interaction.response.send_message(msg, ephemeral=True)


async def _open_modal(
    interaction: discord.Interaction, guild_id: int, modal_data: dict
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

    title = str(modal_data.get("title") or "Formulario").strip()[:45]
    fields = modal_data.get("fields") or []
    destination = modal_data.get("destination") or {"type": "dm_confirmation"}
    response_msg = modal_data.get("response_message")
    modal = DynamicLayoutModal(
        title=title,
        fields=fields,
        destination=destination,
        response_message=response_msg,
    )
    await interaction.response.send_modal(modal)


def _dispatcher_view(rows: list[dict]) -> discord.ui.View:
    """Un botón "dummy" por fila (mismo custom_id, callback real) — nunca se
    muestra en ningún mensaje, solo existe para que discord.py tenga adónde
    despachar el click cuando llega la interacción."""
    view = discord.ui.View(timeout=None)
    for row in rows:
        action_type = row.get("action_type")
        if action_type == "role_toggle":
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

            async def _cb_role(
                interaction: discord.Interaction,
                guild_id=guild_id,
                role_id=role_id,
            ):
                await _role_toggle(interaction, guild_id, role_id)

            btn.callback = _cb_role
            view.add_item(btn)

        elif action_type == "open_modal":
            try:
                data = json.loads(row["action_data"])
                if not isinstance(data, dict):
                    data = {}
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                log.warning(
                    "layout_button_actions fila open_modal con action_data inválido: %s",
                    row["custom_id"],
                )
                continue
            guild_id = row["guild_id"]
            btn_modal: discord.ui.Button = discord.ui.Button(
                style=discord.ButtonStyle.secondary, custom_id=row["custom_id"]
            )

            async def _cb_modal(
                interaction: discord.Interaction,
                guild_id=guild_id,
                modal_data=data,
            ):
                await _open_modal(interaction, guild_id, modal_data)

            btn_modal.callback = _cb_modal
            view.add_item(btn_modal)

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
