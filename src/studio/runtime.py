"""Recolección sin I/O en callbacks; buffer agregado, acotado y fail-soft."""

import asyncio
from collections import deque
from contextlib import contextmanager
from functools import lru_cache
import logging
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from .model import FEATURES, RESULTS, SOURCES, TOKEN, Settings, duration_bucket, utcnow
from .store import Store

log = logging.getLogger(__name__)
_current = None


class Collector:
    def __init__(self, store, settings, *, clock=utcnow):
        self.store, self.settings, self.clock = store, settings, clock
        self.session_id = uuid.uuid4()
        self.started_at = clock()
        self.usage = {}
        self.lifecycle = deque()
        self.inventory = None
        self.written_inventory = None  # (día, claves) ya confirmado en la base
        self.inflight = None
        self.dropped = 0
        self.last_flush = None
        self.last_error = None
        self.lock = asyncio.Lock()
        self.catalog = {}
        self.task = None
        self.stopping = False
        self.bot = None
        self.was_ready = False
        self.coverage_until = self.started_at
        self._guild_key = lru_cache(maxsize=4096)(settings.guild_key)

    def record(
        self,
        guild_id,
        feature,
        *,
        command="",
        source="delivery",
        result="ok",
        duration_ms=None,
        count=1,
    ):
        """No acepta texto, objetos Discord, nombres de usuario ni errores."""
        try:
            if (
                self.stopping
                or not guild_id
                or feature not in FEATURES
                or source not in SOURCES
                or result not in RESULTS
            ):
                return False
            if command and (
                not isinstance(command, str) or not TOKEN.fullmatch(command)
            ):
                return False
            if not isinstance(count, int) or not 1 <= count <= 1000:
                return False
            at = self.clock().replace(minute=0, second=0, microsecond=0)
            key = (
                at,
                self._guild_key(guild_id),
                feature,
                command,
                source,
                result,
                self.settings.version,
            )
            if key not in self.usage:
                if len(self.usage) + len(self.lifecycle) >= self.settings.max_pending:
                    self.dropped += count
                    return False
                self.usage[key] = [0, 0, 0.0, [0] * 11]
            value = self.usage[key]
            value[0] += count
            bucket = duration_bucket(duration_ms)
            if bucket is not None and duration_ms <= 3_600_000:
                value[1] += count
                value[2] += duration_ms * count
                value[3][bucket] += count
            return True
        except Exception:
            self.dropped += 1
            return False

    def membership(self, guild_id, action):
        if self.stopping or action not in {"join", "leave"}:
            return
        if len(self.usage) + len(self.lifecycle) >= self.settings.max_pending:
            self.dropped += 1
            return
        self.lifecycle.append(
            (uuid.uuid4(), self.clock(), self._guild_key(guild_id), action)
        )

    def observe_inventory(self, guild_ids):
        # Inventario completo, nunca interpolación de los contadores 120/126.
        self.inventory = (self.clock(), sorted({self._guild_key(g) for g in guild_ids}))

    @staticmethod
    def _inventory_state(inventory):
        at, keys = inventory
        return at.date(), tuple(keys)

    async def flush(self):
        async with self.lock:
            if self.inflight is None:
                inventory = self.inventory
                if (
                    inventory
                    and self._inventory_state(inventory) == self.written_inventory
                ):
                    inventory = (
                        None  # sin cambios: no reescribir la presencia cada ciclo
                    )
                self.inflight = {
                    "id": uuid.uuid4(),
                    "at": self.clock(),
                    "usage": self.usage,
                    "lifecycle": list(self.lifecycle),
                    "inventory": inventory,
                    "session_id": self.session_id,
                    "coverage_until": self.coverage_until if self.bot else self.clock(),
                }
                self.usage, self.lifecycle, self.inventory = {}, deque(), None
            try:
                await self.store.write(
                    self.inflight, self.inflight["session_id"], self.dropped
                )
            except Exception as exc:
                self.last_error = type(exc).__name__
                return False
            self.last_flush = self.inflight["at"]
            if self.inflight["inventory"] is not None:
                self.written_inventory = self._inventory_state(
                    self.inflight["inventory"]
                )
            self.inflight = None
            self.last_error = None
            return True

    async def sample(self):
        if self.bot:
            ready = self.bot.is_ready()
            if ready and not self.was_ready:
                # Una reconexión inicia otro tramo, nunca rellena el hueco.
                session_id = uuid.uuid4()
                started_at = self.clock()
                await self.store.start(session_id, started_at)
                self.session_id, self.started_at = session_id, started_at
                self.coverage_until = started_at
            self.was_ready = ready
            if ready:
                self.observe_inventory(g.id for g in self.bot.guilds)
                self.coverage_until = self.clock()
        return await self.flush()

    async def run(self):
        cleaned = None
        while not self.stopping:
            try:
                await self.sample()
                if cleaned != self.clock().date():
                    await self.store.cleanup(self.clock())
                    cleaned = self.clock().date()
            except Exception as exc:
                self.last_error = type(exc).__name__
            await asyncio.sleep(self.settings.flush_seconds)

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        # Un lote que ya estaba en vuelo y el buffer posterior son distintos.
        for _ in range(2):
            if not await self.flush():
                return False
        await self.store.finish(self.session_id)
        return True

    def health(self):
        return {
            "version": self.settings.version,
            "pending_keys": len(self.usage) + len(self.lifecycle),
            "inflight": self.inflight is not None,
            "dropped": self.dropped,
            "last_flush": self.last_flush.isoformat() if self.last_flush else None,
            "last_error": self.last_error,
            "retention_days": self.settings.retention_days,
            "gateway_ready": self.bot.is_ready() if self.bot else None,
        }


