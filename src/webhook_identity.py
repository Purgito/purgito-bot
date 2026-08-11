"""Identidad personalizada por mensaje (nombre/avatar) vía un webhook propio
del bot -- Fase 3 del diagnóstico embeds/dashboard.

Confirmado antes de implementar esto: un webhook creado por el propio bot
(`channel.create_webhook`) sigue perteneciendo a la aplicación de Purgito, así
que los clics en sus botones llegan igual por el gateway normal -- discord.py
rutea por custom_id sin importarle si el mensaje se mandó con channel.send()
o con este webhook (ver cogs/layout_buttons.py). La única condición técnica
real es reconstruir el Webhook con `client=bot` (no `Webhook.from_url` ni
`session=` a secas) para que tenga el estado de conexión real adjunto -- sin
eso, discord.py rechaza mandar una vista con componentes interactivos
("Webhook views with interactable components require an associated state
with the webhook", confirmado leyendo discord/webhook/async_.py).

Vive en su propio módulo por el mismo motivo que message_options.py: lo
comparten webapi.py (envío inmediato) y cogs/anuncios.py (envío programado),
sin arrastrar dependencias de uno al otro.

Nota aparte: Webhook.send() no tiene un parámetro `delete_after` (a
diferencia de channel.send) -- los callers de acá no se lo pasan nunca; el
borrado programado de mensajes enviados por este camino depende enteramente
de add_pending_deletion (la red de seguridad que ya existía para eso), no del
atajo rápido en memoria.
"""

import logging

import discord

import db

log = logging.getLogger(__name__)

WEBHOOK_NAME = "Purgito"
_CREATE_REASON = "Identidad personalizada de mensajes (panel de Purgito)"
_MAX_WEBHOOKS_PER_CHANNEL_CODE = 30007  # código real de Discord para el tope de 15


class WebhookIdentityError(Exception):
    """Mensaje ya listo para mostrarle al admin -- no un traceback interno."""


async def _find_existing_webhook(
    channel: discord.TextChannel, bot_user_id: int
) -> discord.Webhook | None:
    """Busca un webhook ya creado por este bot en el canal, por si la fila de
    channel_webhooks se perdió (DB reseteada, migración) pero el webhook en
    Discord sigue vivo -- evita duplicar y chocar el tope de 15."""
    try:
        webhooks = await channel.webhooks()
    except discord.Forbidden:
        return None
    for w in webhooks:
        if w.user and w.user.id == bot_user_id and w.token:
            return w
    return None


async def resolve_channel_webhook(
    bot: discord.Client, guild_id: int, channel: discord.TextChannel
) -> discord.Webhook:
    """Webhook usable (con estado real adjunto vía client=bot) para este
    canal, creándolo si hace falta. Levanta WebhookIdentityError con un
    mensaje legible si no se puede -- nunca falla en silencio."""
    row = await db.get_channel_webhook(guild_id, channel.id)
    if row:
        return discord.Webhook.partial(
            row["webhook_id"], row["webhook_token"], client=bot
        )

    existing = await _find_existing_webhook(channel, bot.user.id)
    if existing is not None:
        await db.set_channel_webhook(guild_id, channel.id, existing.id, existing.token)
        return discord.Webhook.partial(existing.id, existing.token, client=bot)

    try:
        created = await channel.create_webhook(name=WEBHOOK_NAME, reason=_CREATE_REASON)
    except discord.Forbidden:
        raise WebhookIdentityError(
            'Purgito no tiene permiso de "Gestionar webhooks" en ese canal '
            "-- puede estar overrideado a nivel canal aunque el bot lo tenga "
            "a nivel servidor."
        ) from None
    except discord.HTTPException as e:
        if e.code == _MAX_WEBHOOKS_PER_CHANNEL_CODE:
            raise WebhookIdentityError(
                "Ese canal ya llegó al máximo de 15 webhooks de Discord -- "
                "borra alguna integración que ya no se use ahí antes de "
                "mandar con nombre/avatar personalizado."
            ) from None
        raise WebhookIdentityError(
            "No se pudo crear el webhook para este canal, intenta de nuevo."
        ) from None

    await db.set_channel_webhook(guild_id, channel.id, created.id, created.token)
    return discord.Webhook.partial(created.id, created.token, client=bot)


async def send_via_webhook(
    bot: discord.Client,
    guild_id: int,
    channel: discord.TextChannel,
    *,
    username: str = "",
    avatar_url: str = "",
    **kwargs,
) -> discord.WebhookMessage:
    """Resuelve el webhook del canal y manda por ahí. Si el webhook guardado
    ya no existe en Discord (borrado a mano desde las integraciones del
    canal), limpia la fila y devuelve un error pidiendo reintentar -- el
    próximo intento lo recrea solo, sin loop de reintento automático acá."""
    webhook = await resolve_channel_webhook(bot, guild_id, channel)
    if username:
        kwargs["username"] = username
    if avatar_url:
        kwargs["avatar_url"] = avatar_url
    try:
        return await webhook.send(wait=True, **kwargs)
    except discord.NotFound:
        await db.delete_channel_webhook(guild_id, channel.id)
        raise WebhookIdentityError(
            "El webhook de este canal ya no existe en Discord (probablemente "
            "se borró a mano) -- intenta de nuevo, se va a crear uno nuevo."
        ) from None
