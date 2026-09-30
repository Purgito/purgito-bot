"""Cliente Cloudflare R2 con inicialización perezosa.

Tres buckets, cada uno con un rol fijo (ver Store):

- IMAGES  (R2_IMAGES_BUCKET)  imágenes de memes y subidas del editor. Público.
- GIFS    (R2_GIFS_BUCKET)    GIFs content-addressed (`gifs/xx/<sha256>.gif`). Público.
- BACKUPS (R2_BACKUP_BUCKET)  copias de bot.db. PRIVADO: no tiene URL pública.

Credenciales y endpoint (R2_ENDPOINT_URL, el de la cuenta, sin nombre de
bucket) son los mismos para los tres; lo único que cambia es el bucket. No hay
un "bucket actual" global: cada función de este módulo nombra el suyo a mano
(las de GIFs usan GIFS, las de imágenes IMAGES, las de backup BACKUPS), así que
subir un GIF al bucket de imágenes -- o al revés -- no se puede hacer por
accidente, y _put_object lo rechaza además por la forma de la key.

El cliente se crea la primera vez que se necesita; si faltan variables de
entorno el módulo igual importa sin romper nada y images_available() /
gifs_available() / backups_available() devuelven False.

Fallback legacy (TRANSITORIO). Antes había un solo bucket, configurado con
R2_BUCKET_NAME y R2_PUBLIC_URL. Mientras eso siga en el .env:

- si falta R2_IMAGES_BUCKET / R2_GIFS_BUCKET, ese store usa R2_BUCKET_NAME;
- si falta R2_IMAGES_PUBLIC_URL / R2_GIFS_PUBLIC_URL, usa R2_PUBLIC_URL;
- R2_PUBLIC_URL además se sigue reconociendo como alias de las URLs que ya
  están guardadas en la DB (todas apuntan al host viejo hasta que corra
  `scripts/migrate_r2_buckets.py rewrite-db-urls`).

El bucket de backups NO tiene fallback: nunca cae en el bucket viejo. El
fallback se va solo al borrar las dos variables legacy del .env; bot.py avisa
al arrancar mientras sigan definidas (config_warnings). Ver DEPLOY.md
§ "Migrar a tres buckets de R2".
"""

import asyncio
import contextlib
import hashlib
import io
import ipaddress
import logging
import os
import socket
import subprocess
import threading
import time
from typing import NamedTuple
from urllib.parse import urljoin, urlparse

import requests

log = logging.getLogger(__name__)

_client = None
_checked = False


class Store(NamedTuple):
    """Un bucket de R2 y el rol que cumple. `public_var` es None en los
    buckets privados: no existe una URL pública para construir."""

    role: str
    bucket_var: str
    public_var: str | None = None


IMAGES = Store("images", "R2_IMAGES_BUCKET", "R2_IMAGES_PUBLIC_URL")
GIFS = Store("gifs", "R2_GIFS_BUCKET", "R2_GIFS_PUBLIC_URL")
BACKUPS = Store("backups", "R2_BACKUP_BUCKET")

# Variables del esquema de un solo bucket. Solo las lee el fallback de
# bucket_for/public_base y scripts/migrate_r2_buckets.py (como origen).
LEGACY_BUCKET_VAR = "R2_BUCKET_NAME"
LEGACY_PUBLIC_VAR = "R2_PUBLIC_URL"

# Sentinel: el GIF supera el límite de tamaño (no guardar en DB, no reintentar).
GIF_TOO_LARGE = ""

# Cache-Control de los objetos subidos a R2/Cloudflare. Antes 1 año -- para
# contenido content-addressed (la misma key siempre es el mismo contenido)
# tiene sentido cachear agresivo, pero un año es demasiada ventana en la que
# un objeto ya borrado (bloqueo manual, chequeo de salud, wipe) podría seguir
# sirviéndose desde el edge de Cloudflare como si nada. 14 días como punto
# medio: sigue siendo agresivo para el contenido que efectivamente sigue
# vivo (la inmensa mayoría), pero acota la ventana de "borrado que no borra
# de verdad" a algo razonable en vez de a un año. `immutable` se mantiene:
# sigue siendo cierto que la MISMA key nunca cambia de contenido mientras el
# objeto exista, eso no depende de max-age.
_CACHE_CONTROL = "public, max-age=1209600, immutable"


