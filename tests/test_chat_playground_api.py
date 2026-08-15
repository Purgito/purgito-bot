"""Tests del endpoint del playground (Fase 7):
POST /api/server/{guild_id}/chat/playground.

simulate_message en sí ya se prueba en test_chat_playground.py -- acá solo
la parte de webapi.py: validación del body, resolución del canal y del
autor (Member real si se puede, placeholder si no), y que el resultado de
simulate_message se devuelve tal cual.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import webapi

_GUILD = 123
_USER_ID = "999888777"
_USERNAME = "Frambuesa"


class FakeGuild:
    def __init__(self, channels=None, members=None):
        self._channels = channels or {}
        self._members = members or {}

    def get_channel(self, channel_id):
        return self._channels.get(channel_id)

    def get_member(self, user_id):
        return self._members.get(user_id)


class FakeRequest:
    def __init__(self, guild_id=_GUILD, body=None):
        self._body = body
        self.match_info = {"guild_id": str(guild_id)}
        self.headers = {}
        self.remote = "1.2.3.4"

    async def json(self):
        if self._body is None:
            raise ValueError("sin body")
        return self._body


@pytest.fixture
def fake_guild(monkeypatch):
    guild = FakeGuild(channels={10: SimpleNamespace(id=10, name="general")})

    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": _USERNAME}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: guild)
    monkeypatch.setattr(webapi, "_rate_playground", webapi.LRUDict(64))
    return guild


def _run(request):
    return asyncio.run(webapi._api_chat_playground_post(request))


def _json(resp):
    return json.loads(resp.body)


def test_body_invalido_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body=None))
    assert resp.status == 400


def test_mensaje_vacio_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body={"message": "   ", "channel_id": "10"}))
    assert resp.status == 400


def test_channel_id_invalido_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "no-es-un-id"}))
    assert resp.status == 400


def test_canal_inexistente_en_el_guild_devuelve_400(fake_guild):
    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "999"}))
    assert resp.status == 400


def test_devuelve_el_resultado_de_simulate_message_tal_cual(fake_guild, monkeypatch):
    captured = {}

    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        captured.update(
            guild_id=guild_id,
            channel_id=channel_id,
            content=content,
            author=author,
            channel=channel,
            guild=guild,
        )
        return {"would_respond": True, "reason": "markov", "text": "hola"}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    resp = _run(FakeRequest(body={"message": "hola bot", "channel_id": "10"}))

    assert resp.status == 200
    assert _json(resp) == {"would_respond": True, "reason": "markov", "text": "hola"}
    assert captured["guild_id"] == _GUILD
    assert captured["channel_id"] == 10
    assert captured["content"] == "hola bot"
    assert captured["channel"] is fake_guild._channels[10]
    assert captured["guild"] is fake_guild


def test_usa_el_member_real_como_autor_si_esta_en_cache(fake_guild, monkeypatch):
    member = SimpleNamespace(mention=f"<@{_USER_ID}>", display_name="Frambuesa real")
    fake_guild._members[int(_USER_ID)] = member

    captured = {}

    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        captured["author"] = author
        return {"would_respond": False, "reason": "sin_corpus_suficiente", "text": None}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))

    assert captured["author"] is member


def test_respeta_el_rate_limit(fake_guild, monkeypatch):
    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        return {"would_respond": False, "reason": "sin_corpus_suficiente", "text": None}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    for _ in range(20):
        resp = _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))
        assert resp.status == 200

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))
    assert resp.status == 429


def test_usa_un_placeholder_si_no_hay_member_en_cache(fake_guild, monkeypatch):
    captured = {}

    async def fake_simulate(guild_id, channel_id, content, *, author, channel, guild):
        captured["author"] = author
        return {"would_respond": False, "reason": "sin_corpus_suficiente", "text": None}

    monkeypatch.setattr(webapi, "simulate_message", fake_simulate)

    _run(FakeRequest(body={"message": "hola", "channel_id": "10"}))

    author = captured["author"]
    assert author.mention == f"<@{_USER_ID}>"
    assert author.display_name == _USERNAME


def test_canal_sin_permisos_devuelve_403(fake_guild):
    # Canal con permissions_for simulado donde send_messages es False
    no_perms_channel = SimpleNamespace(
        id=20,
        name="solo-lectura",
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True, send_messages=False, read_message_history=True
        ),
    )
    fake_guild._channels[20] = no_perms_channel
    fake_guild.me = SimpleNamespace(id=111)

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "20"}))
    assert resp.status == 403
    data = _json(resp)
    assert "enviar mensajes" in data["error"]


def test_canal_sin_permiso_ver_canal_devuelve_403(fake_guild):
    no_view_channel = SimpleNamespace(
        id=21,
        name="privado",
        permissions_for=lambda me: SimpleNamespace(
            view_channel=False, send_messages=True, read_message_history=True
        ),
    )
    fake_guild._channels[21] = no_view_channel
    fake_guild.me = SimpleNamespace(id=111)

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "21"}))
    assert resp.status == 403
    data = _json(resp)
    assert "ver este canal" in data["error"]


def test_canal_ignorado_en_purgito_devuelve_403(fake_guild, monkeypatch):
    ignored_channel = SimpleNamespace(
        id=22,
        name="canal-silenciado",
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    )
    fake_guild._channels[22] = ignored_channel
    fake_guild.me = SimpleNamespace(id=111)

    async def fake_is_ignored(guild_id, channel_id):
        return channel_id == 22

    monkeypatch.setattr(webapi, "is_channel_ignored", fake_is_ignored)

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "22"}))
    assert resp.status == 403
    data = _json(resp)
    assert "silenciado (ignorado)" in data["error"]


def test_api_channels_marca_elegibilidad_de_simulador(fake_guild, monkeypatch):
    c1 = SimpleNamespace(
        id=1,
        name="valido",
        category=None,
        position=1,
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    )
    c2 = SimpleNamespace(
        id=2,
        name="sin-envio",
        category=None,
        position=2,
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True, send_messages=False, read_message_history=True
        ),
    )
    c3 = SimpleNamespace(
        id=3,
        name="ignorado",
        category=None,
        position=3,
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    )
    fake_guild.text_channels = [c1, c2, c3]
    fake_guild.me = SimpleNamespace(id=111)

    async def fake_list_ignored(guild_id):
        return [3]

    monkeypatch.setattr(webapi, "list_ignored_channels", fake_list_ignored)

    req = FakeRequest()
    req.query = {}
    resp = asyncio.run(webapi._api_channels(req))
    assert resp.status == 200
    data = _json(resp)
    channels = data["channels"]
    assert len(channels) == 3
    assert channels[0]["id"] == "1" and channels[0]["can_use_simulator"] is True
    assert channels[1]["id"] == "2" and channels[1]["can_use_simulator"] is False
    assert channels[2]["id"] == "3" and channels[2]["can_use_simulator"] is False

    # Con ?for=simulator
    req.query = {"for": "simulator"}
    resp_sim = asyncio.run(webapi._api_channels(req))
    data_sim = _json(resp_sim)
    sim_channels = data_sim["channels"]
    assert len(sim_channels) == 1
    assert sim_channels[0]["id"] == "1"


def test_canal_sin_historial_devuelve_403(fake_guild):
    no_history_channel = SimpleNamespace(
        id=23,
        name="sin-historial",
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=False
        ),
    )
    fake_guild._channels[23] = no_history_channel
    fake_guild.me = SimpleNamespace(id=111)

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "23"}))
    assert resp.status == 403
    data = _json(resp)
    assert "leer el historial" in data["error"]


def test_hilo_sin_permiso_enviar_hilos_devuelve_403(fake_guild):
    thread_channel = SimpleNamespace(
        id=24,
        name="hilo-solo-lectura",
        parent=SimpleNamespace(id=10),
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            send_messages_in_threads=False,
        ),
    )
    fake_guild._channels[24] = thread_channel
    fake_guild.me = SimpleNamespace(id=111)

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "24"}))
    assert resp.status == 403
    data = _json(resp)
    assert "enviar mensajes en este hilo" in data["error"]


def test_hilo_bloqueado_devuelve_403(fake_guild):
    locked_thread = SimpleNamespace(
        id=25,
        name="hilo-bloqueado",
        parent=SimpleNamespace(id=10),
        locked=True,
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            send_messages_in_threads=True,
        ),
    )
    fake_guild._channels[25] = locked_thread
    fake_guild.me = SimpleNamespace(id=111)

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "25"}))
    assert resp.status == 403
    data = _json(resp)
    assert "bloqueado" in data["error"]


def test_bot_sin_miembro_en_guild_devuelve_403(fake_guild):
    channel = SimpleNamespace(
        id=26,
        name="canal-cualquiera",
        permissions_for=lambda me: SimpleNamespace(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    )
    fake_guild._channels[26] = channel
    fake_guild.me = None

    resp = _run(FakeRequest(body={"message": "hola", "channel_id": "26"}))
    assert resp.status == 403
    data = _json(resp)
    assert "no se pudo verificar los permisos" in data["error"]


def test_revocacion_dinamica_de_permisos(fake_guild, monkeypatch):
    """Si el canal era válido al listar pero se revocan permisos antes de simular,
    el endpoint POST /chat/playground debe rechazar con 403."""
    class DynamicChannel:
        def __init__(self, id, name):
            self.id = id
            self.name = name
            self.can_send = True

        def permissions_for(self, me):
            return SimpleNamespace(
                view_channel=True,
                send_messages=self.can_send,
                read_message_history=True,
            )

    dyn_channel = DynamicChannel(30, "dinamico")
    fake_guild._channels[30] = dyn_channel
    fake_guild.text_channels = [dyn_channel]
    fake_guild.me = SimpleNamespace(id=111)

    async def fake_empty_ignored(guild_id):
        return []

    monkeypatch.setattr(webapi, "list_ignored_channels", fake_empty_ignored)

    # 1. Al cargar la lista con ?for=simulator, el canal aparece
    req = FakeRequest()
    req.query = {"for": "simulator"}
    resp = asyncio.run(webapi._api_channels(req))
    data = _json(resp)
    assert len(data["channels"]) == 1
    assert data["channels"][0]["id"] == "30"

    # 2. Se revocan los permisos de enviar mensajes en Discord
    dyn_channel.can_send = False

    # 3. La simulación POST sobre ese canal debe fallar con 403 inmediatamente
    resp_post = _run(FakeRequest(body={"message": "hola", "channel_id": "30"}))
    assert resp_post.status == 403
    assert "enviar mensajes" in _json(resp_post)["error"]

    # 4. Al volver a consultar canales, ya no aparece
    resp_reloaded = asyncio.run(webapi._api_channels(req))
    data_reloaded = _json(resp_reloaded)
    assert len(data_reloaded["channels"]) == 0

    # 5. Se restauran permisos en Discord
    dyn_channel.can_send = True
    resp_restored = asyncio.run(webapi._api_channels(req))
    data_restored = _json(resp_restored)
    assert len(data_restored["channels"]) == 1
    assert data_restored["channels"][0]["id"] == "30"

