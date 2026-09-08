"""Privacy: /borrar_mis_datos (Right to be Forgotten) y /mis_datos (su
complemento simétrico de portabilidad). El núcleo de cada uno vive en
generation.forget_user / db.export_user_data (ya implementados y
testeados); este cog es solo presentación, confirmación de dos pasos donde
aplica, y manejo de errores -- no reimplementa ninguna lógica."""

import io
import json
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import generation
from db import export_user_data
from help_view import PURGITO_COLOR
from i18n import guild_locale, t
from utils import LRUDict

log = logging.getLogger(__name__)

# Genera y adjunta un JSON -- sin límite, cualquiera podía disparar esto en
# loop. No hace falta que sea estricto: es un pedido legítimo poco frecuente
# en la práctica, esto solo corta un abuso obvio.
_EXPORT_COOLDOWN_SECONDS = 60
_export_cooldowns: LRUDict = LRUDict(1024)


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


def _check_export_cooldown(user_id: int) -> int | None:
    """None si puede exportar (y marca el cooldown); si no, segundos restantes."""
    now = time.time()
    elapsed = now - _export_cooldowns.get(user_id, 0)
    if elapsed < _EXPORT_COOLDOWN_SECONDS:
        return int(_EXPORT_COOLDOWN_SECONDS - elapsed)
    _export_cooldowns[user_id] = now
    return None


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

    @app_commands.command(
        name="mis_datos",
        description="Descarga en JSON tu estilo guardado y los mensajes que Purgito aprendió de ti.",
    )
    async def mis_datos(self, interaction: discord.Interaction) -> None:
        locale = await guild_locale(interaction.guild.id if interaction.guild else None)

        remaining = _check_export_cooldown(interaction.user.id)
        if remaining is not None:
            await interaction.response.send_message(
                t("privacy.export.cooldown", locale, seconds=remaining),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            by_guild = await export_user_data(interaction.user.id)
        except Exception:
            log.exception(
                "privacy.user_export: fallo exportando datos de author_id=%s",
                interaction.user.id,
            )
            await interaction.followup.send(
                t("privacy.export.error", locale), ephemeral=True
            )
            return

        total_messages = sum(len(rows) for rows in by_guild.values())
        if total_messages == 0:
            await interaction.followup.send(
                t("privacy.export.empty", locale), ephemeral=True
            )
            return

        payload = {
            "user_id": str(interaction.user.id),
            "exported_at": discord.utils.utcnow().isoformat(),
            "servers": [
                {
                    "guild_id": str(guild_id),
                    "guild_name": getattr(self.bot.get_guild(guild_id), "name", None),
                    "messages": rows,
                }
                for guild_id, rows in by_guild.items()
            ],
        }
        buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode())
        log.info(
            "privacy.user_export: author_id=%s messages=%d guilds=%d",
            interaction.user.id,
            total_messages,
            len(by_guild),
        )
        await interaction.followup.send(
            t(
                "privacy.export.result",
                locale,
                count=total_messages,
                guilds=len(by_guild),
            ),
            file=discord.File(buf, filename="purgito_mis_datos.json"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Privacy(bot))
