import asyncio
import datetime
import json
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import db
from cogs.events import ServerEvents

_GUILD_ID = 123
_CHANNEL_ID = 456


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def test_on_member_join_and_welcome(memory_db):
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        # Configure welcome event in DB
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="plain_text",
            message="¡Bienvenido {user} a {server_name}! Miembro {server_membercount_ordinal}.",
        )

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = _CHANNEL_ID
        channel.guild = MagicMock(id=_GUILD_ID)
        channel.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        channel.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "Purgito Community"
        guild.member_count = 125
        guild.get_channel = MagicMock(return_value=channel)
        guild.me = MagicMock()

        member = MagicMock(spec=discord.Member)
        member.id = 777
        member.bot = False
        member.name = "newbie"
        member.mention = "<@777>"
        member.display_name = "Newbie"
        member.guild = guild

        # Trigger on_member_join
        await cog.on_member_join(member)

        assert channel.send.called
        sent_msg = channel.send.call_args[0][0]
        assert "¡Bienvenido <@777> a Purgito Community! Miembro #125." in sent_msg

        # Test disabled event
        await db.toggle_server_event(_GUILD_ID, "welcome", False)
        channel.send.reset_mock()
        await cog.on_member_join(member)
        assert not channel.send.called

        # Test bot member ignored
        await db.toggle_server_event(_GUILD_ID, "welcome", True)
        member.bot = True
        channel.send.reset_mock()
        await cog.on_member_join(member)
        assert not channel.send.called

    asyncio.run(_test())


def test_on_member_remove_and_goodbye(memory_db):
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        # Configure goodbye event
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="goodbye",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="plain_text",
            message="Hasta luego {user_name}, gracias por haber estado en {server_name}.",
        )

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = _CHANNEL_ID
        channel.guild = MagicMock(id=_GUILD_ID)
        channel.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        channel.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "Purgito Community"
        guild.member_count = 124
        guild.get_channel = MagicMock(return_value=channel)
        guild.me = MagicMock()

        member = MagicMock(spec=discord.Member)
        member.id = 777
        member.bot = False
        member.name = "leaver"
        member.mention = "<@777>"
        member.guild = guild

        await cog.on_member_remove(member)

        assert channel.send.called
        sent_msg = channel.send.call_args[0][0]
        assert "Hasta luego leaver, gracias por haber estado en Purgito Community." in sent_msg

    asyncio.run(_test())


def test_on_member_update_boost_transition_and_idempotency(memory_db):
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="boost",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="plain_text",
            message="🚀 ¡Muchas gracias {user} por el boost a {server_name}! Nivel: {server_boostlevel}.",
        )

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = _CHANNEL_ID
        channel.guild = MagicMock(id=_GUILD_ID)
        channel.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        channel.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "Purgito Community"
        guild.member_count = 124
        guild.premium_tier = 2
        guild.premium_subscription_count = 7
        guild.get_channel = MagicMock(return_value=channel)
        guild.me = MagicMock()

        boost_time = datetime.datetime(2026, 8, 21, 10, 0, tzinfo=datetime.timezone.utc)

        before = MagicMock(spec=discord.Member)
        before.id = 555
        before.premium_since = None
        before.guild = guild

        after = MagicMock(spec=discord.Member)
        after.id = 555
        after.name = "booster"
        after.mention = "<@555>"
        after.premium_since = boost_time
        after.guild = guild

        # 1. First transition: None -> timestamp (should send)
        await cog.on_member_update(before, after)
        assert channel.send.called
        sent_msg = channel.send.call_args[0][0]
        assert "🚀 ¡Muchas gracias <@555> por el boost a Purgito Community! Nivel: 2." in sent_msg

        # 2. Repeated event for the same boost (should NOT duplicate)
        channel.send.reset_mock()
        await cog.on_member_update(before, after)
        assert not channel.send.called

        # 3. Member update where user was already boosting (should NOT send)
        channel.send.reset_mock()
        before_already = MagicMock(spec=discord.Member)
        before_already.premium_since = boost_time
        before_already.guild = guild
        await cog.on_member_update(before_already, after)
        assert not channel.send.called

    asyncio.run(_test())


