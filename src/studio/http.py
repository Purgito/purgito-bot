"""Solo JSON, detrás del gate interno existente y del socket loopback real."""

from datetime import date, datetime
import ipaddress
import json
import uuid

from aiohttp import web

from . import runtime
from .model import parse_time
from .report import commands_report, report


def encode(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(type(value).__name__)


def response(data, status=200):
    return web.Response(
        text=json.dumps(data, default=encode),
        content_type="application/json",
        status=status,
        headers={"Cache-Control": "no-store"},
    )


def register(app, existing_gate):
    def gate(request):
        try:
            local = ipaddress.ip_address(request.remote or "").is_loopback
        except ValueError:
            local = False
        host = request.host.rsplit(":", 1)[0]
        if (
            not local
            or host not in {"127.0.0.1", "localhost", "[::1]"}
            or runtime.get() is None
        ):
            return response({"error": "no encontrado"}, 404)
        return existing_gate(request)

    async def get_report(request):
        if (blocked := gate(request)) is not None:
            return blocked
        collector = runtime.get()
        try:
            result = await report(collector.store, request.query, collector.catalog)
            result["collector"] = collector.health()
            return response(result)
        except ValueError:
            return response({"error": "Solicitud inválida"}, 400)
        except Exception:
            return response(
                {
                    "error": "Analítica temporalmente no disponible. Vuelve a intentarlo."
                },
                503,
            )

    async def get_commands(request):
        if (blocked := gate(request)) is not None:
            return blocked
        try:
            return response(await commands_report(runtime.get().store, request.query))
        except ValueError:
            return response({"error": "Solicitud inválida"}, 400)
        except Exception:
            return response(
                {
                    "error": "Analítica temporalmente no disponible. Vuelve a intentarlo."
                },
                503,
            )

    async def annotate(request):
        if (blocked := gate(request)) is not None:
            return blocked
        if request.content_type != "application/json":
            return response({"error": "Se requiere application/json"}, 415)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) - {
                "at",
                "title",
                "note",
                "version",
                "kind",
            }:
                raise ValueError("Campos de anotación inválidos")
            ident = await runtime.get().store.annotate(
                parse_time(body["at"]),
                body["title"],
                body.get("note", ""),
                body.get("version", ""),
                body.get("kind", "change"),
            )
            return response({"id": ident}, 201)
        except (ValueError, KeyError, TypeError):
            return response(
                {
                    "error": "Anotación inválida: revisa fecha, título y longitud de la nota"
                },
                400,
            )
        except Exception:
            return response({"error": "No se pudo guardar la anotación"}, 503)

    app.router.add_get("/internal/studio/report", get_report)
    app.router.add_get("/internal/studio/commands", get_commands)
    app.router.add_post("/internal/studio/annotations", annotate)
