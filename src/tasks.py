"""TaskManager: registro en memoria de operaciones largas/background.

Pieza reutilizable, sin conectar todavía a ningún comando ni endpoint real
(eso es Fase 2/GIF Verify y Fase 3/Refeed). Sin dependencia de discord.py ni
aiohttp para poder importarse desde cogs/*.py y desde webapi.py sin ciclos.

Singleton de proceso: bot y webapi.py corren en el mismo proceso hoy, así
que un módulo con estado alcanza -- no hace falta inyectarlo en PurgitoBot.
Usar get_task_manager().

Task es efímera por diseño: vive solo en RAM. Para saber si un refeed quedó
a medias tras un restart, la fuente de verdad sigue siendo
channel_refeed_status (en db.py), no Task -- el próximo /refeed_channels
retoma desde ese cursor igual que hoy.

Política de "no zombies" (para el día que Task se persista, no aplica
todavía porque el dict se vacía solo al reiniciar el proceso): cualquier
Task encontrada en estado running al arrancar el proceso pasa a failed con
error="interrupted_by_restart".
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

STATUSES = {"pending", "running", "completed", "failed", "cancelled"}

# Cuánto se conserva una task terminada en RAM para que el Dashboard alcance
# a mostrar el resultado final aunque el usuario tarde en refrescar (mismo
# patrón que _pending_layout_files en webapi.py: limpieza perezosa al leer).
_FINISHED_TTL_SECONDS = 600


@dataclass
class Task:
    id: str
    guild_id: int
    type: str
    status: str = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    message: str | None = None
    error: str | None = None


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._expires_at: dict[str, float] = {}

    def _lock_for(self, task_id: str) -> asyncio.Lock:
        lock = self._locks.get(task_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[task_id] = lock
        return lock

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [tid for tid, exp in self._expires_at.items() if exp <= now]
        for tid in expired:
            self._tasks.pop(tid, None)
            self._locks.pop(tid, None)
            del self._expires_at[tid]

    def create(self, guild_id: int, type: str) -> Task:
        self._prune()
        task = Task(id=uuid.uuid4().hex, guild_id=guild_id, type=type)
        self._tasks[task.id] = task
        return task

    async def start(self, task_id: str) -> None:
        async with self._lock_for(task_id):
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)

    async def update_progress(
        self,
        task_id: str,
        *,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
    ) -> None:
        async with self._lock_for(task_id):
            task = self._tasks.get(task_id)
            if task is None:
                return
            if current is not None:
                task.progress_current = current
            if total is not None:
                task.progress_total = total
            if message is not None:
                task.message = message

    async def complete(self, task_id: str) -> None:
        await self._finish(task_id, "completed")

    async def fail(self, task_id: str, error: str) -> None:
        await self._finish(task_id, "failed", error=error)
        log.error("task %s failed: %s", task_id, error)

    async def cancel(self, task_id: str) -> None:
        await self._finish(task_id, "cancelled")

    async def _finish(
        self, task_id: str, status: str, error: str | None = None
    ) -> None:
        async with self._lock_for(task_id):
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.status = status
            task.finished_at = datetime.now(timezone.utc)
            if error is not None:
                task.error = error
            self._expires_at[task_id] = time.monotonic() + _FINISHED_TTL_SECONDS

    def get(self, task_id: str) -> Task | None:
        self._prune()
        return self._tasks.get(task_id)

    def list_for_guild(self, guild_id: int) -> list[Task]:
        self._prune()
        return [t for t in self._tasks.values() if t.guild_id == guild_id]


_task_manager = TaskManager()


def get_task_manager() -> TaskManager:
    return _task_manager
