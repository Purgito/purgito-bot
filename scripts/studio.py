#!/usr/bin/env python3
"""Ejecutar solo en el host privado: python scripts/studio.py (sin abrir puertos públicos)."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aiohttp import web  # noqa: E402
import config  # noqa: E402
from studio.local_server import application  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--backend-port", type=int, default=config.WEB_PORT)
    args = parser.parse_args()
    web.run_app(
        application(
            config.OBSERVABILITY_TOKEN, backend_port=args.backend_port, port=args.port
        ),
        host="127.0.0.1",
        port=args.port,
        access_log=None,
    )


if __name__ == "__main__":
    main()
