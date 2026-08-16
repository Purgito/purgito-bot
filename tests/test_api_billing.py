"""Tests de la separación /api/me/guilds (estado del servidor) vs.
/api/me/billing (facturación privada del usuario autenticado) -- ver
auditoría de Premium+Polar. El caso central: tener MANAGE_GUILD no es ser
dueño de la suscripción, así que un admin B no debe poder ver la facturación
de un admin A del mismo guild.
"""

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


def _upsert(guild_id, **overrides):
    fields = dict(
        subscription_id="sub_1",
        customer_id="cus_1",
        purchaser_user_id="42",
        product_id="prod-monthly",
        status="active",
        current_period_start="2026-08-01T00:00:00+00:00",
        current_period_end="2026-09-01T00:00:00+00:00",
        trial_start=None,
        trial_end=None,
        cancel_at_period_end=False,
        canceled_at=None,
        event_at="2026-08-01T00:00:00+00:00",
    )
    fields.update(overrides)
    asyncio.run(db.upsert_premium_subscription(guild_id, **fields))


class _FakeGuild:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class _FakeBot:
    def __init__(self, guilds=()):
        self.guilds = list(guilds)
        self._by_id = {g.id: g for g in guilds}

    def get_guild(self, gid):
        return self._by_id.get(gid)


class _FakeRequest:
    def __init__(self, bot=None, body=None):
        self.app = {"bot": bot or _FakeBot()}
        self._body = body or {}
        self.headers = {}
        self.remote = "1.2.3.4"
        self.query = {}

    async def json(self):
        return self._body


def _session_as(monkeypatch, user_id):
    async def fake_get_session(request):
        return {"user_id": user_id}

    monkeypatch.setattr(webapi, "get_session", fake_get_session)


def _logged_out(monkeypatch):
    async def fake_get_session(request):
        return {}

    monkeypatch.setattr(webapi, "get_session", fake_get_session)


# ── /api/me/billing filtra por purchaser, no por MANAGE_GUILD ──────────────


def test_billing_solo_devuelve_las_suscripciones_del_usuario(temp_db, monkeypatch):
    _upsert(111, purchaser_user_id="user-a", product_id="prod-monthly")
    _upsert(222, purchaser_user_id="user-b", product_id="prod-annual")
    bot = _FakeBot([_FakeGuild(111, "Servidor de A"), _FakeGuild(222, "Servidor de B")])

    _session_as(monkeypatch, "user-a")
    resp = asyncio.run(webapi._api_me_billing(_FakeRequest(bot=bot)))
    data = json.loads(resp.body)

    assert [s["guild_id"] for s in data["subscriptions"]] == ["111"]
    assert data["subscriptions"][0]["guild_name"] == "Servidor de A"
    assert resp.headers["Cache-Control"] == "no-store"


def test_admin_b_no_ve_la_suscripcion_de_admin_a_en_el_mismo_guild(
    temp_db, monkeypatch
):
    """El escenario exacto de la auditoría: A compra Premium para el guild X,
    B también administra X (MANAGE_GUILD) pero no compró nada -- B no debe
    ver ningún dato de facturación de ese guild."""
    _upsert(999, purchaser_user_id="user-a")

    _session_as(monkeypatch, "user-b")
    resp = asyncio.run(webapi._api_me_billing(_FakeRequest()))
    data = json.loads(resp.body)

    assert data["subscriptions"] == []


def test_billing_no_expone_subscription_id_ni_customer_id(temp_db, monkeypatch):
    _upsert(111, purchaser_user_id="user-a")
    _session_as(monkeypatch, "user-a")
    resp = asyncio.run(webapi._api_me_billing(_FakeRequest()))
    data = json.loads(resp.body)
    sub = data["subscriptions"][0]
    assert "subscription_id" not in sub
    assert "customer_id" not in sub
    assert "purchaser_user_id" not in sub


def test_billing_sin_sesion_da_401(monkeypatch):
    _logged_out(monkeypatch)
    resp = asyncio.run(webapi._api_me_billing(_FakeRequest()))
    assert resp.status == 401


def test_billing_marca_trial_y_cancelacion_programada(temp_db, monkeypatch):
    _upsert(
        111,
        purchaser_user_id="user-a",
        status="trialing",
        trial_end="2026-08-20T00:00:00+00:00",
    )
    _upsert(
        222,
        purchaser_user_id="user-a",
        status="active",
        cancel_at_period_end=True,
    )
    _session_as(monkeypatch, "user-a")
    resp = asyncio.run(webapi._api_me_billing(_FakeRequest()))
    subs = {s["guild_id"]: s for s in json.loads(resp.body)["subscriptions"]}

    assert subs["111"]["is_trialing"] is True
    assert subs["111"]["trial_end"] == "2026-08-20T00:00:00+00:00"
    assert subs["222"]["cancel_at_period_end"] is True


# ── /api/me/billing/portal: link server-side atado al customer_id real ─────


class _FakeCustomerSessions:
    def __init__(self, portal_url="https://polar.sh/portal/abc"):
        self.calls = []
        self._portal_url = portal_url

    async def create_async(self, request):
        self.calls.append(request)
        return SimpleNamespace(customer_portal_url=self._portal_url)


