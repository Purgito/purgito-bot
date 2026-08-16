"""
/help de Purgito: embed intro + botones de navegación por categoría.
El comando en sí vive en cogs/general.py; aquí solo están los embeds y la vista.
"""

import discord

from config import PANEL_URL
from i18n import DEFAULT_LOCALE, t

PURGITO_COLOR = 0x8B00FF  # color de marca usado en todo el proyecto

# Estructura (sin texto traducible): emoji, orden de los botones y, por
# categoría, la lista de (comando literal, clave de i18n de su descripción).
# El texto real (labels, intros, descripciones) vive en locales/{es,en}.json
# bajo "help.cat.<key>.*" -- ver build_category_embed/HelpView.
CATEGORIES = {
    "chat": {
        "emoji": "💬",
        "row": 0,
        "commands": [
            ("/generar", "help.cat.chat.cmd.generar"),
            ("/imitar @usuario", "help.cat.chat.cmd.imitar"),
            ("/corpus_info", "help.cat.chat.cmd.corpus_info"),
            ("/settings", "help.cat.chat.cmd.settings"),
        ],
    },
    "admin": {
        "emoji": "⚙️",
        "row": 0,
        "commands": [
            ("/setup", "help.cat.admin.cmd.setup"),
            ("/settings", "help.cat.admin.cmd.settings"),
            ("/refeed", "help.cat.admin.cmd.refeed"),
            ("/refeed_channels", "help.cat.admin.cmd.refeed_channels"),
            ("!ping", "help.cat.admin.cmd.ping"),
        ],
    },
    "memes": {
        "emoji": "😏",
        "row": 1,
        "intro_key": "help.cat.memes.intro",
        "commands": [
            ("/momo · /meme", "help.cat.memes.cmd.momo"),
            ("Responder a una imagen + “generar”", "help.cat.memes.cmd.reply_generar"),
            ("Reacción 🎯 a una imagen", "help.cat.memes.cmd.reaction"),
            ("/settings → Memes", "help.cat.memes.cmd.settings"),
        ],
    },
    "youtube": {
        "emoji": "📺",
        "row": 1,
        "commands": [
            ("/settings → YouTube", "help.cat.youtube.cmd.settings"),
        ],
    },
    "panel": {
        "emoji": "🧩",
        "row": 1,
        "intro_key": "help.cat.panel.intro",
        "commands": [],
    },
}


def build_intro_embed(guild_name: str, locale: str = DEFAULT_LOCALE) -> discord.Embed:
    embed = discord.Embed(
        title=t("help.intro.title", locale),
        description=t("help.intro.description", locale),
        color=PURGITO_COLOR,
    )
    # Field en vez de footer: los footers de Discord no renderizan links clickeables.
    embed.add_field(
        name=t("help.intro.panel_field_name", locale),
        value=t("help.intro.panel_field_value", locale, url=PANEL_URL),
        inline=False,
    )
    embed.set_footer(text=t("help.intro.footer", locale, guild=guild_name))
    return embed


def build_category_embed(
    key: str, guild_name: str, locale: str = DEFAULT_LOCALE
) -> discord.Embed:
    cat = CATEGORIES[key]
    lines = []
    if "intro_key" in cat:
        lines.append(t(cat["intro_key"], locale, url=PANEL_URL))
        lines.append("")
    for cmd, desc_key in cat["commands"]:
        lines.append(f"`{cmd}` — {t(desc_key, locale)}")
    title = f"{cat['emoji']} {t(f'help.cat.{key}.label', locale)}"
    embed = discord.Embed(
        title=title, description="\n".join(lines), color=PURGITO_COLOR
    )
    embed.set_footer(text=t("help.category.footer", locale, guild=guild_name))
    return embed


class HelpView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        guild_name: str,
        locale: str = DEFAULT_LOCALE,
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.guild_name = guild_name
        self.locale = locale
        self.message: discord.Message | None = None

        home_button = discord.ui.Button(
            label=t("help.button.home", locale),
            emoji="🏠",
            style=discord.ButtonStyle.primary,
            row=0,
        )
        home_button.callback = self._make_home_callback()
        self.add_item(home_button)

        for key, cat in CATEGORIES.items():
            button = discord.ui.Button(
                label=t(f"help.cat.{key}.label", locale),
                emoji=cat["emoji"],
                style=discord.ButtonStyle.secondary,
                row=cat["row"],
            )
            button.callback = self._make_category_callback(key)
            self.add_item(button)

    def _make_home_callback(self):
        async def callback(interaction: discord.Interaction):
            embed = build_intro_embed(self.guild_name, self.locale)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_category_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            embed = build_category_embed(key, self.guild_name, self.locale)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                t("help.not_your_menu", self.locale),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
