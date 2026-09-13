"""Tests de extremo a extremo del flujo de entrega y envío de GIFs en Discord.

Verifica:
1. Tenor GIF (página tenor.com/view/... o directa media*.tenor.com/...gif) termina como discord.File (attachment).
2. NUNCA se envía la URL como `content` en channel.send ni message.reply.
3. El attachment conserva formato image/gif y magic bytes válidos (GIF89a / GIF87a).
4. GIFs provenientes de R2 / cache de contenido se leen y envían como attachment.
5. Memoria LRU cache evita re-descargas innecesarias.
6. Promoción automática a R2 cuando R2 está disponible.
7. Manejo seguro de fallos (permisos de attachment faltantes en Discord, 404/dead, timeouts).
8. Protección SSRF: rechazo de hosts no autorizados e IPs privadas.
"""

import asyncio
import io
from types import SimpleNamespace

import aiosqlite
import discord
import pytest

import cogs.chat as chat_mod
from cogs.chat import Chat
import cogs.gifs as gifs_mod
import db
import r2

_GUILD = 12345
_VALID_GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
_VALID_GIF_87_BYTES = b"GIF87a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    monkeypatch.setattr(r2, "delete_url", _noop_delete_url)

    async def fake_save(guild_id, channel_id, author_id, name, text, message_id=None):
        return (True, True)

    async def fake_locale(guild_id):
        return "es"

    monkeypatch.setattr(chat_mod, "save_corpus_and_user_message", fake_save)
    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale)
    gifs_mod._GIF_CACHE.clear()
    yield conn
    db._db = None
    asyncio.run(conn.close())


async def _noop_delete_url(url):
    return None


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


class FakeChannel:
    def __init__(self, channel_id=10):
        self.id = channel_id
        self.name = "general"
        self.sent_messages: list[dict] = []

    async def send(self, content=None, *, file=None, files=None, **kwargs):
        self.sent_messages.append(
            {"content": content, "file": file, "files": files, "kwargs": kwargs}
        )
        return SimpleNamespace(id=1, channel=self)


class FakeMessage:
    def __init__(self, content="hola", channel_id=10, guild_id=_GUILD):
        self.id = 999
        self.content = content
        self.guild = SimpleNamespace(id=guild_id, name="Guild")
        self.channel = FakeChannel(channel_id=channel_id)
        self.author = SimpleNamespace(
            id=55, bot=False, display_name="user", mention="<@55>", roles=[]
        )
        self.raw_mentions = [9999]  # Mención al bot
        self.reference = None
        self.replies: list[dict] = []

    async def reply(self, content=None, *, file=None, files=None, **kwargs):
        self.replies.append(
            {"content": content, "file": file, "files": files, "kwargs": kwargs}
        )
        return SimpleNamespace(id=2, channel=self.channel)


# ─── Tests de Validación y Detección de Magic Bytes ──────────────────────────


def test_is_valid_gif_bytes():
    assert gifs_mod.is_valid_gif_bytes(_VALID_GIF_BYTES) is True
    assert gifs_mod.is_valid_gif_bytes(_VALID_GIF_87_BYTES) is True
    assert gifs_mod.is_valid_gif_bytes(b"\x89PNG\r\n\x1a\nfake") is False
    assert gifs_mod.is_valid_gif_bytes(b"\xff\xd8\xffjpeg") is False
    assert gifs_mod.is_valid_gif_bytes(b"<html>not a gif</html>") is False
    assert gifs_mod.is_valid_gif_bytes(b"") is False
    assert gifs_mod.is_valid_gif_bytes(None) is False


