"""Resuelve contenido multimedia (video o imagen) disponible en el CONTEXTO
de un mensaje de Discord: adjuntos, el mensaje al que se responde, y los
embeds de cualquiera de los dos -- incluyendo el video/imagen que Discord ya
resolvió de un link externo y sirve a través de su propio proxy de media.

Deliberadamente neutral respecto a "purgito dl" vs "purgito gif": esto es
puro Discord (qué hay ya disponible/resuelto en el mensaje), no scraping de
ninguna plataforma en particular. Lo comparten:

- cogs/download.py ("purgito dl"): usa resolve_reference/reply_target_url
  para encontrar el LINK del mensaje respondido antes de pasárselo a
  yt-dlp -- yt-dlp y el allowlist de plataformas (_ALLOWED_HOSTS) son cosas
  de ese módulo, no de este.
- cogs/imagefx.py ("purgito gif"): arma su fuente de video/imagen a partir
  de esto (adjunto -> embed -> fetch_media_bytes de un link directo) sin
  pasar NUNCA por yt-dlp ni por el allowlist de plataformas de "purgito dl"
  -- ver el docstring de ese cog.
"""

import asyncio
import logging
import re
from urllib.parse import urlparse

import discord
from discord.ext import commands

import r2

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")


async def resolve_reference(ctx: commands.Context) -> discord.Message | None:
    """Resuelve el mensaje al que responde ctx, si lo hay. `resolved` ya
    viene poblado en la mayoría de los casos (Discord lo manda junto con el
    mensaje de reply), pero si no -- mensaje viejo fuera de caché -- se busca
    con un fetch aparte."""
    reference = ctx.message.reference
    if reference is None:
        return None
    resolved = reference.resolved
    if isinstance(resolved, discord.DeletedReferencedMessage):
        return None
    if resolved is None:
        if reference.message_id is None:
            return None
        try:
            resolved = await ctx.channel.fetch_message(reference.message_id)
        except discord.HTTPException:
            return None
    return resolved


async def reply_target_url(ctx: commands.Context) -> str | None:
    """Si el comando se invocó sin link propio pero respondiendo a un
    mensaje, busca un link ahí -- así alcanza con responder a un mensaje que
    ya tiene el video/imagen, sin tener que repetir la URL.

    Además del texto plano, revisa los embeds del mensaje: bots que postean
    un preview suelen mandarlo como embed puro, sin el link en el texto --
    Embed.url es la página de origen en ese caso."""
    resolved = await resolve_reference(ctx)
    if resolved is None:
        return None
    match = URL_RE.search(resolved.content or "")
    if match:
        return match.group(0)
    for embed in resolved.embeds:
        if embed.url:
            return embed.url
    return None


def embed_video_url(message: discord.Message) -> str | None:
    """Busca una URL de video directa en los embeds de un mensaje. A
    diferencia de Embed.url (la página de origen, lo que usa
    reply_target_url), esto es el archivo reproducible en sí: bots que
    postean su propio resultado (ej. NotSoBot) o un GIF de Tenor/Giphy
    (embeds tipo "gifv") lo exponen en Embed.video, no como adjunto ni
    como link en el texto. getattr en vez de embed.video directo: un
    discord.Embed real siempre tiene el atributo (un EmbedProxy vacío si no
    hay video), pero no vale la pena exigirlo de cualquier objeto que
    llegue acá.

    proxy_url antes que url: cuando el video vive en un host de terceros
    (ej. el CDN propio de otro bot, no Discord), Discord igual lo sirve al
    cliente a través de su propio proxy de media (media.discordapp.net) --
    por eso "se ve perfecto" en Discord aunque el host original no esté en
    _DIRECT_MEDIA_HOSTS. video.url en ese caso sigue siendo el host de
    terceros (lo que is_direct_media_host va a rechazar más abajo); url
    queda como fallback para cuando el video YA es de Discord (proxy_url
    puede venir vacío ahí) y para objetos de prueba que no definen proxy_url."""
    for embed in message.embeds:
        video = getattr(embed, "video", None)
        if not video:
            continue
        proxy_url = getattr(video, "proxy_url", None)
        if proxy_url:
            return proxy_url
        if video.url:
            return video.url
    return None


