import asyncio
import json
from unittest.mock import MagicMock

import discord
import pytest

import db
import webapi

_GUILD = 12345
_GUILD_2 = 67890
_CHANNEL_ID = 555
_USER_ID = "999888777"
_USERNAME = "AdminUser"


class FakeRequest:
    def __init__(self, guild_id=_GUILD, announcement_id=None, body=None):
        self._body = body
        self.match_info = {
            "guild_id": str(guild_id),
        }
        if announcement_id is not None:
            self.match_info["announcement_id"] = str(announcement_id)
        self.headers = {"X-Forwarded-For": "1.2.3.4"}
        self.remote = "1.2.3.4"
        self.app = {}

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
def mock_bot_environment(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": _USERNAME}

    async def fake_check_guild_access(request, guild_id):
        return None

    fake_channel = MagicMock(spec=discord.TextChannel)
    fake_channel.id = _CHANNEL_ID
    fake_channel.name = "anuncios"
    fake_channel.permissions_for = MagicMock(
        return_value=MagicMock(send_messages=True, embed_links=True)
    )

    fake_guild = MagicMock(spec=discord.Guild)
    fake_guild.id = _GUILD
    fake_guild.name = "Test Server"
    fake_guild.get_channel = MagicMock(
        side_effect=lambda cid: fake_channel if cid == _CHANNEL_ID else None
    )

    fake_bot = MagicMock()
    fake_bot.get_guild = MagicMock(
        side_effect=lambda gid: fake_guild if gid == _GUILD else None
    )

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: fake_guild)


def test_db_scheduled_announcements_crud_and_quota(memory_db):
    async def _test():
        # Quota inicial
        count, max_limit, is_prem = await db.get_scheduled_announcements_quota(_GUILD)
        assert count == 0
        assert max_limit == 3
        assert not is_prem

        # Crear anuncio por intervalo
        a1_id = await db.add_scheduled_announcement(
            guild_id=_GUILD,
            channel_id=_CHANNEL_ID,
            message="Anuncio 1",
            mode="interval",
            created_by=int(_USER_ID),
            interval_minutes=30,
            delete_after_seconds=60,
        )
        assert a1_id is not None

        # Obtener anuncio
        a1 = await db.get_scheduled_announcement(_GUILD, a1_id)
        assert a1 is not None
        assert a1["channel_id"] == _CHANNEL_ID
        assert a1["message"] == "Anuncio 1"
        assert a1["mode"] == "interval"
        assert a1["interval_minutes"] == 30
        assert a1["delete_after_seconds"] == 60
        assert a1["content_mode"] == "classic_embed"

        # Actualizar anuncio a modo daily con Layout V2
        layout_json = json.dumps({"blocks": [{"type": "text", "content": "Layout Text"}]})
        updated = await db.update_scheduled_announcement(
            guild_id=_GUILD,
            announcement_id=a1_id,
            channel_id=_CHANNEL_ID,
            message="Layout Preview",
            mode="daily",
            hour=14,
            minute=30,
            embed_json=layout_json,
            content_mode="layout_v2",
            delete_after_seconds=120,
        )
        assert updated is True

        # Verificar actualización
        a1_updated = await db.get_scheduled_announcement(_GUILD, a1_id)
        assert a1_updated["mode"] == "daily"
        assert a1_updated["hour"] == 14
        assert a1_updated["minute"] == 30
        assert a1_updated["content_mode"] == "layout_v2"
        assert a1_updated["embed_json"] == layout_json
        assert a1_updated["delete_after_seconds"] == 120

        # Aislamiento entre guilds en DB
        a1_wrong_guild = await db.get_scheduled_announcement(_GUILD_2, a1_id)
        assert a1_wrong_guild is None

        # Eliminar anuncio
        deleted = await db.remove_scheduled_announcement(_GUILD, a1_id)
        assert deleted is True
        assert await db.get_scheduled_announcement(_GUILD, a1_id) is None

    asyncio.run(_test())


def test_api_anuncios_get_and_post_plain_text(memory_db):
    async def _test():
        req_get = FakeRequest(guild_id=_GUILD)
        resp = await webapi._api_anuncios_get(req_get)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["announcements"] == []
        assert data["count"] == 0
        assert data["max"] == 3

        # POST Anuncio de texto plano por intervalo
        post_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "interval",
            "interval_minutes": 60,
            "content_mode": "plain_text",
            "message": "¡Recuerda leer las reglas!",
            "delete_after_seconds": 300,
        }
        req_post = FakeRequest(guild_id=_GUILD, body=post_body)
        resp_post = await webapi._api_anuncios_post(req_post)
        assert resp_post.status == 201
        post_res = json.loads(resp_post.text)
        ann_id = post_res["id"]
        assert ann_id is not None
        assert post_res["announcement"]["message"] == "¡Recuerda leer las reglas!"
        assert post_res["announcement"]["delete_after_seconds"] == 300

    asyncio.run(_test())