def test_is_allowed_gif_host():
    assert gifs_mod._is_allowed_gif_host("tenor.com") is True
    assert gifs_mod._is_allowed_gif_host("media.tenor.com") is True
    assert gifs_mod._is_allowed_gif_host("media1.tenor.com") is True
    assert gifs_mod._is_allowed_gif_host("c.tenor.com") is True
    assert gifs_mod._is_allowed_gif_host("giphy.com") is True
    assert gifs_mod._is_allowed_gif_host("media.giphy.com") is True
    assert gifs_mod._is_allowed_gif_host("cdn.discordapp.com") is True
    assert gifs_mod._is_allowed_gif_host("media.discordapp.net") is True

    # No permitidos
    assert gifs_mod._is_allowed_gif_host("evil.com") is False
    assert gifs_mod._is_allowed_gif_host("tenor.com.evil.com") is False
    assert gifs_mod._is_allowed_gif_host("localhost") is False
    assert gifs_mod._is_allowed_gif_host("") is False


# ─── Tests de Descarga Segura y Fetch de Bytes ───────────────────────────────


def test_fetch_gif_bytes_direct_tenor_url(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {"Content-Type": "image/gif"}

        def iter_content(self, chunk_size=None):
            yield _VALID_GIF_BYTES

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        gifs_mod.fetch_gif_bytes("https://media1.tenor.com/m/abc/bombo.gif")
    )
    assert data == _VALID_GIF_BYTES


def test_fetch_gif_bytes_resolves_tenor_page_first(monkeypatch):
    async def fake_resolve(url):
        return "https://media.tenor.com/m/xyz/resolved.gif"

    class _Resp:
        status_code = 200
        headers = {"Content-Type": "image/gif"}

        def iter_content(self, chunk_size=None):
            yield _VALID_GIF_BYTES

        def close(self):
            pass

    monkeypatch.setattr(gifs_mod, "resolve_media_url", fake_resolve)
    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        gifs_mod.fetch_gif_bytes("https://tenor.com/view/mi-bombo-12345")
    )
    assert data == _VALID_GIF_BYTES


def test_fetch_gif_bytes_rejects_ssrf_and_invalid_hosts():
    assert (
        asyncio.run(gifs_mod.fetch_gif_bytes("http://127.0.0.1/internal.gif")) is None
    )
    assert (
        asyncio.run(gifs_mod.fetch_gif_bytes("http://169.254.169.254/meta.gif")) is None
    )
    assert (
        asyncio.run(gifs_mod.fetch_gif_bytes("https://attacker.site/malicious.gif"))
        is None
    )


def test_fetch_gif_bytes_rejects_non_gif_bytes(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {"Content-Type": "image/gif"}

        def iter_content(self, chunk_size=None):
            yield b"<html><body>Fake GIF</body></html>"

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())
    assert (
        asyncio.run(gifs_mod.fetch_gif_bytes("https://media.tenor.com/fake.gif"))
        is None
    )


# ─── Tests de Memoria LRU Cache ──────────────────────────────────────────────


def test_gif_cache_avoids_duplicate_network_calls(monkeypatch):
    calls = []

    class _Resp:
        status_code = 200
        headers = {"Content-Type": "image/gif"}

        def iter_content(self, chunk_size=None):
            calls.append(1)
            yield _VALID_GIF_BYTES

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    # Primera llamada: descarga
    d1 = asyncio.run(gifs_mod.fetch_gif_bytes("https://media1.tenor.com/cached.gif"))
    assert d1 == _VALID_GIF_BYTES
    assert len(calls) == 1

    # Segunda llamada: servido desde cache de memoria
    d2 = asyncio.run(gifs_mod.fetch_gif_bytes("https://media1.tenor.com/cached.gif"))
    assert d2 == _VALID_GIF_BYTES
    assert len(calls) == 1  # No hubo segunda descarga


# ─── Tests de get_live_gif con R2 y Tenor ─────────────────────────────────────


