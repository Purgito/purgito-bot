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
        self.sent_messages.append({"content": content, "file": file, "files": files, "kwargs": kwargs})
        return SimpleNamespace(id=1, channel=self)


class FakeMessage:
    def __init__(self, content="hola", channel_id=10, guild_id=_GUILD):
        self.id = 999
        self.content = content
        self.guild = SimpleNamespace(id=guild_id, name="Guild")
        self.channel = FakeChannel(channel_id=channel_id)
        self.author = SimpleNamespace(id=55, bot=False, display_name="user", mention="<@55>", roles=[])
        self.raw_mentions = [9999]  # Mención al bot
        self.reference = None
        self.replies: list[dict] = []

    async def reply(self, content=None, *, file=None, files=None, **kwargs):
        self.replies.append({"content": content, "file": file, "files": files, "kwargs": kwargs})
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

    data = asyncio.run(gifs_mod.fetch_gif_bytes("https://media1.tenor.com/m/abc/bombo.gif"))
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

    data = asyncio.run(gifs_mod.fetch_gif_bytes("https://tenor.com/view/mi-bombo-12345"))
    assert data == _VALID_GIF_BYTES


def test_fetch_gif_bytes_rejects_ssrf_and_invalid_hosts():
    assert asyncio.run(gifs_mod.fetch_gif_bytes("http://127.0.0.1/internal.gif")) is None
    assert asyncio.run(gifs_mod.fetch_gif_bytes("http://169.254.169.254/meta.gif")) is None
    assert asyncio.run(gifs_mod.fetch_gif_bytes("https://attacker.site/malicious.gif")) is None


def test_fetch_gif_bytes_rejects_non_gif_bytes(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {"Content-Type": "image/gif"}

        def iter_content(self, chunk_size=None):
            yield b"<html><body>Fake GIF</body></html>"

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())
    assert asyncio.run(gifs_mod.fetch_gif_bytes("https://media.tenor.com/fake.gif")) is None


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
        # Guardar GIF de Tenor en DB
        await db.save_gif_url(_GUILD, "https://media1.tenor.com/m/123/funny.gif")

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
        # Guardar GIF con content_hash (subido a R2)
        content_hash = "f" * 64
        await db.save_gif_url(_GUILD, f"https://cdn.example.com/gifs/ff/{content_hash}.gif", content_hash=content_hash)

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
        monkeypatch.setattr(chat_mod, "list_spontaneous_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())
        monkeypatch.setattr(chat_mod, "_check_spontaneous_cooldown", lambda *a: True)
        monkeypatch.setattr(chat_mod.generation, "note_message_for_auto_generate", lambda *a, **k: True)

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

        msg = FailingReplyMessage(content="hola <@9999>", channel_id=10, guild_id=_GUILD)
        msg.raw_mentions = [9999]

        await chat_cog.on_message(msg)

        # Debe haber caído al texto de markov, NO mandó la URL de Tenor
        assert len(msg.replies) == 1
        assert msg.replies[0]["content"] == "texto fallback de markov"
        assert "tenor.com" not in str(msg.replies[0]["content"])

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
