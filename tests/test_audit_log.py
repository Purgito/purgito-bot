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


@pytest.fixture
def real_db(tmp_path, monkeypatch):
    """DB de archivo real por test (no memoria + SCHEMA a mano): las columnas
    de CHAT_TUNABLES y manager_role_id salen de ALTER TABLE en init_db(), no
    del CREATE TABLE base de db.SCHEMA -- mismo patrón que memory_db en
    test_channel_settings_api.py, necesario para las acciones que leen esas
    columnas antes de guardar (chat_tunables.update, channel_settings.update,
    manager_role.set)."""
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def _fake_role(role_id, name, managed=False):
    return SimpleNamespace(id=role_id, name=name, managed=managed)


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


# ── previous_detail (diff antes/después, solo para ajustes de un único valor) ──


def test_prefix_set_registra_el_valor_anterior(memory_db):
    """La Guía prometía un diff antes/después para todo el Historial; nunca se
    había implementado en ningún punto del pipeline. Acá se cablea para
    ajustes de un único valor -- prefijo, rol de Gestor, tunables de chat,
    overrides por canal, estilo, canal de novedades."""
    _run(webapi._api_prefix_put, FakeRequest(body={"prefix": "?"}))
    _run(webapi._api_prefix_put, FakeRequest(body={"prefix": "$"}))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 2
    # más reciente primero
    assert entries[0]["action"] == "prefix.set"
    assert entries[0]["detail"] == "$"
    assert entries[0]["previous_detail"] == "?"
    assert entries[1]["detail"] == "?"
    assert entries[1]["previous_detail"] == db.DEFAULT_COMMAND_PREFIX


def test_prefix_reset_registra_el_prefijo_personalizado_anterior(memory_db):
    _run(webapi._api_prefix_put, FakeRequest(body={"prefix": "?"}))
    _run(webapi._api_prefix_put, FakeRequest(body={"prefix": ""}))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert entries[0]["action"] == "prefix.reset"
    assert entries[0]["previous_detail"] == "?"


def test_chat_tunables_update_registra_solo_los_valores_previos_de_lo_guardado(real_db):
    _run(
        webapi._api_chat_tunables_put,
        FakeRequest(body={"auto_generate_every": 10}),
    )
    _run(
        webapi._api_chat_tunables_put,
        FakeRequest(body={"auto_generate_every": 20, "mention_rate_limit": 5}),
    )

    entries = asyncio.run(db.list_audit_log(_GUILD))
    first_saved = json.loads(entries[1]["detail"])
    first_previous = json.loads(entries[1]["previous_detail"])
    assert first_saved == {"auto_generate_every": 10}
    # Antes de la primera llamada el guild no tenía fila en settings -- el
    # valor previo tiene que ser el default, no None ni un KeyError.
    assert first_previous["auto_generate_every"] == db.DEFAULT_AUTO_GENERATE_EVERY

    second_saved = json.loads(entries[0]["detail"])
    second_previous = json.loads(entries[0]["previous_detail"])
    assert second_saved == {"auto_generate_every": 20, "mention_rate_limit": 5}
    # El valor previo de auto_generate_every en la 2da llamada es el que
    # quedó guardado por la 1ra (10), no el default original.
    assert second_previous["auto_generate_every"] == 10


def test_channel_settings_update_registra_solo_los_valores_previos_de_lo_guardado(
    real_db,
):
    channel_id = 555
    _run(
        webapi._api_channel_settings_put,
        FakeRequest(
            match_info={"channel_id": str(channel_id)},
            body={"auto_generate_every": 15},
        ),
    )
    _run(
        webapi._api_channel_settings_put,
        FakeRequest(
            match_info={"channel_id": str(channel_id)},
            body={"auto_generate_every": 25},
        ),
    )

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert entries[0]["action"] == "channel_settings.update"
    assert f"channel_id={channel_id}" in entries[0]["detail"]
    # Sin override previo el valor anterior es None (hereda el default del
    # servidor) -- no hay fila en channel_settings todavía en la 1ra llamada.
    assert json.loads(entries[1]["previous_detail"].split(" ", 1)[1]) == {
        "auto_generate_every": None
    }
    assert json.loads(entries[0]["previous_detail"].split(" ", 1)[1]) == {
        "auto_generate_every": 15
    }


def test_manager_role_set_registra_el_valor_anterior(real_db, monkeypatch):
    moderador = _fake_role(1, "Moderador")
    ayudante = _fake_role(2, "Ayudante")
    guild = SimpleNamespace(
        id=_GUILD, get_role=lambda rid: {1: moderador, 2: ayudante}.get(rid)
    )
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: guild)

    _run(webapi._api_manager_role_put, FakeRequest(body={"role_id": "1"}))
    _run(webapi._api_manager_role_put, FakeRequest(body={"role_id": "2"}))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert entries[0]["action"] == "manager_role.set"
    assert entries[0]["detail"] == "Ayudante"
    assert entries[0]["previous_detail"] == "Moderador"
    assert entries[1]["detail"] == "Moderador"
    assert entries[1]["previous_detail"] == "ninguno"


def test_manager_role_clear_registra_el_rol_anterior(real_db, monkeypatch):
    moderador = _fake_role(1, "Moderador")
    guild = SimpleNamespace(id=_GUILD, get_role=lambda rid: {1: moderador}.get(rid))
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: guild)

    _run(webapi._api_manager_role_put, FakeRequest(body={"role_id": "1"}))
    _run(webapi._api_manager_role_put, FakeRequest(body={"role_id": None}))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert entries[0]["action"] == "manager_role.clear"
    assert entries[0]["previous_detail"] == "Moderador"


def test_style_update_registra_el_nick_anterior(memory_db, monkeypatch):
    me = SimpleNamespace(nick=None, edit=AsyncMock())
    guild = SimpleNamespace(me=me)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: guild)

    _run(webapi._api_style_put, FakeRequest(body={"nick": "Purgito"}))
    me.nick = "Purgito"
    _run(webapi._api_style_put, FakeRequest(body={"nick": "Purgo"}))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert entries[0]["action"] == "style.update"
    assert entries[0]["previous_detail"] == "nick='Purgito'"
    assert entries[1]["previous_detail"] == "nick=None"


def test_updates_channel_set_registra_el_canal_anterior(memory_db, monkeypatch):
    canal_avisos = SimpleNamespace(
        id=10,
        name="avisos",
        parent=None,
        send=AsyncMock(),
        permissions_for=lambda member: SimpleNamespace(
            view_channel=True, send_messages=True
        ),
    )
    guild = SimpleNamespace(
        me=SimpleNamespace(),
        get_channel=lambda cid: canal_avisos if cid == 10 else None,
    )
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: guild)

    _run(webapi._api_updates_put, FakeRequest(body={"channel_id": "10"}))
    _run(webapi._api_updates_put, FakeRequest(body={"channel_id": None}))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert entries[0]["action"] == "updates_channel.set"
    assert entries[0]["detail"] == "channel_id=None (desvinculado)"
    assert entries[0]["previous_detail"] == "channel_id=10 channel_name=avisos"
    assert entries[1]["previous_detail"] == "channel_id=None (desvinculado)"


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
