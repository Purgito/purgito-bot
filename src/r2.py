"""Cliente Cloudflare R2 con inicialización perezosa.

El cliente se crea la primera vez que se necesita; si faltan variables de
entorno el módulo igual importa sin romper nada y available() devuelve False.
"""

import asyncio
import hashlib
import io
import logging
import os
import subprocess
from typing import NamedTuple

import requests

log = logging.getLogger(__name__)

_client = None
_checked = False

# Sentinel: el GIF supera el límite de tamaño (no guardar en DB, no reintentar).
GIF_TOO_LARGE = ""


class GifUpload(NamedTuple):
    """Resultado de subir un GIF a R2.

    `url` == GIF_TOO_LARGE ('') significa que el archivo superaba el límite.
    `content_hash` es el sha256 de los bytes que efectivamente se subieron:
    es la identidad del objeto en el bucket y lo que usa db.gif_objects para
    contar referencias.
    `phash` es el dHash perceptual de los bytes locales, calculado solo
    cuando no hubo match exacto (ver upload_gif_sync); el caller lo pasa a
    db.save_gif_url para que quede guardado si el objeto es nuevo de verdad.
    """

    url: str
    content_hash: str = ""
    size_bytes: int = 0
    phash: str | None = None


# Prefijo exclusivo de los GIFs content-addressed. Las imágenes de memes y las
# subidas del editor de embeds usan `{guild_id}/...`, así que este prefijo es
# lo que le permite al barrido de huérfanos borrar sin riesgo de tocarlas.
GIF_KEY_PREFIX = "gifs/"


def gif_key(content_hash: str) -> str:
    """Key content-addressed, sin guild_id: el mismo archivo subido por
    cualquier servidor cae siempre en el mismo objeto. Los dos primeros
    caracteres del hash reparten los objetos en 256 prefijos en vez de
    amontonarlos todos en un mismo 'directorio'."""
    return f"{GIF_KEY_PREFIX}{content_hash[:2]}/{content_hash}.gif"


def list_keys_sync(prefix: str) -> list[tuple[str, int, object]]:
    """(key, tamaño, fecha de modificación) de los objetos bajo un prefijo.

    Pagina la respuesta y solo devuelve metadata; el contenido no se baja.
    """
    client = get_client()
    if client is None:
        return []
    out = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
        for obj in page.get("Contents", []):
            out.append((obj["Key"], obj["Size"], obj.get("LastModified")))
    return out


_IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def public_url() -> str:
    return os.getenv("R2_PUBLIC_URL", "").strip()


def _bucket() -> str:
    return os.getenv("R2_BUCKET_NAME", "").strip()


def get_client():
    global _client, _checked
    if not _checked:
        _checked = True
        endpoint = os.getenv("R2_ENDPOINT_URL", "").strip()
        key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        secret = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        if endpoint and key_id and secret and _bucket():
            import boto3
            from botocore.config import Config

            _client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=key_id,
                aws_secret_access_key=secret,
                config=Config(signature_version="s3v4"),
                region_name="auto",
            )
    return _client


def available() -> bool:
    return get_client() is not None


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, "") or default)
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default


def _lossy_level() -> int:
    """Nivel de --lossy de gifsicle. 0 desactiva la compresión con pérdida
    pero deja el --optimize=3 (que no toca la calidad)."""
    try:
        v = int(os.getenv("GIF_LOSSY_LEVEL", "") or 30)
    except (ValueError, TypeError):
        return 30
    return max(0, min(v, 200))


