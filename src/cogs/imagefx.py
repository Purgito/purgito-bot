"""Filtros de imagen tipo NotSoBot (Fases 1, 2 y 4).

"!gif" resuelve sus fuentes en varios pasos, de más barato a más caro:
adjuntos, medios de embeds O de Components V2 (ver _component_media_urls --
un mensaje tiene una cosa o la otra, nunca las dos, así que hay que mirar
las dos formas) y URLs directas (todo con un GET simple, desde el mensaje
actual o el respondido) y, solo si nada de eso encontró nada descargable,
un link a Instagram/TikTok/Twitter-X/Facebook resuelto con el mismo
extractor que usa "!dl" (yt-dlp, cogs/download.py).

Ninguno de estos pasos es opcional -- cada uno cubre un caso real que ya
rompió en producción cuando faltaba:

- Components V2: muchos bots (y Purgito mismo, ver layout_v2.py) postean su
  resultado con la UI nueva de Discord en vez de un embed clásico -- un
  mensaje así tiene message.embeds vacío SIEMPRE (son excluyentes), así que
  sin _component_media_urls ninguno de los pasos de embed encuentra nada,
  aunque el video esté a la vista.
- yt-dlp: para Instagram/TikTok/Twitter-X/Facebook, el CDN de origen no
  sirve el archivo con un GET anónimo (pide headers o sesión que un bot no
  tiene) -- un intento anterior de arreglar esto sacó por completo la
  reutilización de !dl en vez de solucionar el bug real, y los pasos de GET
  directo (_embed_video_urls, _fetch_media_bytes) siguen sin poder nada
  contra esos cuatro sitios.
- Reenvíos (botón "Reenviar mensaje" de Discord): el contenido de un mensaje
  reenviado no vive en message.attachments/.embeds/.content -- vacíos por
  default en ese caso -- sino en message.message_snapshots (uno o más
  MessageSnapshot con esos mismos campos). _source_messages ya expande esto
  para el mensaje propio y el respondido, así que ningún otro helper
  necesita distinguir un reenvío de un mensaje normal -- pero si algo deja
  de pasar por _source_messages y lee message.attachments/.embeds directo,
  "!gay" (o cualquier otro filtro) respondiendo a un reenvío de un GIF (ej.
  el mensaje de otro bot reenviándolo) vuelve a fallar en silencio, como en
  el bug reportado.

Si volvés a tocar esto: no saques ninguno de los tres, los primeros dos ya
se sacaron una vez por error y reintrodujeron el bug reportado ("!gif" pide
un video aunque el mensaje tenga uno a la vista).
"""

import asyncio
import io
import logging
import os
import re
import shutil
import time
from typing import Callable
from urllib.parse import urlparse

import discord
import requests
from discord import app_commands
from discord.ext import commands

import image_filters
import r2
import video_filters
from cogs import download as download_mod
from cogs.gifs import is_valid_gif_bytes
from config import IMAGEFX_MAX_BYTES, env_int
from i18n import guild_locale, t
from meme_generator import is_valid_image
from utils import LRUDict

log = logging.getLogger(__name__)

# Elemento de _source_messages(): un discord.Message real o, cuando ese
# mensaje es un reenvío (botón "Reenviar mensaje" de Discord), uno de sus
# MessageSnapshot. Discord NO pone el contenido reenviado en
# message.attachments/.embeds/.content -- eso queda vacío -- sino en
# message.message_snapshots. MessageSnapshot expone esos mismos cuatro
# atributos (.attachments/.embeds/.content/.components), así que todo lo que
# ya los lee con getattr(...) funciona igual sin distinguir uno de otro.
MessageSource = discord.Message | discord.MessageSnapshot

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_GIF_EXTS = {".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm"}
_MEDIA_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Tope del video FUENTE de "!gif", antes de convertirlo -- deliberadamente
# más chico que MAX_DL_VIDEO_BYTES (cogs/download.py): un gif es un clip
# corto, no tiene sentido aceptar un archivo enorme solo para truncarlo a
# GIF_MAX_DURATION_SECONDS después.
MAX_GIF_SOURCE_VIDEO_BYTES = env_int("MAX_GIF_SOURCE_VIDEO_BYTES", 25 * 1024 * 1024)
GIF_MAX_DURATION_SECONDS = 8

# Cooldown compartido por TODOS los filtros de imagen/GIF de este cog, no uno
# por comando: son ~30 comandos de costo parecido, así que un cooldown por
# nombre de comando (lo que da @commands.cooldown por default) se evade
# rotando entre ellos -- mismo problema que ya resolvió _check_meme_cooldown
# en cogs/memes.py para /momo vs. el trigger de texto.
_FX_COOLDOWN_SECONDS = 6
_fx_cooldowns: LRUDict = LRUDict(1024)

# "!gif" tiene su propio cooldown, más largo: a diferencia del resto (Pillow
# puro, milisegundos), acá hay un proceso de ffmpeg de verdad -- mismo orden
# de costo que "!dl" (yt-dlp), por eso el mismo valor que _DL_COOLDOWN_SECONDS.
_GIF_CONVERT_COOLDOWN_SECONDS = 20
_gif_convert_cooldowns: LRUDict = LRUDict(256)


