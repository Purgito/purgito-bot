"""Tests de los 4 endpoints de la tab Twitch del dashboard
(/api/server/{guild_id}/twitch[/{id}]), paridad con la categoría Twitch de
/settings. Mismo estilo que test_youtube_webapi.py.

El caso sin paridad en YouTube es la respuesta 503 cuando el bot no tiene
TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET configuradas -- ver
_api_twitch_post/_api_twitch_get en webapi.py.
"""

import asyncio
import json
from types import SimpleNamespace

import aiosqlite
import pytest

import db
import webapi

_GUILD = 123


class FakeRequest:
    def __init__(self, guild_id=_GUILD, body=None, match_info=None, ip="1.2.3.4"):
        self._body = body
        self.match_info = {"guild_id": str(guild_id), **(match_info or {})}
        self.headers = {"X-Forwarded-For": ip}
        self.remote = ip

    async def json(self):
        if self._body is None:
            raise ValueError("sin body")
        return self._body


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


@pytest.fixture(autouse=True)
def allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": "42"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(
        webapi,
        "_bot_guild",
        lambda request, guild_id: SimpleNamespace(get_channel=lambda cid: None),
    )


@pytest.fixture(autouse=True)
def fresh_rate_limit_stores(monkeypatch):
    monkeypatch.setattr(webapi, "_rate_post", webapi.LRUDict(64))
    monkeypatch.setattr(webapi, "_rate_delete", webapi.LRUDict(64))


@pytest.fixture(autouse=True)
def configured_and_fake_resolve(monkeypatch):
    """Por default la integración está "configurada" y cualquier canal
    resuelve con un id/login fijo -- los tests del caso no-configurado y del
    caso canal-inexistente lo pisan."""
    monkeypatch.setattr(webapi, "twitch_is_configured", lambda: True)

    async def fake_resolve(channel_login):
        return {"id": "999", "login": "canal_x", "display_name": "Canal X"}

    monkeypatch.setattr(webapi, "resolve_twitch_channel", fake_resolve)


def _run(handler, request):
    return asyncio.run(handler(request))


def _json(resp):
    return json.loads(resp.body)


# ---------- GET ----------


def test_get_lists_subscriptions_of_the_guild(memory_db):
    asyncio.run(db.add_twitch_sub(_GUILD, "111", "canal_a", 2))

    resp = _run(webapi._api_twitch_get, FakeRequest())

    assert resp.status == 200
    body = _json(resp)
    assert body["configured"] is True
    assert len(body["subscriptions"]) == 1
    sub = body["subscriptions"][0]
    assert sub["twitch_login"] == "canal_a"
    assert sub["discord_channel_id"] == "2"
    assert sub["last_error"] is None


def test_get_is_scoped_to_the_guild(memory_db):
    asyncio.run(db.add_twitch_sub(999, "111", "canal_ajeno", 2))

    resp = _run(webapi._api_twitch_get, FakeRequest())

    assert _json(resp)["subscriptions"] == []


def test_get_reports_not_configured(memory_db, monkeypatch):
    monkeypatch.setattr(webapi, "twitch_is_configured", lambda: False)

    resp = _run(webapi._api_twitch_get, FakeRequest())

    assert resp.status == 200
    assert _json(resp)["configured"] is False


# ---------- POST ----------


def test_post_happy_path_resolves_login_and_saves(memory_db):
    req = FakeRequest(body={"channel_login": "canal_x", "discord_channel_id": "555"})

    resp = _run(webapi._api_twitch_post, req)

    assert resp.status == 200
    assert _json(resp)["added"] is True
    subs = asyncio.run(db.list_twitch_subs(_GUILD))
    assert len(subs) == 1
    assert subs[0]["twitch_login"] == "canal_x"
    assert subs[0]["twitch_user_id"] == "999"


def test_post_duplicate_subscription_returns_added_false(memory_db):
    req = FakeRequest(body={"channel_login": "canal_x", "discord_channel_id": "555"})
    _run(webapi._api_twitch_post, req)

    resp = _run(
        webapi._api_twitch_post,
        FakeRequest(body={"channel_login": "canal_x", "discord_channel_id": "555"}),
    )

    assert resp.status == 200
    assert _json(resp)["added"] is False
    assert len(asyncio.run(db.list_twitch_subs(_GUILD))) == 1


