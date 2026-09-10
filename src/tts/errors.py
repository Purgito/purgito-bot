"""Excepciones especializadas para el sistema TTS."""


class TTSError(Exception):
    """Excepción base para todos los errores del sistema TTS."""

    pass


class ProviderError(TTSError):
    """Error originado en un proveedor de TTS externo (red, servidor, etc.)."""

    pass


class ProviderTimeoutError(ProviderError):
    """El proveedor no respondió dentro del tiempo límite establecido."""

    pass


class ProviderRateLimitError(ProviderError):
    """El proveedor rechazó la solicitud por límite de tasa (HTTP 429)."""

    pass


class ProviderAuthError(ProviderError):
    """Error de autenticación o sesión con el proveedor (HTTP 401/403/session expired)."""

    pass


class ProviderNetworkError(ProviderError):
    """Fallo de conectividad de red con el proveedor (DNS, conexión rechazada, reset)."""

    pass


class ProviderInvalidResponseError(ProviderError):
    """La respuesta del proveedor no tuvo el formato esperado o los datos de audio."""

    pass


class CircuitBreakerOpenError(TTSError):
    """El circuit breaker del proveedor está ABIERTO debido a fallos recientes."""

    pass


class InvalidInputError(TTSError):
    """Entrada inválida permanente (texto vacío, excede longitud, voz inexistente).

    Estos errores nunca deben contar como fallos del proveedor para el circuit breaker.
    """

    pass


class QueueFullError(TTSError):
    """La cola de reproducción del servidor alcanzó su tamaño máximo permitido."""

    pass


class AudioProcessingError(TTSError):
    """Error durante la conversión, filtrado o preparación del audio con FFmpeg."""

    pass


class VoiceConnectionError(TTSError):
    """Error al intentar conectar o reproducir en un canal de voz de Discord."""

    pass