def test_api_anuncios_post_classic_embed_and_daily(memory_db):
    async def _test():
        post_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "daily",
            "hour": 8,
            "minute": 15,
            "content_mode": "classic_embed",
            "embeds": [
                {
                    "title": "Buenos Días",
                    "description": "Que tengan un gran día hoy.",
                    "color": 0x3498DB,
                }
            ],
            "send_options": {
                "username": "Anunciador Oficial",
                "avatar_url": "https://example.com/avatar.png",
            },
        }
        req_post = FakeRequest(guild_id=_GUILD, body=post_body)
        resp_post = await webapi._api_anuncios_post(req_post)
        assert resp_post.status == 201
        post_res = json.loads(resp_post.text)
        ann_id = post_res["id"]

        # Detalle individual
        req_item = FakeRequest(guild_id=_GUILD, announcement_id=ann_id)
        resp_item = await webapi._api_anuncio_get(req_item)
        assert resp_item.status == 200
        item_res = json.loads(resp_item.text)
        ann = item_res["announcement"]
        assert ann["mode"] == "daily"
        assert ann["hour"] == 8
        assert ann["minute"] == 15
        assert ann["content_mode"] == "classic_embed"
        embed_parsed = json.loads(ann["embed_json"])
        assert embed_parsed["embeds"][0]["title"] == "Buenos Días"
        assert embed_parsed["send_options"]["username"] == "Anunciador Oficial"

    asyncio.run(_test())


def test_api_anuncios_put_and_delete(memory_db):
    async def _test():
        # Crear inicial
        post_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "interval",
            "interval_minutes": 15,
            "content_mode": "plain_text",
            "message": "Original",
        }
        req_post = FakeRequest(guild_id=_GUILD, body=post_body)
        resp_post = await webapi._api_anuncios_post(req_post)
        ann_id = json.loads(resp_post.text)["id"]

        # PUT actualizar
        put_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "interval",
            "interval_minutes": 45,
            "content_mode": "plain_text",
            "message": "Actualizado",
            "delete_after_seconds": 180,
        }
        req_put = FakeRequest(guild_id=_GUILD, announcement_id=ann_id, body=put_body)
        resp_put = await webapi._api_anuncio_put(req_put)
        assert resp_put.status == 200
        put_res = json.loads(resp_put.text)
        assert put_res["updated"] is True
        assert put_res["announcement"]["message"] == "Actualizado"
        assert put_res["announcement"]["interval_minutes"] == 45
        assert put_res["announcement"]["delete_after_seconds"] == 180

        # DELETE eliminar
        req_del = FakeRequest(guild_id=_GUILD, announcement_id=ann_id)
        resp_del = await webapi._api_anuncio_delete(req_del)
        assert resp_del.status == 200
        assert json.loads(resp_del.text)["deleted"] is True

        # 404 al consultar eliminado
        resp_get_after = await webapi._api_anuncio_get(req_del)
        assert resp_get_after.status == 404

    asyncio.run(_test())


def test_api_anuncios_validation_errors(memory_db):
    async def _test():
        # Intervalo fuera de rango (<5)
        bad_interval_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 2,
                "content_mode": "plain_text",
                "message": "Test",
            },
        )
        resp = await webapi._api_anuncios_post(bad_interval_req)
        assert resp.status == 400
        assert "interval_minutes" in json.loads(resp.text)["error"]

        # Hora inválida
        bad_hour_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "daily",
                "hour": 25,
                "minute": 0,
                "content_mode": "plain_text",
                "message": "Test",
            },
        )
        resp = await webapi._api_anuncios_post(bad_hour_req)
        assert resp.status == 400
        assert "hora inválida" in json.loads(resp.text)["error"]

        # Delete after inválido
        bad_del_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 30,
                "content_mode": "plain_text",
                "message": "Test",
                "delete_after_seconds": 999999,
            },
        )
        resp = await webapi._api_anuncios_post(bad_del_req)
        assert resp.status == 400
        assert "delete_after_seconds" in json.loads(resp.text)["error"]

    asyncio.run(_test())
