"""Compara el estado real de las suscripciones en Polar contra la tabla local
premium_guilds y reporta discrepancias. Herramienta de mantenimiento manual,
no la corre el bot -- de solo lectura, nunca escribe nada (ni acá ni en Polar).

    python scripts/reconcile_premium.py

## Por qué existe

_webhook_polar (src/webapi.py) mantiene premium_guilds al día reaccionando a
los webhooks de Polar. Si un webhook nunca llega -- el server estuvo caído
más tiempo del que Polar reintenta, o algo falló entre medio de forma que ni
siquiera quedó loggeado -- no hay ninguna otra señal que lo note: el guild
queda desincronizado hasta que alguien lo descubre a mano. Este script es esa
segunda señal: lista las suscripciones activas reales en Polar y las compara
contra lo que tenemos guardado.

## Qué reporta

- "Activa en Polar, no premium acá": probablemente un webhook de activación
  que nunca llegó o falló. Candidato a agregar con set_premium.
- "Premium acá, no aparece activa en Polar": probablemente un webhook de
  baja que nunca llegó o falló -- pero también puede ser premium otorgado a
  mano (soporte, cortesía) que nunca pasó por Polar. No asumas que hay que
  borrarlo sin revisar el guild primero.

PURGATORY_GUILD_ID (siempre premium, no facturado por Polar) se excluye del
reporte: no está en Polar a propósito.

## Por qué no tiene --apply

Corregir premium_guilds a ciegas según lo que diga Polar es arriesgado: un
falso positivo acá le cortaría el servicio a un cliente que sí pagó. Este
script es de detección, no de corrección -- la corrección la aplica el dueño
del bot a mano (con /premium o el panel) después de revisar cada caso.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import config  # noqa: E402

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db"
)


def _active_guild_ids_from_polar(client) -> dict[int, str]:
    """guild_id -> subscription_id de cada suscripción activa en Polar con
    metadata.guild_id válido. Filtra por los product_id configurados si
    están seteados; si no, trae cualquier suscripción activa de la org."""
    product_ids = [
        p
        for p in (config.POLAR_PRODUCT_ID_MONTHLY, config.POLAR_PRODUCT_ID_ANNUAL)
        if p
    ]
    kwargs = {"active": True, "limit": 100}
    if product_ids:
        kwargs["product_id"] = product_ids

    found: dict[int, str] = {}
    resp = client.subscriptions.list(**kwargs)
    while resp is not None:
        for sub in resp.result.items:
            metadata = getattr(sub, "metadata", None) or {}
            raw_guild_id = (
                metadata.get("guild_id") if isinstance(metadata, dict) else None
            )
            try:
                guild_id = int(raw_guild_id)
            except (TypeError, ValueError):
                print(
                    f"  AVISO: suscripción {sub.id} activa sin guild_id "
                    f"válido en metadata ({raw_guild_id!r}) -- no se puede reconciliar"
                )
                continue
            found[guild_id] = sub.id
        resp = resp.next()
    return found


def _local_premium_guild_ids(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT guild_id FROM premium_guilds").fetchall()
    return {r[0] for r in rows}


def reconcile(client, conn: sqlite3.Connection) -> dict:
    polar_active = _active_guild_ids_from_polar(client)
    local_premium = _local_premium_guild_ids(conn)

    polar_only = {
        gid: sub_id for gid, sub_id in polar_active.items() if gid not in local_premium
    }
    permanent_ids = getattr(config, "PERMANENT_PREMIUM_GUILD_IDS", {config.PURGATORY_GUILD_ID})
    local_only = local_premium - set(polar_active) - permanent_ids - {config.PURGATORY_GUILD_ID}

    print(f"Polar: {len(polar_active)} suscripción(es) activa(s) con guild_id válido")
    print(f"Local: {len(local_premium)} guild(s) marcados premium en premium_guilds")
    print()

    if polar_only:
        print(f"Activa(s) en Polar, NO premium acá ({len(polar_only)}):")
        for gid, sub_id in sorted(polar_only.items()):
            print(f"  guild {gid}  (subscription {sub_id})")
    else:
        print("Ninguna suscripción activa en Polar está sin reflejar acá. Bien.")
    print()

    if local_only:
        print(f"Premium acá, NO aparece activa en Polar ({len(local_only)}):")
        for gid in sorted(local_only):
            print(
                f"  guild {gid}  -- revisar antes de tocar: puede ser cortesía manual"
            )
    else:
        print("Ningún guild premium acá está desalineado con Polar. Bien.")

    return {"polar_only": polar_only, "local_only": local_only}


def main() -> int:
    if not config.POLAR_ACCESS_TOKEN:
        print("POLAR_ACCESS_TOKEN no está configurado -- nada para reconciliar.")
        return 1

    from polar_sdk import Polar

    client = Polar(access_token=config.POLAR_ACCESS_TOKEN, server=config.POLAR_SERVER)
    conn = sqlite3.connect(DB_PATH)
    try:
        result = reconcile(client, conn)
    finally:
        conn.close()
    return 1 if (result["polar_only"] or result["local_only"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
