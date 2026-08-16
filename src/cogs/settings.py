"""Panel unificado /settings + onboarding (/setup y bienvenida al unirse a un servidor).

Todo el texto pasa por i18n (src/i18n.py + src/locales/*.json).
"""

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

import generation
import i18n
from cogs.premium import is_premium_guild
from cogs.youtube import get_latest_video
from config import BOT_TRIGGER_NAME, PANEL_URL, get_dashboard_url
from db import (
    YOUTUBE_ERROR_CHANNEL_NOT_FOUND,
    YOUTUBE_ERROR_NO_PERMISSION,
    add_corpus_channel,
    add_meme_schedule,
    add_scheduled_announcement,
    add_youtube_sub,
    count_guild_corpus_messages,
    get_chat_settings,
    list_corpus_channels,
    list_ignored_channels,
    list_meme_schedules,
    list_scheduled_announcements,
    list_youtube_subs,
    remember_welcome_channel,
    remove_corpus_channel,
    remove_meme_schedule,
    remove_scheduled_announcement,
    remove_youtube_sub,
    set_chat_mode,
    set_youtube_mention_role,
    update_last_video_id,
    wipe_corpus,
    wipe_gifs,
)
from i18n import t
from tasks import get_task_manager

log = logging.getLogger(__name__)

PURGITO_COLOR = 0x8B00FF

_HOUR_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

MAX_DELETE_AFTER_SECONDS = 86400


def _refeed_task_running(guild_id: int) -> bool:
    return any(
        t.type == "refeed_channels" and t.status in ("pending", "running")
        for t in get_task_manager().list_for_guild(guild_id)
    )


def _parse_delete_after_seconds(raw: str) -> int | None:
    """None si el campo vino vacío (no autoborrar). Lanza ValueError si no es
    un entero entre 1 y MAX_DELETE_AFTER_SECONDS."""
    raw = raw.strip()
    if not raw:
        return None
    if not raw.isdigit() or not (1 <= int(raw) <= MAX_DELETE_AFTER_SECONDS):
        raise ValueError
    return int(raw)


# ─── Infraestructura del panel /settings ────────────────────────────────────


class SettingsCategory:
    """Una categoría del panel. Subclases definen key, emoji y sus componentes."""

    key: str = ""
    emoji: str = "⚙️"
    premium_only: bool = False

    def label(self, locale: str) -> str:
        return t(f"settings.cat.{self.key}.label", locale)

    def description(self, locale: str) -> str:
        return t(f"settings.cat.{self.key}.desc", locale)

    def title(self, locale: str) -> str:
        return t(f"settings.cat.{self.key}.title", locale)

    async def build_embed(self, panel: "SettingsPanel") -> discord.Embed:
        raise NotImplementedError

    async def build_items(self, panel: "SettingsPanel") -> list[discord.ui.Item]:
        raise NotImplementedError


class CategorySelect(discord.ui.Select):
    def __init__(self, panel: "SettingsPanel"):
        options = [
            discord.SelectOption(
                label=cat.label(panel.locale),
                description=cat.description(panel.locale)[:100],
                value=cat.key,
                emoji=cat.emoji,
                default=panel.current_key == cat.key,
            )
            for cat in CATEGORIES
        ]
        super().__init__(
            placeholder=t("settings.select_placeholder", panel.locale),
            options=options,
            row=0,
        )
        self.panel = panel

    async def callback(self, interaction: discord.Interaction):
        self.panel.current_key = self.values[0]
        await self.panel.refresh(interaction)


class SettingsPanel(discord.ui.View):
    """Vista navegable: select de categorías (fila 0) + componentes de la categoría actual."""

    def __init__(
        self,
        guild: discord.Guild,
        locale: str,
        invoker_id: int,
        intro: tuple[str, str] | None = None,
    ):
        super().__init__(timeout=600)
        self.guild = guild
        self.locale = locale
        self.invoker_id = invoker_id
        self.intro = intro or (
            t("settings.title", locale),
            t("settings.intro", locale, url=get_dashboard_url(guild.id, locale)),
        )
        self.show_panel_footer = intro is None
        self.current_key: str | None = None
        self.channels_feedback: str | None = None

    def _category(self) -> SettingsCategory | None:
        for cat in CATEGORIES:
            if cat.key == self.current_key:
                return cat
        return None

    async def build_embed(self) -> discord.Embed:
        cat = self._category()
        if cat is None:
            title, body = self.intro
            embed = discord.Embed(title=title, description=body, color=PURGITO_COLOR)
            if self.show_panel_footer:
                embed.set_footer(
                    text=t("settings.panel_footer", self.locale, url=PANEL_URL)
                )
            return embed
        return await cat.build_embed(self)

    async def rebuild(self) -> None:
        self.clear_items()
        self.add_item(CategorySelect(self))
        cat = self._category()
        if cat is None:
            return
        if cat.premium_only and not is_premium_guild(self.guild.id):
            return
        for item in await cat.build_items(self):
            self.add_item(item)

    async def refresh(self, interaction: discord.Interaction) -> None:
        """Re-renderiza embed + componentes en el mensaje del panel."""
        await self.rebuild()
        embed = await self.build_embed()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                t("settings.not_your_panel", self.locale), ephemeral=True
            )
            return False
        if (
            not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                t("settings.no_permission", self.locale), ephemeral=True
            )
            return False
        return True


def _premium_locked_embed(panel: SettingsPanel, cat: SettingsCategory) -> discord.Embed:
    return discord.Embed(
        title=cat.title(panel.locale),
        description=t("settings.premium_only", panel.locale),
        color=PURGITO_COLOR,
    )


