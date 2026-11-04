#!/usr/bin/env python3
"""Interfaz privada de Purgito Studio (solo loopback). Ver docs/STUDIO.md y docs/STUDIO_ACCESS.md.

Local, sin más:        python scripts/studio.py
Como servicio (systemd) lee solo STUDIO_*/OBSERVABILITY_TOKEN del entorno (EnvironmentFile): no
necesita el .env completo del bot. Si OBSERVABILITY_TOKEN no está en el entorno, se carga la
configuración del bot (modo administración local).
"""

import argparse
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aiohttp import web  # noqa: E402
from studio.access import AccessSettings  # noqa: E402
from studio.local_server import application  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument(
        "--backend-port",
        type=int,
        default=None,
        help="Puerto del backend del bot (por defecto WEB_PORT o 8080)",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    token = os.environ.get("OBSERVABILITY_TOKEN", "")
    backend_port = args.backend_port or int(os.environ.get("WEB_PORT") or 0) or None
    if not token or backend_port is None:
        import config  # carga el .env del bot: solo en el modo de administración local

        token = token or config.OBSERVABILITY_TOKEN
        backend_port = backend_port or config.WEB_PORT
    try:
        access = AccessSettings.from_env(os.environ)
    except ValueError as exc:
        sys.exit(f"Configuración de acceso remoto inválida: {exc}")

    log = logging.getLogger("studio")
    log.info(
        "Acceso local en http://127.0.0.1:%s (admin + OBSERVABILITY_TOKEN)", args.port
    )
    if access:
        log.info(
            "Acceso remoto activo para %s (%d correos autorizados, equipo %s)",
            access.host,
            len(access.emails),
            access.team,
        )
    else:
        log.info("Acceso remoto desactivado (STUDIO_ACCESS_* sin definir)")
    web.run_app(
        application(token, backend_port=backend_port, port=args.port, access=access),
        host="127.0.0.1",
        port=args.port,
        access_log=None,
        print=None,
    )


if __name__ == "__main__":
    main()
