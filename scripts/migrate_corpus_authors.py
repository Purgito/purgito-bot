"""Migración controlada de corpus_messages: atribuye cada mensaje heredado a su autor y elimina los que
no se pueden atribuir de forma verificable.

    .venv/bin/python scripts/migrate_corpus_authors.py            # dry-run: solo cuenta
    .venv/bin/python scripts/migrate_corpus_authors.py --apply    # atribuye y elimina

Regla única: un mensaje sin author_id se atribuye SOLO si existe una fila de user_corpus con el MISMO
(guild_id, message_id). Nunca por contenido ni por heurística. Lo que no tenga ese vínculo no se puede
borrar a petición de su autor, así que se elimina (decisión del titular). Haz antes un respaldo
(`systemctl start purgito-backup`): es la vía de recuperación durante 14 días. Reinicia el bot
después para que las cachés de Markov se reconstruyan.
"""

import argparse
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:  # pragma: no cover
    pass

import db  # noqa: E402


async def main_async(apply: bool) -> int:
    await db.init_db()  # añade la columna author_id si falta
    try:
        res = await db.reconcile_corpus_authors(apply=apply)
    finally:
        await db.close_db()
    verbo = "APLICADO" if apply else "DRY-RUN (no se modificó nada)"
    print(f"== {verbo}")
    for k, v in res.items():
        print(f"  {k}: {v}")
    if apply and res.get("sin_autor_despues", 1) != 0:
        print("ERROR: quedaron mensajes sin autor")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    sys.exit(asyncio.run(main_async(ap.parse_args().apply)))
