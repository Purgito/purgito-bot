"""Tests de las piezas de datos de la feature de Twitch (avisos de "en
vivo"): CRUD en db.py (mismo esquema y mismas variantes por id interno que
youtube_subscriptions, ver test_youtube_dashboard_db.py) y resolve_twitch_channel
en cogs/twitch.py (Helix API mockeada, sin red real).

DB en memoria, mismo estilo que test_youtube_dashboard_db.py.
"""

import asyncio

import aiosqlite
import pytest

import cogs.twitch as twitch_mod
import config
import db

_GUILD_A = 1
_GUILD_B = 2


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
def configured(monkeypatch):
    """La mayoría de estos tests asumen credenciales de Twitch presentes --
    los que prueban el caso "no configurado" las vacían explícitamente."""
    monkeypatch.setattr(config, "TWITCH_CLIENT_ID", "client-id-test")
    monkeypatch.setattr(config, "TWITCH_CLIENT_SECRET", "client-secret-test")
    monkeypatch.setattr(twitch_mod, "_token_cache", {"token": None, "expires_at": 0.0})


# ---------- db: list/add por guild ----------


def test_list_twitch_subs_is_scoped_to_the_guild(memory_db):
    async def run():
        await db.add_twitch_sub(_GUILD_A, "111", "canal_a", 20)
        await db.add_twitch_sub(_GUILD_B, "222", "canal_b", 20)
        return await db.list_twitch_subs(_GUILD_A)

    subs = asyncio.run(run())
    assert len(subs) == 1
    assert subs[0]["twitch_login"] == "canal_a"
    assert subs[0]["last_error"] is None


def test_add_twitch_sub_reports_duplicate(memory_db):
    async def run():
        first = await db.add_twitch_sub(_GUILD_A, "111", "canal_a", 20)
        second = await db.add_twitch_sub(_GUILD_A, "111", "canal_a_repetido", 20)
        return first, second

    first, second = asyncio.run(run())
    assert first is True
    assert second is False  # UNIQUE(guild_id, twitch_user_id): no se duplica


def test_remove_twitch_sub_by_natural_key(memory_db):
    async def run():
        await db.add_twitch_sub(_GUILD_A, "111", "canal_a", 20)
        removed = await db.remove_twitch_sub(_GUILD_A, "111")
        return removed, await db.list_twitch_subs(_GUILD_A)

    removed, remaining = asyncio.run(run())
    assert removed is True
    assert remaining == []


# ---------- db: variantes por id interno ----------


def test_remove_twitch_sub_by_id_only_touches_the_matching_guild(memory_db):
    async def run():
        await db.add_twitch_sub(_GUILD_A, "111", "canal_a", 20)
        subs = await db.list_twitch_subs(_GUILD_A)
        sub_id = subs[0]["id"]

        wrong_guild = await db.remove_twitch_sub_by_id(_GUILD_B, sub_id)
        removed = await db.remove_twitch_sub_by_id(_GUILD_A, sub_id)
        return wrong_guild, removed, await db.list_twitch_subs(_GUILD_A)

    wrong_guild, removed, remaining = asyncio.run(run())
    assert wrong_guild is False
    assert removed is True
    assert remaining == []


def test_remove_twitch_sub_by_id_returns_false_for_unknown_id(memory_db):
    assert asyncio.run(db.remove_twitch_sub_by_id(_GUILD_A, 999)) is False


def test_set_twitch_mention_role_by_id_updates_and_clears(memory_db):
    async def run():
        await db.add_twitch_sub(_GUILD_A, "111", "canal_a", 20)
        sub_id = (await db.list_twitch_subs(_GUILD_A))[0]["id"]

        set_ok = await db.set_twitch_mention_role_by_id(_GUILD_A, sub_id, 555)
        with_role = (await db.list_twitch_subs(_GUILD_A))[0]["mention_role_id"]

        cleared_ok = await db.set_twitch_mention_role_by_id(_GUILD_A, sub_id, None)
        cleared = (await db.list_twitch_subs(_GUILD_A))[0]["mention_role_id"]
        return set_ok, with_role, cleared_ok, cleared

    set_ok, with_role, cleared_ok, cleared = asyncio.run(run())
    assert set_ok is True
    assert with_role == 555
    assert cleared_ok is True
    assert cleared is None


def test_set_twitch_mention_role_by_id_returns_false_for_unknown_id(memory_db):
    assert asyncio.run(db.set_twitch_mention_role_by_id(_GUILD_A, 999, 1)) is False


def test_set_twitch_sub_error_and_update_last_stream_id(memory_db):
    async def run():
        await db.add_twitch_sub(_GUILD_A, "111", "canal_a", 20)
        await db.set_twitch_sub_error(_GUILD_A, "111", db.TWITCH_ERROR_NO_PERMISSION)
        after_error = (await db.list_twitch_subs(_GUILD_A))[0]["last_error"]

        await db.update_last_stream_id(_GUILD_A, "111", "stream-1")
        after_stream = (await db.list_twitch_subs(_GUILD_A))[0]["last_stream_id"]
        return after_error, after_stream

    after_error, after_stream = asyncio.run(run())
    assert after_error == db.TWITCH_ERROR_NO_PERMISSION
    assert after_stream == "stream-1"