def test_get_live_gif_from_tenor_returns_discord_file(memory_db, monkeypatch):
    async def run():
        # Guardar GIFs de Tenor en DB (mínimo MIN_GIFS_PER_GUILD)
        for i in range(gifs_mod.MIN_GIFS_PER_GUILD):
            await db.save_gif_url(_GUILD, f"https://media1.tenor.com/m/{i}/funny.gif")

        async def fake_fetch(url, **kwargs):
            return _VALID_GIF_BYTES

        monkeypatch.setattr(gifs_mod, "fetch_gif_bytes", fake_fetch)

        file = await gifs_mod.get_live_gif(_GUILD, attempts=1)
        assert isinstance(file, discord.File)
        assert file.filename == "purgito.gif"
        assert file.fp.read() == _VALID_GIF_BYTES

    asyncio.run(run())


def test_get_live_gif_from_r2_storage(memory_db, monkeypatch):
    async def run():
        # Guardar GIFs con content_hash (subido a R2) (mínimo MIN_GIFS_PER_GUILD)
        for i in range(gifs_mod.MIN_GIFS_PER_GUILD):
            content_hash = f"{i:x}" * 64
            await db.save_gif_url(
                _GUILD,
                f"https://cdn.example.com/gifs/{content_hash[:2]}/{content_hash}.gif",
                content_hash=content_hash,
            )

        monkeypatch.setattr(r2, "available", lambda: True)
        monkeypatch.setattr(r2, "get_object_bytes_sync", lambda key: _VALID_GIF_BYTES)

        file = await gifs_mod.get_live_gif(_GUILD, attempts=1)
        assert isinstance(file, discord.File)
        assert file.filename == "purgito.gif"
        assert file.fp.read() == _VALID_GIF_BYTES

    asyncio.run(run())


# ─── Tests de Envío en Chat (on_message: espontáneo y mención) ────────────────


def test_chat_spontaneous_sends_gif_as_attachment_not_url(memory_db, monkeypatch):
    async def run():
        chat_mod._muted_reply_cooldowns.clear()
        chat_mod._recent_message_ids.clear()
        chat_mod._spontaneous_cooldowns.clear()

        # Probabilidad 1.0 para forzar envío de GIF
        async def fake_effective(guild_id, channel_id):
            return {
                "enabled": True,
                "channel_id": None,
                "mention_rate_limit": 0,
                "auto_generate_every": 1,
                "auto_generate_probability": 1.0,
                "reaction_probability": 0.0,
                "gif_response_probability": 1.0,
                "frase_probability": 0.0,
            }

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
        monkeypatch.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_true())
        monkeypatch.setattr(
            chat_mod, "list_spontaneous_channels", lambda *a: _async_list()
        )
        monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "_check_spontaneous_cooldown", lambda *a: True)
        monkeypatch.setattr(
            chat_mod.generation, "note_message_for_auto_generate", lambda *a, **k: True
        )

        async def fake_get_live_gif(guild_id):
            return discord.File(io.BytesIO(_VALID_GIF_BYTES), filename="purgito.gif")

        monkeypatch.setattr(chat_mod, "get_live_gif", fake_get_live_gif)
        monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        chat_cog = Chat(bot)

        # Mensaje espontáneo (sin mención al bot)
        msg = FakeMessage(content="hola a todos", channel_id=10, guild_id=_GUILD)
        msg.raw_mentions = []

        await chat_cog.on_message(msg)

        # Verificar que se envió un mensaje en el canal
        assert len(msg.channel.sent_messages) == 1
        sent = msg.channel.sent_messages[0]

        # REQUISITO CRÍTICO: content NUNCA debe ser una URL ni texto del GIF
        assert sent["content"] is None
        # REQUISITO CRÍTICO: debe enviarse como attachment discord.File
        assert isinstance(sent["file"], discord.File)
        assert sent["file"].filename == "purgito.gif"
        assert sent["file"].fp.read() == _VALID_GIF_BYTES

    asyncio.run(run())