# ─── Categorías del panel /settings ─────────────────────────────────────────


class CanalesCategory(SettingsCategory):
    key = "canales"
    emoji = "📚"

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        allowed = await list_corpus_channels(panel.guild.id)
        corpus_count = await count_guild_corpus_messages(panel.guild.id)

        body = t("settings.canales.body", panel.locale) + "\n\n"
        if allowed:
            body += t("settings.canales.selected_count", panel.locale, count=len(allowed)) + "\n"
            body += ", ".join(f"<#{cid}>" for cid in allowed[:15])
            if len(allowed) > 15:
                body += f" (+{len(allowed) - 15})"
        else:
            body += t("setup.status_no_channels", panel.locale)

        if getattr(panel, "channels_feedback", None):
            body += "\n\n" + panel.channels_feedback
            panel.channels_feedback = None

        return discord.Embed(
            title=self.title(panel.locale),
            description=body,
            color=PURGITO_COLOR,
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        allowed = await list_corpus_channels(panel.guild.id)
        is_running = _refeed_task_running(panel.guild.id)
        items: list[discord.ui.Item] = []

        channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder=t("settings.canales.placeholder", panel.locale),
            min_values=0,
            max_values=min(25, max(1, len(panel.guild.text_channels))),
            default_values=[discord.Object(id=cid) for cid in allowed[:25]],
            row=1,
        )

        async def on_channels_select(interaction: discord.Interaction):
            selected_ids = set()
            problems = []
            me = panel.guild.me
            for ch in channel_select.values:
                real_ch = panel.guild.get_channel(ch.id)
                if not real_ch or not isinstance(real_ch, discord.TextChannel):
                    continue
                if getattr(real_ch, "is_nsfw", lambda: False)():
                    problems.append(t("setup.error_nsfw_channel", panel.locale, channel=real_ch.name))
                    continue
                perms = real_ch.permissions_for(me)
                if not (perms.view_channel and perms.read_message_history):
                    problems.append(t("setup.error_no_permission_channel", panel.locale, channel=real_ch.name))
                    continue
                selected_ids.add(real_ch.id)

            current_set = set(await list_corpus_channels(panel.guild.id))
            for cid in current_set - selected_ids:
                await remove_corpus_channel(panel.guild.id, cid)
            for cid in selected_ids - current_set:
                await add_corpus_channel(panel.guild.id, cid)

            if problems:
                panel.channels_feedback = "\n".join(problems)

            await panel.refresh(interaction)

        channel_select.callback = on_channels_select
        items.append(channel_select)

        if allowed:
            btn_refeed = discord.ui.Button(
                label=t("settings.canales.btn_refeed", panel.locale),
                style=discord.ButtonStyle.primary,
                disabled=is_running,
                row=2,
            )

            async def on_refeed(interaction: discord.Interaction):
                if _refeed_task_running(panel.guild.id):
                    await interaction.response.send_message(
                        t("chat.refeed_channels.already_running", panel.locale),
                        ephemeral=True,
                    )
                    return
                chat_cog = interaction.client.get_cog("Chat")
                if chat_cog is not None:
                    await interaction.response.defer()
                    progress_msg = await interaction.original_response()
                    chat_cog.start_refeed_channels(panel.guild, progress_msg, interaction.channel)
                else:
                    await panel.refresh(interaction)

            btn_refeed.callback = on_refeed
            items.append(btn_refeed)

        return items


