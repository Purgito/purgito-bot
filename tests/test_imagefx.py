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
import i18n
import image_filters
import video_filters
from cogs.imagefx import (
    _GIF_EXTS,
    _IMAGE_EXTS,
    _VIDEO_EXTS,
    ImageFx,
    SourceTooLarge,
    _find_attachment,
    _resolve_gif_bytes,
    _resolve_gif_source_image_bytes,
    _resolve_image_bytes,
    _resolve_image_or_gif_bytes,
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


# ── image_filters: imagen estática -> GIF (fuente alternativa de "!gif") ─────


def test_image_to_gif_devuelve_un_gif_valido():
    out = image_filters.image_to_gif(_png_bytes(size=(64, 48)))
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "GIF"
        assert img.size == (64, 48)


def test_image_to_gif_acepta_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 30, 30)).save(buf, format="JPEG")
    out = image_filters.image_to_gif(buf.getvalue())
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "GIF"


def test_image_to_gif_acepta_webp():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (30, 200, 30)).save(buf, format="WEBP")
    out = image_filters.image_to_gif(buf.getvalue())
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "GIF"


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
        content="",
        embeds=None,
        author=None,
        guild_id=1,
        guild_filesize_limit=25 * 1024 * 1024,
        channel_is_nsfw=False,
        channel_id=None,
        bot=None,
    ):
        self.guild = (
            SimpleNamespace(id=guild_id, filesize_limit=guild_filesize_limit)
            if guild_id is not None
            else None
        )
        self.author = author or FakeAuthor()
        self.message = SimpleNamespace(
            attachments=attachments or [],
            reference=reference,
            content=content,
            embeds=embeds or [],
        )
        self.channel = SimpleNamespace(
            fetch_message=self._fetch_message,
            is_nsfw=lambda: channel_is_nsfw,
            id=channel_id,
        )
        self.bot = bot or SimpleNamespace(get_channel=lambda _channel_id: None)
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


def test_resolve_gif_bytes_detecta_por_content_type():
    attachment = FakeAttachment(filename="sin_extension", data=_gif_bytes())
    attachment.content_type = "image/gif"
    ctx = FakeContext(attachments=[attachment])

    assert asyncio.run(_resolve_gif_bytes(ctx)) == attachment._data


def test_resolve_gif_bytes_usa_el_gif_embebido_del_mensaje_respondido(monkeypatch):
    # Ej. un GIF mandado con el selector de Tenor de Discord llega como
    # embed (Embed.image), no como adjunto -- ver docstring de
    # _resolve_gif_bytes.
    gif_data = _gif_bytes()

    async def fake_fetch(url, max_bytes):
        assert url == "https://media.discordapp.net/attachments/1/2/tenor.gif"
        assert max_bytes == imagefx_mod.IMAGEFX_MAX_BYTES
        return gif_data

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                image=SimpleNamespace(
                    url="https://media.discordapp.net/attachments/1/2/tenor.gif"
                ),
                video=None,
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_gif_bytes(ctx)) == gif_data


def test_resolve_gif_bytes_ignora_un_embed_que_no_es_un_gif_valido(monkeypatch):
    # El embed tiene una imagen, pero no es un GIF real (ej. un thumbnail
    # PNG) -- no debe colarse como si lo fuera.
    async def fake_fetch(url, max_bytes):
        return _png_bytes()

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                image=SimpleNamespace(url="https://cdn.discordapp.com/x.png"),
                video=None,
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_gif_bytes(ctx)) is None


def test_resolve_gif_bytes_prioriza_el_adjunto_sobre_el_gif_embebido(monkeypatch):
    async def fake_fetch(url, max_bytes):
        raise AssertionError("no debería llamarse: hay un adjunto propio")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                image=SimpleNamespace(url="https://cdn.discordapp.com/x.gif"),
                video=None,
            )
        ],
    )
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="a.gif", data=b"adjunto propio")],
        reference=SimpleNamespace(resolved=referenced, message_id=1),
    )

    assert asyncio.run(_resolve_gif_bytes(ctx)) == b"adjunto propio"


def test_resolve_gif_bytes_convierte_un_adjunto_de_video_propio():
    # El bug reportado: muchos archivos que se comparten como "un GIF" en
    # Discord (loop, sin sonido) en realidad son un video -- típico de algo
    # re-subido desde Twitter/Reddit, que transcodean a mp4/webm los GIFs
    # que se suben. Antes de este fallback, _resolve_gif_bytes solo miraba
    # la extensión ".gif"/content-type "image/gif" y esto se descartaba en
    # silencio.
    video_bytes = _make_test_video_bytes(duration=0.5, fps=8)
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=video_bytes)]
    )

    data = asyncio.run(_resolve_gif_bytes(ctx))

    assert data is not None
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "GIF"
        assert img.is_animated