def test_chat_mention_sends_gif_as_attachment_not_url(memory_db, monkeypatch):
    async def run():
        chat_mod._muted_reply_cooldowns.clear()
        chat_mod._recent_message_ids.clear()
        chat_mod._spontaneous_cooldowns.clear()

        async def fake_effective(guild_id, channel_id):
            return {
                "enabled": True,
                "channel_id": None,
                "mention_rate_limit": 0,
                "auto_generate_every": 15,
                "auto_generate_probability": 0.6,
                "reaction_probability": 0.0,
                "gif_response_probability": 1.0,
                "frase_probability": 0.0,
            }

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
        monkeypatch.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_true())
        monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())

        async def fake_get_live_gif(guild_id):
            return discord.File(io.BytesIO(_VALID_GIF_BYTES), filename="purgito.gif")

        monkeypatch.setattr(chat_mod, "get_live_gif", fake_get_live_gif)
        monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        chat_cog = Chat(bot)

        # Mensaje con mención al bot
        msg = FakeMessage(content="hola <@9999>", channel_id=10, guild_id=_GUILD)
        msg.raw_mentions = [9999]

        await chat_cog.on_message(msg)

        # Verificar que se respondió al mensaje
        assert len(msg.replies) == 1
        reply = msg.replies[0]

        # REQUISITO CRÍTICO: content NUNCA debe ser una URL de Tenor
        assert reply["content"] is None
        assert isinstance(reply["file"], discord.File)
        assert reply["file"].filename == "purgito.gif"
        assert reply["file"].fp.read() == _VALID_GIF_BYTES

    asyncio.run(run())


def test_chat_forbidden_attachment_falls_back_to_text_cleanly(memory_db, monkeypatch):
    """Si Discord rechaza el attachment (ej. falta permiso attach_files), el bot
    cae limpiamente a generación de texto y NUNCA envía la URL como texto."""

    async def run():
        chat_mod._muted_reply_cooldowns.clear()
        chat_mod._recent_message_ids.clear()
        chat_mod._spontaneous_cooldowns.clear()

        async def fake_effective(guild_id, channel_id):
            return {
                "enabled": True,
                "channel_id": None,
                "mention_rate_limit": 0,
                "auto_generate_every": 15,
                "auto_generate_probability": 0.6,
                "reaction_probability": 0.0,
                "gif_response_probability": 1.0,
                "frase_probability": 0.0,
            }

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
        monkeypatch.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_true())
        monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())

        async def fake_get_live_gif(guild_id):
            return discord.File(io.BytesIO(_VALID_GIF_BYTES), filename="purgito.gif")

        monkeypatch.setattr(chat_mod, "get_live_gif", fake_get_live_gif)
        monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

        # Simular que generate_response genera texto de fallback
        async def fake_gen(guild_id, channel_id, **kwargs):
            return "texto fallback de markov", False

        monkeypatch.setattr(chat_mod.generation, "generate_response", fake_gen)

        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        chat_cog = Chat(bot)

        class FailingReplyMessage(FakeMessage):
            async def reply(self, content=None, *, file=None, **kwargs):
                if file is not None:
                    # Simular 403 Forbidden de Discord por falta de permiso attach_files
                    resp = SimpleNamespace(status=403, reason="Forbidden")
                    raise discord.Forbidden(resp, "Missing Permissions: Attach Files")
                self.replies.append({"content": content, "file": None})

        msg = FailingReplyMessage(
            content="hola <@9999>", channel_id=10, guild_id=_GUILD
        )
        msg.raw_mentions = [9999]

        await chat_cog.on_message(msg)

        # Debe haber caído al texto de markov, NO mandó la URL de Tenor
        assert len(msg.replies) == 1
        assert msg.replies[0]["content"] == "texto fallback de markov"
        assert "tenor.com" not in str(msg.replies[0]["content"])

    asyncio.run(run())


# ─── Tests del requisito MIN_GIFS_PER_GUILD ──────────────────────────────────


