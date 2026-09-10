"""Proveedor primario TTS: TikTok Text-to-Speech API."""

import asyncio
import base64
import logging
import os
from typing import ClassVar

import aiohttp

from tts.errors import (
    InvalidInputError,
    ProviderAuthError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from tts.providers.base import BaseTTSProvider

log = logging.getLogger(__name__)

# Catálogo oficial de voces de TikTok soportadas
TIKTOK_VOICES: dict[str, str] = {
    # Español
    "es_002": "Español (Hombre)",
    "es_male_m3": "Español - Julio",
    "es_female_f6": "Español - Marcela",
    "es_female_fp1": "Español - Suave",
    "es_mx_002": "Español México (Hombre)",
    "es_mx_female_supermom": "Español México - Supermom",
    # Inglés
    "en_us_001": "English US - Female 1",
    "en_us_002": "English US - Jessie",
    "en_us_006": "English US - Joey",
    "en_us_007": "English US - Professor",
    "en_us_009": "English US - Scientist",
    "en_us_010": "English US - Confidence",
    "en_male_narration": "Narrator",
    "en_male_funny": "Wacky",
    "en_female_emotional": "Peaceful",
    "en_male_c3po": "C3PO",
    "en_male_chewbacca": "Chewbacca",
    "en_male_ghostface": "Ghostface",
    "en_male_stitch": "Stitch",
    "en_male_stormtrooper": "Stormtrooper",
    "en_male_santa_narration": "Santa",
    "en_male_deadpool": "Deadpool",
    "en_male_jarvis": "Jarvis",
    "en_female_ht_f08_glorious": "Glorious",
    "en_male_sing_deep_cappella": "Deep Chorus",
    # Otros
    "br_003": "Português (Homem)",
    "br_004": "Português (Mulher)",
    "br_005": "Português (Narrador)",
    "fr_001": "Français (Homme 1)",
    "fr_002": "Français (Homme 2)",
    "de_001": "Deutsch (Frau)",
    "de_002": "Deutsch (Mann)",
    "jp_001": "日本語 (女性 1)",
    "jp_003": "日本語 (女性 2)",
    "jp_005": "日本語 (男性 1)",
    "jp_006": "日本語 (男性 2)",
}


class TikTokTTSProvider(BaseTTSProvider):
    """Proveedor TTS usando la API de TikTok."""

    name = "tiktok"

    ENDPOINT: ClassVar[str] = (
        "https://api16-normal-v6.tiktokv.com/media/api/text/speech/invoke/"
    )
    DEFAULT_TIMEOUT: ClassVar[float] = 8.0

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._session = session
        self._timeout = timeout_seconds or self.DEFAULT_TIMEOUT

    def supports_voice(self, voice_id: str) -> bool:
        if not voice_id:
            return False
        # Si tiene Neural o guion medio como es-ES, es voz de Edge
        if "Neural" in voice_id or "-" in voice_id:
            return False
        return voice_id in TIKTOK_VOICES or voice_id.startswith(
            ("es_", "en_", "br_", "fr_", "de_", "jp_")
        )

    def get_available_voices(self) -> dict[str, str]:
        return dict(TIKTOK_VOICES)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def synthesize(self, text: str, voice_id: str) -> bytes:
        clean_text = (text or "").strip()
        if not clean_text:
            raise InvalidInputError("El texto a sintetizar no puede estar vacío.")

        if not self.supports_voice(voice_id):
            raise InvalidInputError(
                f"Voz '{voice_id}' no soportada por el proveedor TikTok."
            )

        # Obtener sesión opcional de TikTok desde el entorno sin registrar secretos
        session_id = os.getenv("TIKTOK_SESSION_ID", "").strip()

        headers = {
            "User-Agent": (
                "com.zhiliaoapp.musically/2022600030 "
                "(Linux; U; Android 7.1.2; es_ES; AppBuild/2022600030)"
            ),
        }
        if session_id:
            headers["Cookie"] = f"sessionid={session_id}"

        params = {
            "text_speaker": voice_id,
            "req_text": clean_text,
            "speaker_map_type": "0",
            "aid": "1233",
        }

        session = await self._get_session()
        client_timeout = aiohttp.ClientTimeout(total=self._timeout)

        try:
            async with session.post(
                self.ENDPOINT,
                params=params,
                headers=headers,
                timeout=client_timeout,
            ) as resp:
                status = resp.status

                if status == 429:
                    raise ProviderRateLimitError(
                        f"TikTok rechazó la petición por rate limit (HTTP {status})"
                    )
                if status in (401, 403):
                    raise ProviderAuthError(
                        f"TikTok rechazó la petición por error de autenticación/sesión (HTTP {status})"
                    )
                if status >= 500:
                    raise ProviderError(
                        f"TikTok respondió con error de servidor (HTTP {status})"
                    )
                if status != 200:
                    raise ProviderInvalidResponseError(
                        f"TikTok devolvió un código HTTP inesperado ({status})"
                    )

                try:
                    data = await resp.json(content_type=None)
                except Exception as exc:
                    raise ProviderInvalidResponseError(
                        f"Respuesta de TikTok no es JSON válido: {exc}"
                    ) from exc

        except asyncio.TimeoutError as exc:
            raise ProviderTimeoutError(
                f"Timeout tras {self._timeout:.1f}s esperando respuesta de TikTok"
            ) from exc
        except aiohttp.ClientConnectorError as exc:
            raise ProviderNetworkError(f"Error de conexión con TikTok: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise ProviderNetworkError(
                f"Error de red al consultar TikTok: {exc}"
            ) from exc

        status_code = data.get("status_code")
        message = data.get("message", "")

        # status_code == 0 indica éxito en la API de TikTok
        if status_code == 0:
            v_str = (data.get("data") or {}).get("v_str")
            if not v_str:
                raise ProviderInvalidResponseError(
                    "TikTok devolvió status_code 0 pero falta data.v_str con el audio"
                )
            try:
                audio_bytes = base64.b64decode(v_str)
                if not audio_bytes:
                    raise ProviderInvalidResponseError("TikTok devolvió audio vacío")
                return audio_bytes
            except Exception as exc:
                raise ProviderInvalidResponseError(
                    f"Fallo al decodificar audio base64 de TikTok: {exc}"
                ) from exc

        # Códigos de error específicos de TikTok
        # status_code 2 usualmente significa texto demasiado largo o voz no válida
        if status_code == 2:
            raise InvalidInputError(f"TikTok rechazó la entrada (status 2): {message}")
        if status_code == 4:
            raise ProviderAuthError(
                f"Sesión de TikTok inválida o expirada (status 4): {message}"
            )

        raise ProviderError(f"TikTok falló con status_code {status_code}: {message}")
