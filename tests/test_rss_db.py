"""Tests de persistencia y funciones de datos para suscripciones RSS/Atom genéricas."""

import asyncio

import aiosqlite
import pytest

import cogs.rss as rss_mod
import db

_GUILD_A = 1
_GUILD_B = 2
_FEED_URL_A = "https://ejemplo.com/feed.xml"
_FEED_URL_B = "https://otro-sitio.com/rss"


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


# ---------- db: list/add por guild ----------


def test_list_rss_subs_is_scoped_to_the_guild(memory_db):
    async def run():
        await db.add_rss_sub(_GUILD_A, _FEED_URL_A, "Feed A", 20)
        await db.add_rss_sub(_GUILD_B, _FEED_URL_B, "Feed B", 20)
        return await db.list_rss_subs(_GUILD_A)

    subs = asyncio.run(run())
    assert len(subs) == 1
    assert subs[0]["feed_title"] == "Feed A"
    assert subs[0]["feed_url"] == _FEED_URL_A
    assert subs[0]["last_error"] is None


def test_add_rss_sub_reports_duplicate(memory_db):
    async def run():
        first = await db.add_rss_sub(_GUILD_A, _FEED_URL_A, "Feed A", 20)
        second = await db.add_rss_sub(_GUILD_A, _FEED_URL_A, "Feed A (repetido)", 20)
        return first, second

    first, second = asyncio.run(run())
    assert first is True
    assert second is False  # UNIQUE(guild_id, feed_url): no se duplica


# ---------- db: variantes por id interno ----------


def test_remove_rss_sub_by_id_only_touches_the_matching_guild(memory_db):
    async def run():
        await db.add_rss_sub(_GUILD_A, _FEED_URL_A, "Feed A", 20)
        subs = await db.list_rss_subs(_GUILD_A)
        sub_id = subs[0]["id"]

        wrong_guild = await db.remove_rss_sub_by_id(_GUILD_B, sub_id)
        removed = await db.remove_rss_sub_by_id(_GUILD_A, sub_id)
        return wrong_guild, removed, await db.list_rss_subs(_GUILD_A)

    wrong_guild, removed, remaining = asyncio.run(run())
    assert wrong_guild is False
    assert removed is True
    assert remaining == []


def test_remove_rss_sub_by_id_returns_false_for_unknown_id(memory_db):
    assert asyncio.run(db.remove_rss_sub_by_id(_GUILD_A, 999)) is False


def test_set_rss_mention_role_by_id_updates_and_clears(memory_db):
    async def run():
        await db.add_rss_sub(_GUILD_A, _FEED_URL_A, "Feed A", 20)
        sub_id = (await db.list_rss_subs(_GUILD_A))[0]["id"]

        set_ok = await db.set_rss_mention_role_by_id(_GUILD_A, sub_id, 555)
        with_role = (await db.list_rss_subs(_GUILD_A))[0]["mention_role_id"]

        cleared_ok = await db.set_rss_mention_role_by_id(_GUILD_A, sub_id, None)
        cleared = (await db.list_rss_subs(_GUILD_A))[0]["mention_role_id"]
        return set_ok, with_role, cleared_ok, cleared

    set_ok, with_role, cleared_ok, cleared = asyncio.run(run())
    assert set_ok is True
    assert with_role == 555
    assert cleared_ok is True
    assert cleared is None


def test_set_rss_mention_role_by_id_returns_false_for_unknown_id(memory_db):
    assert asyncio.run(db.set_rss_mention_role_by_id(_GUILD_A, 999, 1)) is False


# ---------- cogs/rss: resolve_rss_feed ----------


def _feed_xml(title: str = "Blog de prueba", entries_xml: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{title}</title>
    <link>https://ejemplo.com</link>
    <description>Un blog</description>
    {entries_xml}
  </channel>
</rss>""".encode()


_RSS_ENTRY = """
<item>
  <guid>item-unique-id-123</guid>
  <title>Primer post</title>
  <link>https://ejemplo.com/post-1</link>
</item>
"""


class _FakeResp:
    def __init__(self, content, status=200):
        if isinstance(content, str):
            self.content = content.encode("utf-8")
            self.text = content
        else:
            self.content = content
            self.text = content.decode("utf-8", errors="replace")
        self._status = status
        self.status_code = status

    def raise_for_status(self):
        if self._status >= 400:
            raise rss_mod.requests.HTTPError(f"HTTP {self._status}", response=self)


def test_resolve_rss_feed_with_items_returns_title_and_latest_id(monkeypatch):
    monkeypatch.setattr(
        rss_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(_feed_xml("Mi Blog", _RSS_ENTRY)),
    )
    resolved = asyncio.run(rss_mod.resolve_rss_feed(_FEED_URL_A))
    assert resolved == {
        "title": "Mi Blog",
        "latest_item_id": "item-unique-id-123",
    }


def test_resolve_rss_feed_valid_but_no_items_allows_subscription(monkeypatch):
    monkeypatch.setattr(
        rss_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(_feed_xml("Blog Vacío", "")),
    )
    resolved = asyncio.run(rss_mod.resolve_rss_feed(_FEED_URL_A))
    assert resolved == {
        "title": "Blog Vacío",
        "latest_item_id": None,
    }


def test_resolve_rss_feed_invalid_html_rejected(monkeypatch):
    html = "<html><head><title>Página normal</title></head><body>No soy un feed</body></html>".encode(
        "utf-8"
    )
    monkeypatch.setattr(
        rss_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(html),
    )
    assert asyncio.run(rss_mod.resolve_rss_feed(_FEED_URL_A)) is None


def test_resolve_rss_feed_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(
        rss_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(b"", status=404),
    )
    assert asyncio.run(rss_mod.resolve_rss_feed(_FEED_URL_A)) is None


def test_resolve_rss_feed_returns_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise rss_mod.requests.ConnectionError("no network")

    monkeypatch.setattr(rss_mod.requests, "get", boom)
    assert asyncio.run(rss_mod.resolve_rss_feed(_FEED_URL_A)) is None


def test_get_latest_rss_item_raises_feed_not_found_on_404(monkeypatch):
    monkeypatch.setattr(
        rss_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(b"", status=404),
    )
    with pytest.raises(rss_mod.RSSFeedNotFound):
        asyncio.run(rss_mod.get_latest_rss_item(_FEED_URL_A))


def test_get_latest_rss_item_returns_none_on_transient_http_error(monkeypatch):
    monkeypatch.setattr(
        rss_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(b"", status=500),
    )
    assert asyncio.run(rss_mod.get_latest_rss_item(_FEED_URL_A)) is None
