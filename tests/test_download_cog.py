"""Comando "dl" (cogs/download.py): descarga de un video de Instagram y lo
sube al canal. Mockea _download_video por completo -- nada de red real ni
yt-dlp de verdad. Cubre la validación de dominio (solo Instagram), los tres
casos de error, y el camino feliz (manda el archivo y limpia el tmp dir).

Mismo patrón que test_mis_datos.py / test_borrar_mis_datos.py: se llama
directo a Cog.dl.callback(cog, ctx, ...) para saltear los decoradores de
cooldown/max_concurrency de discord.py.
"""

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

import cogs.download as download_mod
from cogs.download import Download, DownloadFailed, DownloadTooLarge, _is_instagram_url


class _FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeContext:
    def __init__(self, guild_filesize_limit=25 * 1024 * 1024, guild_id=1):
        self.guild = SimpleNamespace(id=guild_id, filesize_limit=guild_filesize_limit)
        self.replies: list[str] = []
        self.reply_files: list = []

    async def reply(self, content=None, *, file=None, **kwargs):
        if content is not None:
            self.replies.append(content)
        if file is not None:
            self.reply_files.append(file)

    def typing(self):
        return _FakeTyping()


@pytest.fixture(autouse=True)
def fake_locale(monkeypatch):
    async def fake_guild_locale(guild_id):
        return "es"

    monkeypatch.setattr(download_mod, "guild_locale", fake_guild_locale)


def _cog():
    return Download(SimpleNamespace())


def _fake_download_factory(seen=None):
    """Fabrica un _download_video falso que crea un archivo temporal real
    (para que discord.File(path) funcione sin mockear discord) y anota los
    argumentos con los que se lo llamó."""

    def fake(url, max_bytes):
        if seen is not None:
            seen["url"] = url
            seen["max_bytes"] = max_bytes
        tmp_dir = tempfile.mkdtemp(prefix="purgito_dl_test_")
        path = os.path.join(tmp_dir, "video.mp4")
        with open(path, "wb") as f:
            f.write(b"fake-mp4-bytes")
        return path

    return fake


# ── _is_instagram_url ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com/reel/abc123",
        "https://www.instagram.com/reel/abc123",
        "https://instagr.am/p/xyz",
        "http://m.instagram.com/p/xyz",
    ],
)
def test_is_instagram_url_acepta_hosts_validos(url):
    assert _is_instagram_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://evil.com/instagram.com",
        "https://instagram.com.evil.com/reel/abc",
        "not-a-url",
        "",
    ],
)
def test_is_instagram_url_rechaza_todo_lo_demas(url):
    assert not _is_instagram_url(url)


# ── comando dl ────────────────────────────────────────────────────────────────


def test_dl_sin_link_responde_con_instrucciones():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.dl.callback(cog, ctx, url=None))

    assert len(ctx.replies) == 1
    assert ctx.reply_files == []


def test_dl_rechaza_link_que_no_es_instagram():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.dl.callback(cog, ctx, url="https://youtube.com/watch?v=abc"))

    assert len(ctx.replies) == 1
    assert ctx.reply_files == []


def test_dl_extrae_el_link_de_un_mensaje_con_texto_alrededor(monkeypatch):
    cog = _cog()
    ctx = FakeContext()
    seen: dict = {}
    monkeypatch.setattr(download_mod, "_download_video", _fake_download_factory(seen))

    asyncio.run(
        cog.dl.callback(
            cog, ctx, url="mira este reel https://instagram.com/reel/xyz che"
        )
    )

    assert seen["url"] == "https://instagram.com/reel/xyz"
    assert len(ctx.reply_files) == 1


def test_dl_respeta_el_filesize_limit_del_guild(monkeypatch):
    cog = _cog()
    ctx = FakeContext(guild_filesize_limit=5 * 1024 * 1024)
    seen: dict = {}
    monkeypatch.setattr(download_mod, "_download_video", _fake_download_factory(seen))

    asyncio.run(cog.dl.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert seen["max_bytes"] == 5 * 1024 * 1024


def test_dl_camino_feliz_limpia_el_directorio_temporal(monkeypatch):
    cog = _cog()
    ctx = FakeContext()
    created_dirs: list[str] = []

    def fake(url, max_bytes):
        tmp_dir = tempfile.mkdtemp(prefix="purgito_dl_test_")
        created_dirs.append(tmp_dir)
        path = os.path.join(tmp_dir, "video.mp4")
        with open(path, "wb") as f:
            f.write(b"fake-mp4-bytes")
        return path

    monkeypatch.setattr(download_mod, "_download_video", fake)

    asyncio.run(cog.dl.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1
    assert not os.path.exists(created_dirs[0])


def test_dl_video_demasiado_grande(monkeypatch):
    cog = _cog()
    ctx = FakeContext()

    def fake(url, max_bytes):
        raise DownloadTooLarge(max_bytes)

    monkeypatch.setattr(download_mod, "_download_video", fake)

    asyncio.run(cog.dl.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.replies) == 1
    assert ctx.reply_files == []


def test_dl_descarga_fallida(monkeypatch):
    cog = _cog()
    ctx = FakeContext()

    def fake(url, max_bytes):
        raise DownloadFailed("privado o borrado")

    monkeypatch.setattr(download_mod, "_download_video", fake)

    asyncio.run(cog.dl.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.replies) == 1
    assert ctx.reply_files == []


def test_dl_error_generico_no_revienta_y_responde_algo(monkeypatch):
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.dl_error(ctx, ValueError("boom")))

    assert len(ctx.replies) == 1
