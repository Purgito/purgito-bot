"""Contrato acotado: sin personas, mensajes ni dimensiones de texto libre."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import math
import os
import re

FEATURES = {
    "chat": "Conversación",
    "gifs": "GIFs",
    "memes": "Memes",
    "youtube": "YouTube",
    "twitch": "Twitch",
    "rss": "RSS",
    "anuncios": "Anuncios",
    "general": "General",
    "download": "Descargas",
    "imagefx": "Edición de imágenes",
    "settings": "Configuración",
    "layout_buttons": "Embeds y botones",
    "privacy": "Privacidad",
    "updates": "Novedades",
    "events": "Eventos",
    "premium": "Premium",
}
SOURCES = {
    "prefix",
    "slash",
    "mention",
    "trigger",
    "spontaneous",
    "background",
    "delivery",
}
ACTIVE_SOURCES = ("prefix", "slash", "mention", "trigger")
# ok: terminó bien. error: fallo interno o de Discord que Purgito debe atender.
# rejected: validación previa (permisos de quien invoca, argumentos, cooldown).
# refused: Discord rechazó una acción por configuración del servidor (el bot sin
# permiso, canal o mensaje borrado). Es operativo: se muestra, no cuenta como fallo.
RESULTS = {"ok", "error", "rejected", "refused"}
# Política de cobertura (fracción del período con sesiones de captura confirmadas).
COVERAGE_COMPLETE = 0.995
COVERAGE_PARTIAL = 0.90
BOUNDS = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000)
TOKEN = re.compile(r"^[a-zA-Z0-9_. /-]{1,80}$")


def utcnow():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    key: str = ""
    version: str = "unversioned"
    retention_days: int = 90
    max_pending: int = 4096
    flush_seconds: float = 10

    @classmethod
    def from_env(cls, version="unversioned"):
        days = int(os.getenv("STUDIO_RETENTION_DAYS", "90"))
        if not 7 <= days <= 365:
            raise ValueError("STUDIO_RETENTION_DAYS debe estar entre 7 y 365")
        enabled = os.getenv("STUDIO_ENABLED", "").lower() in {"1", "true", "yes"}
        key = os.getenv("STUDIO_HMAC_KEY", "")
        if enabled and len(key) < 32:
            raise ValueError("STUDIO_HMAC_KEY requiere al menos 32 caracteres")
        version = os.getenv("STUDIO_VERSION", "") or version or "unversioned"
        if not TOKEN.fullmatch(version):
            raise ValueError("STUDIO_VERSION inválida")
        return cls(enabled=enabled, key=key, version=version, retention_days=days)

    def guild_key(self, guild_id):
        return hmac.new(
            self.key.encode(), str(int(guild_id)).encode(), hashlib.sha256
        ).hexdigest()


def duration_bucket(ms):
    if ms is None or not math.isfinite(ms) or ms < 0:
        return None
    return next((i for i, bound in enumerate(BOUNDS) if ms <= bound), len(BOUNDS))


def parse_time(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Las fechas requieren zona horaria")
    return value.astimezone(timezone.utc)


def period(params, now=None):
    now = now or utcnow()
    end = parse_time(params["end"]) if params.get("end") else now
    start = (
        parse_time(params["start"]) if params.get("start") else end - timedelta(days=28)
    )
    if not timedelta(0) < end - start <= timedelta(days=90) or end > now + timedelta(
        seconds=1
    ):
        raise ValueError("Período inválido: máximo 90 días, sin fechas futuras")
    if params.get("feature") and params["feature"] not in FEATURES:
        raise ValueError("Función desconocida")
    if params.get("version") and not TOKEN.fullmatch(params["version"]):
        raise ValueError("Versión inválida")
    if params.get("result") and params["result"] not in RESULTS:
        raise ValueError("Resultado inválido")
    # Agregados horarios: no se finge precisión inferior a la hora.
    if start.minute or start.second or start.microsecond:
        start = start.replace(minute=0, second=0, microsecond=0)
    end = end.replace(minute=0, second=0, microsecond=0)
    if end <= start:
        raise ValueError("Selecciona al menos una hora completa")
    cend = parse_time(params["compare_end"]) if params.get("compare_end") else start
    cstart = (
        parse_time(params["compare_start"])
        if params.get("compare_start")
        else cend - (end - start)
    )
    if cend - cstart != end - start or cend > start:
        raise ValueError("La comparación debe ser anterior y durar lo mismo")
    return start, end, cstart, cend