class ChatCategory(SettingsCategory):
    key = "chat"
    emoji = "💬"

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        settings = await get_chat_settings(panel.guild.id)
        body = t(
            "settings.chat.status_on"
            if settings["enabled"]
            else "settings.chat.status_off",
            panel.locale,
        )
        return discord.Embed(
            title=self.title(panel.locale), description=body, color=PURGITO_COLOR
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        settings = await get_chat_settings(panel.guild.id)

        enable_btn = discord.ui.Button(
            label=t("settings.chat.btn_enable", panel.locale),
            style=discord.ButtonStyle.success,
            disabled=settings["enabled"],
            row=1,
        )
        disable_btn = discord.ui.Button(
            label=t("settings.chat.btn_disable", panel.locale),
            style=discord.ButtonStyle.danger,
            disabled=not settings["enabled"],
            row=1,
        )

        async def on_enable(interaction: discord.Interaction):
            current = await get_chat_settings(panel.guild.id)
            await set_chat_mode(panel.guild.id, True, current["channel_id"])
            await panel.refresh(interaction)

        async def on_disable(interaction: discord.Interaction):
            current = await get_chat_settings(panel.guild.id)
            await set_chat_mode(panel.guild.id, False, current["channel_id"])
            await panel.refresh(interaction)

        enable_btn.callback = on_enable
        disable_btn.callback = on_disable
        return [enable_btn, disable_btn]


class IdiomaCategory(SettingsCategory):
    key = "idioma"
    emoji = "🌐"

    def _language_name(self, locale: str) -> str:
        return dict(i18n.SUPPORTED_LOCALES).get(locale, locale)

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        return discord.Embed(
            title=self.title(panel.locale),
            description=t(
                "settings.idioma.body",
                panel.locale,
                language=self._language_name(panel.locale),
            ),
            color=PURGITO_COLOR,
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        select = discord.ui.Select(
            placeholder=t("settings.idioma.placeholder", panel.locale),
            options=[
                discord.SelectOption(
                    label=name, value=code, default=code == panel.locale
                )
                for code, name in i18n.SUPPORTED_LOCALES
            ],
            row=1,
        )

        async def on_select(interaction: discord.Interaction):
            new_locale = select.values[0]
            await i18n.set_locale(panel.guild.id, new_locale)
            panel.locale = new_locale
            panel.intro = (
                t("settings.title", new_locale),
                t(
                    "settings.intro",
                    new_locale,
                    url=get_dashboard_url(panel.guild.id, new_locale),
                ),
            )
            await panel.refresh(interaction)

        select.callback = on_select
        return [select]


class AprendizajeCategory(SettingsCategory):
    key = "aprendizaje"
    emoji = "🔄"

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        allowed = await list_corpus_channels(panel.guild.id)
        corpus_count = await count_guild_corpus_messages(panel.guild.id)
        is_running = _refeed_task_running(panel.guild.id)

        if is_running:
            status = t("setup.status_refeeding", panel.locale)
        elif not allowed:
            status = t("setup.status_no_channels", panel.locale)
        elif corpus_count == 0:
            status = t("setup.status_channels_no_history", panel.locale, count=len(allowed))
        else:
            status = t("setup.status_ready", panel.locale, corpus=f"{corpus_count:,}", channels=len(allowed))

        body = t("settings.aprendizaje.body", panel.locale) + "\n\n" + status
        return discord.Embed(
            title=self.title(panel.locale),
            description=body,
            color=PURGITO_COLOR,
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        allowed = await list_corpus_channels(panel.guild.id)
        is_running = _refeed_task_running(panel.guild.id)

        btn = discord.ui.Button(
            label=t("settings.aprendizaje.btn_start", panel.locale),
            style=discord.ButtonStyle.primary,
            disabled=len(allowed) == 0 or is_running,
            row=1,
        )

        async def on_start(interaction: discord.Interaction):
            if _refeed_task_running(panel.guild.id):
                await interaction.response.send_message(
                    t("chat.refeed_channels.already_running", panel.locale),
                    ephemeral=True,
                )
                return
            chat_cog = interaction.client.get_cog("Chat")
            if chat_cog is not None:
                await interaction.response.defer()
                progress_msg = await interaction.original_response()
                chat_cog.start_refeed_channels(panel.guild, progress_msg, interaction.channel)
            else:
                await panel.refresh(interaction)

        btn.callback = on_start
        return [btn]


class DatosCategory(SettingsCategory):
    key = "datos"
    emoji = "🗑️"

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        return discord.Embed(
            title=self.title(panel.locale),
            description=t("settings.datos.body", panel.locale),
            color=PURGITO_COLOR,
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        wipe_btn = discord.ui.Button(
            label=t("settings.corpus.btn_wipe", panel.locale),
            style=discord.ButtonStyle.danger,
            row=1,
        )

        class WipeConfirmModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(
                    title=t("settings.corpus.wipe_modal_title", panel.locale)
                )
                self.confirm_input = discord.ui.TextInput(
                    label=t("settings.corpus.wipe_modal_field", panel.locale)[:45],
                    max_length=100,
                )
                self.add_item(self.confirm_input)

            async def on_submit(self, interaction: discord.Interaction):
                if self.confirm_input.value.strip() != panel.guild.name:
                    await interaction.response.send_message(
                        t("settings.corpus.wipe_mismatch", panel.locale), ephemeral=True
                    )
                    return
                await wipe_corpus(panel.guild.id)
                generation.reset_guild_caches(panel.guild.id)
                await panel.refresh(interaction)
                await interaction.followup.send(
                    t("settings.corpus.wipe_success", panel.locale), ephemeral=True
                )

        async def on_wipe(interaction: discord.Interaction):
            await interaction.response.send_modal(WipeConfirmModal())

        wipe_btn.callback = on_wipe

        wipe_gifs_btn = discord.ui.Button(
            label=t("settings.corpus.btn_wipe_gifs", panel.locale),
            style=discord.ButtonStyle.danger,
            row=2,
        )

        class WipeGifsConfirmModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(
                    title=t("settings.corpus.wipe_gifs_modal_title", panel.locale)
                )
                self.confirm_input = discord.ui.TextInput(
                    label=t("settings.corpus.wipe_modal_field", panel.locale)[:45],
                    max_length=100,
                )
                self.add_item(self.confirm_input)

            async def on_submit(self, interaction: discord.Interaction):
                if self.confirm_input.value.strip() != panel.guild.name:
                    await interaction.response.send_message(
                        t("settings.corpus.wipe_mismatch", panel.locale), ephemeral=True
                    )
                    return
                count = await wipe_gifs(panel.guild.id)
                await panel.refresh(interaction)
                await interaction.followup.send(
                    t("settings.corpus.wipe_gifs_success", panel.locale, count=count),
                    ephemeral=True,
                )

        async def on_wipe_gifs(interaction: discord.Interaction):
            await interaction.response.send_modal(WipeGifsConfirmModal())

        wipe_gifs_btn.callback = on_wipe_gifs
        return [wipe_btn, wipe_gifs_btn]


class YouTubeCategory(SettingsCategory):
    key = "youtube"
    emoji = "📺"

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        subs = await list_youtube_subs(panel.guild.id)
        body = t("settings.youtube.body", panel.locale)
        if subs:
            lines = []
            for s in subs:
                line = (
                    f"• **{s['youtube_channel_name']}** → <#{s['discord_channel_id']}>"
                )
                if s["last_error"] == YOUTUBE_ERROR_NO_PERMISSION:
                    line += "\n  " + t(
                        "settings.youtube.error_no_permission", panel.locale
                    )
                elif s["last_error"] == YOUTUBE_ERROR_CHANNEL_NOT_FOUND:
                    line += "\n  " + t(
                        "settings.youtube.error_channel_not_found", panel.locale
                    )
                lines.append(line)
            body += "\n\n" + "\n".join(lines)
        else:
            body += "\n\n" + t("settings.youtube.none", panel.locale)
        if getattr(panel, "yt_pending_channel", None):
            body += "\n\n" + t("settings.youtube.add_pending_hint", panel.locale)
        if getattr(panel, "yt_add_error", False):
            body += "\n\n" + t("settings.youtube.add_invalid", panel.locale)
            panel.yt_add_error = False
        if getattr(panel, "yt_pending_mention", None):
            body += "\n\n" + t("settings.youtube.mention_pending_hint", panel.locale)
        return discord.Embed(
            title=self.title(panel.locale), description=body[:4000], color=PURGITO_COLOR
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        subs = await list_youtube_subs(panel.guild.id)
        items: list[discord.ui.Item] = []

        if subs:
            remove_select = discord.ui.Select(
                placeholder=t("settings.youtube.remove_placeholder", panel.locale),
                options=[
                    discord.SelectOption(
                        label=s["youtube_channel_name"][:100],
                        value=s["youtube_channel_id"],
                    )
                    for s in subs[:25]
                ],
                row=1,
            )

            async def on_remove(interaction: discord.Interaction):
                await remove_youtube_sub(panel.guild.id, remove_select.values[0])
                await panel.refresh(interaction)

            remove_select.callback = on_remove
            items.append(remove_select)

        pending_channel: str | None = getattr(panel, "yt_pending_channel", None)
        if pending_channel:
            dest_select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.text],
                placeholder=t("settings.youtube.add_channel_placeholder", panel.locale),
                row=2,
            )

            async def on_dest_channel(interaction: discord.Interaction):
                video = await get_latest_video(pending_channel)
                panel.yt_pending_channel = None
                if video is None:
                    panel.yt_add_error = True
                    await panel.refresh(interaction)
                    return
                channel_name = video["author"] or pending_channel
                added = await add_youtube_sub(
                    panel.guild.id,
                    interaction.channel.id if interaction.channel else 0,
                    pending_channel,
                    channel_name,
                    dest_select.values[0].id,
                )
                if added:
                    await update_last_video_id(
                        panel.guild.id, pending_channel, video["id"]
                    )
                await panel.refresh(interaction)

            dest_select.callback = on_dest_channel
            items.append(dest_select)
        else:
            add_btn = discord.ui.Button(
                label=t("settings.youtube.btn_add", panel.locale),
                style=discord.ButtonStyle.primary,
                row=2,
            )

            class AddChannelModal(discord.ui.Modal):
                def __init__(self):
                    super().__init__(
                        title=t("settings.youtube.add_modal_title", panel.locale)
                    )
                    self.channel_input = discord.ui.TextInput(
                        label=t("settings.youtube.add_modal_field", panel.locale)[:45],
                        max_length=100,
                    )
                    self.add_item(self.channel_input)

                async def on_submit(self, interaction: discord.Interaction):
                    text = self.channel_input.value.strip()
                    if not text:
                        await interaction.response.send_message(
                            t("settings.youtube.add_invalid", panel.locale),
                            ephemeral=True,
                        )
                        return
                    panel.yt_pending_channel = text
                    await panel.refresh(interaction)

            async def on_add(interaction: discord.Interaction):
                await interaction.response.send_modal(AddChannelModal())

            add_btn.callback = on_add
            items.append(add_btn)

        pending_mention: str | None = getattr(panel, "yt_pending_mention", None)
        if pending_mention:
            role_select = discord.ui.RoleSelect(
                placeholder=t(
                    "settings.youtube.mention_role_placeholder", panel.locale
                ),
                min_values=0,
                max_values=1,
                row=3,
            )

            async def on_role(interaction: discord.Interaction):
                role_id = role_select.values[0].id if role_select.values else None
                await set_youtube_mention_role(panel.guild.id, pending_mention, role_id)
                panel.yt_pending_mention = None
                await panel.refresh(interaction)

            role_select.callback = on_role
            items.append(role_select)
        elif subs:
            mention_select = discord.ui.Select(
                placeholder=t("settings.youtube.mention_placeholder", panel.locale),
                options=[
                    discord.SelectOption(
                        label=s["youtube_channel_name"][:100],
                        value=s["youtube_channel_id"],
                    )
                    for s in subs[:25]
                ],
                row=3,
            )

            async def on_mention_target(interaction: discord.Interaction):
                panel.yt_pending_mention = mention_select.values[0]
                await panel.refresh(interaction)

            mention_select.callback = on_mention_target
            items.append(mention_select)

        return items


class MemesCategory(SettingsCategory):
    key = "memes"
    emoji = "😏"
    premium_only = True

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        if not is_premium_guild(panel.guild.id):
            return _premium_locked_embed(panel, self)
        schedules = await list_meme_schedules(panel.guild.id)
        body = t("settings.memes.body", panel.locale)
        if schedules:
            body += "\n\n" + "\n".join(
                f"• <#{s['channel_id']}> — "
                + t(
                    "settings.memes.entry",
                    panel.locale,
                    hours=s["interval_minutes"] // 60,
                )
                for s in schedules
            )
        else:
            body += "\n\n" + t("settings.memes.none", panel.locale)
        if getattr(panel, "memes_pending_interval", None):
            body += "\n\n" + t("settings.memes.activate_pending_hint", panel.locale)
        return discord.Embed(
            title=self.title(panel.locale), description=body[:4000], color=PURGITO_COLOR
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        schedules = await list_meme_schedules(panel.guild.id)
        items: list[discord.ui.Item] = []

        if schedules:
            channel_names = {
                s["channel_id"]: getattr(
                    panel.guild.get_channel(s["channel_id"]),
                    "name",
                    str(s["channel_id"]),
                )
                for s in schedules
            }
            remove_select = discord.ui.Select(
                placeholder=t("settings.memes.remove_placeholder", panel.locale),
                options=[
                    discord.SelectOption(
                        label=f"#{channel_names[s['channel_id']]}"[:100],
                        value=str(s["channel_id"]),
                    )
                    for s in schedules[:25]
                ],
                row=1,
            )

            async def on_remove(interaction: discord.Interaction):
                await remove_meme_schedule(panel.guild.id, int(remove_select.values[0]))
                await panel.refresh(interaction)

            remove_select.callback = on_remove
            items.append(remove_select)

        pending_interval: int | None = getattr(panel, "memes_pending_interval", None)
        if pending_interval:
            channel_select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.text],
                placeholder=t(
                    "settings.memes.activate_channel_placeholder", panel.locale
                ),
                row=2,
            )

            async def on_channel(interaction: discord.Interaction):
                await add_meme_schedule(
                    panel.guild.id, channel_select.values[0].id, pending_interval * 60
                )
                panel.memes_pending_interval = None
                await panel.refresh(interaction)

            channel_select.callback = on_channel
            items.append(channel_select)
        else:
            activate_btn = discord.ui.Button(
                label=t("settings.memes.btn_activate", panel.locale),
                style=discord.ButtonStyle.primary,
                row=2,
            )

            class ActivateModal(discord.ui.Modal):
                def __init__(self):
                    super().__init__(
                        title=t("settings.memes.activate_modal_title", panel.locale)
                    )
                    self.interval_input = discord.ui.TextInput(
                        label=t("settings.memes.activate_modal_field", panel.locale)[
                            :45
                        ],
                        max_length=3,
                    )
                    self.add_item(self.interval_input)

                async def on_submit(self, interaction: discord.Interaction):
                    raw = self.interval_input.value.strip()
                    if not raw.isdigit() or not (2 <= int(raw) <= 24):
                        await interaction.response.send_message(
                            t("settings.memes.activate_invalid", panel.locale),
                            ephemeral=True,
                        )
                        return
                    panel.memes_pending_interval = int(raw)
                    await panel.refresh(interaction)

            async def on_activate(interaction: discord.Interaction):
                await interaction.response.send_modal(ActivateModal())

            activate_btn.callback = on_activate
            items.append(activate_btn)

        return items


class AnunciosCategory(SettingsCategory):
    key = "anuncios"
    emoji = "📢"

    async def build_embed(self, panel: SettingsPanel) -> discord.Embed:
        anuncios = await list_scheduled_announcements(panel.guild.id)
        body = t("settings.anuncios.body", panel.locale)
        if anuncios:
            lines = []
            for a in anuncios:
                preview = a["message"][:60]
                if len(a["message"]) > 60:
                    preview += "…"
                if a["mode"] == "interval":
                    mode_text = t(
                        "settings.anuncios.entry_interval",
                        panel.locale,
                        minutes=a["interval_minutes"],
                    )
                else:
                    mode_text = t(
                        "settings.anuncios.entry_daily",
                        panel.locale,
                        time=f"{a['hour']:02d}:{a['minute']:02d}",
                    )
                line = f'• <#{a["channel_id"]}> — {mode_text} — "{preview}"'
                if a.get("delete_after_seconds"):
                    line += " — " + t(
                        "settings.anuncios.preview_delete_after",
                        panel.locale,
                        seconds=a["delete_after_seconds"],
                    )
                lines.append(line)
            body += "\n\n" + "\n".join(lines)
        else:
            body += "\n\n" + t("settings.anuncios.none", panel.locale)
        if getattr(panel, "anuncio_pending", None):
            body += "\n\n" + t("settings.anuncios.activate_pending_hint", panel.locale)
        if getattr(panel, "anuncio_limit_error", False):
            body += "\n\n" + t("settings.anuncios.limit_reached", panel.locale)
            panel.anuncio_limit_error = False
        return discord.Embed(
            title=self.title(panel.locale), description=body[:4000], color=PURGITO_COLOR
        )

    async def build_items(self, panel: SettingsPanel) -> list[discord.ui.Item]:
        anuncios = await list_scheduled_announcements(panel.guild.id)
        items: list[discord.ui.Item] = []

        if anuncios:
            remove_select = discord.ui.Select(
                placeholder=t("settings.anuncios.remove_placeholder", panel.locale),
                options=[
                    discord.SelectOption(
                        label=(
                            f"#{getattr(panel.guild.get_channel(a['channel_id']), 'name', a['channel_id'])} "
                            f"— {a['message'][:40]}"
                        )[:100],
                        value=str(a["id"]),
                    )
                    for a in anuncios[:25]
                ],
                row=1,
            )

            async def on_remove(interaction: discord.Interaction):
                await remove_scheduled_announcement(
                    panel.guild.id, int(remove_select.values[0])
                )
                await panel.refresh(interaction)

            remove_select.callback = on_remove
            items.append(remove_select)

        pending: dict | None = getattr(panel, "anuncio_pending", None)
        if pending:
            channel_select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.text],
                placeholder=t(
                    "settings.anuncios.activate_channel_placeholder", panel.locale
                ),
                row=2,
            )

            async def on_channel(interaction: discord.Interaction):
                new_id = await add_scheduled_announcement(
                    panel.guild.id,
                    channel_select.values[0].id,
                    pending["message"],
                    pending["mode"],
                    panel.invoker_id,
                    interval_minutes=pending.get("interval_minutes"),
                    hour=pending.get("hour"),
                    minute=pending.get("minute"),
                    delete_after_seconds=pending.get("delete_after_seconds"),
                )
                panel.anuncio_pending = None
                if new_id is None:
                    panel.anuncio_limit_error = True
                await panel.refresh(interaction)

            channel_select.callback = on_channel
            items.append(channel_select)
        else:
            add_interval_btn = discord.ui.Button(
                label=t("settings.anuncios.btn_add_interval", panel.locale),
                style=discord.ButtonStyle.primary,
                row=2,
            )

            class IntervalModal(discord.ui.Modal):
                def __init__(self):
                    super().__init__(
                        title=t("settings.anuncios.modal_title_interval", panel.locale)
                    )
                    self.message_input = discord.ui.TextInput(
                        label=t("settings.anuncios.modal_field_message", panel.locale)[
                            :45
                        ],
                        style=discord.TextStyle.paragraph,
                        max_length=500,
                    )
                    self.interval_input = discord.ui.TextInput(
                        label=t("settings.anuncios.modal_field_interval", panel.locale)[
                            :45
                        ],
                        max_length=4,
                    )
                    self.delete_after_input = discord.ui.TextInput(
                        label=t(
                            "settings.anuncios.modal_field_delete_after", panel.locale
                        )[:45],
                        max_length=5,
                        required=False,
                    )
                    self.add_item(self.message_input)
                    self.add_item(self.interval_input)
                    self.add_item(self.delete_after_input)

                async def on_submit(self, interaction: discord.Interaction):
                    raw = self.interval_input.value.strip()
                    if not raw.isdigit() or not (5 <= int(raw) <= 1440):
                        await interaction.response.send_message(
                            t("settings.anuncios.invalid_interval", panel.locale),
                            ephemeral=True,
                        )
                        return
                    try:
                        delete_after = _parse_delete_after_seconds(
                            self.delete_after_input.value
                        )
                    except ValueError:
                        await interaction.response.send_message(
                            t("settings.anuncios.invalid_delete_after", panel.locale),
                            ephemeral=True,
                        )
                        return
                    panel.anuncio_pending = {
                        "message": self.message_input.value.strip(),
                        "mode": "interval",
                        "interval_minutes": int(raw),
                        "delete_after_seconds": delete_after,
                    }
                    await panel.refresh(interaction)

            async def on_add_interval(interaction: discord.Interaction):
                await interaction.response.send_modal(IntervalModal())

            add_interval_btn.callback = on_add_interval
            items.append(add_interval_btn)

            add_daily_btn = discord.ui.Button(
                label=t("settings.anuncios.btn_add_daily", panel.locale),
                style=discord.ButtonStyle.primary,
                row=2,
            )

            class DailyModal(discord.ui.Modal):
                def __init__(self):
                    super().__init__(
                        title=t("settings.anuncios.modal_title_daily", panel.locale)
                    )
                    self.message_input = discord.ui.TextInput(
                        label=t("settings.anuncios.modal_field_message", panel.locale)[
                            :45
                        ],
                        style=discord.TextStyle.paragraph,
                        max_length=500,
                    )
                    self.hour_input = discord.ui.TextInput(
                        label=t("settings.anuncios.modal_field_hour", panel.locale)[
                            :45
                        ],
                        max_length=5,
                    )
                    self.delete_after_input = discord.ui.TextInput(
                        label=t(
                            "settings.anuncios.modal_field_delete_after", panel.locale
                        )[:45],
                        max_length=5,
                        required=False,
                    )
                    self.add_item(self.message_input)
                    self.add_item(self.hour_input)
                    self.add_item(self.delete_after_input)

                async def on_submit(self, interaction: discord.Interaction):
                    match = _HOUR_RE.match(self.hour_input.value.strip())
                    if not match:
                        await interaction.response.send_message(
                            t("settings.anuncios.invalid_hour", panel.locale),
                            ephemeral=True,
                        )
                        return
                    try:
                        delete_after = _parse_delete_after_seconds(
                            self.delete_after_input.value
                        )
                    except ValueError:
                        await interaction.response.send_message(
                            t("settings.anuncios.invalid_delete_after", panel.locale),
                            ephemeral=True,
                        )
                        return
                    panel.anuncio_pending = {
                        "message": self.message_input.value.strip(),
                        "mode": "daily",
                        "hour": int(match.group(1)),
                        "minute": int(match.group(2)),
                        "delete_after_seconds": delete_after,
                    }
                    await panel.refresh(interaction)

            async def on_add_daily(interaction: discord.Interaction):
                await interaction.response.send_modal(DailyModal())

            add_daily_btn.callback = on_add_daily
            items.append(add_daily_btn)

        return items


