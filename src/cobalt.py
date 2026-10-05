"""Cliente de una instancia PROPIA de cobalt (https://github.com/imputnet/cobalt).

Respaldo de "!dl" (cogs/download.py): se prueba solo cuando yt-dlp falló con un
link que ya pasó la allowlist de hosts, y solo si hay COBALT_API_URL. Sin esa
variable `configured()` es False y nada de esto corre.

La instancia pública (api.cobalt.tools) NO se puede usar acá: su documentación
la reserva para su propia web y pide permiso explícito para otros proyectos.
Por eso el bot espera una instancia autoalojada, normalmente en loopback
(DEPLOY.md § cobalt). Es un servicio aparte al que se le habla por HTTP, así
que la AGPL de cobalt no alcanza al código de este repo.

El flujo es el de la API documentada: `POST /` con la URL devuelve un JSON con
`status`. Con `alwaysProxy` casi todo llega como `tunnel` (cobalt sirve el
archivo en `GET /tunnel`); `redirect` y `picker` se manejan igual por si
alguno aparece. Dos decisiones de seguridad:

- Un `tunnel` se descarga SIEMPRE de COBALT_API_URL, nunca del host que diga la
  respuesta: cobalt arma esa URL con su `API_URL`, que en una instancia pública
  es otro host, y no hay motivo para confiar en uno que no configuró el
  operador del bot.
- Cualquier otra URL (un `redirect`, el item de un `picker`) apunta a un sitio
  de terceros, así que pasa por r2.fetch_public_url, el mismo filtro SSRF que
  usa r2.py para las URLs de imágenes.

Cobalt no informa si el contenido es sensible, así que `!dl` no puede aplicarle
el filtro de canal NSFW que sí aplica con el `age_limit` de yt-dlp (ver
cogs/download.py).
"""

import logging
import os
import shutil
import tempfile
import time
from urllib.parse import urlparse

import requests

import r2
from config import COBALT_API_KEY, COBALT_API_URL

log = logging.getLogger(__name__)

# 720p y no el default (1080p) de cobalt: es un archivo para subir a Discord,
# donde el tope de tamaño manda más que la resolución.
_VIDEO_QUALITY = "720"
# (conexión, lectura) del POST: cobalt resuelve el link antes de responder.
_API_TIMEOUT = (5, 30)
# (conexión, lectura entre chunks) de la descarga, y tope de tiempo total.
_FETCH_TIMEOUT = (5, 30)
_DOWNLOAD_DEADLINE_SECONDS = 60
_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".gif"}
_PICKER_VIDEO_TYPES = {"video", "gif"}


class CobaltError(Exception):
    """Cobalt no pudo darnos el video (error de su API, sin red, respuesta
    rara, archivo vacío...)."""


class CobaltTooLarge(Exception):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes


class CobaltNoVideo(Exception):
    """El link es válido pero cobalt solo encontró fotos (un `picker` sin
    ningún video adentro)."""


def configured() -> bool:
    parsed = urlparse(COBALT_API_URL)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "purgito-bot",
    }
    if COBALT_API_KEY:
        headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"
    return headers


def _request_media(url: str) -> dict:
    resp = requests.post(
        f"{COBALT_API_URL}/",
        json={
            "url": url,
            "videoQuality": _VIDEO_QUALITY,
            "downloadMode": "auto",
            "alwaysProxy": True,
        },
        headers=_headers(),
        timeout=_API_TIMEOUT,
    )
    # Cobalt responde los errores de contenido con un JSON de status "error"
    # (a veces con un 4xx), así que se lee el cuerpo antes de mirar el código.
    try:
        data = resp.json()
    except ValueError as e:
        raise CobaltError(f"respuesta no JSON (HTTP {resp.status_code})") from e
    if not isinstance(data, dict):
        raise CobaltError(f"respuesta inesperada (HTTP {resp.status_code})")
    if resp.status_code in (401, 429):
        # Falta la key, o se pasó del rate limit de la instancia: no es un
        # problema del link, el operador tiene que enterarse.
        log.warning(
            "cobalt respondió HTTP %s (¿COBALT_API_KEY / rate limit?)", resp.status_code
        )
    return data


def _pick_media(data: dict) -> tuple[str, str | None]:
    """(url, nombre de archivo) del video según la respuesta de cobalt."""
    status = data.get("status")
    if status in ("tunnel", "redirect"):
        url = data.get("url")
        if isinstance(url, str) and url:
            return url, data.get("filename")
        raise CobaltError(f"{status} sin url")
    if status == "picker":
        for item in data.get("picker") or []:
            url = item.get("url") if isinstance(item, dict) else None
            if isinstance(url, str) and url and item.get("type") in _PICKER_VIDEO_TYPES:
                return url, None
        raise CobaltNoVideo("picker sin videos")
    if status == "error":
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        raise CobaltError(f"error de cobalt: {code}")
    # "local-processing" solo llega si se pide localProcessing, que no se pide.
    raise CobaltError(f"status inesperado: {status!r}")


def _is_tunnel_url(url: str) -> bool:
    return urlparse(url).path.rstrip("/").endswith("/tunnel")


def _open_stream(media_url: str):
    """Abre la descarga: la instancia propia para un tunnel (siempre re-armado
    sobre COBALT_API_URL, ver el docstring del módulo), el resto con el filtro
    SSRF."""
    if _is_tunnel_url(media_url):
        tunnel = f"{COBALT_API_URL}/tunnel?{urlparse(media_url).query}"
        return requests.get(
            tunnel,
            headers={"User-Agent": "purgito-bot"},
            timeout=_FETCH_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
    return r2.fetch_public_url(
        requests.get,
        media_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; bot)"},
        timeout=_FETCH_TIMEOUT,
        stream=True,
    )


def _save_stream(media_url: str, path: str, max_bytes: int) -> None:
    resp = _open_stream(media_url)
    try:
        if resp.status_code != 200:
            raise CobaltError(f"la descarga respondió HTTP {resp.status_code}")
        length = resp.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > max_bytes:
            raise CobaltTooLarge(max_bytes)
        deadline = time.monotonic() + _DOWNLOAD_DEADLINE_SECONDS
        total = 0
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=262144):
                total += len(chunk)
                if total > max_bytes:
                    raise CobaltTooLarge(max_bytes)
                if time.monotonic() > deadline:
                    raise CobaltError("la descarga tardó demasiado")
                f.write(chunk)
    finally:
        resp.close()
    if total == 0:
        raise CobaltError("archivo vacío")


def _extension(filename: str | None) -> str:
    # Solo la extensión, de una lista cerrada: el nombre lo manda cobalt y el
    # path nunca se arma con él.
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in _VIDEO_EXTENSIONS else ".mp4"


def download_video(url: str, max_bytes: int) -> str:
    """Bloqueante -- se corre en un thread aparte, igual que la descarga con
    yt-dlp. Devuelve la ruta del archivo; el caller borra el directorio
    temporal entero. Si falla, limpia su propio directorio antes de propagar."""
    tmp_dir = tempfile.mkdtemp(prefix="purgito_dl_")
    try:
        data = _request_media(url)
        media_url, filename = _pick_media(data)
        path = os.path.join(tmp_dir, f"cobalt_video{_extension(filename)}")
        _save_stream(media_url, path, max_bytes)
        return path
    except (requests.RequestException, ValueError, OSError, r2.BlockedTarget) as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise CobaltError(f"{type(e).__name__}: {e}") from e
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