def test_resolve_gif_bytes_convierte_el_adjunto_de_video_del_mensaje_respondido():
    # Mismo caso, como reply -- el escenario exacto del reporte:
    # "!gifwide" respondiendo a un mensaje cuyo adjunto es un video que se ve
    # como un GIF.
    video_bytes = _make_test_video_bytes(duration=0.5, fps=8)
    referenced = SimpleNamespace(
        attachments=[FakeAttachment(filename="clip.mp4", data=video_bytes)],
        embeds=[],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    data = asyncio.run(_resolve_gif_bytes(ctx))

    assert data is not None
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "GIF"


def test_resolve_gif_bytes_prioriza_el_gif_real_sobre_un_adjunto_de_video():
    ctx = FakeContext(
        attachments=[
            FakeAttachment(filename="a.gif", data=_gif_bytes()),
            FakeAttachment(filename="clip.mp4", data=b"no deberia leerse"),
        ]
    )

    assert asyncio.run(_resolve_gif_bytes(ctx)) == _gif_bytes()


def test_resolve_gif_bytes_ignora_un_adjunto_de_video_no_decodificable():
    # Extensión/content-type de video pero contenido que ffmpeg no puede
    # decodificar -- no debe reventar, sigue el flujo normal de "no
    # encontré nada".
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=b"esto no es un video")]
    )

    assert asyncio.run(_resolve_gif_bytes(ctx)) is None


def test_resolve_gif_bytes_rechaza_adjunto_de_video_demasiado_grande():
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", size=999_999_999)]
    )

    with pytest.raises(SourceTooLarge):
        asyncio.run(_resolve_gif_bytes(ctx))


def test_as_gif_bytes_no_reconvierte_un_gif_real(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("no deberia intentar convertir un GIF que ya es valido")

    monkeypatch.setattr(video_filters, "convert_video_to_gif", fail_if_called)

    gif_data = _gif_bytes()
    assert asyncio.run(imagefx_mod._as_gif_bytes(gif_data)) == gif_data


def test_as_gif_bytes_no_convierte_una_imagen_estatica(monkeypatch):
    # Un thumbnail/imagen embebida no es "un video que parece un GIF" --
    # sin este chequeo, ffmpeg puede decodificar un PNG como un video de un
    # solo frame y colarlo como si fuera el GIF buscado.
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("no deberia intentar convertir una imagen estatica")

    monkeypatch.setattr(video_filters, "convert_video_to_gif", fail_if_called)

    assert asyncio.run(imagefx_mod._as_gif_bytes(_png_bytes())) is None


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
    # _resolve_image_bytes no pasa content_type_prefix -- un adjunto con
    # extensión no soportada sigue sin matchear aunque su content_type diga
    # "video/...".
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

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
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


def test_resolve_video_bytes_usa_proxy_url_cuando_el_embed_no_expone_url(monkeypatch):
    async def fake_fetch(url, max_bytes):
        assert url == "https://media.discordapp.net/attachments/1/2/clip.mp4"
        return b"video desde proxy"

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url=None,
                    proxy_url="https://media.discordapp.net/attachments/1/2/clip.mp4",
                )
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_video_bytes(ctx)) == b"video desde proxy"


def test_resolve_video_bytes_prueba_el_siguiente_recurso_del_embed(monkeypatch):
    async def fake_fetch(url, max_bytes):
        if url.endswith("no-disponible.mp4"):
            return None
        assert url.endswith("disponible.mp4")
        return b"video disponible"

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://cdn.test/no-disponible.mp4")
            ),
            SimpleNamespace(
                video=SimpleNamespace(url="https://cdn.test/disponible.mp4")
            ),
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_video_bytes(ctx)) == b"video disponible"


def test_resolve_video_bytes_busca_el_reply_en_su_canal_original(monkeypatch):
    async def fake_fetch(url, max_bytes):
        return b"video de otro canal"

    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(video=SimpleNamespace(url="https://cdn.test/clip.mp4"))
        ],
    )

    async def fetch_message(message_id):
        assert message_id == 42
        return referenced

    reference_channel = SimpleNamespace(fetch_message=fetch_message)
    bot = SimpleNamespace(get_channel=lambda channel_id: reference_channel)
    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    ctx = FakeContext(
        reference=SimpleNamespace(resolved=None, message_id=42, channel_id=200),
        channel_id=100,
        bot=bot,
    )

    assert asyncio.run(_resolve_video_bytes(ctx)) == b"video de otro canal"


def test_resolve_video_bytes_prioriza_el_adjunto_sobre_el_video_embebido(monkeypatch):
    async def fake_fetch(url, max_bytes):
        raise AssertionError("no debería llamarse: hay un adjunto de video")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
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


def test_resolve_video_bytes_ignora_un_video_embebido_que_no_se_puede_bajar(
    monkeypatch,
):
    async def fake_fetch(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    # _embed_video_url encuentra la URL, pero _fetch_direct_media_bytes (sin
    # mockear acá) la rechaza por host -- _resolve_video_bytes no debe
    # devolver nada, no reventar.
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[SimpleNamespace(video=SimpleNamespace(url="https://evil.com/x.mp4"))],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_video_bytes(ctx)) is None


