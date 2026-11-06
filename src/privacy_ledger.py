"""Instantánea del registro de eliminaciones y exclusiones de privacidad.

Para qué sirve: al restaurar un backup anterior a un borrado, los datos borrados
vuelven. Las lápidas de la base (deleted_user_tombstones, purged_guild_tombstones)
evitan eso solo mientras la base sobreviva; si se pierde la base, se pierden
también las lápidas. Esta instantánea se exporta cifrada FUERA del servidor
(R2, ver scripts/export_privacy_ledger.py) y scripts/reapply_deletions.py --ledger
la vuelve a aplicar después de un restore, antes de arrancar el bot.

Qué contiene (solo identificadores y fechas, nada de contenido de mensajes):
  - lápidas vigentes de usuarios (eliminación de datos (Centro de Privacidad)) y de servidores purgados;
  - las exclusiones activas (excluded_users), incluida la global (guild_id = 0): son
    preferencias del usuario, y un restore anterior a su elección las perdería;
  - las solicitudes de eliminación del Centro de Privacidad que siguen ABIERTAS
    (privacy_requests): usuario y fechas, para que un restore no pierda una solicitud
    que aún no se había procesado. Las completadas ya están en la lápida del usuario;
  - las lápidas vigentes de MENSAJES sueltos y de CANALES eliminados (solo ids y fechas). Si un
    servidor acumula más de lo que cabe (MAX_MESSAGE_TOMBSTONES en total), sus lápidas individuales se
    SUSTITUYEN por un corte por servidor (`guild_cutoff`): al restaurar se borra todo el corpus de ese
    servidor aprendido antes del corte. Sobre-borra a propósito: nunca deja reaparecer un mensaje;
  - el ANCLA del registro encadenado de solicitudes (`log_anchor`: último seq y su hash). La
    instantánea se guarda fuera del servidor con credenciales que el bot no tiene, así que quien
    reescriba toda la cadena en la base no puede reescribir también las anclas ya exportadas
    (scripts/verify_privacy_log.py las compara).

Cuánto dura cada cosa (justificación en docs/PRIVACY.md):
  - una lápida, 15 días (DELETION_TOMBSTONE_RETENTION_DAYS): 14 de antigüedad
    máxima de un backup + 1 de margen. La instantánea solo lleva las vigentes, así
    que cada identificador sale de ella a más tardar con su lápida;
  - cada instantánea en R2, 15 días como máximo (siempre quedan las 3 últimas);
  - una exclusión, mientras la persona la mantenga activa.

Formato: JSON Lines. Primera línea `header`, última `footer` con los conteos (una
instantánea truncada se rechaza al leerla).
"""

import json
from datetime import datetime, timezone

SNAPSHOT_VERSION = 1
_TS_FMT = "%Y-%m-%d %H:%M:%S"


class LedgerError(ValueError):
    """La instantánea está corrupta, truncada o es de una versión desconocida."""