class SourceTooLarge(Exception):
    """El adjunto/reply encontrado (imagen, GIF o video fuente de "!gif")
    supera el tope de tamaño correspondiente."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


class SensitiveContentBlocked(Exception):
    """El link de Instagram/TikTok/Twitter-X/Facebook resuelto vía yt-dlp
    viene marcado +18 (info.age_limit) y el canal no es NSFW -- mismo gate
    que "!dl" (cogs/download.py:dl), reutilizado acá porque el video sale
    del mismo extractor."""


def _clean_url(url: str) -> str:
    """Limpia caracteres de cierre de markdown o puntuación residual de una URL."""
    url = url.strip()
    for start_char, end_char in (
        ("<", ">"),
        ("(", ")"),
        ("[", "]"),
        ('"', '"'),
        ("'", "'"),
    ):
        if url.startswith(start_char) and url.endswith(end_char):
            url = url[1:-1].strip()
    while url and url[-1] in (")", "]", ">", '"', "'", ",", ";", "."):
        url = url[:-1]
    return url


async def _resolve_reference(ctx: commands.Context) -> discord.Message | None:
    """Obtiene el mensaje respondido sin depender del handler de !dl.

    Si Discord mandó un snapshot parcial en `referenced_message` o el mensaje
    estaba en caché antes de que Discord generase los embeds (unfurl
    asíncrono), intenta un `fetch_message` para obtener la versión completa con
    embeds y adjuntos. message_snapshots (plural, distinto del "snapshot
    parcial" de arriba -- ver MessageSource) también cuenta como "ya está
    completo": un mensaje que reenvía algo no tiene attachments/embeds
    propios ni falta que tenerlos para estar completo.
    """
    reference = getattr(ctx.message, "reference", None)
    if reference is None:
        return None
    resolved = getattr(reference, "resolved", None)
    if isinstance(resolved, discord.DeletedReferencedMessage):
        return None

    message_id = getattr(reference, "message_id", None)
    needs_fetch = resolved is None or (
        not getattr(resolved, "attachments", None)
        and not getattr(resolved, "embeds", None)
        and not getattr(resolved, "message_snapshots", None)
    )
    if needs_fetch and message_id is not None:
        channel = ctx.channel
        reference_channel_id = getattr(reference, "channel_id", None)
        bot = getattr(ctx, "bot", None)
        if (
            reference_channel_id
            and reference_channel_id != getattr(channel, "id", None)
            and bot is not None
        ):
            channel = getattr(bot, "get_channel", lambda _: None)(reference_channel_id)
            if channel is None and hasattr(bot, "fetch_channel"):
                try:
                    channel = await bot.fetch_channel(reference_channel_id)
                except discord.HTTPException:
                    channel = None
        if channel is not None and hasattr(channel, "fetch_message"):
            try:
                fetched = await channel.fetch_message(message_id)
                if fetched is not None:
                    resolved = fetched
            except discord.HTTPException:
                pass
    return resolved


async def _source_messages(ctx: commands.Context) -> list[MessageSource]:
    """Mensaje actual primero (y, si es un reenvío, sus MessageSnapshot justo
    después) y, si existe, el mensaje al que se responde (mismo trato: él
    mismo y después sus propios MessageSnapshot si también es un reenvío).

    Un MessageSnapshot no es un discord.Message real -- ver MessageSource --
    pero expone .attachments/.embeds/.content/.components, así que agregarlo
    acá alcanza para que _find_attachment y los demás helpers de este módulo
    (todos leen esos campos con getattr) encuentren el contenido de un
    reenvío sin ningún cambio propio."""
    messages: list[MessageSource] = []
    for message in (ctx.message, await _resolve_reference(ctx)):
        if message is None:
            continue
        messages.append(message)
        messages.extend(getattr(message, "message_snapshots", None) or ())
    return messages


def _embed_media_urls(message: MessageSource, attributes: tuple[str, ...]):
    """Entrega todas las URLs de medio que Discord expone en sus embeds.

    Los embeds no tienen una forma única: según el proveedor y el tipo,
    discord.py puede poner el archivo en ``url`` o en ``proxy_url``. Se
    recorren ambos y todos los embeds en vez de descartar el mensaje tras el
    primer recurso que falle.
    """
    seen: set[str] = set()
    for embed in getattr(message, "embeds", ()):
        for attribute in attributes:
            media = getattr(embed, attribute, None)
            for name in ("url", "proxy_url"):
                url = getattr(media, name, None)
                if url:
                    url = _clean_url(url)
                    if url and url not in seen:
                        seen.add(url)
                        yield url


def _embed_url_texts_single(embed: discord.Embed):
    def walk(key, value):
        # Evitar imágenes/iconos que nunca son el video
        if key in ("thumbnail", "author", "footer", "icon"):
            return
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for k, child in value.items():
                yield from walk(k, child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from walk(key, child)

    for attribute in ("title", "description"):
        value = getattr(embed, attribute, None)
        if isinstance(value, str):
            yield value

    for field in getattr(embed, "fields", ()):
        if isinstance(field, dict):
            name = field.get("name")
            val = field.get("value")
        else:
            name = getattr(field, "name", None)
            val = getattr(field, "value", None)
        if isinstance(name, str):
            yield name
        if isinstance(val, str):
            yield val

    author = getattr(embed, "author", None)
    author_url = getattr(author, "url", None)
    if isinstance(author_url, str):
        yield author_url

    to_dict = getattr(embed, "to_dict", None)
    if callable(to_dict):
        try:
            yield from walk("", to_dict())
        except Exception:
            log.debug("No se pudo serializar embed para !gif", exc_info=True)


def _embed_url_texts(message: MessageSource):
    """Expone las URLs y texto serializado de cualquier variante de embed."""
    for embed in getattr(message, "embeds", ()):
        yield from _embed_url_texts_single(embed)


def _embed_video_urls(message: MessageSource):
    """Entrega todas las URLs potenciales de video de los embeds del mensaje.

    Cubre todas las variantes de embeds de Discord:
    1. Embeds con reproductor de video (type='video', 'gifv'):
       - embed.video.url y embed.video.proxy_url
    2. Embeds con URL principal (type='rich', 'link', 'article', etc.):
       - embed.url
    3. URLs encontradas en description, fields o to_dict() del embed
    """
    seen: set[str] = set()

    def _yield_url(raw: str | None):
        if not raw or not isinstance(raw, str):
            return
        cleaned = _clean_url(raw)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            yield cleaned

    for embed in getattr(message, "embeds", ()):
        # 1. Video explícito del embed
        video = getattr(embed, "video", None)
        if video is not None:
            for name in ("url", "proxy_url"):
                yield from _yield_url(getattr(video, name, None))

        # 2. URL principal del embed (clave en embeds tipo 'rich', 'link', 'article')
        yield from _yield_url(getattr(embed, "url", None))

        # 3. URLs en texto serializado del embed
        for text in _embed_url_texts_single(embed):
            for match in _MEDIA_URL_RE.finditer(text):
                yield from _yield_url(match.group(0))


def _component_media_urls(message: MessageSource):
    """Toda URL de medio dentro de message.components (Components V2:
    Container/Section/MediaGallery/File anidados en cualquier profundidad,
    ver layout_v2.py). Un mensaje NO puede tener embeds clásicos y
    Components V2 a la vez -- son excluyentes vía el flag IS_COMPONENTS_V2
    (layout_v2.py) -- así que cuando message.embeds viene vacío pero el
    mensaje sí muestra algo (ej. un bot posteando su resultado con esta UI
    en vez de un embed clásico), esto es la ÚNICA fuente posible de medio
    embebido; sin este paso, _embed_video_urls/_embed_media_urls (que solo
    miran message.embeds) no tienen nada que recorrer y "!gif" falla aunque
    el video esté ahí, a la vista.

    Recorre TANTO el dict crudo (to_dict(), como _embed_url_texts_single con
    los embeds: el campo "media"/"file" con una "url" adentro es el schema
    de Discord, estable pase lo que pase con el nombre de atributo Python de
    turno) COMO los atributos directos del objeto (.media/.file y
    .items/.children/.components/.accessory para bajar un nivel) -- no hay
    forma de instalar discord.py acá para confirmar cuál de los dos expone
    cada clase de Components V2 recibida, así que se prueban los dos en vez
    de apostar a uno solo y fallar en silencio si se apostó mal."""
    seen: set[str] = set()

    def yield_media_url(media):
        url = (
            media.get("url") if isinstance(media, dict) else getattr(media, "url", None)
        )
        if isinstance(url, str) and url and url not in seen:
            seen.add(url)
            yield url

    def walk(node):
        if node is None or isinstance(node, str):
            return
        if isinstance(node, dict):
            for key in ("media", "file"):
                sub = node.get(key)
                if sub is not None:
                    yield from yield_media_url(sub)
            for child in node.values():
                yield from walk(child)
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                yield from walk(item)
            return

        # Objeto de discord.py (no dict/list/str): mismos dos campos por
        # atributo directo, más to_dict() y los contenedores conocidos.
        for key in ("media", "file"):
            sub = getattr(node, key, None)
            if sub is not None:
                yield from yield_media_url(sub)
        to_dict = getattr(node, "to_dict", None)
        if callable(to_dict):
            try:
                yield from walk(to_dict())
            except Exception:
                log.debug("No se pudo serializar componente para !gif", exc_info=True)
        for attr in ("items", "children", "components", "accessory"):
            sub = getattr(node, attr, None)
            if sub is not None:
                yield from walk(sub)

    for component in getattr(message, "components", None) or ():
        yield from walk(component)


async def _fetch_media_bytes(
    url: str, max_bytes: int, timeout: float = 15.0
) -> bytes | None:
    """Baja una URL HTTP(S) de medios con límite y protección SSRF."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    def _download() -> bytes | None:
        try:
            response = r2.fetch_public_url(
                requests.get,
                url,
                headers={"User-Agent": _BROWSER_UA},
                timeout=timeout,
                stream=True,
            )
            try:
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type.startswith("text/html"):
                    return None
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise SourceTooLarge(max_bytes)
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=262144):
                    total += len(chunk)
                    if total > max_bytes:
                        raise SourceTooLarge(max_bytes)
                    chunks.append(chunk)
                data = b"".join(chunks)
                if data.lstrip().startswith(
                    (b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"<?xml")
                ):
                    return None
                return data
            finally:
                response.close()
        except SourceTooLarge:
            raise
        except Exception:
            log.debug("No se pudo bajar medio para !gif: %s", url, exc_info=True)
            return None

    return await asyncio.to_thread(_download)