# ── cogs/imagefx.py: _resolve_gif_source_image_bytes (fuente de imagen de
# "!gif" cuando no hay ningún video) ──────────────────────────────────────


def test_resolve_gif_source_image_bytes_sin_adjunto_ni_reply_devuelve_none():
    ctx = FakeContext()

    assert asyncio.run(_resolve_gif_source_image_bytes(ctx)) is None


def test_resolve_gif_source_image_bytes_usa_el_adjunto_propio():
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", data=b"una imagen")]
    )

    data = asyncio.run(_resolve_gif_source_image_bytes(ctx))

    assert data == b"una imagen"


def test_resolve_gif_source_image_bytes_usa_el_adjunto_del_mensaje_respondido():
    referenced = SimpleNamespace(
        attachments=[FakeAttachment(filename="foto.png", data=b"del reply")], embeds=[]
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    data = asyncio.run(_resolve_gif_source_image_bytes(ctx))

    assert data == b"del reply"


def test_resolve_gif_source_image_bytes_rechaza_adjunto_demasiado_grande():
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", size=999_999_999)]
    )

    with pytest.raises(SourceTooLarge):
        asyncio.run(_resolve_gif_source_image_bytes(ctx))


def test_resolve_gif_source_image_bytes_detecta_por_content_type():
    attachment = FakeAttachment(filename="foto", data=b"sin extension")
    attachment.content_type = "image/webp"
    ctx = FakeContext(attachments=[attachment])

    data = asyncio.run(_resolve_gif_source_image_bytes(ctx))

    assert data == b"sin extension"


def test_resolve_gif_source_image_bytes_usa_la_imagen_embebida_del_mensaje_respondido(
    monkeypatch,
):
    # Ej. NotSoBot reposteando su resultado como embed con Embed.image (una
    # imagen, no un video) en vez de como adjunto.
    async def fake_fetch(url, max_bytes):
        assert url == "https://cdn.discordapp.com/attachments/1/2/foto.webp"
        assert max_bytes == imagefx_mod.IMAGEFX_MAX_BYTES
        return b"imagen del embed"

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                image=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/foto.webp"
                )
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    data = asyncio.run(_resolve_gif_source_image_bytes(ctx))

    assert data == b"imagen del embed"


def test_resolve_gif_source_image_bytes_ignora_embed_sin_imagen():
    referenced = SimpleNamespace(attachments=[], embeds=[SimpleNamespace(image=None)])
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_gif_source_image_bytes(ctx)) is None


def test_resolve_gif_source_image_bytes_ignora_una_imagen_embebida_que_no_se_puede_bajar(
    monkeypatch,
):
    async def fake_fetch(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        attachments=[],
        embeds=[SimpleNamespace(image=SimpleNamespace(url="https://evil.com/x.webp"))],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(_resolve_gif_source_image_bytes(ctx)) is None


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


# ── image_filters.apply_per_frame: filtros de imagen estática aplicados a
# cada frame de un GIF (Fase 1/2 ahora también aceptan GIF, no solo imagen) ──


def test_apply_per_frame_conserva_la_cantidad_y_orden_de_frames():
    out = image_filters.apply_per_frame(image_filters.invert, _gif_bytes())
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "GIF"
        assert img.n_frames == 4


def test_apply_per_frame_aplica_el_filtro_a_cada_frame():
    # El primer frame de _gif_bytes() es rojo puro (255,0,0); invertido
    # debería ser cian (0,255,255) -- confirma que el filtro corrió sobre
    # el frame real, no que solo se copió el GIF de entrada.
    out = image_filters.apply_per_frame(image_filters.invert, _gif_bytes())
    with Image.open(io.BytesIO(out)) as img:
        assert img.convert("RGB").getpixel((0, 0)) == (0, 255, 255)


def test_apply_per_frame_conserva_las_duraciones_originales():
    out = image_filters.apply_per_frame(image_filters.invert, _gif_bytes())
    with Image.open(io.BytesIO(out)) as img:
        durations = [f.info.get("duration") for f in ImageSequence.Iterator(img)]
        assert durations == [100, 100, 100, 100]


def test_apply_per_frame_pasa_argumentos_extra_al_filtro():
    out = image_filters.apply_per_frame(image_filters.wide, _gif_bytes(), 2.0)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (80, 40)
        assert img.n_frames == 4


# ── cogs/imagefx.py: _resolve_image_or_gif_bytes (fuente ampliada de los
# comandos de "Filtros de imagen": GIF primero, imagen estática si no hay) ───


def test_resolve_image_or_gif_bytes_prioriza_el_gif_si_hay_uno():
    gif_data = _gif_bytes()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=gif_data)])

    data, is_gif = asyncio.run(_resolve_image_or_gif_bytes(ctx))

    assert is_gif is True
    assert data == gif_data


def test_resolve_image_or_gif_bytes_cae_a_imagen_estatica_sin_gif():
    png_data = _png_bytes()
    ctx = FakeContext(attachments=[FakeAttachment(data=png_data)])

    data, is_gif = asyncio.run(_resolve_image_or_gif_bytes(ctx))

    assert is_gif is False
    assert data == png_data


