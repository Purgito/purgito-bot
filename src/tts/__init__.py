"""Módulo TTS (Text-to-Speech) para Purgito."""

from tts.circuit_breaker import CircuitBreaker, CircuitState
from tts.errors import (
    AudioProcessingError,
    CircuitBreakerOpenError,
    InvalidInputError,
    ProviderAuthError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    QueueFullError,
    TTSError,
    VoiceConnectionError,
)
from tts.queue_manager import GuildTTSPlayer, TTSQueueItem, TTSQueueManager
from tts.service import TTSService

__all__ = [
    "TTSService",
    "TTSQueueManager",
    "GuildTTSPlayer",
    "TTSQueueItem",
    "CircuitBreaker",
    "CircuitState",
    "TTSError",
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderRateLimitError",
    "ProviderAuthError",
    "ProviderNetworkError",
    "ProviderInvalidResponseError",
    "CircuitBreakerOpenError",
    "InvalidInputError",
    "QueueFullError",
    "AudioProcessingError",
    "VoiceConnectionError",
]
