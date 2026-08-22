import asyncio
import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import db
import webapi
from cogs.anuncios import Anuncios
from placeholders import build_announcement_context, resolve_placeholders

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

        # Crear anuncio por intervalo (default plain_text)
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
        assert a1["content_mode"] == "plain_text"

        # Actualizar anuncio a modo daily
        updated = await db.update_scheduled_announcement(
            guild_id=_GUILD,
            announcement_id=a1_id,
            channel_id=_CHANNEL_ID,
            message="Mensaje actualizado",
            mode="daily",
            hour=14,
            minute=30,
            delete_after_seconds=120,
        )
        assert updated is True

        # Verificar actualización
        a1_updated = await db.get_scheduled_announcement(_GUILD, a1_id)
        assert a1_updated["mode"] == "daily"
        assert a1_updated["hour"] == 14
        assert a1_updated["minute"] == 30
        assert a1_updated["message"] == "Mensaje actualizado"
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
        assert "variables" in data
        var_names = [v["name"] for v in data["variables"]]
        assert "server_name" in var_names
        assert "channel" in var_names
        assert "user" not in var_names

        # POST Anuncio de texto plano por intervalo sin campos de embed
        post_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "interval",
            "interval_minutes": 60,
            "message": "¡Recuerda leer las reglas en {channel} de {server_name}!",
            "delete_after_seconds": 300,
        }
        req_post = FakeRequest(guild_id=_GUILD, body=post_body)
        resp_post = await webapi._api_anuncios_post(req_post)
        assert resp_post.status == 201
        post_res = json.loads(resp_post.text)
        ann_id = post_res["id"]
        assert ann_id is not None
        assert post_res["announcement"]["message"] == "¡Recuerda leer las reglas en {channel} de {server_name}!"
        assert post_res["announcement"]["delete_after_seconds"] == 300
        assert post_res["announcement"]["content_mode"] == "plain_text"

    asyncio.run(_test())


def test_api_anuncios_post_daily_and_get_item(memory_db):
    async def _test():
        post_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "daily",
            "hour": 8,
            "minute": 15,
            "message": "Buenos días a todos los miembros de {server_name}. Hoy somos {server_membercount}.",
            "delete_after_seconds": 60,
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
        assert ann["content_mode"] == "plain_text"
        assert ann["message"] == "Buenos días a todos los miembros de {server_name}. Hoy somos {server_membercount}."
        assert "variables" in item_res

    asyncio.run(_test())


def test_api_anuncios_put_and_delete(memory_db):
    async def _test():
        # Crear inicial
        post_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "interval",
            "interval_minutes": 15,
            "message": "Original sin variables",
        }
        req_post = FakeRequest(guild_id=_GUILD, body=post_body)
        resp_post = await webapi._api_anuncios_post(req_post)
        ann_id = json.loads(resp_post.text)["id"]

        # PUT actualizar
        put_body = {
            "channel_id": _CHANNEL_ID,
            "mode": "interval",
            "interval_minutes": 45,
            "message": "Actualizado para {server_name}",
            "delete_after_seconds": 180,
        }
        req_put = FakeRequest(guild_id=_GUILD, announcement_id=ann_id, body=put_body)
        resp_put = await webapi._api_anuncio_put(req_put)
        assert resp_put.status == 200
        put_res = json.loads(resp_put.text)
        assert put_res["updated"] is True
        assert put_res["announcement"]["message"] == "Actualizado para {server_name}"
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
                "message": "Test",
            },
        )
        resp = await webapi._api_anuncios_post(bad_interval_req)
        assert resp.status == 400
        assert "interval_minutes" in json.loads(resp.text)["error"]

        # Intervalo fuera de rango (>1440)
        bad_interval_high = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 2000,
                "message": "Test",
            },
        )
        resp_high = await webapi._api_anuncios_post(bad_interval_high)
        assert resp_high.status == 400
        assert "interval_minutes" in json.loads(resp_high.text)["error"]

        # Hora inválida (>23)
        bad_hour_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "daily",
                "hour": 25,
                "minute": 0,
                "message": "Test",
            },
        )
        resp = await webapi._api_anuncios_post(bad_hour_req)
        assert resp.status == 400
        assert "hora inválida" in json.loads(resp.text)["error"]

        # Minuto inválido (>59)
        bad_minute_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "daily",
                "hour": 12,
                "minute": 75,
                "message": "Test",
            },
        )
        resp = await webapi._api_anuncios_post(bad_minute_req)
        assert resp.status == 400
        assert "hora inválida" in json.loads(resp.text)["error"]

        # Mensaje vacío
        empty_msg_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 30,
                "message": "   ",
            },
        )
        resp = await webapi._api_anuncios_post(empty_msg_req)
        assert resp.status == 400
        assert "vacío" in json.loads(resp.text)["error"]

        # Delete after inválido
        bad_del_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 30,
                "message": "Test",
                "delete_after_seconds": 999999,
            },
        )
        resp = await webapi._api_anuncios_post(bad_del_req)
        assert resp.status == 400
        assert "delete_after_seconds" in json.loads(resp.text)["error"]

        # Canal inexistente
        bad_channel_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": 9999999,
                "mode": "interval",
                "interval_minutes": 30,
                "message": "Test",
            },
        )
        resp = await webapi._api_anuncios_post(bad_channel_req)
        assert resp.status == 400
        assert "el canal no existe" in json.loads(resp.text)["error"]

    asyncio.run(_test())