def test_post_rejects_channel_that_does_not_resolve(memory_db, monkeypatch):
    async def fake_resolve_none(channel_login):
        return None

    monkeypatch.setattr(webapi, "resolve_twitch_channel", fake_resolve_none)
    req = FakeRequest(body={"channel_login": "no_existe", "discord_channel_id": "555"})

    resp = _run(webapi._api_twitch_post, req)

    assert resp.status == 400
    assert asyncio.run(db.list_twitch_subs(_GUILD)) == []


def test_post_missing_fields_returns_400(memory_db):
    resp = _run(webapi._api_twitch_post, FakeRequest(body={"channel_login": "canal_x"}))
    assert resp.status == 400


def test_post_returns_503_when_not_configured(memory_db, monkeypatch):
    monkeypatch.setattr(webapi, "twitch_is_configured", lambda: False)
    req = FakeRequest(body={"channel_login": "canal_x", "discord_channel_id": "555"})

    resp = _run(webapi._api_twitch_post, req)

    assert resp.status == 503
    assert asyncio.run(db.list_twitch_subs(_GUILD)) == []


def test_post_is_rate_limited_after_five_per_minute(memory_db):
    for _ in range(5):
        req = FakeRequest(
            body={"channel_login": "canal_x", "discord_channel_id": "555"}
        )
        resp = _run(webapi._api_twitch_post, req)
        assert resp.status == 200

    sixth = FakeRequest(body={"channel_login": "canal_y", "discord_channel_id": "555"})
    resp = _run(webapi._api_twitch_post, sixth)

    assert resp.status == 429
    assert len(asyncio.run(db.list_twitch_subs(_GUILD))) == 1


# ---------- DELETE ----------


def test_delete_happy_path_removes_the_row(memory_db):
    asyncio.run(db.add_twitch_sub(_GUILD, "111", "canal_a", 2))
    sub_id = asyncio.run(db.list_twitch_subs(_GUILD))[0]["id"]

    resp = _run(
        webapi._api_twitch_delete, FakeRequest(match_info={"sub_id": str(sub_id)})
    )

    assert resp.status == 200
    assert _json(resp)["removed"] is True
    assert asyncio.run(db.list_twitch_subs(_GUILD)) == []


def test_delete_unknown_id_returns_removed_false(memory_db):
    resp = _run(webapi._api_twitch_delete, FakeRequest(match_info={"sub_id": "999"}))
    assert resp.status == 200
    assert _json(resp)["removed"] is False


def test_delete_is_rate_limited_after_three_per_minute(memory_db):
    asyncio.run(db.add_twitch_sub(_GUILD, "111", "canal_a", 2))
    sub_id = asyncio.run(db.list_twitch_subs(_GUILD))[0]["id"]

    for _ in range(3):
        resp = _run(
            webapi._api_twitch_delete, FakeRequest(match_info={"sub_id": str(sub_id)})
        )
        assert resp.status == 200

    resp = _run(
        webapi._api_twitch_delete, FakeRequest(match_info={"sub_id": str(sub_id)})
    )
    assert resp.status == 429


# ---------- PATCH ----------


def test_patch_sets_and_clears_mention_role(memory_db):
    asyncio.run(db.add_twitch_sub(_GUILD, "111", "canal_a", 2))
    sub_id = asyncio.run(db.list_twitch_subs(_GUILD))[0]["id"]

    set_resp = _run(
        webapi._api_twitch_patch,
        FakeRequest(
            match_info={"sub_id": str(sub_id)}, body={"mention_role_id": "777"}
        ),
    )
    assert set_resp.status == 200
    assert _json(set_resp)["updated"] is True
    assert asyncio.run(db.list_twitch_subs(_GUILD))[0]["mention_role_id"] == 777

    clear_resp = _run(
        webapi._api_twitch_patch,
        FakeRequest(match_info={"sub_id": str(sub_id)}, body={"mention_role_id": None}),
    )
    assert clear_resp.status == 200
    assert asyncio.run(db.list_twitch_subs(_GUILD))[0]["mention_role_id"] is None


def test_patch_missing_field_returns_400(memory_db):
    resp = _run(
        webapi._api_twitch_patch, FakeRequest(match_info={"sub_id": "1"}, body={})
    )
    assert resp.status == 400
