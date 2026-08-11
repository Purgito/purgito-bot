"""Tests de identidad personalizada por mensaje (Fase 3 del editor de
embeds/dashboard): resolución/creación del webhook propio del canal
(webhook_identity.py), las opciones nuevas en message_options.py, y —el punto
que hace o rompe toda la premisa de la fase— que un Webhook.partial construido
con `client=bot` (no `session=` a secas) queda con un estado real adjunto, que
es lo que le permite a discord.py mandar vistas con componentes interactivos
(botones de rol) por ese webhook sin levantar el ValueError documentado en
discord/webhook/async_.py ("Webhook views with interactable components
require an associated state with the webhook").

Usa una DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest
from discord.webhook.async_ import _WebhookState

import db
import webapi
from message_options import (
    sanitize_send_options,
    validate_send_options,
    wants_custom_identity,
)
from webhook_identity import (
    WebhookIdentityError,
    resolve_channel_webhook,
    send_via_webhook,
)


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


# ─── El mecanismo central: Webhook.partial(client=bot) vs session= a secas ──


def test_webhook_partial_with_client_gets_real_state_not_webhookstate():
    """Esto es lo que hace posible que los botones sigan funcionando: sin
    `client=`, discord.py adjunta un _WebhookState de relleno y rechaza
    mandar vistas interactivas por ese webhook."""
    fake_bot = MagicMock()
    fake_bot._connection = MagicMock(name="real_connection_state")
    hook = discord.Webhook.partial(123, "tok", client=fake_bot)
    assert not isinstance(hook._state, _WebhookState)
    assert hook._state is fake_bot._connection


def test_webhook_partial_session_only_gets_webhookstate_placeholder():
    """Contraste directo: si algún día alguien "simplifica" resolve_channel_webhook
    para no pasar `client=`, este test se rompe -- es la señal de alarma."""
    hook = discord.Webhook.partial(123, "tok", session=MagicMock())
    assert isinstance(hook._state, _WebhookState)


# ─── message_options.py: opciones de identidad personalizada ────────────────


def test_sanitize_send_options_passes_through_identity():
    opts = sanitize_send_options(
        {"username": "Anuncios", "avatar_url": "https://x/y.png"}
    )
    assert opts == {
        "silent": False,
        "restrict_mentions": False,
        "allowed_role_ids": [],
        "username": "Anuncios",
        "avatar_url": "https://x/y.png",
    }


def test_sanitize_send_options_none_when_all_default():
    assert sanitize_send_options({"username": "", "avatar_url": ""}) is None
    assert sanitize_send_options({}) is None


def test_wants_custom_identity():
    assert wants_custom_identity({"username": "x", "avatar_url": ""}) is True
    assert wants_custom_identity({"username": "", "avatar_url": "https://x"}) is True
    assert wants_custom_identity({"username": "", "avatar_url": ""}) is False
    assert wants_custom_identity(None) is False


def test_validate_send_options_username_too_long():
    err = validate_send_options({"username": "x" * 81, "avatar_url": ""})
    assert err is not None
    assert validate_send_options({"username": "x" * 80, "avatar_url": ""}) is None


def test_validate_send_options_avatar_url_must_be_http():
    assert (
        validate_send_options({"username": "", "avatar_url": "javascript:alert(1)"})
        is not None
    )
    assert validate_send_options({"username": "", "avatar_url": "ftp://x"}) is not None
    assert (
        validate_send_options({"username": "", "avatar_url": "https://x/y.png"}) is None
    )


def test_validate_send_options_none_is_fine():
    assert validate_send_options(None) is None


# ─── resolve_channel_webhook: DB primero, después channel.webhooks(), después crear ──


def _fake_bot(bot_user_id=999):
    bot = MagicMock()
    bot.user = SimpleNamespace(id=bot_user_id)
    bot._connection = MagicMock()
    return bot


def _fake_channel(channel_id=10, webhooks=None, create_result=None, create_exc=None):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.webhooks = AsyncMock(return_value=webhooks or [])
    if create_exc:
        channel.create_webhook = AsyncMock(side_effect=create_exc)
    else:
        channel.create_webhook = AsyncMock(return_value=create_result)
    return channel


def test_resolve_uses_stored_webhook_without_touching_discord(memory_db):
    asyncio.run(db.set_channel_webhook(1, 10, 555, "tok555"))
    channel = _fake_channel(10)
    bot = _fake_bot()
    hook = asyncio.run(resolve_channel_webhook(bot, 1, channel))
    assert hook.id == 555
    assert hook.token == "tok555"
    channel.webhooks.assert_not_called()
    channel.create_webhook.assert_not_called()


def test_resolve_reuses_existing_bot_owned_webhook(memory_db):
    other_app_hook = SimpleNamespace(id=1, token="t1", user=SimpleNamespace(id=111))
    own_hook = SimpleNamespace(id=2, token="t2", user=SimpleNamespace(id=999))
    channel = _fake_channel(10, webhooks=[other_app_hook, own_hook])
    bot = _fake_bot(bot_user_id=999)
    hook = asyncio.run(resolve_channel_webhook(bot, 1, channel))
    assert hook.id == 2
    channel.create_webhook.assert_not_called()
    # Quedó persistido para no volver a listar la próxima vez.
    row = asyncio.run(db.get_channel_webhook(1, 10))
    assert row == {"webhook_id": 2, "webhook_token": "t2"}


def test_resolve_creates_when_nothing_found(memory_db):
    created = SimpleNamespace(id=3, token="t3")
    channel = _fake_channel(10, webhooks=[], create_result=created)
    bot = _fake_bot()
    hook = asyncio.run(resolve_channel_webhook(bot, 1, channel))
    assert hook.id == 3
    channel.create_webhook.assert_awaited_once()
    assert asyncio.run(db.get_channel_webhook(1, 10)) == {
        "webhook_id": 3,
        "webhook_token": "t3",
    }


def test_resolve_forbidden_raises_clear_error(memory_db):
    channel = _fake_channel(
        10,
        webhooks=[],
        create_exc=discord.Forbidden(SimpleNamespace(status=403, reason=""), "no"),
    )
    bot = _fake_bot()
    with pytest.raises(WebhookIdentityError, match="Gestionar webhooks"):
        asyncio.run(resolve_channel_webhook(bot, 1, channel))


def test_resolve_webhook_cap_raises_clear_error(memory_db):
    exc = discord.HTTPException(
        SimpleNamespace(status=400, reason=""),
        {"code": 30007, "message": "Maximum number of webhooks reached (15)"},
    )
    channel = _fake_channel(10, webhooks=[], create_exc=exc)
    bot = _fake_bot()
    with pytest.raises(WebhookIdentityError, match="15 webhooks"):
        asyncio.run(resolve_channel_webhook(bot, 1, channel))


def test_resolve_other_http_error_raises_generic_message(memory_db):
    exc = discord.HTTPException(
        SimpleNamespace(status=500, reason=""), {"code": 0, "message": "boom"}
    )
    channel = _fake_channel(10, webhooks=[], create_exc=exc)
    bot = _fake_bot()
    with pytest.raises(WebhookIdentityError):
        asyncio.run(resolve_channel_webhook(bot, 1, channel))


def test_channel_webhooks_forbidden_falls_through_to_create(memory_db):
    """Si el bot no puede LISTAR webhooks (raro, pero channel.webhooks()
    también exige Manage Webhooks) no debe explotar -- sigue al intento de
    creación, que es donde se decide si hay o no permiso de verdad."""
    created = SimpleNamespace(id=4, token="t4")
    channel = _fake_channel(10, create_result=created)
    channel.webhooks = AsyncMock(
        side_effect=discord.Forbidden(SimpleNamespace(status=403, reason=""), "no")
    )
    bot = _fake_bot()
    hook = asyncio.run(resolve_channel_webhook(bot, 1, channel))
    assert hook.id == 4


# ─── send_via_webhook ────────────────────────────────────────────────────────


def test_send_via_webhook_omits_blank_identity_kwargs(monkeypatch, memory_db):
    asyncio.run(db.set_channel_webhook(1, 10, 555, "tok555"))
    channel = _fake_channel(10)
    bot = _fake_bot()
    sent_kwargs = {}

    async def fake_send(**kwargs):
        sent_kwargs.update(kwargs)
        return SimpleNamespace(id=42)

    import webhook_identity

    monkeypatch.setattr(
        webhook_identity.discord.Webhook, "send", lambda self, **kw: fake_send(**kw)
    )
    asyncio.run(
        send_via_webhook(bot, 1, channel, username="", avatar_url="", content="hola")
    )
    assert "username" not in sent_kwargs
    assert "avatar_url" not in sent_kwargs
    assert sent_kwargs["content"] == "hola"
    assert sent_kwargs["wait"] is True


def test_send_via_webhook_includes_identity_when_set(monkeypatch, memory_db):
    asyncio.run(db.set_channel_webhook(1, 10, 555, "tok555"))
    channel = _fake_channel(10)
    bot = _fake_bot()
    sent_kwargs = {}

    async def fake_send(**kwargs):
        sent_kwargs.update(kwargs)
        return SimpleNamespace(id=42)

    import webhook_identity

    monkeypatch.setattr(
        webhook_identity.discord.Webhook, "send", lambda self, **kw: fake_send(**kw)
    )
    asyncio.run(
        send_via_webhook(
            bot, 1, channel, username="Anuncios", avatar_url="https://x/y.png"
        )
    )
    assert sent_kwargs["username"] == "Anuncios"
    assert sent_kwargs["avatar_url"] == "https://x/y.png"


def test_send_via_webhook_notfound_clears_stale_row_and_raises(monkeypatch, memory_db):
    asyncio.run(db.set_channel_webhook(1, 10, 555, "tok555"))
    channel = _fake_channel(10)
    bot = _fake_bot()

    import webhook_identity

    async def fake_send(self, **kw):
        raise discord.NotFound(
            SimpleNamespace(status=404, reason=""), "unknown webhook"
        )

    monkeypatch.setattr(webhook_identity.discord.Webhook, "send", fake_send)
    with pytest.raises(WebhookIdentityError):
        asyncio.run(send_via_webhook(bot, 1, channel, username="X"))
    assert asyncio.run(db.get_channel_webhook(1, 10)) is None


# ─── Identidad personalizada persiste en plantillas (punto 4 del pedido) ────
# _extract_content es el único punto de entrada que usan tanto
# /embeds/schedule como /embeds/templates (POST y PUT) -- probarlo acá alcanza
# para cubrir los tres, igual criterio que las pruebas de bloques File.


def test_extract_content_keeps_identity_for_classic_embed():
    data = {
        "content_mode": "classic_embed",
        "embeds": [{"title": "t"}],
        "send_options": {"username": "Anuncios", "avatar_url": "https://x/y.png"},
    }
    content_mode, payload, _preview, err = webapi._extract_content(data)
    assert err is None
    saved = json.loads(payload)
    assert saved["send_options"]["username"] == "Anuncios"
    assert saved["send_options"]["avatar_url"] == "https://x/y.png"


def test_extract_content_keeps_identity_for_layout_v2():
    data = {
        "content_mode": "layout_v2",
        "layout": {"blocks": [{"type": "text", "content": "hola"}]},
        "send_options": {"username": "Anuncios", "avatar_url": ""},
    }
    content_mode, payload, _preview, err = webapi._extract_content(data)
    assert err is None
    saved = json.loads(payload)
    assert saved["send_options"]["username"] == "Anuncios"


def test_extract_content_rejects_bad_avatar_url():
    data = {
        "content_mode": "classic_embed",
        "embeds": [{"title": "t"}],
        "send_options": {"username": "", "avatar_url": "javascript:alert(1)"},
    }
    _content_mode, _payload, _preview, err = webapi._extract_content(data)
    assert err is not None


def test_template_roundtrip_preserves_custom_identity(memory_db):
    data = {
        "content_mode": "classic_embed",
        "embeds": [{"title": "anuncio"}],
        "send_options": {"username": "Bot de avisos", "avatar_url": "https://x/y.png"},
    }
    _content_mode, payload, _preview, err = webapi._extract_content(data)
    assert err is None
    tid = asyncio.run(db.add_embed_template(1, "con identidad", payload))
    saved = asyncio.run(db.get_embed_template(tid, 1))
    saved_options = json.loads(saved["embed_json"])["send_options"]
    assert saved_options["username"] == "Bot de avisos"
    assert saved_options["avatar_url"] == "https://x/y.png"
