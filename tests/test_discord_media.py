"""discord_media.py: helpers para resolver contenido multimedia disponible
en el CONTEXTO de un mensaje de Discord (adjuntos, el mensaje al que se
responde, y los embeds de cualquiera de los dos) -- compartidos por
"purgito dl" (cogs/download.py) y "purgito gif" (cogs/imagefx.py), pero sin
nada de scraping de plataformas puntuales ni de yt-dlp: eso es exclusivo de
cogs/download.py, cubierto en test_download_cog.py.
"""

import asyncio
from types import SimpleNamespace

import discord
import pytest

import discord_media
import r2


class FakeContext:
    def __init__(self, reference=None):
        self.message = SimpleNamespace(reference=reference)
        self.channel = SimpleNamespace(fetch_message=self._fetch_message)
        self._fetch_message_result = None

    async def _fetch_message(self, message_id):
        if self._fetch_message_result is None:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "")
        return self._fetch_message_result


# ── resolve_reference ─────────────────────────────────────────────────────


def test_resolve_reference_sin_reply_devuelve_none():
    ctx = FakeContext()

    assert asyncio.run(discord_media.resolve_reference(ctx)) is None


def test_resolve_reference_usa_el_resolved_ya_poblado():
    referenced = SimpleNamespace(content="hola")
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(discord_media.resolve_reference(ctx)) is referenced


def test_resolve_reference_ignora_reply_borrado():
    ctx = FakeContext(
        reference=SimpleNamespace(
            resolved=discord.DeletedReferencedMessage(SimpleNamespace()), message_id=1
        )
    )

    assert asyncio.run(discord_media.resolve_reference(ctx)) is None


def test_resolve_reference_busca_con_fetch_si_no_esta_en_cache():
    ctx = FakeContext(reference=SimpleNamespace(resolved=None, message_id=42))
    fetched = SimpleNamespace(content="del fetch")
    ctx._fetch_message_result = fetched

    assert asyncio.run(discord_media.resolve_reference(ctx)) is fetched


def test_resolve_reference_devuelve_none_si_el_fetch_falla():
    ctx = FakeContext(reference=SimpleNamespace(resolved=None, message_id=42))

    assert asyncio.run(discord_media.resolve_reference(ctx)) is None


def test_resolve_reference_devuelve_none_sin_resolved_ni_message_id():
    ctx = FakeContext(reference=SimpleNamespace(resolved=None, message_id=None))

    assert asyncio.run(discord_media.resolve_reference(ctx)) is None


# ── reply_target_url ──────────────────────────────────────────────────────


def test_reply_target_url_sin_reply_devuelve_none():
    ctx = FakeContext()

    assert asyncio.run(discord_media.reply_target_url(ctx)) is None


def test_reply_target_url_extrae_el_link_del_texto():
    referenced = SimpleNamespace(
        content="mira esto https://ejemplo.com/video", embeds=[]
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert (
        asyncio.run(discord_media.reply_target_url(ctx)) == "https://ejemplo.com/video"
    )


def test_reply_target_url_cae_al_embed_url_si_no_hay_link_en_el_texto():
    referenced = SimpleNamespace(
        content="", embeds=[SimpleNamespace(url="https://ejemplo.com/pagina")]
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert (
        asyncio.run(discord_media.reply_target_url(ctx)) == "https://ejemplo.com/pagina"
    )


def test_reply_target_url_prioriza_el_texto_sobre_el_embed():
    referenced = SimpleNamespace(
        content="https://ejemplo.com/del-texto",
        embeds=[SimpleNamespace(url="https://ejemplo.com/del-embed")],
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert (
        asyncio.run(discord_media.reply_target_url(ctx))
        == "https://ejemplo.com/del-texto"
    )


def test_reply_target_url_sin_link_en_ningun_lado_devuelve_none():
    referenced = SimpleNamespace(
        content="che mira esto", embeds=[SimpleNamespace(url=None)]
    )
    ctx = FakeContext(reference=SimpleNamespace(resolved=referenced, message_id=1))

    assert asyncio.run(discord_media.reply_target_url(ctx)) is None


# ── embed_video_url / embed_image_url / is_direct_media_host /
# fetch_direct_media_bytes ────────────────────────────────────────────────
#
# Usados por "purgito gif" (cogs/imagefx.py) para bajar el video o imagen
# EMBEBIDOS de un mensaje (propio o respondido) -- Embed.video / Embed.image
# -- cuando no hay adjunto (ej. otro bot reposteando su resultado como
# embed en vez de como adjunto de Discord). A diferencia de Embed.url (la
# página de origen que usa reply_target_url), esto es el archivo
# reproducible en sí.


def test_embed_video_url_extrae_el_video_del_embed():
    message = SimpleNamespace(
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/clip.mp4"
                )
            )
        ]
    )

    assert (
        discord_media.embed_video_url(message)
        == "https://cdn.discordapp.com/attachments/1/2/clip.mp4"
    )


