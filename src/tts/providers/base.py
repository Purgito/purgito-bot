"""Interfaz base para proveedores de síntesis de voz (TTS)."""

from abc import ABC, abstractmethod


class BaseTTSProvider(ABC):
    """Clase base abstracta que define la interfaz común de proveedores TTS."""

    name: str

    @abstractmethod
    async def synthesize(self, text: str, voice_id: str) -> bytes:
        """Sintetiza texto a bytes de audio (típicamente formato MP3).

        Lanza subclases de TTSError en caso de fallo.
        """
        pass

    @abstractmethod
    def supports_voice(self, voice_id: str) -> bool:
        """Determina si este proveedor puede procesar el identificador de voz dado."""
        pass

    @abstractmethod
    def get_available_voices(self) -> dict[str, str]:
        """Devuelve un diccionario {voice_id: display_name} de voces conocidas."""
        pass