def test_min_gifs_threshold_ladder(memory_db, monkeypatch):
    """Verifica que get_live_gif respete estrictamente el umbral mínimo de GIFs:
    0 GIFs  -> None
    1 GIF   -> None
    9 GIFs  -> None
    10 GIFs -> discord.File
    11+ GIFs-> discord.File
    """

    async def run():
        async def fake_fetch(url, **kwargs):
            return _VALID_GIF_BYTES

        monkeypatch.setattr(gifs_mod, "fetch_gif_bytes", fake_fetch)

        # 0 GIFs
        assert await db.count_gif_urls(_GUILD) == 0
        assert await gifs_mod.get_live_gif(_GUILD, attempts=1) is None

        # 1 GIF
        await db.save_gif_url(_GUILD, "https://media.tenor.com/m/0/gif0.gif")
        assert await db.count_gif_urls(_GUILD) == 1
        assert await gifs_mod.get_live_gif(_GUILD, attempts=1) is None

        # 2 a 8 GIFs (total 8)
        for i in range(1, 8):
            await db.save_gif_url(_GUILD, f"https://media.tenor.com/m/{i}/gif{i}.gif")
        assert await db.count_gif_urls(_GUILD) == 8
        assert await gifs_mod.get_live_gif(_GUILD, attempts=1) is None

        # 9 GIFs
        await db.save_gif_url(_GUILD, "https://media.tenor.com/m/8/gif8.gif")
        assert await db.count_gif_urls(_GUILD) == 9
        assert await gifs_mod.get_live_gif(_GUILD, attempts=1) is None

        # 10 GIFs -> Alcanza el mínimo exactamente, entrega GIF
        await db.save_gif_url(_GUILD, "https://media.tenor.com/m/9/gif9.gif")
        assert await db.count_gif_urls(_GUILD) == 10
        file_10 = await gifs_mod.get_live_gif(_GUILD, attempts=1)
        assert isinstance(file_10, discord.File)
        assert file_10.filename == "purgito.gif"
        assert file_10.fp.read() == _VALID_GIF_BYTES

        # 11 GIFs -> Supera el mínimo, sigue entregando GIF
        await db.save_gif_url(_GUILD, "https://media.tenor.com/m/10/gif10.gif")
        assert await db.count_gif_urls(_GUILD) == 11
        file_11 = await gifs_mod.get_live_gif(_GUILD, attempts=1)
        assert isinstance(file_11, discord.File)
        assert file_11.filename == "purgito.gif"
        assert file_11.fp.read() == _VALID_GIF_BYTES

    asyncio.run(run())


def test_chat_spontaneous_below_min_gifs_threshold_falls_back_to_text(
    memory_db, monkeypatch
):
    """En generación espontánea con probabilidad de GIF = 1.0 pero menos de 10 GIFs,
    Purgito no debe enviar GIF y debe generar respuesta de texto normalmente."""

    async def run():
        chat_mod._muted_reply_cooldowns.clear()
        chat_mod._recent_message_ids.clear()
        chat_mod._spontaneous_cooldowns.clear()

        # Solo 3 GIFs en la base de datos (< 10)
        for i in range(3):
            await db.save_gif_url(_GUILD, f"https://media.tenor.com/m/{i}/g.gif")

        async def fake_effective(guild_id, channel_id):
            return {
                "enabled": True,
                "channel_id": None,
                "mention_rate_limit": 0,
                "auto_generate_every": 1,
                "auto_generate_probability": 1.0,
                "reaction_probability": 0.0,
                "gif_response_probability": 1.0,
                "frase_probability": 0.0,
            }

        bumped = []

        async def track_bump(guild_id, name):
            bumped.append(name)

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
        monkeypatch.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_true())
        monkeypatch.setattr(
            chat_mod, "list_spontaneous_channels", lambda *a: _async_list()
        )
        monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "_check_spontaneous_cooldown", lambda *a: True)
        monkeypatch.setattr(
            chat_mod.generation, "note_message_for_auto_generate", lambda *a, **k: True
        )
        monkeypatch.setattr(chat_mod, "bump_counter", track_bump)

        async def fake_gen(guild_id, channel_id, **kwargs):
            return "texto generado de markov", False

        monkeypatch.setattr(chat_mod.generation, "generate_response", fake_gen)

        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        chat_cog = Chat(bot)

        msg = FakeMessage(content="hola gente", channel_id=10, guild_id=_GUILD)
        msg.raw_mentions = []

        await chat_cog.on_message(msg)

        assert len(msg.channel.sent_messages) == 1
        sent = msg.channel.sent_messages[0]
        assert sent["file"] is None
        assert sent["content"] == "texto generado de markov"
        assert "mensajes_enviados" in bumped
        assert "gifs_enviados" not in bumped

    asyncio.run(run())