CATEGORIES: list[SettingsCategory] = [
    CanalesCategory(),
    ChatCategory(),
    IdiomaCategory(),
    AprendizajeCategory(),
    YouTubeCategory(),
    MemesCategory(),
    AnunciosCategory(),
    DatosCategory(),
]


# ─── Onboarding interactivo (/setup) ─────────────────────────────────────────


class SetupView(discord.ui.View):
    """Panel interactivo de onboarding y configuración de canales en Discord."""

    def __init__(self, guild: discord.Guild, locale: str, invoker_id: int):
        super().__init__(timeout=600)
        self.guild = guild
        self.locale = locale
        self.invoker_id = invoker_id
        self.feedback_msg: str | None = None

    async def build_embed(self) -> discord.Embed:
        allowed = await list_corpus_channels(self.guild.id)
        corpus_count = await count_guild_corpus_messages(self.guild.id)
        is_running = _refeed_task_running(self.guild.id)

        if is_running:
            status = t("setup.status_refeeding", self.locale)
        elif not allowed:
            status = t("setup.status_no_channels", self.locale)
        elif corpus_count == 0:
            status = t("setup.status_channels_no_history", self.locale, count=len(allowed))
        else:
            status = t(
                "setup.status_ready",
                self.locale,
                corpus=f"{corpus_count:,}",
                channels=len(allowed),
            )

        lines = [
            t("setup.intro", self.locale),
            "",
            status,
        ]

        if allowed:
            lines.append("")
            lines.append(
                f"**{t('setup.selected_channels_header', self.locale, count=len(allowed))}**"
            )
            chan_str = ", ".join(f"<#{cid}>" for cid in allowed[:12])
            if len(allowed) > 12:
                chan_str += f" (+{len(allowed) - 12})"
            lines.append(chan_str)

        if self.feedback_msg:
            lines.append("")
            lines.append(self.feedback_msg)
            self.feedback_msg = None

        embed = discord.Embed(
            title=t("setup.title", self.locale),
            description="\n".join(lines),
            color=PURGITO_COLOR,
        )
        return embed

    async def rebuild(self) -> None:
        self.clear_items()
        allowed = await list_corpus_channels(self.guild.id)
        is_running = _refeed_task_running(self.guild.id)

        channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder=t("setup.select_channels_placeholder", self.locale),
            min_values=0,
            max_values=min(25, max(1, len(self.guild.text_channels))),
            default_values=[discord.Object(id=cid) for cid in allowed[:25]],
            row=0,
        )

        async def on_channels_select(interaction: discord.Interaction):
            selected_ids = set()
            problems = []
            me = self.guild.me
            for ch in channel_select.values:
                real_ch = self.guild.get_channel(ch.id)
                if not real_ch or not isinstance(real_ch, discord.TextChannel):
                    continue
                if getattr(real_ch, "is_nsfw", lambda: False)():
                    problems.append(
                        t("setup.error_nsfw_channel", self.locale, channel=real_ch.name)
                    )
                    continue
                perms = real_ch.permissions_for(me)
                if not (perms.view_channel and perms.read_message_history):
                    problems.append(
                        t(
                            "setup.error_no_permission_channel",
                            self.locale,
                            channel=real_ch.name,
                        )
                    )
                    continue
                selected_ids.add(real_ch.id)

            current_set = set(await list_corpus_channels(self.guild.id))
            for cid in current_set - selected_ids:
                await remove_corpus_channel(self.guild.id, cid)
            for cid in selected_ids - current_set:
                await add_corpus_channel(self.guild.id, cid)

            if problems:
                self.feedback_msg = "\n".join(problems)

            await self.refresh(interaction)

        channel_select.callback = on_channels_select
        self.add_item(channel_select)

        if allowed:
            btn_refeed = discord.ui.Button(
                label=t("setup.btn_learn_history", self.locale),
                style=discord.ButtonStyle.primary,
                disabled=is_running,
                row=1,
            )

            async def on_learn_history(interaction: discord.Interaction):
                if _refeed_task_running(self.guild.id):
                    await interaction.response.send_message(
                        t("chat.refeed_channels.already_running", self.locale),
                        ephemeral=True,
                    )
                    return

                chat_cog = interaction.client.get_cog("Chat")
                if chat_cog is not None:
                    await interaction.response.defer()
                    progress_msg = await interaction.original_response()
                    chat_cog.start_refeed_channels(
                        self.guild, progress_msg, interaction.channel
                    )
                else:
                    await self.refresh(interaction)

            btn_refeed.callback = on_learn_history
            self.add_item(btn_refeed)

        self.add_item(
            discord.ui.Button(
                label=t("setup.btn_dashboard", self.locale),
                style=discord.ButtonStyle.link,
                url=get_dashboard_url(self.guild.id, self.locale, "chat#canales"),
                row=1,
            )
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.rebuild()
        embed = await self.build_embed()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                t("settings.not_your_panel", self.locale), ephemeral=True
            )
            return False
        if (
            not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                t("settings.no_permission", self.locale), ephemeral=True
            )
            return False
        return True


