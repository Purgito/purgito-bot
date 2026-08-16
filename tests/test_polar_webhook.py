"""Tests del webhook de Polar (/webhooks/polar) sin red ni credenciales reales.

Los casos con tipos que polar-sdk modela (active/revoked) parchean validate_event
con un evento fabricado; el caso paused firma el payload de verdad con
standardwebhooks (misma lib que usa el SDK) para ejercitar la verificación real
y el fallback de JSON crudo para tipos que el SDK no conoce.
"""

import asyncio
import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from standardwebhooks.webhooks import Webhook

import webapi
from polar_sdk.webhooks import WebhookVerificationError

SECRET = "test-secret"
MONTHLY = "prod-monthly"
ANNUAL = "prod-annual"


class FakeRequest:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}
        self.remote = "127.0.0.1"

    async def read(self) -> bytes:
        return self._body


def _signed_headers(body: str) -> dict:
    ts = datetime.now(timezone.utc)
    signer = Webhook(base64.b64encode(SECRET.encode()).decode())
    return {
        "webhook-id": "msg_test",
        "webhook-timestamp": str(int(ts.timestamp())),
        "webhook-signature": signer.sign("msg_test", ts, body),
    }


def _fake_event(
    event_type: str,
    metadata,
    product_id: str = MONTHLY,
    status=None,
    revoke_benefits=None,
):
    return SimpleNamespace(
        TYPE=event_type,
        data=SimpleNamespace(
            metadata=metadata,
            product_id=product_id,
            status=status,
            revoke_benefits=revoke_benefits,
        ),
    )


def _run(
    monkeypatch,
    request: FakeRequest,
    fake_event=None,
    raise_verification=False,
    set_returns=True,
):
    """Ejecuta el handler con set/unset espiados; retorna (response, calls).

    set_returns controla lo que devuelve set_premium (True = alta nueva, False =
    ya era premium), para ejercitar la rama idempotente del handler."""
    calls = {"set": [], "unset": []}

    async def fake_set(guild_id, note=None, event_at=None):
        calls["set"].append((guild_id, note))
        return set_returns

    async def fake_unset(guild_id, event_at=None):
        calls["unset"].append(guild_id)
        return True

    async def fake_upsert_subscription(guild_id, **fields):
        calls.setdefault("upsert_subscription", []).append(guild_id)

    monkeypatch.setattr(webapi, "set_premium", fake_set)
    monkeypatch.setattr(webapi, "unset_premium", fake_unset)
    monkeypatch.setattr(webapi, "upsert_premium_subscription", fake_upsert_subscription)
    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(webapi, "POLAR_PRODUCT_ID_MONTHLY", MONTHLY)
    monkeypatch.setattr(webapi, "POLAR_PRODUCT_ID_ANNUAL", ANNUAL)
    webapi._rate_webhook_polar.clear()
    if raise_verification:

        def fake_validate(body, headers, secret):
            raise WebhookVerificationError("no matching signature")

        monkeypatch.setattr(webapi, "validate_event", fake_validate)
    elif fake_event is not None:
        monkeypatch.setattr(
            webapi, "validate_event", lambda body, headers, secret: fake_event
        )
    resp = asyncio.run(webapi._webhook_polar(request))
    return resp, calls


def test_active_sets_premium(monkeypatch):
    event = _fake_event("subscription.active", {"guild_id": "123"}, MONTHLY)
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["set"] == [(123, "Polar — mensual")]
    assert calls["unset"] == []


def test_active_annual_note(monkeypatch):
    event = _fake_event("subscription.active", {"guild_id": "123"}, ANNUAL)
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert calls["set"] == [(123, "Polar — anual")]


# ── premium_subscriptions: metadatos de facturación, independientes del
# acceso -- ver upsert_premium_subscription en db.py y su llamada en
# _webhook_polar. subscription.updated/canceled en particular NO están en
# _POLAR_ACTIVATE ni _POLAR_DEACTIVATE (nunca deben tocar premium_guilds),
# pero antes de este cambio el filtro de "ignorado" los descartaba del todo.


def test_active_tambien_guarda_metadata_de_suscripcion(monkeypatch):
    event = _fake_event("subscription.active", {"guild_id": "123"}, MONTHLY)
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert calls["upsert_subscription"] == [123]