def test_resolve_image_or_gif_bytes_sin_nada_cae_al_avatar():
    ctx = FakeContext(author=FakeAuthor(avatar_bytes=b"avatar-bytes"))

    data, is_gif = asyncio.run(_resolve_image_or_gif_bytes(ctx))

    assert is_gif is False
    assert data == b"avatar-bytes"


def test_resolve_image_or_gif_bytes_allow_gif_false_ignora_el_gif_adjunto():
    # Lo usa "!triggered" -- ver su docstring en cogs/imagefx.py.
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())],
        author=FakeAuthor(avatar_bytes=b"avatar-bytes"),
    )

    data, is_gif = asyncio.run(_resolve_image_or_gif_bytes(ctx, allow_gif=False))

    assert is_gif is False
    assert data == b"avatar-bytes"


# ── cogs/imagefx.py: comandos de "Filtros de imagen" (Fase 1/2) aceptando
# GIF además de imagen estática, end-to-end ──────────────────────────────────


def test_invert_acepta_un_gif_y_responde_con_un_gif():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())])

    asyncio.run(cog.invert_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"
    assert ctx.replies == []


def test_caption_acepta_un_gif_y_responde_con_un_gif():
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())])

    asyncio.run(cog.caption_cmd.callback(cog, ctx, texto="ARRIBA|ABAJO"))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_wide_acepta_un_video_que_se_ve_como_gif_en_vez_de_caer_al_avatar():
    # Mismo caso que el bug reportado, para uno de los ~25 filtros de
    # imagen (Fase 1/2): comparten _resolve_gif_bytes vía
    # _resolve_image_or_gif_bytes, así que sin este fallback no fallaban con
    # un error -- caían en silencio al avatar de quien invoca (peor: ningún
    # aviso de que se ignoró el adjunto).
    cog = _cog()
    video_bytes = _make_test_video_bytes(duration=0.5, fps=8)
    referenced = SimpleNamespace(
        attachments=[FakeAttachment(filename="clip.mp4", data=video_bytes)],
        embeds=[],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.wide_cmd.callback(cog, ctx, factor=2.0))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_filtro_sin_gif_de_por_medio_sigue_devolviendo_png():
    # Comportamiento sin cambios cuando no hay ningún GIF en la fuente.
    cog = _cog()
    ctx = FakeContext(attachments=[FakeAttachment(data=_png_bytes())])

    asyncio.run(cog.invert_cmd.callback(cog, ctx))

    assert ctx.reply_files[0].filename == "purgito.png"


def test_filtro_rechaza_un_gif_adjunto_con_contenido_invalido():
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="a.gif", data=b"no es un gif")]
    )

    asyncio.run(cog.invert_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_triggered_ignora_un_gif_adjunto_y_usa_su_propio_efecto_desde_el_avatar():
    # triggered() ya genera su propio GIF corto (zoom + temblor) a partir de
    # una imagen fija -- animatable=False en su _run_filter hace que un GIF
    # adjunto no se use como fuente en absoluto (ver docstring de
    # _resolve_image_or_gif_bytes).
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="a.gif", data=_gif_bytes())],
        author=FakeAuthor(avatar_bytes=_png_bytes_with_shape()),
    )

    asyncio.run(cog.triggered_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


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


def test_gifwide_acepta_un_video_que_se_ve_como_gif_del_mensaje_respondido():
    # Reproduce el bug reportado end-to-end: "!gifwide" respondiendo a un
    # mensaje con un adjunto de video (no ".gif") debe generar el GIF, no
    # pedir uno que en los hechos ya está ahí.
    cog = _cog()
    video_bytes = _make_test_video_bytes(duration=0.5, fps=8)
    referenced = SimpleNamespace(
        attachments=[FakeAttachment(filename="clip.mp4", data=video_bytes)],
        embeds=[],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gifwide_cmd.callback(cog, ctx))

    assert ctx.replies == []
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


def test_gif_cmd_fuera_de_un_guild_responde_guild_only():
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=b"x")], guild_id=None
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert ctx.replies == [i18n.t("general.guild_only", "es")]


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


def _fake_fetch_media_factory(seen=None, is_sensitive=False):
    """Mismo patrón que test_download_cog.py: crea un archivo temporal real
    (necesario porque gif_cmd hace open(path, "rb") sobre el resultado) y
    anota los argumentos con los que se lo llamó."""

    async def fake(url, max_bytes):
        if seen is not None:
            seen["url"] = url
            seen["max_bytes"] = max_bytes
        return _make_test_video_bytes(duration=0.3, fps=6)

    return fake


