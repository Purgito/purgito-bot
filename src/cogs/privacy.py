"""Privacy: /borrar_mis_datos -- interfaz de Discord del Right to be
Forgotten individual. El núcleo de borrado vive en db.delete_user_data /
generation.forget_user (ya implementados y testeados); este cog es solo
presentación, confirmación de dos pasos y manejo de errores -- no reimplementa
ninguna lógica de borrado."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import generation
from help_view import PURGITO_COLOR
from i18n import guild_locale, t

log = logging.getLogger(__name__)


class _ConfirmDeleteView(discord.ui.View):
    """Confirmación de dos pasos sobre el MISMO botón: el primer click en
    "Eliminar mis datos" solo lo arma (lo relabelea y pide un segundo click)
    -- ningún click aislado dispara el borrado real. Mismo timeout/patrón de
    on_timeout que HelpView (help_view.py) y mismo interaction_check por
    author_id que SettingsPanel (cogs/settings.py).

    interaction_check exige interaction.user.id == self.author_id, capturado
    de interaction.user.id en el momento en que se ejecutó /borrar_mis_datos
    -- una tercera persona que pulse cualquiera de los dos botones nunca
    llega a _on_delete/_on_cancel."""

    def __init__(self, author_id: int, locale: str):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.locale = locale
        self.message: discord.Message | None = None
        self._armed = False

        self.delete_button = discord.ui.Button(
            label=t("privacy.delete.button_start", locale),
            style=discord.ButtonStyle.danger,
        )
        self.delete_button.callback = self._on_delete
        self.cancel_button = discord.ui.Button(
            label=t("privacy.delete.button_cancel", locale),
            style=discord.ButtonStyle.secondary,
        )
        self.cancel_button.callback = self._on_cancel
        self.add_item(self.delete_button)
        self.add_item(self.cancel_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                t("privacy.delete.not_your_request", self.locale), ephemeral=True
            )
            return False
        return True

    def _disable_all(self) -> None:
        for item in self.children:
            item.disabled = True

    async def on_timeout(self) -> None:
        self._disable_all()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        self._disable_all()
        await interaction.response.edit_message(
            content=t("privacy.delete.cancelled", self.locale),
            embed=None,
            view=self,
        )

    async def _on_delete(self, interaction: discord.Interaction) -> None:
        if not self._armed:
            # Primer click: solo arma el botón, todavía no borra nada.
            self._armed = True
            self.delete_button.label = t("privacy.delete.button_confirm", self.locale)
            await interaction.response.edit_message(
                content=t("privacy.delete.confirm_again", self.locale), view=self
            )
            return

        # Segundo click sobre el mismo botón ya armado: acá sí se borra.
        self.stop()
        self._disable_all()
        # forget_user borra en SQLite (varias tablas) y después recorre los
        # guilds afectados invalidando caches -- puede superar los 3s que da
        # Discord antes de expirar la interacción, así que se difiere primero.
        await interaction.response.defer()
        try:
            report = await generation.forget_user(self.author_id)
        except Exception:
            # Nunca se muestra el detalle real (stack trace) al usuario --
            # solo queda en el log del proceso, sin contenido de mensajes.
            log.exception(
                "privacy.user_delete: fallo borrando datos de author_id=%s",
                self.author_id,
            )
            await interaction.edit_original_response(
                content=t("privacy.delete.error", self.locale),
                embed=None,
                view=self,
            )
            return

        # Log de proceso, no fila de audit_log: audit_log es NOT NULL
        # guild_id (pensada para "quién tocó qué config de ESTE servidor",
        # visible a los admins de ese guild vía el dashboard) y este borrado
        # es global, cruza guilds. Meter ahí "el usuario X pidió su RTBF"
        # expondría ese hecho a los admins de cada guild afectado sin que
        # eso aporte nada a la auditoría de configuración del servidor -- es
        # un dato sensible de más, no una decisión de retención que este
        # cambio deba tomar. Si en algún momento se quiere un trail de
        # auditoría de solicitudes de RTBF (para el propio operador de
        # Purgito, no por-guild), es una tabla/política aparte a decidir,
        # no un overload de audit_log.
        log.info(
            "privacy.user_delete: author_id=%s user_corpus_deleted=%d "
            "corpus_messages_deleted=%d guilds_affected=%d",
            self.author_id,
            report["user_corpus_deleted"],
            report["corpus_messages_deleted"],
            len(report["guild_ids"]),
        )

        if report["user_corpus_deleted"] == 0:
            result = t("privacy.delete.result_empty", self.locale)
        else:
            result = t(
                "privacy.delete.result_success",
                self.locale,
                user_corpus_deleted=report["user_corpus_deleted"],
                guilds=len(report["guild_ids"]),
            )
        await interaction.edit_original_response(content=result, embed=None, view=self)


class Privacy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="borrar_mis_datos",
        description="Elimina permanentemente tus datos guardados por Purgito.",
    )
    async def borrar_mis_datos(self, interaction: discord.Interaction) -> None:
        locale = await guild_locale(interaction.guild.id if interaction.guild else None)
        if not interaction.guild:
            await interaction.response.send_message(
                t("general.guild_only", locale), ephemeral=True
            )
            return

        embed = discord.Embed(
            title=t("privacy.delete.title", locale),
            description=t("privacy.delete.body", locale),
            color=PURGITO_COLOR,
        )
        view = _ConfirmDeleteView(author_id=interaction.user.id, locale=locale)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Privacy(bot))
