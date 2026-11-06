"""API del Centro de Privacidad: solo actúa sobre la persona autenticada."""

import asyncio
import json

import pytest

import db
import privacy_requests as pr
import webapi


@pytest.fixture
def memory_db():
    asyncio.run(db.init_db())

    async def _clean():
        conn = await db.get_db()
        async with db._db_lock:
            for t in ("privacy_requests", "privacy_request_log", "excluded_users",
                      "user_corpus", "corpus_messages", "gif_senders", "privacy_rights_requests"):
                await conn.execute(f"DELETE FROM {t}")
            await conn.commit()

    asyncio.run(_clean())
    yield
    asyncio.run(_clean())
    asyncio.run(db.close_db())


class _Bot:
    def get_guild(self, gid):
        return None


class _Req:
    def __init__(self, body=None):
        self.app = {"bot": _Bot()}
        self._body = body
        self.headers = {}
        self.remote = "1.2.3.4"
        self.query = {}

    async def json(self):
        return self._body


def _as(monkeypatch, user_id):
    async def fake(request):
        return {"user_id": user_id} if user_id is not None else {}

    monkeypatch.setattr(webapi, "get_session", fake)


def _body(resp):
    return json.loads(resp.body)


@pytest.mark.parametrize(
    "handler",
    [
        webapi._api_me_privacy_get,
        webapi._api_me_privacy_exclusion_put,
        webapi._api_me_privacy_requests_post,
        webapi._api_me_privacy_export_get,
        webapi._api_me_privacy_rights_post,
    ],
)
def test_sin_sesion_responde_401(memory_db, monkeypatch, handler):
    _as(monkeypatch, None)
    assert asyncio.run(handler(_Req({"enabled": True}))).status == 401


def test_la_exclusion_global_se_activa_y_se_quita(memory_db, monkeypatch):
    _as(monkeypatch, "4242")
    resp = asyncio.run(webapi._api_me_privacy_exclusion_put(_Req({"enabled": True})))
    assert resp.status == 200 and _body(resp)["exclusion"]["enabled"] is True
    assert asyncio.run(db.is_user_excluded_from_learning(999, 4242))  # en cualquier servidor
    assert not asyncio.run(db.is_user_excluded_from_learning(999, 4243))  # y solo ella
    resp = asyncio.run(webapi._api_me_privacy_exclusion_put(_Req({"enabled": False})))
    assert _body(resp)["exclusion"]["enabled"] is False
    assert not asyncio.run(db.is_user_excluded_from_learning(999, 4242))


@pytest.mark.parametrize("body", [None, {}, {"enabled": "true"}, {"enabled": 1}])
def test_la_exclusion_exige_un_booleano(memory_db, monkeypatch, body):
    _as(monkeypatch, "4242")
    assert asyncio.run(webapi._api_me_privacy_exclusion_put(_Req(body))).status == 400


def test_no_se_puede_actuar_sobre_otra_persona(memory_db, monkeypatch):
    _as(monkeypatch, "100")
    asyncio.run(webapi._api_me_privacy_exclusion_put(_Req({"enabled": True, "user_id": 200})))
    resp = asyncio.run(webapi._api_me_privacy_requests_post(_Req({"user_id": 200})))
    assert asyncio.run(pr.user_requests(200)) == []
    assert len(asyncio.run(pr.user_requests(100))) == 1 and resp.status == 201
    assert not asyncio.run(db.is_user_excluded_from_learning(1, 200))


def test_solicitar_dos_veces_devuelve_la_misma(memory_db, monkeypatch):
    _as(monkeypatch, "7")
    first = asyncio.run(webapi._api_me_privacy_requests_post(_Req()))
    second = asyncio.run(webapi._api_me_privacy_requests_post(_Req()))
    assert first.status == 201 and second.status == 200
    assert _body(first)["request"]["id"] == _body(second)["request"]["id"]
    state = _body(asyncio.run(webapi._api_me_privacy_get(_Req())))
    assert len(state["requests"]) == 1 and state["deadline_days"] == 7


def test_la_exportacion_incluye_todo_y_es_descargable(memory_db, monkeypatch):
    async def seed():
        await db.save_corpus_and_user_message(10, 1, 7, "n", "mensaje de estilo", message_id=1)
        conn = await db.get_db()
        async with db._db_lock:
            await conn.execute("INSERT INTO gif_senders (gif_id, guild_id, user_id) VALUES (3, 10, 7)")
            await conn.commit()

    asyncio.run(seed())
    _as(monkeypatch, "7")
    resp = asyncio.run(webapi._api_me_privacy_export_get(_Req()))
    assert "attachment" in resp.headers["Content-Disposition"]
    data = json.loads(resp.text)
    assert data["user_id"] == "7"
    assert len(data["servers"][0]["messages"]) == 1 and len(data["gifs"]) == 1
    assert {"boosts", "special_phrases", "exclusions", "deletion_requests"} <= data.keys()


def test_otras_solicitudes_de_derechos_usan_solo_la_identidad_de_la_sesion(memory_db, monkeypatch):
    import privacy_rights

    _as(monkeypatch, "100")
    resp = asyncio.run(
        webapi._api_me_privacy_rights_post(_Req({"right": "access", "note": "hola", "user_id": 200}))
    )
    assert resp.status == 201 and _body(resp)["request"]["right"] == "access"
    assert asyncio.run(privacy_rights.user_requests(200)) == []  # un user_id enviado se ignora
    assert len(asyncio.run(privacy_rights.user_requests(100))) == 1
    state = _body(asyncio.run(webapi._api_me_privacy_get(_Req())))
    assert len(state["rights"]) == 1 and state["rights_deadline_days"] == 30
    _as(monkeypatch, "200")
    assert _body(asyncio.run(webapi._api_me_privacy_get(_Req())))["rights"] == []  # y no la ve otra persona


@pytest.mark.parametrize(
    "body",
    [None, {}, {"right": "borrar_todo"}, {"right": 5}, {"right": "access", "note": 5}, {"right": "access", "note": "x" * 2000}],
)
def test_derechos_rechaza_entradas_invalidas(memory_db, monkeypatch, body):
    _as(monkeypatch, "100")
    assert asyncio.run(webapi._api_me_privacy_rights_post(_Req(body))).status == 400