def test_subscription_updated_captura_metadata_sin_tocar_acceso(monkeypatch):
    """El caso central del cambio: subscription.updated no otorga ni quita
    premium (no está en _POLAR_ACTIVATE ni _POLAR_DEACTIVATE), pero sí debe
    guardar cancel_at_period_end/período -- antes se descartaba entero."""
    event = _fake_event("subscription.updated", {"guild_id": "123"}, MONTHLY)
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["upsert_subscription"] == [123]
    assert calls["set"] == [] and calls["unset"] == []


def test_subscription_canceled_captura_metadata_sin_tocar_acceso(monkeypatch):
    event = _fake_event("subscription.canceled", {"guild_id": "123"}, MONTHLY)
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["upsert_subscription"] == [123]
    assert calls["set"] == [] and calls["unset"] == []


def test_subscription_updated_sin_guild_id_no_llama_upsert(monkeypatch):
    event = _fake_event("subscription.updated", {}, MONTHLY)
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls.get("upsert_subscription", []) == []


def test_refund_no_llama_upsert_de_suscripcion(monkeypatch):
    """refund.* no es un evento de suscripción -- no debe tocar
    premium_subscriptions, solo premium_guilds vía unset_premium."""
    event = _fake_event(
        "refund.created", {"guild_id": "123"}, status="succeeded", revoke_benefits=True
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert calls.get("upsert_subscription", []) == []
    assert calls["unset"] == [123]


def test_created_trialing_sets_premium(monkeypatch):
    # El caso que motivó este cambio: con free trial configurado en Polar,
    # subscription.active recién llega al terminar el trial — subscription.created
    # con status "trialing" es lo único que avisa que el trial arrancó.
    event = _fake_event(
        "subscription.created", {"guild_id": "123"}, MONTHLY, status="trialing"
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["set"] == [(123, "Polar — mensual")]
    assert calls["unset"] == []


def test_created_incomplete_is_ignored(monkeypatch):
    # subscription.created también dispara con status "incomplete" mientras se
    # procesa el primer pago (sin trial): no debe activar premium todavía.
    event = _fake_event(
        "subscription.created", {"guild_id": "123"}, MONTHLY, status="incomplete"
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["set"] == [] and calls["unset"] == []


def test_created_already_active_status_is_ignored(monkeypatch):
    # Si subscription.created llegara con status "active" (pago inmediato sin
    # trial), no la tratamos como alta acá: subscription.active se encarga.
    event = _fake_event(
        "subscription.created", {"guild_id": "123"}, MONTHLY, status="active"
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["set"] == [] and calls["unset"] == []


def test_active_after_trial_is_idempotent(monkeypatch, caplog):
    # Fin del trial: subscription.active llega para una suscripción que
    # subscription.created ya había activado. set_premium (INSERT OR IGNORE)
    # devuelve False; el handler debe seguir llamándola (sin romper nada) pero
    # loguear como "sin cambios", no como una activación nueva.
    event = _fake_event("subscription.active", {"guild_id": "123"}, MONTHLY)
    with caplog.at_level("DEBUG", logger="webapi"):
        resp, calls = _run(
            monkeypatch, FakeRequest(b"{}"), fake_event=event, set_returns=False
        )
    assert resp.status == 200
    assert calls["set"] == [(123, "Polar — mensual")]
    assert not [r for r in caplog.records if "activado" in r.getMessage().lower()]
    assert any("sin cambios" in r.getMessage() for r in caplog.records)


def test_revoked_unsets_premium(monkeypatch):
    event = _fake_event("subscription.revoked", {"guild_id": "456"})
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["unset"] == [456]
    assert calls["set"] == []


def test_invalid_signature_403(monkeypatch):
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), raise_verification=True)
    assert resp.status == 403
    assert calls["set"] == [] and calls["unset"] == []


def test_missing_guild_id_responds_200(monkeypatch):
    event = _fake_event("subscription.active", {})
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["set"] == [] and calls["unset"] == []


def test_paused_real_signature_unknown_type_fallback(monkeypatch):
    # subscription.paused no existe en polar-sdk 0.31.7: firma real, el handler
    # debe caer al fallback de JSON crudo y desactivar premium igual.
    body = json.dumps(
        {
            "type": "subscription.paused",
            "data": {"metadata": {"guild_id": "789"}, "product_id": MONTHLY},
        }
    )
    req = FakeRequest(body.encode(), _signed_headers(body))
    resp, calls = _run(monkeypatch, req)
    assert resp.status == 200
    assert calls["unset"] == [789]


def test_bad_signature_real_path_403(monkeypatch):
    body = json.dumps({"type": "subscription.active", "data": {}})
    headers = _signed_headers(body)
    headers["webhook-signature"] = "v1,QUFBQQ=="
    resp, calls = _run(monkeypatch, FakeRequest(body.encode(), headers))
    assert resp.status == 403
    assert calls["set"] == [] and calls["unset"] == []


# ── Reembolsos: revoke_benefits es la señal real, no "hubo un refund" ──────
#
# Confirmado contra el modelo Refund del SDK (polar_sdk/models/refund.py):
# el reembolso trae su propio campo `revoke_benefits`, independiente de que
# el reembolso haya ocurrido -- Polar no revoca la suscripción automática-
# mente al reembolsar. refund.created dispara "regardless of status"
# (incluye pending/failed), así que además hace falta status="succeeded".


def test_refund_succeeded_con_revoke_benefits_desactiva_premium(monkeypatch):
    event = _fake_event(
        "refund.created",
        {"guild_id": "123"},
        status="succeeded",
        revoke_benefits=True,
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["unset"] == [123]
    assert calls["set"] == []


def test_refund_parcial_sin_revoke_benefits_no_toca_premium(monkeypatch):
    # Reembolso parcial: Polar no lo marca para revocar beneficios.
    event = _fake_event(
        "refund.created",
        {"guild_id": "123"},
        status="succeeded",
        revoke_benefits=False,
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["unset"] == [] and calls["set"] == []


def test_refund_pending_con_revoke_benefits_no_desactiva_todavia(monkeypatch):
    # revoke_benefits=True pero el reembolso todavía no se concretó -- no hay
    # que cortar el acceso antes de que Polar confirme el reembolso en sí.
    event = _fake_event(
        "refund.created",
        {"guild_id": "123"},
        status="pending",
        revoke_benefits=True,
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["unset"] == [] and calls["set"] == []


def test_refund_updated_succeeded_revoke_benefits_desactiva_premium(monkeypatch):
    # El reembolso puede empezar pending y confirmarse después vía
    # refund.updated -- misma lógica que refund.created.
    event = _fake_event(
        "refund.updated",
        {"guild_id": "456"},
        status="succeeded",
        revoke_benefits=True,
    )
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["unset"] == [456]


def test_refund_sin_guild_id_responde_200_sin_tocar_nada(monkeypatch):
    event = _fake_event("refund.created", {}, status="succeeded", revoke_benefits=True)
    resp, calls = _run(monkeypatch, FakeRequest(b"{}"), fake_event=event)
    assert resp.status == 200
    assert calls["unset"] == [] and calls["set"] == []


# ── Payloads malformados: 4xx sin excepción sin manejar ────────────────────
#
# Ambos casos exigen una firma VÁLIDA (con SECRET real) -- son body real +
# _signed_headers, no mocks, para probar el comportamiento real de
# standardwebhooks/pydantic, no una suposición sobre qué excepción tiran.
# Sin el secreto real, ninguno de los dos es alcanzable por un atacante
# (cae en firma inválida -> 403 antes de llegar acá).


def test_body_no_json_con_firma_valida_responde_400_no_500(monkeypatch):
    body = "esto no es json"
    req = FakeRequest(body.encode(), _signed_headers(body))
    resp, calls = _run(monkeypatch, req)
    assert resp.status == 400
    assert calls["set"] == [] and calls["unset"] == []


def test_json_valido_sin_los_campos_esperados_responde_400_no_500(monkeypatch):
    # type conocido (pasa el chequeo de _KNOWN_EVENT_TYPES) pero "data" no
    # tiene ninguno de los campos que pide el schema de Subscription --
    # pydantic tira ValidationError al armar el modelo tipado.
    body = json.dumps(
        {"type": "subscription.active", "data": {"esto": "no es una Subscription"}}
    )
    req = FakeRequest(body.encode(), _signed_headers(body))
    resp, calls = _run(monkeypatch, req)
    assert resp.status == 400
    assert calls["set"] == [] and calls["unset"] == []
