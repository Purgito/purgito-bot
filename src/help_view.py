"""
/help de Purgito: embed intro + botones de navegación por categoría.
El comando en sí vive en cogs/general.py; aquí solo están los embeds y la vista.
"""

import discord

from config import PANEL_URL, get_dashboard_url
from i18n import DEFAULT_LOCALE, t
from utils import SafeView

PURGITO_COLOR = 0x8B00FF  # color de marca usado en todo el proyecto

# Estructura (sin texto traducible): emoji, orden de los botones y, por
# categoría, la lista de (comando literal, clave de i18n de su descripción).
# El texto real (labels, intros, descripciones) vive en locales/{es,en}.json
# bajo "help.cat.<key>.*" -- ver build_category_embed/HelpView. Los comandos
# de prefijo usan el placeholder "{prefix}" en vez de "!" literal: el símbolo
# es personalizable por guild (ver get_guild_prefix en db.py) y build_category_embed
# lo resuelve con .format() antes de mostrarlo.
CATEGORIES = {
    "chat": {
        "emoji": "💬",
        "row": 0,
        "commands": [
            ("/generar", "help.cat.chat.cmd.generar"),
            ("/imitar @usuario", "help.cat.chat.cmd.imitar"),
            ("/imitar_mezcla", "help.cat.chat.cmd.imitar_mezcla"),
            ("/corpus_info", "help.cat.chat.cmd.corpus_info"),
            ("/settings", "help.cat.chat.cmd.settings"),
            ("{prefix}dl <link> · purgito dl <link>", "help.cat.chat.cmd.dl"),
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
            ("{prefix}ping", "help.cat.admin.cmd.ping"),
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
    "twitch": {
        "emoji": "🔴",
        "row": 1,
        "commands": [
            ("/settings → Twitch", "help.cat.twitch.cmd.settings"),
        ],
    },
    "panel": {
        "emoji": "🧩",
        "row": 1,
        "intro_key": "help.cat.panel.intro",
        "commands": [],
    },
    "imagen": {
        "emoji": "🖼️",
        "row": 1,
        "intro_key": "help.cat.imagen.intro",
        "commands": [
            ("{prefix}caption <arriba>|<abajo>", "help.cat.imagen.cmd.caption"),
            ("{prefix}deepfry", "help.cat.imagen.cmd.deepfry"),
            ("{prefix}wide", "help.cat.imagen.cmd.wide"),
            ("{prefix}squish", "help.cat.imagen.cmd.squish"),
            ("{prefix}invert", "help.cat.imagen.cmd.invert"),
            ("{prefix}greyscale", "help.cat.imagen.cmd.greyscale"),
            ("{prefix}sepia", "help.cat.imagen.cmd.sepia"),
            ("{prefix}pixelate", "help.cat.imagen.cmd.pixelate"),
            ("{prefix}rotate <grados>", "help.cat.imagen.cmd.rotate"),
            ("{prefix}flip", "help.cat.imagen.cmd.flip"),
            ("{prefix}flop", "help.cat.imagen.cmd.flop"),
            ("{prefix}circle", "help.cat.imagen.cmd.circle"),
            ("{prefix}blur", "help.cat.imagen.cmd.blur"),
            ("{prefix}sharpen", "help.cat.imagen.cmd.sharpen"),
            ("{prefix}triggered", "help.cat.imagen.cmd.triggered"),
            ("{prefix}wasted", "help.cat.imagen.cmd.wasted"),
            ("{prefix}trash", "help.cat.imagen.cmd.trash"),
            ("{prefix}communism", "help.cat.imagen.cmd.communism"),
            ("{prefix}gay", "help.cat.imagen.cmd.gay"),
            ("{prefix}jail", "help.cat.imagen.cmd.jail"),
            ("{prefix}wanted", "help.cat.imagen.cmd.wanted"),
            ("{prefix}rip", "help.cat.imagen.cmd.rip"),
            ("{prefix}america", "help.cat.imagen.cmd.america"),
            ("{prefix}polaroid", "help.cat.imagen.cmd.polaroid"),
            ("{prefix}poster", "help.cat.imagen.cmd.poster"),
            ("{prefix}threshold", "help.cat.imagen.cmd.threshold"),
            ("{prefix}emboss", "help.cat.imagen.cmd.emboss"),
            ("{prefix}gif", "help.cat.imagen.cmd.gif"),
            ("{prefix}gifcaption <arriba>|<abajo>", "help.cat.imagen.cmd.gifcaption"),
            ("{prefix}gifspeed <factor>", "help.cat.imagen.cmd.gifspeed"),
            ("{prefix}gifreverse", "help.cat.imagen.cmd.gifreverse"),
            ("{prefix}gifwide", "help.cat.imagen.cmd.gifwide"),
        ],
    },
}


def _panel_url(guild_id: int | None, locale: str) -> str:
    # Sin guild_id (ej. /help en DM) no hay servidor al que apuntar el
    # dashboard -- se cae a la landing. Con guild_id, el link va directo al
    # dashboard de ESE servidor (get_dashboard_url), no a la landing pelada:
    # si el usuario ya tiene sesión lo abre directo, y si no, el propio JS
    # del dashboard (ver landing/js/core/api.js) lo manda a /auth/login con
    # `from` apuntando de vuelta a esta misma URL, así que el login no lo
    # deja tirado en la landing.
    if guild_id is None:
        return PANEL_URL
    return get_dashboard_url(guild_id, locale)


def build_intro_embed(
    guild_name: str, locale: str = DEFAULT_LOCALE, guild_id: int | None = None
) -> discord.Embed:
    embed = discord.Embed(
        title=t("help.intro.title", locale),
        description=t("help.intro.description", locale),
        color=PURGITO_COLOR,
    )
    # Field en vez de footer: los footers de Discord no renderizan links clickeables.
    embed.add_field(
        name=t("help.intro.panel_field_name", locale),
        value=t(
            "help.intro.panel_field_value", locale, url=_panel_url(guild_id, locale)
        ),
        inline=False,
    )
    embed.set_footer(text=t("help.intro.footer", locale, guild=guild_name))
    return embed


def build_category_embed(
    key: str,
    guild_name: str,
    prefix: str,
    locale: str = DEFAULT_LOCALE,
    guild_id: int | None = None,
) -> discord.Embed:
    cat = CATEGORIES[key]
    lines = []
    if "intro_key" in cat:
        lines.append(
            t(cat["intro_key"], locale, url=_panel_url(guild_id, locale), prefix=prefix)
        )
        lines.append("")
    for cmd, desc_key in cat["commands"]:
        lines.append(
            f"`{cmd.format(prefix=prefix)}` — {t(desc_key, locale, prefix=prefix)}"
        )
    title = f"{cat['emoji']} {t(f'help.cat.{key}.label', locale)}"
    embed = discord.Embed(
        title=title, description="\n".join(lines), color=PURGITO_COLOR
    )
    embed.set_footer(text=t("help.category.footer", locale, guild=guild_name))
    return embed


class HelpView(SafeView):
    def __init__(
        self,
        author_id: int,
        guild_name: str,
        prefix: str,
        locale: str = DEFAULT_LOCALE,
        timeout: float = 180.0,
        guild_id: int | None = None,
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.guild_name = guild_name
        self.prefix = prefix
        self.locale = locale
        self.guild_id = guild_id
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
            embed = build_intro_embed(self.guild_name, self.locale, self.guild_id)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_category_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            embed = build_category_embed(
                key, self.guild_name, self.prefix, self.locale, self.guild_id
            )
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
