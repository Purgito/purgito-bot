"""Captura y gestión de GIFs: detección en mensajes, subida a R2, galería web."""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import discord
from discord import app_commands
from discord.ext import commands, tasks

import r2
from db import (
    count_gif_urls,
    get_gifs_for_health_check,
    get_live_gif_keys,
    get_random_gif_candidates,
    get_unresolved_gifs,
    is_channel_ignored,
    record_gif_health_check,
    save_gif_url,
    update_gif_media_url,
)
from utils import has_admin_permission

log = logging.getLogger(__name__)

GIF_RE = re.compile(
    r"https?://\S*(tenor\.com|giphy\.com|cdn\.discordapp\.com/attachments/\S*\.gif)\S*",
    re.IGNORECASE,
)


def _gif_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_gif_site(host: str) -> bool:
    return host in ("tenor.com", "giphy.com") or host.endswith(
        (".tenor.com", ".giphy.com")
    )


async def save_gif_candidates(guild_id: int, message: discord.Message) -> int:
    """Guarda en la colección los GIFs (tenor/giphy/cdn) del contenido y adjuntos de un mensaje.
    Retorna cuántos GIFs nuevos (no duplicados) se guardaron."""
    saved = 0
    if message.content:
        for m in GIF_RE.finditer(message.content):
            try:
                url = m.group(0)
                # Se valida el host real: el regex matchea el dominio como
                # substring y dejaría pasar "https://evil.com/?tenor.com".
                host = _gif_host(url)
                content_hash, size_bytes, phash = None, 0, None
                if host == "cdn.discordapp.com":
                    up = await asyncio.to_thread(r2.upload_gif_sync, url)
                    if not up or up.url == r2.GIF_TOO_LARGE:
                        # Sin subida a R2 no hay URL estable que guardar: el
                        # link crudo de cdn.discordapp.com está firmado y
                        # expira, así que quedaría roto en el corpus.
                        continue
                    url, content_hash, size_bytes, phash = up
                elif not _is_gif_site(host):
                    continue
                inserted, _ = await save_gif_url(
                    guild_id, url, content_hash, size_bytes, phash
                )
                if inserted:
                    saved += 1
            except Exception:
                log.exception("Error guardando GIF de mensaje: %s", m.group(0))

    for attachment in message.attachments:
        if attachment.url and (
            attachment.url.lower().endswith(".gif")
            or (attachment.content_type and "gif" in attachment.content_type)
        ):
            try:
                url = attachment.url
                content_hash, size_bytes, phash = None, 0, None
                if "cdn.discordapp.com" in url:
                    up = await asyncio.to_thread(r2.upload_gif_sync, url)
                    if not up or up.url == r2.GIF_TOO_LARGE:
                        continue
                    url, content_hash, size_bytes, phash = up
                inserted, _ = await save_gif_url(
                    guild_id, url, content_hash, size_bytes, phash
                )
                if inserted:
                    saved += 1
            except Exception:
                log.exception("Error guardando GIF adjunto: %s", attachment.url)
    return saved


async def resolve_media_url(url: str) -> str | None:
    import requests

    try:
        if "cdn.discordapp.com" in url or (
            r2.public_url() and url.startswith(r2.public_url())
        ):
            return url
        if "tenor.com" in url:
            resp = await asyncio.to_thread(
                requests.get,
                f"https://tenor.com/oembed?url={quote(url, safe='')}&format=json",
                timeout=8,
            )
            # El oEmbed de tenor no trae un campo "url": el único media real
            # que expone es "thumbnail_url" (un .png estático del gif). No es
            # el gif animado, pero alcanza para el chequeo de salud -- que es
            # el único consumidor de media_url.
            return resp.json()["thumbnail_url"]
        if "giphy.com" in url:
            resp = await asyncio.to_thread(
                requests.get,
                f"https://giphy.com/services/oembed?url={quote(url, safe='')}&format=json",
                timeout=8,
            )
            # A diferencia de tenor, el oEmbed de giphy sí trae el .gif real
            # bajo "url" -- no tiene "thumbnail_url".
            return resp.json()["url"]
    except Exception:
        return None
    return None