def get():
    return _current


def delivery(guild_id, feature, *, source="delivery", count=1):
    if _current:
        _current.record(guild_id, feature, source=source, count=count)


def _feature(command):
    module = getattr(getattr(command, "callback", None), "__module__", "")
    feature = module.removeprefix("cogs.").split(".")[0]
    return feature if feature in FEATURES else "general"


def classify_error(error):
    """Separa fallos de Purgito de rechazos operativos. Solo mira el tipo, nunca el texto."""
    error = getattr(error, "original", None) or error  # CommandInvokeError
    if isinstance(
        error,
        (
            discord.Forbidden,
            discord.NotFound,
            commands.BotMissingPermissions,
            app_commands.BotMissingPermissions,
        ),
    ):
        return "refused"
    if isinstance(
        error,
        (
            commands.CheckFailure,
            commands.UserInputError,
            commands.CommandOnCooldown,
            app_commands.CheckFailure,
            app_commands.CommandOnCooldown,
            app_commands.TransformerError,
        ),
    ):
        return "rejected"
    return "error"


_result = classify_error


def _finish_command(context, command=None, error=None, *, slash=False):
    if not _current or not getattr(context, "guild", None):
        return
    command = command or getattr(context, "command", None)
    if command is None or isinstance(error, commands.CommandNotFound):
        return
    extras = context.extras if slash else context.__dict__
    if extras.get("_studio_done"):
        return
    extras["_studio_done"] = True
    begin = extras.get("_studio_started")
    _current.record(
        context.guild.id,
        _feature(command),
        command=command.qualified_name,
        source="slash" if slash else "prefix",
        result=_result(error) if error else "ok",
        duration_ms=(time.perf_counter() - begin) * 1000 if begin is not None else None,
    )


def finish_command(context, command=None, error=None, *, slash=False):
    try:
        _finish_command(context, command, error, slash=slash)
    except Exception:
        pass  # Nunca interrumpir un comando ni su manejador de errores.


class StudioTree(app_commands.CommandTree):
    async def interaction_check(self, interaction):
        if _current:
            interaction.extras["_studio_started"] = time.perf_counter()
        return await super().interaction_check(interaction)


async def start(bot):
    global _current
    from db import get_db
    from observability.monitor import detect_version
    from pathlib import Path

    try:
        settings = Settings.from_env()
        if not settings.enabled:
            return
        if settings.version == "unversioned":
            from dataclasses import replace

            settings = replace(
                settings,
                version=detect_version(str(Path(__file__).resolve().parents[2]))
                or "unversioned",
            )
        store = Store(await get_db(), settings)
        collector = Collector(store, settings)
        await asyncio.wait_for(
            store.start(collector.session_id, collector.started_at), timeout=5
        )
        collector.bot = bot
        for source, items in [
            ("prefix", bot.walk_commands()),
            ("slash", bot.tree.walk_commands()),
        ]:
            for command in items:
                if hasattr(command, "callback"):
                    collector.catalog[(source, command.qualified_name)] = _feature(
                        command
                    )
        _current = collector

        async def before(ctx):
            ctx.__dict__["_studio_started"] = time.perf_counter()

        async def complete(ctx):
            finish_command(ctx)

        async def failed(ctx, error):
            finish_command(ctx, error=error)

        async def slash_complete(interaction, command):
            finish_command(interaction, command, slash=True)

        async def disconnected():
            collector.was_ready = False

        async def joined(guild):
            collector.membership(guild.id, "join")

        async def left(guild):
            if not getattr(guild, "unavailable", False):
                collector.membership(guild.id, "leave")

        bot.before_invoke(before)
        for name, callback in [
            ("on_command_completion", complete),
            ("on_command_error", failed),
            ("on_app_command_completion", slash_complete),
            ("on_disconnect", disconnected),
            ("on_guild_join", joined),
            ("on_guild_remove", left),
        ]:
            bot.add_listener(callback, name)
        collector.task = asyncio.create_task(collector.run(), name="studio-writer")
    except Exception:
        _current = None
        log.error(
            "Studio no se activó; revisar configuración y conexión local",
            exc_info=False,
        )


async def stop():
    global _current
    collector, _current = _current, None
    if collector:
        try:
            await asyncio.wait_for(collector.stop(), timeout=8)
        except Exception:
            log.warning("Studio dejó un intervalo sin confirmar al cerrar")


@contextmanager
def measure_delivery(guild_id, feature, *, source="delivery"):
    collector = _current
    if not collector:
        yield
        return
    start = time.perf_counter()
    result = "ok"
    observed = True
    try:
        yield
    except asyncio.CancelledError:
        observed = False  # una cancelación (p. ej. el apagado) no es éxito ni fallo
        raise
    except Exception as exc:
        result = classify_error(exc)
        raise
    finally:
        if observed:
            collector.record(
                guild_id,
                feature,
                source=source,
                result=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
