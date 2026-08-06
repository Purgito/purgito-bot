"""Tests de los endpoints de triggers (Fase 4):
/api/server/{guild_id}/settings/triggers[/{trigger_id}].

Mismo patrón que test_frase_packs_api.py: handlers llamados directo, DB de
archivo real (init_db completo), get_session/check_guild_access/_bot_guild
parcheados para que guild_api deje pasar.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import db
import webapi

_GUILD = 123
_USER_ID = "999888777"
_USERNAME = "Frambuesa"


class FakeRequest:
    def __init__(self, guild_id=_GUILD, body=None, match_info=None):
        self._body = body
        self.match_info = {"guild_id": str(guild_id), **(match_info or {})}

    async def json(self):
        if self._body is None:
            raise ValueError("sin body")
        return self._body


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


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
        lambda request, guild_id: SimpleNamespace(get_channel=lambda cid: None),
    )


def _run(handler, request):
    return asyncio.run(handler(request))


def _json(resp):
    return json.loads(resp.body)


def _valid_body(**overrides):
    body = {
        "channel_id": "10",
        "match_type": "exact",
        "pattern": "hola",
        "action": "markov",
    }
    body.update(overrides)
    return body


# ── POST ─────────────────────────────────────────────────────────────────────


def test_post_crea_un_trigger(memory_db):
    resp = _run(webapi._api_triggers_post, FakeRequest(body=_valid_body()))

    assert resp.status == 200
    trigger_id = _json(resp)["id"]
    triggers = asyncio.run(db.list_channel_triggers(_GUILD, 10))
    assert triggers[0]["id"] == trigger_id


def test_post_sin_channel_id_devuelve_400(memory_db):
    body = _valid_body()
    del body["channel_id"]
    resp = _run(webapi._api_triggers_post, FakeRequest(body=body))
    assert resp.status == 400


def test_post_match_type_invalido_devuelve_400(memory_db):
    resp = _run(
        webapi._api_triggers_post,
        FakeRequest(body=_valid_body(match_type="lo_que_sea")),
    )
    assert resp.status == 400


def test_post_action_invalida_devuelve_400(memory_db):
    resp = _run(
        webapi._api_triggers_post, FakeRequest(body=_valid_body(action="lo_que_sea"))
    )
    assert resp.status == 400


def test_post_pattern_vacio_devuelve_400(memory_db):
    resp = _run(webapi._api_triggers_post, FakeRequest(body=_valid_body(pattern="  ")))
    assert resp.status == 400


def test_post_regex_invalido_devuelve_400(memory_db):
    resp = _run(
        webapi._api_triggers_post,
        FakeRequest(body=_valid_body(match_type="regex", pattern="(")),
    )
    assert resp.status == 400


def test_post_regex_valido_se_acepta(memory_db):
    resp = _run(
        webapi._api_triggers_post,
        FakeRequest(body=_valid_body(match_type="regex", pattern=r"^hola.*$")),
    )
    assert resp.status == 200


def test_post_con_pack_id(memory_db):
    pack_id = asyncio.run(db.add_frase_pack(_GUILD, "Navidad"))

    resp = _run(
        webapi._api_triggers_post,
        FakeRequest(body=_valid_body(action="frase_de_pack", pack_id=pack_id)),
    )

    assert resp.status == 200
    triggers = asyncio.run(db.list_channel_triggers(_GUILD, 10))
    assert triggers[0]["pack_id"] == pack_id


def test_post_en_el_limite_devuelve_409(memory_db, monkeypatch):
    monkeypatch.setenv("MAX_CHANNEL_TRIGGERS_PER_GUILD_FREE", "1")
    _run(webapi._api_triggers_post, FakeRequest(body=_valid_body(pattern="uno")))

    resp = _run(webapi._api_triggers_post, FakeRequest(body=_valid_body(pattern="dos")))

    assert resp.status == 409


def test_post_loguea_en_el_audit_log(memory_db):
    _run(webapi._api_triggers_post, FakeRequest(body=_valid_body()))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["action"] == "triggers.create"
    assert entries[0]["user_id"] == int(_USER_ID)


# ── GET ──────────────────────────────────────────────────────────────────────


def test_get_lista_los_triggers_del_guild(memory_db):
    asyncio.run(db.add_channel_trigger(_GUILD, 10, "exact", "hola", "markov"))
    asyncio.run(db.add_channel_trigger(_GUILD, 20, "exact", "chau", "markov"))
    asyncio.run(db.add_channel_trigger(999, 10, "exact", "otro guild", "markov"))

    resp = _run(webapi._api_triggers_get, FakeRequest())

    body = _json(resp)
    assert body["total"] == 2
    assert {t["pattern"] for t in body["triggers"]} == {"hola", "chau"}
    assert {t["channel_id"] for t in body["triggers"]} == {"10", "20"}  # como string
    assert body["limit"] == db.channel_triggers_limit(_GUILD)
    assert "exact" in body["match_types"]
    assert "markov" in body["actions"]


# ── DELETE ───────────────────────────────────────────────────────────────────


def test_delete_borra_el_trigger(memory_db):
    trigger_id = asyncio.run(
        db.add_channel_trigger(_GUILD, 10, "exact", "hola", "markov")
    )

    resp = _run(
        webapi._api_triggers_delete,
        FakeRequest(match_info={"trigger_id": str(trigger_id)}),
    )

    assert _json(resp)["deleted"] is True
    assert asyncio.run(db.list_channel_triggers(_GUILD, 10)) == []


def test_delete_trigger_inexistente_devuelve_false(memory_db):
    resp = _run(
        webapi._api_triggers_delete, FakeRequest(match_info={"trigger_id": "999"})
    )
    assert _json(resp)["deleted"] is False