def test_api_anuncios_variables_validation(memory_db):
    async def _test():
        # Variable desconocida rechazada con 400
        bad_var_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 30,
                "message": "Hola {variable_inexistente}",
            },
        )
        resp = await webapi._api_anuncios_post(bad_var_req)
        assert resp.status == 400
        assert "Variable desconocida" in json.loads(resp.text)["error"]

        # Variable de usuario rechazada con 400 en contexto de anuncio
        user_var_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 30,
                "message": "Bienvenido {user_name} a nuestro servidor",
            },
        )
        resp_user = await webapi._api_anuncios_post(user_var_req)
        assert resp_user.status == 400
        assert "no está disponible" in json.loads(resp_user.text)["error"]

        # Variable {user} rechazada con 400
        user_mention_req = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "daily",
                "hour": 10,
                "minute": 0,
                "message": "Hola {user}",
            },
        )
        resp_mention = await webapi._api_anuncios_post(user_mention_req)
        assert resp_mention.status == 400
        assert "no está disponible" in json.loads(resp_mention.text)["error"]

    asyncio.run(_test())


def test_api_anuncios_quota_limit(memory_db):
    async def _test():
        for i in range(3):
            req = FakeRequest(
                guild_id=_GUILD,
                body={
                    "channel_id": _CHANNEL_ID,
                    "mode": "interval",
                    "interval_minutes": 30 + i,
                    "message": f"Anuncio {i}",
                },
            )
            resp = await webapi._api_anuncios_post(req)
            assert resp.status == 201

        # Cuarto anuncio excede límite de 3 (free)
        req_over = FakeRequest(
            guild_id=_GUILD,
            body={
                "channel_id": _CHANNEL_ID,
                "mode": "interval",
                "interval_minutes": 60,
                "message": "Anuncio 4 excedido",
            },
        )
        resp_over = await webapi._api_anuncios_post(req_over)
        assert resp_over.status == 409
        assert "máximo de anuncios" in json.loads(resp_over.text)["error"]

    asyncio.run(_test())


def test_anuncios_runtime_resolution_and_delivery(memory_db):
    """Verifica que DB (raw template) -> build_announcement_context -> resolve_placeholders -> channel.send()

    resuelve variables con datos actuales (ej. member_count) al momento del envío.
    """
    fake_channel = MagicMock(spec=discord.TextChannel)
    fake_channel.id = _CHANNEL_ID
    fake_channel.name = "general"
    fake_channel.mention = "<#555>"
    perms = MagicMock()
    perms.send_messages = True
    fake_channel.permissions_for = MagicMock(return_value=perms)
    fake_channel.send = AsyncMock()

    fake_guild = MagicMock(spec=discord.Guild)
    fake_guild.id = _GUILD
    fake_guild.name = "Servidor Increíble"
    fake_guild.member_count = 1420
    fake_guild.members = [MagicMock()]
    fake_guild.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    fake_guild.roles = [MagicMock(), MagicMock()]
    fake_guild.channels = [fake_channel]
    fake_guild.premium_tier = 2
    fake_guild.premium_subscription_count = 7
    fake_guild.icon = None
    fake_guild.owner = None
    fake_guild.owner_id = 111

    fake_channel.guild = fake_guild

    fake_bot = MagicMock()
    fake_bot.get_channel.return_value = fake_channel

    # Guardar anuncio con template sin resolver en DB
    raw_template = "¡Bienvenidos a {server_name}! Canal: {channel_name}. Miembros actuales: {server_membercount}."
    asyncio.run(
        db.add_scheduled_announcement(
            guild_id=_GUILD,
            channel_id=_CHANNEL_ID,
            message=raw_template,
            mode="interval",
            created_by=int(_USER_ID),
            interval_minutes=30,
        )
    )

    # Verificar que en DB se guardó el raw string sin resolver
    ann = asyncio.run(db.get_scheduled_announcement(_GUILD, 1))
    assert ann["message"] == raw_template

    # Ejecutar loop de anuncios
    cog = Anuncios(fake_bot)
    asyncio.run(cog.check_announcements.coro(cog))

    # Verificar que channel.send fue llamado con las variables resueltas
    fake_channel.send.assert_awaited_once()
    sent_msg = fake_channel.send.await_args[0][0]
    assert sent_msg == "¡Bienvenidos a Servidor Increíble! Canal: general. Miembros actuales: 1.420."


def test_anuncios_legacy_embed_runtime_resilience(memory_db):
    """Verifica que anuncios históricos guardados con embed_json se envíen sin romper el loop."""
    fake_channel = MagicMock(spec=discord.TextChannel)
    fake_channel.id = _CHANNEL_ID
    perms = MagicMock()
    perms.send_messages = True
    perms.embed_links = True
    fake_channel.permissions_for = MagicMock(return_value=perms)
    fake_channel.send = AsyncMock()

    fake_guild = MagicMock(spec=discord.Guild)
    fake_guild.id = _GUILD
    fake_channel.guild = fake_guild

    fake_bot = MagicMock()
    fake_bot.get_channel.return_value = fake_channel

    legacy_embed = json.dumps([{"title": "Legacy Embed", "description": "Contenido antiguo"}])
    asyncio.run(
        db.add_scheduled_announcement(
            guild_id=_GUILD,
            channel_id=_CHANNEL_ID,
            message="Snippet legacy",
            mode="interval",
            created_by=int(_USER_ID),
            interval_minutes=30,
            embed_json=legacy_embed,
            content_mode="classic_embed",
        )
    )

    cog = Anuncios(fake_bot)
    asyncio.run(cog.check_announcements.coro(cog))

    # El loop debió despachar embeds usando la compatibilidad legacy
    fake_channel.send.assert_awaited_once()
    kwargs = fake_channel.send.await_args[1]
    assert "embeds" in kwargs
    assert kwargs["embeds"][0].title == "Legacy Embed"
