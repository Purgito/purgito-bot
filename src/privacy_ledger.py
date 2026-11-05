"""Instantánea del registro de eliminaciones y exclusiones de privacidad.

Para qué sirve: al restaurar un backup anterior a un borrado, los datos borrados
vuelven. Las lápidas de la base (deleted_user_tombstones, purged_guild_tombstones)
evitan eso solo mientras la base sobreviva; si se pierde la base, se pierden
también las lápidas. Esta instantánea se exporta cifrada FUERA del servidor
(R2, ver scripts/export_privacy_ledger.py) y scripts/reapply_deletions.py --ledger
la vuelve a aplicar después de un restore, antes de arrancar el bot.

Qué contiene (solo identificadores y fechas, nada de contenido de mensajes):
  - lápidas vigentes de usuarios (/borrar_mis_datos) y de servidores purgados;
  - las exclusiones activas (excluded_users): son preferencias del usuario, y un
    restore anterior a su elección las perdería.

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
    )


def snapshot_from_rows(
    users, guilds, exclusions, now: datetime | None = None
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
    out.append(
        {
            "type": "footer",
            "counts": {
                "user_tombstone": len(users),
                "guild_tombstone": len(guilds),
                "exclusion": len(exclusions),
            },
        }
    )
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
    kinds = {"user_tombstone": [], "guild_tombstone": [], "exclusion": []}
    for rec in records[1:-1]:
        kind = rec.get("type")
        if kind not in kinds:
            raise LedgerError(f"registro desconocido: {kind!r}")
        kinds[kind].append(rec)
    for kind, items in kinds.items():
        if foot.get("counts", {}).get(kind) != len(items):
            raise LedgerError(f"el pie no coincide con los registros de {kind}")
    for rec in kinds["user_tombstone"]:
        _require_int(rec, "user_id")
    for rec in kinds["guild_tombstone"]:
        _require_int(rec, "guild_id")
    for rec in kinds["exclusion"]:
        _require_int(
            rec, "guild_id", "user_id", "exclude_interaction", "exclude_learning"
        )
    return {
        "exported_at": head.get("exported_at", ""),
        "user_tombstones": kinds["user_tombstone"],
        "guild_tombstones": kinds["guild_tombstone"],
        "exclusions": kinds["exclusion"],
    }


def _require_int(rec: dict, *fields: str) -> None:
    for f in fields:
        if not isinstance(rec.get(f), int) or isinstance(rec.get(f), bool):
            raise LedgerError(f"{rec.get('type')}: {f} no es un entero")