# Umbrales del onboarding
VISIBILITY_LIMITED_RATIO = 0.4
VISIBILITY_LIMITED_MAX_SEEN = 3


def _scan_channel_visibility(guild: discord.Guild) -> dict:
    """Compara los canales de texto totales del guild contra los que Purgito
    puede ver y leer."""
    me = guild.me
    visible, hidden = [], []
    for ch in guild.text_channels:
        perms = ch.permissions_for(me)
        target = (
            visible if (perms.view_channel and perms.read_message_history) else hidden
        )
        target.append(ch)
    return {"total": len(guild.text_channels), "visible": visible, "hidden": hidden}


def _visibility_is_limited(scan: dict) -> bool:
    total, seen = scan["total"], len(scan["visible"])
    if total <= 3:
        return False
    return (
        seen < total * VISIBILITY_LIMITED_RATIO or seen <= VISIBILITY_LIMITED_MAX_SEEN
    )


def _format_channel_names(channels: list, max_shown: int = 5) -> str:
    text = ", ".join(f"#{ch.name}" for ch in channels[:max_shown])
    extra = len(channels) - max_shown
    if extra > 0:
        text += f" (+{extra})"
    return text


async def _find_inviter(guild: discord.Guild) -> discord.Member | None:
    me = guild.me
    if me is None or not me.guild_permissions.view_audit_log:
        return None
    try:
        async for entry in guild.audit_logs(
            action=discord.AuditLogAction.bot_add, limit=5
        ):
            if entry.target and entry.target.id == me.id:
                return entry.user
    except discord.Forbidden:
        return None
    return None