async def _resolve_component_media_bytes(
    message: MessageSource, url: str, max_bytes: int
) -> bytes | None:
    """Como _fetch_media_bytes, pero entiende "attachment://<filename>" --
    el esquema que usa un bloque File/MediaGallery de Components V2 cuando
    el medio no es una URL externa sino un adjunto real del mismo mensaje
    (ver layout_v2.py). Ese archivo ya viene en message.attachments; un GET
    HTTP a ese "url" literal fallaría (no es http/https), así que hay que
    resolverlo ahí en vez de pasarlo a _fetch_media_bytes."""
    if url.startswith("attachment://"):
        filename = url[len("attachment://") :]
        for attachment in getattr(message, "attachments", ()):
            if getattr(attachment, "filename", None) == filename:
                if attachment.size > max_bytes:
                    raise SourceTooLarge(max_bytes)
                return await attachment.read()
        return None
    return await _fetch_media_bytes(url, max_bytes)


def _check_fx_cooldown(user_id: int) -> int | None:
    now = time.monotonic()
    elapsed = now - _fx_cooldowns.get(user_id, 0.0)
    if elapsed < _FX_COOLDOWN_SECONDS:
        return int(_FX_COOLDOWN_SECONDS - elapsed) or 1
    _fx_cooldowns[user_id] = now
    return None


