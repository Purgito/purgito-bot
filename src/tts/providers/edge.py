"""Proveedor de fallback TTS: Microsoft Edge Text-to-Speech (edge-tts)."""

import asyncio
import logging
from typing import ClassVar

import edge_tts

from tts.errors import (
    InvalidInputError,
    ProviderError,
    ProviderNetworkError,
    ProviderTimeoutError,
)
from tts.providers.base import BaseTTSProvider

log = logging.getLogger(__name__)

EDGE_VOICES: dict[str, str] = {
    # Español
    "es-ES-AlvaroNeural": "Español (España) - Álvaro",
    "es-ES-ElviraNeural": "Español (España) - Elvira",
    "es-MX-JorgeNeural": "Español (México) - Jorge",
    "es-MX-DaliaNeural": "Español (México) - Dalia",
    "es-AR-TomasNeural": "Español (Argentina) - Tomás",
    "es-CL-LorenzoNeural": "Español (Chile) - Lorenzo",
    "es-CO-GonzaloNeural": "Español (Colombia) - Gonzalo",
    # Inglés
    "en-US-ChristopherNeural": "English US - Christopher",
    "en-US-JennyNeural": "English US - Jenny",
    "en-US-GuyNeural": "English US - Guy",
    "en-GB-RyanNeural": "English UK - Ryan",
    # Otros
    "pt-BR-AntonioNeural": "Português (Brasil) - Antonio",
    "fr-FR-HenriNeural": "Français (France) - Henri",
    "de-DE-ConradNeural": "Deutsch (Deutschland) - Conrad",
    "ja-JP-KeitaNeural": "日本語 (日本) - Keita",
}

# Mapeo de voces de TikTok u otros IDs a equivalentes recomendados de Edge
FALLBACK_VOICE_MAPPING: dict[str, str] = {
    "es_002": "es-ES-AlvaroNeural",
    "es_male_m3": "es-ES-AlvaroNeural",
    "es_female_f6": "es-ES-ElviraNeural",
    "es_female_fp1": "es-MX-DaliaNeural",
    "es_mx_002": "es-MX-JorgeNeural",
    "es_mx_female_supermom": "es-MX-DaliaNeural",
    "en_us_001": "en-US-JennyNeural",
    "en_us_002": "en-US-JennyNeural",
    "en_us_006": "en-US-GuyNeural",
    "en_us_007": "en-US-ChristopherNeural",
    "en_us_009": "en-US-ChristopherNeural",
    "en_us_010": "en-US-GuyNeural",
    "en_male_narration": "en-US-ChristopherNeural",
    "en_male_funny": "en-US-GuyNeural",
    "en_female_emotional": "en-US-JennyNeural",
    "en_male_c3po": "en-US-GuyNeural",
    "en_male_chewbacca": "en-US-ChristopherNeural",
    "en_male_ghostface": "en-US-GuyNeural",
    "en_male_stitch": "en-US-GuyNeural",
    "en_male_stormtrooper": "en-US-ChristopherNeural",
    "en_male_santa_narration": "en-US-ChristopherNeural",
    "en_male_deadpool": "en-US-GuyNeural",
    "en_male_jarvis": "en-GB-RyanNeural",
    "en_female_ht_f08_glorious": "en-US-JennyNeural",
    "en_male_sing_deep_cappella": "en-US-ChristopherNeural",
    "br_003": "pt-BR-AntonioNeural",
    "br_004": "pt-BR-AntonioNeural",
    "br_005": "pt-BR-AntonioNeural",
    "fr_001": "fr-FR-HenriNeural",
    "fr_002": "fr-FR-HenriNeural",
    "de_001": "de-DE-ConradNeural",
    "de_002": "de-DE-ConradNeural",
    "jp_001": "ja-JP-KeitaNeural",
    "jp_003": "ja-JP-KeitaNeural",
    "jp_005": "ja-JP-KeitaNeural",
    "jp_006": "ja-JP-KeitaNeural",
}


class EdgeTTSProvider(BaseTTSProvider):
    """Proveedor de síntesis de voz mediante Microsoft Edge TTS."""

    name = "edge"

    DEFAULT_TIMEOUT: ClassVar[float] = 10.0
    DEFAULT_VOICE: ClassVar[str] = "es-ES-AlvaroNeural"

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self._timeout = timeout_seconds or self.DEFAULT_TIMEOUT

    def map_voice(self, voice_id: str) -> str:
        """Resuelve el voice_id a una voz nativa de Edge."""
        if voice_id in EDGE_VOICES:
            return voice_id
        if voice_id in FALLBACK_VOICE_MAPPING:
            return FALLBACK_VOICE_MAPPING[voice_id]
        # Si tiene prefijo de idioma, intentar aproximación inteligente
        if voice_id.startswith("es_") or voice_id.startswith("es-"):
            return "es-ES-AlvaroNeural"
        if voice_id.startswith("en_") or voice_id.startswith("en-"):
            return "en-US-ChristopherNeural"
        return self.DEFAULT_VOICE

    def supports_voice(self, voice_id: str) -> bool:
        # Como provider de fallback general, Edge puede sintetizar cualquier voz
        # mapeándola a su equivalente fonético más cercano
        return True

    def get_available_voices(self) -> dict[str, str]:
        return dict(EDGE_VOICES)

    async def synthesize(self, text: str, voice_id: str) -> bytes:
        clean_text = (text or "").strip()
        if not clean_text:
            raise InvalidInputError("El texto a sintetizar no puede estar vacío.")

        resolved_voice = self.map_voice(voice_id)

        communicate = edge_tts.Communicate(clean_text, resolved_voice)
        audio_chunks: list[bytes] = []

        try:

            async def _stream_audio():
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_chunks.append(chunk["data"])

            await asyncio.wait_for(_stream_audio(), timeout=self._timeout)

        except asyncio.TimeoutError as exc:
            raise ProviderTimeoutError(
                f"Timeout tras {self._timeout:.1f}s esperando respuesta de Edge-TTS"
            ) from exc
        except Exception as exc:
            raise ProviderNetworkError(
                f"Error durante la síntesis con Edge-TTS: {exc}"
            ) from exc

        audio_bytes = b"".join(audio_chunks)
        if not audio_bytes:
            raise ProviderError("Edge-TTS finalizó pero no generó datos de audio.")

        return audio_bytes