def build_dm_welcome_embed(
    guild: discord.Guild, locale: str, scan: dict | None
) -> discord.Embed:
    """Quickstart privado para quien invitó al bot."""
    body = t("dm.body", locale, url=get_dashboard_url(guild.id, locale, "chat#canales"))
    if scan is not None and _visibility_is_limited(scan):
        body += "\n\n" + t(
            "dm.limited_visibility_extra",
            locale,
            seen=len(scan["visible"]),
            total=scan["total"],
        )
    return discord.Embed(
        title=t("dm.title", locale, guild=guild.name),
        description=body,
        color=PURGITO_COLOR,
    )


def build_welcome_embed(guild: discord.Guild, locale: str) -> discord.Embed:
    lines = [
        t("welcome.intro", locale),
        "",
        t("welcome.getting_started", locale),
        "",
        t("welcome.commands", locale),
        "",
        t("welcome.dashboard_hint", locale),
    ]
    return discord.Embed(
        title=t("welcome.title", locale),
        description="\n".join(lines),
        color=PURGITO_COLOR,
    )


class WelcomeView(discord.ui.View):
    """Botón principal de bienvenida (abre el panel de setup)
    + botón secundario de link directo al dashboard."""

    def __init__(self, locale: str = i18n.DEFAULT_LOCALE, guild_id: int | None = None):
        super().__init__(timeout=None)
        self.configure_btn.label = t("welcome.btn_configure", locale)
        if guild_id is not None:
            self.add_item(
                discord.ui.Button(
                    label=t("welcome.btn_dashboard", locale),
                    style=discord.ButtonStyle.link,
                    url=get_dashboard_url(guild_id, locale, "chat#canales"),
                )
            )

    @discord.ui.button(style=discord.ButtonStyle.primary, custom_id="purgito_setup_btn")
    async def configure_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.guild:
            return
        locale = await i18n.guild_locale(interaction.guild.id)
        if (
            not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                t("settings.no_permission", locale), ephemeral=True
            )
            return
        await _send_setup_panel(interaction, locale)


