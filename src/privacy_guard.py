"""Guardián de restauración: una base restaurada de un backup antiguo no puede arrancar el bot
sin haber pasado por la reconciliación con el registro externo de eliminaciones.

Mecanismo (sin servicios nuevos):
  - El bot escribe cada minuto un LATIDO (`privacy_state.heartbeat_at`) en la base y en un archivo local
    (`data/privacy_watermark`, que vive en el volumen cifrado). Son dos relojes independientes: uno
    viaja con la base (un backup lo trae viejo) y el otro con el servidor (un backup no lo toca).
  - Al arrancar, si el latido de la base es MÁS ANTIGUO que el del archivo local, esta base es anterior
    a lo último que el servidor vio: se restauró. El bot se niega a arrancar (código 78, que el unit de
    systemd marca como "no reintentar") hasta que scripts/reapply_deletions.py reconcilie con un
    registro válido y fresco; ese script es lo único que "pone al día" el latido de la base.
  - Sin archivo local (servidor nuevo) y con un latido de la base de hace más de 10 minutos, la
    procedencia es desconocida y también se niega. El primer arranque tras instalar esto (sin latido
    ni archivo) se acepta y empieza a latir.

Prefiere fallar a parecer exitoso: el único atajo es reconciliar (o `--sin-registro`, explícito).
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db

log = logging.getLogger(__name__)

EXIT_CODE = 78  # EX_CONFIG: systemd no lo reintenta (RestartPreventExitStatus=78)
SLACK = timedelta(minutes=5)
FRESH_WINDOW = timedelta(minutes=10)
FMT = "%Y-%m-%d %H:%M:%S"
HEARTBEAT_KEY = "heartbeat_at"


class RestoreNotReconciled(RuntimeError):
    """La base parece restaurada o de origen desconocido y no está reconciliada."""


def watermark_path() -> Path:
    override = os.getenv("PRIVACY_WATERMARK_PATH", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data" / "privacy_watermark"


def _parse(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _read_local() -> datetime | None:
    try:
        return _parse(watermark_path().read_text(encoding="utf-8"))
    except OSError:
        return None


def _write_local(now: datetime) -> None:
    path = watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(now.strftime(FMT), encoding="utf-8")
    os.replace(tmp, path)


async def _read_db() -> datetime | None:
    conn = await db.get_db()
    async with conn.execute(
        "SELECT value FROM privacy_state WHERE key=?", (HEARTBEAT_KEY,)
    ) as cur:
        row = await cur.fetchone()
    return _parse(row[0]) if row else None


async def beat(now: datetime | None = None) -> None:
    """Latido: base y archivo local, juntos. Solo después de que check_startup pasó."""
    now = now or datetime.now(timezone.utc)
    conn = await db.get_db()
    async with db._db_lock:
        await conn.execute(
            "INSERT INTO privacy_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (HEARTBEAT_KEY, now.strftime(FMT), now.strftime(FMT)),
        )
        await conn.commit()
    try:
        _write_local(now)
    except OSError:
        # Sin archivo local la guardia sigue funcionando con la regla de "procedencia desconocida".
        log.exception("privacy_guard: no se pudo escribir %s", watermark_path())


async def check_startup(now: datetime | None = None) -> str:
    """Decide si este arranque es seguro. Devuelve el motivo (para el log) o lanza
    RestoreNotReconciled."""
    now = now or datetime.now(timezone.utc)
    db_hb = await _read_db()
    local = _read_local()
    if db_hb is None and local is None:
        return "primer arranque con la guardia: se acepta y empieza a latir"
    if db_hb is None:
        raise RestoreNotReconciled(
            "la base no tiene latido pero este servidor sí lo tuvo: es una base anterior a la "
            "guardia (restauración sin reconciliar). Ejecuta scripts/reapply_deletions.py --ledger - --apply"
        )
    if local is None:
        if now - db_hb <= FRESH_WINDOW:
            return "sin archivo local, pero la base fue reconciliada hace instantes"
        raise RestoreNotReconciled(
            "este servidor no tiene registro local y el último latido de la base es de hace más de "
            "10 minutos: procedencia desconocida. Ejecuta scripts/reapply_deletions.py --ledger - --apply"
        )
    if db_hb >= local - SLACK:
        return "la base es continuación de lo último que este servidor vio"
    raise RestoreNotReconciled(
        "la base es MÁS ANTIGUA que lo último que este servidor vio (parece un backup restaurado). "
        "Reconcilia con el registro externo antes de arrancar: "
        "scripts/reapply_deletions.py --ledger - --apply < registro.jsonl"
    )
