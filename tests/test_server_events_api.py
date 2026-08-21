import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import db
import webapi

_GUILD = 123
_CHANNEL_ID = 555
_USER_ID = "999888777"
_USERNAME = "AdminUser"


class FakeRequest:
    def __init__(self, guild_id=_GUILD, event_type="welcome", body=None):
        self._body = body
        self.match_info = {
            "guild_id": str(guild_id),
            "event_type": str(event_type),
        }
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
def allow_guild_access(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": _USERNAME}

    async def fake_check_guild_access(request, guild_id):
        return None

    fake_guild = MagicMock(spec=discord.Guild)
    fake_guild.id = _GUILD
    fake_guild.name = "Test Server"
    fake_guild.member_count = 100
    fake_guild.me = MagicMock()

    fake_channel = MagicMock(spec=discord.TextChannel)
    fake_channel.id = _CHANNEL_ID
    fake_channel.name = "llegadas"
    fake_channel.guild = fake_guild
    fake_channel.permissions_for = MagicMock(
        return_value=MagicMock(send_messages=True, embed_links=True)
    )
    fake_guild.get_channel = MagicMock(
        side_effect=lambda cid: fake_channel if cid == _CHANNEL_ID else None
    )

    fake_bot = MagicMock()
    fake_bot.get_guild = MagicMock(return_value=fake_guild)
    fake_bot.user = MagicMock()
    fake_bot.user.id = 1234

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: fake_guild)


def test_server_events_api_get_all_and_single(memory_db):
    async def _test():
        # GET all
        req = FakeRequest()
        resp = await webapi._api_server_events_get(req)
        data = json.loads(resp.text)
        assert "events" in data
        assert "variables" in data
        assert len(data["variables"]) > 0

        # GET single (unconfigured)
        req = FakeRequest(event_type="welcome")
        resp = await webapi._api_server_event_get(req)
        data = json.loads(resp.text)
        assert data["event"] is None
        assert "variables" in data

        # GET invalid event type
        req = FakeRequest(event_type="invalid_type")
        resp = await webapi._api_server_event_get(req)
        assert resp.status == 400

    asyncio.run(_test())


def test_server_events_api_put_plain_text_and_validation(memory_db):
    async def _test():
        # Valid PUT plain text
        body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "plain_text",
            "message": "Bienvenido {user} a {server_name}! Somos {server_membercount}",
        }
        req = FakeRequest(event_type="welcome", body=body)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["saved"] is True
        assert data["event"]["enabled"] is True
        assert data["event"]["message"] == body["message"]

        # PUT with unknown variable
        bad_body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "plain_text",
            "message": "Hola {variable_inexistente}",
        }
        req = FakeRequest(event_type="welcome", body=bad_body)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 400
        data = json.loads(resp.text)
        assert "Variable desconocida" in data["error"]

        # PUT with incompatible variable (boost var in welcome)
        bad_body2 = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "plain_text",
            "message": "Faltan {server_nextboostlevel_required} boosts",
        }
        req = FakeRequest(event_type="welcome", body=bad_body2)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 400
        data = json.loads(resp.text)
        assert "no está disponible" in data["error"]

        # PUT with channel that does not exist
        bad_chan = {
            "enabled": True,
            "channel_id": 999999,
            "content_mode": "plain_text",
            "message": "Bienvenido {user}",
        }
        req = FakeRequest(event_type="welcome", body=bad_chan)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 400
        data = json.loads(resp.text)
        assert "el canal no existe" in data["error"]

    asyncio.run(_test())


def test_server_events_api_put_embed_and_layout(memory_db):
    async def _test():
        # Classic Embed
        embed_body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "classic_embed",
            "embeds": [
                {
                    "title": "Bienvenido {user_name}!",
                    "description": "Gracias por unirte a {server_name}",
                    "thumbnail": {"url": "{user_avatar}"},
                }
            ],
            "send_options": {"silent": True},
        }
        req = FakeRequest(event_type="welcome", body=embed_body)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["saved"] is True
        assert data["event"]["content_mode"] == "classic_embed"

        # Layout V2
        layout_body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "layout_v2",
            "layout": {
                "blocks": [
                    {
                        "type": "text",
                        "content": "🚀 **¡Nuevo Boost!** Gracias {user}!",
                    }
                ]
            },
        }
        req = FakeRequest(event_type="boost", body=layout_body)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["saved"] is True
        assert data["event"]["content_mode"] == "layout_v2"

        # Composite Mode (Message + Embed + Buttons)
        composite_body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "composite",
            "message": "¡Bienvenido {user} a {server_name}!",
            "embeds": [
                {
                    "title": "Reglas de la comunidad",
                    "description": "Por favor revisa {channel} antes de comenzar",
                }
            ],
            "buttons": [
                {"label": "Web Oficial", "url": "https://purgito.com", "style": "link"}
            ],
            "send_options": {"username": "Purgito Welcomer"},
        }
        req = FakeRequest(event_type="welcome", body=composite_body)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["saved"] is True
        assert data["event"]["content_mode"] == "composite"
        assert data["event"]["message"] == composite_body["message"]
        parsed_embed_json = json.loads(data["event"]["embed_json"])
        assert len(parsed_embed_json["embeds"]) == 1
        assert len(parsed_embed_json["buttons"]) == 1

    asyncio.run(_test())



