"""Auditoría sección 9, ronda 2, punto 2: forma del payload del webhook de Polar.

La firma ya se auditó en la sección 2. Lo de acá es lo que pasa DESPUÉS de que
la firma valida: el handler tiene dos ramas de extracción, una tipada por el
SDK y otra que parsea el JSON crudo cuando polar-sdk no modela el tipo de
evento. La segunda vivía dentro de un bloque `except`, y una excepción
levantada ahí no la atrapa el `except Exception` que viene después -- salía del
handler como 500, que es justo lo que ese catch-all existe para evitar (un 500
hace que Polar reintente contra algo que nunca se va a resolver solo).

No se testea con firmas reales: se parchea validate_event para forzar cada
rama, que es lo que se quiere ejercitar.
"""

import asyncio
import json

import pytest

import webapi


class FakeRequest:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {}
        self.remote = "1.2.3.4"

    async def read(self):
        return self._body


@pytest.fixture(autouse=True)
def webhook_configurado(monkeypatch):
    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", "un-secreto")
    monkeypatch.setattr(webapi, "_rate_webhook_polar", webapi.LRUDict(64))


@pytest.fixture
def tipo_no_modelado(monkeypatch):
    """Fuerza la rama de JSON crudo (la que dispara WebhookUnknownTypeError)."""

    def _boom(body, headers, secret):
        raise webapi.WebhookUnknownTypeError("tipo no modelado por el SDK")

    monkeypatch.setattr(webapi, "validate_event", _boom)


def _run(body: bytes):
    return asyncio.run(webapi._webhook_polar(FakeRequest(body)))


@pytest.mark.parametrize(
    "body",
    [
        b"[1, 2, 3]",  # JSON válido pero no es un objeto
        b'"soy un string"',
        b"42",
        b"null",
        b"no soy json",
        b"",
    ],
)
def test_payload_no_parseable_da_400_y_no_500(tipo_no_modelado, body):
    """Un 500 hace que Polar reintente para siempre contra algo que no se va a
    resolver solo; un 400 le dice que ese evento es basura y deje de insistir.

    Antes del fix, cada uno de estos casos salía del handler como excepción
    sin capturar: el parseo del JSON crudo vivía dentro de un bloque `except`,
    y el `except Exception` de más abajo no cubre eso.
    """
    resp = _run(body)
    assert resp.status == 400
    assert json.loads(resp.body)["error"] == "payload inválido"


@pytest.mark.parametrize(
    "body",
    [
        b'{"type": "subscription.paused", "data": "no soy un dict"}',
        b'{"type": "subscription.paused", "data": [1, 2]}',
        b'{"type": "subscription.paused"}',
        b"{}",
    ],
)
def test_payload_con_data_inutil_se_ignora_sin_romper(tipo_no_modelado, body):
    """Sobre destruido pero legible: no hay nada que aplicar (sin guild_id),
    así que se acusa recibo con 200 en vez de hacer reintentar a Polar. Lo que
    importa es que no reviente."""
    resp = _run(body)
    assert resp.status == 200
    assert json.loads(resp.body) == {"ok": True}


def test_payload_bien_formado_de_tipo_no_modelado_sigue_funcionando(
    tipo_no_modelado, monkeypatch
):
    """El fix no puede romper el caso real que la rama existe para cubrir:
    subscription.paused con su metadata."""
    llamadas = []

    async def _fake_unset(guild_id, event_at_iso=None):
        llamadas.append(guild_id)
        return True

    monkeypatch.setattr(webapi, "unset_premium", _fake_unset)

    body = json.dumps(
        {
            "type": "subscription.paused",
            "timestamp": "2026-08-10T12:00:00Z",
            "data": {"metadata": {"guild_id": "777"}, "status": "paused"},
        }
    ).encode()
    resp = _run(body)

    assert resp.status == 200
    assert llamadas == [777]


def test_metadata_deforme_no_rompe(tipo_no_modelado):
    """metadata que no es un dict: el handler ya tenía el isinstance, esto lo
    fija para que no se caiga en un refactor."""
    body = json.dumps(
        {"type": "subscription.paused", "data": {"metadata": "no soy un dict"}}
    ).encode()
    resp = _run(body)
    assert resp.status == 200
    assert json.loads(resp.body) == {"ok": True}


@pytest.mark.parametrize(
    "guild_id",
    ["no-es-un-numero", None, {"a": 1}, [1], "9" * 5000],
)
def test_guild_id_invalido_se_ignora_sin_romper(tipo_no_modelado, guild_id):
    body = json.dumps(
        {"type": "subscription.paused", "data": {"metadata": {"guild_id": guild_id}}}
    ).encode()
    resp = _run(body)
    assert resp.status == 200
    assert json.loads(resp.body) == {"ok": True}


def test_sin_secret_configurado_no_procesa_nada(monkeypatch):
    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", "")
    resp = _run(b'{"type": "subscription.active"}')
    assert resp.status == 503
