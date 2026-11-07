#!/usr/bin/env python3
"""Sanea parámetros OAuth/sensibles de logs HISTÓRICOS sin perder el resto de la evidencia.

    sudo scripts/scrub_oauth_logs.py /var/log/nginx/access.log.1 /var/log/nginx/access.log.*.gz
    sudo scripts/scrub_oauth_logs.py --apply --report /root/scrub-report.json ARCHIVO...

Por defecto es un ENSAYO (solo cuenta). Con --apply reescribe cada archivo cambiando únicamente el
VALOR de los parámetros sensibles (`?code=…`, `&state=…`, tokens…) por `[redactado]`: se conservan la
línea, la hora, la ruta, el estado HTTP, el navegador y el NOMBRE del parámetro, que es la evidencia
de seguridad útil (que hubo un callback OAuth, cuándo y con qué resultado).

Garantías y límites:
  - Nunca imprime ni guarda un valor sensible: ni en pantalla, ni en el informe, ni en un `.bak`
    (no hay copia de seguridad del original; si algo falla, el original queda intacto).
  - El temporal se crea 0600 en el mismo directorio y ya contiene el texto saneado.
  - Comprueba antes de reemplazar: mismo número de líneas y ningún valor sensible restante.
  - Conserva dueño, permisos y fecha de modificación (logrotate no se desordena).
  - Se niega a tocar un archivo ACTIVO (nginx y el bot lo tienen abierto: un reemplazo atómico los
    dejaría escribiendo en un archivo borrado). Rota antes (ver docs/DESPLIEGUE_PRIVACIDAD.md).
  - Los bloques liberados del disco pueden conservar el texto original hasta ser reutilizados
    (ext4 con journal): no es un borrado forense. En el volumen cifrado (LUKS2) eso queda cubierto por
    el cifrado; en el disco raíz (nginx) no.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter

SENSITIVE_PARAMS = (
    "code",
    "state",
    "access_token",
    "id_token",
    "refresh_token",
    "token",
    "client_secret",
    "password",
    "session",
    "sessionid",
    "api_key",
    "apikey",
    "key",
    "secret",
)
_PATTERN = re.compile(
    r"([?&;](?:%s)=)([^&\s\"'#]+)" % "|".join(SENSITIVE_PARAMS), re.IGNORECASE
)
REDACTED = "[redactado]"
# Un archivo con una escritura reciente probablemente sigue abierto por quien lo genera.
MIN_AGE_SECONDS = 120


def is_active(path: str) -> bool:
    """`access.log`, `error.log`, `bot.log`…: sin sufijo numérico, de fecha ni .gz."""
    name = os.path.basename(path)
    if name.endswith(".gz"):
        return False
    if re.search(r"\.(\d+|\d{4}-\d{2}-\d{2}_\d{6}(-\d+)?)$", name):
        return False
    return True


def scrub_text(text: str) -> tuple[str, Counter]:
    """(texto saneado, cuántas veces se saneó cada nombre de parámetro)."""
    found: Counter = Counter()

    def _sub(m: re.Match) -> str:
        if m.group(2) == REDACTED:  # ya saneado: idempotente, no se cuenta
            return m.group(0)
        found[m.group(1)[1:-1].lower()] += 1
        return m.group(1) + REDACTED

    return _PATTERN.sub(_sub, text), found


def _read(path: str) -> str:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def _write_atomic(path: str, text: str) -> None:
    st = os.stat(path)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".scrub-", dir=directory)  # 0600
    try:
        with os.fdopen(fd, "wb") as raw:
            if path.endswith(".gz"):
                with gzip.GzipFile(
                    fileobj=raw, mode="wb", mtime=int(st.st_mtime)
                ) as gz:
                    gz.write(text.encode("utf-8", errors="surrogateescape"))
            else:
                raw.write(text.encode("utf-8", errors="surrogateescape"))
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.chmod(tmp, st.st_mode & 0o7777)
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def process(path: str, apply: bool, now: float | None = None) -> dict:
    """Resultado por archivo: {'path', 'status', 'params': {nombre: n}, 'lines': [n, …]}."""
    out = {"path": path, "status": "", "params": {}, "lines": []}
    if not os.path.isfile(path):
        out["status"] = "no existe"
        return out
    if is_active(path):
        out["status"] = "OMITIDO: archivo activo (rótalo antes)"
        return out
    if (now or time.time()) - os.stat(path).st_mtime < MIN_AGE_SECONDS:
        out["status"] = "OMITIDO: modificado hace menos de 2 min"
        return out
    original = _read(path)
    cleaned, found = scrub_text(original)
    out["params"] = dict(found)
    out["lines"] = [
        i + 1 for i, line in enumerate(original.split("\n")) if _PATTERN.search(line)
    ]
    if not found:
        out["status"] = "sin parámetros sensibles"
        return out
    if original.count("\n") != cleaned.count("\n"):
        out["status"] = "ERROR: la verificación de líneas falló (no se tocó)"
        return out
    leftover = [m for m in _PATTERN.finditer(cleaned) if m.group(2) != REDACTED]
    if leftover:
        out["status"] = "ERROR: quedarían valores sensibles (no se tocó)"
        return out
    if not apply:
        out["status"] = f"ensayo: {sum(found.values())} valor(es) a sanear"
        return out
    _write_atomic(path, cleaned)
    out["status"] = f"saneado: {sum(found.values())} valor(es)"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="reescribe los archivos (por defecto, ensayo)",
    )
    ap.add_argument(
        "--report",
        help="JSON 0600 con archivo, líneas y NOMBRES de parámetros (sin valores)",
    )
    args = ap.parse_args(argv)
    results = [process(p, args.apply) for p in args.paths]
    for r in results:
        detail = ", ".join(f"{k}×{v}" for k, v in sorted(r["params"].items()))
        print(f"{r['path']}: {r['status']}" + (f" [{detail}]" if detail else ""))
    if args.report:
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "applied": args.apply,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "files": results,
                },
                f,
                indent=1,
            )
    return 1 if any(r["status"].startswith("ERROR") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