def test_server_events_api_delete(memory_db):
    async def _test():
        # Setup an event
        body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "plain_text",
            "message": "Adios {user}!",
        }
        req = FakeRequest(event_type="goodbye", body=body)
        await webapi._api_server_event_put(req)

        # DELETE
        req_del = FakeRequest(event_type="goodbye")
        resp = await webapi._api_server_event_delete(req_del)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["deleted"] is True

        # Check it is gone
        ev = await db.get_server_event(_GUILD, "goodbye")
        assert ev is None

    asyncio.run(_test())


def test_server_events_api_test_endpoint(memory_db):
    async def _test():
        fake_cog = MagicMock()
        fake_cog.dispatch_server_event = AsyncMock(return_value=(True, None))

        bot = MagicMock()
        bot.get_cog = MagicMock(return_value=fake_cog)

        body = {
            "channel_id": _CHANNEL_ID,
            "content_mode": "plain_text",
            "message": "Prueba de bienvenida para {user}!",
        }
        req = FakeRequest(event_type="welcome", body=body)
        req.app["bot"] = bot

        resp = await webapi._api_server_event_test(req)
        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["sent"] is True
        assert fake_cog.dispatch_server_event.called

    asyncio.run(_test())


def test_server_events_api_test_endpoint_rate_limit(memory_db):
    """SEC-04: El endpoint /test aplica rate limiting y rechaza ráfagas con HTTP 429."""
    async def _test():
        fake_cog = MagicMock()
        fake_cog.dispatch_server_event = AsyncMock(return_value=(True, None))

        bot = MagicMock()
        bot.get_cog = MagicMock(return_value=fake_cog)

        body = {
            "channel_id": _CHANNEL_ID,
            "content_mode": "plain_text",
            "message": "Test spam",
        }

        # Limpiar bucket de rate limit para IP de prueba
        test_ip = "10.20.30.40"
        webapi._rate_post.pop(test_ip, None)

        # Enviar 5 requests exitosas
        for i in range(5):
            req = FakeRequest(event_type="welcome", body=body)
            req.remote = test_ip
            req.headers = {"X-Forwarded-For": test_ip}
            req.app["bot"] = bot
            resp = await webapi._api_server_event_test(req)
            assert resp.status == 200

        # La 6ta request consecutiva debe devolver 429
        req = FakeRequest(event_type="welcome", body=body)
        req.remote = test_ip
        req.headers = {"X-Forwarded-For": test_ip}
        req.app["bot"] = bot
        resp = await webapi._api_server_event_test(req)
        assert resp.status == 429
        data = json.loads(resp.text)
        assert "demasiados intentos" in data["error"]

    asyncio.run(_test())


def test_server_events_api_put_validates_send_options_placeholders(memory_db):
    """SEC-05: Las variables en send_options se validan con el catálogo del evento."""
    async def _test():
        # 1. Variable desconocida en send_options.username -> 400
        bad_body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "classic_embed",
            "embeds": [{"title": "Title"}],
            "send_options": {"username": "Bot de {variable_inexistente}"},
        }
        req = FakeRequest(event_type="welcome", body=bad_body)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 400
        data = json.loads(resp.text)
        assert "Variable desconocida" in data["error"]

        # 2. Variable válida en send_options.username -> 200
        good_body = {
            "enabled": True,
            "channel_id": _CHANNEL_ID,
            "content_mode": "classic_embed",
            "embeds": [{"title": "Title"}],
            "send_options": {"username": "Bot de {server_name}"},
        }
        req = FakeRequest(event_type="welcome", body=good_body)
        resp = await webapi._api_server_event_put(req)
        assert resp.status == 200

    asyncio.run(_test())