class GifFingerprint(NamedTuple):
    """Huella estructural completa de un GIF, para detectar casi-duplicados
    (mismo meme reposteado con distinta compresión/recorte) sin arriesgar
    falsos positivos entre GIFs de contenido distinto.

    frame_count/width/height/duration_ms son señales baratas que descartan
    la enorme mayoría de los no-duplicados antes de mirar el contenido
    visual -- dos animaciones distintas casi nunca comparten las cuatro a
    la vez. `phashes` son los dHash (hex) de hasta 3 frames muestreados
    (primero, medio, último): comparar varios puntos de la animación, no
    solo el primero, es lo que evita que dos GIFs distintos con un
    fotograma inicial parecido (mismo template de meme, mismo thumbnail de
    video) se confundan entre sí -- ver _closest_fingerprint_match.
    """

    frame_count: int
    width: int
    height: int
    duration_ms: int
    phashes: tuple[str, ...]


class GifUpload(NamedTuple):
    """Resultado de subir un GIF a R2.

    `url` == GIF_TOO_LARGE ('') significa que el archivo superaba el límite.
    `content_hash` es el sha256 de los bytes que efectivamente se subieron:
    es la identidad del objeto en el bucket y lo que usa db.gif_objects para
    contar referencias.
    `fingerprint` es la huella perceptual de los bytes locales, calculada
    solo cuando no hubo match exacto (ver upload_gif_sync); el caller lo pasa
    a db.save_gif_url para que quede guardado si el objeto es nuevo de verdad.
    """

    url: str
    content_hash: str = ""
    size_bytes: int = 0
    fingerprint: GifFingerprint | None = None


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


def _list_keys_sync(store: Store, prefix: str) -> list[tuple[str, int, object]]:
    """(key, tamaño, fecha de modificación) de los objetos de `store` bajo un
    prefijo.

    Pagina la respuesta y solo devuelve metadata; el contenido no se baja.
    """
    client = get_client()
    bucket = bucket_for(store)
    if client is None or not bucket:
        return []
    out = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            out.append((obj["Key"], obj["Size"], obj.get("LastModified")))
    return out


def list_gif_keys_sync(prefix: str) -> list[tuple[str, int, object]]:
    """Objetos del bucket de GIFs bajo un prefijo (ver _list_keys_sync)."""
    return _list_keys_sync(GIFS, prefix)


_IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def bucket_for(store: Store, *, legacy: bool = True) -> str:
    """Nombre del bucket de `store`, o "" si no está configurado.

    Con legacy=True (default) IMAGES y GIFS caen en R2_BUCKET_NAME mientras su
    variable propia esté vacía -- el fallback transitorio del docstring del
    módulo. BACKUPS nunca cae en nada: si R2_BACKUP_BUCKET falta, no hay
    bucket de backups. legacy=False lee solo la variable propia (lo usa el
    script de migración, que tiene que distinguir origen de destino)."""
    name = _env(store.bucket_var)
    if name or not legacy or store is BACKUPS:
        return name
    return _env(LEGACY_BUCKET_VAR)


def public_base(store: Store, *, legacy: bool = True) -> str:
    """URL pública de `store` sin barra final, o "" si no está configurada.

    Levanta ValueError para un bucket privado (BACKUPS): pedirle una URL
    pública es un error de programación, no una configuración faltante."""
    if store.public_var is None:
        raise ValueError(f"el bucket '{store.role}' es privado: no tiene URL pública")
    url = _env(store.public_var)
    if not url and legacy:
        url = _env(LEGACY_PUBLIC_VAR)
    return url.rstrip("/")


def public_images_url() -> str:
    """Base pública de las imágenes (R2_IMAGES_PUBLIC_URL), sin barra final."""
    return public_base(IMAGES)


def public_gifs_url() -> str:
    """Base pública de los GIFs (R2_GIFS_PUBLIC_URL), sin barra final."""
    return public_base(GIFS)


def _public_bases(store: Store) -> tuple[str, ...]:
    """Bases públicas que identifican una URL como de `store`: la propia y,
    mientras R2_PUBLIC_URL siga definida, la vieja (las filas guardadas antes
    de la migración la llevan). La primera es la que se usa para construir
    URLs nuevas."""
    bases = (public_base(store), _env(LEGACY_PUBLIC_VAR).rstrip("/"))
    return tuple(dict.fromkeys(b for b in bases if b))


def gif_public_bases() -> tuple[str, ...]:
    return _public_bases(GIFS)


def image_public_bases() -> tuple[str, ...]:
    return _public_bases(IMAGES)


def _key_from_url(store: Store, url) -> str | None:
    """Key del objeto si `url` pertenece al bucket público de `store`, None si
    es externa (tenor, giphy, Discord CDN...). Las keys bajo `gifs/` son
    siempre de GIFs: el bucket de imágenes no las reconoce ni por el alias
    legacy, donde las dos familias comparten host."""
    if not isinstance(url, str):
        return None
    for base in _public_bases(store):
        prefix = base + "/"
        if url.startswith(prefix) and len(url) > len(prefix):
            key = url[len(prefix) :]
            if store is IMAGES and key.startswith(GIF_KEY_PREFIX):
                return None
            return key
    return None