async def get_live_gif(
    guild_id: int, attempts: int = 3, timeout: float = 3.0
) -> str | None:
    """Elige un GIF random, valida que cargue, prueba otro si está muerto.

    Reusa el mismo chequeo tri-estado que el ciclo de salud diario
    (r2.check_gif_url_health + db.record_gif_health_check): un timeout o
    error de red puntual ("unreachable") no cuenta como confirmación de que
    el link esté roto, recién se borra a los 2 "dead" confirmados seguidos
    (404/410 o content-type inválido). Antes usaba is_url_alive, que
    consideraba "muerto" cualquier fallo -- un solo bloqueo de rate-limit o
    timeout del host ya sumaba, y a la 3ra vez borraba un GIF que en Discord
    seguía funcionando perfecto.
    """
    for gif in await get_random_gif_candidates(guild_id, limit=attempts):
        url = gif["media_url"] or gif["url"]
        status = await asyncio.to_thread(r2.check_gif_url_health, url, timeout)
        await record_gif_health_check(gif["id"], status)
        if status == "ok":
            return url
    return None


# Espaciado entre chequeos del ciclo de salud, para no golpear el mismo host
# en ráfaga -- ver check_gif_url_health/record_gif_health_check en db.py/r2.py.
HEALTH_CHECK_DELAY = 1.5
HEALTH_CHECK_BATCH = 500


async def run_gif_health_check(
    guild_id: int | None = None, limit: int = HEALTH_CHECK_BATCH
) -> int:
    """Revisa hasta `limit` GIFs (de un guild puntual, o de todos si es
    None -- usado por el ciclo diario) contra el propio host y guarda el
    resultado. Usado tanto por el loop periódico como por el botón manual
    "Verificar GIFs" del panel."""
    gifs = await get_gifs_for_health_check(guild_id, limit=limit)
    for gif in gifs:
        url = gif["media_url"] or gif["url"]
        status = await asyncio.to_thread(r2.check_gif_url_health, url)
        await record_gif_health_check(gif["id"], status)
        await asyncio.sleep(HEALTH_CHECK_DELAY)
    return len(gifs)


# Un objeto recién subido cuya fila todavía no se guardó (o cuyo guardado
# falló a mitad) no debe contar como huérfano en el mismo momento: se le da un
# día de gracia antes de considerarlo basura.
ORPHAN_GRACE_HOURS = 24
# Techo por corrida: si algo hace que el conjunto de keys vivas salga vacío o
# incompleto, esto acota el daño a 500 objetos en vez de al bucket entero.
ORPHAN_MAX_DELETES = 500


async def run_gif_orphan_sweep() -> int:
    """Borra objetos de R2 bajo el prefijo de GIFs que ya no referencia nadie.

    Red de seguridad contra fugas: si algún camino de borrado se olvida de
    soltar su referencia, el objeto queda ocupando espacio para siempre y en
    silencio. Esto lo encuentra sin depender de que ese camino esté bien.

    Se limita al prefijo `gifs/` (r2.GIF_KEY_PREFIX), que es exclusivo de los
    GIFs content-addressed. En el mismo bucket viven las imágenes del pool de
    memes y las subidas del editor de embeds, con keys `{guild_id}/...`; las de
    embeds ni siquiera están en una columna `url` (van dentro del JSON de la
    plantilla), así que no hay forma barata de cruzarlas. El prefijo evita todo
    ese problema: nada fuera de `gifs/` se mira siquiera.
    """
    if not r2.available():
        return 0
    live = await get_live_gif_keys()
    objects = await asyncio.to_thread(r2.list_keys_sync, r2.GIF_KEY_PREFIX)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ORPHAN_GRACE_HOURS)

    deleted = 0
    for key, size, modified in objects:
        if key in live:
            continue
        if modified and modified > cutoff:
            continue
        if deleted >= ORPHAN_MAX_DELETES:
            log.warning(
                "Barrido de huérfanos: se alcanzó el tope de %d borrados, "
                "el resto queda para la próxima corrida",
                ORPHAN_MAX_DELETES,
            )
            break
        log.warning(
            "Barrido de huérfanos: borrando %s (%s bytes, modificado %s)",
            key,
            size,
            modified,
        )
        await r2.delete_key(key)
        deleted += 1

    log.info(
        "Barrido de huérfanos: %d objetos en %s, %d vivos, %d borrados",
        len(objects),
        r2.GIF_KEY_PREFIX,
        len(live),
        deleted,
    )
    return deleted


