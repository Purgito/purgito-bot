"""audit_log es la única tabla que dice quién tocó qué desde el dashboard,
salvo frases_especiales (que ya guardaba user_id/user_name antes de esto).
Mismo patrón de test que test_youtube_webapi.py: handlers llamados directo,
DB en memoria real (no mocks de db.py), get_session/check_guild_access/
_bot_guild parcheados para que guild_api deje pasar.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

import db
import webapi

_GUILD = 123
_USER_ID = "999888777"
_USERNAME = "Frambuesa"


class FakeRequest:
    def __init__(self, guild_id=_GUILD, body=None, match_info=None, query=None):
        self._body = body
        self.match_info = {"guild_id": str(guild_id), **(match_info or {})}
        self.query = query or {}
        self.headers = {"X-Forwarded-For": "1.2.3.4"}
        self.remote = "1.2.3.4"

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


def _fake_channel(cid):
    # view_channel=True: estos tests ejercitan otra cosa (quién queda
    # registrado en el audit log), no el scoping de canal de la sección 10 --
    # ese tiene su propio archivo (test_channel_scope_authorization.py).
    return SimpleNamespace(
        id=cid, permissions_for=lambda member: SimpleNamespace(view_channel=True)
    )


@pytest.fixture(autouse=True)
def allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": _USERNAME}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(
        webapi,
        "_bot_guild",
        lambda request, guild_id: SimpleNamespace(
            get_channel=_fake_channel,
            fetch_member=AsyncMock(return_value=SimpleNamespace(id=int(_USER_ID))),
        ),
    )


@pytest.fixture(autouse=True)
def fresh_rate_limit_stores(monkeypatch):
    monkeypatch.setattr(webapi, "_rate_post", webapi.LRUDict(64))
    monkeypatch.setattr(webapi, "_rate_delete", webapi.LRUDict(64))


def _run(handler, request):
    return asyncio.run(handler(request))


def _json(resp):
    return json.loads(resp.body)


# ── db.log_audit / db.list_audit_log ─────────────────────────────────────────


def test_log_audit_escribe_una_fila(memory_db):
    asyncio.run(
        db.log_audit(_GUILD, 42, "Alguien", "chat.settings_update", "enabled=True")
    )

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["user_id"] == 42
    assert entries[0]["user_name"] == "Alguien"
    assert entries[0]["action"] == "chat.settings_update"
    assert entries[0]["detail"] == "enabled=True"


def test_list_audit_log_esta_scopeado_al_guild_y_ordena_mas_reciente_primero(memory_db):
    asyncio.run(db.log_audit(_GUILD, 1, "A", "corpus.add", "channel_id=1"))
    asyncio.run(db.log_audit(999, 1, "A", "corpus.add", "channel_id=2"))  # otro guild
    asyncio.run(db.log_audit(_GUILD, 1, "A", "corpus.remove", "channel_id=1"))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert [e["action"] for e in entries] == ["corpus.remove", "corpus.add"]


def test_list_audit_log_respeta_limit_y_offset(memory_db):
    for i in range(5):
        asyncio.run(db.log_audit(_GUILD, 1, "A", "gifs.add", f"url-{i}"))

    page = asyncio.run(db.list_audit_log(_GUILD, limit=2, offset=1))
    assert len(page) == 2
    # El más nuevo es url-4 (id más alto); offset=1 lo salta.
    assert page[0]["detail"] == "url-3"
    assert page[1]["detail"] == "url-2"


# ── db.list_audit_log_page (cursor, tab HISTORIAL) ────────────────────────────


def test_list_audit_log_page_primera_pagina_sin_cursor(memory_db):
    for i in range(6):
        asyncio.run(db.log_audit(_GUILD, 1, "A", "gifs.add", f"url-{i}"))

    entries, has_more = asyncio.run(db.list_audit_log_page(_GUILD, limit=5))

    assert [e["detail"] for e in entries] == [
        "url-5",
        "url-4",
        "url-3",
        "url-2",
        "url-1",
    ]
    assert has_more is True


def test_list_audit_log_page_con_cursor_trae_la_siguiente_tanda(memory_db):
    for i in range(6):
        asyncio.run(db.log_audit(_GUILD, 1, "A", "gifs.add", f"url-{i}"))
    primera, _ = asyncio.run(db.list_audit_log_page(_GUILD, limit=5))
    ultimo_id_visto = primera[-1]["id"]

    entries, has_more = asyncio.run(
        db.list_audit_log_page(_GUILD, before_id=ultimo_id_visto, limit=5)
    )

    assert [e["detail"] for e in entries] == ["url-0"]
    assert has_more is False


def test_list_audit_log_page_cursor_en_el_limite_exacto(memory_db):
    """Quedan exactamente `limit` filas viejas: la página se llena justo y
    no debe sobrar una fila fantasma que dispare has_more."""
    for i in range(10):
        asyncio.run(db.log_audit(_GUILD, 1, "A", "gifs.add", f"url-{i}"))
    primera, _ = asyncio.run(db.list_audit_log_page(_GUILD, limit=5))
    ultimo_id_visto = primera[-1]["id"]

    entries, has_more = asyncio.run(
        db.list_audit_log_page(_GUILD, before_id=ultimo_id_visto, limit=5)
    )

    assert len(entries) == 5
    assert has_more is False


def test_list_audit_log_page_cursor_pasado_el_final(memory_db):
    asyncio.run(db.log_audit(_GUILD, 1, "A", "gifs.add", "url-0"))
    entries, _ = asyncio.run(db.list_audit_log_page(_GUILD, limit=5))
    id_mas_viejo = entries[-1]["id"]

    entries, has_more = asyncio.run(
        db.list_audit_log_page(_GUILD, before_id=id_mas_viejo, limit=5)
    )

    assert entries == []
    assert has_more is False


def test_list_audit_log_page_guild_sin_acciones_todavia(memory_db):
    entries, has_more = asyncio.run(db.list_audit_log_page(_GUILD, limit=5))

    assert entries == []
    assert has_more is False


# ── Endpoints de mutación de verdad loguean con el user_id de la sesión ──────


def test_corpus_post_loguea_con_el_user_id_de_la_sesion(memory_db):
    req = FakeRequest(body={"channel_id": "555"})

    resp = _run(webapi._api_corpus_post, req)

    assert _json(resp)["added"] is True
    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["user_id"] == int(_USER_ID)
    assert entries[0]["user_name"] == _USERNAME
    assert entries[0]["action"] == "corpus.add"
    assert "555" in entries[0]["detail"]


def test_corpus_post_no_loguea_si_el_canal_ya_estaba(memory_db):
    req = FakeRequest(body={"channel_id": "555"})
    _run(webapi._api_corpus_post, req)

    resp = _run(webapi._api_corpus_post, FakeRequest(body={"channel_id": "555"}))

    assert _json(resp)["added"] is False
    # Una sola entrada -- la del alta real, no un segundo intento sin efecto.
    assert len(asyncio.run(db.list_audit_log(_GUILD))) == 1


def test_exempt_roles_delete_loguea_al_borrar(memory_db):
    asyncio.run(db.add_exempt_role(_GUILD, 777))

    resp = _run(
        webapi._api_exempt_roles_delete, FakeRequest(match_info={"role_id": "777"})
    )

    assert _json(resp)["removed"] is True
    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["action"] == "exempt_roles.remove"
    assert entries[0]["user_id"] == int(_USER_ID)


def test_embed_template_create_loguea_con_el_nombre(memory_db):
    req = FakeRequest(body={"name": "Bienvenida", "embeds": [{"title": "Hola"}]})

    resp = _run(webapi._api_embed_templates_post, req)

    assert resp.status == 200
    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["action"] == "embed_template.create"
    assert entries[0]["detail"] == "Bienvenida"


# ── Endpoint de lectura ───────────────────────────────────────────────────────


def test_get_audit_log_devuelve_las_entradas_del_guild(memory_db):
    asyncio.run(db.log_audit(_GUILD, 1, "A", "gifs.add", "url-1"))
    asyncio.run(db.log_audit(999, 1, "A", "gifs.add", "url-otro-guild"))

    resp = _run(webapi._api_audit_log_get, FakeRequest())

    assert resp.status == 200
    body = _json(resp)
    assert len(body["entries"]) == 1
    assert body["entries"][0]["detail"] == "url-1"
    assert body["has_more"] is False


def test_get_audit_log_pagina_por_cursor_con_before_id(memory_db):
    for i in range(3):
        asyncio.run(db.log_audit(_GUILD, 1, "A", "gifs.add", f"url-{i}"))
    primera = _run(webapi._api_audit_log_get, FakeRequest(query={"limit": "1"}))
    primer_id = _json(primera)["entries"][0]["id"]

    resp = _run(
        webapi._api_audit_log_get,
        FakeRequest(query={"limit": "1", "before_id": str(primer_id)}),
    )

    body = _json(resp)
    assert len(body["entries"]) == 1
    assert body["entries"][0]["detail"] == "url-1"
    assert body["has_more"] is True


# ── db.purge_old_audit_log_entries (Sección 7) ────────────────────────────────
#
# audit_log.detail puede llevar texto tal cual escrito por un admin (ej.
# "frases.add" guarda la frase completa) -- sin un límite de retención
# propio, borrar esa frase desde /settings no la borraba de verdad, quedaba
# una copia indefinida en el audit log.


def test_purge_old_audit_log_entries_borra_solo_lo_vencido(memory_db):
    async def run():
        conn = await db.get_db()
        await db.log_audit(_GUILD, 1, "A", "frases.add", "una frase vieja y sensible")
        await conn.execute(
            "UPDATE audit_log SET created_at = datetime('now', '-100 days')"
        )
        await conn.commit()
        await db.log_audit(_GUILD, 1, "A", "frases.add", "una frase reciente")

        deleted = await db.purge_old_audit_log_entries(90)
        remaining = await db.list_audit_log(_GUILD)
        return deleted, remaining

    deleted, remaining = asyncio.run(run())
    assert deleted == 1
    assert len(remaining) == 1
    assert remaining[0]["detail"] == "una frase reciente"


def test_purge_old_audit_log_entries_no_toca_nada_dentro_de_la_retencion(memory_db):
    async def run():
        await db.log_audit(_GUILD, 1, "A", "frases.add", "frase de ayer")
        deleted = await db.purge_old_audit_log_entries(90)
        remaining = await db.list_audit_log(_GUILD)
        return deleted, remaining

    deleted, remaining = asyncio.run(run())
    assert deleted == 0
    assert len(remaining) == 1