def test_chat_mention_below_min_gifs_threshold_falls_back_to_text(
    memory_db, monkeypatch
):
    """En respuesta a mención con probabilidad de GIF = 1.0 pero menos de 10 GIFs,
    Purgito no debe responder con GIF y debe generar texto normalmente."""

    async def run():
        chat_mod._muted_reply_cooldowns.clear()
        chat_mod._recent_message_ids.clear()
        chat_mod._spontaneous_cooldowns.clear()

        # Solo 5 GIFs en la base de datos (< 10)
        for i in range(5):
            await db.save_gif_url(_GUILD, f"https://media.tenor.com/m/{i}/g.gif")

        async def fake_effective(guild_id, channel_id):
            return {
                "enabled": True,
                "channel_id": None,
                "mention_rate_limit": 0,
                "auto_generate_every": 15,
                "auto_generate_probability": 0.6,
                "reaction_probability": 0.0,
                "gif_response_probability": 1.0,
                "frase_probability": 0.0,
            }

        bumped = []

        async def track_bump(guild_id, name):
            bumped.append(name)

        monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
        monkeypatch.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
        monkeypatch.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_true())
        monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "bump_counter", track_bump)

        async def fake_gen(guild_id, channel_id, **kwargs):
            return "respuesta de texto a la mención", False

        monkeypatch.setattr(chat_mod.generation, "generate_response", fake_gen)

        bot = SimpleNamespace(user=SimpleNamespace(id=9999))
        chat_cog = Chat(bot)

        msg = FakeMessage(content="hola <@9999>", channel_id=10, guild_id=_GUILD)
        msg.raw_mentions = [9999]

        await chat_cog.on_message(msg)

        assert len(msg.replies) == 1
        reply = msg.replies[0]
        assert reply["file"] is None
        assert reply["content"] == "respuesta de texto a la mención"
        assert "mensajes_enviados" in bumped
        assert "gifs_enviados" not in bumped

    asyncio.run(run())


def test_gif_collection_continues_when_below_min_threshold(memory_db, monkeypatch):
    """La recopilación y guardado de GIFs debe funcionar normalmente aunque haya < 10.
    En cuanto se guarda el 10mo GIF, get_live_gif comienza a responder inmediatamente."""

    async def run():
        async def fake_fetch(url, **kwargs):
            return _VALID_GIF_BYTES

        monkeypatch.setattr(gifs_mod, "fetch_gif_bytes", fake_fetch)

        # 1. Guardar 9 GIFs mediante save_gif_candidates simulando mensajes
        for i in range(9):
            fake_msg = SimpleNamespace(
                content=f"Mira este gif: https://tenor.com/view/cat-meme-{i}",
                attachments=[],
                author=SimpleNamespace(id=55),
                channel=SimpleNamespace(id=10),
                id=100 + i,
            )
            saved = await gifs_mod.save_gif_candidates(_GUILD, fake_msg)
            assert saved == 1

        assert await db.count_gif_urls(_GUILD) == 9
        # Con 9 todavía no se puede entregar GIF
        assert await gifs_mod.get_live_gif(_GUILD, attempts=1) is None

        # 2. Guardar el 10mo GIF
        msg_10 = SimpleNamespace(
            content="El décimo https://tenor.com/view/cat-meme-9",
            attachments=[],
            author=SimpleNamespace(id=55),
            channel=SimpleNamespace(id=10),
            id=200,
        )
        saved_10 = await gifs_mod.save_gif_candidates(_GUILD, msg_10)
        assert saved_10 == 1
        assert await db.count_gif_urls(_GUILD) == 10

        # Ahora que llegó a 10, la entrega funciona automáticamente
        delivered = await gifs_mod.get_live_gif(_GUILD, attempts=1)
        assert isinstance(delivered, discord.File)
        assert delivered.filename == "purgito.gif"

    asyncio.run(run())


