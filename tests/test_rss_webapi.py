"""Tests de los endpoints /api/server/{guild_id}/rss (GET/POST/DELETE/PATCH)."""

import asyncio
import json
from types import SimpleNamespace

import aiosqlite
import pytest

import db
import webapi

_GUILD = 123456789


class FakeRequest:
    def __init__(self, match_info=None, body=None, query=None):
        self.match_info = match_info or {"guild_id": str(_GUILD)}
        self._body = body
        self.query = query or {}
        self.headers = {}
        self.remote = "127.0.0.1"
        self.app = {
            "bot": SimpleNamespace(
                get_guild=lambda gid: SimpleNamespace(
                    get_channel=lambda cid: SimpleNamespace(name=f"chan-{cid}"),
                    get_role=lambda rid: SimpleNamespace(name=f"role-{rid}"),
                )
            )
        }

    async def json(self):
        if self._body is None:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return self._body


def _json(resp):
    return json.loads(resp.text)


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
def fake_resolve(monkeypatch):
    async def fake_resolve_rss_feed(feed_url):
        return {"title": "Blog de prueba", "latest_item_id": "ITEM123"}

    monkeypatch.setattr(webapi, "resolve_rss_feed", fake_resolve_rss_feed)


def _run(handler, request):
    return asyncio.run(handler(request))


# ---------- GET ----------


def test_get_lists_subscriptions_of_the_guild(memory_db):
    asyncio.run(db.add_rss_sub(_GUILD, "https://ejemplo.com/rss", "Blog A", 2))

    resp = _run(webapi._api_rss_get, FakeRequest())

    assert resp.status == 200
    body = _json(resp)
    assert len(body["subscriptions"]) == 1
    sub = body["subscriptions"][0]
    assert sub["feed_title"] == "Blog A"
    assert sub["feed_url"] == "https://ejemplo.com/rss"
    assert sub["discord_channel_id"] == "2"
    assert sub["last_error"] is None


def test_get_is_scoped_to_the_guild(memory_db):
    asyncio.run(db.add_rss_sub(999, "https://otro.com/feed", "Blog ajeno", 2))

    resp = _run(webapi._api_rss_get, FakeRequest())

    assert _json(resp)["subscriptions"] == []


# ---------- POST ----------


def test_post_happy_path_resolves_title_and_saves(memory_db):
    req = FakeRequest(
        body={"feed_url": "https://ejemplo.com/rss", "discord_channel_id": "555"}
    )

    resp = _run(webapi._api_rss_post, req)

    assert resp.status == 200
    assert _json(resp)["added"] is True
    subs = asyncio.run(db.list_rss_subs(_GUILD))
    assert len(subs) == 1
    assert subs[0]["feed_title"] == "Blog de prueba"
    assert subs[0]["last_item_id"] == "ITEM123"


def test_post_duplicate_subscription_returns_added_false(memory_db):
    req = FakeRequest(
        body={"feed_url": "https://ejemplo.com/rss", "discord_channel_id": "555"}
    )
    _run(webapi._api_rss_post, req)

    resp = _run(
        webapi._api_rss_post,
        FakeRequest(
            body={"feed_url": "https://ejemplo.com/rss", "discord_channel_id": "555"}
        ),
    )

    assert resp.status == 200
    assert _json(resp)["added"] is False
    assert len(asyncio.run(db.list_rss_subs(_GUILD))) == 1


def test_post_rejects_feed_that_does_not_resolve(memory_db, monkeypatch):
    async def fake_resolve_none(feed_url):
        return None

    monkeypatch.setattr(webapi, "resolve_rss_feed", fake_resolve_none)
    req = FakeRequest(
        body={"feed_url": "https://invalido.com/404", "discord_channel_id": "555"}
    )

    resp = _run(webapi._api_rss_post, req)

    assert resp.status == 400
    assert asyncio.run(db.list_rss_subs(_GUILD)) == []


def test_post_requires_discord_channel_id():
    resp = _run(
        webapi._api_rss_post, FakeRequest(body={"feed_url": "https://ejemplo.com"})
    )
    assert resp.status == 400


# ---------- DELETE ----------


def test_delete_removes_subscription_of_the_guild(memory_db):
    asyncio.run(db.add_rss_sub(_GUILD, "https://ejemplo.com/rss", "Blog A", 2))
    sub = asyncio.run(db.list_rss_subs(_GUILD))[0]

    req = FakeRequest(match_info={"guild_id": str(_GUILD), "sub_id": str(sub["id"])})
    resp = _run(webapi._api_rss_delete, req)

    assert resp.status == 200
    assert _json(resp)["removed"] is True
    assert asyncio.run(db.list_rss_subs(_GUILD)) == []


def test_delete_cannot_remove_subscription_of_another_guild(memory_db):
    asyncio.run(db.add_rss_sub(999, "https://ejemplo.com/rss", "Blog A", 2))
    sub = asyncio.run(db.list_rss_subs(999))[0]

    req = FakeRequest(match_info={"guild_id": str(_GUILD), "sub_id": str(sub["id"])})
    resp = _run(webapi._api_rss_delete, req)

    assert resp.status == 200
    assert _json(resp)["removed"] is False
    assert len(asyncio.run(db.list_rss_subs(999))) == 1


# ---------- PATCH ----------


def test_patch_sets_mention_role(memory_db):
    asyncio.run(db.add_rss_sub(_GUILD, "https://ejemplo.com/rss", "Blog A", 2))
    sub = asyncio.run(db.list_rss_subs(_GUILD))[0]

    req = FakeRequest(
        match_info={"guild_id": str(_GUILD), "sub_id": str(sub["id"])},
        body={"mention_role_id": "777"},
    )
    resp = _run(webapi._api_rss_patch, req)

    assert resp.status == 200
    assert _json(resp)["updated"] is True
    subs = asyncio.run(db.list_rss_subs(_GUILD))
    assert subs[0]["mention_role_id"] == 777


def test_patch_clears_mention_role_with_null(memory_db):
    asyncio.run(
        db.add_rss_sub(
            _GUILD, "https://ejemplo.com/rss", "Blog A", 2, mention_role_id=777
        )
    )
    sub = asyncio.run(db.list_rss_subs(_GUILD))[0]

    req = FakeRequest(
        match_info={"guild_id": str(_GUILD), "sub_id": str(sub["id"])},
        body={"mention_role_id": None},
    )
    resp = _run(webapi._api_rss_patch, req)

    assert resp.status == 200
    assert _json(resp)["updated"] is True
    subs = asyncio.run(db.list_rss_subs(_GUILD))
    assert subs[0]["mention_role_id"] is None