class FakeTemplateRequest:
    """Igual que FakeRequest pero con match_info de plantillas (sin event_type)."""

    def __init__(self, guild_id=_GUILD, template_id=None, body=None):
        self._body = body
        self.match_info = {"guild_id": str(guild_id)}
        if template_id is not None:
            self.match_info["template_id"] = str(template_id)
        self.headers = {"X-Forwarded-For": "1.2.3.4"}
        self.remote = "1.2.3.4"

    async def json(self):
        if self._body is None:
            raise ValueError("sin body")
        return self._body


def test_event_put_with_template_id_links_and_resolves(memory_db):
    async def _test():
        create_resp = await webapi._api_embed_templates_post(
            FakeTemplateRequest(body={"name": "Bienvenida", "content_mode": "plain_text", "message": "Hola {user}"})
        )
        assert create_resp.status == 200
        template_id = json.loads(create_resp.text)["id"]

        put_resp = await webapi._api_server_event_put(FakeRequest(
            event_type="welcome",
            body={"enabled": True, "channel_id": _CHANNEL_ID, "template_id": template_id},
        ))
        assert put_resp.status == 200
        saved = json.loads(put_resp.text)["event"]
        assert saved["template_id"] == template_id

        get_resp = await webapi._api_server_event_get(FakeRequest(event_type="welcome"))
        resolved = json.loads(get_resp.text)["event"]
        assert resolved["content_mode"] == "plain_text"
        assert resolved["message"] == "Hola {user}"

        # template_id inexistente -> 400, no crea referencia colgante
        bad_resp = await webapi._api_server_event_put(FakeRequest(
            event_type="goodbye",
            body={"enabled": False, "channel_id": _CHANNEL_ID, "template_id": 999999},
        ))
        assert bad_resp.status == 400

    asyncio.run(_test())


def test_template_delete_blocked_while_in_use(memory_db):
    async def _test():
        create_resp = await webapi._api_embed_templates_post(
            FakeTemplateRequest(body={"name": "Gracias por boostear", "content_mode": "plain_text", "message": "Gracias {user}"})
        )
        template_id = json.loads(create_resp.text)["id"]

        await webapi._api_server_event_put(FakeRequest(
            event_type="boost",
            body={"enabled": True, "channel_id": _CHANNEL_ID, "template_id": template_id},
        ))

        list_resp = await webapi._api_embed_templates_get(FakeTemplateRequest())
        tpl = json.loads(list_resp.text)["templates"][0]
        assert tpl["used_by"] == ["boost"]

        delete_resp = await webapi._api_embed_template_delete(
            FakeTemplateRequest(template_id=template_id)
        )
        assert delete_resp.status == 409
        assert "boost" in json.loads(delete_resp.text)["error"]

        # Al desvincular el evento, ahora sí se puede borrar.
        await webapi._api_server_event_put(FakeRequest(
            event_type="boost",
            body={"enabled": False, "channel_id": _CHANNEL_ID, "template_id": None},
        ))
        delete_resp2 = await webapi._api_embed_template_delete(
            FakeTemplateRequest(template_id=template_id)
        )
        assert delete_resp2.status == 200
        assert json.loads(delete_resp2.text)["deleted"] is True

    asyncio.run(_test())


def test_server_events_save_and_switch_templates_cycle(memory_db):
    """Prueba el ciclo completo de guardar, cambiar plantilla y desvincular para welcome, goodbye y boost."""
    async def _test():
        # Crear Plantilla A
        res_a = await webapi._api_embed_templates_post(
            FakeTemplateRequest(body={"name": "Plantilla A", "content_mode": "plain_text", "message": "Mensaje A {user}"})
        )
        tpl_a_id = json.loads(res_a.text)["id"]

        # Crear Plantilla B
        res_b = await webapi._api_embed_templates_post(
            FakeTemplateRequest(body={"name": "Plantilla B", "content_mode": "plain_text", "message": "Mensaje B {user}"})
        )
        tpl_b_id = json.loads(res_b.text)["id"]

        for ev_type in ("welcome", "goodbye", "boost"):
            # 1. Guardar con Plantilla A
            put_a = await webapi._api_server_event_put(FakeRequest(
                event_type=ev_type,
                body={"enabled": True, "channel_id": _CHANNEL_ID, "template_id": tpl_a_id},
            ))
            assert put_a.status == 200
            assert json.loads(put_a.text)["event"]["template_id"] == tpl_a_id

            # 2. Recargar y verificar que tiene plantilla A
            get_a = await webapi._api_server_event_get(FakeRequest(event_type=ev_type))
            ev_a = json.loads(get_a.text)["event"]
            assert ev_a["template_id"] == tpl_a_id
            assert ev_a["message"] == "Mensaje A {user}"
            assert ev_a["template_name"] == "Plantilla A"

            # 3. Cambiar a Plantilla B
            put_b = await webapi._api_server_event_put(FakeRequest(
                event_type=ev_type,
                body={"enabled": True, "channel_id": _CHANNEL_ID, "template_id": tpl_b_id},
            ))
            assert put_b.status == 200
            assert json.loads(put_b.text)["event"]["template_id"] == tpl_b_id

            # 4. Recargar y verificar que tiene plantilla B
            get_b = await webapi._api_server_event_get(FakeRequest(event_type=ev_type))
            ev_b = json.loads(get_b.text)["event"]
            assert ev_b["template_id"] == tpl_b_id
            assert ev_b["message"] == "Mensaje B {user}"
            assert ev_b["template_name"] == "Plantilla B"

            # 5. Desvincular plantilla (template_id = None) y desactivar
            put_none = await webapi._api_server_event_put(FakeRequest(
                event_type=ev_type,
                body={"enabled": False, "channel_id": _CHANNEL_ID, "template_id": None},
            ))
            assert put_none.status == 200
            assert json.loads(put_none.text)["event"]["template_id"] is None

            # 6. Recargar y verificar que no tiene plantilla
            get_none = await webapi._api_server_event_get(FakeRequest(event_type=ev_type))
            ev_none = json.loads(get_none.text)["event"]
            assert ev_none["template_id"] is None
            assert ev_none["enabled"] is False

    asyncio.run(_test())