def _check_gif_convert_cooldown(user_id: int) -> int | None:
    now = time.monotonic()
    elapsed = now - _gif_convert_cooldowns.get(user_id, 0.0)
    if elapsed < _GIF_CONVERT_COOLDOWN_SECONDS:
        return int(_GIF_CONVERT_COOLDOWN_SECONDS - elapsed) or 1
    _gif_convert_cooldowns[user_id] = now
    return None


async def _find_attachment(
    ctx: commands.Context, exts: set[str], content_type_prefix: str | None = None
) -> discord.Attachment | None:
    """content_type_prefix es un fallback además de la extensión (no en su
    reemplazo) -- lo usa _resolve_video_bytes/_resolve_gif_source_image_bytes
    porque algunos clientes suben el archivo con una extensión que no está
    en el set (ej. .mkv), pero sí content_type="video/..." o "image/...",
    mismo patrón que ya usa cogs/gifs.py.save_gif_candidates para adjuntos
    GIF. getattr en vez de attachment.content_type directo: un
    discord.Attachment real siempre tiene el atributo (None si Discord no
    reportó uno), pero no vale la pena exigirlo de cualquier objeto que
    llegue acá -- mismo criterio que _embed_video_url/_embed_image_url en
    cogs/download.py."""

    def _matches(attachment: discord.Attachment) -> bool:
        if os.path.splitext(attachment.filename.lower())[1] in exts:
            return True
        content_type = getattr(attachment, "content_type", None)
        return bool(
            content_type_prefix
            and content_type
            and content_type.lower().startswith(content_type_prefix)
        )

    for message in await _source_messages(ctx):
        for attachment in getattr(message, "attachments", ()):
            if _matches(attachment):
                return attachment
    return None


async def _resolve_image_bytes(ctx: commands.Context) -> bytes:
    """Adjunto propio -> adjunto del mensaje respondido -> avatar de quien
    invoca. with_static_format fuerza un PNG estático incluso si el avatar
    es animado -- is_valid_image no acepta GIF (ver _ALLOWED_FORMATS en
    meme_generator.py)."""
    attachment = await _find_attachment(ctx, _IMAGE_EXTS)
    if attachment is not None:
        if attachment.size > IMAGEFX_MAX_BYTES:
            raise SourceTooLarge(IMAGEFX_MAX_BYTES)
        return await attachment.read()
    avatar = ctx.author.display_avatar.with_static_format("png")
    return await avatar.read()


async def _resolve_image_or_gif_bytes(
    ctx: commands.Context, allow_gif: bool = True
) -> tuple[bytes, bool]:
    """Fuente de los ~25 comandos de "Filtros de imagen" (Fase 1/2), ahora
    también con GIF: intenta primero resolver un GIF (adjunto, reply o
    embebido -- reutiliza _resolve_gif_bytes, que ya cubre Tenor/embeds/
    Components V2) y, si no hay ninguno, cae al flujo de imagen estática de
    siempre (_resolve_image_bytes: adjunto propio -> adjunto del reply ->
    avatar). Devuelve (bytes, es_gif) para que el caller (ImageFx._run_filter)
    elija entre aplicar el filtro una vez (PNG) o frame por frame
    (image_filters.apply_per_frame, GIF de salida).

    allow_gif=False lo saltea del todo -- lo usa "!triggered", que ya genera
    su propio GIF corto (zoom + temblor) a partir de una imagen fija: correr
    ese efecto frame por frame sobre un GIF de entrada anidaría una
    animación dentro de otra sin necesidad real, y con un costo mucho más
    alto (frames del GIF fuente × 8 sub-frames de triggered).

    _resolve_image_bytes solo encuentra un adjunto por EXTENSIÓN de imagen
    estática (.png/.jpg/.jpeg/.webp), sin mirar el contenido -- por eso un
    GIF real subido con esa extensión (ej. Discord nombra "image.png" lo que
    se pega desde el portapapeles, sea cual sea el formato real detrás) no
    lo encuentra ninguno de los pasos de _resolve_gif_bytes (que sí exigen
    ".gif"/"image/gif" o convierten un video) y termina acá con el
    contenido real de un GIF bajo una extensión mentirosa. Sin este segundo
    chequeo, ese caso rechazaba con "formato no compatible" en vez de
    aplicar el filtro -- se confirma recién acá, no antes, porque hacerlo en
    cada candidato de _resolve_image_bytes duplicaría el mismo chequeo por
    cada llamada (adjunto propio, del reply, avatar)."""
    if allow_gif:
        gif_data = await _resolve_gif_bytes(ctx)
        if gif_data is not None:
            return gif_data, True
    data = await _resolve_image_bytes(ctx)
    if allow_gif and is_valid_gif_bytes(data):
        return data, True
    return data, False


async def _as_gif_bytes(data: bytes) -> bytes | None:
    """Acepta `data` como fuente de "un GIF" para _resolve_gif_bytes: si ya
    es un GIF real (firma GIF87a/GIF89a) se devuelve tal cual. Si no, se
    descarta directo cuando es una imagen estática válida (evita que un
    thumbnail PNG de un embed se cuele como si fuera video -- mismo criterio
    que ya usa _resolve_video_bytes para no confundir la miniatura con el
    video real) y, para cualquier otra cosa, se prueba la misma conversión
    que usa "!gif" (video_filters.convert_video_to_gif): gran parte de lo
    que la gente comparte como "un GIF" en Discord en realidad es un archivo
    de video (mp4/webm) que loopea igual -- Twitter/Reddit transcodean a
    video los GIFs que se suben, y esa es la copia que circula -- así que
    sin este paso ese archivo se descartaba en silencio aunque el mensaje se
    viera exactamente igual a un GIF real. VideoConversionFailed solo
    significa que tampoco era un video utilizable: None, para que el caller
    siga probando el próximo candidato. GifTooLarge se deja propagar -- acá
    sí hay una fuente real, así que el caller la trata como error propio en
    vez de como "no encontré nada"."""
    if is_valid_gif_bytes(data):
        return data
    if is_valid_image(data):
        return None
    try:
        return await asyncio.to_thread(
            video_filters.convert_video_to_gif,
            data,
            GIF_MAX_DURATION_SECONDS,
            IMAGEFX_MAX_BYTES,
        )
    except video_filters.VideoConversionFailed:
        return None