def optimize_gif_bytes(data: bytes) -> bytes:
    """Pasa el GIF por gifsicle y devuelve la versión más chica.

    Degrada con gracia: si gifsicle no está instalado, truena, tarda demasiado
    o devuelve algo más grande, retorna los bytes originales. Optimizar nunca
    debe impedir que se guarde un GIF.

    Trabaja sobre bytes a propósito (stdin/stdout, sin archivos temporales):
    así la usan igual la subida en caliente y el backfill, que ya tiene el
    objeto descargado en memoria.
    """
    cmd = ["gifsicle", "--optimize=3", "--no-warnings"]
    lossy = _lossy_level()
    if lossy:
        cmd.append(f"--lossy={lossy}")
    try:
        proc = subprocess.run(cmd, input=data, capture_output=True, timeout=60)
    except FileNotFoundError:
        log.debug("gifsicle no está instalado: se sube el GIF sin optimizar")
        return data
    except Exception:
        log.warning("gifsicle falló: se sube el GIF sin optimizar", exc_info=True)
        return data
    if proc.returncode != 0 or not proc.stdout:
        log.debug(
            "gifsicle salió con código %s: se sube sin optimizar", proc.returncode
        )
        return data
    if len(proc.stdout) >= len(data):
        return data
    log.debug("GIF optimizado: %d -> %d bytes", len(data), len(proc.stdout))
    return proc.stdout


def _object_exists(client, key: str) -> bool:
    try:
        client.head_object(Bucket=_bucket(), Key=key)
        return True
    except Exception:
        return False


def compute_phash(data: bytes) -> str | None:
    """dHash perceptual del primer frame del GIF, para detectar casi-duplicados
    (mismo meme, distinta compresión/recorte/origen -- ver
    _closest_phash_match). Degrada con gracia: si Pillow no puede decodificar
    el archivo, un GIF sin phash simplemente no participa en el matching, no
    debe impedir que se guarde."""
    try:
        from PIL import Image
        import imagehash

        with Image.open(io.BytesIO(data)) as img:
            return str(imagehash.dhash(img))
    except Exception:
        log.debug("No se pudo calcular el phash del GIF", exc_info=True)
        return None


def _phash_max_distance() -> int:
    return _env_int("GIF_PHASH_MAX_DISTANCE", 6)


def _closest_phash_match(phash: str, max_distance: int) -> tuple[str, str] | None:
    """(content_hash, r2_key) del objeto existente más parecido dentro de
    max_distance, o None si ninguno califica."""
    import imagehash

    import db  # import diferido: evita import circular (db.py importa r2)

    try:
        candidates = asyncio.run(db.get_all_gif_phashes())
    except Exception:
        log.warning(
            "No se pudieron consultar los phashes existentes de gif_objects",
            exc_info=True,
        )
        return None

    target = imagehash.hex_to_hash(phash)
    best: tuple[str, str] | None = None
    best_dist = max_distance + 1
    for content_hash, r2_key, other_phash in candidates:
        try:
            dist = target - imagehash.hex_to_hash(other_phash)
        except Exception:
            continue
        if dist <= max_distance and dist < best_dist:
            best, best_dist = (content_hash, r2_key), dist
    return best


def upload_gif_sync(url: str) -> GifUpload | None:
    """Descarga el GIF, lo identifica por el sha256 de su contenido y lo sube
    solo si ese contenido no está ya en el bucket. Retorna un GifUpload,
    GifUpload(GIF_TOO_LARGE) si supera el límite, o None en otros errores.

    Antes de subir un objeto sin match exacto, intenta un match perceptual
    (dHash) contra los objetos ya guardados: el mismo meme reposteado con
    distinta compresión/recorte cae con content_hash distinto pero suele
    tener un phash casi idéntico. Si hay match, reusa ese objeto en vez de
    subir uno nuevo -- ver GIF_PHASH_MAX_DISTANCE en limits.env.
    """
    client = get_client()
    if client is None:
        return None
    max_bytes = _env_int("MAX_GIF_DOWNLOAD_BYTES", 8 * 1024 * 1024)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; bot)"}
        resp = requests.get(url, headers=headers, timeout=15, stream=True)
        if resp.status_code != 200:
            log.error("HTTP %s al descargar GIF para R2: %s", resp.status_code, url)
            return None
        cl = resp.headers.get("Content-Length")
        if cl and int(cl) > max_bytes:
            log.debug("GIF descartado (Content-Length %s > %d): %s", cl, max_bytes, url)
            resp.close()
            return GifUpload(GIF_TOO_LARGE)
        data = resp.content
        resp.close()
        if len(data) > max_bytes:
            log.debug("GIF descartado (%d bytes > %d): %s", len(data), max_bytes, url)
            return GifUpload(GIF_TOO_LARGE)
        # Optimizar ANTES de hashear: el hash tiene que identificar los bytes
        # que efectivamente quedan en el bucket, no los que llegaron.
        data = optimize_gif_bytes(data)
        content_hash = hashlib.sha256(data).hexdigest()
        key = gif_key(content_hash)
        phash = None
        # Subir dos veces el mismo contenido a la misma key es inofensivo
        # (bytes idénticos), así que el head_object es solo para ahorrarse la
        # subida en el caso común de un repost, no un candado de concurrencia.
        if not _object_exists(client, key):
            phash = compute_phash(data)
            if phash:
                match = _closest_phash_match(phash, _phash_max_distance())
                if match:
                    match_hash, match_key = match
                    log.info(
                        "GIF casi-duplicado detectado (phash): %s reusa el objeto %s",
                        content_hash,
                        match_hash,
                    )
                    return GifUpload(
                        f"{public_url().rstrip('/')}/{match_key}", match_hash, len(data)
                    )
            client.put_object(
                Bucket=_bucket(),
                Key=key,
                Body=data,
                ContentType="image/gif",
                CacheControl="public, max-age=31536000, immutable",
            )
        return GifUpload(
            f"{public_url().rstrip('/')}/{key}", content_hash, len(data), phash
        )
    except Exception:
        log.exception("Error subiendo GIF a R2: %s", url)
        return None


