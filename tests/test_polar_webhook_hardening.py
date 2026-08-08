"""Endurecimiento del webhook de Polar (Sección 2, tercera área de la
auditoría): reintentos fuera de orden y rate limit sobre el endpoint
público. Ver _polar_event_timestamp y _rate_webhook_polar en webapi.py.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import db
import webapi

SECRET = "test-secret"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    # asyncio.Lock se ata al event loop de su primer acquire() CONTENDIDO
    # (asyncio/locks.py: solo pasa por _get_loop() cuando hay que esperar).
    # Los tests de esta ronda son los primeros del repo en generar
    # contención real sobre _db_lock (asyncio.gather de dos escrituras al
    # mismo guild) -- sin resetearlo acá, el lock queda atado para siempre
    # al loop de asyncio.run() de ESTE test, y el próximo test que dispare
    # contención (con su propio asyncio.run(), o sea otro loop) se cuelga o
    # explota con "bound to a different event loop". _db sí se resetea
    # siempre; _db_lock nunca se había necesitado resetear porque hasta
    # ahora ningún test generaba contención real.
    monkeypatch.setattr(db, "_db_lock", asyncio.Lock())
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


class _FakeRequest:
    def __init__(self, body: bytes = b"{}", remote: str = "127.0.0.1"):
        self._body = body
        self.headers: dict = {}
        self.remote = remote

    async def read(self) -> bytes:
        return self._body


def _fake_event(
    event_type, guild_id, timestamp, product_id="prod-monthly", status=None
):
    return SimpleNamespace(
        TYPE=event_type,
        timestamp=timestamp,
        data=SimpleNamespace(
            metadata={"guild_id": str(guild_id)}, product_id=product_id, status=status
        ),
    )


def _run(monkeypatch, event):
    """Corre _webhook_polar de verdad contra la DB real (set_premium/
    unset_premium SIN mockear) -- necesario para probar el chequeo atómico
    de apply_premium_webhook_change, que ahora vive adentro de esas
    funciones, no en _webhook_polar."""
    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(webapi, "validate_event", lambda body, headers, secret: event)
    webapi._rate_webhook_polar.clear()
    return asyncio.run(webapi._webhook_polar(_FakeRequest()))


async def _is_premium(guild_id: int) -> bool:
    rows = await db.list_premium_guilds()
    return any(r["guild_id"] == guild_id for r in rows)


# ── Watermark: descarta eventos que llegan fuera de orden ──────────────────


def test_evento_se_aplica_normalmente(monkeypatch, temp_db):
    event = _fake_event("subscription.active", 123, datetime.now(timezone.utc))
    resp = _run(monkeypatch, event)
    assert resp.status == 200
    assert asyncio.run(_is_premium(123)) is True


def test_evento_viejo_se_descarta_si_llega_despues_de_uno_nuevo(monkeypatch, temp_db):
    """Simula el reintento tardío de un "revoked" viejo llegando DESPUÉS de
    que ya se procesó un "active" más nuevo (resuscripción) -- Polar no
    garantiza orden de entrega, así que esto es real. No debe pisar el
    estado correcto que ya se aplicó."""
    now = datetime.now(timezone.utc)

    nuevo = _fake_event("subscription.active", 123, now)
    resp1 = _run(monkeypatch, nuevo)
    assert resp1.status == 200
    assert asyncio.run(_is_premium(123)) is True

    viejo = _fake_event("subscription.revoked", 123, now - timedelta(minutes=10))
    resp2 = _run(monkeypatch, viejo)
    assert resp2.status == 200
    assert asyncio.run(_is_premium(123)) is True  # se ignoró: sigue premium


def test_evento_mas_nuevo_se_sigue_aplicando_tras_uno_previo(monkeypatch, temp_db):
    """El watermark no bloquea eventos legítimos posteriores -- solo los que
    llegan fuera de orden respecto al último ya aplicado."""
    now = datetime.now(timezone.utc)

    primero = _fake_event("subscription.active", 123, now)
    _run(monkeypatch, primero)

    segundo = _fake_event("subscription.revoked", 123, now + timedelta(minutes=5))
    resp = _run(monkeypatch, segundo)
    assert resp.status == 200
    assert asyncio.run(_is_premium(123)) is False


def test_sin_timestamp_no_bloquea_nada(monkeypatch, temp_db):
    """Un evento sin `timestamp` parseable (falta el atributo, o polar-sdk
    cambia el shape) debe seguir aplicándose -- mejor no bloquear que
    descartar un evento legítimo por un dato faltante."""
    event = SimpleNamespace(
        TYPE="subscription.active",
        data=SimpleNamespace(
            metadata={"guild_id": "123"}, product_id="prod-monthly", status=None
        ),
    )  # sin .timestamp
    resp = _run(monkeypatch, event)
    assert resp.status == 200
    assert asyncio.run(_is_premium(123)) is True


# ── Watermark: la lectura + el cambio + la escritura son atómicos ─────────


def test_dos_webhooks_concurrentes_no_pueden_leer_el_mismo_watermark_viejo(
    monkeypatch, temp_db
):
    """El caso que motiva esta ronda: si el chequeo de watermark y el cambio
    de estado no fueran una sola sección crítica bajo _db_lock, dos
    corrutinas concurrentes para el MISMO guild podrían leer el watermark
    viejo cada una por su lado (ninguna ve todavía el resultado de la otra)
    y las dos pasarían el chequeo de "no está obsoleto" -- sin importar cuál
    evento era realmente el más nuevo. Se simula lanzando ambas como tareas
    de asyncio sin esperar a que la primera termine antes de arrancar la
    segunda (asyncio.gather), exactamente la condición de carrera real."""
    now = datetime.now(timezone.utc)
    viejo = _fake_event("subscription.active", 123, now)
    nuevo = _fake_event("subscription.revoked", 123, now + timedelta(minutes=5))

    async def run():
        monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", SECRET)
        webapi._rate_webhook_polar.clear()

        # Cada _webhook_polar necesita su propio validate_event devolviendo
        # el evento que le toca -- se alternan según el orden de llamada.
        events = iter([viejo, nuevo])
        monkeypatch.setattr(
            webapi, "validate_event", lambda body, headers, secret: next(events)
        )

        await asyncio.gather(
            webapi._webhook_polar(_FakeRequest()),
            webapi._webhook_polar(_FakeRequest()),
        )
        return await _is_premium(123)

    # El resultado final tiene que corresponder a UN evento real aplicado
    # limpiamente -- no a los dos aplicados en cualquier orden. Como el más
    # nuevo (revoked) tiene que ganar pase lo que pase, el guild termina
    # SIN premium.
    assert asyncio.run(run()) is False


def test_apply_premium_webhook_change_concurrente_termina_consistente(temp_db):
    """Mismo escenario que el test de arriba pero un nivel más abajo, contra
    db.apply_premium_webhook_change directo (sin pasar por el handler HTTP
    ni por validate_event) -- fija el contrato exacto de la función que
    hace la sección crítica atómica: no importa en qué orden el scheduler
    de asyncio corra las dos corrutinas, el ganador final tiene que ser
    siempre el evento con el timestamp más nuevo, y el watermark que queda
    grabado tiene que ser el de ESE evento, no el del otro."""
    t_viejo = "2026-01-01T00:00:00+00:00"
    t_nuevo = "2026-01-01T00:05:00+00:00"

    async def run():
        await asyncio.gather(
            db.apply_premium_webhook_change(
                123, activate=True, note="x", event_at=t_viejo
            ),
            db.apply_premium_webhook_change(
                123, activate=False, note=None, event_at=t_nuevo
            ),
        )
        premium = await _is_premium(123)
        watermark = await db.get_premium_event_watermark(123)
        return premium, watermark

    premium, watermark = asyncio.run(run())
    assert premium is False  # el evento más nuevo (desactivar) tiene que ganar
    assert watermark == t_nuevo  # y el watermark tiene que reflejar ESE evento


# ── Watermark: capa DB ──────────────────────────────────────────────────────


def test_watermark_round_trip(temp_db):
    async def run():
        assert await db.get_premium_event_watermark(1) is None
        await db.set_premium_event_watermark(1, "2026-01-01T00:00:00+00:00")
        return await db.get_premium_event_watermark(1)

    assert asyncio.run(run()) == "2026-01-01T00:00:00+00:00"


# ── Rate limit sobre el endpoint público ────────────────────────────────────


def test_webhook_polar_bloquea_tras_superar_el_limite_por_ip(monkeypatch, temp_db):
    """Sin este límite, cualquiera podía golpear /webhooks/polar en loop --
    corre en el mismo proceso que el dashboard. El límite es generoso a
    propósito (60/min): no debe interferir con reintentos legítimos de
    Polar, así que primero confirma que los intentos normales (rechazados
    por firma inválida) siguen pasando, y solo el que excede el límite
    se corta distinto (429, no 403)."""
    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", SECRET)

    def fake_validate(body, headers, secret):
        raise webapi.WebhookVerificationError("nop")

    monkeypatch.setattr(webapi, "validate_event", fake_validate)
    webapi._rate_webhook_polar.clear()

    async def run():
        statuses = []
        for _ in range(61):
            resp = await webapi._webhook_polar(_FakeRequest(remote="203.0.113.9"))
            statuses.append(resp.status)
        return statuses

    statuses = asyncio.run(run())
    assert statuses[:60] == [403] * 60
    assert statuses[60] == 429


def test_webhook_polar_no_comparte_limite_entre_ips(monkeypatch, temp_db):
    monkeypatch.setattr(webapi, "POLAR_WEBHOOK_SECRET", SECRET)

    def fake_validate(body, headers, secret):
        raise webapi.WebhookVerificationError("nop")

    monkeypatch.setattr(webapi, "validate_event", fake_validate)
    webapi._rate_webhook_polar.clear()

    async def run():
        for _ in range(60):
            await webapi._webhook_polar(_FakeRequest(remote="203.0.113.9"))
        # IP A ya agotó su límite; IP B no debería verse afectada.
        return await webapi._webhook_polar(_FakeRequest(remote="198.51.100.1"))

    resp = asyncio.run(run())
    assert (
        resp.status == 403
    )  # llegó a validar firma, no lo frenó el límite de la otra IP


# ── Tamaño del body ──────────────────────────────────────────────────────
#
# La app no fija client_max_size -- corre con el default de aiohttp
# (1 MiB), que además se aplica de forma incremental (chunk a chunk, no
# recién al final) según aiohttp/web_request.py:Request.read(). Este test
# no re-verifica ese comportamiento de la librería (no es código nuestro):
# solo confirma que nadie agregó un client_max_size más laxo (o lo sacó del
# todo) sin darse cuenta al tocar start_web_server.


class _FakeBot:
    guilds: list = []

    def get_guild(self, guild_id):
        return None


def test_no_se_configuro_un_client_max_size_mas_laxo_que_el_default():
    original_enabled = webapi.DASHBOARD_ENABLED
    original_runner = webapi._runner
    webapi.DASHBOARD_ENABLED = True
    webapi._runner = None

    async def run():
        await webapi.start_web_server(_FakeBot())
        try:
            return webapi._runner.app._client_max_size
        finally:
            await webapi.stop_web_server()

    try:
        max_size = asyncio.run(run())
    finally:
        webapi.DASHBOARD_ENABLED = original_enabled
        webapi._runner = original_runner

    assert max_size == 1024**2  # default de aiohttp -- no lo sobreescribimos