async def _resolve_gif_bytes(ctx: commands.Context) -> bytes | None:
    """Adjunto propio (GIF real o video que se ve como uno) -> mismo par de
    opciones en el adjunto del mensaje respondido -> GIF o video embebido
    (embed clásico, Components V2, o URL en el texto/embed) del mensaje
    actual o del respondido -- ej. un GIF mandado con el selector de Tenor
    de Discord no llega como adjunto real, llega como embed, así que sin
    este fallback "responder a un mensaje con un GIF" fallaba para
    !gifwide/!gifspeed/!gifreverse/!gifcaption aunque el GIF estuviera a la
    vista (mismo bug que _resolve_video_bytes/_resolve_gif_source_image_bytes
    ya cubren para "!gif"). Cada candidato pasa por _as_gif_bytes en vez de
    un chequeo directo de is_valid_gif_bytes -- ver su docstring: además de
    validar, ahí es donde se resuelve el caso de un video (mp4/webm) que
    visualmente es indistinguible de un GIF (sin sonido, en loop) pero no
    tiene el contenedor de GIF real, ej. algo re-subido desde Twitter/Reddit.
    A diferencia de _resolve_image_bytes, sin fallback a avatar (no hay
    "avatar en GIF" que tenga sentido usar acá) -- None significa "no hay
    nada para editar"."""
    attachment = await _find_attachment(ctx, _GIF_EXTS, content_type_prefix="image/gif")
    if attachment is not None:
        if attachment.size > IMAGEFX_MAX_BYTES:
            raise SourceTooLarge(IMAGEFX_MAX_BYTES)
        return await attachment.read()

    video_attachment = await _find_attachment(
        ctx, _VIDEO_EXTS, content_type_prefix="video/"
    )
    if video_attachment is not None:
        if video_attachment.size > MAX_GIF_SOURCE_VIDEO_BYTES:
            raise SourceTooLarge(MAX_GIF_SOURCE_VIDEO_BYTES)
        converted = await _as_gif_bytes(await video_attachment.read())
        if converted is not None:
            return converted

    if ctx.message.attachments:
        return None

    seen_urls: set[str] = set()
    for message in await _source_messages(ctx):
        media_urls = (
            list(_embed_media_urls(message, ("image", "thumbnail")))
            + list(_embed_video_urls(message))
            + list(_component_media_urls(message))
        )
        for media_url in media_urls:
            if media_url in seen_urls:
                continue
            seen_urls.add(media_url)
            data = await _resolve_component_media_bytes(
                message, media_url, IMAGEFX_MAX_BYTES
            )
            if data is not None:
                converted = await _as_gif_bytes(data)
                if converted is not None:
                    return converted

    candidates: list[str] = []
    for message in await _source_messages(ctx):
        content = getattr(message, "content", "") or ""
        if content:
            candidates.append(content)
        candidates.extend(_embed_url_texts(message))
    for candidate in candidates:
        for match in _MEDIA_URL_RE.finditer(candidate):
            clean = _clean_url(match.group(0))
            if not clean or clean in seen_urls:
                continue
            seen_urls.add(clean)
            data = await _fetch_media_bytes(clean, IMAGEFX_MAX_BYTES)
            if data is not None:
                converted = await _as_gif_bytes(data)
                if converted is not None:
                    return converted

    return None


async def _resolve_social_video_bytes(
    ctx: commands.Context, url: str | None
) -> bytes | None:
    """Último recurso de "!gif": un link a Instagram/TikTok/Twitter-X/Facebook
    (URL propia, texto del mensaje actual o del respondido, o el Embed.url
    que Discord genera al desempaquetarlo) resuelto con el mismo extractor
    que "!dl" (yt_dlp, vía cogs/download.py). Los pasos anteriores de
    _resolve_video_bytes (GET directo a embed.video/proxy_url/embed.url) NO
    alcanzan para estos cuatro sitios -- el CDN de origen no sirve el
    archivo a un GET anónimo -- así que hace falta la misma extracción real
    que ya usa "!dl", no otro intento de adivinar una URL descargable.

    Prueba cada link reconocido (download_mod._is_supported_url) hasta que
    uno descargue; None si ninguno lo es o ninguno se pudo bajar. Puede
    levantar SourceTooLarge o SensitiveContentBlocked -- mismas excepciones
    que _resolve_video_bytes, el caller ya las maneja igual."""
    seen: set[str] = set()
    candidates: list[str] = [url] if url else []
    for message in await _source_messages(ctx):
        content = getattr(message, "content", "") or ""
        if content:
            candidates.append(content)
        for embed in getattr(message, "embeds", ()):
            embed_url = getattr(embed, "url", None)
            if embed_url:
                candidates.append(embed_url)

    social_urls: list[str] = []
    for candidate in candidates:
        for match in _MEDIA_URL_RE.finditer(candidate):
            clean = _clean_url(match.group(0))
            if not clean or clean in seen:
                continue
            seen.add(clean)
            if download_mod._is_supported_url(clean):
                social_urls.append(clean)

    for social_url in social_urls:
        try:
            path, is_sensitive = await asyncio.to_thread(
                download_mod._download_video, social_url, MAX_GIF_SOURCE_VIDEO_BYTES
            )
        except download_mod.DownloadTooLarge as e:
            raise SourceTooLarge(e.max_bytes) from e
        except download_mod.DownloadFailed:
            continue

        tmp_dir = os.path.dirname(path)
        try:
            channel_is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: False)()
            if is_sensitive and not channel_is_nsfw:
                raise SensitiveContentBlocked()
            with open(path, "rb") as f:
                return f.read()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return None


