"""Tests del checkout premium de Polar en el panel."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import db
import webapi


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


class FakeRequest:
    def __init__(self, payload: dict, guild_id: int = 123):
        self._payload = payload
        self.match_info = {"guild_id": str(guild_id)}

    async def json(self):
        return self._payload


class FakePolar:
    def __init__(self):
        self.calls = []
        self.checkouts = SimpleNamespace(create_async=self.create_async)

    async def create_async(self, request):
        self.calls.append(request)
        raise RuntimeError(
            'API error occurred: Status 403. Body: {"error": "insufficient_scope"}'
        )


def _allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": "42"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: object())


def test_premium_checkout_insufficient_scope(monkeypatch):
    _allow_guild_access(monkeypatch)
    fake_polar = FakePolar()
    monkeypatch.setattr(webapi, "_polar", fake_polar)
    monkeypatch.setattr(webapi, "POLAR_SERVER", "production")
    monkeypatch.setattr(webapi, "POLAR_PRODUCT_ID_MONTHLY", "prod-monthly")

    resp = asyncio.run(webapi._api_premium_checkout(FakeRequest({"plan": "monthly"})))

    assert resp.status == 502
    assert json.loads(resp.text) == {
        "error": "Polar rechazó la creación del checkout por permisos insuficientes del token"
    }
    assert len(fake_polar.calls) == 1


def test_premium_checkout_no_escribe_nada_localmente(monkeypatch, temp_db):
    """Crear el checkout (aunque el usuario después abandone la pestaña de
    Polar sin pagar) no debe dejar ningún estado local huérfano -- Purgito
    recién escribe premium_guilds cuando llega el webhook real, nunca al
    crear el checkout."""
    _allow_guild_access(monkeypatch)

    class FakeCheckout:
        url = "https://checkout.polar.sh/abc123"

    async def fake_create_async(request):
        return FakeCheckout()

    fake_polar = SimpleNamespace(
        checkouts=SimpleNamespace(create_async=fake_create_async)
    )
    monkeypatch.setattr(webapi, "_polar", fake_polar)
    monkeypatch.setattr(webapi, "POLAR_PRODUCT_ID_MONTHLY", "prod-monthly")

    async def run():
        resp = await webapi._api_premium_checkout(FakeRequest({"plan": "monthly"}))
        return resp, await db.list_premium_guilds()

    resp, premium_guilds = asyncio.run(run())

    assert resp.status == 200
    assert json.loads(resp.text) == {"checkout_url": "https://checkout.polar.sh/abc123"}
    assert premium_guilds == []