def test_server_events_enable_without_template_rejected_if_no_legacy(memory_db):
    """Activar un evento sin plantilla ni contenido previo es rechazado con error claro."""
    async def _test():
        resp = await webapi._api_server_event_put(FakeRequest(
            event_type="welcome",
            body={"enabled": True, "channel_id": _CHANNEL_ID, "template_id": None},
        ))
        assert resp.status == 400
        data = json.loads(resp.text)
        assert "debes seleccionar una plantilla" in data["error"]

    asyncio.run(_test())


def test_server_events_enable_preserves_legacy_inline_when_unlinked(memory_db):
    """Un evento antiguo con mensaje inline puede reactivarse sin template_id y conserva su mensaje."""
    async def _test():
        # Configurar evento en formato legacy
        await webapi._api_server_event_put(FakeRequest(
            event_type="goodbye",
            body={
                "enabled": True,
                "channel_id": _CHANNEL_ID,
                "content_mode": "plain_text",
                "message": "Hasta luego {user}",
            },
        ))

        # Actualizar desde el configurador cambiando solo canal y enabled
        resp = await webapi._api_server_event_put(FakeRequest(
            event_type="goodbye",
            body={"enabled": True, "channel_id": _CHANNEL_ID, "template_id": None},
        ))
        assert resp.status == 200
        ev = json.loads(resp.text)["event"]
        assert ev["enabled"] is True
        assert ev["message"] == "Hasta luego {user}"
        assert ev["template_id"] is None

    asyncio.run(_test())


def test_server_events_snowflake_channel_id_preserved_and_resolved(memory_db, monkeypatch):
    """Verifica que un Snowflake de 19 dígitos (> 2^53) se procese sin pérdida de precisión."""
    snowflake_channel_id = 1345678901234567895

    fake_guild = MagicMock(spec=discord.Guild)
    fake_guild.id = _GUILD
    fake_guild.name = "Test Server"
    fake_guild.me = MagicMock()

    fake_channel = MagicMock(spec=discord.TextChannel)
    fake_channel.id = snowflake_channel_id
    fake_channel.guild = fake_guild
    fake_channel.permissions_for = MagicMock(
        return_value=MagicMock(send_messages=True, embed_links=True)
    )
    fake_guild.get_channel = MagicMock(
        side_effect=lambda cid: fake_channel if cid == snowflake_channel_id else None
    )

    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: fake_guild)

    async def _test():
        tpl_res = await webapi._api_embed_templates_post(
            FakeTemplateRequest(body={"name": "Bienvenida Snowflake", "content_mode": "plain_text", "message": "Hola {user}"})
        )
        tpl_id = json.loads(tpl_res.text)["id"]

        # Guardar pasando snowflake como string
        put_resp = await webapi._api_server_event_put(FakeRequest(
            event_type="welcome",
            body={"enabled": True, "channel_id": str(snowflake_channel_id), "template_id": tpl_id},
        ))
        assert put_resp.status == 200
        saved_ev = json.loads(put_resp.text)["event"]
        assert saved_ev["channel_id"] == snowflake_channel_id

        # Recargar y verificar exactitud del Snowflake
        get_resp = await webapi._api_server_event_get(FakeRequest(event_type="welcome"))
        assert get_resp.status == 200
        ev = json.loads(get_resp.text)["event"]
        assert ev["channel_id"] == snowflake_channel_id

    asyncio.run(_test())