async def _send_setup_panel(interaction: discord.Interaction, locale: str) -> None:
    view = SetupView(interaction.guild, locale, interaction.user.id)
    await view.rebuild()
    embed = await view.build_embed()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ─── Cog ─────────────────────────────────────────────────────────────────────


class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(WelcomeView())

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        locale = await i18n.guild_locale(guild.id)
        embed = build_welcome_embed(guild, locale)
        view = WelcomeView(locale, guild.id)
        welcome_channel = None
        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if perms.send_messages:
                try:
                    await channel.send(embed=embed, view=view)
                    welcome_channel = channel
                except Exception:
                    log.warning(
                        "on_guild_join: no se pudo enviar mensaje en %s (%s)",
                        channel.id,
                        guild.id,
                    )
                break

        scan: dict | None = None
        try:
            scan = _scan_channel_visibility(guild)
        except Exception:
            log.exception(
                "on_guild_join: falló el escaneo de visibilidad (%s)", guild.id
            )

        if (
            welcome_channel is not None
            and scan is not None
            and _visibility_is_limited(scan)
        ):
            try:
                await welcome_channel.send(
                    t(
                        "welcome.limited_visibility",
                        locale,
                        seen=len(scan["visible"]),
                        total=scan["total"],
                        names=_format_channel_names(scan["visible"]),
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception:
                log.warning(
                    "on_guild_join: no se pudo avisar la visibilidad limitada (%s)",
                    guild.id,
                )

        try:
            inviter = await _find_inviter(guild)
            if inviter is not None:
                await inviter.send(embed=build_dm_welcome_embed(guild, locale, scan))
        except discord.Forbidden:
            pass
        except Exception:
            log.warning(
                "on_guild_join: falló el DM al invitador (%s)", guild.id, exc_info=True
            )

        if welcome_channel is not None:
            await remember_welcome_channel(guild.id, welcome_channel.id)

    @app_commands.command(
        name="settings", description="Panel de configuración rápida del servidor."
    )
    async def settings(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                t("settings.guild_only"), ephemeral=True
            )
            return
        locale = await i18n.guild_locale(interaction.guild.id)
        if (
            not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                t("settings.no_permission", locale), ephemeral=True
            )
            return
        panel = SettingsPanel(interaction.guild, locale, interaction.user.id)
        await panel.rebuild()
        embed = await panel.build_embed()
        await interaction.response.send_message(embed=embed, view=panel, ephemeral=True)

    @app_commands.command(
        name="setup", description="Configuración inicial de Purgito y selección de canales."
    )
    async def setup_cmd(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                t("settings.guild_only"), ephemeral=True
            )
            return
        locale = await i18n.guild_locale(interaction.guild.id)
        if (
            not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.manage_guild
        ):
            await interaction.response.send_message(
                t("settings.no_permission", locale), ephemeral=True
            )
            return
        await _send_setup_panel(interaction, locale)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))
