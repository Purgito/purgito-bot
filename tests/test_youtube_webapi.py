"""Tests de los 4 endpoints nuevos de la tab YouTube del dashboard
(/api/server/{guild_id}/youtube[/{id}]), paridad con la categoría YouTube de
/settings.

Los handlers se llaman directo (sin servidor HTTP real), mismo patrón que
test_premium_checkout.py: se parchea get_session/check_guild_access/_bot_guild
para que guild_api deje pasar, y un FakeRequest imita lo que aiohttp expone
(match_info, json(), headers, remote).

DB en memoria de verdad (no mocks de db.py): son estos endpoints los que
más se benefician de un test de integración real, porque casi toda su
lógica es "traducir HTTP a las funciones de db.py" que ya se prueban aparte
en test_youtube_dashboard_db.py.
"""

import asyncio
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
    """_rate_post/_rate_delete son estado compartido por IP entre todos los
    endpoints (gifs incluido): cada test arranca con contadores limpios."""
    monkeypatch.setattr(webapi, "_rate_post", webapi.LRUDict(64))
    monkeypatch.setattr(webapi, "_rate_delete", webapi.LRUDict(64))


@pytest.fixture(autouse=True)
def fake_resolve(monkeypatch):
    """Por default resuelve cualquier canal con un nombre fijo y un video
    último -- los tests que necesiten simular un canal inválido lo pisan."""

    async def fake_resolve_youtube_channel(channel_id):
        return {"name": "Canal de prueba", "latest_video_id": "VIDEOID123"}

    monkeypatch.setattr(webapi, "resolve_youtube_channel", fake_resolve_youtube_channel)


def _run(handler, request):
    return asyncio.run(handler(request))


# ---------- GET ----------


def test_get_lists_subscriptions_of_the_guild(memory_db):
    asyncio.run(db.add_youtube_sub(_GUILD, 1, "UCxxx", "Canal A", 2))

    resp = _run(webapi._api_youtube_get, FakeRequest())

    assert resp.status == 200
    body = _json(resp)
    assert len(body["subscriptions"]) == 1
    sub = body["subscriptions"][0]
    assert sub["youtube_channel_name"] == "Canal A"
    assert sub["discord_channel_id"] == "2"
    assert sub["last_error"] is None


def test_get_is_scoped_to_the_guild(memory_db):
    asyncio.run(db.add_youtube_sub(999, 1, "UCxxx", "Canal ajeno", 2))

    resp = _run(webapi._api_youtube_get, FakeRequest())

    assert _json(resp)["subscriptions"] == []


# ---------- POST ----------


def test_post_happy_path_resolves_name_and_saves(memory_db):
    req = FakeRequest(body={"channel_id": "UCxxx", "discord_channel_id": "555"})

    resp = _run(webapi._api_youtube_post, req)

    assert resp.status == 200
    assert _json(resp)["added"] is True
    subs = asyncio.run(db.list_youtube_subs(_GUILD))
    assert len(subs) == 1
    assert subs[0]["youtube_channel_name"] == "Canal de prueba"
    assert subs[0]["last_video_id"] == "VIDEOID123"


def test_post_duplicate_subscription_returns_added_false(memory_db):
    req = FakeRequest(body={"channel_id": "UCxxx", "discord_channel_id": "555"})
    _run(webapi._api_youtube_post, req)

    resp = _run(
        webapi._api_youtube_post,
        FakeRequest(body={"channel_id": "UCxxx", "discord_channel_id": "555"}),
    )

    assert resp.status == 200
    assert _json(resp)["added"] is False
    assert len(asyncio.run(db.list_youtube_subs(_GUILD))) == 1


def test_post_rejects_channel_that_does_not_resolve(memory_db, monkeypatch):
    async def fake_resolve_none(channel_id):
        return None

    monkeypatch.setattr(webapi, "resolve_youtube_channel", fake_resolve_none)
    req = FakeRequest(
        body={"channel_id": "not-a-real-channel", "discord_channel_id": "555"}
    )

    resp = _run(webapi._api_youtube_post, req)

    assert resp.status == 400
    assert asyncio.run(db.list_youtube_subs(_GUILD)) == []


def test_post_missing_fields_returns_400(memory_db):
    resp = _run(webapi._api_youtube_post, FakeRequest(body={"channel_id": "UCxxx"}))
    assert resp.status == 400


def test_post_is_rate_limited_after_five_per_minute(memory_db):
    for _ in range(5):
        req = FakeRequest(body={"channel_id": "UCxxx", "discord_channel_id": "555"})
        resp = _run(webapi._api_youtube_post, req)
        assert resp.status == 200

    sixth = FakeRequest(body={"channel_id": "UCyyy", "discord_channel_id": "555"})
    resp = _run(webapi._api_youtube_post, sixth)

    assert resp.status == 429
    # Las 5 previas fueron el mismo canal (duplicado): una sola fila real.
    assert len(asyncio.run(db.list_youtube_subs(_GUILD))) == 1


# ---------- DELETE ----------


def test_delete_happy_path_removes_the_row(memory_db):
    asyncio.run(db.add_youtube_sub(_GUILD, 1, "UCxxx", "Canal A", 2))
    sub_id = asyncio.run(db.list_youtube_subs(_GUILD))[0]["id"]

    resp = _run(
        webapi._api_youtube_delete, FakeRequest(match_info={"sub_id": str(sub_id)})
    )

    assert resp.status == 200
    assert _json(resp)["removed"] is True
    assert asyncio.run(db.list_youtube_subs(_GUILD)) == []


def test_delete_unknown_id_returns_removed_false(memory_db):
    resp = _run(webapi._api_youtube_delete, FakeRequest(match_info={"sub_id": "999"}))
    assert resp.status == 200
    assert _json(resp)["removed"] is False


def test_delete_is_rate_limited_after_three_per_minute(memory_db):
    asyncio.run(db.add_youtube_sub(_GUILD, 1, "UCxxx", "Canal A", 2))
    sub_id = asyncio.run(db.list_youtube_subs(_GUILD))[0]["id"]

    for _ in range(3):
        resp = _run(
            webapi._api_youtube_delete, FakeRequest(match_info={"sub_id": str(sub_id)})
        )
        assert resp.status == 200

    resp = _run(
        webapi._api_youtube_delete, FakeRequest(match_info={"sub_id": str(sub_id)})
    )
    assert resp.status == 429


# ---------- PATCH ----------


def test_patch_sets_and_clears_mention_role(memory_db):
    asyncio.run(db.add_youtube_sub(_GUILD, 1, "UCxxx", "Canal A", 2))
    sub_id = asyncio.run(db.list_youtube_subs(_GUILD))[0]["id"]

    set_resp = _run(
        webapi._api_youtube_patch,
        FakeRequest(
            match_info={"sub_id": str(sub_id)}, body={"mention_role_id": "777"}
        ),
    )
    assert set_resp.status == 200
    assert _json(set_resp)["updated"] is True
    assert asyncio.run(db.list_youtube_subs(_GUILD))[0]["mention_role_id"] == 777

    clear_resp = _run(
        webapi._api_youtube_patch,
        FakeRequest(match_info={"sub_id": str(sub_id)}, body={"mention_role_id": None}),
    )
    assert clear_resp.status == 200
    assert asyncio.run(db.list_youtube_subs(_GUILD))[0]["mention_role_id"] is None


def test_patch_missing_field_returns_400(memory_db):
    resp = _run(
        webapi._api_youtube_patch, FakeRequest(match_info={"sub_id": "1"}, body={})
    )
    assert resp.status == 400


def _json(resp):
    import json

    return json.loads(resp.body)