class Gifs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.resolve_gifs_task.start()
        self.gif_health_check_task.start()
        self.gif_orphan_sweep_task.start()

    async def cog_unload(self) -> None:
        self.resolve_gifs_task.cancel()
        self.gif_health_check_task.cancel()
        self.gif_orphan_sweep_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if (message.content or "").strip().startswith("!"):
            return
        from cogs.memes import is_meme_trigger

        if is_meme_trigger(self.bot, message):
            return
        if await is_channel_ignored(message.guild.id, message.channel.id):
            return
        await save_gif_candidates(message.guild.id, message)

    @tasks.loop(seconds=90)
    async def resolve_gifs_task(self):
        try:
            gifs = await get_unresolved_gifs(limit=25)
            if not gifs:
                return
            for gif in gifs:
                resolved = await resolve_media_url(gif["url"])
                if resolved is not None:
                    await update_gif_media_url(gif["id"], resolved)
                await asyncio.sleep(1.5)
        except Exception:
            log.exception("Error en resolve_gifs_task")

    @resolve_gifs_task.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def gif_health_check_task(self):
        try:
            checked = await run_gif_health_check()
            if checked:
                log.info("Ciclo de salud de GIFs: %s revisados", checked)
        except Exception:
            log.exception("Error en gif_health_check_task")

    @gif_health_check_task.before_loop
    async def _wait_ready_health(self):
        await self.bot.wait_until_ready()

    # Semanal: es una red de seguridad, no un mecanismo del que dependa nada.
    # Listar el bucket entero todos los días sería pagar de más por lo mismo.
    @tasks.loop(hours=24 * 7)
    async def gif_orphan_sweep_task(self):
        try:
            await run_gif_orphan_sweep()
        except Exception:
            log.exception("Error en gif_orphan_sweep_task")

    @gif_orphan_sweep_task.before_loop
    async def _wait_ready_sweep(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="gif_add", description="Agrega un GIF a la colección del servidor."
    )
    @app_commands.describe(
        url="URL del GIF (tenor.com, giphy.com o cdn.discordapp.com)"
    )
    async def gif_add(self, interaction: discord.Interaction, url: str):
        from cogs.premium import is_premium_guild, premium_required_message

        if not interaction.guild:
            await interaction.response.send_message(
                "Solo en servidores.", ephemeral=True
            )
            return
        if not has_admin_permission(interaction):
            await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )
            return
        if not is_premium_guild(interaction.guild_id):
            await interaction.response.send_message(
                premium_required_message(), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        url = url.strip()
        host = _gif_host(url)
        content_hash, size_bytes, phash = None, 0, None
        if host == "cdn.discordapp.com":
            up = await asyncio.to_thread(r2.upload_gif_sync, url)
            if up and up.url == r2.GIF_TOO_LARGE:
                await interaction.followup.send(
                    "❌ El GIF supera el límite de tamaño permitido."
                )
                return
            if not up:
                await interaction.followup.send(
                    "❌ No se pudo subir el GIF a R2. Comprueba que la URL sea accesible."
                )
                return
            final_url, content_hash, size_bytes, phash = up
        elif _is_gif_site(host):
            final_url = url
        else:
            await interaction.followup.send(
                "❌ URL no reconocida. Solo se aceptan GIFs de tenor.com, giphy.com o cdn.discordapp.com."
            )
            return

        inserted, _ = await save_gif_url(
            interaction.guild.id, final_url, content_hash, size_bytes, phash
        )
        total = await count_gif_urls(interaction.guild.id)
        if inserted:
            await interaction.followup.send(
                f"✅ GIF guardado. La colección del servidor tiene {total} GIFs en total."
            )
        else:
            await interaction.followup.send(
                f"ℹ️ Ese GIF ya estaba en la colección. Total: {total} GIFs."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gifs(bot))