def gif_key_from_url(url) -> str | None:
    return _key_from_url(GIFS, url)


def image_key_from_url(url) -> str | None:
    return _key_from_url(IMAGES, url)


def get_client():
    """Cliente S3 compartido: mismas credenciales y endpoint para los tres
    buckets. No depende de ningún bucket -- qué bucket se usa lo decide cada
    llamada (bucket_for)."""
    global _client, _checked
    if not _checked:
        _checked = True
        endpoint = _env("R2_ENDPOINT_URL")
        key_id = _env("R2_ACCESS_KEY_ID")
        secret = _env("R2_SECRET_ACCESS_KEY")
        if endpoint and key_id and secret:
            try:
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
            except Exception:
                _client = None
    return _client


def _store_ready(store: Store) -> bool:
    """Hay cliente, bucket y (si el bucket es público) URL pública. Sin la URL
    no se puede armar el link que se guarda en la DB, así que una subida
    "exitosa" dejaría una fila rota: es mejor degradar a "R2 no disponible"."""
    if get_client() is None or not bucket_for(store):
        return False
    return store.public_var is None or bool(public_base(store))


def images_available() -> bool:
    return _store_ready(IMAGES)


def gifs_available() -> bool:
    return _store_ready(GIFS)


def backups_available() -> bool:
    return _store_ready(BACKUPS)


def legacy_vars_set() -> list[str]:
    """Variables del esquema viejo que siguen definidas. Vacía == ya no queda
    ninguna dependencia: es lo que hay que conseguir antes de borrar el bucket
    viejo (ver DEPLOY.md)."""
    return [v for v in (LEGACY_BUCKET_VAR, LEGACY_PUBLIC_VAR) if _env(v)]


def config_warnings() -> list[str]:
    """Problemas de configuración de R2, listos para loguear al arrancar.
    Lista vacía == todo en orden (los backups son opcionales y no entran:
    solo los usa el cron de deploy/backup_db.sh)."""
    if get_client() is None:
        return [
            "R2 no configurado: las imágenes de Discord CDN se guardarán con su URL "
            "original (pueden expirar). Configura R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_IMAGES_BUCKET, R2_IMAGES_PUBLIC_URL, "
            "R2_GIFS_BUCKET y R2_GIFS_PUBLIC_URL para persistencia permanente."
        ]
    out = []
    for store in (IMAGES, GIFS):
        if not _store_ready(store):
            out.append(
                f"R2 ({store.role}): falta {store.bucket_var} o {store.public_var}; "
                f"ese tipo de archivo se guardará con su URL original."
            )
    legacy = legacy_vars_set()
    if legacy:
        out.append(
            f"R2: {' y '.join(legacy)} siguen definidas (esquema de un solo bucket). "
            "Se usan solo como fallback mientras se migra; borrarlas del .env al "
            "terminar (DEPLOY.md § Migrar a tres buckets de R2)."
        )
    return out


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


def _gif_object_exists(client, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket_for(GIFS), Key=key)
        return True
    except Exception:
        return False


def _put_object(store: Store, key: str, data: bytes, content_type: str) -> None:
    """put_object sobre un bucket PÚBLICO (imágenes o GIFs), con el mismo
    Cache-Control para ambos. Rechaza una key que no corresponde al bucket:
    las de `gifs/` son solo de GIFs y todo lo demás solo de imágenes. La
    subida ya elige el bucket por su cuenta; esto es la segunda llave -- una
    key cruzada por un bug futuro falla acá en vez de ensuciar el otro
    bucket sin que nadie se entere."""
    if store not in (IMAGES, GIFS):
        raise ValueError(
            f"_put_object es solo para buckets públicos, no '{store.role}'"
        )
    is_gif_key = key.startswith(GIF_KEY_PREFIX)
    if (store is GIFS) != is_gif_key:
        raise ValueError(f"la key {key!r} no corresponde al bucket '{store.role}'")
    client = get_client()
    if client is None:
        raise RuntimeError("R2 no está configurado")
    client.put_object(
        Bucket=bucket_for(store),
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl=_CACHE_CONTROL,
    )


# Tolerancias de las señales estructurales baratas (frame_count, aspect
# ratio, duración) que tienen que coincidir ANTES de siquiera mirar el
# contenido visual -- ver _fingerprints_compatible. No son configurables:
# ensancharlas reabre la puerta a fusionar contenido distinto entre
# servidores, que es exactamente lo que este esquema existe para impedir.
_ASPECT_RATIO_TOLERANCE = 0.02
_DURATION_TOLERANCE = 0.10