async def _resolve_video_bytes(
    ctx: commands.Context, url: str | None = None
) -> bytes | None:
    """Fuente del video para "!gif":
    1. Adjunto de video propio o del mensaje respondido (extensión o video/*).
    2. Video en los embeds del mensaje actual o del respondido:
       - embed.video (url y proxy_url)
       - embed.url (clave en embeds de tipo rich, link, etc. que envían bots)
       - URLs en description, fields o payload serializado del embed
    2b. Video en los Components V2 del mensaje (Container/MediaGallery/File
        anidados) cuando ese mensaje no tiene embeds -- son excluyentes,
        ver _component_media_urls.
    3. URL provista como argumento o presente en el texto del mensaje.
    4. Link a Instagram/TikTok/Twitter-X/Facebook resuelto vía yt-dlp
       (_resolve_social_video_bytes) -- únicamente si nada de lo anterior
       encontró nada descargable.
    """
    attachment = await _find_attachment(ctx, _VIDEO_EXTS, content_type_prefix="video/")
    if attachment is not None:
        if attachment.size > MAX_GIF_SOURCE_VIDEO_BYTES:
            raise SourceTooLarge(MAX_GIF_SOURCE_VIDEO_BYTES)
        return await attachment.read()

    # Si el comando tiene un adjunto propio (aunque sea imagen), ese adjunto
    # local tiene prioridad sobre links o descargas web.
    if ctx.message.attachments:
        return None

    seen_urls: set[str] = set()
    for message in await _source_messages(ctx):
        media_urls = list(_embed_video_urls(message)) + list(
            _component_media_urls(message)
        )
        for video_url in media_urls:
            if video_url in seen_urls:
                continue
            seen_urls.add(video_url)
            data = await _resolve_component_media_bytes(
                message, video_url, MAX_GIF_SOURCE_VIDEO_BYTES
            )
            if data is not None:
                if is_valid_image(data):
                    continue
                return data

    candidates: list[str] = [url] if url else []
    for message in await _source_messages(ctx):
        content = getattr(message, "content", "") or ""
        if content:
            candidates.append(content)
    for candidate in candidates:
        for match in _MEDIA_URL_RE.finditer(candidate):
            clean = _clean_url(match.group(0))
            if not clean or clean in seen_urls:
                continue
            seen_urls.add(clean)
            data = await _fetch_media_bytes(clean, MAX_GIF_SOURCE_VIDEO_BYTES)
            if data is not None and not is_valid_image(data):
                return data

    return await _resolve_social_video_bytes(ctx, url)


async def _resolve_gif_source_image_bytes(
    ctx: commands.Context, url: str | None = None
) -> bytes | None:
    """Fuente de imagen para "!gif" cuando NO hubo ningún video:
    1. Adjunto de imagen propio o del mensaje respondido
    2. Imagen o thumbnail embebidos en el mensaje (embed clásico o, si no
       tiene embeds, Components V2 -- ver _component_media_urls)
    3. URL directa o presente en el texto del mensaje
    """
    attachment = await _find_attachment(ctx, _IMAGE_EXTS, content_type_prefix="image/")
    if attachment is not None:
        if attachment.size > IMAGEFX_MAX_BYTES:
            raise SourceTooLarge(IMAGEFX_MAX_BYTES)
        return await attachment.read()

    if ctx.message.attachments:
        return None

    seen_urls: set[str] = set()
    for message in await _source_messages(ctx):
        media_urls = list(_embed_media_urls(message, ("image", "thumbnail"))) + list(
            _component_media_urls(message)
        )
        for image_url in media_urls:
            if image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            data = await _resolve_component_media_bytes(
                message, image_url, IMAGEFX_MAX_BYTES
            )
            if data is not None:
                return data

    candidates: list[str] = [url] if url else []
    for message in await _source_messages(ctx):
        content = getattr(message, "content", "") or ""
        if content:
            candidates.append(content)
        candidates.extend(_embed_url_texts(message))
    for candidate in candidates:
        for match in _MEDIA_URL_RE.finditer(candidate):
            clean = _clean_url(match.group(0))
            if not clean or clean in seen_urls:
                continue
            seen_urls.add(clean)
            data = await _fetch_media_bytes(clean, IMAGEFX_MAX_BYTES)
            if data is not None:
                return data

    return None


