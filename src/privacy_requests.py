"""Solicitudes de eliminación del Centro de Privacidad: cola persistente, procesamiento
diferido y registro verificable.

Qué garantiza:
  - Una solicitud vive en la base (privacy_requests): sobrevive a reinicios. Si el proceso
    cae a mitad de un intento, el arrendamiento (`locked_until`) vence y otro ciclo la
    retoma; nunca queda "procesando" para siempre.
  - Plazo máximo de 7 días naturales (`due_at`). Los fallos se reintentan con espera
    creciente hasta lograrlo; ni un fallo ni un reinicio cancelan la solicitud.
  - A lo sumo UNA solicitud abierta por persona (índice único parcial): pedir dos veces no
    duplica trabajo.
  - Cada paso queda en privacy_request_log, solo-añadir y encadenado por hash. El registro
    NO lleva ids de persona ni contenido: request_id, fecha, evento y conteos.
    `verify_log()` detecta una fila cambiada, quitada o intercalada.
  - El borrado en sí es el de siempre (generation.forget_user -> db.delete_user_data), que
    además escribe la lápida que el registro externo de eliminaciones exporta.

Los avisos al titular (fallo, plazo próximo, plazo vencido) se calculan acá (`pending_alerts`)
y se envían con privacy_alerts; una marca de "aviso enviado" solo se guarda si el envío
tuvo éxito, así que un aviso que no pudo salir se reintenta en el siguiente ciclo.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import db

log = logging.getLogger(__name__)

REQUEST_DEADLINE_DAYS = 7
DUE_SOON_HOURS = 48
LEASE_MINUTES = 10
OVERDUE_REPEAT_HOURS = 24
# Una solicitud terminada se conserva este tiempo (rendición de cuentas) y luego se borra;
# el registro encadenado no lleva ids de persona, así que puede conservarse entero.
RETENTION_DAYS = 90
BACKOFF_MINUTES = (1, 5, 30, 120, 360)
GENESIS_HASH = "0" * 64
FMT = "%Y-%m-%d %H:%M:%S"

OPEN_STATUSES = ("pending", "processing", "failed")


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(FMT)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def chain_hash(prev_hash: str, request_id: int, at: str, event: str, detail: str) -> str:
    return hashlib.sha256(
        f"{prev_hash}|{request_id}|{at}|{event}|{detail}".encode()
    ).hexdigest()


def _detail(data: dict | None) -> str:
    return json.dumps(data or {}, sort_keys=True, separators=(",", ":"))


async def _append_log(conn, request_id: int, event: str, data: dict | None, at: str):
    """Añade una fila al registro. Siempre dentro del `async with db._db_lock` del
    llamador: leer el último hash y escribir el siguiente es una sola transacción."""
    async with conn.execute(
        "SELECT hash FROM privacy_request_log ORDER BY seq DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    prev = row[0] if row else GENESIS_HASH
    detail = _detail(data)
    await conn.execute(
        "INSERT INTO privacy_request_log (request_id, at, event, detail, prev_hash, hash) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, at, event, detail, prev, chain_hash(prev, request_id, at, event, detail)),
    )


def append_log_sync(conn, request_id: int, event: str, data: dict | None, at: str):
    """Igual que _append_log pero con la conexión síncrona de pgsync (scripts de
    restauración, que corren con el bot parado)."""
    row = conn.execute(
        "SELECT hash FROM privacy_request_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    prev = row[0] if row else GENESIS_HASH
    detail = _detail(data)
    conn.execute(
        "INSERT INTO privacy_request_log (request_id, at, event, detail, prev_hash, hash) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, at, event, detail, prev, chain_hash(prev, request_id, at, event, detail)),
    )


# Todas las consultas son literales completos (el proyecto prohíbe armar SQL con f-strings).
_SQL_OPEN_OF_USER = (
    "SELECT id, user_id, kind, status, source, created_at, due_at, next_attempt_at, "
    "attempts, last_error, completed_at FROM privacy_requests "
    "WHERE user_id=? AND kind='delete' AND status <> 'completed'"
)
_SQL_DUE = (
    "SELECT id, user_id, kind, status, source, created_at, due_at, next_attempt_at, "
    "attempts, last_error, completed_at FROM privacy_requests WHERE "
    "(status IN ('pending','failed') AND next_attempt_at <= ?) "
    "OR (status = 'processing' AND locked_until <= ?) "
    "ORDER BY due_at, id LIMIT ?"
)
_SQL_ALERT_FAILED = (
    "SELECT id, user_id, kind, status, source, created_at, due_at, next_attempt_at, "
    "attempts, last_error, completed_at FROM privacy_requests "
    "WHERE status='failed' AND notified_failed_at IS NULL ORDER BY id"
)
_SQL_ALERT_DUE_SOON = (
    "SELECT id, user_id, kind, status, source, created_at, due_at, next_attempt_at, "
    "attempts, last_error, completed_at FROM privacy_requests "
    "WHERE status <> 'completed' AND due_at > ? AND due_at <= ? "
    "AND notified_due_soon_at IS NULL ORDER BY id"
)
_SQL_ALERT_OVERDUE = (
    "SELECT id, user_id, kind, status, source, created_at, due_at, next_attempt_at, "
    "attempts, last_error, completed_at FROM privacy_requests "
    "WHERE status <> 'completed' AND due_at <= ? "
    "AND (notified_overdue_at IS NULL OR notified_overdue_at <= ?) ORDER BY id"
)


def _row(r) -> dict:
    keys = (
        "id user_id kind status source created_at due_at next_attempt_at "
        "attempts last_error completed_at"
    ).split()
    return dict(zip(keys, r))


async def create_request(
    user_id: int, source: str = "api", now: datetime | None = None
) -> tuple[dict, bool]:
    """Crea la solicitud de borrado de `user_id` o devuelve la que ya esté abierta.
    Devuelve (solicitud, creada)."""
    now = _now(now)
    conn = await db.get_db()
    async with db._db_lock:
        async with conn.execute(_SQL_OPEN_OF_USER, (user_id,)) as cur:
            existing = await cur.fetchone()
        if existing:
            return _row(existing), False
        due = now + timedelta(days=REQUEST_DEADLINE_DAYS)
        await conn.execute(
            "INSERT INTO privacy_requests (user_id, kind, status, source, created_at, "
            "due_at, next_attempt_at) VALUES (?, 'delete', 'pending', ?, ?, ?, ?)",
            (user_id, source, _ts(now), _ts(due), _ts(now)),
        )
        async with conn.execute(_SQL_OPEN_OF_USER, (user_id,)) as cur:
            created = _row(await cur.fetchone())
        await _append_log(
            conn,
            created["id"],
            "created",
            {"source": source, "due_at": created["due_at"]},
            _ts(now),
        )
        await conn.commit()
    return created, True


async def claim_due(limit: int = 5, now: datetime | None = None) -> list[dict]:
    """Toma las solicitudes que toca intentar: pendientes o fallidas cuyo próximo intento
    ya llegó, y las "procesando" cuyo arrendamiento venció (el proceso cayó a medias)."""
    now = _now(now)
    now_t = _ts(now)
    claimed: list[dict] = []
    conn = await db.get_db()
    async with db._db_lock:
        async with conn.execute(_SQL_DUE, (now_t, now_t, limit)) as cur:
            rows = [_row(r) for r in await cur.fetchall()]
        for req in rows:
            if req["status"] == "processing":
                await _append_log(conn, req["id"], "lease_expired", {}, now_t)
            attempt = req["attempts"] + 1
            await conn.execute(
                "UPDATE privacy_requests SET status='processing', attempts=?, "
                "locked_until=? WHERE id=?",
                (attempt, _ts(now + timedelta(minutes=LEASE_MINUTES)), req["id"]),
            )
            await _append_log(conn, req["id"], "attempt_started", {"attempt": attempt}, now_t)
            req["attempts"] = attempt
            claimed.append(req)
        await conn.commit()
    return claimed


async def complete(
    request_id: int, report: dict, now: datetime | None = None, attempt: int | None = None
) -> bool:
    """Cierra la solicitud. `attempt` es el intento que la tomó (token de control): si otro
    intento la retomó mientras tanto (arrendamiento vencido) o ya está cerrada, no hace nada y
    devuelve False. El borrado es idempotente, así que el intento perdedor no deja daño."""
    now_t = _ts(_now(now))
    counts = {
        k: v
        for k, v in report.items()
        if k.endswith(("_deleted", "_pseudonymized")) and isinstance(v, int)
    }
    counts["guilds"] = len(report.get("guild_ids", []))
    conn = await db.get_db()
    async with db._db_lock:
        if attempt is None:
            cur = await conn.execute(
                "UPDATE privacy_requests SET status='completed', completed_at=?, "
                "locked_until=NULL, last_error=NULL WHERE id=? AND status='processing'",
                (now_t, request_id),
            )
        else:
            cur = await conn.execute(
                "UPDATE privacy_requests SET status='completed', completed_at=?, "
                "locked_until=NULL, last_error=NULL "
                "WHERE id=? AND status='processing' AND attempts=?",
                (now_t, request_id, attempt),
            )
        if cur.rowcount != 1:
            await conn.commit()
            return False
        await _append_log(conn, request_id, "completed", counts, now_t)
        await conn.commit()
    return True


async def fail(
    request_id: int,
    error: Exception,
    now: datetime | None = None,
    attempt: int | None = None,
) -> bool:
    """Registra un intento fallido y programa el siguiente con espera creciente. Solo se
    guarda el NOMBRE de la excepción: su mensaje podría llevar datos. Con `attempt`, un intento
    desplazado por otro (o una solicitud ya cerrada) no la degrada: devuelve False."""
    now = _now(now)
    name = type(error).__name__[:80]
    conn = await db.get_db()
    async with db._db_lock:
        async with conn.execute(
            "SELECT attempts, status FROM privacy_requests WHERE id=?", (request_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row or row[1] != "processing" or (attempt is not None and int(row[0]) != attempt):
            await conn.commit()
            return False
        attempts = int(row[0])
        wait = BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES)) - 1]
        nxt = _ts(now + timedelta(minutes=wait))
        await conn.execute(
            "UPDATE privacy_requests SET status='failed', last_error=?, "
            "next_attempt_at=?, locked_until=NULL WHERE id=?",
            (name, nxt, request_id),
        )
        await _append_log(
            conn,
            request_id,
            "attempt_failed",
            {"attempt": attempts, "error": name, "next_attempt_at": nxt},
            _ts(now),
        )
        await conn.commit()
    return True


async def process_due(forget, *, limit: int = 5, now: datetime | None = None) -> dict:
    """Un ciclo del trabajador. `forget` es generation.forget_user (borra, escribe la
    lápida e invalida cachés). Devuelve cuántas se completaron y cuántas fallaron."""
    done = failed = 0
    for req in await claim_due(limit, now):
        try:
            report = await forget(req["user_id"])
        except Exception as e:
            log.exception("privacy_requests: falló el intento de la solicitud %s", req["id"])
            if await fail(req["id"], e, now, req["attempts"]):
                failed += 1
        else:
            if await complete(req["id"], report, now, req["attempts"]):
                done += 1
    return {"completed": done, "failed": failed}


async def pending_alerts(now: datetime | None = None) -> list[dict]:
    """Avisos que toca enviar al titular, cada uno con su `kind`:
    failed (hubo un fallo y no se avisó), due_soon (faltan <48 h) y overdue (venció;
    se repite cada 24 h hasta completarse)."""
    now = _now(now)
    now_t = _ts(now)
    soon_t = _ts(now + timedelta(hours=DUE_SOON_HOURS))
    again_t = _ts(now - timedelta(hours=OVERDUE_REPEAT_HOURS))
    conn = await db.get_db()
    out: list[dict] = []
    queries = (
        ("failed", _SQL_ALERT_FAILED, ()),
        ("due_soon", _SQL_ALERT_DUE_SOON, (now_t, soon_t)),
        ("overdue", _SQL_ALERT_OVERDUE, (now_t, again_t)),
    )
    for kind, sql, params in queries:
        async with conn.execute(sql, params) as cur:
            for r in await cur.fetchall():
                out.append({**_row(r), "kind": kind})  # el tipo de AVISO manda
    return out


_ALERT_UPDATE = {
    "failed": "UPDATE privacy_requests SET notified_failed_at=? WHERE id=?",
    "due_soon": "UPDATE privacy_requests SET notified_due_soon_at=? WHERE id=?",
    "overdue": "UPDATE privacy_requests SET notified_overdue_at=? WHERE id=?",
}


async def mark_alert_sent(request_id: int, kind: str, now: datetime | None = None) -> None:
    now_t = _ts(_now(now))
    conn = await db.get_db()
    async with db._db_lock:
        await conn.execute(_ALERT_UPDATE[kind], (now_t, request_id))
        await _append_log(conn, request_id, "alert_sent", {"kind": kind}, now_t)
        await conn.commit()


async def dispatch_alerts(send, now: datetime | None = None) -> int:
    """Envía los avisos pendientes con `send(alert) -> bool`. Solo marca como enviado lo
    que `send` confirmó; lo demás se reintenta en el siguiente ciclo."""
    sent = 0
    for alert in await pending_alerts(now):
        try:
            ok = await send(alert)
        except Exception:
            log.exception("privacy_requests: falló el envío del aviso %s", alert["kind"])
            ok = False
        if ok:
            await mark_alert_sent(alert["id"], alert["kind"], now)
            sent += 1
    return sent


async def user_requests(user_id: int) -> list[dict]:
    """Solicitudes de la persona, para la API. Sin `last_error` ni datos internos."""
    conn = await db.get_db()
    async with conn.execute(
        "SELECT id, status, created_at, due_at, completed_at, attempts "
        "FROM privacy_requests WHERE user_id=? ORDER BY id DESC",
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    keys = ("id", "status", "created_at", "due_at", "completed_at", "attempts")
    return [dict(zip(keys, r)) for r in rows]


async def request_log(request_id: int) -> list[dict]:
    conn = await db.get_db()
    async with conn.execute(
        "SELECT seq, at, event, detail FROM privacy_request_log "
        "WHERE request_id=? ORDER BY seq",
        (request_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {"seq": r[0], "at": r[1], "event": r[2], "detail": json.loads(r[3])}
        for r in rows
    ]


def verify_chain(rows) -> dict:
    """Recalcula la cadena sobre filas (seq, request_id, at, event, detail, prev_hash, hash)
    ordenadas por seq. {"ok", "rows", "bad_seq"}: bad_seq es la primera fila cuyo hash o
    enlace no coincide (cambiada, quitada o intercalada)."""
    prev = GENESIS_HASH
    for seq, request_id, at, event, detail, prev_hash, h in rows:
        if prev_hash != prev or h != chain_hash(prev, request_id, at, event, detail):
            return {"ok": False, "rows": len(rows), "bad_seq": seq}
        prev = h
    return {"ok": True, "rows": len(rows), "bad_seq": None}


def check_anchors(rows, anchors) -> dict:
    """Compara la cadena de la base con ANCLAS (seq, hash) exportadas fuera del servidor.

    Una cadena reescrita entera es internamente coherente (verify_chain no lo ve), pero cambia
    el hash de las filas anteriores a la reescritura: no coincidirá con lo que ya se exportó.
      - altered: la fila ancla falta o su hash difiere, o la cadena no cierra.
      - ahead:   el ancla es posterior al final de la base (restauración antigua o cola borrada;
                 no se puede distinguir, hay que mirar el contexto).
    Una fila posterior al último ancla exportado queda sin cubrir hasta la siguiente instantánea
    (como máximo, una hora)."""
    chain = verify_chain(rows)
    by_seq = {r[0]: r[6] for r in rows}
    last = max(by_seq) if by_seq else 0
    altered, ahead, matched = [], [], 0
    for seq, h in anchors:
        if seq > last:
            ahead.append(seq)
        elif by_seq.get(seq) != h:
            altered.append(seq)
        else:
            matched += 1
    return {
        "chain_ok": chain["ok"],
        "chain_bad_seq": chain["bad_seq"],
        "anchors": len(anchors),
        "matched": matched,
        "altered": altered,
        "ahead": ahead,
        "ok": chain["ok"] and not altered,
    }


async def verify_log() -> dict:
    """Recalcula la cadena completa de la base (ver verify_chain)."""
    conn = await db.get_db()
    async with conn.execute(
        "SELECT seq, request_id, at, event, detail, prev_hash, hash "
        "FROM privacy_request_log ORDER BY seq"
    ) as cur:
        rows = await cur.fetchall()
    return verify_chain(rows)


async def purge_old(now: datetime | None = None) -> int:
    """Borra las solicitudes terminadas hace más de RETENTION_DAYS. El registro no se toca."""
    limit_t = _ts(_now(now) - timedelta(days=RETENTION_DAYS))
    conn = await db.get_db()
    async with db._db_lock:
        cur = await conn.execute(
            "DELETE FROM privacy_requests WHERE status='completed' AND completed_at < ?",
            (limit_t,),
        )
        n = cur.rowcount
        await conn.commit()
    return n