def test_gif_cmd_usa_link_propio(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        imagefx_mod, "_fetch_media_bytes", _fake_fetch_media_factory(seen)
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
        imagefx_mod, "_fetch_media_bytes", _fake_fetch_media_factory(seen)
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
        imagefx_mod, "_fetch_media_bytes", _fake_fetch_media_factory(seen)
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


def test_gif_cmd_usa_url_dentro_del_payload_de_un_embed(monkeypatch):
    seen: dict = {}

    async def fake_fetch(url, max_bytes):
        seen["url"] = url
        return _make_test_video_bytes(duration=0.3, fps=6)

    class PayloadEmbed:
        url = None
        title = None
        description = None

        def to_dict(self):
            return {"provider": {"media_url": "https://cdn.example.test/video.mp4"}}

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(content="", attachments=[], embeds=[PayloadEmbed()])
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert seen["url"] == "https://cdn.example.test/video.mp4"
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

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
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


def test_gif_cmd_usa_el_video_embebido_en_el_mensaje_actual(monkeypatch):
    async def fake_fetch(url, max_bytes):
        assert url == "https://media.example.test/notso.mp4"
        return _make_test_video_bytes(duration=0.3, fps=6)

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    cog = _cog()
    ctx = FakeContext(
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://media.example.test/notso.mp4")
            )
        ]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_convierte_una_imagen_desde_url(monkeypatch):
    async def fake_fetch(url, max_bytes):
        assert url == "https://images.example.test/foto.png"
        return _png_bytes()

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(
        cog.gif_cmd.callback(cog, ctx, url="https://images.example.test/foto.png")
    )

    assert len(ctx.reply_files) == 1


def test_gif_cmd_prioriza_el_adjunto_sobre_el_link(monkeypatch):
    def fake_download(url, max_bytes):
        raise AssertionError("no debería llamarse: hay un adjunto de video")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_download)
    cog = _cog()
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="clip.mp4", data=video_bytes)]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_acepta_una_url_de_cualquier_host_publico(monkeypatch):
    async def fake_fetch(url, max_bytes):
        assert url == "https://youtube.com/watch?v=abc"
        return _make_test_video_bytes(duration=0.3, fps=6)

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://youtube.com/watch?v=abc"))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_link_descarga_fallida(monkeypatch):
    async def fake_download(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_link_descarga_demasiado_grande(monkeypatch):
    async def fake_download(url, max_bytes):
        raise SourceTooLarge(max_bytes)

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_no_hereda_la_politica_nsfw_de_dl(monkeypatch):
    monkeypatch.setattr(
        imagefx_mod, "_fetch_media_bytes", _fake_fetch_media_factory(is_sensitive=True)
    )
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=False)

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_funciona_tambien_en_un_canal_nsfw(monkeypatch):
    monkeypatch.setattr(
        imagefx_mod, "_fetch_media_bytes", _fake_fetch_media_factory(is_sensitive=True)
    )
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=True)

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert len(ctx.reply_files) == 1
    assert ctx.replies == []


def test_gif_cmd_link_no_crea_archivos_temporales(monkeypatch):
    async def fake_fetch(url, max_bytes):
        return _make_test_video_bytes(duration=0.3, fps=6)

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1


# ── "!gif" con una imagen estática (sin video en ningún lado) ────────────────


def test_gif_cmd_usa_una_imagen_adjunta_si_no_hay_ningun_video():
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", data=_png_bytes())]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"
    assert ctx.replies == []