def upload_image_bytes_sync(
    url: str, data: bytes, guild_id: int, ext: str
) -> str | None:
    """Sube bytes ya descargados (y validados como imagen real por el caller);
    `url` solo se usa para derivar la key y para los logs de error."""
    client = get_client()
    if client is None:
        return None
    content_type = _IMAGE_CONTENT_TYPES.get(ext.lower(), "image/png")
    try:
        key = f"{guild_id}/{hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()}{ext}"
        client.put_object(
            Bucket=_bucket(),
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
        return f"{public_url().rstrip('/')}/{key}"
    except Exception:
        log.exception("Error subiendo imagen a R2: %s", url)
        return None


_VALID_MEDIA_CONTENT_TYPES = ("image/", "video/")


def check_gif_url_health(url: str, timeout: float = 6.0) -> str:
    """Chequea un GIF guardado para la galería del panel: "ok" / "dead" /
    "unreachable". A propósito NO manda un header Referer de navegador, para
    comportarse lo más parecido posible a cómo Discord lo desempaqueta (a
    diferencia de un <img> de navegador, que sí manda el Referer que activa
    la protección anti-hotlink de muchos hosts de GIFs).

    "dead": el link está confirmado roto (404/410, o un Content-Type que no
    es de imagen/video) -- esto también le va a fallar a Discord.
    "unreachable": fallo de red o timeout puntual, no alcanza para asegurar
    que el link esté muerto (podría ser una caída transitoria del host).
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; bot)"}
    try:
        resp = requests.head(
            url, headers=headers, timeout=timeout, allow_redirects=True
        )
        if resp.status_code == 405 or not resp.headers.get("Content-Type"):
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
            resp.close()
    except Exception:
        return "unreachable"

    if resp.status_code in (404, 410):
        return "dead"
    if resp.status_code != 200:
        return "unreachable"

    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if content_type.startswith(_VALID_MEDIA_CONTENT_TYPES):
        return "ok"
    return "dead"


async def delete_key(key: str) -> None:
    """Borra un objeto de R2 por su key."""
    client = get_client()
    if client is None:
        return
    try:
        await asyncio.to_thread(client.delete_object, Bucket=_bucket(), Key=key)
    except Exception:
        log.warning("No se pudo eliminar objeto de R2: %s", key)


async def delete_url(url: str) -> None:
    """Borra un objeto de R2 si la URL le pertenece. No-op para URLs externas.

    Para GIFs con content_hash usar db.release_gif_reference: los objetos
    content-addressed son compartidos y borrarlos por URL se llevaría puestas
    las referencias de otros servidores. Esto sigue valiendo para imágenes y
    para las filas viejas anteriores a la deduplicación (key por guild, 1:1).
    """
    pub = public_url()
    if not pub or not url.startswith(pub):
        return
    await delete_key(url[len(pub.rstrip("/")) + 1 :])
