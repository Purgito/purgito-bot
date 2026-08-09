"""Tests de los endpoints nuevos de la Fase 3: canales permitidos para
frases especiales y packs (/api/server/{guild_id}/settings/frases/... y
/api/server/{guild_id}/frases/packs/...).

Mismo patrón que test_channel_settings_api.py / test_audit_log.py: handlers
llamados directo, DB de archivo real (init_db completo -- necesaria por las
columnas que salen de ALTER TABLE, ver test_chat_config.py), get_session/
check_guild_access/_bot_guild parcheados para que guild_api deje pasar.
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
    def __init__(self, guild_id=_GUILD, body=None, match_info=None, query=None):
        self._body = body
        self.match_info = {"guild_id": str(guild_id), **(match_info or {})}
        self.query = query or {}

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


# ── Canales permitidos para frases ───────────────────────────────────────────


def test_get_frase_channels_vacio_por_default(memory_db):
    resp = _run(webapi._api_frase_channels_get, FakeRequest())
    assert _json(resp)["channels"] == []


def test_post_agrega_un_canal(memory_db):
    resp = _run(webapi._api_frase_channels_post, FakeRequest(body={"channel_id": "10"}))
    assert _json(resp)["added"] is True
    assert asyncio.run(db.list_frase_channels(_GUILD)) == [10]


def test_delete_quita_un_canal(memory_db):
    _run(webapi._api_frase_channels_post, FakeRequest(body={"channel_id": "10"}))
    resp = _run(
        webapi._api_frase_channels_delete, FakeRequest(match_info={"channel_id": "10"})
    )
    assert _json(resp)["removed"] is True
    assert asyncio.run(db.list_frase_channels(_GUILD)) == []


# ── Frases: pack_id, límite, patch ───────────────────────────────────────────


def test_post_frase_acepta_pack_id_opcional(memory_db):
    pack_id = asyncio.run(db.add_frase_pack(_GUILD, "Navidad"))

    resp = _run(
        webapi._api_frases_post,
        FakeRequest(body={"frase": "feliz navidad", "pack_id": pack_id}),
    )

    assert _json(resp)["added"] is True
    frases = asyncio.run(db.list_frases_especiales(_GUILD))
    assert frases[0]["pack_id"] == pack_id


def test_get_frases_expone_pack_id_y_limite(memory_db):
    asyncio.run(db.add_frase_especial(_GUILD, 1, "u", "hola"))

    resp = _run(webapi._api_frases_get, FakeRequest())

    body = _json(resp)
    assert body["frases"][0]["pack_id"] is None
    assert body["limit"] == db.frases_limit(_GUILD)


def test_post_frase_en_el_limite_devuelve_409(memory_db, monkeypatch):
    monkeypatch.setenv("MAX_FRASES_PER_GUILD_FREE", "1")
    _run(webapi._api_frases_post, FakeRequest(body={"frase": "una"}))

    resp = _run(webapi._api_frases_post, FakeRequest(body={"frase": "dos"}))

    assert resp.status == 409


def test_patch_reasigna_el_pack_de_una_frase(memory_db):
    asyncio.run(db.add_frase_especial(_GUILD, 1, "u", "hola"))
    frase_id = asyncio.run(db.list_frases_especiales(_GUILD))[0]["id"]
    pack_id = asyncio.run(db.add_frase_pack(_GUILD, "Navidad"))

    resp = _run(
        webapi._api_frases_patch,
        FakeRequest(match_info={"frase_id": str(frase_id)}, body={"pack_id": pack_id}),
    )

    assert _json(resp)["updated"] is True
    frase = asyncio.run(db.get_frase_especial(_GUILD, frase_id))
    assert frase["pack_id"] == pack_id


def test_patch_con_pack_id_null_quita_el_pack(memory_db):
    pack_id = asyncio.run(db.add_frase_pack(_GUILD, "Navidad"))
    asyncio.run(db.add_frase_especial(_GUILD, 1, "u", "hola", pack_id=pack_id))
    frase_id = asyncio.run(db.list_frases_especiales(_GUILD))[0]["id"]

    resp = _run(
        webapi._api_frases_patch,
        FakeRequest(match_info={"frase_id": str(frase_id)}, body={"pack_id": None}),
    )

    assert _json(resp)["updated"] is True
    frase = asyncio.run(db.get_frase_especial(_GUILD, frase_id))
    assert frase["pack_id"] is None


def test_patch_sin_pack_id_en_el_body_devuelve_400(memory_db):
    resp = _run(
        webapi._api_frases_patch,
        FakeRequest(match_info={"frase_id": "1"}, body={}),
    )
    assert resp.status == 400


def test_patch_no_puede_asignar_un_pack_de_otro_guild(memory_db):
    """Sección 6, ronda 1: pack_id es un autoincrement global -- sin la
    validación de guild, un admin podía apuntar su propia frase al pack_id
    de OTRO servidor (adivinable/enumerable por ser secuencial)."""
    otro_guild = _GUILD + 1
    ajeno = asyncio.run(db.add_frase_pack(otro_guild, "Pack ajeno"))
    asyncio.run(db.add_frase_especial(_GUILD, 1, "u", "hola"))
    frase_id = asyncio.run(db.list_frases_especiales(_GUILD))[0]["id"]

    resp = _run(
        webapi._api_frases_patch,
        FakeRequest(match_info={"frase_id": str(frase_id)}, body={"pack_id": ajeno}),
    )

    assert _json(resp)["updated"] is False
    frase = asyncio.run(db.get_frase_especial(_GUILD, frase_id))
    assert frase["pack_id"] is None  # no quedó apuntando al pack ajeno


# ── Packs: CRUD ───────────────────────────────────────────────────────────────


def test_post_pack_crea_y_get_lo_lista(memory_db):
    post = _run(webapi._api_frase_packs_post, FakeRequest(body={"name": "Navidad"}))
    assert post.status == 200
    pack_id = _json(post)["id"]

    get = _run(webapi._api_frase_packs_get, FakeRequest())
    body = _json(get)
    assert body["total"] == 1
    assert body["packs"][0]["id"] == pack_id
    assert body["limit"] == db.frase_pack_limit(_GUILD)


def test_post_pack_sin_nombre_devuelve_400(memory_db):
    resp = _run(webapi._api_frase_packs_post, FakeRequest(body={"name": "  "}))
    assert resp.status == 400


def test_post_pack_duplicado_devuelve_409(memory_db):
    _run(webapi._api_frase_packs_post, FakeRequest(body={"name": "Navidad"}))
    resp = _run(webapi._api_frase_packs_post, FakeRequest(body={"name": "Navidad"}))
    assert resp.status == 409


def test_delete_pack_lo_borra(memory_db):
    pack_id = asyncio.run(db.add_frase_pack(_GUILD, "Navidad"))

    resp = _run(
        webapi._api_frase_packs_delete,
        FakeRequest(match_info={"pack_id": str(pack_id)}),
    )

    assert _json(resp)["deleted"] is True
    assert asyncio.run(db.list_frase_packs(_GUILD)) == []


# ── Asignación de pack a canal ───────────────────────────────────────────────


def test_asignar_y_listar_canales_de_un_pack(memory_db):
    pack_id = asyncio.run(db.add_frase_pack(_GUILD, "Navidad"))

    post = _run(
        webapi._api_frase_pack_channels_post,
        FakeRequest(match_info={"pack_id": str(pack_id)}, body={"channel_id": "10"}),
    )
    assert post.status == 200

    get = _run(
        webapi._api_frase_pack_channels_get,
        FakeRequest(match_info={"pack_id": str(pack_id)}),
    )
    channels = _json(get)["channels"]
    assert len(channels) == 1
    assert channels[0]["id"] == "10"


def test_asignar_canal_a_un_pack_de_otro_guild_devuelve_404(memory_db):
    otro_guild = _GUILD + 1
    ajeno = asyncio.run(db.add_frase_pack(otro_guild, "Pack ajeno"))

    resp = _run(
        webapi._api_frase_pack_channels_post,
        FakeRequest(match_info={"pack_id": str(ajeno)}, body={"channel_id": "10"}),
    )

    assert resp.status == 404
    assert asyncio.run(db.get_effective_frase_pool(_GUILD, 10)) is None


def test_desasignar_un_canal_de_un_pack(memory_db):
    pack_id = asyncio.run(db.add_frase_pack(_GUILD, "Navidad"))
    asyncio.run(db.assign_pack_to_channel(_GUILD, 10, pack_id))

    resp = _run(
        webapi._api_frase_pack_channels_delete,
        FakeRequest(match_info={"pack_id": str(pack_id), "channel_id": "10"}),
    )

    assert _json(resp)["removed"] is True
    assert asyncio.run(db.get_effective_frase_pool(_GUILD, 10)) is None


def test_desasignar_con_pack_id_equivocado_no_afecta_nada(memory_db):
    a = asyncio.run(db.add_frase_pack(_GUILD, "A"))
    b = asyncio.run(db.add_frase_pack(_GUILD, "B"))
    asyncio.run(db.assign_pack_to_channel(_GUILD, 10, b))

    resp = _run(
        webapi._api_frase_pack_channels_delete,
        FakeRequest(match_info={"pack_id": str(a), "channel_id": "10"}),
    )

    assert _json(resp)["removed"] is False
    assert asyncio.run(db.get_effective_frase_pool(_GUILD, 10)) == b


# ── Audit log ─────────────────────────────────────────────────────────────────


def test_crear_pack_queda_en_el_audit_log(memory_db):
    _run(webapi._api_frase_packs_post, FakeRequest(body={"name": "Navidad"}))

    entries = asyncio.run(db.list_audit_log(_GUILD))
    assert len(entries) == 1
    assert entries[0]["action"] == "frase_packs.create"
    assert entries[0]["user_id"] == int(_USER_ID)
