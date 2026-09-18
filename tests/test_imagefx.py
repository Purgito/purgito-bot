"""Filtros de imagen tipo NotSoBot (Fases 1, 2 y 4): image_filters.py y
video_filters.py (funciones puras) y cogs/imagefx.py (resolución de la
imagen/GIF/video fuente + comandos).

Mismo patrón que test_download_cog.py: se llama directo a
Cog.<comando>.callback(cog, ctx, ...) para saltear los decoradores de
discord.py, con un FakeContext basado en SimpleNamespace.
"""

import asyncio
import io
import os
import subprocess
import tempfile
from types import SimpleNamespace

import discord
import imageio_ffmpeg
import pytest
from PIL import Image, ImageDraw, ImageSequence

import cogs.download as download_mod
import cogs.imagefx as imagefx_mod
import image_filters
import r2
import video_filters
from cogs.imagefx import (
    _GIF_EXTS,
    _IMAGE_EXTS,
    _VIDEO_EXTS,
    ImageFx,
    SourceTooLarge,
    _find_attachment,
    _resolve_gif_bytes,
    _resolve_image_bytes,
    _resolve_video_bytes,
)


def _png_bytes(size=(200, 120), color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _png_bytes_with_shape(size=(200, 120)) -> bytes:
    """A diferencia de _png_bytes, no es un color plano -- necesario para
    probar cosas como triggered() donde un recorte desplazado de una imagen
    de un solo color da bytes idénticos sin importar el desplazamiento."""
    img = Image.new("RGB", size, (10, 120, 200))
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.ellipse((w * 0.2, h * 0.2, w * 0.8, h * 0.8), fill=(250, 200, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gif_bytes(colors=((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))) -> bytes:
    """GIF animado real con frames de colores distintos (para poder verificar
    orden/cantidad de frames, no solo que el archivo "no rompe")."""
    frames = [Image.new("RGB", (40, 40), c) for c in colors]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0
    )
    return buf.getvalue()


def _make_test_video_bytes(duration=0.5, size="64x64", fps=8) -> bytes:
    """Video real y chico generado con el mismo binario de ffmpeg que
    convert_video_to_gif usa en producción (imageio-ffmpeg) -- así el test de
    integración de "!gif" no depende de ningún archivo de fixture ni de red."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size={size}:rate={fps}",
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return proc.stdout


# ── image_filters: los filtros de imagen estática no rompen y devuelven una
# imagen válida (todos menos triggered, que devuelve un GIF -- ver más abajo) ─

_ALL_FILTERS = [
    (image_filters.caption, ("ARRIBA|ABAJO",)),
    (image_filters.deepfry, ()),
    (image_filters.wide, ()),
    (image_filters.squish, ()),
    (image_filters.invert, ()),
    (image_filters.greyscale, ()),
    (image_filters.sepia, ()),
    (image_filters.pixelate, ()),
    (image_filters.rotate, ()),
    (image_filters.flip, ()),
    (image_filters.flop, ()),
    (image_filters.circle, ()),
    (image_filters.blur, ()),
    (image_filters.sharpen, ()),
    (image_filters.wasted, ()),
    (image_filters.trash, ()),
    (image_filters.communism, ()),
    (image_filters.gay, ()),
    (image_filters.jail, ()),
    (image_filters.wanted, ()),
    (image_filters.rip, ()),
    (image_filters.america, ()),
    (image_filters.polaroid, ()),
    (image_filters.poster, ()),
    (image_filters.threshold, ()),
    (image_filters.emboss, ()),
]


@pytest.mark.parametrize(
    "fn,args", _ALL_FILTERS, ids=[fn.__name__ for fn, _ in _ALL_FILTERS]
)
def test_filtro_devuelve_png_valido(fn, args):
    out = fn(_png_bytes(), *args)
    with Image.open(io.BytesIO(out)) as img:
        img.load()
        assert img.format == "PNG"
        assert img.size[0] > 0 and img.size[1] > 0


def test_caption_sin_separador_no_rompe():
    # Sin "|" todo el texto es la parte de "arriba" -- no debe intentar
    # dibujar una parte de abajo vacía.
    out = image_filters.caption(_png_bytes(), "SOLO ARRIBA")
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (200, 120)


def test_wide_estira_solo_el_ancho():
    out = image_filters.wide(_png_bytes(size=(200, 120)), factor=2.0)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (400, 120)


def test_squish_comprime_solo_el_ancho():
    out = image_filters.squish(_png_bytes(size=(200, 120)), factor=0.5)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (100, 120)


@pytest.mark.parametrize("factor", [100.0, 0.001, -5.0])
def test_wide_clampea_factores_extremos(factor):
    out = image_filters.wide(_png_bytes(size=(200, 120)), factor=factor)
    with Image.open(io.BytesIO(out)) as img:
        # 4.0 es el tope; nunca debería generar algo desproporcionado.
        assert img.size[0] <= 200 * 4.0


def test_rotate_90_intercambia_ancho_y_alto():
    out = image_filters.rotate(_png_bytes(size=(200, 120)), degrees=90)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (120, 200)
        assert img.mode == "RGBA"


def test_rotate_acepta_grados_fuera_de_0_360():
    # 450 % 360 == 90 -- mismo resultado que test_rotate_90_intercambia...
    out = image_filters.rotate(_png_bytes(size=(200, 120)), degrees=450)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (120, 200)


def test_circle_recorta_las_esquinas_transparentes():
    out = image_filters.circle(_png_bytes(size=(200, 120)))
    with Image.open(io.BytesIO(out)) as img:
        assert img.mode == "RGBA"
        w, h = img.size
        assert w == h  # se recorta a cuadrado antes de aplicar la máscara
        assert img.getpixel((0, 0))[3] == 0  # esquina: transparente
        assert img.getpixel((w // 2, h // 2))[3] == 255  # centro: opaco


def test_triggered_devuelve_gif_animado():
    out = image_filters.triggered(_png_bytes_with_shape())
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "GIF"
        assert img.is_animated
        assert img.n_frames >= 2


def test_threshold_solo_produce_negro_o_blanco():
    out = image_filters.threshold(_png_bytes(), level=128)
    with Image.open(io.BytesIO(out)) as img:
        colors = {
            img.convert("RGB").getpixel((x, y))
            for x in (0, img.width - 1)
            for y in (0, img.height - 1)
        }
        assert colors <= {(0, 0, 0), (255, 255, 255)}


def test_polaroid_agrega_marco_mas_grueso_abajo():
    w, h = 200, 120
    out = image_filters.polaroid(_png_bytes(size=(w, h)))
    with Image.open(io.BytesIO(out)) as img:
        side_border = (img.width - w) // 2
        bottom_border = img.height - h - side_border
        assert bottom_border > side_border


# ── image_filters: edición de un GIF existente (Fase 4) ──────────────────────


def test_gif_caption_devuelve_gif_con_la_misma_cantidad_de_frames():
    out = image_filters.gif_caption(_gif_bytes(), "ARRIBA|ABAJO")
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "GIF"
        assert img.n_frames == 4


def test_gif_speed_acelera_reduce_la_duracion_de_cada_frame():
    out = image_filters.gif_speed(_gif_bytes(), factor=2.0)
    with Image.open(io.BytesIO(out)) as img:
        durations = [f.info.get("duration") for f in ImageSequence.Iterator(img)]
        assert all(d == 50 for d in durations)  # 100 / 2.0


def test_gif_reverse_invierte_el_orden_de_los_frames():
    out = image_filters.gif_reverse(_gif_bytes())
    with Image.open(io.BytesIO(out)) as img:
        first_pixel = img.convert("RGB").getpixel((0, 0))
        assert first_pixel == (255, 255, 0)  # último color de _gif_bytes


def test_gif_wide_estira_todos_los_frames():
    out = image_filters.gif_wide(_gif_bytes(), factor=2.0)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (80, 40)
        assert img.n_frames == 4


# ── video_filters: conversión de video a GIF (Fase 4) ────────────────────────


def test_convert_video_to_gif_produce_un_gif_animado():
    video_bytes = _make_test_video_bytes(duration=0.6, fps=10)

    out = video_filters.convert_video_to_gif(
        video_bytes, max_seconds=2.0, max_output_bytes=5 * 1024 * 1024
    )

    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "GIF"
        assert img.is_animated
        assert img.n_frames >= 2


def test_convert_video_to_gif_trunca_a_max_seconds():
    video_bytes = _make_test_video_bytes(duration=3.0, fps=10)

    out = video_filters.convert_video_to_gif(
        video_bytes, max_seconds=0.5, max_output_bytes=5 * 1024 * 1024
    )

    with Image.open(io.BytesIO(out)) as img:
        # A 10fps, 3s enteros serían ~30 frames -- truncado a 0.5s da ~5.
        assert img.n_frames < 15


def test_convert_video_to_gif_rechaza_salida_demasiado_grande():
    video_bytes = _make_test_video_bytes(duration=0.5)

    with pytest.raises(video_filters.GifTooLarge):
        video_filters.convert_video_to_gif(
            video_bytes, max_seconds=1.0, max_output_bytes=10
        )


def test_convert_video_to_gif_rechaza_contenido_invalido():
    with pytest.raises(video_filters.VideoConversionFailed):
        video_filters.convert_video_to_gif(
            b"esto no es un video", max_seconds=1.0, max_output_bytes=5 * 1024 * 1024
        )


# ── cogs/imagefx.py: resolución de la imagen fuente ──────────────────────────


class FakeAttachment:
    def __init__(self, filename="foto.png", size=1024, data=b"fake"):
        self.filename = filename
        self.size = size
        self._data = data

    async def read(self):
        return self._data


class FakeAvatarAsset:
    def __init__(self, data: bytes):
        self._data = data

    def with_static_format(self, _fmt):
        return self

    async def read(self):
        return self._data


class FakeAuthor:
    def __init__(self, user_id=1, avatar_bytes: bytes | None = None):
        self.id = user_id
        self.display_avatar = FakeAvatarAsset(avatar_bytes or _png_bytes())


class _FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeContext:
    def __init__(
        self,
        attachments=None,
        reference=None,
        author=None,
        guild_id=1,
        guild_filesize_limit=25 * 1024 * 1024,
        channel_is_nsfw=False,
        own_embeds=None,
    ):
        self.guild = (
            SimpleNamespace(id=guild_id, filesize_limit=guild_filesize_limit)
            if guild_id is not None
            else None
        )
        self.author = author or FakeAuthor()
        self.message = SimpleNamespace(
            attachments=attachments or [], reference=reference, embeds=own_embeds or []
        )
        self.channel = SimpleNamespace(
            fetch_message=self._fetch_message, is_nsfw=lambda: channel_is_nsfw
        )
        self.command = "fake_command"
        self.replies: list[str] = []
        self.reply_files: list = []
        self._fetch_message_result = None

    async def reply(self, content=None, *, file=None, **kwargs):
        if content is not None:
            self.replies.append(content)
        if file is not None:
            self.reply_files.append(file)

    async def _fetch_message(self, message_id):
        if self._fetch_message_result is None:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "")
        return self._fetch_message_result

    def typing(self):
        return _FakeTyping()


@pytest.fixture(autouse=True)
def fake_locale(monkeypatch):
    async def fake_guild_locale(guild_id):
        return "es"

    monkeypatch.setattr(imagefx_mod, "guild_locale", fake_guild_locale)


@pytest.fixture(autouse=True)
def reset_cooldowns():
    # _fx_cooldowns es compartido por todos los comandos del cog (a propósito,
    # ver el comentario junto a _check_fx_cooldown) -- y también entre tests,
    # así que hay que limpiarlo para que no interfieran entre sí. Mismo motivo
    # para _gif_convert_cooldowns, el pool aparte de "!gif".
    imagefx_mod._fx_cooldowns.clear()
    imagefx_mod._gif_convert_cooldowns.clear()
    yield
    imagefx_mod._fx_cooldowns.clear()
    imagefx_mod._gif_convert_cooldowns.clear()


def _cog():
    return ImageFx(SimpleNamespace())


def test_find_attachment_usa_el_adjunto_propio():
    ctx = FakeContext(attachments=[FakeAttachment(data=b"propio")])

    attachment = asyncio.run(_find_attachment(ctx, _IMAGE_EXTS))

    assert attachment is not None
    assert asyncio.run(attachment.read()) == b"propio"


def test_find_attachment_ignora_extensiones_no_soportadas():
    ctx = FakeContext(attachments=[FakeAttachment(filename="video.mp4")])

    assert asyncio.run(_find_attachment(ctx, _IMAGE_EXTS)) is None


def test_find_attachment_respeta_el_set_de_extensiones_pedido():
    # Mismo helper que usan los filtros de imagen, pero para GIFs y videos --
    # generalizado en la Fase 4 para no triplicar la lógica de reply/fetch.
    ctx = FakeContext(
        attachments=[
            FakeAttachment(filename="foto.png", data=b"imagen"),
            FakeAttachment(filename="animado.gif", data=b"gif"),
        ]
    )

    gif_attachment = asyncio.run(_find_attachment(ctx, _GIF_EXTS))
    video_attachment = asyncio.run(_find_attachment(ctx, _VIDEO_EXTS))

    assert asyncio.run(gif_attachment.read()) == b"gif"
    assert video_attachment is None


def test_find_attachment_usa_el_adjunto_del_mensaje_respondido():
    referenced = SimpleNamespace(attachments=[FakeAttachment(data=b"del reply")])
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    attachment = asyncio.run(_find_attachment(ctx, _IMAGE_EXTS))

    assert asyncio.run(attachment.read()) == b"del reply"


def test_find_attachment_prioriza_el_adjunto_propio_sobre_el_reply():
    referenced = SimpleNamespace(attachments=[FakeAttachment(data=b"del reply")])
    ctx = FakeContext(
        attachments=[FakeAttachment(data=b"propio")],
        reference=SimpleNamespace(resolved=referenced, message_id=1),
    )

    attachment = asyncio.run(_find_attachment(ctx, _IMAGE_EXTS))

    assert asyncio.run(attachment.read()) == b"propio"


def test_find_attachment_ignora_reply_borrado():
    ctx = FakeContext(
        reference=SimpleNamespace(
            resolved=discord.DeletedReferencedMessage(SimpleNamespace()), message_id=1
        )
    )

    assert asyncio.run(_find_attachment(ctx, _IMAGE_EXTS)) is None


def test_find_attachment_busca_con_fetch_si_el_reply_no_esta_en_cache():
    ctx = FakeContext(reference=SimpleNamespace(resolved=None, message_id=42))
    ctx._fetch_message_result = SimpleNamespace(
        attachments=[FakeAttachment(data=b"fetch")]
    )

    attachment = asyncio.run(_find_attachment(ctx, _IMAGE_EXTS))

    assert asyncio.run(attachment.read()) == b"fetch"


def test_resolve_image_bytes_usa_el_avatar_si_no_hay_adjunto():
    ctx = FakeContext(author=FakeAuthor(avatar_bytes=b"avatar-bytes"))

    data = asyncio.run(_resolve_image_bytes(ctx))

    assert data == b"avatar-bytes"


def test_resolve_image_bytes_rechaza_adjunto_demasiado_grande():
    ctx = FakeContext(attachments=[FakeAttachment(size=999_999_999)])

    with pytest.raises(SourceTooLarge):
        asyncio.run(_resolve_image_bytes(ctx))


def test_resolve_gif_bytes_sin_adjunto_ni_reply_devuelve_none():
    # A diferencia de _resolve_image_bytes, acá no hay fallback a avatar.
    ctx = FakeContext()

    assert asyncio.run(_resolve_gif_bytes(ctx)) is None


def test_resolve_gif_bytes_usa_el_adjunto_gif():
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=b"un gif")])

    data = asyncio.run(_resolve_gif_bytes(ctx))

    assert data == b"un gif"


def test_resolve_gif_bytes_rechaza_adjunto_demasiado_grande():
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", size=999_999_999)])

    with pytest.raises(SourceTooLarge):
        asyncio.run(_resolve_gif_bytes(ctx))


def test_resolve_video_bytes_sin_adjunto_ni_reply_devuelve_none():
    ctx = FakeContext()

    assert asyncio.run(_resolve_video_bytes(ctx)) is None


def test_resolve_video_bytes_usa_el_adjunto_de_video():
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=b"un video")]
    )

    data = asyncio.run(_resolve_video_bytes(ctx))

    assert data == b"un video"


def test_resolve_video_bytes_rechaza_adjunto_demasiado_grande():
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", size=999_999_999)]
    )

    with pytest.raises(SourceTooLarge):
        asyncio.run(_resolve_video_bytes(ctx))


def test_find_attachment_detecta_video_por_content_type_aunque_la_extension_no_matchee():
    # Ej. .mkv no está en _VIDEO_EXTS pero algunos clientes lo suben con
    # content_type="video/x-matroska" -- mismo patrón de fallback por
    # content-type que ya usa save_gif_candidates en cogs/gifs.py.
    attachment = FakeAttachment(filename="clip.mkv", data=b"video raro")
    attachment.content_type = "video/x-matroska"
    ctx = FakeContext(attachments=[attachment])

    found = asyncio.run(
        _find_attachment(ctx, _VIDEO_EXTS, content_type_prefix="video/")
    )

    assert found is not None
    assert asyncio.run(found.read()) == b"video raro"


def test_find_attachment_content_type_no_afecta_a_quien_no_lo_pide():
    # _resolve_image_bytes/_resolve_gif_bytes no pasan content_type_prefix --
    # un adjunto con extensión no soportada sigue sin matchear aunque su
    # content_type diga "video/...".
    attachment = FakeAttachment(filename="clip.mkv", data=b"video raro")
    attachment.content_type = "video/x-matroska"
    ctx = FakeContext(attachments=[attachment])

    assert asyncio.run(_find_attachment(ctx, _VIDEO_EXTS)) is None


def test_resolve_video_bytes_usa_el_video_embebido_del_mensaje_respondido(monkeypatch):
    # Ej. NotSoBot reposteando su resultado como embed con Embed.video, no
    # como adjunto de Discord -- ver docstring de _resolve_video_bytes.
    async def fake_fetch(url, max_bytes):
        assert url == "https://cdn.discordapp.com/attachments/1/2/clip.mp4"
        assert max_bytes == imagefx_mod.MAX_GIF_SOURCE_VIDEO_BYTES
        return b"video del embed"

    monkeypatch.setattr(download_mod, "_fetch_direct_video_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/clip.mp4"
                )
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    data = asyncio.run(_resolve_video_bytes(ctx))

    assert data == b"video del embed"


def test_resolve_video_bytes_prioriza_el_adjunto_sobre_el_video_embebido(monkeypatch):
    async def fake_fetch(url, max_bytes):
        raise AssertionError("no debería llamarse: hay un adjunto de video")

    monkeypatch.setattr(download_mod, "_fetch_direct_video_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://cdn.discordapp.com/x.mp4")
            )
        ],
    )
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=b"adjunto propio")],
        reference=SimpleNamespace(resolved=referenced, message_id=1),
    )

    data = asyncio.run(_resolve_video_bytes(ctx))

    assert data == b"adjunto propio"


def test_resolve_video_bytes_ignora_embed_sin_video():
    referenced = SimpleNamespace(attachments=[], embeds=[SimpleNamespace(video=None)])
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_video_bytes(ctx)) is None


def test_resolve_video_bytes_no_confia_en_video_embebido_de_host_no_confiable():
    # _embed_video_url encuentra la URL, pero _fetch_direct_video_bytes (sin
    # mockear acá) la rechaza por host -- _resolve_video_bytes no debe
    # devolver nada, no reventar.
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[SimpleNamespace(video=SimpleNamespace(url="https://evil.com/x.mp4"))],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_video_bytes(ctx)) is None


def test_resolve_video_bytes_usa_el_video_embebido_del_propio_mensaje(monkeypatch):
    # Si Discord ya desempaquetó un link del propio mensaje del comando
    # (ej. "purgito gif <link>") antes de que el bot lo procese, no hace
    # falta ir a buscar un mensaje respondido -- ni siquiera hace falta que
    # haya uno.
    async def fake_fetch(url, max_bytes):
        assert url == "https://cdn.discordapp.com/attachments/1/2/propio.mp4"
        return b"video del propio embed"

    monkeypatch.setattr(download_mod, "_fetch_direct_video_bytes", fake_fetch)
    ctx = FakeContext(
        own_embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/propio.mp4"
                )
            )
        ]
    )

    data = asyncio.run(_resolve_video_bytes(ctx))

    assert data == b"video del propio embed"


def test_resolve_video_bytes_prioriza_el_embed_propio_sobre_el_del_reply(monkeypatch):
    async def fake_fetch(url, max_bytes):
        assert url == "https://cdn.discordapp.com/propio.mp4"
        return b"del propio"

    monkeypatch.setattr(download_mod, "_fetch_direct_video_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://cdn.discordapp.com/del-reply.mp4")
            )
        ],
    )
    ctx = FakeContext(
        own_embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://cdn.discordapp.com/propio.mp4")
            )
        ],
        reference=SimpleNamespace(resolved=referenced, message_id=1),
    )

    data = asyncio.run(_resolve_video_bytes(ctx))

    assert data == b"del propio"


def test_resolve_video_bytes_usa_proxy_url_para_video_embebido_de_otro_bot(monkeypatch):
    # Caso reportado: "purgito gif" respondiendo al resultado de otro bot
    # (ej. NotSoBot) cuyo embed apunta a SU PROPIO CDN, no al de Discord --
    # Embed.video.url por sí solo fallaría _is_direct_video_host. Discord
    # igual lo sirve al cliente vía su proxy de media (por eso "se ve
    # perfecto" en Discord), y _embed_video_url ya prefiere ese proxy_url.
    # Sin mockear _fetch_direct_video_bytes: confirma que el flujo completo
    # (incluido el chequeo real de host) acepta el resultado.
    class _Resp:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size=None):
            yield b"video de otro bot"

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.notsobot.com/results/clip.mp4",
                    proxy_url="https://media.discordapp.net/external/abc/clip.mp4",
                )
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    data = asyncio.run(_resolve_video_bytes(ctx))

    assert data == b"video de otro bot"


# ── cogs/imagefx.py: comandos end-to-end ─────────────────────────────────────


def test_deepfry_camino_feliz_responde_con_archivo():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])

    asyncio.run(cog.deepfry_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1
    assert ctx.replies == []


def test_triggered_responde_con_un_gif():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(data=_png_bytes_with_shape())])

    asyncio.run(cog.triggered_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_wasted_camino_feliz_responde_con_archivo():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])

    asyncio.run(cog.wasted_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.png"


def test_caption_sin_texto_pide_el_texto():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])

    asyncio.run(cog.caption_cmd.callback(cog, ctx, texto=None))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_caption_camino_feliz_responde_con_archivo():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])

    asyncio.run(cog.caption_cmd.callback(cog, ctx, texto="ARRIBA|ABAJO"))

    assert len(ctx.reply_files) == 1


def test_filtro_rechaza_contenido_que_no_es_imagen_valida():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(data=b"no es una imagen")])

    asyncio.run(cog.invert_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_filtro_avisa_si_el_adjunto_es_demasiado_grande():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(size=999_999_999)])

    asyncio.run(cog.invert_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_segundo_filtro_distinto_respeta_el_cooldown_compartido():
    """El cooldown es por usuario, no por comando -- spamear deepfry, wide,
    invert... en ronda no debería dar 14x el rate real."""
    cog = _cog()
    ctx1 = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])
    asyncio.run(cog.deepfry_cmd.callback(cog, ctx1))
    assert len(ctx1.reply_files) == 1

    ctx2 = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])
    asyncio.run(cog.wide_cmd.callback(cog, ctx2))

    assert ctx2.reply_files == []
    assert len(ctx2.replies) == 1


def test_cooldown_distingue_usuarios_distintos():
    cog = _cog()
    ctx1 = FakeContext(
        author=FakeAuthor(user_id=1), attachments=[FakeAttachment(data=_png_bytes())]
    )
    asyncio.run(cog.deepfry_cmd.callback(cog, ctx1))

    ctx2 = FakeContext(
        author=FakeAuthor(user_id=2), attachments=[FakeAttachment(data=_png_bytes())]
    )
    asyncio.run(cog.deepfry_cmd.callback(cog, ctx2))

    assert len(ctx2.reply_files) == 1


# ── cog_command_error ─────────────────────────────────────────────────────────


def test_cog_command_error_bad_argument():
    from discord.ext import commands

    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.cog_command_error(ctx, commands.BadArgument("factor inválido")))

    assert len(ctx.replies) == 1


def test_cog_command_error_generico_no_revienta():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.cog_command_error(ctx, ValueError("boom")))

    assert len(ctx.replies) == 1


# ── Fase 4: comandos de edición de GIF end-to-end ────────────────────────────


def test_gifcaption_camino_feliz_responde_con_archivo():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())])

    asyncio.run(cog.gifcaption_cmd.callback(cog, ctx, texto="ARRIBA|ABAJO"))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gifcaption_sin_texto_pide_el_texto():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())])

    asyncio.run(cog.gifcaption_cmd.callback(cog, ctx, texto=None))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gifspeed_camino_feliz_responde_con_archivo():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())])

    asyncio.run(cog.gifspeed_cmd.callback(cog, ctx, factor=2.0))

    assert len(ctx.reply_files) == 1


def test_gifreverse_camino_feliz_responde_con_archivo():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())])

    asyncio.run(cog.gifreverse_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1


def test_gifwide_camino_feliz_responde_con_archivo():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())])

    asyncio.run(cog.gifwide_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1


def test_gif_edit_sin_adjunto_ni_reply_pide_un_gif():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gifreverse_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_edit_rechaza_contenido_que_no_es_gif_valido():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_png_bytes())])

    asyncio.run(cog.gifreverse_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


# ── Fase 4: "!gif" (video -> GIF) end-to-end ─────────────────────────────────


def test_gif_cmd_camino_feliz_convierte_un_video_real():
    # Única prueba que corre ffmpeg de verdad (las demás mockean
    # video_filters.convert_video_to_gif) -- confirma que el cableado
    # completo funciona, no solo cada pieza por separado.
    cog = _cog()
    video_bytes = _make_test_video_bytes(duration=0.5, fps=8)
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=video_bytes)]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_sin_video_pide_un_video():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_rechaza_video_demasiado_grande():
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", size=999_999_999)]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_avisa_si_la_conversion_falla(monkeypatch):
    def fake_convert(data, max_seconds, max_output_bytes):
        raise video_filters.VideoConversionFailed("boom")

    monkeypatch.setattr(imagefx_mod.video_filters, "convert_video_to_gif", fake_convert)
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="clip.mp4", data=b"x")])

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_avisa_si_el_gif_resultante_es_demasiado_grande(monkeypatch):
    def fake_convert(data, max_seconds, max_output_bytes):
        raise video_filters.GifTooLarge(max_output_bytes)

    monkeypatch.setattr(imagefx_mod.video_filters, "convert_video_to_gif", fake_convert)
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="clip.mp4", data=b"x")])

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_error_max_concurrency():
    from discord.ext import commands

    cog = _cog()
    ctx = FakeContext()

    asyncio.run(
        cog.gif_cmd_error(
            ctx, commands.MaxConcurrencyReached(1, commands.BucketType.guild)
        )
    )

    assert len(ctx.replies) == 1


def test_gif_cmd_tiene_su_propio_cooldown_separado_del_resto(monkeypatch):
    """ "!gif" es mucho más caro (ffmpeg de verdad) que el resto de los
    filtros -- su cooldown NO debería compartirse con _fx_cooldowns ni
    viceversa."""

    def fake_convert(data, max_seconds, max_output_bytes):
        return _gif_bytes()

    monkeypatch.setattr(imagefx_mod.video_filters, "convert_video_to_gif", fake_convert)
    cog = _cog()

    ctx1 = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])
    asyncio.run(cog.deepfry_cmd.callback(cog, ctx1))
    assert len(ctx1.reply_files) == 1

    ctx2 = FakeContext(attachments=[FakeAttachment(filename="clip.mp4", data=b"x")])
    asyncio.run(cog.gif_cmd.callback(cog, ctx2))

    assert len(ctx2.reply_files) == 1


# ── "!gif" con link, igual que "!dl" (sin adjunto de video) ──────────────────


def _fake_download_video_factory(seen=None, is_sensitive=False):
    """Mismo patrón que test_download_cog.py: crea un archivo temporal real
    (necesario porque gif_cmd hace open(path, "rb") sobre el resultado) y
    anota los argumentos con los que se lo llamó."""

    def fake(url, max_bytes):
        if seen is not None:
            seen["url"] = url
            seen["max_bytes"] = max_bytes
        tmp_dir = tempfile.mkdtemp(prefix="purgito_gif_test_")
        path = os.path.join(tmp_dir, "video.mp4")
        with open(path, "wb") as f:
            f.write(_make_test_video_bytes(duration=0.3, fps=6))
        return path, is_sensitive

    return fake


def test_gif_cmd_usa_link_propio(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(seen)
    )
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert seen["url"] == "https://instagram.com/reel/xyz"
    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_usa_link_del_mensaje_respondido(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(seen)
    )
    cog = _cog()
    referenced = SimpleNamespace(
        content="mira este reel https://instagram.com/reel/xyz",
        attachments=[],
        embeds=[],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert seen["url"] == "https://instagram.com/reel/xyz"
    assert len(ctx.reply_files) == 1


def test_gif_cmd_usa_la_url_del_embed_si_el_mensaje_respondido_no_tiene_texto(
    monkeypatch,
):
    """Ej. NotSoBot posteando un preview del video como embed puro, sin link
    de texto ni adjunto de Discord -- ver docstring de _reply_target_url."""
    seen: dict = {}
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(seen)
    )
    cog = _cog()
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[SimpleNamespace(url="https://instagram.com/reel/xyz")],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert seen["url"] == "https://instagram.com/reel/xyz"
    assert len(ctx.reply_files) == 1


def test_gif_cmd_usa_el_video_embebido_si_el_mensaje_respondido_no_tiene_adjunto(
    monkeypatch,
):
    """Caso reportado: responder "purgito gif" al resultado de otro bot (ej.
    NotSoBot) que lo mandó como embed con Embed.video -- no un adjunto de
    Discord ni un link de página. gif_cmd tiene que bajarlo directo, sin
    pasar por yt-dlp/_download_video."""

    async def fake_fetch(url, max_bytes):
        assert url == "https://cdn.discordapp.com/attachments/1/2/clip.mp4"
        return _make_test_video_bytes(duration=0.3, fps=6)

    def fail_download(url, max_bytes):
        raise AssertionError("no debería llamarse: el video vino del embed")

    monkeypatch.setattr(download_mod, "_fetch_direct_video_bytes", fake_fetch)
    monkeypatch.setattr(download_mod, "_download_video", fail_download)
    cog = _cog()
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/clip.mp4"
                )
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_usa_proxy_url_para_video_de_otro_bot_alojado_fuera_de_discord(
    monkeypatch,
):
    """Mismo caso reportado que el test anterior, pero sin mockear
    _fetch_direct_video_bytes: el embed de NotSoBot apunta a SU PROPIO CDN
    (no a Discord) en Embed.video.url, y solo Embed.video.proxy_url cae en
    un host de Discord -- confirma que el comando completo (incluido el
    chequeo real de _is_direct_video_host) usa ese proxy_url en vez de
    fallar con "necesito un video"."""

    class _Resp:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size=None):
            yield _make_test_video_bytes(duration=0.3, fps=6)

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    def fail_download(url, max_bytes):
        raise AssertionError("no debería llamarse: el video vino del embed")

    monkeypatch.setattr(download_mod, "_download_video", fail_download)
    cog = _cog()
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.notsobot.com/results/clip.mp4",
                    proxy_url="https://media.discordapp.net/external/abc/clip.mp4",
                )
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_prioriza_el_adjunto_sobre_el_link(monkeypatch):
    def fake_download(url, max_bytes):
        raise AssertionError("no debería llamarse: hay un adjunto de video")

    monkeypatch.setattr(download_mod, "_download_video", fake_download)
    cog = _cog()
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=video_bytes)]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_rechaza_link_de_sitio_no_soportado():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://youtube.com/watch?v=abc"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_link_descarga_fallida(monkeypatch):
    def fake_download(url, max_bytes):
        raise download_mod.DownloadFailed("privado o borrado")

    monkeypatch.setattr(download_mod, "_download_video", fake_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_link_descarga_demasiado_grande(monkeypatch):
    def fake_download(url, max_bytes):
        raise download_mod.DownloadTooLarge(max_bytes)

    monkeypatch.setattr(download_mod, "_download_video", fake_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_link_video_sensible_bloqueado_fuera_de_nsfw(monkeypatch):
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(is_sensitive=True)
    )
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=False)

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_link_video_sensible_permitido_en_nsfw(monkeypatch):
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(is_sensitive=True)
    )
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=True)

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert len(ctx.reply_files) == 1
    assert ctx.replies == []


def test_gif_cmd_link_limpia_el_directorio_temporal(monkeypatch):
    created_dirs: list[str] = []

    def fake_download(url, max_bytes):
        tmp_dir = tempfile.mkdtemp(prefix="purgito_gif_test_")
        created_dirs.append(tmp_dir)
        path = os.path.join(tmp_dir, "video.mp4")
        with open(path, "wb") as f:
            f.write(_make_test_video_bytes(duration=0.3, fps=6))
        return path, False

    monkeypatch.setattr(download_mod, "_download_video", fake_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1
    assert len(created_dirs) == 1
    assert not os.path.exists(created_dirs[0])
