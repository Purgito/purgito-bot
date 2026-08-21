"""Captura y gestión de GIFs: detección en mensajes, subida a R2, galería web."""

import asyncio
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
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
    is_user_excluded_from_learning,
    record_gif_health_check,
    save_gif_url,
    update_gif_media_url,
    update_gif_storage,
)
from i18n import guild_locale, t
from tasks import get_task_manager
from utils import has_admin_permission

log = logging.getLogger(__name__)

GIF_RE = re.compile(
    r"https?://\S*(tenor\.com|giphy\.com|cdn\.discordapp\.com/attachments/\S*\.gif)\S*",
    re.IGNORECASE,
)

ALLOWED_GIF_HOSTS = (
    "tenor.com",
    "giphy.com",
    "cdn.discordapp.com",
    "media.discordapp.net",
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


def _is_allowed_gif_host(host: str) -> bool:
    if not host:
        return False
    h = host.lower().strip()
    if h in ALLOWED_GIF_HOSTS or h.endswith(tuple(f".{x}" for x in ALLOWED_GIF_HOSTS)):
        return True
    pub = r2.public_url()
    if pub:
        pub_host = (urlparse(pub).hostname or "").lower()
        if pub_host and (h == pub_host or h.endswith(f".{pub_host}")):
            return True
    return False


def is_valid_gif_bytes(data: bytes) -> bool:
    """Valida que los bytes comiencen con la firma de un GIF real (GIF87a o GIF89a)."""
    return bool(data and len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"))


class _LRUGifCache:
    def __init__(self, capacity: int = 128):
        self._capacity = capacity
        self._cache: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        if key in self._cache:
            val = self._cache.pop(key)
            self._cache[key] = val
            return val
        return None

    def set(self, key: str, val: bytes) -> None:
        if key in self._cache:
            self._cache.pop(key)
        elif len(self._cache) >= self._capacity:
            first_key = next(iter(self._cache))
            self._cache.pop(first_key)
        self._cache[key] = val

    def clear(self) -> None:
        self._cache.clear()


_GIF_CACHE = _LRUGifCache(128)


# r2.upload_gif_sync es caro (descarga hasta MAX_GIF_DOWNLOAD_BYTES, gifsicle,
# sha256, phash) y corre en el thread pool default de asyncio -- compartido
# con la generación de Markov, memes y todo lo demás del proceso. Sin tope,
# cualquier miembro (no hace falta ser admin: on_message dispara esto para
# TODO mensaje) podía postear GIFs de cdn.discordapp.com en ráfaga y saturar
# ese pool para el resto del bot -- mismo patrón de "un guild degrada a
# todos" que ya se corrigió en /auth/callback y /webhooks/polar.
#
# Un semáforo (no un rate limit que descarte) a propósito: nunca hay que
# perder un GIF legítimo por llegar en una ráfaga -- ver la investigación del
# auto-borrado agresivo. Esto solo acota cuántas subidas corren en paralelo;
# el resto espera su turno, no se pierde.
_UPLOAD_CONCURRENCY = asyncio.Semaphore(2)


async def _upload_gif_throttled(url: str) -> "r2.GifUpload | None":
    async with _UPLOAD_CONCURRENCY:
        return await asyncio.to_thread(r2.upload_gif_sync, url)


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
                    up = await _upload_gif_throttled(url)
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
                    up = await _upload_gif_throttled(url)
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


def _valid_media_url(resolved) -> bool:
    """Un media_url resuelto solo se acepta si es un string válido,
    pertenece a un host de GIFs conocido y no apunta a una extensión estática incompatible."""
    if not (isinstance(resolved, str) and resolved.startswith(("http://", "https://"))):
        return False
    host = _gif_host(resolved)
    if not _is_gif_site(host):
        return False
    lower = resolved.lower().split("?")[0]
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return False
    return True


class _OgImageParser(HTMLParser):
    """Busca el primer <meta property="og:image" content="..."> (o twitter:image / contentUrl)
    y extrae la URL directa del .gif animado -- mismo mecanismo que usa Discord
    para armar el preview cuando alguien pega un link de Tenor a secas en un canal."""

    def __init__(self):
        super().__init__()
        self.og_image: str | None = None
        self._fallback_image: str | None = None

    def handle_starttag(self, tag, attrs):
        if self.og_image or tag != "meta":
            return
        attr_dict = dict(attrs)
        prop = attr_dict.get("property")
        name = attr_dict.get("name")
        itemprop = attr_dict.get("itemprop")
        content = attr_dict.get("content")

        if not content:
            return

        if prop == "og:image":
            self.og_image = content
        elif (
            name == "twitter:image" or itemprop == "contentUrl"
        ) and not self._fallback_image:
            self._fallback_image = content

    def get_image(self) -> str | None:
        return self.og_image or self._fallback_image


async def resolve_tenor_gif_url(url: str) -> str | None:
    """Resuelve una página tenor.com/view/... a la URL directa de su .gif animado."""
    import requests

    host = _gif_host(url)
    if host != "tenor.com" and not host.endswith(".tenor.com"):
        return None
    try:
        resp = await asyncio.to_thread(
            r2.fetch_public_url, requests.get, url, timeout=8
        )
        html_text = resp.text
    except Exception:
        return None
    parser = _OgImageParser()
    try:
        parser.feed(html_text)
    except Exception:
        return None
    resolved = parser.get_image()
    if (
        not resolved
        or not _valid_media_url(resolved)
        or not resolved.lower().split("?")[0].endswith(".gif")
    ):
        return None
    return resolved


async def resolve_media_url(url: str) -> str | None:
    import requests

    try:
        host = _gif_host(url)
        if host == "cdn.discordapp.com" or (
            r2.public_url() and url.startswith(r2.public_url())
        ):
            return url
        # Si la URL ya es directa a un GIF de un host válido, se devuelve directamente
        if url.lower().split("?")[0].endswith(".gif") and _valid_media_url(url):
            return url
        if host == "tenor.com" or host.endswith(".tenor.com"):
            # Tenor: resolver al .gif animado real leyendo og:image de la página
            resolved = await resolve_tenor_gif_url(url)
        elif host == "giphy.com" or host.endswith(".giphy.com"):
            resp = await asyncio.to_thread(
                requests.get,
                f"https://giphy.com/services/oembed?url={quote(url, safe='')}&format=json",
                timeout=8,
            )
            # A diferencia de tenor, el oEmbed de giphy sí trae el .gif real bajo "url"
            resolved = resp.json()["url"]
        else:
            return None
    except Exception:
        return None
    if not _valid_media_url(resolved):
        if resolved:
            log.warning(
                "Media URL resuelta inválida o fuera de los hosts de GIFs: %r", resolved
            )
        return None
    return resolved


async def fetch_gif_bytes(url: str, timeout: float = 8.0) -> bytes | None:
    """Descarga bytes de un GIF desde una URL remota de forma segura contra SSRF.

    - Valida el host contra los proveedores de GIFs autorizados.
    - Si es una página (ej. tenor.com/view/...), la resuelve a la URL directa del .gif.
    - Verifica el límite de tamaño MAX_GIF_DOWNLOAD_BYTES.
    - Valida magic bytes GIF87a/GIF89a.
    - Cachea en memoria los bytes descargados.
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()

    cached = _GIF_CACHE.get(url)
    if cached:
        return cached

    host = _gif_host(url)
    if not _is_allowed_gif_host(host):
        log.warning("Descarga de GIF rechazada por host no permitido: %s", url)
        return None

    target_url = url
    # Si es página de Tenor o Giphy sin .gif directo, resolver primero
    if not target_url.lower().split("?")[0].endswith(".gif"):
        resolved = await resolve_media_url(target_url)
        if resolved:
            target_url = resolved
            cached = _GIF_CACHE.get(target_url)
            if cached:
                _GIF_CACHE.set(url, cached)
                return cached
        else:
            log.debug("No se pudo resolver URL de página a .gif directo: %s", url)
            return None

    target_host = _gif_host(target_url)
    if not _is_allowed_gif_host(target_host):
        log.warning(
            "URL de GIF resuelta rechazada por host no permitido: %s", target_url
        )
        return None

    max_bytes = r2._env_int("MAX_GIF_DOWNLOAD_BYTES", 8 * 1024 * 1024)

    def _download():
        import requests

        headers = {"User-Agent": "Mozilla/5.0 (compatible; bot)"}
        try:
            resp = r2.fetch_public_url(
                requests.get,
                target_url,
                headers=headers,
                timeout=timeout,
                stream=True,
            )
            if resp.status_code != 200:
                log.debug("HTTP %s al descargar GIF: %s", resp.status_code, target_url)
                resp.close()
                return None
            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > max_bytes:
                resp.close()
                return None
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=262144):
                total += len(chunk)
                if total > max_bytes:
                    resp.close()
                    return None
                chunks.append(chunk)
            resp.close()
            data = b"".join(chunks)
            if not is_valid_gif_bytes(data):
                log.debug(
                    "Bytes descargados no corresponden a un GIF válido: %s", target_url
                )
                return None
            return data
        except Exception:
            log.debug("Fallo descargando GIF de %s", target_url, exc_info=True)
            return None

    data = await asyncio.to_thread(_download)
    if data:
        _GIF_CACHE.set(url, data)
        if target_url != url:
            _GIF_CACHE.set(target_url, data)
    return data


async def fetch_gif_from_storage(content_hash: str) -> bytes | None:
    """Obtiene los bytes del GIF desde R2 / Cloudflare."""
    if not content_hash or not r2.available():
        return None
    cached = _GIF_CACHE.get(content_hash)
    if cached:
        return cached
    key = r2.gif_key(content_hash)
    data = await asyncio.to_thread(r2.get_object_bytes_sync, key)
    if data and is_valid_gif_bytes(data):
        _GIF_CACHE.set(content_hash, data)
        return data
    pub = r2.public_url()
    if pub:
        url = f"{pub.rstrip('/')}/{key}"
        data = await fetch_gif_bytes(url)
        if data:
            _GIF_CACHE.set(content_hash, data)
            return data
    return None


async def _promote_gif_to_r2(gif_id: int, guild_id: int, data: bytes) -> None:
    """Sube un GIF descargado a R2 en segundo plano y actualiza la fila en corpus_gifs."""
    if not r2.available():
        return
    try:
        up = await asyncio.to_thread(r2.upload_gif_bytes_sync, data)
        if up and up.url and up.content_hash:
            import db

            await update_gif_storage(gif_id, up.url, up.content_hash)
            db_conn = await db.get_db()
            async with db._db_lock:
                await db._retain_gif_object(
                    db_conn,
                    up.content_hash,
                    r2.gif_key(up.content_hash),
                    up.size_bytes,
                    up.phash,
                )
                await db_conn.commit()
    except Exception:
        log.debug("Error promoviendo GIF id=%s a R2", gif_id, exc_info=True)


async def get_live_gif(
    guild_id: int, attempts: int = 3, timeout: float = 6.0
) -> discord.File | None:
    """Elige un GIF aleatorio del corpus del servidor, obtiene sus bytes reales
    (desde R2, cache o descargando de proveedores autorizados), valida los magic
    bytes GIF87a/GIF89a, y devuelve un discord.File listo para ser enviado como
    attachment.

    Si un candidato falla:
    - 404/410 o contenido corrupto/no-GIF: suma al streak 'dead' (se auto-borra a los 3 seguidos).
    - Timeout puntual o caída de red: registra 'unreachable' sin acumular strikes.
    - Continúa con el siguiente candidato disponible hasta agotar `attempts`.
    """
    candidates = await get_random_gif_candidates(guild_id, limit=attempts)
    for gif in candidates:
        gif_id = gif["id"]
        content_hash = gif.get("content_hash")
        data: bytes | None = None

        # 1. Preferir storage R2 / cache de contenido si ya tiene content_hash
        if content_hash:
            data = await fetch_gif_from_storage(content_hash)

        # 2. Si no tiene hash o falló R2, descargar desde media_url o url
        if not data:
            media_url = gif.get("media_url")
            if media_url and not media_url.lower().split("?")[0].endswith(
                (".png", ".jpg", ".jpeg", ".webp")
            ):
                target_url = media_url
            else:
                target_url = gif["url"]

            data = await fetch_gif_bytes(target_url, timeout=timeout)

        if data and is_valid_gif_bytes(data):
            await record_gif_health_check(gif_id, "ok")
            if r2.available() and not content_hash:
                asyncio.create_task(_promote_gif_to_r2(gif_id, guild_id, data))
            return discord.File(io.BytesIO(data), filename="purgito.gif")

        # Si no se obtuvieron bytes válidos, registrar el estado de salud tri-estado
        check_url = gif.get("media_url") or gif["url"]
        status = await asyncio.to_thread(r2.check_gif_url_health, check_url, timeout)
        await record_gif_health_check(gif_id, status)

    return None


# Espaciado entre chequeos del ciclo de salud, para no golpear el mismo host
# en ráfaga -- ver check_gif_url_health/record_gif_health_check en db.py/r2.py.
HEALTH_CHECK_DELAY = 1.5
HEALTH_CHECK_BATCH = 500

# Cada cuántos GIFs se reporta avance a la Task (Fase 2 de TaskManager): no
# vale la pena un update_progress por cada GIF individual si son cientos.
_HEALTH_CHECK_PROGRESS_INTERVAL = 20


async def run_gif_health_check(
    guild_id: int | None = None,
    limit: int = HEALTH_CHECK_BATCH,
    task_id: str | None = None,
) -> int:
    """Revisa hasta `limit` GIFs (de un guild puntual, o de todos si es
    None -- usado por el ciclo diario) contra el propio host y guarda el
    resultado. Usado tanto por el loop periódico como por el botón manual
    "Verificar GIFs" del panel.

    task_id es opcional: el ciclo diario (guild_id=None) lo llama sin task_id
    y no reporta progreso a ningún lado, igual que antes de la Fase 2 de
    TaskManager. El endpoint manual del panel sí pasa un task_id."""
    gifs = await get_gifs_for_health_check(guild_id, limit=limit)
    total = len(gifs)
    task_manager = get_task_manager() if task_id else None
    for i, gif in enumerate(gifs, start=1):
        url = gif["media_url"] or gif["url"]
        status = await asyncio.to_thread(r2.check_gif_url_health, url)
        await record_gif_health_check(gif["id"], status)
        if task_manager is not None and (
            i % _HEALTH_CHECK_PROGRESS_INTERVAL == 0 or i == total
        ):
            await task_manager.update_progress(
                task_id, current=i, total=total, message="Verificando GIFs..."
            )
        await asyncio.sleep(HEALTH_CHECK_DELAY)
    return total


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
        if await is_user_excluded_from_learning(message.guild.id, message.author.id):
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

        locale = await guild_locale(interaction.guild.id if interaction.guild else None)

        if not interaction.guild:
            await interaction.response.send_message(
                t("general.guild_only", locale), ephemeral=True
            )
            return
        if not has_admin_permission(interaction):
            await interaction.response.send_message(
                t("general.error.no_permission", locale), ephemeral=True
            )
            return
        if not is_premium_guild(interaction.guild_id):
            await interaction.response.send_message(
                premium_required_message(locale), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        url = url.strip()
        host = _gif_host(url)
        content_hash, size_bytes, phash = None, 0, None
        if host == "cdn.discordapp.com":
            up = await _upload_gif_throttled(url)
            if up and up.url == r2.GIF_TOO_LARGE:
                await interaction.followup.send(t("gifs.add.too_large", locale))
                return
            if not up:
                await interaction.followup.send(t("gifs.add.upload_failed", locale))
                return
            final_url, content_hash, size_bytes, phash = up
        elif _is_gif_site(host):
            final_url = url
        else:
            await interaction.followup.send(t("gifs.add.unrecognized_url", locale))
            return

        inserted, _ = await save_gif_url(
            interaction.guild.id, final_url, content_hash, size_bytes, phash
        )
        total = await count_gif_urls(interaction.guild.id)
        if inserted:
            await interaction.followup.send(t("gifs.add.saved", locale, total=total))
        else:
            await interaction.followup.send(
                t("gifs.add.duplicate", locale, total=total)
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gifs(bot))