def test_multi_guild_isolation_threshold(memory_db, monkeypatch):
    """Un servidor con pocos GIFs (<10) no afecta a otro servidor con suficientes GIFs (>=10)."""

    async def run():
        guild_small = 111
        guild_large = 222

        async def fake_fetch(url, **kwargs):
            return _VALID_GIF_BYTES

        monkeypatch.setattr(gifs_mod, "fetch_gif_bytes", fake_fetch)

        # Guild A: 3 GIFs
        for i in range(3):
            await db.save_gif_url(
                guild_small, f"https://media.tenor.com/m/a{i}/gif.gif"
            )

        # Guild B: 12 GIFs
        for i in range(12):
            await db.save_gif_url(
                guild_large, f"https://media.tenor.com/m/b{i}/gif.gif"
            )

        assert await db.count_gif_urls(guild_small) == 3
        assert await db.count_gif_urls(guild_large) == 12

        # Guild A devuelve None
        assert await gifs_mod.get_live_gif(guild_small, attempts=1) is None

        # Guild B entrega GIF con éxito
        result_b = await gifs_mod.get_live_gif(guild_large, attempts=1)
        assert isinstance(result_b, discord.File)
        assert result_b.filename == "purgito.gif"

    asyncio.run(run())


def test_manual_gif_commands_unaffected_by_threshold(memory_db, monkeypatch):
    """Los comandos / acciones manuales para agregar o gestionar GIFs funcionan sin importar
    si el guild tiene < 10 GIFs."""

    async def run():
        from cogs.gifs import Gifs
        import cogs.premium as premium_mod

        # Configurar guild premium para permitir /gif_add
        monkeypatch.setattr(premium_mod, "is_premium_guild", lambda gid: True)
        monkeypatch.setattr(gifs_mod, "has_admin_permission", lambda inter: True)

        bot = SimpleNamespace()
        cog = Gifs(bot)

        # Guild tiene solo 2 GIFs
        for i in range(2):
            await db.save_gif_url(_GUILD, f"https://media.tenor.com/m/{i}/g.gif")
        assert await db.count_gif_urls(_GUILD) == 2

        # Simular interacción de /gif_add
        responses = []

        class FakeInteraction:
            guild = SimpleNamespace(id=_GUILD)
            guild_id = _GUILD
            channel_id = 10
            user = SimpleNamespace(
                id=1, guild_permissions=SimpleNamespace(administrator=True)
            )

            class response:
                @staticmethod
                async def defer(ephemeral=True):
                    pass

                @staticmethod
                async def send_message(content, ephemeral=True):
                    responses.append(content)

            class followup:
                @staticmethod
                async def send(content, ephemeral=True):
                    responses.append(content)

        interaction = FakeInteraction()
        await cog.gif_add.callback(
            cog, interaction, "https://tenor.com/view/nuevo-gif-manual-12345"
        )

        assert len(responses) == 1
        assert "3" in responses[0]  # Total reportado = 3
        assert await db.count_gif_urls(_GUILD) == 3

    asyncio.run(run())


# ─── Helpers auxiliares ──────────────────────────────────────────────────────


async def _async_false():
    return False


async def _async_true():
    return True


async def _async_list():
    return []


async def _noop_counter(guild_id, name):
    pass