def test_dispatch_event_embed_and_layout(memory_db):
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = _CHANNEL_ID
        channel.guild = MagicMock(id=_GUILD_ID)
        channel.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        channel.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "Purgito Community"
        guild.member_count = 100
        guild.get_channel = MagicMock(return_value=channel)
        guild.me = MagicMock()

        member = MagicMock(spec=discord.Member)
        member.id = 777
        member.name = "isa"
        member.mention = "<@777>"
        member.display_avatar = MagicMock()
        member.display_avatar.url = "https://cdn.discordapp.com/avatar.png"
        member.guild = guild

        # Classic Embed
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="classic_embed",
            embed_json='[{"title": "¡Bienvenido {user_name}!", "description": "A {server_name}"}]',
        )

        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is True
        assert err is None
        assert channel.send.called
        call_kwargs = channel.send.call_args[1]
        assert "embeds" in call_kwargs
        assert call_kwargs["embeds"][0].title == "¡Bienvenido isa!"
        assert call_kwargs["embeds"][0].description == "A Purgito Community"

        # Layout V2
        layout_json = (
            '{"blocks": [{"type": "text", "content": "Bienvenido {user} a {server_name}!"}]}'
        )
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="layout_v2",
            embed_json=layout_json,
        )

        channel.send.reset_mock()
        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is True
        assert err is None
        assert channel.send.called
        call_kwargs = channel.send.call_args[1]
        # Composite Mode (Message + Embed + Buttons)
        composite_payload = {
            "embeds": [{"title": "Bienvenido {user_name}!", "description": "A {server_name}"}],
            "buttons": [{"label": "Reglas", "url": "https://example.com/rules", "style": "link"}],
        }
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="composite",
            message="¡Hola {user}!",
            embed_json=json.dumps(composite_payload),
        )

        channel.send.reset_mock()
        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is True
        assert err is None
        assert channel.send.called
        call_kwargs = channel.send.call_args[1]
        assert call_kwargs.get("content") == "¡Hola <@777>!"
        assert "embeds" in call_kwargs
        assert len(call_kwargs["embeds"]) == 1
        assert "view" in call_kwargs

    asyncio.run(_test())



def test_boost_100_concurrent_updates_exact_one_message(memory_db):
    """SEC-01: 100 corrutinas on_member_update concurrentes resultan en exactamente 1 mensaje enviado."""
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="boost",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="plain_text",
            message="🚀 ¡Gracias {user}!",
        )

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = _CHANNEL_ID
        channel.guild = MagicMock(id=_GUILD_ID)
        channel.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        channel.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "Purgito Community"
        guild.member_count = 100
        guild.premium_tier = 1
        guild.premium_subscription_count = 2
        guild.get_channel = MagicMock(return_value=channel)
        guild.me = MagicMock()

        boost_time = datetime.datetime(2026, 8, 21, 10, 0, tzinfo=datetime.timezone.utc)

        before = MagicMock(spec=discord.Member)
        before.id = 888
        before.premium_since = None
        before.guild = guild

        after = MagicMock(spec=discord.Member)
        after.id = 888
        after.name = "concurrent_booster"
        after.mention = "<@888>"
        after.premium_since = boost_time
        after.guild = guild

        # Disparar 100 corrutinas concurrentemente con asyncio.gather
        tasks = [cog.on_member_update(before, after) for _ in range(100)]
        await asyncio.gather(*tasks)

        # EXACTAMENTE 1 mensaje enviado
        assert channel.send.call_count == 1

        # Si vuelve a dispararse después, 0 mensajes adicionales
        channel.send.reset_mock()
        await cog.on_member_update(before, after)
        assert channel.send.call_count == 0

        # Si el usuario deja de boostear y luego vuelve a boostear con nueva fecha B:
        boost_time_b = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc)
        after_b = MagicMock(spec=discord.Member)
        after_b.id = 888
        after_b.name = "concurrent_booster"
        after_b.mention = "<@888>"
        after_b.premium_since = boost_time_b
        after_b.guild = guild

        channel.send.reset_mock()
        await cog.on_member_update(before, after_b)
        assert channel.send.call_count == 1

    asyncio.run(_test())


def test_server_icon_none_thumbnail_empty_url_sanitized(memory_db):
    """SEC-02: Servidor sin icono no genera {'url': ''} en thumbnail ni en author/footer."""
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = _CHANNEL_ID
        channel.guild = MagicMock(id=_GUILD_ID)
        channel.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        channel.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "No Icon Guild"
        guild.icon = None  # Sin icono
        guild.member_count = 50
        guild.get_channel = MagicMock(return_value=channel)
        guild.me = MagicMock()

        member = MagicMock(spec=discord.Member)
        member.id = 111
        member.name = "member_no_icon"
        member.mention = "<@111>"
        member.display_avatar = MagicMock(url="https://cdn.discordapp.com/avatar.png")
        member.guild = guild

        embed_payload = [
            {
                "title": "Welcome {user_name}",
                "thumbnail": {"url": "{server_icon}"},
                "author": {"name": "{server_name}", "icon_url": "{server_icon}"},
                "footer": {"text": "Footer text", "icon_url": "{server_icon}"},
            }
        ]

        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="classic_embed",
            embed_json=json.dumps(embed_payload),
        )

        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is True
        assert err is None
        assert channel.send.called

        embed_sent = channel.send.call_args[1]["embeds"][0]
        # El thumbnail debe haber sido omitido en lugar de tener url=''
        assert embed_sent.thumbnail.url is None
        assert embed_sent.author.icon_url is None
        assert embed_sent.footer.icon_url is None
        assert embed_sent.author.name == "No Icon Guild"
        assert embed_sent.footer.text == "Footer text"

    import json
    asyncio.run(_test())