def test_embed_video_url_ignora_embeds_sin_video():
    message = SimpleNamespace(embeds=[SimpleNamespace(video=None, url="https://x.com")])

    assert discord_media.embed_video_url(message) is None


def test_embed_video_url_sin_embeds_devuelve_none():
    assert discord_media.embed_video_url(SimpleNamespace(embeds=[])) is None


def test_embed_video_url_tolera_embeds_sin_atributo_video():
    # Un discord.Embed real siempre tiene .video (un EmbedProxy vacío si no
    # hay video) -- pero cualquier otro objeto con forma de embed no debería
    # romper esto con un AttributeError.
    message = SimpleNamespace(embeds=[SimpleNamespace(url="https://x.com")])

    assert discord_media.embed_video_url(message) is None


def test_embed_video_url_prioriza_proxy_url_sobre_url():
    # Caso reportado: un bot (ej. NotSoBot) postea un embed cuyo video vive
    # en SU propio CDN, no en Discord -- Embed.video.url apunta ahí y
    # is_direct_media_host lo va a rechazar. Pero Discord igual lo sirve al
    # cliente a través de su proxy de media (por eso "se ve perfecto" en la
    # captura del reporte), y ESE host sí está en _DIRECT_MEDIA_HOSTS.
    message = SimpleNamespace(
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.notsobot.com/results/clip.mp4",
                    proxy_url="https://media.discordapp.net/external/abc/clip.mp4",
                )
            )
        ]
    )

    assert (
        discord_media.embed_video_url(message)
        == "https://media.discordapp.net/external/abc/clip.mp4"
    )


def test_embed_video_url_cae_a_url_si_proxy_url_esta_vacio():
    message = SimpleNamespace(
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/clip.mp4",
                    proxy_url=None,
                )
            )
        ]
    )

    assert (
        discord_media.embed_video_url(message)
        == "https://cdn.discordapp.com/attachments/1/2/clip.mp4"
    )


def test_embed_image_url_extrae_la_imagen_del_embed():
    message = SimpleNamespace(
        embeds=[
            SimpleNamespace(
                image=SimpleNamespace(
                    url="https://cdn.discordapp.com/attachments/1/2/foto.webp"
                )
            )
        ]
    )

    assert (
        discord_media.embed_image_url(message)
        == "https://cdn.discordapp.com/attachments/1/2/foto.webp"
    )


def test_embed_image_url_ignora_embeds_sin_imagen():
    message = SimpleNamespace(embeds=[SimpleNamespace(image=None, url="https://x.com")])

    assert discord_media.embed_image_url(message) is None


def test_embed_image_url_sin_embeds_devuelve_none():
    assert discord_media.embed_image_url(SimpleNamespace(embeds=[])) is None


def test_embed_image_url_tolera_embeds_sin_atributo_image():
    message = SimpleNamespace(embeds=[SimpleNamespace(url="https://x.com")])

    assert discord_media.embed_image_url(message) is None


def test_embed_image_url_prioriza_proxy_url_sobre_url():
    # Mismo criterio que embed_video_url -- ver
    # test_embed_video_url_prioriza_proxy_url_sobre_url.
    message = SimpleNamespace(
        embeds=[
            SimpleNamespace(
                image=SimpleNamespace(
                    url="https://cdn.notsobot.com/results/foto.webp",
                    proxy_url="https://media.discordapp.net/external/abc/foto.webp",
                )
            )
        ]
    )

    assert (
        discord_media.embed_image_url(message)
        == "https://media.discordapp.net/external/abc/foto.webp"
    )


def test_embed_image_url_no_se_confunde_con_un_video_en_el_mismo_embed():
    # Un embed puede tener video e imagen (ej. la miniatura) a la vez --
    # cada helper busca su propio campo, no el primero que encuentre.
    message = SimpleNamespace(
        embeds=[
            SimpleNamespace(
                video=SimpleNamespace(url="https://cdn.discordapp.com/x.mp4"),
                image=SimpleNamespace(url="https://cdn.discordapp.com/x-thumb.webp"),
            )
        ]
    )

    assert discord_media.embed_video_url(message) == "https://cdn.discordapp.com/x.mp4"
    assert (
        discord_media.embed_image_url(message)
        == "https://cdn.discordapp.com/x-thumb.webp"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.discordapp.com/attachments/1/2/clip.mp4",
        "https://media.discordapp.net/attachments/1/2/clip.mp4",
        "https://sub.cdn.discordapp.com/attachments/1/2/clip.mp4",
    ],
)
def test_is_direct_media_host_acepta_el_cdn_de_discord(url):
    assert discord_media.is_direct_media_host(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/clip.mp4",
        "https://discordapp.com.evil.com/clip.mp4",
        "not-a-url",
        "",
    ],
)
def test_is_direct_media_host_rechaza_hosts_de_terceros(url):
    assert not discord_media.is_direct_media_host(url)


