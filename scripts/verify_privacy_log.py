#!/usr/bin/env python3
"""Verifica el registro encadenado de solicitudes de privacidad contra sus ANCLAS externas.

Cada instantánea del registro de eliminaciones (la que el runner aislado cifra y sube a
gen2/ledger/ de R2 cada hora) lleva un `log_anchor`: el último seq de privacy_request_log y su
hash. Esas instantáneas viven fuera del servidor y se escriben con credenciales que el bot no
tiene, así que quien reescribiera TODA la cadena en la base no podría reescribir también las
anclas ya exportadas. Este script las compara con la base.

Uso (en el equipo del titular o en el servidor, con la clave age para descifrar):
    age -d -i clave.txt privacy-ledger-AAAAMMDDTHHMMSSZ.jsonl.age > ancla1.jsonl
    .venv/bin/python scripts/verify_privacy_log.py --anchor ancla1.jsonl [--anchor ancla2.jsonl ...]

No imprime ids de persona (el registro no los lleva): solo conteos y números de fila.
Código de salida: 0 todo coincide · 1 ALTERADO (cadena rota o ancla que no coincide) ·
2 ancla posterior al final de la base (restauración antigua o cola borrada) · 3 entrada inválida.
Cobertura: una fila posterior al último ancla exportado queda sin cubrir hasta la siguiente
instantánea (como máximo una hora); una ancla solo existe mientras viva su instantánea (15 días).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import pgsync  # noqa: E402
import privacy_ledger  # noqa: E402
import privacy_requests  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", help="default: DATABASE_URL")
    ap.add_argument(
        "--anchor",
        action="append",
        required=True,
        metavar="ARCHIVO",
        help="instantánea del registro ya descifrada (JSONL); se puede repetir",
    )
    args = ap.parse_args(argv)

    anchors: set[tuple[int, str]] = set()
    for path in args.anchor:
        try:
            with open(path, encoding="utf-8") as f:
                snap = privacy_ledger.loads(f.read())
        except (OSError, privacy_ledger.LedgerError) as e:
            print(f"ERROR: {path}: {e}", file=sys.stderr)
            return 3
        anchors |= {(a["seq"], a["hash"]) for a in snap["log_anchors"]}
    if not anchors:
        print("ERROR: ninguna de las instantáneas trae ancla (¿anteriores al registro?)", file=sys.stderr)
        return 3

    conn = pgsync.connect(args.dsn)
    try:
        rows = conn.execute(
            "SELECT seq, request_id, at, event, detail, prev_hash, hash "
            "FROM privacy_request_log ORDER BY seq"
        ).fetchall()
    finally:
        conn.close()

    res = privacy_requests.check_anchors(rows, sorted(anchors))
    print(
        f"filas del registro: {len(rows)} | cadena interna: "
        f"{'coherente' if res['chain_ok'] else 'ROTA en la fila ' + str(res['chain_bad_seq'])}"
    )
    print(
        f"anclas: {res['anchors']} | coinciden: {res['matched']} | "
        f"alteradas: {len(res['altered'])} | posteriores a la base: {len(res['ahead'])}"
    )
    if res["altered"]:
        print(f"ALTERADO: el hash difiere en las filas {res['altered']}", file=sys.stderr)
    if res["ahead"]:
        print(
            f"AVISO: hay anclas más allá de la fila {rows[-1][0] if rows else 0}: "
            "restauración antigua o filas finales borradas",
            file=sys.stderr,
        )
    if not res["ok"]:
        return 1
    return 2 if res["ahead"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