def test_thread_channel_support_and_webhook_identity(memory_db, monkeypatch):
    """SEC-03: Soporte para hilos (Threads) con y sin identidad personalizada."""
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        parent_channel = MagicMock(spec=discord.TextChannel)
        parent_channel.id = 1000
        parent_channel.guild = MagicMock(id=_GUILD_ID)

        thread = MagicMock(spec=discord.Thread)
        thread.id = 2000
        thread.guild = MagicMock(id=_GUILD_ID)
        thread.parent = parent_channel
        thread.archived = False
        thread.locked = False
        thread.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        thread.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "Thread Guild"
        guild.member_count = 10
        guild.get_channel = MagicMock(return_value=thread)
        guild.me = MagicMock()

        member = MagicMock(spec=discord.Member)
        member.id = 123
        member.name = "thread_user"
        member.mention = "<@123>"
        member.guild = guild

        # 1. Thread sin identidad personalizada
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=2000,
            content_mode="plain_text",
            message="Hola en hilo {user}",
        )
        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is True
        assert thread.send.called

        # 2. Thread con webhook identity
        fake_webhook = MagicMock()
        fake_webhook.send = AsyncMock()

        async def fake_resolve(b, gid, ch):
            return fake_webhook

        monkeypatch.setattr("cogs.events.send_via_webhook", AsyncMock())

        embed_payload = {
            "embeds": [{"title": "Thread Embed"}],
            "send_options": {"username": "Bot de {server_name}"},
        }
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=2000,
            content_mode="classic_embed",
            embed_json=json.dumps(embed_payload),
        )

        from cogs.events import send_via_webhook as mock_send_via_webhook
        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is True
        assert mock_send_via_webhook.called
        # Comprobar que username resolvió {server_name}
        call_kwargs = mock_send_via_webhook.call_args[1]
        assert call_kwargs["username"] == "Bot de Thread Guild"

        # 3. Thread archivado devuelve error seguro
        thread.archived = True
        import webhook_identity
        with pytest.raises(webhook_identity.WebhookIdentityError) as exc_info:
            await webhook_identity.resolve_channel_webhook(bot, _GUILD_ID, thread)
        assert "archivado" in str(exc_info.value)

    import json
    asyncio.run(_test())


def test_post_resolution_overflow_rejection(memory_db):
    """SEC-09: Si al resolver variables se superan los límites de Discord, rechazar con error explícito sin truncar."""
    async def _test():
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = ServerEvents(bot)

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = _CHANNEL_ID
        channel.guild = MagicMock(id=_GUILD_ID)
        channel.permissions_for = MagicMock(
            return_value=MagicMock(send_messages=True, embed_links=True)
        )
        channel.send = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.id = _GUILD_ID
        guild.name = "Purgito"
        guild.member_count = 10
        guild.get_channel = MagicMock(return_value=channel)
        guild.me = MagicMock()

        member = MagicMock(spec=discord.Member)
        member.id = 123
        member.name = "A" * 100
        member.mention = "<@" + ("A" * 100) + ">"
        member.guild = guild

        # 1. Plain text > 2000 chars tras expansion
        huge_raw_msg = "X" * 1950 + " {user}"
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="plain_text",
            message=huge_raw_msg,
        )

        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is False
        assert "2000 caracteres" in err
        assert not channel.send.called

        # 2. Embed description > 4096 chars tras expansion
        huge_desc = "D" * 4080 + " {user_name}"
        embed_payload = [{"title": "Title", "description": huge_desc}]
        await db.set_server_event(
            guild_id=_GUILD_ID,
            event_type="welcome",
            enabled=True,
            channel_id=_CHANNEL_ID,
            content_mode="classic_embed",
            embed_json=json.dumps(embed_payload),
        )

        ok, err = await cog.dispatch_server_event("welcome", guild, member)
        assert ok is False
        assert "límites de Discord" in err
        assert not channel.send.called

    import json
    asyncio.run(_test())