def embed_image_url(message: discord.Message) -> str | None:
    """Igual que embed_video_url pero para una imagen estática: Embed.image
    en vez de Embed.video -- mismo caso (otro bot postea su resultado
    directo en el embed), pero cuando lo que posteó es una imagen, no un
    video.

    Mismo criterio de proxy_url que embed_video_url (ver ese docstring): si
    la imagen vive en el host de un tercero, Discord la sirve al cliente a
    través de su propio proxy de media, y ese host es el que
    is_direct_media_host reconoce -- el .url original del tercero no."""
    for embed in message.embeds:
        image = getattr(embed, "image", None)
        if not image:
            continue
        proxy_url = getattr(image, "proxy_url", None)
        if proxy_url:
            return proxy_url
        if image.url:
            return image.url
    return None


# Hosts desde los que se puede bajar un video o imagen EMBEBIDOS (Embed.video
# / Embed.image) como archivo directo, sin pasar por ningún scraper. Dos
# casos distintos conviven acá: cdn.discordapp.com es donde vive de verdad un
# adjunto que otro bot ya subió a Discord (ej. un bot reposteando su propio
# resultado como adjunto); media.discordapp.net es el proxy de media de
# Discord, que sirve CUALQUIER embed con video o imagen sin importar dónde
# esté alojado el original -- así es como el cliente de Discord lo muestra,
# y por eso embed_video_url/embed_image_url prefieren el proxy_url del embed
# sobre su url.
_DIRECT_MEDIA_HOSTS = ("cdn.discordapp.com", "media.discordapp.net")


def is_direct_media_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return host in _DIRECT_MEDIA_HOSTS or host.endswith(
        tuple(f".{h}" for h in _DIRECT_MEDIA_HOSTS)
    )


def _download_bytes(url: str, max_bytes: int, timeout: float) -> bytes | None:
    """Bloqueante -- correr en un thread aparte. GET en streaming protegido
    contra SSRF vía r2.fetch_public_url (mismo mecanismo que fetch_gif_bytes
    en cogs/gifs.py), cortando apenas se supera max_bytes. None si falla,
    el status no es 200, o supera max_bytes -- el caller solo necesita saber
    si hay bytes o no, no distingue el motivo."""
    import requests

    try:
        resp = r2.fetch_public_url(
            requests.get,
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; bot)"},
            timeout=timeout,
            stream=True,
        )
        if resp.status_code != 200:
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
        return b"".join(chunks)
    except Exception:
        log.debug("Fallo descargando media de %s", url, exc_info=True)
        return None


async def fetch_direct_media_bytes(
    url: str, max_bytes: int, timeout: float = 15.0
) -> bytes | None:
    """Descarga bytes de un archivo directo (video o imagen, no una página)
    desde un host de confianza (is_direct_media_host). Usado para bajar lo
    que un EMBED de Discord ya resolvió (embed_video_url/embed_image_url) --
    ahí el host viene acotado a Discord mismo o a su proxy de media, así que
    tiene sentido exigirlo antes de pegarle. None si el host no es de
    confianza."""
    if not is_direct_media_host(url):
        return None
    return await asyncio.to_thread(_download_bytes, url, max_bytes, timeout)


async def fetch_media_bytes(
    url: str, max_bytes: int, timeout: float = 15.0
) -> bytes | None:
    """Igual que fetch_direct_media_bytes pero SIN restringir el host: para
    cuando el link no vino de un embed que Discord ya resolvió, sino que lo
    tipeó directamente quien usa el comando (ej. "purgito gif
    https://cdn-de-cualquier-lado.com/clip.mp4"). No hay forma de acotar de
    antemano a qué host puede apuntar un link así -- la única defensa es
    SSRF a nivel de IP (r2.fetch_public_url, el mismo filtro que ya usa
    check_gif_url_health en r2.py para "cualquier URL de imagen") más el
    tope de tamaño. El contenido en sí NO se valida acá -- eso es trabajo
    del caller (ej. is_valid_image / video_filters.convert_video_to_gif en
    cogs/imagefx.py), igual que con cualquier otra fuente de media."""
    return await asyncio.to_thread(_download_bytes, url, max_bytes, timeout)