def test_server_events_channel_fallback_to_fetch_channel(memory_db, monkeypatch):
    """Si el canal no está en la caché local del guild, se resuelve vía bot.fetch_channel."""
    uncached_channel_id = 777888999

    fake_guild = MagicMock(spec=discord.Guild)
    fake_guild.id = _GUILD
    fake_guild.me = MagicMock()
    # Cache local retorna None
    fake_guild.get_channel = MagicMock(return_value=None)

    fake_channel = MagicMock(spec=discord.TextChannel)
    fake_channel.id = uncached_channel_id
    fake_channel.guild = fake_guild
    fake_channel.permissions_for = MagicMock(
        return_value=MagicMock(send_messages=True, embed_links=True)
    )

    fake_bot = MagicMock()
    fake_bot.fetch_channel = AsyncMock(return_value=fake_channel)
    fake_bot.user = MagicMock(id=1234)

    monkeypatch.setattr(webapi, "_bot_guild", lambda req, gid: fake_guild)

    async def _test():
        req = FakeRequest(
            event_type="welcome",
            body={
                "enabled": True,
                "channel_id": uncached_channel_id,
                "content_mode": "plain_text",
                "message": "Hola {user}",
            },
        )
        req.app["bot"] = fake_bot

        put_resp = await webapi._api_server_event_put(req)
        assert put_resp.status == 200
        assert fake_bot.fetch_channel.called

    asyncio.run(_test())


def test_server_events_composite_button_validation(memory_db):
    """Valida límites y seguridad de botones en plantillas y eventos composite."""
    async def _test():
        # 1. URL maliciosa (javascript:) rechazada
        bad_url_resp = await webapi._api_embed_templates_post(FakeTemplateRequest(
            body={
                "name": "Malicious Button",
                "content_mode": "composite",
                "message": "Test",
                "buttons": [{"label": "Click", "style": "link", "url": "javascript:alert(1)"}],
            }
        ))
        assert bad_url_resp.status == 400
        assert "http" in json.loads(bad_url_resp.text)["error"]

        # 2. Más de 5 botones rechazado
        too_many_resp = await webapi._api_embed_templates_post(FakeTemplateRequest(
            body={
                "name": "Too Many Buttons",
                "content_mode": "composite",
                "message": "Test",
                "buttons": [
                    {"label": f"B{i}", "style": "link", "url": "https://example.com"}
                    for i in range(6)
                ],
            }
        ))
        assert too_many_resp.status == 400
        assert "más de 5 botones" in json.loads(too_many_resp.text)["error"]

        # 3. Botón de rol sin role_id rechazado
        no_role_resp = await webapi._api_embed_templates_post(FakeTemplateRequest(
            body={
                "name": "Missing Role ID",
                "content_mode": "composite",
                "message": "Test",
                "buttons": [{"label": "Rol", "style": "role", "role_id": None}],
            }
        ))
        assert no_role_resp.status == 400
        assert "rol asignado" in json.loads(no_role_resp.text)["error"]

        # 4. Botones válidos aceptados
        ok_resp = await webapi._api_embed_templates_post(FakeTemplateRequest(
            body={
                "name": "Valid Buttons",
                "content_mode": "composite",
                "message": "Test {user}",
                "buttons": [
                    {"label": "Web", "style": "link", "url": "https://purgito.app"},
                    {"label": "Rol VIP", "style": "role", "role_id": 999999999999999999},
                ],
            }
        ))
        assert ok_resp.status == 200

    asyncio.run(_test())


def test_cross_server_template_idor_blocked(memory_db):
    """Un servidor no puede asignar ni acceder a una plantilla de otro servidor."""
    async def _test():
        # Crear plantilla en Servidor 1 (guild_id = _GUILD = 123)
        res1 = await webapi._api_embed_templates_post(FakeTemplateRequest(
            guild_id=123,
            body={"name": "Plantilla Guild 123", "content_mode": "plain_text", "message": "Guild 123 {user}"},
        ))
        tpl_id = json.loads(res1.text)["id"]

        # Intentar asignar la plantilla en Servidor 2 (guild_id = 999)
        put_idor = await webapi._api_server_event_put(FakeRequest(
            guild_id=999,
            event_type="welcome",
            body={"enabled": False, "channel_id": None, "template_id": tpl_id},
        ))
        assert put_idor.status == 400
        assert "plantilla no encontrada" in json.loads(put_idor.text)["error"]

    asyncio.run(_test())


