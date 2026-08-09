"""General: /help, !ping, manejo de errores y ciclo de vida de guilds (limpieza diferida)."""

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import r2
from cogs.premium import discard_premium_guild
from config import PURGATORY_GUILD_ID, env_int
from db import (
    clear_guild_departure,
    get_expired_departures,
    list_gif_urls,
    list_image_urls,
    mark_guild_departed,
    purge_expired_revoked_sessions,
    purge_expired_shared_embeds,
    purge_guild_data,
    purge_old_audit_log_entries,
    release_gif_reference,
)
from help_view import PURGITO_COLOR, HelpView, build_intro_embed
from i18n import guild_locale, t

log = logging.getLogger(__name__)

VOTE_URL = "https://top.gg/bot/1471724794411089920/vote"


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.guild_cleanup_task.start()
        # Errores de slash commands: sin esto, cualquier excepción termina en
        # "La aplicación no respondió" sin feedback. on_command_error (abajo)
        # solo cubre comandos de prefijo.
        self.bot.tree.on_error = self.on_app_command_error

    async def cog_unload(self) -> None:
        self.guild_cleanup_task.cancel()

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        await ctx.send("Pong!")

    @app_commands.command(
        name="help", description="Muestra los comandos de Purgito y cómo usarlos."
    )
    async def help(self, interaction: discord.Interaction):
        locale = await guild_locale(interaction.guild.id if interaction.guild else None)
        guild_name = (
            interaction.guild.name
            if interaction.guild
            else t("general.help.default_guild_name", locale)
        )
        embed = build_intro_embed(guild_name, locale)
        view = HelpView(author_id=interaction.user.id, guild_name=guild_name, locale=locale)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(
        name="vote", description="Link para votar por Purgito en top.gg."
    )
    async def vote(self, interaction: discord.Interaction):
        locale = await guild_locale(interaction.guild.id if interaction.guild else None)
        embed = discord.Embed(
            title=t("general.vote.title", locale),
            description=t("general.vote.description", locale, url=VOTE_URL),
            color=PURGITO_COLOR,
        )
        await interaction.response.send_message(embed=embed)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        locale = await guild_locale(interaction.guild.id if interaction.guild else None)
        if isinstance(error, app_commands.CommandOnCooldown):
            # No es un error real: avisar el tiempo de espera, sin loguear ni
            # pisar la respuesta con el mensaje genérico de abajo.
            msg = t(
                "general.error.cooldown", locale, seconds=f"{error.retry_after:.0f}"
            )
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.followup.send(msg, ephemeral=True)
            except (discord.HTTPException, discord.ClientException):
                pass
            return

        # CommandInvokeError envuelve la excepción real; se desenvuelve para
        # que el traceback del log muestre la causa y no solo el wrapper.
        original = getattr(error, "original", error)
        command = interaction.command.name if interaction.command else "desconocido"
        log.error("Error en slash command /%s", command, exc_info=original)
        try:
            msg = t("general.error.generic", locale)
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            elif (
                interaction.response.type
                is discord.InteractionResponseType.deferred_channel_message
            ):
                # Defer sin resolver ("pensando…"): editar no pierde contenido
                # y hereda la visibilidad original del defer.
                await interaction.edit_original_response(
                    content=msg, embed=None, view=None
                )
            else:
                # Ya se mostró una respuesta real (ej. /help y su embed): no
                # pisarla con el error, avisar en un mensaje efímero aparte.
                await interaction.followup.send(msg, ephemeral=True)
        except (discord.HTTPException, discord.ClientException):
            # Interacción expirada (>3 s sin defer) u otro rechazo de Discord:
            # ya quedó logueado el error real, no hay nada más que hacer.
            log.debug(
                "No se pudo avisar el error de /%s al usuario", command, exc_info=True
            )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            locale = await guild_locale(ctx.guild.id if ctx.guild else None)
            await ctx.send(t("general.error.no_permission", locale))
            return
        elif isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            locale = await guild_locale(ctx.guild.id if ctx.guild else None)
            await ctx.send(t("general.error.missing_argument", locale))
            return
        log.error("Error en comando %s", getattr(ctx, "command", None), exc_info=error)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await clear_guild_departure(guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        if guild.id == PURGATORY_GUILD_ID:
            return
        await mark_guild_departed(guild.id)
        log.info(
            "on_guild_remove: guild %s (%s) marcado para limpieza diferida",
            guild.id,
            guild.name,
        )

    @tasks.loop(hours=24)
    async def guild_cleanup_task(self):
        try:
            stale_shares = await purge_expired_shared_embeds()
            if stale_shares:
                log.info(
                    "guild_cleanup: %d link(s) de embed compartido vencidos borrados",
                    stale_shares,
                )
            stale_revocations = await purge_expired_revoked_sessions()
            if stale_revocations:
                log.info(
                    "guild_cleanup: %d sid(s) de sesión revocada vencidos borrados",
                    stale_revocations,
                )
            audit_retention = env_int("AUDIT_LOG_RETENTION_DAYS", 90)
            stale_audit = await purge_old_audit_log_entries(audit_retention)
            if stale_audit:
                log.info(
                    "guild_cleanup: %d entrada(s) de audit_log vencidas borradas",
                    stale_audit,
                )
            retention = env_int("GUILD_DATA_RETENTION_DAYS", 30)
            expired = await get_expired_departures(retention)
            if not expired:
                return
            purged = 0
            for guild_id in expired:
                # expired se armó con una sola lectura al principio del loop;
                # purgar guilds grandes (muchos GIFs) puede tardar. Si el bot
                # vuelve a este guild mientras tanto, on_guild_join ya limpió
                # guild_departures, pero esa lectura vieja no se entera -- sin
                # este re-chequeo, un guild recién reincorporado perdería su
                # corpus/GIFs/config igual, de forma irreversible. bot.get_guild
                # refleja la membresía ACTUAL, no la de cuando arrancó el loop.
                if self.bot.get_guild(guild_id) is not None:
                    log.info(
                        "guild_cleanup: guild %s volvió a estar activo, se salta la purga",
                        guild_id,
                    )
                    continue
                try:
                    if r2.available() and r2.public_url():
                        # release_gif_reference, NO r2.delete_url: los GIFs con
                        # content_hash son objetos content-addressed compartidos
                        # entre guilds (ver el comentario de gif_objects en el
                        # schema) -- borrar por url directo, como se hacía antes,
                        # se llevaba puesto el objeto de OTRO guild que todavía
                        # lo referenciaba, dejándolo con un link roto. Las
                        # imágenes sí son 1:1 por guild (key con {guild_id}/
                        # de prefijo) así que esas siguen borrándose por url.
                        for item in await list_gif_urls(guild_id):
                            await release_gif_reference(
                                item["content_hash"], item["url"]
                            )
                        for img_url in await list_image_urls(guild_id):
                            await r2.delete_url(img_url)
                    await purge_guild_data(guild_id)
                    discard_premium_guild(guild_id)
                    purged += 1
                except Exception:
                    log.exception("guild_cleanup: error purgando guild %s", guild_id)
            if purged:
                log.info("guild_cleanup: %d servidor(es) purgados", purged)
        except Exception:
            log.exception("Error en guild_cleanup_task")

    @guild_cleanup_task.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
