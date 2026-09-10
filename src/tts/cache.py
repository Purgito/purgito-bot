"""Gestor de caché local para audios TTS con deduplicación por hash SHA-256."""

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


class TTSCache:
    """Caché en disco para audios sintetizados y procesados.

    - Clave de caché basada en hash SHA-256 de todos los parámetros efectivos.
    - Escrituras atómicas mediante archivos temporales y os.replace.
    - TTL máximo de 7 días.
    - Poda automática por LRU/antigüedad cuando se supera el límite de bytes.
    """

    def __init__(
        self,
        cache_dir: str | None = None,
        max_size_bytes: int = 500 * 1024 * 1024,
        ttl_seconds: float = 7 * 86400,
    ) -> None:
        if cache_dir is None:
            base_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            cache_dir = os.path.join(base_dir, "data", "tts_cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = max_size_bytes
        self.ttl_seconds = ttl_seconds
        self._prune_lock = asyncio.Lock()

    @staticmethod
    def compute_key(
        provider: str,
        voice: str,
        text: str,
        speed: float = 1.0,
        pitch: float = 1.0,
        filter_name: str = "normal",
        filter_params: dict | None = None,
        audio_format: str = "mp3",
    ) -> str:
        """Calcula el hash SHA-256 canónico de los parámetros efectivos."""
        clean_text = (text or "").strip()
        canonical_params = json.dumps(filter_params or {}, sort_keys=True)
        payload = (
            f"{provider.lower()}:{voice.strip()}:{clean_text}:{speed:.3f}:"
            f"{pitch:.3f}:{filter_name.lower()}:{canonical_params}:{audio_format.lower()}"
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _file_path(self, cache_key: str, audio_format: str = "mp3") -> Path:
        return self.cache_dir / f"{cache_key}.{audio_format}"

    async def get(self, cache_key: str, audio_format: str = "mp3") -> str | None:
        """Devuelve la ruta absoluta del archivo si existe y no ha expirado.

        Actualiza la marca de tiempo de acceso para política LRU.
        """
        path = self._file_path(cache_key, audio_format)
        if not path.exists():
            return None

        try:
            stat = path.stat()
            now = time.time()
            if now - stat.st_mtime > self.ttl_seconds:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None

            # Actualizar mtime/atime para política LRU
            try:
                os.utime(path, None)
            except OSError:
                pass

            return str(path)
        except OSError:
            return None

    async def put(self, cache_key: str, data: bytes, audio_format: str = "mp3") -> str:
        """Guarda bytes de audio en la caché de forma atómica.

        Devuelve la ruta absoluta del archivo guardado.
        """
        final_path = self._file_path(cache_key, audio_format)
        temp_path = self.cache_dir / f"{cache_key}.tmp.{uuid.uuid4().hex}"

        def _write():
            with open(temp_path, "wb") as f:
                f.write(data)
            os.replace(temp_path, final_path)

        await asyncio.to_thread(_write)

        # Disparar poda en segundo plano si es necesario
        asyncio.create_task(self._prune_if_needed())
        return str(final_path)

    async def put_file(
        self, cache_key: str, source_path: str, audio_format: str = "mp3"
    ) -> str:
        """Guarda un archivo existente en la caché de forma atómica."""
        final_path = self._file_path(cache_key, audio_format)
        temp_path = self.cache_dir / f"{cache_key}.tmp.{uuid.uuid4().hex}"

        def _copy_or_replace():
            import shutil

            shutil.copyfile(source_path, temp_path)
            os.replace(temp_path, final_path)

        await asyncio.to_thread(_copy_or_replace)
        asyncio.create_task(self._prune_if_needed())
        return str(final_path)

    async def _prune_if_needed(self) -> None:
        try:
            await self.prune()
        except Exception:
            log.exception("Error podando caché de TTS")

    async def prune(self) -> int:
        """Poda archivos expirados y reduce el tamaño si supera max_size_bytes.

        Devuelve la cantidad de archivos eliminados.
        """
        async with self._prune_lock:
            return await asyncio.to_thread(self._prune_sync)

    def _prune_sync(self) -> int:
        now = time.time()
        deleted_count = 0
        total_size = 0
        entries: list[tuple[Path, float, int]] = []  # (path, mtime, size)

        try:
            for entry in self.cache_dir.iterdir():
                if not entry.is_file() or ".tmp." in entry.name:
                    continue
                try:
                    stat = entry.stat()
                    # Eliminar archivos expirados por TTL
                    if now - stat.st_mtime > self.ttl_seconds:
                        entry.unlink(missing_ok=True)
                        deleted_count += 1
                        continue
                    entries.append((entry, stat.st_mtime, stat.st_size))
                    total_size += stat.st_size
                except OSError:
                    continue
        except OSError:
            return deleted_count

        # Si el tamaño supera el máximo, podar los menos usados / más antiguos (LRU)
        if total_size > self.max_size_bytes:
            # Ordenar ascendente por fecha de último acceso/modificación
            entries.sort(key=lambda x: x[1])
            target_size = int(self.max_size_bytes * 0.8)  # Reducir al 80% para margen

            for path, _mtime, size in entries:
                if total_size <= target_size:
                    break
                try:
                    path.unlink(missing_ok=True)
                    total_size -= size
                    deleted_count += 1
                except OSError:
                    pass

        return deleted_count