def compute_gif_fingerprint(data: bytes) -> GifFingerprint | None:
    """Huella estructural completa del GIF (frame_count, dimensiones,
    duración total y dHash de varios frames muestreados), para detectar
    casi-duplicados sin arriesgar falsos positivos -- ver
    _closest_fingerprint_match. Degrada con gracia: si Pillow no puede
    decodificar el archivo, un GIF sin fingerprint simplemente no participa
    en el matching, no debe impedir que se guarde."""
    try:
        from PIL import Image
        import imagehash

        # Rechaza imágenes descomprimidas gigantes (decompression bomb) antes
        # de decodificar -- mismo valor y motivo que meme_generator.py.
        # Repetido a propósito (no importado desde ahí): esto no puede
        # depender de que algún OTRO módulo se haya importado antes para
        # tener efecto -- Image.MAX_IMAGE_PIXELS es un global del proceso,
        # así que fijarlo acá también es idempotente y no pisa nada.
        Image.MAX_IMAGE_PIXELS = 15_000_000
        # formats=("GIF",): data llega de una URL de host confiable (CDN de
        # Discord/Tenor/Giphy, ya validado por el caller), pero el HOST
        # confiable no garantiza que el contenido en esa URL sea realmente
        # un GIF -- sin esto, Image.open() prueba cualquier formato que
        # Pillow sepa leer (TIFF, ICO, EPS, etc.) contra esos bytes.
        with Image.open(io.BytesIO(data), formats=("GIF",)) as img:
            width, height = img.size
            frame_count = int(img.n_frames)
            if frame_count < 1:
                return None
            duration_ms = 0
            for i in range(frame_count):
                img.seek(i)
                duration_ms += int(img.info.get("duration", 0) or 0)
            # Primero, medio y último -- de menor a mayor cantidad de frames
            # únicos según el largo real de la animación (1, 2 o 3 índices).
            sample_indices = sorted({0, frame_count // 2, frame_count - 1})
            phashes = []
            for idx in sample_indices:
                img.seek(idx)
                phashes.append(str(imagehash.dhash(img.convert("RGB"))))
        return GifFingerprint(
            frame_count=frame_count,
            width=width,
            height=height,
            duration_ms=duration_ms,
            phashes=tuple(phashes),
        )
    except Exception:
        log.debug("No se pudo calcular el fingerprint del GIF", exc_info=True)
        return None


def _phash_max_distance() -> int:
    return _env_int("GIF_PHASH_MAX_DISTANCE", 4)


def _fingerprints_compatible(a: GifFingerprint, b: GifFingerprint) -> bool:
    """Filtro barato ANTES de comparar contenido visual: dos animaciones
    distintas casi nunca coinciden en frame_count, aspect ratio y duración
    total a la vez, así que exigir las tres reduce drásticamente el espacio
    de candidatos que llegan a la comparación por dHash (y con eso, la
    chance de una coincidencia accidental).

    Un GIF de un solo frame (imagen estática) nunca califica para matching
    perceptual, sin excepción: con frame_count=1 no hay "medio" ni "último"
    frame que muestrear (los tres índices colapsan al mismo), y duration_ms
    es 0 para prácticamente cualquier estático -- las dos señales que hacen
    fuerte a este esquema para GIFs animados no discriminan nada acá, y
    quedaría reducido a un solo dHash con un umbral laxo, exactamente el
    esquema viejo que causó el bug real. Dos estáticos solo se consideran
    "el mismo" si son bit a bit idénticos (dedup exacto por content_hash)."""
    if a.frame_count == 1 or b.frame_count == 1:
        return False
    if a.frame_count != b.frame_count or len(a.phashes) != len(b.phashes):
        return False
    if a.width <= 0 or a.height <= 0 or b.width <= 0 or b.height <= 0:
        return False
    ratio_a = a.width / a.height
    ratio_b = b.width / b.height
    if abs(ratio_a - ratio_b) / ratio_a > _ASPECT_RATIO_TOLERANCE:
        return False
    longest_duration = max(a.duration_ms, b.duration_ms, 1)
    if abs(a.duration_ms - b.duration_ms) / longest_duration > _DURATION_TOLERANCE:
        return False
    return True


def fingerprint_distance(
    a: GifFingerprint, b: GifFingerprint, max_distance: int
) -> int | None:
    """Distancia total entre dos fingerprints si califican como
    casi-duplicado, o None si no.

    Calificar exige pasar _fingerprints_compatible (misma duración/forma/
    cantidad de frames) Y que los dHash coincidan de a pares (primero con
    primero, medio con medio, último con último) con TODOS por debajo de
    max_distance -- no alcanza con que uno de los frames muestreados sea
    parecido, tienen que serlo todos. Esa combinación (estructura idéntica +
    contenido visual idéntico en varios puntos de la animación) es
    deliberadamente exigente: la única forma barata de garantizar que nunca
    se confunden dos GIFs de contenido distinto.

    Único lugar donde vive este criterio -- lo comparten el matching en
    caliente (_closest_fingerprint_match, contra un solo candidato a la vez)
    y el clustering offline (scripts/backfill_gif_phashes.py, todos contra
    todos) para que nunca puedan divergir en qué cuenta como "el mismo GIF".
    """
    if not _fingerprints_compatible(a, b):
        return None
    import imagehash

    total = 0
    for hash_a, hash_b in zip(a.phashes, b.phashes):
        try:
            dist = imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)
        except Exception:
            return None
        if dist > max_distance:
            return None
        total += dist
    return total


def _closest_fingerprint_match(
    fingerprint: GifFingerprint, max_distance: int
) -> tuple[str, str] | None:
    """(content_hash, r2_key) del objeto existente más parecido dentro de
    max_distance (ver fingerprint_distance), o None si ninguno califica."""
    import db  # import diferido: evita import circular (db.py importa r2)

    try:
        candidates = asyncio.run(db.get_all_gif_fingerprints())
    except Exception:
        log.warning(
            "No se pudieron consultar los fingerprints existentes de gif_objects",
            exc_info=True,
        )
        return None

    best: tuple[str, str] | None = None
    best_total_dist: int | None = None
    for content_hash, r2_key, other in candidates:
        total_dist = fingerprint_distance(fingerprint, other, max_distance)
        if total_dist is None:
            continue
        if best is None or total_dist < best_total_dist:
            best, best_total_dist = (content_hash, r2_key), total_dist
    return best


def _public_ip_for_host(hostname: str) -> str | None:
    """Resuelve `hostname` y devuelve la primera IP que sea públicamente
    enrutable, o None si ninguna lo es (localhost, LAN, link-local,
    endpoints de metadata de cloud, etc.) -- defensa SSRF.

    No hay ruta explotable hoy (el único caller real ya valida el hostname
    exacto contra cdn.discordapp.com antes de llegar acá), pero es barato y
    cubre a un caller futuro menos cuidadoso."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            return ip
    return None


# Serializa las descargas que pinnean DNS: socket.getaddrinfo es un global
# del proceso, así que parchearlo sin lock correría el riesgo de que dos
# descargas concurrentes en threads distintos se pisen el parche entre sí.
# ponytail: lock global en vez de pinning por-conexión (requeriría un
# HTTPAdapter/SSLContext a medida) -- las descargas de GIF no son un path de
# alto throughput, así que serializar esto no es un cuello de botella real.
_dns_pin_lock = threading.Lock()


@contextlib.contextmanager
def _pinned_dns(hostname: str, ip: str):
    """Fija la resolución de `hostname` a la IP ya validada como pública,
    durante el bloque. Sin esto, `requests` volvería a resolver el hostname
    por su cuenta al conectar -- una ventana de milisegundos después de la
    validación en la que un DNS rebinding attack (el mismo hostname resuelve
    distinto la segunda vez) haría inútil el chequeo de arriba."""
    real_getaddrinfo = socket.getaddrinfo

    def _pinned(host, *args, **kwargs):
        return real_getaddrinfo(ip if host == hostname else host, *args, **kwargs)

    with _dns_pin_lock:
        socket.getaddrinfo = _pinned
        try:
            yield
        finally:
            socket.getaddrinfo = real_getaddrinfo


class BlockedTarget(Exception):
    """La URL (o alguno de sus redirects) apunta a una IP no pública."""


# Los redirects de un host de GIFs son normales (media.tenor.com reparte a su
# CDN), así que cortarlos de plano rompería links legítimos. Se siguen a mano
# para poder validar CADA salto: con allow_redirects=True, requests resuelve y
# conecta por su cuenta y el chequeo de IP pública solo cubriría el primer
# host.
_MAX_REDIRECTS = 5
_REDIRECT_CODES = (301, 302, 303, 307, 308)


def fetch_public_url(method, url: str, **kwargs):
    """requests.get/head con el filtro SSRF puesto en todos los saltos.

    Levanta BlockedTarget si algún host de la cadena no resuelve a una IP
    públicamente enrutable (localhost, LAN, link-local, metadata de cloud) o
    si la cadena de redirects se pasa de _MAX_REDIRECTS.
    """
    for _ in range(_MAX_REDIRECTS + 1):
        hostname = urlparse(url).hostname or ""
        ip = _public_ip_for_host(hostname)
        if ip is None:
            raise BlockedTarget(url)
        with _pinned_dns(hostname, ip):
            resp = method(url, allow_redirects=False, **kwargs)
        location = resp.headers.get("Location")
        if resp.status_code in _REDIRECT_CODES and location:
            resp.close()
            url = urljoin(url, location)
            continue
        return resp
    raise BlockedTarget(url)


class FetchLimitExceeded(Exception):
    """La respuesta superó el tope de bytes o el tiempo total permitido."""


def _read_available(resp, size: int = 65536) -> bytes:
    """Lee lo que haya llegado (hasta `size` bytes) SIN esperar a llenar el
    chunk. `iter_content(65536)` bloquea hasta juntar 64 KiB o el cierre, así
    que contra un servidor que gotea un byte por vez el chequeo de tiempo
    total de fetch_public_bytes nunca llegaba a correr. read1 (urllib3 >= 2)
    devuelve apenas hay datos, y b"" solo al terminar el cuerpo. Con un
    urllib3 viejo sin read1 se cae a chunks chicos: menos preciso, pero acota
    cuánto puede colgarse una lectura."""
    read1 = getattr(resp.raw, "read1", None)
    if read1 is not None:
        return read1(size, decode_content=True)
    return resp.raw.read(1024, decode_content=True)


def fetch_public_bytes(
    url: str, max_bytes: int, *, total_timeout: float = 30.0, **kwargs
) -> bytes:
    """GET con filtro SSRF en todos los saltos (fetch_public_url) y con tope
    de tamaño y de tiempo total: para URLs que escribe un admin (feeds RSS,
    páginas de canal) y cuyo cuerpo se parsea entero en memoria.

    `timeout` de requests es por lectura, no total: un servidor que gotea un
    byte cada pocos segundos lo respeta para siempre y deja el thread colgado,
    así que el tiempo total se controla acá, chunk a chunk.

    Levanta requests.HTTPError (con `.response`, igual que raise_for_status)
    ante un status >= 400, BlockedTarget si algún salto no es público y
    FetchLimitExceeded si se pasa del tope. Los callers que ya distinguían un
    404 de otros errores siguen funcionando igual."""
    deadline = time.monotonic() + total_timeout
    resp = fetch_public_url(requests.get, url, stream=True, **kwargs)
    try:
        resp.raise_for_status()
        declared = resp.headers.get("Content-Length", "")
        if declared.isdigit() and int(declared) > max_bytes:
            raise FetchLimitExceeded(url)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = _read_available(resp)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > max_bytes or time.monotonic() > deadline:
                raise FetchLimitExceeded(url)
            chunks.append(chunk)
    finally:
        resp.close()


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
    if not gifs_available():
        return None
    max_bytes = _env_int("MAX_GIF_DOWNLOAD_BYTES", 8 * 1024 * 1024)
    hostname = urlparse(url).hostname or ""
    ip = _public_ip_for_host(hostname)
    if ip is None:
        log.warning("GIF descartado (host no resuelve a una IP pública): %s", url)
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; bot)"}
        # allow_redirects=False: la key de este link ya se validó como
        # cdn.discordapp.com en el caller (ver cogs/gifs.py) ANTES de llegar
        # acá -- si se siguiera un redirect, ese chequeo de host quedaría sin
        # efecto para el destino real de la descarga.
        # _pinned_dns: fija la conexión a la IP ya validada arriba, para que
        # un DNS rebinding (el hostname resuelve distinto entre el chequeo y
        # la conexión real) no evada el filtro de IP pública.
        with _pinned_dns(hostname, ip):
            resp = requests.get(
                url, headers=headers, timeout=15, stream=True, allow_redirects=False
            )
        if resp.status_code != 200:
            log.warning("HTTP %s al descargar GIF para R2: %s", resp.status_code, url)
            return None
        cl = resp.headers.get("Content-Length")
        if cl and int(cl) > max_bytes:
            log.debug("GIF descartado (Content-Length %s > %d): %s", cl, max_bytes, url)
            resp.close()
            return GifUpload(GIF_TOO_LARGE)
        # No confiar solo en Content-Length -- puede faltar o mentir. Se lee
        # en chunks y se corta apenas se supera el límite, en vez de
        # bufferear con resp.content (que junta el cuerpo entero en memoria
        # antes de que el chequeo de tamaño de abajo pueda actuar).
        chunks: list[bytes] = []
        total = 0
        too_large = False
        for chunk in resp.iter_content(chunk_size=262144):
            total += len(chunk)
            if total > max_bytes:
                too_large = True
                break
            chunks.append(chunk)
        resp.close()
        if too_large:
            log.debug("GIF descartado (>%d bytes en el cuerpo): %s", max_bytes, url)
            return GifUpload(GIF_TOO_LARGE)
        data = b"".join(chunks)
        return upload_gif_bytes_sync(data)
    except Exception:
        log.exception("Error subiendo GIF a R2: %s", url)
        return None


def upload_gif_bytes_sync(data: bytes) -> GifUpload | None:
    """Optimiza bytes de GIF con gifsicle, calcula sha256 y fingerprint,
    y los sube a R2 si no existe ya un objeto con ese contenido o similar.
    Retorna un GifUpload, GifUpload(GIF_TOO_LARGE) si supera el límite, o None en error."""
    client = get_client()
    if client is None or not gifs_available():
        return None
    max_bytes = _env_int("MAX_GIF_DOWNLOAD_BYTES", 8 * 1024 * 1024)
    if len(data) > max_bytes:
        return GifUpload(GIF_TOO_LARGE)
    try:
        # Optimizar ANTES de hashear: el hash tiene que identificar los bytes
        # que efectivamente quedan en el bucket, no los que llegaron.
        data = optimize_gif_bytes(data)
        content_hash = hashlib.sha256(data).hexdigest()
        key = gif_key(content_hash)
        fingerprint = None
        # Subir dos veces el mismo contenido a la misma key es inofensivo
        # (bytes idénticos), así que el head_object es solo para ahorrarse la
        # subida en el caso común de un repost, no un candado de concurrencia.
        if not _gif_object_exists(client, key):
            fingerprint = compute_gif_fingerprint(data)
            if fingerprint:
                match = _closest_fingerprint_match(fingerprint, _phash_max_distance())
                if match:
                    match_hash, match_key = match
                    log.info(
                        "GIF casi-duplicado detectado (fingerprint): %s reusa el objeto %s",
                        content_hash,
                        match_hash,
                    )
                    return GifUpload(
                        f"{public_gifs_url()}/{match_key}", match_hash, len(data)
                    )
            _put_object(GIFS, key, data, "image/gif")
        return GifUpload(
            f"{public_gifs_url()}/{key}", content_hash, len(data), fingerprint
        )
    except Exception:
        log.exception("Error subiendo bytes de GIF a R2")
        return None


def get_gif_bytes_sync(key: str) -> bytes | None:
    """Lee los bytes de un objeto del bucket de GIFs vía el cliente S3."""
    client = get_client()
    bucket = bucket_for(GIFS)
    if client is None or not bucket:
        return None
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except Exception:
        log.debug("No se pudo leer objeto de R2: %s", key, exc_info=True)
        return None


def upload_image_bytes_sync(
    url: str, data: bytes, guild_id: int, ext: str
) -> str | None:
    """Sube bytes ya descargados (y validados como imagen real por el caller)
    al bucket de imágenes; `url` solo se usa para derivar la key y para los
    logs de error. Una imagen .gif va acá igual: el bucket de GIFs es solo
    para los GIFs del pool (keys `gifs/...`), no para cualquier archivo .gif."""
    if not images_available():
        return None
    content_type = _IMAGE_CONTENT_TYPES.get(ext.lower(), "image/png")
    try:
        key = f"{guild_id}/{hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()}{ext}"
        _put_object(IMAGES, key, data, content_type)
        return f"{public_images_url()}/{key}"
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

    Sale por fetch_public_url, no por requests directo: acá llegan `url` y
    sobre todo `media_url`, que la resuelve un oEmbed de terceros, y el
    resultado tri-estado se le devuelve al panel -- sin el filtro esto era un
    oráculo para sondear la red interna del droplet salto por salto.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; bot)"}
    try:
        resp = fetch_public_url(requests.head, url, headers=headers, timeout=timeout)
        # Algunos CDNs (como Tenor para URLs directas /m/...gif) responden con 404/405 a peticiones HEAD,
        # pero responden 200 OK con Content-Type image/gif a peticiones GET. Si HEAD no devuelve 200 o no
        # trae Content-Type, intentamos un GET con stream=True antes de clasificar el recurso.
        if resp.status_code != 200 or not resp.headers.get("Content-Type"):
            resp = fetch_public_url(
                requests.get, url, headers=headers, timeout=timeout, stream=True
            )
            resp.close()
    except BlockedTarget:
        # "unreachable" y no "dead" a propósito: _public_ip_for_host también
        # devuelve None cuando el DNS falla, y "dead" acumula strikes que
        # terminan borrando el GIF (_DEAD_STREAK_THRESHOLD). Una caída de DNS
        # no debe vaciarle el corpus a nadie -- para frenar el SSRF alcanza
        # con no haber hecho el request.
        log.warning("Chequeo de salud descartado (destino no público): %s", url)
        return "unreachable"
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


async def _delete_key(store: Store, key: str) -> None:
    """Borra un objeto de `store` por su key."""
    client = get_client()
    bucket = bucket_for(store)
    if client is None or not bucket:
        return
    try:
        await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=key)
    except Exception:
        log.warning("No se pudo eliminar objeto de R2 (%s): %s", store.role, key)


async def delete_gif_key(key: str) -> None:
    """Borra un objeto del bucket de GIFs por su key."""
    await _delete_key(GIFS, key)


async def delete_gif_url(url: str) -> None:
    """Borra un GIF del bucket de GIFs si la URL le pertenece. No-op para URLs
    externas (tenor, giphy, Discord CDN).

    Para GIFs con content_hash usar db.release_gif_reference: los objetos
    content-addressed son compartidos y borrarlos por URL se llevaría puestas
    las referencias de otros servidores. Esto sigue valiendo para las filas
    viejas anteriores a la deduplicación (key por guild, 1:1).
    """
    key = gif_key_from_url(url)
    if key:
        await _delete_key(GIFS, key)


async def delete_image_url(url: str) -> None:
    """Borra una imagen del bucket de imágenes si la URL le pertenece. No-op
    para URLs externas. Las imágenes son 1:1 por guild (key con `{guild_id}/`
    de prefijo), así que no hay referencias compartidas que proteger."""
    key = image_key_from_url(url)
    if key:
        await _delete_key(IMAGES, key)


# ─── Backups (bucket PRIVADO) ─────────────────────────────────────────────────
#
# A diferencia del resto del módulo, estas funciones LEVANTAN excepción: el que
# las llama (scripts/r2_backup.py, desde deploy/backup_db.sh) tiene que enterarse
# de que la copia remota no quedó -- un backup que solo existe en el disco de la
# instancia no protege contra perder la instancia, que es justo para lo que está
# el bucket. Nada de acá construye URLs: el bucket no tiene URL pública y no hay
# que dársela (ni Development URL ni dominio). Se lee y se escribe solo con el
# token S3.


class BackupError(Exception):
    """No se pudo subir, listar o bajar un backup."""


def _backup_client_and_bucket():
    client = get_client()
    bucket = bucket_for(BACKUPS)
    if client is None:
        raise BackupError(
            "R2 no está configurado (faltan R2_ENDPOINT_URL, R2_ACCESS_KEY_ID "
            "o R2_SECRET_ACCESS_KEY)"
        )
    if not bucket:
        raise BackupError("falta R2_BACKUP_BUCKET")
    return client, bucket


def upload_backup_file_sync(path: str, key: str | None = None) -> str:
    """Sube un archivo al bucket de backups y devuelve la key (por default el
    nombre del archivo, el mismo que tiene en BACKUP_DIR: `bot-<fecha>.db`).

    Verifica después de subir -- head_object contra el tamaño y el sha256
    locales -- en vez de confiar en que put_object no levantó nada. Un put
    exitoso con un cuerpo truncado por el camino sería un backup que parece
    estar y no sirve. Sin CacheControl ni ContentDisposition: no es contenido
    para servir, y el bucket no tiene cómo servirlo."""
    client, bucket = _backup_client_and_bucket()
    key = key or os.path.basename(path)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise BackupError(f"no se pudo leer {path}: {e}") from e
    digest = hashlib.sha256(data).hexdigest()
    try:
        # Cuerpo en memoria y no upload_file: es el mismo camino que ya usan las
        # subidas de GIFs/imágenes (put_object con bytes), y el de streaming con
        # checksum en trailer es el que R2 viene rechazando en boto3 nuevos. Una
        # copia de bot.db cabe de sobra; el tope de un PUT simple es 5 GiB.
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="application/octet-stream",
            Metadata={"sha256": digest},
        )
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception as e:
        raise BackupError(f"falló la subida de {key} a R2: {e}") from e
    if head.get("ContentLength") != len(data):
        raise BackupError(
            f"{key}: el objeto quedó de {head.get('ContentLength')} bytes en R2 "
            f"y el archivo local tiene {len(data)}"
        )
    return key


def list_backups_sync() -> list[tuple[str, int, object]]:
    """(key, tamaño, fecha) de los backups del bucket, del más viejo al más
    nuevo. Los nombres llevan la fecha (`bot-YYYYMMDD-HHMMSS`), así que el
    orden alfabético es el cronológico."""
    client, bucket = _backup_client_and_bucket()
    try:
        out = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                out.append((obj["Key"], obj["Size"], obj.get("LastModified")))
    except Exception as e:
        raise BackupError(f"no se pudo listar el bucket de backups: {e}") from e
    return sorted(out)


def download_backup_sync(key: str, dest_path: str) -> str:
    """Baja un backup a `dest_path` (0600: lleva lo mismo que bot.db) y comprueba
    el sha256 que guardó la subida, si el objeto lo trae."""
    client, bucket = _backup_client_and_bucket()
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()
    except Exception as e:
        raise BackupError(f"no se pudo bajar {key}: {e}") from e
    expected = (resp.get("Metadata") or {}).get("sha256")
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise BackupError(
            f"{key}: el sha256 de lo bajado no coincide con el de la subida"
        )
    fd = os.open(dest_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return dest_path
