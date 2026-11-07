"""Bandeja del operador para las solicitudes de derechos del Centro de Privacidad.

    .venv/bin/python scripts/privacy_inbox.py list            # abiertas (derecho, fechas, comentario)
    .venv/bin/python scripts/privacy_inbox.py who ID          # id de Discord (y correo opcional) de quien la envió
    .venv/bin/python scripts/privacy_inbox.py answer ID --text "..." [--deny]   # guarda la respuesta y cierra
    .venv/bin/python scripts/privacy_inbox.py answer ID --text-file respuesta.txt [--deny]
    .venv/bin/python scripts/privacy_inbox.py check           # código 1 si hay algo vencido o por vencer (erasure o derechos)

`check` está pensado para vigilarlo desde fuera (cron/monitor). Plazos: eliminación 7 días,
otros derechos 30 días corridos, bloqueo temporal 2 días (Ley 21.719 art. 11). La respuesta se guarda en
la solicitud (la persona la ve en el Centro) y se envía al correo que indicó, si lo hizo, o por Discord.
--deny añade el aviso del plazo para reclamar ante la Agencia. Nunca se publica el contenido de la solicitud.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:  # pragma: no cover
    pass

import db  # noqa: E402
import privacy_requests  # noqa: E402
import privacy_rights  # noqa: E402


async def _run(args) -> int:
    await db.init_db()
    try:
        if args.cmd == "list":
            rows = await privacy_rights.open_requests()
            if not rows:
                print("Sin solicitudes de derechos abiertas.")
            for r in rows:
                flag = "VENCIDA" if r["overdue"] else "abierta"
                print(
                    f"#{r['id']} [{flag}] {r['right']} | creada {r['created_at']} | plazo {r['due_at']}"
                )
                if r["note"]:
                    print(f"    comentario: {r['note']}")
            return 0
        if args.cmd == "who":
            who = await privacy_rights.requester_of(args.id)
            if not who:
                print("no existe")
                return 2
            print(f"discord_id={who[0]} correo={who[1] or '-'}")
            return 0
        if args.cmd == "answer":
            text = (
                args.text
                if args.text is not None
                else open(args.text_file, encoding="utf-8").read()
            )
            ok = await privacy_rights.mark_answered(args.id, text, denied=args.deny)
            print("contestada y guardada" if ok else "no existe o ya estaba contestada")
            return 0 if ok else 2
        # check
        soon = datetime.now(timezone.utc) + timedelta(hours=48)
        bad = 0
        for r in await privacy_rights.open_requests():
            if r["overdue"] or r["due_at"] <= soon.strftime(privacy_rights.FMT):
                bad += 1
                print(
                    f"derechos #{r['id']} {'VENCIDA' if r['overdue'] else 'vence en <48 h'} ({r['due_at']})"
                )
        conn = await db.get_db()
        now_s = datetime.now(timezone.utc).strftime(privacy_requests.FMT)
        async with conn.execute(
            "SELECT id, due_at FROM privacy_requests WHERE status IN ('pending','processing','failed') AND due_at < ?",
            (now_s,),
        ) as cur:
            for rid, due in await cur.fetchall():
                bad += 1
                print(f"eliminación #{rid} VENCIDA ({due})")
        print(
            "OK: nada vencido" if not bad else f"{bad} solicitud(es) requieren atención"
        )
        return 1 if bad else 0
    finally:
        await db.close_db()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    p = sub.add_parser("who")
    p.add_argument("id", type=int)
    p = sub.add_parser("answer")
    p.add_argument("id", type=int)
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--text")
    grp.add_argument("--text-file")
    p.add_argument(
        "--deny",
        action="store_true",
        help="la solicitud se deniega (añade el aviso para reclamar ante la Agencia)",
    )
    sys.exit(asyncio.run(_run(ap.parse_args())))


if __name__ == "__main__":
    main()
