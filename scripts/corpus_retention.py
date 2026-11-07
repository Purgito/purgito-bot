"""Retención de los mensajes aprendidos: recuento previo y purga controlada (solo conteos, nunca contenido).

    .venv/bin/python scripts/corpus_retention.py                               # ensayo: solo cuenta
    .venv/bin/python scripts/corpus_retention.py --apply --report ruta.json    # cuenta, purga y verifica

Usa el MISMO criterio que la purga diaria del bot (`db.purge_expired_corpus`): `created_at` (cuándo Purgito
aprendió el mensaje, no cuándo se escribió en Discord) anterior a CORPUS_RETENTION_DAYS (30) para el corpus
colectivo y el estilo por usuario; el registro de remitentes de GIF sigue su plazo propio
(GIF_SENDER_RETENTION_DAYS, 180). No toca mensajes originales de Discord, archivos multimedia, cuotas ni
exclusiones. Después de la purga comprueba que no quede nada vencido y que lo borrado coincida con el
recuento previo. Reinicia el bot después para que las cachés de Markov se reconstruyan.
"""

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:  # pragma: no cover
    pass

import config  # noqa: E402
import db  # noqa: E402


async def _oldest(table: str, column: str):
    conn = await db.get_db()
    async with conn.execute(f"SELECT MIN({column}) FROM {table}") as cur:
        return (await cur.fetchone())[0]


async def main_async(apply: bool, report: str | None) -> int:
    days = config.env_int("CORPUS_RETENTION_DAYS", 30)
    gif_days = config.env_int("GIF_SENDER_RETENTION_DAYS", 180)
    await db.init_db()
    try:
        before = await db.count_expired_corpus(days, gif_days)
        before["oldest_corpus_messages"] = await _oldest(
            "corpus_messages", "created_at"
        )
        before["oldest_user_corpus"] = await _oldest("user_corpus", "created_at")
        out = {"days": days, "gif_days": gif_days, "applied": apply, "before": before}
        print(
            f"== {'APLICAR' if apply else 'ENSAYO (no se modificó nada)'}: mensajes {days} días, remitentes de GIF {gif_days} días"
        )
        for k, v in before.items():
            print(f"  antes.{k}: {v}")
        rc = 0
        if apply:
            res = await db.purge_expired_corpus(days, gif_days=gif_days)
            after = await db.count_expired_corpus(days, gif_days)
            after["oldest_corpus_messages"] = await _oldest(
                "corpus_messages", "created_at"
            )
            after["oldest_user_corpus"] = await _oldest("user_corpus", "created_at")
            out["deleted"] = {
                k: res[k] for k in ("corpus_messages", "user_corpus", "gif_senders")
            }
            out["after"] = after
            out["guilds_affected"] = len(res["guild_ids"])
            for k, v in out["deleted"].items():
                print(f"  borrados.{k}: {v}")
            for k, v in after.items():
                print(f"  despues.{k}: {v}")
            expected = {
                k: before[k] for k in ("corpus_messages", "user_corpus", "gif_senders")
            }
            if out["deleted"] != expected:
                print(
                    f"ERROR: lo borrado {out['deleted']} no coincide con el recuento previo {expected}"
                )
                rc = 1
            if after["corpus_messages"] or after["user_corpus"] or after["gif_senders"]:
                print("ERROR: queda material vencido tras la purga")
                rc = 1
            if (
                after["corpus_messages_total"]
                != before["corpus_messages_total"] - before["corpus_messages"]
            ):
                print("ERROR: el total de mensajes no cuadra con lo borrado")
                rc = 1
        if report:
            fd = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1)
        return rc
    finally:
        try:
            await db.close_db()
        except Exception:  # el cierre del pool no debe tapar el resultado
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply",
        action="store_true",
        help="purga de verdad (por defecto, solo cuenta)",
    )
    ap.add_argument("--report", help="JSON 0600 con los conteos (sin contenido)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main_async(a.apply, a.report)))
