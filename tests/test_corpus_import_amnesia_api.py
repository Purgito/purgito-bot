"""Tests de los endpoints de la Fase 8:
POST /api/server/{guild_id}/settings/corpus/import/{channel_id} (subida de
.txt) y POST /api/server/{guild_id}/settings/corpus/amnesia (borra el
corpus de las últimas 24h).

DB en memoria vía executescript(db.SCHEMA) -- corpus_messages/user_corpus
no tienen columnas de ALTER TABLE, alcanza con el CREATE TABLE base (mismo
criterio que test_trim_corpus.py). get_session/check_guild_access/
_bot_guild parcheados para que guild_api deje pasar.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import aiosqlite
import pytest

import db
import generation
import webapi

_GUILD = 123
_CHANNEL = 10
_USER_ID = "999888777"
_USERNAME = "Frambuesa"


class FakeRequest:
    def __init__(self, guild_id=_GUILD, body=b"", match_info=None, content_length=None):
        self._body = body
        self.match_info = {"guild_id": str(guild_id), **(match_info or {})}
        self.content_length = len(body) if content_length is None else content_length
        self.headers = {}
        self.remote = "1.2.3.4"

    async def read(self):
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
        return {"user_id": _USER_ID, "username": _USERNAME}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(
        webapi, "_bot_guild", lambda request, guild_id: SimpleNamespace()
    )
    monkeypatch.setattr(webapi, "_rate_corpus_import", webapi.LRUDict(64))
    monkeypatch.setattr(webapi, "_rate_delete", webapi.LRUDict(64))


def _run(handler, request):
    return asyncio.run(handler(request))


def _json(resp):
    return json.loads(resp.body)


# ── Import ───────────────────────────────────────────────────────────────────


def test_import_sin_channel_id_devuelve_400(memory_db):
    resp = _run(webapi._api_corpus_import_post, FakeRequest(match_info={}))
    assert resp.status == 400


def test_import_archivo_vacio_devuelve_400(memory_db):
    resp = _run(
        webapi._api_corpus_import_post,
        FakeRequest(body=b"", match_info={"channel_id": str(_CHANNEL)}),
    )
    assert resp.status == 400


def test_import_archivo_demasiado_grande_devuelve_413(memory_db, monkeypatch):
    monkeypatch.setenv("MAX_CORPUS_IMPORT_BYTES", "10")
    resp = _run(
        webapi._api_corpus_import_post,
        FakeRequest(
            body=b"esto es mas de diez bytes de texto",
            match_info={"channel_id": str(_CHANNEL)},
        ),
    )
    assert resp.status == 413


def test_import_no_utf8_devuelve_400(memory_db):
    resp = _run(
        webapi._api_corpus_import_post,
        FakeRequest(body=b"\xff\xfe\x00", match_info={"channel_id": str(_CHANNEL)}),
    )
    assert resp.status == 400


def test_import_sin_texto_aprovechable_devuelve_400(memory_db):
    """Líneas de solo números/símbolos las descarta clean_for_corpus."""
    resp = _run(
        webapi._api_corpus_import_post,
        FakeRequest(body=b"12345\n!!!\n---", match_info={"channel_id": str(_CHANNEL)}),
    )
    assert resp.status == 400


def test_import_exitoso_guarda_las_lineas(memory_db):
    body = "hola a todos\nesto es una prueba\notra linea mas".encode("utf-8")
    resp = _run(
        webapi._api_corpus_import_post,
        FakeRequest(body=body, match_info={"channel_id": str(_CHANNEL)}),
    )

    assert resp.status == 200
    data = _json(resp)
    assert data["imported"] == 3
    assert data["lines_found"] == 3
    assert asyncio.run(db.count_corpus_messages(_GUILD, _CHANNEL)) == 3


def test_import_invalida_el_modelo_markov_cacheado(memory_db, monkeypatch):
    called = []
    monkeypatch.setattr(
        generation, "reset_guild_caches", lambda guild_id: called.append(guild_id)
    )

    _run(
        webapi._api_corpus_import_post,
        FakeRequest(body=b"hola a todos", match_info={"channel_id": str(_CHANNEL)}),
    )

    assert called == [_GUILD]


def test_import_respeta_el_rate_limit(memory_db, monkeypatch):
    monkeypatch.setattr(webapi, "_rate_corpus_import", webapi.LRUDict(64))
    body = b"hola a todos"
    for _ in range(3):
        resp = _run(
            webapi._api_corpus_import_post,
            FakeRequest(body=body, match_info={"channel_id": str(_CHANNEL)}),
        )
        assert resp.status == 200

    resp = _run(
        webapi._api_corpus_import_post,
        FakeRequest(body=body, match_info={"channel_id": str(_CHANNEL)}),
    )
    assert resp.status == 429


def test_import_queda_en_el_audit_log(memory_db):
    _run(
        webapi._api_corpus_import_post,
        FakeRequest(body=b"hola a todos", match_info={"channel_id": str(_CHANNEL)}),
    )

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["action"] == "corpus.import"
    assert entries[0]["user_id"] == int(_USER_ID)


# ── Amnesia ──────────────────────────────────────────────────────────────────


def _iso(hours_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


async def _insert_corpus_at(conn, guild_id, channel_id, created_at):
    await conn.execute(
        "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content, created_at) "
        "VALUES (?, ?, NULL, 'msg', ?)",
        (guild_id, channel_id, created_at),
    )
    await conn.commit()


def test_amnesia_borra_solo_lo_reciente_y_devuelve_los_conteos(memory_db):
    asyncio.run(_insert_corpus_at(memory_db, _GUILD, _CHANNEL, _iso(1)))
    asyncio.run(_insert_corpus_at(memory_db, _GUILD, _CHANNEL, _iso(48)))

    resp = _run(webapi._api_corpus_amnesia_post, FakeRequest())

    assert resp.status == 200
    assert _json(resp)["deleted"]["corpus_messages"] == 1
    assert asyncio.run(db.count_guild_corpus_messages(_GUILD)) == 1


def test_amnesia_invalida_el_modelo_markov_cacheado(memory_db, monkeypatch):
    called = []
    monkeypatch.setattr(
        generation, "reset_guild_caches", lambda guild_id: called.append(guild_id)
    )

    _run(webapi._api_corpus_amnesia_post, FakeRequest())

    assert called == [_GUILD]


def test_amnesia_respeta_el_rate_limit(memory_db, monkeypatch):
    monkeypatch.setattr(webapi, "_rate_delete", webapi.LRUDict(64))
    for _ in range(3):
        resp = _run(webapi._api_corpus_amnesia_post, FakeRequest())
        assert resp.status == 200

    resp = _run(webapi._api_corpus_amnesia_post, FakeRequest())
    assert resp.status == 429


def test_amnesia_queda_en_el_audit_log(memory_db):
    asyncio.run(_insert_corpus_at(memory_db, _GUILD, _CHANNEL, _iso(1)))

    _run(webapi._api_corpus_amnesia_post, FakeRequest())

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["action"] == "corpus.amnesia"
    assert entries[0]["user_id"] == int(_USER_ID)