class ImageFx(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _run_filter(
        self,
        ctx: commands.Context,
        fn: Callable[..., bytes],
        *args,
        filename: str = "purgito.png",
        animatable: bool = True,
    ) -> None:
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        remaining = _check_fx_cooldown(ctx.author.id)
        if remaining is not None:
            await ctx.reply(t("general.error.cooldown", locale, seconds=remaining))
            return

        try:
            data, is_gif = await _resolve_image_or_gif_bytes(ctx, allow_gif=animatable)
        except SourceTooLarge as e:
            await ctx.reply(
                t("imagefx.too_large", locale, mb=e.max_bytes // (1024 * 1024))
            )
            return
        except video_filters.GifTooLarge as e:
            await ctx.reply(
                t(
                    "imagefx.gif_output_too_large",
                    locale,
                    mb=e.max_bytes // (1024 * 1024),
                )
            )
            return
        except discord.HTTPException:
            await ctx.reply(t("general.error.generic", locale))
            return

        if is_gif:
            if not is_valid_gif_bytes(data):
                await ctx.reply(t("imagefx.invalid_gif", locale))
                return
            try:
                result = await asyncio.to_thread(
                    image_filters.apply_per_frame, fn, data, *args
                )
            except Exception:
                log.exception(
                    "Error aplicando filtro de imagen a un GIF (%s)", fn.__name__
                )
                await ctx.reply(t("general.error.generic", locale))
                return
            await ctx.reply(
                file=discord.File(io.BytesIO(result), filename="purgito.gif")
            )
            return

        if not is_valid_image(data):
            await ctx.reply(t("imagefx.invalid_image", locale))
            return

        try:
            result = await asyncio.to_thread(fn, data, *args)
        except Exception:
            log.exception("Error aplicando filtro de imagen (%s)", fn.__name__)
            await ctx.reply(t("general.error.generic", locale))
            return

        await ctx.reply(file=discord.File(io.BytesIO(result), filename=filename))

    async def _run_gif_filter(
        self, ctx: commands.Context, fn: Callable[..., bytes], *args
    ) -> None:
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        remaining = _check_fx_cooldown(ctx.author.id)
        if remaining is not None:
            await ctx.reply(t("general.error.cooldown", locale, seconds=remaining))
            return

        try:
            data = await _resolve_gif_bytes(ctx)
        except SourceTooLarge as e:
            await ctx.reply(
                t("imagefx.too_large", locale, mb=e.max_bytes // (1024 * 1024))
            )
            return
        except video_filters.GifTooLarge as e:
            await ctx.reply(
                t(
                    "imagefx.gif_output_too_large",
                    locale,
                    mb=e.max_bytes // (1024 * 1024),
                )
            )
            return
        except discord.HTTPException:
            await ctx.reply(t("general.error.generic", locale))
            return

        if data is None:
            await ctx.reply(t("imagefx.gif_missing", locale))
            return
        if not is_valid_gif_bytes(data):
            await ctx.reply(t("imagefx.invalid_gif", locale))
            return

        try:
            result = await asyncio.to_thread(fn, data, *args)
        except Exception:
            log.exception("Error aplicando filtro de GIF (%s)", fn.__name__)
            await ctx.reply(t("general.error.generic", locale))
            return

        await ctx.reply(file=discord.File(io.BytesIO(result), filename="purgito.gif"))

    @commands.command(name="caption")
    async def caption_cmd(self, ctx: commands.Context, *, texto: str | None = None):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if not texto:
            await ctx.reply(t("imagefx.caption.missing_text", locale))
            return
        await self._run_filter(ctx, image_filters.caption, texto)

    @commands.command(name="deepfry")
    async def deepfry_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.deepfry)

    @commands.command(name="wide")
    async def wide_cmd(self, ctx: commands.Context, factor: float = 2.0):
        await self._run_filter(ctx, image_filters.wide, factor)

    @commands.command(name="squish")
    async def squish_cmd(self, ctx: commands.Context, factor: float = 0.5):
        await self._run_filter(ctx, image_filters.squish, factor)

    @commands.command(name="invert")
    async def invert_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.invert)

    @commands.command(name="greyscale", aliases=["grayscale"])
    async def greyscale_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.greyscale)

    @commands.command(name="sepia")
    async def sepia_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.sepia)

    @commands.command(name="pixelate")
    async def pixelate_cmd(self, ctx: commands.Context, block_size: int = 12):
        await self._run_filter(ctx, image_filters.pixelate, block_size)

    @commands.command(name="rotate")
    async def rotate_cmd(self, ctx: commands.Context, degrees: int = 90):
        await self._run_filter(ctx, image_filters.rotate, degrees)

    @commands.command(name="flip")
    async def flip_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.flip)

    @commands.command(name="flop")
    async def flop_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.flop)

    @commands.command(name="circle")
    async def circle_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.circle)

    @commands.command(name="blur")
    async def blur_cmd(self, ctx: commands.Context, radius: int = 6):
        await self._run_filter(ctx, image_filters.blur, radius)

    @commands.command(name="sharpen")
    async def sharpen_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.sharpen)

    # ── Fase 2: overlays y efectos de un solo chiste ─────────────────────────

    @commands.command(name="triggered")
    async def triggered_cmd(self, ctx: commands.Context):
        await self._run_filter(
            ctx, image_filters.triggered, filename="purgito.gif", animatable=False
        )

    @commands.command(name="wasted")
    async def wasted_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.wasted)

    @commands.command(name="trash")
    async def trash_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.trash)

    @commands.command(name="communism")
    async def communism_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.communism)

    @commands.command(name="gay")
    async def gay_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.gay)

    @commands.command(name="jail")
    async def jail_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.jail)

    @commands.command(name="wanted")
    async def wanted_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.wanted)

    @commands.command(name="rip")
    async def rip_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.rip)

    @commands.command(name="america")
    async def america_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.america)

    @commands.command(name="polaroid")
    async def polaroid_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.polaroid)

    @commands.command(name="poster")
    async def poster_cmd(self, ctx: commands.Context, bits: int = 2):
        await self._run_filter(ctx, image_filters.poster, bits)

    @commands.command(name="threshold")
    async def threshold_cmd(self, ctx: commands.Context, level: int = 128):
        await self._run_filter(ctx, image_filters.threshold, level)

    @commands.command(name="emboss")
    async def emboss_cmd(self, ctx: commands.Context):
        await self._run_filter(ctx, image_filters.emboss)

    # ── Fase 4: video -> GIF y edición de un GIF existente ───────────────────

    # hybrid_command (mismo motivo que "dl" en cogs/download.py: /gif con
    # installation type "user" y context "private channel" es la única forma
    # de que esto funcione fuera de un servidor, incluido un Group DM). El
    # parámetro "archivo" es nuevo acá porque en un slash command no existe
    # "mandar un adjunto junto al mensaje" -- discord.py convierte un
    # parámetro discord.Attachment en la opción de subida del slash Y, del
    # lado de invocación por interacción, lo agrega solo a
    # ctx.message.attachments (ver discord.ext.commands.context.Context.
    # from_interaction), así que _resolve_video_bytes/_resolve_gif_source_
    # image_bytes de más abajo lo encuentran sin ningún cambio adicional. Va
    # ANTES del "*, url" (keyword-only): discord.py corta el parseo de texto
    # en el primer parámetro keyword-only que encuentra, así que uno después
    # de "url" nunca se poblaría al invocar como "!gif"/"purgito gif".
    @commands.hybrid_command(
        name="gif", description="Convierte un video o una imagen a GIF."
    )
    @app_commands.describe(
        url="Link del video/imagen a convertir, o del post de Instagram/TikTok/X/Facebook.",
        archivo="Video o imagen para convertir (alternativa a un link).",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=False)
    async def gif_cmd(
        self,
        ctx: commands.Context,
        archivo: discord.Attachment | None = None,
        *,
        url: str | None = None,
    ):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        remaining = _check_gif_convert_cooldown(ctx.author.id)
        if remaining is not None:
            await ctx.reply(t("general.error.cooldown", locale, seconds=remaining))
            return

        try:
            data = await _resolve_video_bytes(ctx, url=url)
        except SourceTooLarge as e:
            await ctx.reply(
                t("imagefx.video_too_large", locale, mb=e.max_bytes // (1024 * 1024))
            )
            return
        except SensitiveContentBlocked:
            await ctx.reply(t("download.dl.nsfw_channel_required", locale))
            return
        except discord.HTTPException:
            await ctx.reply(t("general.error.generic", locale))
            return

        if data is None:
            # Sin ningún video (adjunto, embed o URL): se busca una imagen
            # estática como fallback (adjunto, embed o URL) y se empaqueta
            # como GIF de un solo frame.
            try:
                image_data = await _resolve_gif_source_image_bytes(ctx, url=url)
            except SourceTooLarge as e:
                await ctx.reply(
                    t("imagefx.too_large", locale, mb=e.max_bytes // (1024 * 1024))
                )
                return
            except discord.HTTPException:
                await ctx.reply(t("general.error.generic", locale))
                return

            if image_data is not None:
                if not is_valid_image(image_data):
                    await ctx.reply(t("imagefx.invalid_image", locale))
                    return
                try:
                    result = await asyncio.to_thread(
                        image_filters.image_to_gif, image_data
                    )
                except Exception:
                    log.exception("Error convirtiendo imagen a GIF en !gif")
                    await ctx.reply(t("general.error.generic", locale))
                    return
                await ctx.reply(
                    file=discord.File(io.BytesIO(result), filename="purgito.gif")
                )
                return

            await ctx.reply(t("imagefx.video_missing", locale))
            return

        if is_valid_image(data):
            try:
                result = await asyncio.to_thread(image_filters.image_to_gif, data)
            except Exception:
                log.exception("Error convirtiendo imagen a GIF en !gif")
                await ctx.reply(t("general.error.generic", locale))
                return
            await ctx.reply(
                file=discord.File(io.BytesIO(result), filename="purgito.gif")
            )
            return

        async with ctx.typing():
            max_output = IMAGEFX_MAX_BYTES
            if ctx.guild is not None:
                max_output = min(max_output, ctx.guild.filesize_limit)

            try:
                result = await asyncio.to_thread(
                    video_filters.convert_video_to_gif,
                    data,
                    GIF_MAX_DURATION_SECONDS,
                    max_output,
                )
            except video_filters.GifTooLarge as e:
                await ctx.reply(
                    t(
                        "imagefx.gif_output_too_large",
                        locale,
                        mb=e.max_bytes // (1024 * 1024),
                    )
                )
                return
            except video_filters.VideoConversionFailed:
                await ctx.reply(t("imagefx.video_conversion_failed", locale))
                return

        await ctx.reply(file=discord.File(io.BytesIO(result), filename="purgito.gif"))

    @gif_cmd.error
    async def gif_cmd_error(self, ctx: commands.Context, error: Exception):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if isinstance(error, commands.MaxConcurrencyReached):
            await ctx.reply(t("imagefx.gif_busy", locale))
            return
        log.error("Error en comando !gif", exc_info=error)
        await ctx.reply(t("general.error.generic", locale))

    @commands.command(name="gifcaption")
    async def gifcaption_cmd(self, ctx: commands.Context, *, texto: str | None = None):
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if not texto:
            await ctx.reply(t("imagefx.caption.missing_text", locale))
            return
        await self._run_gif_filter(ctx, image_filters.gif_caption, texto)

    @commands.command(name="gifspeed")
    async def gifspeed_cmd(self, ctx: commands.Context, factor: float = 2.0):
        await self._run_gif_filter(ctx, image_filters.gif_speed, factor)

    @commands.command(name="gifreverse")
    async def gifreverse_cmd(self, ctx: commands.Context):
        await self._run_gif_filter(ctx, image_filters.gif_reverse)

    @commands.command(name="gifwide")
    async def gifwide_cmd(self, ctx: commands.Context, factor: float = 2.0):
        await self._run_gif_filter(ctx, image_filters.gif_wide, factor)

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        error = getattr(error, "original", error)
        locale = await guild_locale(ctx.guild.id if ctx.guild else None)
        if isinstance(error, commands.BadArgument):
            await ctx.reply(t("general.error.missing_argument", locale))
            return
        log.error("Error en comando de imagefx (%s)", ctx.command, exc_info=error)
        await ctx.reply(t("general.error.generic", locale))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImageFx(bot))
