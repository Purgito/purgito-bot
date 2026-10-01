"""Crédito "Enviado por <usuario>" para el contenido que el bot sube suelto
como respuesta a un comando (cogs/download.py, cogs/imagefx.py,
cogs/memes.py).

Si borran el mensaje del comando, el reply del bot queda sin referencia y el
archivo sigue en el canal sin decir quién lo pidió -- para moderar, el crédito
tiene que estar en el propio mensaje del bot. Solo se agrega donde ese
mensaje sale "suelto": un comando de texto (prefijo o "purgito <palabra>")
dentro de un servidor. No en un slash (Discord ya pega "<usuario> usó /dl" a
la respuesta) ni en un DM (solo están el usuario y el bot). Tampoco en lo que
el bot postea por su cuenta (memes automáticos, GIFs espontáneos): ahí no hay
nadie a quien atribuirle nada.
"""

import discord
from discord.ext import commands

from i18n import t

# Sin pings por el texto del crédito: el reply ya avisa al autor del comando,
# que es el mismo usuario que se menciona ahí -- users=False apaga el ping del
# contenido y replied_user=True conserva el del reply, igual que antes de
# existir el crédito.
_MENTIONS = discord.AllowedMentions(
    everyone=False, roles=False, users=False, replied_user=True
)


def sent_by_credit(locale: str, author: discord.abc.User) -> dict:
    """kwargs (content + allowed_mentions) para el reply que sube el archivo.
    Para quien no tiene un Context (un on_message, ej. cogs/memes.py) y ya
    sabe que está en un servidor, respondiendo a un mensaje suelto; el resto
    usa reply_with_file."""
    return {
        "content": t("general.sent_by", locale, user=author.mention),
        "allowed_mentions": _MENTIONS,
    }


async def reply_with_file(
    ctx: commands.Context, locale: str, file: discord.File
) -> None:
    """Sube `file` como respuesta al comando, con "Enviado por <usuario>"
    cuando corresponde (ver el docstring del módulo)."""
    if ctx.interaction is not None or ctx.guild is None:
        await ctx.reply(file=file)
        return
    await ctx.reply(file=file, **sent_by_credit(locale, ctx.author))
