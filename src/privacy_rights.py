"""Solicitudes de derechos que el Centro de Privacidad no resuelve solo.

Descargar los datos, excluirse del aprendizaje y pedir la eliminación son automáticos
(privacy_requests, /api/me/privacy). Lo demás -- acceso más allá de la descarga, rectificación,
oposición, portabilidad, bloqueo temporal u otra consulta -- lo atiende una persona.

Se sigue el artículo 11 de la Ley 21.719 (texto oficial en leychile.cl, idNorma 1209272):
  - el acuse de recibo es inmediato (la solicitud queda numerada y fechada en el Centro);
  - respuesta por escrito dentro de 30 días corridos (la ley permite prorrogar UNA vez hasta 30 más;
    Purgito se compromete a no pasar de 30 y, si no pudiera, la prórroga se avisa a la persona);
  - el bloqueo temporal se responde dentro de 2 días hábiles (aquí: 2 días corridos, siempre ≤ al plazo legal);
  - se guarda copia de la respuesta (texto y fecha) para poder demostrarla; si se deniega, la respuesta
    funda la decisión e informa el plazo de 30 días hábiles para reclamar ante la Agencia.
Solo se guarda lo mínimo: quién (el id de la sesión, nunca un valor enviado por el cliente), qué derecho, un
comentario opcional corto, un correo opcional para la respuesta (se borra al contestar) y las fechas.
Las contestadas se borran a los 90 días.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import db

log = logging.getLogger(__name__)

DEADLINE_DAYS = 30
BLOCKING_DEADLINE_DAYS = 2
RETENTION_DAYS = 90
NOTE_MAX = 1000
EMAIL_MAX = 254
MAX_OPEN_PER_USER = 5
RIGHT_KINDS = ("access", "rectification", "objection", "portability", "blocking", "other")
FMT = "%Y-%m-%d %H:%M:%S"
_COLS = "id, right_kind, note, status, created_at, due_at, answered_at, response_text"
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")

DENIAL_NOTICE = (
    "Si no estás de acuerdo con esta decisión, dispones de un plazo de treinta días hábiles para formular "
    "una reclamación ante la Agencia de Protección de Datos Personales (artículo 11 de la Ley N.º 21.719)."
)


class RightsError(ValueError):
    """Entrada no válida (derecho desconocido, comentario o correo no válidos, demasiadas abiertas)."""


def deadline_days(right_kind: str) -> int:
    return BLOCKING_DEADLINE_DAYS if right_kind == "blocking" else DEADLINE_DAYS


def _row(r) -> dict:
    return {
        "id": r[0],
        "right": r[1],
        "note": r[2],
        "status": r[3],
        "created_at": r[4],
        "due_at": r[5],
        "answered_at": r[6],
        "response": r[7],
    }


async def create(
    user_id: int,
    right_kind: str,
    note: str = "",
    reply_email: str | None = None,
    now: datetime | None = None,
) -> dict:
    if right_kind not in RIGHT_KINDS:
        raise RightsError("derecho no válido")
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise RightsError("comentario demasiado largo")
    reply_email = (reply_email or "").strip() or None
    if reply_email is not None and (len(reply_email) > EMAIL_MAX or not _EMAIL_RE.match(reply_email)):
        raise RightsError("correo no válido")
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
            "INSERT INTO privacy_rights_requests "
            "(user_id, right_kind, note, status, created_at, due_at, reply_email) "
            "VALUES (?, ?, ?, 'open', ?, ?, ?)",
            (
                user_id,
                right_kind,
                note,
                now.strftime(FMT),
                (now + timedelta(days=deadline_days(right_kind))).strftime(FMT),
                reply_email,
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


async def requester_of(request_id: int) -> tuple[int, str | None] | None:
    """(id de Discord, correo opcional) para que el operador conteste; nunca se expone por la API."""
    conn = await db.get_db()
    async with conn.execute(
        "SELECT user_id, reply_email FROM privacy_rights_requests WHERE id=?", (request_id,)
    ) as cur:
        row = await cur.fetchone()
    return (int(row[0]), row[1]) if row else None


async def mark_answered(
    request_id: int,
    response_text: str,
    *,
    denied: bool = False,
    now: datetime | None = None,
) -> bool:
    """Cierra la solicitud guardando la respuesta (texto y fecha) y borrando el correo. Si se deniega,
    añade el aviso del plazo para reclamar ante la Agencia (Ley 21.719 art. 11)."""
    text = (response_text or "").strip()
    if not text:
        raise RightsError("la respuesta no puede estar vacía")
    if denied:
        text = f"{text}\n\n{DENIAL_NOTICE}"
    now = now or datetime.now(timezone.utc)
    conn = await db.get_db()
    async with db._db_lock:
        cur = await conn.execute(
            "UPDATE privacy_rights_requests SET status=?, answered_at=?, response_text=?, reply_email=NULL "
            "WHERE id=? AND status='open'",
            ("denied" if denied else "answered", now.strftime(FMT), text, request_id),
        )
        await conn.commit()
    return cur.rowcount > 0


async def purge_old(now: datetime | None = None) -> int:
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)).strftime(FMT)
    conn = await db.get_db()
    async with db._db_lock:
        cur = await conn.execute(
            "DELETE FROM privacy_rights_requests WHERE status IN ('answered','denied') AND answered_at < ?",
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