def test_gif_cmd_usa_la_imagen_del_mensaje_respondido():
    referenced = SimpleNamespace(
        attachments=[FakeAttachment(filename="foto.png", data=_png_bytes())],
        embeds=[],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_usa_la_imagen_embebida_si_el_mensaje_respondido_no_tiene_adjunto(
    monkeypatch,
):
    """Mismo caso que el video embebido (Embed.video), pero cuando lo que
    posteó el otro bot es una imagen (Embed.image)."""

    async def fake_fetch(url, max_bytes):
        return _png_bytes()

    def fail_download(url, max_bytes):
        raise AssertionError("no debería llamarse: la imagen vino del embed")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    cog = _cog()
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                image=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/foto.webp"
                )
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_prioriza_el_video_sobre_una_imagen():
    # Si de alguna forma hay las dos cosas (dos adjuntos distintos), el
    # video sigue ganando -- "!gif" es primero un conversor de video.
    cog = _cog()
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    ctx = FakeContext(
        attachments=[
            FakeAttachment(filename="clip.mp4", data=video_bytes),
            FakeAttachment(filename="foto.png", data=_png_bytes()),
        ]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_prioriza_una_imagen_adjunta_sobre_un_link(monkeypatch):
    # Mismo criterio que "adjunto > link" para video: un adjunto (sea video
    # o imagen) le gana a un link pasado como argumento.
    def fail_download(url, max_bytes):
        raise AssertionError("no debería llamarse: hay una imagen adjunta")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fail_download)
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", data=_png_bytes())]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_avisa_si_la_imagen_es_invalida():
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", data=b"no es una imagen")]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_avisa_si_la_imagen_es_demasiado_grande():
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", size=999_999_999)]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_imagen_no_pasa_por_ffmpeg(monkeypatch):
    def fail_convert(data, max_seconds, max_output_bytes):
        raise AssertionError("no debería llamarse: no hay ningún video")

    monkeypatch.setattr(imagefx_mod.video_filters, "convert_video_to_gif", fail_convert)
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", data=_png_bytes())]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_avisa_si_falla_la_conversion_de_imagen_a_gif(monkeypatch):
    def fail_convert(data):
        raise ValueError("boom")

    monkeypatch.setattr(imagefx_mod.image_filters, "image_to_gif", fail_convert)
    cog = _cog()
    ctx = FakeContext(
        attachments=[FakeAttachment(filename="foto.webp", data=_png_bytes())]
    )

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_sin_nada_sigue_pidiendo_video_o_imagen():
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_prioriza_video_de_embed_sobre_thumbnail_en_mensaje_respondido(
    monkeypatch,
):
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    thumb_bytes = _png_bytes()
    called = {}

    async def fake_fetch(url, max_bytes):
        if "clip.mp4" in url:
            return video_bytes
        if "thumb.jpg" in url:
            return thumb_bytes
        return None

    def fake_video_to_gif(data, max_dur, max_out):
        called["converter"] = "video"
        return b"GIF_VIDEO"

    def fail_image_to_gif(data):
        called["converter"] = "image"
        raise AssertionError(
            "no deberia llamarse image_to_gif cuando hay un video en el embed"
        )

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(
        imagefx_mod.video_filters, "convert_video_to_gif", fake_video_to_gif
    )
    monkeypatch.setattr(imagefx_mod.image_filters, "image_to_gif", fail_image_to_gif)

    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/clip.mp4"
                ),
                thumbnail=SimpleNamespace(
                    url="https://images.discordapp.net/thumb.jpg"
                ),
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert called.get("converter") == "video"
    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_extrae_video_de_embed_rich_de_otro_bot_sin_embed_video(monkeypatch):
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    thumb_bytes = _png_bytes()
    called = {}

    async def fake_fetch(url, max_bytes):
        if "output.mp4" in url:
            return video_bytes
        if "preview.png" in url:
            return thumb_bytes
        return None

    def fake_video_to_gif(data, max_dur, max_out):
        called["converter"] = "video"
        return b"GIF_VIDEO"

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(
        imagefx_mod.video_filters, "convert_video_to_gif", fake_video_to_gif
    )

    # Embed creado por un bot (tipo rich): Discord API no permite setear embed.video,
    # por lo que el bot envía la URL del video en embed.url y una miniatura en embed.thumbnail
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=None,
                url="https://cdn.bot.test/output.mp4",
                thumbnail=SimpleNamespace(url="https://cdn.bot.test/preview.png"),
                description="Meme generado",
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert called.get("converter") == "video"
    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_extrae_video_de_embed_markdown_description(monkeypatch):
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    requested_urls = []

    async def fake_fetch(url, max_bytes):
        requested_urls.append(url)
        if url == "https://cdn.bot.test/clip.mp4":
            return video_bytes
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=None,
                url=None,
                thumbnail=SimpleNamespace(url="https://cdn.bot.test/thumb.jpg"),
                description="Descarga tu video: [Click aqui](https://cdn.bot.test/clip.mp4)",
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert "https://cdn.bot.test/clip.mp4" in requested_urls
    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_resolve_reference_refetches_when_resolved_lacks_embeds_and_attachments():
    fetched_message = SimpleNamespace(
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://cdn.example.test/video.mp4")
            )
        ],
    )

    async def fake_fetch_message(message_id):
        assert message_id == 12345
        return fetched_message

    ctx = FakeContext()
    ctx.channel = SimpleNamespace(id=999, fetch_message=fake_fetch_message)
    partial_resolved = SimpleNamespace(attachments=[], embeds=[])
    ctx.message.reference = SimpleNamespace(
        message_id=12345, channel_id=999, resolved=partial_resolved
    )

    resolved = asyncio.run(imagefx_mod._resolve_reference(ctx))
    assert resolved is fetched_message
    assert len(resolved.embeds) == 1