def test_fetch_direct_media_bytes_descarga_desde_un_host_de_confianza(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size=None):
            yield b"video-bytes"

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        discord_media.fetch_direct_media_bytes(
            "https://cdn.discordapp.com/attachments/1/2/clip.mp4", 1024
        )
    )

    assert data == b"video-bytes"


def test_fetch_direct_media_bytes_rechaza_host_no_confiable():
    data = asyncio.run(
        discord_media.fetch_direct_media_bytes("https://evil.com/clip.mp4", 1024)
    )

    assert data is None


def test_fetch_direct_media_bytes_respeta_el_limite_de_tamano_por_content_length(
    monkeypatch,
):
    class _Resp:
        status_code = 200
        headers = {"Content-Length": "2048"}

        def iter_content(self, chunk_size=None):
            yield b"x" * 2048

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        discord_media.fetch_direct_media_bytes(
            "https://cdn.discordapp.com/attachments/1/2/clip.mp4", 1024
        )
    )

    assert data is None


def test_fetch_direct_media_bytes_respeta_el_limite_de_tamano_sin_content_length(
    monkeypatch,
):
    # Sin Content-Length hay que cortar mientras se van sumando los chunks.
    class _Resp:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size=None):
            yield b"x" * 2048

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        discord_media.fetch_direct_media_bytes(
            "https://cdn.discordapp.com/attachments/1/2/clip.mp4", 1024
        )
    )

    assert data is None


def test_fetch_direct_media_bytes_devuelve_none_si_el_status_no_es_200(monkeypatch):
    class _Resp:
        status_code = 404
        headers = {}

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        discord_media.fetch_direct_media_bytes(
            "https://cdn.discordapp.com/attachments/1/2/clip.mp4", 1024
        )
    )

    assert data is None


def test_fetch_direct_media_bytes_rechaza_ssrf():
    # Mismo filtro que fetch_gif_bytes en cogs/gifs.py: r2.fetch_public_url
    # bloquea IPs no públicamente enrutables, aunque el host esté en la
    # allowlist -- acá lo confirmamos con hosts que no pasan
    # is_direct_media_host (127.0.0.1/metadata no son
    # cdn.discordapp.com/media.discordapp.net).
    assert (
        asyncio.run(
            discord_media.fetch_direct_media_bytes(
                "http://127.0.0.1/internal.mp4", 1024
            )
        )
        is None
    )


# ── fetch_media_bytes (sin restricción de host) ───────────────────────────
#
# A diferencia de fetch_direct_media_bytes, esto es lo que usa "purgito gif"
# para un link que tipeó directamente quien invoca el comando (no algo que
# un embed de Discord ya resolvió) -- cualquier host, protegido solo por el
# filtro de IP de r2.fetch_public_url (igual que check_gif_url_health en
# r2.py) y el tope de tamaño.


def test_fetch_media_bytes_descarga_de_cualquier_host(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size=None):
            yield b"contenido-de-otro-cdn"

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        discord_media.fetch_media_bytes("https://cdn-de-cualquier-lado.com/x.mp4", 1024)
    )

    assert data == b"contenido-de-otro-cdn"


def test_fetch_media_bytes_respeta_el_limite_de_tamano(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {"Content-Length": "2048"}

        def iter_content(self, chunk_size=None):
            yield b"x" * 2048

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        discord_media.fetch_media_bytes("https://cualquier-host.com/x.mp4", 1024)
    )

    assert data is None


def test_fetch_media_bytes_devuelve_none_si_el_status_no_es_200(monkeypatch):
    class _Resp:
        status_code = 404
        headers = {}

        def close(self):
            pass

    monkeypatch.setattr(r2, "fetch_public_url", lambda *a, **k: _Resp())

    data = asyncio.run(
        discord_media.fetch_media_bytes("https://cualquier-host.com/x.mp4", 1024)
    )

    assert data is None


def test_fetch_media_bytes_rechaza_ssrf():
    # Sin allowlist de host, la única defensa es el filtro de IP -- confirma
    # que sigue aplicando incluso sin el chequeo de is_direct_media_host.
    assert (
        asyncio.run(
            discord_media.fetch_media_bytes("http://127.0.0.1/internal.mp4", 1024)
        )
        is None
    )


def test_fetch_media_bytes_devuelve_none_si_la_conexion_falla(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("boom")

    monkeypatch.setattr(r2, "fetch_public_url", _raise)

    assert (
        asyncio.run(discord_media.fetch_media_bytes("https://ejemplo.com/x.mp4", 1024))
        is None
    )
