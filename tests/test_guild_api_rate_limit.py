"""Rate limit genérico del wrapper guild_api (AUDITORIA_SEGURIDAD.md §6):
de los ~80 endpoints bajo @guild_api, solo un puñado tenía su propio
_rate_ok puntual -- el resto nunca se auditó sistemáticamente. Este test
cubre la red de seguridad agregada directamente en el wrapper: aplica a
escrituras (POST/PUT/PATCH/DELETE), no a GET, y la clave es por usuario de
sesión, no por IP.

Mismo estilo que test_corpus_import_amnesia_api.py: FakeRequest + DB en
memoria + get_session/check_guild_access/_bot_guild parcheados para que
guild_api deje pasar.
"""

import asyncio
import json
from types import SimpleNamespace

import aiosqlite
import pytest

import db
import webapi

_GUILD = 123
_CHANNEL = 10


class FakeRequest:
    def __init__(self, guild_id=_GUILD, channel_id=_CHANNEL, method="DELETE"):
        self.match_info = {"guild_id": str(guild_id), "channel_id": str(channel_id)}
        self.method = method
        self.headers = {}
        self.remote = "1.2.3.4"

    async def read(self):
        return b""

    async def json(self):
        return {}


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
    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(
        webapi, "_bot_guild", lambda request, guild_id: SimpleNamespace()
    )
    monkeypatch.setattr(webapi, "_rate_guild_api_write", webapi.LRUDict(64))


def _session_for(user_id):
    async def fake_get_session(request):
        return {"user_id": user_id, "username": "u"}

    return fake_get_session


def _run(handler, request):
    return asyncio.run(handler(request))


def test_writes_are_capped_per_user(memory_db, monkeypatch):
    monkeypatch.setattr(webapi, "get_session", _session_for("111"))

    for _ in range(60):
        resp = _run(webapi._api_corpus_delete, FakeRequest())
        assert resp.status == 200

    resp = _run(webapi._api_corpus_delete, FakeRequest())
    assert resp.status == 429
    assert "demasiadas solicitudes" in json.loads(resp.body)["error"]


def test_limit_is_per_user_not_shared(memory_db, monkeypatch):
    """Dos usuarios distintos (mismo endpoint, misma IP) no comparten cupo:
    la clave es user_id, no _client_ip -- varios admins del mismo servidor,
    o simplemente detrás del mismo NAT, no deben pisarse el límite."""
    for user_id in ("111", "222"):
        monkeypatch.setattr(webapi, "get_session", _session_for(user_id))
        for _ in range(60):
            resp = _run(webapi._api_corpus_delete, FakeRequest())
            assert resp.status == 200


def test_reads_are_not_rate_limited(memory_db, monkeypatch):
    """GET no pasa por este límite: son lecturas baratas ya protegidas por
    sesión + permiso de guild, y varias se disparan juntas al cargar el
    dashboard -- limitarlas rompería el uso normal sin agregar protección
    real."""
    monkeypatch.setattr(webapi, "get_session", _session_for("111"))

    for _ in range(100):
        resp = _run(webapi._api_corpus_get, FakeRequest(method="GET"))
        assert resp.status == 200
