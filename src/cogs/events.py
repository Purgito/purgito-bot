"""Eventos del servidor: Bienvenidas, Despedidas y Boosts de Discord.

Gestiona el envío de mensajes automáticos cuando ocurren eventos de miembros en el servidor.
Soporta mensajes de texto normal, embeds clásicos y Layout V2 con resolución de variables.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import discord
from discord.ext import commands

import i18n
from db import (
    add_button_action,
    extract_send_options,
    get_server_event,
    is_boost_processed,
    normalize_embeds_json,
    record_member_boost,
    try_record_member_boost,
)
from embeds_core import validate_embeds_payload
from layout_v2 import (
    BUTTON_COLORS,
    ROLE_TOGGLE_PREFIX,
    assign_button_custom_ids,
    build_layout_view,
    validate_layout_v2_payload,
)
from message_options import send_kwargs, wants_custom_identity
from placeholders import (
    _is_valid_http_url,
    _resolve_embed,
    build_event_context,
    get_preview_context,
    resolve_content_placeholders,
    resolve_placeholders,
)
from webhook_identity import WebhookIdentityError, send_via_webhook

log = logging.getLogger(__name__)


class ServerEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def dispatch_server_event(
        self,
        event_type: str,
        guild: discord.Guild,
        member: discord.Member | discord.User | None,
        channel_override: discord.TextChannel | None = None,
        is_test: bool = False,
        test_channel_id: int | None = None,
        mock_context: bool = False,
        content_override: dict | None = None,
        boost_info: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Despacha un evento de servidor (welcome, goodbye, boost) hacia Discord.

        Devuelve (True, None) si se envió correctamente, o (False, "motivo") si falló.
        """
        try:
            # get_server_event ya resuelve template_id -> contenido de la
            # plantilla (ver db.py); acá no hace falta ninguna rama nueva.
            config = content_override or await get_server_event(guild.id, event_type)
            if not config:
                return False, "Evento no configurado"

            if config.get("template_missing"):
                return False, "La plantilla asociada a este evento ya no existe"

            if not is_test and not config.get("enabled"):
                return False, "Evento desactivado"

            target_channel_id = (
                channel_override.id
                if channel_override
                else (test_channel_id or config.get("channel_id"))
            )
            if not target_channel_id:
                return False, "Canal destino no configurado"

            channel = guild.get_channel(int(target_channel_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(target_channel_id))
                except Exception:
                    channel = None

            if not channel or not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return False, "Canal destino no encontrado o no es de texto"

            if getattr(channel, "guild", None) and channel.guild.id != guild.id:
                return False, "El canal no pertenece a este servidor"

            me = guild.me or guild.get_member(self.bot.user.id if self.bot.user else 0)
            if me:
                perms = channel.permissions_for(me)
                if not perms.send_messages:
                    return False, "Purgito no tiene permiso para enviar mensajes en ese canal"

            locale = await i18n.guild_locale(guild.id)
            if mock_context or (is_test and (not member or isinstance(member, discord.User))):
                ctx = get_preview_context(event_type, guild=guild, locale=locale)
            else:
                ctx = build_event_context(
                    event_type,
                    guild,
                    member,
                    channel=channel,
                    boost_info=boost_info,
                    locale=locale,
                )

            content_mode = config.get("content_mode") or "plain_text"

            if content_mode == "plain_text":
                raw_msg = config.get("message") or ""
                if not raw_msg.strip():
                    return False, "Mensaje de texto vacío"
                final_msg = resolve_placeholders(raw_msg, ctx)
                if len(final_msg) > 2000:
                    return False, "El mensaje excede el límite de 2000 caracteres de Discord tras resolver variables"
                await channel.send(final_msg)

            elif content_mode == "classic_embed":
                if me and not channel.permissions_for(me).embed_links:
                    return False, "Purgito no tiene permiso para incrustar enlaces (embeds) en ese canal"

                raw_embed_json = config.get("embed_json")
                if not raw_embed_json:
                    return False, "Embed no configurado"

                embed_dicts = normalize_embeds_json(raw_embed_json)
                if not embed_dicts:
                    return False, "Lista de embeds vacía"

                options = extract_send_options(raw_embed_json)
                extra = send_kwargs(options)
                resolved_embed_dicts = [
                    _resolve_embed(e, ctx) for e in embed_dicts if isinstance(e, dict)
                ]
                val_err = validate_embeds_payload(resolved_embed_dicts)
                if val_err:
                    return False, f"El embed excede los límites de Discord tras resolver variables: {val_err}"

                embeds = [
                    discord.Embed.from_dict(e)
                    for e in resolved_embed_dicts
                    if e
                ]
                if not embeds:
                    return False, "Lista de embeds vacía tras resolver variables"

                if wants_custom_identity(options):
                    raw_user = options.get("username", "")
                    raw_avatar = options.get("avatar_url", "")
                    res_user = resolve_placeholders(raw_user, ctx).strip() if raw_user else ""
                    if len(res_user) > 80:
                        res_user = res_user[:80]
                    res_avatar = resolve_placeholders(raw_avatar, ctx).strip() if raw_avatar else ""
                    if res_avatar and not _is_valid_http_url(res_avatar):
                        res_avatar = ""

                    await send_via_webhook(
                        self.bot,
                        guild.id,
                        channel,
                        username=res_user,
                        avatar_url=res_avatar,
                        embeds=embeds,
                        **extra,
                    )
                else:
                    await channel.send(embeds=embeds, **extra)

            elif content_mode == "layout_v2":
                if me and not channel.permissions_for(me).embed_links:
                    return False, "Purgito no tiene permiso para incrustar componentes Layout V2 en ese canal"

                raw_embed_json = config.get("embed_json")
                if not raw_embed_json:
                    return False, "Layout no configurado"

                raw_layout = (
                    json.loads(raw_embed_json)
                    if isinstance(raw_embed_json, str)
                    else raw_embed_json
                )
                resolved_layout = resolve_content_placeholders(
                    "layout_v2", raw_layout, ctx
                )
                if not isinstance(resolved_layout, dict):
                    return False, "Estructura de Layout V2 inválida"

                val_err = validate_layout_v2_payload(resolved_layout)
                if val_err:
                    return False, f"El layout excede los límites de Discord tras resolver variables: {val_err}"

                options = extract_send_options(raw_embed_json)
                extra = send_kwargs(options)

                # Si el layout tiene botones de rol nuevos, registrarlos
                assignments = assign_button_custom_ids(resolved_layout)
                if assignments:
                    from cogs.layout_buttons import register_button_actions

                    rows = []
                    for a in assignments:
                        action_data = json.dumps({"role_id": a["role_id"]})
                        await add_button_action(
                            a["custom_id"], guild.id, "role_toggle", action_data
                        )
                        rows.append(
                            {
                                "custom_id": a["custom_id"],
                                "guild_id": guild.id,
                                "action_type": "role_toggle",
                                "action_data": action_data,
                            }
                        )
                    await register_button_actions(self.bot, rows)

                view = build_layout_view(resolved_layout)

                if wants_custom_identity(options):
                    raw_user = options.get("username", "")
                    raw_avatar = options.get("avatar_url", "")
                    res_user = resolve_placeholders(raw_user, ctx).strip() if raw_user else ""
                    if len(res_user) > 80:
                        res_user = res_user[:80]
                    res_avatar = resolve_placeholders(raw_avatar, ctx).strip() if raw_avatar else ""
                    if res_avatar and not _is_valid_http_url(res_avatar):
                        res_avatar = ""

                    await send_via_webhook(
                        self.bot,
                        guild.id,
                        channel,
                        username=res_user,
                        avatar_url=res_avatar,
                        view=view,
                        **extra,
                    )
                else:
                    await channel.send(view=view, **extra)

            elif content_mode == "composite":
                raw_msg = config.get("message") or ""
                final_msg = resolve_placeholders(raw_msg, ctx) if raw_msg.strip() else None
                if final_msg and len(final_msg) > 2000:
                    return False, "El mensaje excede el límite de 2000 caracteres de Discord tras resolver variables"

                embeds = None
                raw_embed_json = config.get("embed_json")
                options = {}
                view = None

                if raw_embed_json:
                    embed_dicts = normalize_embeds_json(raw_embed_json)
                    if embed_dicts:
                        if me and not channel.permissions_for(me).embed_links:
                            return False, "Purgito no tiene permiso para incrustar enlaces (embeds) en ese canal"
                        resolved_embed_dicts = [
                            _resolve_embed(e, ctx) for e in embed_dicts if isinstance(e, dict)
                        ]
                        val_err = validate_embeds_payload(resolved_embed_dicts)
                        if val_err:
                            return False, f"El embed excede los límites de Discord tras resolver variables: {val_err}"
                        embeds = [
                            discord.Embed.from_dict(e)
                            for e in resolved_embed_dicts
                            if e
                        ]
                    options = extract_send_options(raw_embed_json)

                    # Extract buttons
                    try:
                        parsed_raw = json.loads(raw_embed_json) if isinstance(raw_embed_json, str) else raw_embed_json
                        buttons_data = parsed_raw.get("buttons") if isinstance(parsed_raw, dict) else None
                    except Exception:
                        buttons_data = None

                    if buttons_data and isinstance(buttons_data, list) and len(buttons_data) > 0:
                        view = discord.ui.View()
                        for b in buttons_data[:5]:
                            if not isinstance(b, dict):
                                continue
                            b_label = resolve_placeholders(b.get("label", ""), ctx)[:80] or "Enlace"
                            b_url = resolve_placeholders(b.get("url", ""), ctx)
                            b_style = b.get("style", "link")
                            if b_style == "link" or b_url:
                                if _is_valid_http_url(b_url):
                                    view.add_item(discord.ui.Button(label=b_label, url=b_url, style=discord.ButtonStyle.link))
                            elif b_style == "role" and b.get("role_id"):
                                color_style = BUTTON_COLORS.get(b.get("color"), discord.ButtonStyle.secondary)
                                custom_id = b.get("custom_id") or f"{ROLE_TOGGLE_PREFIX}{uuid.uuid4().hex[:12]}"
                                view.add_item(discord.ui.Button(label=b_label, style=color_style, custom_id=custom_id))

                if not final_msg and not embeds and not view:
                    return False, "No hay contenido configurado para enviar"

                extra = send_kwargs(options)
                send_params = {}
                if final_msg:
                    send_params["content"] = final_msg
                if embeds:
                    send_params["embeds"] = embeds
                if view:
                    send_params["view"] = view

                if wants_custom_identity(options):
                    raw_user = options.get("username", "")
                    raw_avatar = options.get("avatar_url", "")
                    res_user = resolve_placeholders(raw_user, ctx).strip() if raw_user else ""
                    if len(res_user) > 80:
                        res_user = res_user[:80]
                    res_avatar = resolve_placeholders(raw_avatar, ctx).strip() if raw_avatar else ""
                    if res_avatar and not _is_valid_http_url(res_avatar):
                        res_avatar = ""

                    await send_via_webhook(
                        self.bot,
                        guild.id,
                        channel,
                        username=res_user,
                        avatar_url=res_avatar,
                        **send_params,
                        **extra,
                    )
                else:
                    await channel.send(**send_params, **extra)
            else:
                return False, f"Modo de contenido no soportado: {content_mode}"

            log.info(
                "[eventos] %s enviado con éxito guild=%s channel=%s user=%s mode=%s is_test=%s",
                event_type,
                guild.id,
                target_channel_id,
                getattr(member, "id", "none"),
                content_mode,
                is_test,
            )
            return True, None

        except WebhookIdentityError as e:
            log.warning(
                "[eventos] %s fallo de webhook identity guild=%s: %s",
                event_type,
                guild.id,
                e,
            )
            return False, f"Error de identidad de webhook: {e}"
        except discord.Forbidden as e:
            log.warning(
                "[eventos] %s permisos insuficientes guild=%s channel=%s: %s",
                event_type,
                guild.id,
                target_channel_id if "target_channel_id" in locals() else "?",
                e,
            )
            return False, "Purgito no tiene permisos suficientes para enviar el mensaje"
        except discord.HTTPException as e:
            log.warning(
                "[eventos] %s error HTTP Discord guild=%s channel=%s: %s",
                event_type,
                guild.id,
                target_channel_id if "target_channel_id" in locals() else "?",
                e,
            )
            return False, f"Discord rechazó el mensaje: {e.text or e}"
        except Exception as e:
            log.exception(
                "[eventos] %s error inesperado guild=%s channel=%s",
                event_type,
                guild.id,
                target_channel_id if "target_channel_id" in locals() else "?",
            )
            return False, f"Error interno: {e}"

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        await self.dispatch_server_event("welcome", member.guild, member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if getattr(member, "bot", False):
            return
        await self.dispatch_server_event("goodbye", member.guild, member)

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        # Detecta transición de "no boosteaba" a "empieza a boostear"
        if before.premium_since is None and after.premium_since is not None:
            premium_since_iso = after.premium_since.isoformat()
            won = await try_record_member_boost(after.guild.id, after.id, premium_since_iso)
            if not won:
                return
            await self.dispatch_server_event(
                "boost",
                after.guild,
                after,
                boost_info={"premium_since": after.premium_since},
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerEvents(bot))
