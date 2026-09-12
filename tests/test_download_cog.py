"""Comando "dl" (cogs/download.py): descarga de un video de Instagram,
TikTok o Twitter/X y lo sube al canal. Mockea _download_video por completo
-- nada de red real ni yt-dlp de verdad. Cubre la validación de dominio
(la allowlist, incluyendo que "t.co" quede afuera a propósito), los tres
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
import yt_dlp

import cogs.download as download_mod
from cogs.download import Download, DownloadFailed, DownloadTooLarge, _is_supported_url


class _FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeContext:
    def __init__(
        self, guild_filesize_limit=25 * 1024 * 1024, guild_id=1, channel_is_nsfw=False
    ):
        self.guild = SimpleNamespace(id=guild_id, filesize_limit=guild_filesize_limit)
        self.channel = SimpleNamespace(is_nsfw=lambda: channel_is_nsfw)
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


def _fake_download_factory(seen=None, is_sensitive=False):
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
        return path, is_sensitive

    return fake


# ── _is_supported_url ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com/reel/abc123",
        "https://www.instagram.com/reel/abc123",
        "https://instagr.am/p/xyz",
        "http://m.instagram.com/p/xyz",
        "https://tiktok.com/@user/video/123",
        "https://www.tiktok.com/@user/video/123",
        "https://vm.tiktok.com/abc123",
        "https://twitter.com/user/status/123",
        "https://x.com/user/status/123",
        "https://mobile.twitter.com/user/status/123",
    ],
)
def test_is_supported_url_acepta_hosts_validos(url):
    assert _is_supported_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://evil.com/instagram.com",
        "https://instagram.com.evil.com/reel/abc",
        # t.co es un acortador genérico de Twitter (cualquier link tuiteado
        # pasa por ahí, no solo contenido de Twitter) -- queda afuera a
        # propósito, ver el docstring del módulo.
        "https://t.co/abc123",
        "not-a-url",
        "",
    ],
)
def test_is_supported_url_rechaza_todo_lo_demas(url):
    assert not _is_supported_url(url)


# ── comando dl ────────────────────────────────────────────────────────────────


def test_dl_sin_link_responde_con_instrucciones():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.dl.callback(cog, ctx, url=None))

    assert len(ctx.replies) == 1
    assert ctx.reply_files == []


def test_dl_rechaza_link_de_sitio_no_soportado():
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
        return path, False

    monkeypatch.setattr(download_mod, "_download_video", fake)

    asyncio.run(cog.dl.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1
    assert not os.path.exists(created_dirs[0])


def test_dl_no_sube_video_sensible_fuera_de_un_canal_nsfw(monkeypatch):
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=False)
    created_dirs: list[str] = []

    def fake(url, max_bytes):
        tmp_dir = tempfile.mkdtemp(prefix="purgito_dl_test_")
        created_dirs.append(tmp_dir)
        path = os.path.join(tmp_dir, "video.mp4")
        with open(path, "wb") as f:
            f.write(b"fake-mp4-bytes")
        return path, True

    monkeypatch.setattr(download_mod, "_download_video", fake)

    asyncio.run(cog.dl.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1
    assert not os.path.exists(created_dirs[0])


def test_dl_sube_video_sensible_en_un_canal_nsfw(monkeypatch):
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=True)
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_factory(is_sensitive=True)
    )

    asyncio.run(cog.dl.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert len(ctx.reply_files) == 1
    assert ctx.replies == []


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


# ── _download_video: fallback a syndication en Twitter/X ──────────────────────
#
# X exige login vía la API graphql (la que yt-dlp usa por default sin
# cookies) para cualquier tuit marcado "sensible", aunque sea público -- ver
# el docstring de _download_video. Estos tests mockean yt_dlp.YoutubeDL
# directamente (en vez de _download_video como los de arriba) para cubrir
# ese reintento.


class _FakeYDL:
    """Registra los ydl_opts de cada instanciación en `calls` y simula
    extract_info/prepare_filename escribiendo un archivo real (para que los
    chequeos de os.path.getsize de _download_video funcionen)."""

    def __init__(self, calls, should_fail, opts, age_limit=0):
        self.calls = calls
        self.should_fail = should_fail
        self.opts = opts
        self.age_limit = age_limit
        calls.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if self.should_fail(self.opts):
            raise yt_dlp.utils.DownloadError("NSFW tweet requires authentication")
        return {"id": "vid", "age_limit": self.age_limit}

    def prepare_filename(self, info):
        tmp_dir = os.path.dirname(self.opts["outtmpl"])
        path = os.path.join(tmp_dir, "vid.mp4")
        with open(path, "wb") as f:
            f.write(b"contenido")
        return path


def _patch_ydl(monkeypatch, should_fail, age_limit=0):
    calls: list[dict] = []
    monkeypatch.setattr(
        download_mod.yt_dlp,
        "YoutubeDL",
        lambda opts: _FakeYDL(calls, should_fail, opts, age_limit),
    )
    return calls


def test_download_video_reintenta_con_syndication_si_twitter_pide_login(monkeypatch):
    calls = _patch_ydl(
        monkeypatch, should_fail=lambda opts: "extractor_args" not in opts
    )

    path, is_sensitive = download_mod._download_video(
        "https://x.com/user/status/123", 1024 * 1024
    )

    assert os.path.exists(path)
    assert is_sensitive is False
    assert len(calls) == 2
    assert "extractor_args" not in calls[0]
    assert calls[1]["extractor_args"] == {"twitter": {"api": ["syndication"]}}


def test_download_video_propaga_age_limit_como_is_sensitive(monkeypatch):
    # El tuit sensible que forzó el reintento con syndication sigue viniendo
    # marcado como tal en el info que devuelve esa API -- lo único que cambia
    # es que ya no hace falta login para leerlo.
    _patch_ydl(
        monkeypatch, should_fail=lambda opts: "extractor_args" not in opts, age_limit=18
    )

    _path, is_sensitive = download_mod._download_video(
        "https://x.com/user/status/123", 1024 * 1024
    )

    assert is_sensitive is True


def test_download_video_no_reintenta_en_sitios_que_no_son_twitter(monkeypatch):
    calls = _patch_ydl(monkeypatch, should_fail=lambda opts: True)

    with pytest.raises(DownloadFailed):
        download_mod._download_video("https://instagram.com/reel/xyz", 1024 * 1024)

    assert len(calls) == 1


def test_download_video_falla_si_syndication_tambien_falla(monkeypatch):
    calls = _patch_ydl(monkeypatch, should_fail=lambda opts: True)

    with pytest.raises(DownloadFailed):
        download_mod._download_video("https://twitter.com/user/status/123", 1024 * 1024)

    assert len(calls) == 2


def test_download_video_no_deja_directorios_temporales_al_fallar(monkeypatch):
    created_dirs: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracked_mkdtemp(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        created_dirs.append(d)
        return d

    monkeypatch.setattr(download_mod.tempfile, "mkdtemp", tracked_mkdtemp)
    _patch_ydl(monkeypatch, should_fail=lambda opts: True)

    with pytest.raises(DownloadFailed):
        download_mod._download_video("https://twitter.com/user/status/123", 1024 * 1024)

    assert len(created_dirs) == 2
    assert not any(os.path.exists(d) for d in created_dirs)
