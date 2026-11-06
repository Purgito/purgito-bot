"""Solicitudes de derechos que el Centro de Privacidad no resuelve solo.

Descargar los datos, excluirse del aprendizaje y pedir la eliminación son automáticos
(privacy_requests, /api/me/privacy). Lo demás -- acceso más allá de la descarga, rectificación,
oposición, portabilidad, limitación del tratamiento u otras consultas -- lo atiende una persona.
Esta tabla solo guarda lo mínimo: quién (siempre el id de la sesión, nunca un valor enviado por el
cliente), qué derecho, un comentario opcional corto y las fechas. Plazo interno de respuesta: 30
días corridos (compromiso de Purgito, no una cita legal). Las contestadas se borran a los 90 días.
"""

import logging
from datetime import datetime, timedelta, timezone

import db

log = logging.getLogger(__name__)

DEADLINE_DAYS = 30
RETENTION_DAYS = 90
NOTE_MAX = 1000
MAX_OPEN_PER_USER = 5
RIGHT_KINDS = ("access", "rectification", "objection", "portability", "restriction", "other")
FMT = "%Y-%m-%d %H:%M:%S"
_COLS = "id, right_kind, note, status, created_at, due_at, answered_at"


class RightsError(ValueError):
    """Entrada no válida (derecho desconocido, comentario demasiado largo, demasiadas abiertas)."""


def _row(r) -> dict:
    return {
        "id": r[0],
        "right": r[1],
        "note": r[2],
        "status": r[3],
        "created_at": r[4],
        "due_at": r[5],
        "answered_at": r[6],
    }


async def create(user_id: int, right_kind: str, note: str = "", now: datetime | None = None) -> dict:
    if right_kind not in RIGHT_KINDS:
        raise RightsError("derecho no válido")
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise RightsError("comentario demasiado largo")
    now = now or datetime.now(timezone.utc)
    conn = await db.get_db()
    async with db._db_lock:
        async with conn.execute(
            "SELECT COUNT(*) FROM privacy_rights_requests WHERE user_id=? AND status='open'",
            (user_id,),
        ) as cur:
            open_n = (await cur.fetchone())[0]
        if open_n >= MAX_OPEN_PER_USER:
            raise RightsError("demasiadas solicitudes abiertas")
        await conn.execute(
            "INSERT INTO privacy_rights_requests (user_id, right_kind, note, status, created_at, due_at) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (
                user_id,
                right_kind,
                note,
                now.strftime(FMT),
                (now + timedelta(days=DEADLINE_DAYS)).strftime(FMT),
            ),
        )
        async with conn.execute(
            f"SELECT {_COLS} FROM privacy_rights_requests WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        await conn.commit()
    log.info("privacy.rights: id=%s derecho=%s (nueva)", row[0], right_kind)
    return _row(row)


async def user_requests(user_id: int) -> list[dict]:
    conn = await db.get_db()
    async with conn.execute(
        f"SELECT {_COLS} FROM privacy_rights_requests WHERE user_id=? ORDER BY id", (user_id,)
    ) as cur:
        return [_row(r) for r in await cur.fetchall()]


async def open_requests(now: datetime | None = None) -> list[dict]:
    """Abiertas, con el campo `overdue`. Sin ids de persona: es para el operador."""
    now_s = (now or datetime.now(timezone.utc)).strftime(FMT)
    conn = await db.get_db()
    async with conn.execute(
        f"SELECT {_COLS} FROM privacy_rights_requests WHERE status='open' ORDER BY due_at"
    ) as cur:
        rows = [_row(r) for r in await cur.fetchall()]
    for r in rows:
        r["overdue"] = r["due_at"] < now_s
    return rows


async def requester_of(request_id: int) -> int | None:
    """Solo para que el operador conteste a la persona; nunca se expone por la API."""
    conn = await db.get_db()
    async with conn.execute(
        "SELECT user_id FROM privacy_rights_requests WHERE id=?", (request_id,)
    ) as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else None


async def mark_answered(request_id: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    conn = await db.get_db()
    async with db._db_lock:
        cur = await conn.execute(
            "UPDATE privacy_rights_requests SET status='answered', answered_at=? "
            "WHERE id=? AND status='open'",
            (now.strftime(FMT), request_id),
        )
        await conn.commit()
    return cur.rowcount > 0


async def purge_old(now: datetime | None = None) -> int:
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)).strftime(FMT)
    conn = await db.get_db()
    async with db._db_lock:
        cur = await conn.execute(
            "DELETE FROM privacy_rights_requests WHERE status='answered' AND answered_at < ?",
            (cutoff,),
        )
        await conn.commit()
    return max(cur.rowcount, 0)


async def delete_of_user(user_id: int) -> int:
    """Al eliminar los datos de una persona también se borran sus solicitudes de derechos."""
    conn = await db.get_db()
    async with db._db_lock:
        cur = await conn.execute("DELETE FROM privacy_rights_requests WHERE user_id=?", (user_id,))
        await conn.commit()
    return max(cur.rowcount, 0)