def test_billing_portal_genera_link_con_el_customer_id_guardado(temp_db, monkeypatch):
    _upsert(111, purchaser_user_id="user-a", customer_id="cus_real_de_polar")
    fake_sessions = _FakeCustomerSessions()
    monkeypatch.setattr(
        webapi, "_polar", SimpleNamespace(customer_sessions=fake_sessions)
    )
    _session_as(monkeypatch, "user-a")

    resp = asyncio.run(
        webapi._api_me_billing_portal(_FakeRequest(body={"guild_id": 111}))
    )
    data = json.loads(resp.body)

    assert data["portal_url"] == "https://polar.sh/portal/abc"
    assert fake_sessions.calls == [{"customer_id": "cus_real_de_polar"}]
    assert resp.headers["Cache-Control"] == "no-store"


def test_billing_portal_no_deja_que_b_genere_el_link_de_a(temp_db, monkeypatch):
    _upsert(111, purchaser_user_id="user-a", customer_id="cus_real_de_polar")
    monkeypatch.setattr(
        webapi, "_polar", SimpleNamespace(customer_sessions=_FakeCustomerSessions())
    )
    _session_as(monkeypatch, "user-b")

    resp = asyncio.run(
        webapi._api_me_billing_portal(_FakeRequest(body={"guild_id": 111}))
    )
    assert resp.status == 404


def test_billing_portal_sin_polar_configurado_da_502(monkeypatch):
    monkeypatch.setattr(webapi, "_polar", None)
    _session_as(monkeypatch, "user-a")
    resp = asyncio.run(
        webapi._api_me_billing_portal(_FakeRequest(body={"guild_id": 111}))
    )
    assert resp.status == 502


def test_billing_portal_guild_id_invalido_da_400(monkeypatch):
    monkeypatch.setattr(
        webapi, "_polar", SimpleNamespace(customer_sessions=_FakeCustomerSessions())
    )
    _session_as(monkeypatch, "user-a")
    resp = asyncio.run(
        webapi._api_me_billing_portal(
            _FakeRequest(body={"guild_id": "no-es-un-numero"})
        )
    )
    assert resp.status == 400


def test_billing_portal_sin_sesion_da_401(monkeypatch):
    monkeypatch.setattr(
        webapi, "_polar", SimpleNamespace(customer_sessions=_FakeCustomerSessions())
    )
    _logged_out(monkeypatch)
    resp = asyncio.run(
        webapi._api_me_billing_portal(_FakeRequest(body={"guild_id": 111}))
    )
    assert resp.status == 401


# ── /api/me/guilds y /api/server/{id}/premium ya no filtran datos de plan ──


def test_api_me_guilds_ya_no_expone_premium_note(temp_db, monkeypatch):
    monkeypatch.setattr(webapi, "_user_guilds_cache", webapi.LRUDict(8))

    async def fake_get_session(request):
        return {"user_id": "42", "access_token": "tok"}

    async def fake_get(url, headers=None):
        raise AssertionError("no debería llamar a Discord en este test")

    monkeypatch.setattr(webapi, "get_session", fake_get_session)

    async def fake_fetch_manage_guilds(request, force=False):
        return [{"id": "123", "name": "S", "icon": None}]

    monkeypatch.setattr(webapi, "_fetch_manage_guilds", fake_fetch_manage_guilds)
    monkeypatch.setattr(webapi, "is_premium_guild", lambda gid: True)

    bot = _FakeBot([_FakeGuild(123, "S")])
    resp = asyncio.run(webapi._api_me_guilds(_FakeRequest(bot=bot)))
    data = json.loads(resp.body)

    conf = data["configured"][0]
    assert "premium_note" not in conf
    assert conf["is_premium"] is True
    assert conf["is_permanent"] is False


def test_api_me_guilds_marca_is_permanent_para_guilds_exentos(temp_db, monkeypatch):
    monkeypatch.setattr(webapi, "_user_guilds_cache", webapi.LRUDict(8))

    async def fake_get_session(request):
        return {"user_id": "42", "access_token": "tok"}

    monkeypatch.setattr(webapi, "get_session", fake_get_session)

    permanent_id = 1521362322331795487

    async def fake_fetch_manage_guilds(request, force=False):
        return [{"id": str(permanent_id), "name": "Purgatory", "icon": None}]

    monkeypatch.setattr(webapi, "_fetch_manage_guilds", fake_fetch_manage_guilds)

    bot = _FakeBot([_FakeGuild(permanent_id, "Purgatory")])
    resp = asyncio.run(webapi._api_me_guilds(_FakeRequest(bot=bot)))
    conf = json.loads(resp.body)["configured"][0]

    assert conf["is_premium"] is True
    assert conf["is_permanent"] is True


def test_api_premium_get_ya_no_expone_note(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": "42"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: object())
    monkeypatch.setattr(webapi, "is_premium_guild", lambda gid: True)

    class Req:
        match_info = {"guild_id": "123"}
        headers = {}
        remote = "1.2.3.4"

    resp = asyncio.run(webapi._api_premium_get(Req()))
    data = json.loads(resp.body)

    assert data == {"premium": True}
