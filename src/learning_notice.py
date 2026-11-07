"""Aviso y confirmación del administrador al ACTIVAR el aprendizaje de un canal.

Activar el aprendizaje es siempre explícito (nunca automático) y se hace desde /settings, el asistente
/setup o el dashboard. Antes de guardar el canal, el administrador confirma un aviso que le dice qué va a
guardar Purgito, por cuánto tiempo, que las personas pueden excluirse y pedir la eliminación de sus datos, y
que él debe informar a los miembros. La confirmación queda en el registro de auditoría del servidor
(`corpus.add`, con la versión del aviso y la interfaz), sin otros datos.

Esta confirmación NO es el consentimiento individual de los miembros ni resuelve por sí sola la base jurídica
del tratamiento (pendiente de revisión profesional, ver docs/LEGITIMIDAD_APRENDIZAJE.md).
"""

from __future__ import annotations

import discord

from config import LANDING_URL, env_int
from db import CORPUS_RETENTION_MIN_DAYS, add_corpus_channel, log_audit
from i18n import t

# Cambia si cambia el texto del aviso: el dashboard debe enviar esta misma versión y el registro la conserva.
NOTICE_VERSION = "2026-11-07"

PRIVACY_CENTER_URL = f"{LANDING_URL}/privacidad"


def retention_days() -> int:
    return max(env_int("CORPUS_RETENTION_DAYS", 30), CORPUS_RETENTION_MIN_DAYS)


def terms_url(locale: str) -> str:
    return f"{LANDING_URL}/en/terms" if locale == "en" else f"{LANDING_URL}/es/terminos"


def privacy_url(locale: str) -> str:
    return (
        f"{LANDING_URL}/en/privacy"
        if locale == "en"
        else f"{LANDING_URL}/es/privacidad"
    )


def audit_detail(channel_id: int, source: str) -> str:
    return f"channel_id={channel_id} notice={NOTICE_VERSION} source={source}"


def _channels_text(channel_ids: list[int]) -> str:
    shown = ", ".join(f"<#{cid}>" for cid in channel_ids[:10])
    if len(channel_ids) > 10:
        shown += f" (+{len(channel_ids) - 10})"
    return shown


def build_notice_embed(locale: str, channel_ids: list[int]) -> discord.Embed:
    return discord.Embed(
        title=t("learning.confirm.title", locale),
        description=t(
            "learning.confirm.body",
            locale,
            channels=_channels_text(channel_ids),
            days=retention_days(),
            center=PRIVACY_CENTER_URL,
        ),
        color=0xE67E22,
    )


class LearningConfirmView(discord.ui.View):
    """Reemplaza temporalmente el panel: confirmar activa los canales y vuelve al panel; cancelar solo vuelve."""

    def __init__(self, host, channel_ids: list[int], source: str):
        super().__init__(timeout=300)
        self.host = host
        self.channel_ids = channel_ids
        self.source = source
        locale = host.locale

        ok = discord.ui.Button(
            label=t("learning.confirm.btn_ok", locale),
            style=discord.ButtonStyle.success,
            row=0,
        )
        cancel = discord.ui.Button(
            label=t("learning.confirm.btn_cancel", locale),
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        ok.callback = self._on_confirm
        cancel.callback = self._on_cancel
        self.add_item(ok)
        self.add_item(cancel)
        self.add_item(
            discord.ui.Button(
                label=t("learning.confirm.btn_terms", locale),
                style=discord.ButtonStyle.link,
                url=terms_url(locale),
                row=1,
            )
        )
        self.add_item(
            discord.ui.Button(
                label=t("learning.confirm.btn_privacy", locale),
                style=discord.ButtonStyle.link,
                url=privacy_url(locale),
                row=1,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if interaction.user.id != self.host.invoker_id or not (
            isinstance(member, discord.Member) and member.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                t("settings.not_your_panel", self.host.locale), ephemeral=True
            )
            return False
        return True

    async def _on_confirm(self, interaction: discord.Interaction) -> None:
        guild = self.host.guild
        for cid in self.channel_ids:
            if await add_corpus_channel(guild.id, cid):
                await log_audit(
                    guild.id,
                    interaction.user.id,
                    interaction.user.display_name,
                    "corpus.add",
                    audit_detail(cid, self.source),
                )
        self.stop()
        await self.host.refresh(interaction)

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        await self.host.refresh(interaction)


async def request_learning_activation(
    interaction: discord.Interaction, host, channel_ids: list[int], source: str
) -> None:
    """Muestra el aviso en lugar del panel. `host` aporta guild, locale, invoker_id y refresh()."""
    view = LearningConfirmView(host, sorted(channel_ids), source)
    await interaction.response.edit_message(
        embed=build_notice_embed(host.locale, sorted(channel_ids)), view=view
    )
