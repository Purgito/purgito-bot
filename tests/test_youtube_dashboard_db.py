"""Tests de las piezas de datos que agrega la tab YouTube del dashboard web.

db.py: list_youtube_subs ya hacía de "get_youtube_subs_for_guild" (se
reutiliza tal cual, sin duplicar), add_youtube_sub ya soporta el alta con
duplicado -- lo que faltaba y se agrega acá son las variantes por id interno
(remove_youtube_sub_by_id, set_youtube_mention_role_by_id), que el dashboard
necesita porque referencia filas por id, no por youtube_channel_id como hace
/settings.

cogs/youtube.py: resolve_youtube_channel es la validación nueva para el alta
desde el dashboard -- a diferencia de get_latest_video, un canal real sin
videos todavía no debe bloquear el alta.

DB en memoria y mocking de requests/feedparser, mismo estilo que
test_youtube_check.py y test_gif_dedup.py.
"""

import asyncio

import aiosqlite
import pytest

import cogs.youtube as youtube_mod
import db

_GUILD_A = 1
_GUILD_B = 2
_YT_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"


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


def test_list_youtube_subs_is_scoped_to_the_guild(memory_db):
    async def run():
        await db.add_youtube_sub(_GUILD_A, 10, _YT_ID, "Canal A", 20)
        await db.add_youtube_sub(_GUILD_B, 10, "UCyyy", "Canal B", 20)
        return await db.list_youtube_subs(_GUILD_A)

    subs = asyncio.run(run())
    assert len(subs) == 1
    assert subs[0]["youtube_channel_name"] == "Canal A"
    assert subs[0]["last_error"] is None


def test_add_youtube_sub_reports_duplicate(memory_db):
    async def run():
        first = await db.add_youtube_sub(_GUILD_A, 10, _YT_ID, "Canal A", 20)
        second = await db.add_youtube_sub(
            _GUILD_A, 10, _YT_ID, "Canal A (repetido)", 20
        )
        return first, second

    first, second = asyncio.run(run())
    assert first is True
    assert second is False  # UNIQUE(guild_id, youtube_channel_id): no se duplica


# ---------- db: variantes por id interno ----------


def test_remove_youtube_sub_by_id_only_touches_the_matching_guild(memory_db):
    async def run():
        await db.add_youtube_sub(_GUILD_A, 10, _YT_ID, "Canal A", 20)
        subs = await db.list_youtube_subs(_GUILD_A)
        sub_id = subs[0]["id"]

        # Otro guild no puede borrar una fila que no es suya.
        wrong_guild = await db.remove_youtube_sub_by_id(_GUILD_B, sub_id)
        removed = await db.remove_youtube_sub_by_id(_GUILD_A, sub_id)
        return wrong_guild, removed, await db.list_youtube_subs(_GUILD_A)

    wrong_guild, removed, remaining = asyncio.run(run())
    assert wrong_guild is False
    assert removed is True
    assert remaining == []


def test_remove_youtube_sub_by_id_returns_false_for_unknown_id(memory_db):
    assert asyncio.run(db.remove_youtube_sub_by_id(_GUILD_A, 999)) is False


def test_set_youtube_mention_role_by_id_updates_and_clears(memory_db):
    async def run():
        await db.add_youtube_sub(_GUILD_A, 10, _YT_ID, "Canal A", 20)
        sub_id = (await db.list_youtube_subs(_GUILD_A))[0]["id"]

        set_ok = await db.set_youtube_mention_role_by_id(_GUILD_A, sub_id, 555)
        with_role = (await db.list_youtube_subs(_GUILD_A))[0]["mention_role_id"]

        cleared_ok = await db.set_youtube_mention_role_by_id(_GUILD_A, sub_id, None)
        cleared = (await db.list_youtube_subs(_GUILD_A))[0]["mention_role_id"]
        return set_ok, with_role, cleared_ok, cleared

    set_ok, with_role, cleared_ok, cleared = asyncio.run(run())
    assert set_ok is True
    assert with_role == 555
    assert cleared_ok is True
    assert cleared is None


def test_set_youtube_mention_role_by_id_returns_false_for_unknown_id(memory_db):
    assert asyncio.run(db.set_youtube_mention_role_by_id(_GUILD_A, 999, 1)) is False


# ---------- cogs/youtube: resolve_youtube_channel ----------


def _feed_xml(entries_xml: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <author><name>Canal de prueba</name></author>
  {entries_xml}
</feed>""".encode()


_ENTRY = """
<entry>
  <id>yt:video:VIDEOID123</id>
  <yt:videoId>VIDEOID123</yt:videoId>
  <title>Un video</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=VIDEOID123"/>
  <author><name>Canal de prueba</name></author>
</entry>
"""


class _FakeResp:
    def __init__(self, content, status=200):
        self.content = content
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise youtube_mod.requests.HTTPError(f"HTTP {self._status}")


def test_resolve_youtube_channel_with_videos_returns_name_and_latest_id(monkeypatch):
    monkeypatch.setattr(
        youtube_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(_feed_xml(_ENTRY)),
    )
    resolved = asyncio.run(youtube_mod.resolve_youtube_channel(_YT_ID))
    assert resolved == {"name": "Canal de prueba", "latest_video_id": "VIDEOID123"}


def test_resolve_youtube_channel_valid_but_no_videos_allows_generic_save(monkeypatch):
    """Canal real, cero videos subidos: no debe bloquear el alta -- distinto
    de get_latest_video, donde 'sin entradas' significa 'nada que avisar'."""
    monkeypatch.setattr(
        youtube_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(_feed_xml()),
    )
    resolved = asyncio.run(youtube_mod.resolve_youtube_channel(_YT_ID))
    assert resolved == {"name": None, "latest_video_id": None}


def test_resolve_youtube_channel_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(
        youtube_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(b"", status=404),
    )
    assert asyncio.run(youtube_mod.resolve_youtube_channel(_YT_ID)) is None


def test_resolve_youtube_channel_returns_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise youtube_mod.requests.ConnectionError("no network")

    monkeypatch.setattr(youtube_mod.requests, "get", boom)
    assert asyncio.run(youtube_mod.resolve_youtube_channel(_YT_ID)) is None


def test_get_latest_video_still_returns_none_when_channel_has_no_videos(monkeypatch):
    """Contraste con resolve_youtube_channel: get_latest_video NO debe
    cambiar de comportamiento -- lo usa el chequeo periódico, donde 'sin
    entradas' sigue significando 'nada nuevo que avisar'."""
    monkeypatch.setattr(
        youtube_mod.requests,
        "get",
        lambda *a, **k: _FakeResp(_feed_xml()),
    )
    assert asyncio.run(youtube_mod.get_latest_video(_YT_ID)) is None