def test_get_all_twitch_subs_spans_every_guild(memory_db):
    async def run():
        await db.add_twitch_sub(_GUILD_A, "111", "canal_a", 20)
        await db.add_twitch_sub(_GUILD_B, "222", "canal_b", 20)
        return await db.get_all_twitch_subs()

    subs = asyncio.run(run())
    assert {s["twitch_user_id"] for s in subs} == {"111", "222"}


# ---------- cogs/twitch: resolve_twitch_channel ----------


class _FakeResp:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise twitch_mod.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def _patch_token(monkeypatch):
    monkeypatch.setattr(
        twitch_mod.requests,
        "post",
        lambda *a, **k: _FakeResp({"access_token": "tok", "expires_in": 3600}),
    )


def test_resolve_twitch_channel_happy_path(monkeypatch):
    _patch_token(monkeypatch)
    monkeypatch.setattr(
        twitch_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(
            {"data": [{"id": "999", "login": "canal_x", "display_name": "Canal X"}]}
        ),
    )
    resolved = asyncio.run(twitch_mod.resolve_twitch_channel("canal_x"))
    assert resolved == {"id": "999", "login": "canal_x", "display_name": "Canal X"}


def test_resolve_twitch_channel_accepts_full_url(monkeypatch):
    _patch_token(monkeypatch)
    monkeypatch.setattr(
        twitch_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(
            {"data": [{"id": "999", "login": "canal_x", "display_name": "Canal X"}]}
        ),
    )
    resolved = asyncio.run(
        twitch_mod.resolve_twitch_channel("https://twitch.tv/canal_x?foo=bar")
    )
    assert resolved["login"] == "canal_x"


def test_resolve_twitch_channel_accepts_at_prefix(monkeypatch):
    _patch_token(monkeypatch)
    monkeypatch.setattr(
        twitch_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(
            {"data": [{"id": "999", "login": "canal_x", "display_name": "Canal X"}]}
        ),
    )
    resolved = asyncio.run(twitch_mod.resolve_twitch_channel("@canal_x"))
    assert resolved["login"] == "canal_x"


def test_resolve_twitch_channel_invalid_login_returns_none(monkeypatch):
    _patch_token(monkeypatch)
    # No debería ni llegar a pegarle a la red con un login inválido.
    called = []
    monkeypatch.setattr(
        twitch_mod.requests, "get", lambda *a, **k: called.append(1) or _FakeResp({})
    )
    assert asyncio.run(twitch_mod.resolve_twitch_channel("a")) is None
    assert called == []


def test_resolve_twitch_channel_nonexistent_returns_none(monkeypatch):
    _patch_token(monkeypatch)
    monkeypatch.setattr(
        twitch_mod.requests, "get", lambda *a, **k: _FakeResp({"data": []})
    )
    assert asyncio.run(twitch_mod.resolve_twitch_channel("no_existe")) is None


def test_resolve_twitch_channel_network_error_returns_none(monkeypatch):
    _patch_token(monkeypatch)

    def boom(*a, **k):
        raise twitch_mod.requests.ConnectionError("no network")

    monkeypatch.setattr(twitch_mod.requests, "get", boom)
    assert asyncio.run(twitch_mod.resolve_twitch_channel("canal_x")) is None


def test_resolve_twitch_channel_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "TWITCH_CLIENT_ID", "")
    monkeypatch.setattr(config, "TWITCH_CLIENT_SECRET", "")
    with pytest.raises(twitch_mod.TwitchNotConfigured):
        asyncio.run(twitch_mod.resolve_twitch_channel("canal_x"))


def test_is_configured_reflects_env(monkeypatch):
    assert twitch_mod.is_configured() is True
    monkeypatch.setattr(config, "TWITCH_CLIENT_SECRET", "")
    assert twitch_mod.is_configured() is False


# ---------- cogs/twitch: get_live_streams ----------


def test_get_live_streams_maps_by_user_id(monkeypatch):
    _patch_token(monkeypatch)
    monkeypatch.setattr(
        twitch_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(
            {
                "data": [
                    {
                        "id": "stream-1",
                        "user_id": "111",
                        "user_login": "canal_a",
                        "title": "Jugando",
                        "game_name": "Juego",
                    }
                ]
            }
        ),
    )
    live = asyncio.run(twitch_mod.get_live_streams(["111", "222"]))
    assert set(live.keys()) == {"111"}
    assert live["111"]["id"] == "stream-1"
    assert live["111"]["url"] == "https://twitch.tv/canal_a"


def test_get_live_streams_empty_input_skips_request(monkeypatch):
    called = []
    monkeypatch.setattr(
        twitch_mod.requests, "get", lambda *a, **k: called.append(1) or _FakeResp({})
    )
    assert asyncio.run(twitch_mod.get_live_streams([])) == {}
    assert called == []


def test_get_live_streams_batches_over_100_ids(monkeypatch):
    _patch_token(monkeypatch)
    calls = []

    def fake_get(url, params=None, **k):
        calls.append(params)
        return _FakeResp({"data": []})

    monkeypatch.setattr(twitch_mod.requests, "get", fake_get)
    ids = [str(i) for i in range(150)]
    asyncio.run(twitch_mod.get_live_streams(ids))
    assert len(calls) == 2
    assert len(calls[0]) == 100
    assert len(calls[1]) == 50