def _now_text(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime(_TS_FMT)


USERS_SQL = (
    "SELECT user_id, deleted_at, expires_at FROM deleted_user_tombstones "
    "WHERE expires_at > {now} ORDER BY user_id"
)
GUILDS_SQL = (
    "SELECT purged_guild_id, purged_at, expires_at FROM purged_guild_tombstones "
    "WHERE expires_at > {now} ORDER BY purged_guild_id"
)
EXCLUSIONS_SQL = (
    "SELECT guild_id, user_id, exclude_interaction, exclude_learning, created_at "
    "FROM excluded_users ORDER BY guild_id, user_id"
)


REQUESTS_SQL = (
    "SELECT user_id, created_at, due_at FROM privacy_requests "
    "WHERE status <> 'completed' ORDER BY id"
)


# Tope de lápidas de mensajes individuales por instantánea (~80 bytes cada una: unos 8 MB sin
# comprimir). Lo que exceda se resuelve con cortes por servidor, no se trunca.
MAX_MESSAGE_TOMBSTONES = 100_000
# Defensa final de la consulta: si se alcanza, la instantánea se marca `truncated` y la restauración
# se niega a seguir (no debería ocurrir: son 15 días de borrados de mensajes).
HARD_MESSAGE_ROWS = 1_000_000

MESSAGES_SQL = (
    "SELECT guild_id, message_id, deleted_at, expires_at FROM deleted_message_tombstones "
    "WHERE expires_at > {now} ORDER BY guild_id, message_id LIMIT " + str(HARD_MESSAGE_ROWS + 1)
)
CHANNELS_SQL = (
    "SELECT guild_id, channel_id, deleted_at, expires_at FROM deleted_channel_tombstones "
    "WHERE expires_at > {now} ORDER BY guild_id, channel_id"
)
ANCHOR_SQL = "SELECT seq, hash FROM privacy_request_log ORDER BY seq DESC LIMIT 1"


def build_snapshot(conn, now: datetime | None = None) -> list[dict]:
    """Registros de la instantánea a partir de una conexión síncrona de pgsync (tests y
    herramientas del checkout). Solo lápidas vigentes (`expires_at > ahora`)."""
    now = now or datetime.now(timezone.utc)
    now_text = _now_text(now)
    return snapshot_from_rows(
        conn.execute(USERS_SQL.format(now="?"), (now_text,)).fetchall(),
        conn.execute(GUILDS_SQL.format(now="?"), (now_text,)).fetchall(),
        conn.execute(EXCLUSIONS_SQL).fetchall(),
        now,
        conn.execute(REQUESTS_SQL).fetchall(),
        conn.execute(MESSAGES_SQL.format(now="?"), (now_text,)).fetchall(),
        conn.execute(CHANNELS_SQL.format(now="?"), (now_text,)).fetchall(),
        conn.execute(ANCHOR_SQL).fetchall(),
    )


def snapshot_from_rows(
    users,
    guilds,
    exclusions,
    now: datetime | None = None,
    requests=(),
    messages=(),
    channels=(),
    anchor=(),
) -> list[dict]:
    """Registros de la instantánea (header, datos, footer) a partir de las filas de las
    tres consultas (USERS_SQL, GUILDS_SQL, EXCLUSIONS_SQL). No depende de ningún driver:
    el exportador del runner aislado las obtiene con `psql`."""
    now = now or datetime.now(timezone.utc)
    now_text = _now_text(now)
    out: list[dict] = [
        {"type": "header", "version": SNAPSHOT_VERSION, "exported_at": now_text}
    ]
    out += [
        {
            "type": "user_tombstone",
            "user_id": int(r[0]),
            "deleted_at": str(r[1]),
            "expires_at": str(r[2]),
        }
        for r in users
    ]
    out += [
        {
            "type": "guild_tombstone",
            "guild_id": int(r[0]),
            "purged_at": str(r[1]),
            "expires_at": str(r[2]),
        }
        for r in guilds
    ]
    out += [
        {
            "type": "exclusion",
            "guild_id": int(r[0]),
            "user_id": int(r[1]),
            "exclude_interaction": int(r[2]),
            "exclude_learning": int(r[3]),
            "created_at": str(r[4]),
        }
        for r in exclusions
    ]
    out += [
        {
            "type": "deletion_request",
            "user_id": int(r[0]),
            "created_at": str(r[1]),
            "due_at": str(r[2]),
        }
        for r in requests
    ]
    # Más filas que el tope duro: no se puede garantizar nada -> se marca y la restauración se niega.
    truncated = len(messages) > HARD_MESSAGE_ROWS
    messages = list(messages)[:HARD_MESSAGE_ROWS]
    # Desbordamiento: los servidores con más lápidas pasan a un corte por servidor hasta caber.
    per_guild: dict[int, int] = {}
    for r in messages:
        per_guild[int(r[0])] = per_guild.get(int(r[0]), 0) + 1
    cut_guilds: set[int] = set()
    total = len(messages)
    for gid, n in sorted(per_guild.items(), key=lambda kv: (-kv[1], kv[0])):
        if total <= MAX_MESSAGE_TOMBSTONES:
            break
        cut_guilds.add(gid)
        total -= n
    cutoff_at = _now_text(now)
    kept = [r for r in messages if int(r[0]) not in cut_guilds]
    out += [
        {
            "type": "message_tombstone",
            "guild_id": int(r[0]),
            "message_id": int(r[1]),
            "deleted_at": str(r[2]),
            "expires_at": str(r[3]),
        }
        for r in kept
    ]
    cutoffs = [
        {"type": "guild_cutoff", "guild_id": gid, "cutoff": cutoff_at}
        for gid in sorted(cut_guilds)
    ]
    out += cutoffs
    out += [
        {
            "type": "channel_tombstone",
            "guild_id": int(r[0]),
            "channel_id": int(r[1]),
            "deleted_at": str(r[2]),
            "expires_at": str(r[3]),
        }
        for r in channels
    ]
    out += [
        {"type": "log_anchor", "seq": int(r[0]), "hash": str(r[1])} for r in anchor
    ]
    footer = {
        "type": "footer",
        "counts": {
            "user_tombstone": len(users),
            "guild_tombstone": len(guilds),
            "exclusion": len(exclusions),
            "deletion_request": len(requests),
            "message_tombstone": len(kept),
            "guild_cutoff": len(cutoffs),
            "channel_tombstone": len(channels),
            "log_anchor": len(anchor),
        },
    }
    if truncated:
        footer["truncated"] = ["message_tombstone"]
    out.append(footer)
    return out


def dumps(records: list[dict]) -> str:
    return "".join(
        json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in records
    )


def loads(text: str) -> dict:
    """Parsea y valida una instantánea. Devuelve
    {"exported_at", "user_tombstones", "guild_tombstones", "exclusions"}."""
    try:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as e:
        raise LedgerError(f"JSON inválido: {e}") from e
    if len(records) < 2:
        raise LedgerError("instantánea vacía o truncada")
    head, foot = records[0], records[-1]
    if head.get("type") != "header" or head.get("version") != SNAPSHOT_VERSION:
        raise LedgerError("cabecera ausente o versión desconocida")
    if foot.get("type") != "footer":
        raise LedgerError("falta el pie: la instantánea está truncada")
    kinds = {
        "user_tombstone": [],
        "guild_tombstone": [],
        "exclusion": [],
        "deletion_request": [],
        "message_tombstone": [],
        "channel_tombstone": [],
        "guild_cutoff": [],
        "log_anchor": [],
    }
    # Tipos añadidos después de la versión 1: una instantánea anterior no trae su conteo (vale 0).
    optional = {
        "deletion_request",
        "message_tombstone",
        "channel_tombstone",
        "guild_cutoff",
        "log_anchor",
    }
    for rec in records[1:-1]:
        kind = rec.get("type")
        if kind not in kinds:
            raise LedgerError(f"registro desconocido: {kind!r}")
        kinds[kind].append(rec)
    for kind, items in kinds.items():
        # Las instantáneas anteriores a las solicitudes no traen ese conteo: valen 0.
        default = 0 if kind in optional else None
        if foot.get("counts", {}).get(kind, default) != len(items):
            raise LedgerError(f"el pie no coincide con los registros de {kind}")
    for rec in kinds["user_tombstone"]:
        _require_int(rec, "user_id")
    for rec in kinds["guild_tombstone"]:
        _require_int(rec, "guild_id")
    for rec in kinds["exclusion"]:
        _require_int(
            rec, "guild_id", "user_id", "exclude_interaction", "exclude_learning"
        )
    for rec in kinds["deletion_request"]:
        _require_int(rec, "user_id")
    for rec in kinds["message_tombstone"]:
        _require_int(rec, "guild_id", "message_id")
    for rec in kinds["channel_tombstone"]:
        _require_int(rec, "guild_id", "channel_id")
    for rec in kinds["guild_cutoff"]:
        _require_int(rec, "guild_id")
        if not isinstance(rec.get("cutoff"), str):
            raise LedgerError("guild_cutoff: falta la fecha de corte")
    for rec in kinds["log_anchor"]:
        _require_int(rec, "seq")
    return {
        "exported_at": head.get("exported_at", ""),
        "user_tombstones": kinds["user_tombstone"],
        "guild_tombstones": kinds["guild_tombstone"],
        "exclusions": kinds["exclusion"],
        "deletion_requests": kinds["deletion_request"],
        "message_tombstones": kinds["message_tombstone"],
        "channel_tombstones": kinds["channel_tombstone"],
        "guild_cutoffs": kinds["guild_cutoff"],
        "log_anchors": kinds["log_anchor"],
        "truncated": list(foot.get("truncated", [])),
    }


def _require_int(rec: dict, *fields: str) -> None:
    for f in fields:
        if not isinstance(rec.get(f), int) or isinstance(rec.get(f), bool):
            raise LedgerError(f"{rec.get('type')}: {f} no es un entero")