def test_fetch_media_bytes_rechaza_html(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def iter_content(self, chunk_size=262144):
            yield b"<!DOCTYPE html><html><body>Player page</body></html>"

        def close(self):
            pass

    def fake_fetch_public_url(method, url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(imagefx_mod.r2, "fetch_public_url", fake_fetch_public_url)

    result = asyncio.run(
        imagefx_mod._fetch_media_bytes("https://example.com/player", 1024 * 1024)
    )
    assert result is None


# ── "!gif" cae a yt-dlp (mismo extractor que "!dl") cuando el embed no ──────
# expone un video descargable con un GET simple -- caso real: Instagram,
# TikTok, Twitter/X y Facebook exponen el video en el embed pero su CDN de
# origen rechaza un GET anónimo. Un intento previo de arreglar "!gif" sacó
# esta reutilización de "!dl" por completo (ver historial de
# cogs/imagefx.py) y reintrodujo el bug reportado -- estos tests existen
# para que no vuelva a pasar en silencio.


def _fake_download_video_factory(seen=None, is_sensitive=False):
    """Mismo patrón que test_download_cog.py: crea un archivo temporal real
    (necesario porque _resolve_social_video_bytes hace open(path, "rb")
    sobre el resultado) y anota los argumentos con los que se lo llamó."""

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


def test_gif_cmd_usa_yt_dlp_si_el_link_propio_no_se_puede_bajar_directo(monkeypatch):
    """ "!gif https://instagram.com/reel/xyz": un GET directo a esa URL no
    devuelve un video (es la página HTML, no el archivo), así que tiene que
    caer a yt-dlp igual que "!dl"."""
    seen: dict = {}

    async def fake_fetch(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(seen)
    )
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert seen["url"] == "https://instagram.com/reel/xyz"
    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_usa_yt_dlp_con_el_embed_url_del_mensaje_respondido(monkeypatch):
    """Caso reportado: se responde a un mensaje cuyo embed (el que Discord
    generó solo al pegar un link de X) tiene un video adentro, pero
    Embed.video/proxy_url no se puede bajar con un GET simple -- Embed.url
    (el link de origen) sí es reconocible para yt-dlp."""
    seen: dict = {}

    async def fake_fetch(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(seen)
    )
    cog = _cog()
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://video.twimg.com/clip.mp4"),
                url="https://x.com/user/status/123",
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert seen["url"] == "https://x.com/user/status/123"
    assert len(ctx.reply_files) == 1


def test_gif_cmd_no_llama_a_yt_dlp_si_el_embed_ya_se_pudo_bajar_directo(monkeypatch):
    """El video de un repost tipo NotSoBot (Embed.video apuntando al CDN de
    Discord) ya se puede bajar con un GET simple -- no debe pasar por
    yt-dlp, mucho más caro."""
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)

    async def fake_fetch(url, max_bytes):
        return video_bytes

    def fail_download(url, max_bytes):
        raise AssertionError("no debería llamarse: el video ya se bajó directo")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(download_mod, "_download_video", fail_download)
    cog = _cog()
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/clip.mp4"
                ),
                url=None,
            )
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_yt_dlp_falla_no_revienta(monkeypatch):
    async def fake_fetch(url, max_bytes):
        return None

    def fail_download(url, max_bytes):
        raise download_mod.DownloadFailed("privado o borrado")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(download_mod, "_download_video", fail_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://tiktok.com/@user/video/1"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_yt_dlp_video_demasiado_grande(monkeypatch):
    async def fake_fetch(url, max_bytes):
        return None

    def fail_download(url, max_bytes):
        raise download_mod.DownloadTooLarge(max_bytes)

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(download_mod, "_download_video", fail_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://facebook.com/watch/?v=1"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1
    assert "MB" in ctx.replies[0]


def test_gif_cmd_yt_dlp_video_sensible_bloqueado_fuera_de_nsfw(monkeypatch):
    async def fake_fetch(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(is_sensitive=True)
    )
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=False)

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


def test_gif_cmd_yt_dlp_video_sensible_permitido_en_nsfw(monkeypatch):
    async def fake_fetch(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(
        download_mod, "_download_video", _fake_download_video_factory(is_sensitive=True)
    )
    cog = _cog()
    ctx = FakeContext(channel_is_nsfw=True)

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://x.com/user/status/123"))

    assert len(ctx.reply_files) == 1
    assert ctx.replies == []


def test_gif_cmd_yt_dlp_limpia_el_directorio_temporal(monkeypatch):
    created_dirs: list[str] = []

    async def fake_fetch(url, max_bytes):
        return None

    def fake_download(url, max_bytes):
        tmp_dir = tempfile.mkdtemp(prefix="purgito_gif_test_")
        created_dirs.append(tmp_dir)
        path = os.path.join(tmp_dir, "video.mp4")
        with open(path, "wb") as f:
            f.write(_make_test_video_bytes(duration=0.3, fps=6))
        return path, False

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(download_mod, "_download_video", fake_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url="https://instagram.com/reel/xyz"))

    assert len(ctx.reply_files) == 1
    assert len(created_dirs) == 1
    assert not os.path.exists(created_dirs[0])


def test_gif_cmd_sin_link_de_sitio_soportado_no_llama_a_yt_dlp(monkeypatch):
    """Un link de un sitio que ni yt-dlp sabe scrapear (ej. YouTube, que
    "!dl" excluye a propósito) no debe intentar _download_video -- termina
    en el mensaje genérico de "necesito un video o imagen"."""

    async def fake_fetch(url, max_bytes):
        return None

    def fail_download(url, max_bytes):
        raise AssertionError("no debería llamarse: el host no está soportado")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(download_mod, "_download_video", fail_download)
    cog = _cog()
    ctx = FakeContext()

    asyncio.run(
        cog.gif_cmd.callback(cog, ctx, url="https://youtube.com/watch?v=abc123")
    )

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1


# ── "!gif" con Components V2 (sin message.embeds) ────────────────────────────
# Caso reportado: un bot (ej. NotSoBot) postea su resultado con la UI nueva
# de Discord (Container > MediaGallery/File, layout_v2.py) en vez de un
# embed clásico. Un mensaje así tiene message.embeds SIEMPRE vacío (son
# excluyentes vía IS_COMPONENTS_V2) -- _embed_video_urls/_embed_media_urls
# no tienen nada que recorrer y "!gif" pedía un video igual, aunque hubiera
# uno a la vista. Los SimpleNamespace de acá reproducen la forma real de
# discord.py 2.7.1 (Container.children, MediaGallery.items,
# MediaGalleryItem.media.url, FileComponent.media.url -- verificado contra
# el código fuente de la librería, no adivinado).


def _fake_media_gallery(*urls):
    return SimpleNamespace(
        items=[SimpleNamespace(media=SimpleNamespace(url=u)) for u in urls]
    )


def _fake_file_component(url):
    return SimpleNamespace(media=SimpleNamespace(url=url))


def _fake_container(*children):
    return SimpleNamespace(children=list(children))


def test_component_media_urls_encuentra_media_gallery_en_un_container():
    message = SimpleNamespace(
        embeds=[],
        components=[
            _fake_container(_fake_media_gallery("https://cdn.notsobot.com/result.gif"))
        ],
    )
    urls = list(imagefx_mod._component_media_urls(message))
    assert urls == ["https://cdn.notsobot.com/result.gif"]


def test_component_media_urls_encuentra_file_component_anidado():
    message = SimpleNamespace(
        embeds=[],
        components=[
            _fake_container(
                SimpleNamespace(content="Invoked by @Frambuesa"),
                _fake_file_component("https://cdn.notsobot.com/result.mp4"),
            )
        ],
    )
    urls = list(imagefx_mod._component_media_urls(message))
    assert urls == ["https://cdn.notsobot.com/result.mp4"]


def test_component_media_urls_via_to_dict_si_no_hay_atributos_directos():
    """Cubre el caso en que el objeto de discord.py solo expone to_dict()
    (o cambió de nombre de atributo interno) -- mismo mecanismo defensivo
    que _embed_url_texts_single ya usa para embeds."""

    class OnlyToDict:
        def to_dict(self):
            return {
                "type": 17,
                "components": [
                    {
                        "type": 12,
                        "items": [{"media": {"url": "https://cdn.notsobot.com/x.gif"}}],
                    }
                ],
            }

    message = SimpleNamespace(embeds=[], components=[OnlyToDict()])
    urls = list(imagefx_mod._component_media_urls(message))
    assert urls == ["https://cdn.notsobot.com/x.gif"]


def test_component_media_urls_sin_components_no_rompe():
    message = SimpleNamespace(embeds=[], content="")
    assert list(imagefx_mod._component_media_urls(message)) == []


def test_gif_cmd_encuentra_video_en_components_v2_sin_embeds(monkeypatch):
    """El caso reportado en producción: se responde con "!gif" a un mensaje
    de otro bot que muestra su resultado con Components V2, sin ningún
    embed clásico ni adjunto de Discord -- el medio vive en una URL externa
    (el propio CDN del bot) dentro de un MediaGallery."""
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    requested_urls = []

    async def fake_fetch(url, max_bytes):
        requested_urls.append(url)
        if url == "https://cdn.notsobot.com/result.gif":
            return video_bytes
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(
        content="",
        attachments=[],
        embeds=[],
        components=[
            _fake_container(_fake_media_gallery("https://cdn.notsobot.com/result.gif"))
        ],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert "https://cdn.notsobot.com/result.gif" in requested_urls
    assert len(ctx.reply_files) == 1
    assert ctx.reply_files[0].filename == "purgito.gif"


def test_gif_cmd_resuelve_attachment_scheme_de_components_v2(monkeypatch):
    """Un bloque File de Components V2 que referencia un adjunto real del
    propio mensaje usa el esquema "attachment://<filename>" (ver
    layout_v2.py) -- eso no es una URL HTTP: hay que resolverlo contra
    message.attachments en vez de intentar un GET. Extensión .gif a
    propósito (no .mp4): tiene que no matchear _find_attachment (que busca
    video por extensión/content-type) para probar de verdad la resolución
    por Components V2, no la del adjunto de video de siempre."""

    async def fail_fetch(url, max_bytes):
        raise AssertionError("no debería intentar un GET: es attachment://")

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fail_fetch)
    video_bytes = _make_test_video_bytes(duration=0.3, fps=6)
    referenced = SimpleNamespace(
        content="",
        attachments=[FakeAttachment(filename="clip.gif", data=video_bytes)],
        embeds=[],
        components=[_fake_container(_fake_file_component("attachment://clip.gif"))],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert len(ctx.reply_files) == 1


def test_gif_cmd_sin_embeds_ni_components_sigue_pidiendo_video(monkeypatch):
    async def fake_fetch(url, max_bytes):
        return None

    monkeypatch.setattr(imagefx_mod, "_fetch_media_bytes", fake_fetch)
    referenced = SimpleNamespace(content="", attachments=[], embeds=[], components=[])
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))
    cog = _cog()

    asyncio.run(cog.gif_cmd.callback(cog, ctx, url=None))

    assert ctx.reply_files == []
    assert len(ctx.replies) == 1
