"""
/help de Purgito: embed intro + botones de navegación por categoría.
El comando en sí vive en cogs/general.py; aquí solo están los embeds y la vista.
"""

import discord

from config import PANEL_URL

PURGITO_COLOR = 0x8B00FF  # color de marca usado en todo el proyecto

INTRO_DESCRIPTION = (
    "**Purgito** es el bot del servidor: aprende a hablar como la comunidad "
    "usando cadenas de Markov entrenadas con los propios mensajes del server, "
    "guarda los GIFs que se comparten en una galería pública "
    "y avisa cuando tus creadores favoritos de YouTube publican contenido nuevo.\n\n"
    "Desde el panel web también puedes armar embeds y mensajes con botones "
    "interactivos —incluyendo botones que asignan un rol— sin escribir código.\n\n"
    "Todos los comandos son **slash commands** (`/`) — escribe `/` en el chat y "
    "Discord te va a mostrar las opciones con autocompletado. La única excepción "
    "es `!ping`, que es un comando de texto clásico.\n\n"
    "Usa los botones de abajo para ver los comandos de cada sección."
)

CATEGORIES = {
    "chat": {
        "emoji": "🤖",
        "label": "Markov / Chat",
        "title": "🤖 Markov / Chat",
        "row": 0,
        "commands": [
            ("/generar", "genera un mensaje con Markov"),
            ("/imitar @usuario", "imita el estilo de un miembro"),
            ("/corpus_info", "mensajes en el corpus del canal"),
            ("/settings → Chat / Frases", "auto-reply y frases especiales"),
        ],
    },
    "memes": {
        "emoji": "😏",
        "label": "Memes ⭐",
        "title": "😏 Memes ⭐",
        "row": 0,
        "intro": "⭐ **Función premium** — no disponible en todos los servidores.",
        "commands": [
            ("/momo · /meme", "genera un meme de la colección de imágenes"),
            ("Responder a una imagen + “generar”", "meme de esa imagen"),
            ("Reacción 🎯 a una imagen", "la agrega a la colección de memes"),
            ("/settings → Memes", "memes automáticos por canal"),
        ],
    },
    "youtube": {
        "emoji": "📺",
        "label": "YouTube",
        "title": "📺 YouTube",
        "row": 1,
        "commands": [
            (
                "/settings → YouTube",
                "suscribe canales, elige dónde anunciar y qué rol mencionar",
            ),
        ],
    },
    "admin": {
        "emoji": "⚙️",
        "label": "Administración",
        "title": "⚙️ Administración",
        "row": 1,
        "commands": [
            ("/settings", "panel de configuración del servidor"),
            ("/setup", "guía de configuración inicial"),
            ("/refeed", "importa mensajes del canal al corpus"),
            ("/refeed_all", "importa todos los canales"),
            (
                "/settings → Corpus / Reacciones",
                "canales ignorados, wipe del corpus y pool de emojis",
            ),
            ("/gif_add <url>", "añade un GIF a la colección ⭐"),
            ("!ping", "verifica que el bot está online"),
        ],
    },
    "panel": {
        "emoji": "🧩",
        "label": "Panel web",
        "title": "🧩 Panel web",
        "row": 1,
        "intro": (
            f"Estas funciones viven en el panel web ({PANEL_URL}), no son slash commands.\n\n"
            "🧩 **Editor de embeds** — arma embeds clásicos (hasta 10 por mensaje) o "
            "layouts con Components V2: contenedores, secciones, galerías de imágenes "
            "y separadores.\n"
            "🔘 **Botones interactivos** — agrega botones de enlace o botones que "
            "asignan/quitan un rol al hacer clic.\n"
            "🖼️ **Imágenes** — sube imágenes directo desde tu computador o pega una URL.\n"
            "💾 **Plantillas** — guarda tus embeds favoritos para reusarlos después."
        ),
        "commands": [],
    },
}


def build_intro_embed(guild_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="📖 ¿Qué es Purgito?",
        description=INTRO_DESCRIPTION,
        color=PURGITO_COLOR,
    )
    # Field en vez de footer: los footers de Discord no renderizan links clickeables.
    embed.add_field(
        name="⚙️ Panel web",
        value=f"Configura Purgito desde el navegador: {PANEL_URL}",
        inline=False,
    )
    embed.set_footer(
        text=f"Comandos disponibles en {guild_name} · usa los botones de abajo"
    )
    return embed


def build_category_embed(key: str, guild_name: str) -> discord.Embed:
    cat = CATEGORIES[key]
    lines = []
    if "intro" in cat:
        lines.append(cat["intro"])
        lines.append("")
    for cmd, desc in cat["commands"]:
        lines.append(f"`{cmd}` — {desc}")
    embed = discord.Embed(
        title=cat["title"], description="\n".join(lines), color=PURGITO_COLOR
    )
    embed.set_footer(text=f"{guild_name} · /help para volver al inicio")
    return embed


class HelpView(discord.ui.View):
    def __init__(self, author_id: int, guild_name: str, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.guild_name = guild_name
        self.message: discord.Message | None = None

        home_button = discord.ui.Button(
            label="Inicio", emoji="🏠", style=discord.ButtonStyle.primary, row=0
        )
        home_button.callback = self._make_home_callback()
        self.add_item(home_button)

        for key, cat in CATEGORIES.items():
            button = discord.ui.Button(
                label=cat["label"],
                emoji=cat["emoji"],
                style=discord.ButtonStyle.secondary,
                row=cat["row"],
            )
            button.callback = self._make_category_callback(key)
            self.add_item(button)

    def _make_home_callback(self):
        async def callback(interaction: discord.Interaction):
            embed = build_intro_embed(self.guild_name)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_category_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            embed = build_category_embed(key, self.guild_name)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Este menú lo abrió otra persona — usa `/help` para abrir el tuyo.",
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
