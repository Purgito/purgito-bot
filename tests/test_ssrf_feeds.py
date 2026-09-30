"""SSRF en las URLs que escribe un admin y el bot descarga: feeds RSS y
páginas de canal de YouTube.

Antes de este fix, `cogs.rss` y `cogs.youtube` hacían `requests.get` directo
sobre la URL del admin: se podía apuntar a localhost, a la red interna o al
endpoint de metadata de la nube (169.254.169.254), incluso vía un redirect, y
el cuerpo se leía entero en memoria. Ahora salen por `r2.fetch_public_bytes`
(filtro de IP pública en cada salto + tope de bytes + tope de tiempo total) y
YouTube exige además que el host sea youtube.com.
"""

import asyncio
import gzip
import http.server
import threading
import time

import pytest
import requests

import r2
from cogs import rss as rss_mod
from cogs import youtube as youtube_mod

_RSS = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>FEED-INTERNO</title>'
    b"<item><title>x</title><link>http://a</link></item></channel></rss>"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits.append(self.path)
        port = self.server.server_address[1]
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/interno")
            self.end_headers()
        elif self.path == "/404":
            self.send_response(404)
            self.end_headers()
        elif self.path == "/declarado-grande":
            self.send_response(200)
            self.send_header("Content-Length", "10000")
            self.end_headers()
            self.wfile.write(b"x" * 10000)
        elif self.path == "/sin-largo":
            # HTTP/1.0 sin Content-Length: el cuerpo termina al cerrar.
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 200_000)
        elif self.path == "/bomba":
            # ~20 KB comprimidos que descomprimen a 20 MB.
            body = gzip.compress(b"\0" * 20_000_000)
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/gotea":
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(200):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(_RSS)))
            self.end_headers()
            self.wfile.write(_RSS)

    def log_message(self, *args):
        pass


@pytest.fixture
def servidor_local():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.hits = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def host_publico_falso(monkeypatch, servidor_local):
    """Hace que `feed.test` "resuelva a una IP pública" (en realidad el server
    local), para poder ejercitar el camino feliz y los topes de fetch_public_bytes
    sin red. Cualquier otro host -- 127.0.0.1 incluido -- sigue pasando por el
    filtro real, así que un redirect a una IP interna sigue bloqueado."""
    real = r2._public_ip_for_host
    monkeypatch.setattr(
        r2,
        "_public_ip_for_host",
        lambda host: "127.0.0.1" if host == "feed.test" else real(host),
    )
    return f"http://feed.test:{servidor_local.server_address[1]}"


# ── RSS ──────────────────────────────────────────────────────────────────────


def test_rss_resolve_no_pide_una_ip_interna(servidor_local):
    url = f"http://127.0.0.1:{servidor_local.server_address[1]}/feed.xml"
    assert asyncio.run(rss_mod.resolve_rss_feed(url)) is None
    assert servidor_local.hits == []


def test_rss_get_latest_no_pide_una_ip_interna(servidor_local):
    url = f"http://127.0.0.1:{servidor_local.server_address[1]}/feed.xml"
    assert asyncio.run(rss_mod.get_latest_rss_item(url)) is None
    assert servidor_local.hits == []


def test_rss_resolve_no_sigue_un_redirect_a_ip_interna(
    servidor_local, host_publico_falso
):
    assert asyncio.run(rss_mod.resolve_rss_feed(f"{host_publico_falso}/redir")) is None
    # Llegó al primer salto (el host "público"), pero NO al destino del redirect.
    assert servidor_local.hits == ["/redir"]


def test_rss_resolve_camino_feliz(servidor_local, host_publico_falso):
    result = asyncio.run(rss_mod.resolve_rss_feed(f"{host_publico_falso}/ok"))
    assert result is not None
    assert result["title"] == "FEED-INTERNO"


def test_rss_resolve_rechaza_un_feed_demasiado_grande(
    servidor_local, host_publico_falso, monkeypatch
):
    monkeypatch.setattr(rss_mod, "_MAX_FEED_BYTES", 1024)
    assert (
        asyncio.run(rss_mod.resolve_rss_feed(f"{host_publico_falso}/declarado-grande"))
        is None
    )


# ── fetch_public_bytes ───────────────────────────────────────────────────────


def test_fetch_bytes_devuelve_el_cuerpo(host_publico_falso):
    assert r2.fetch_public_bytes(f"{host_publico_falso}/ok", 10_000) == _RSS


def test_fetch_bytes_rechaza_por_content_length_declarado(host_publico_falso):
    with pytest.raises(r2.FetchLimitExceeded):
        r2.fetch_public_bytes(f"{host_publico_falso}/declarado-grande", 1000)


def test_fetch_bytes_rechaza_sin_content_length(host_publico_falso):
    with pytest.raises(r2.FetchLimitExceeded):
        r2.fetch_public_bytes(f"{host_publico_falso}/sin-largo", 50_000)


def test_fetch_bytes_cuenta_bytes_ya_descomprimidos(host_publico_falso):
    with pytest.raises(r2.FetchLimitExceeded):
        r2.fetch_public_bytes(f"{host_publico_falso}/bomba", 100_000)


def test_fetch_bytes_corta_por_tiempo_total_aunque_llegue_algo_siempre(
    host_publico_falso,
):
    started = time.monotonic()
    with pytest.raises(r2.FetchLimitExceeded):
        r2.fetch_public_bytes(
            f"{host_publico_falso}/gotea", 10_000, total_timeout=0.4, timeout=5
        )
    assert time.monotonic() - started < 3


def test_fetch_bytes_conserva_el_status_en_el_http_error(host_publico_falso):
    """rss/youtube distinguen un 404 (feed borrado) de otros errores leyendo
    `e.response.status_code`: el helper tiene que seguir exponiéndolo."""
    with pytest.raises(requests.HTTPError) as exc:
        r2.fetch_public_bytes(f"{host_publico_falso}/404", 10_000)
    assert exc.value.response.status_code == 404


def test_fetch_bytes_bloquea_una_ip_interna(servidor_local):
    with pytest.raises(r2.BlockedTarget):
        r2.fetch_public_bytes(
            f"http://127.0.0.1:{servidor_local.server_address[1]}/ok", 10_000
        )
    assert servidor_local.hits == []


def test_rss_404_sigue_levantando_feed_not_found(host_publico_falso):
    with pytest.raises(rss_mod.RSSFeedNotFound):
        asyncio.run(rss_mod.get_latest_rss_item(f"{host_publico_falso}/404"))


# ── YouTube ──────────────────────────────────────────────────────────────────


def _no_debe_pedirse(*args, **kwargs):
    raise AssertionError("no debía hacerse ningún request")


@pytest.mark.parametrize(
    "entrada",
    [
        "http://127.0.0.1:1/x",
        "http://169.254.169.254/latest/meta-data/",
        "https://evil.example/?youtube.com",
        "evil.example/youtube.com/foo",
        "https://youtube.com.evil.example/channel",
    ],
)
def test_youtube_rechaza_hosts_que_no_son_youtube(entrada, monkeypatch):
    monkeypatch.setattr(r2, "fetch_public_bytes", _no_debe_pedirse)
    assert asyncio.run(youtube_mod._resolve_handle_to_channel_id(entrada)) is None


def test_youtube_resolve_no_pide_una_ip_interna(servidor_local):
    url = f"http://127.0.0.1:{servidor_local.server_address[1]}/yt"
    assert asyncio.run(youtube_mod.resolve_youtube_channel(url)) is None
    assert servidor_local.hits == []


@pytest.mark.parametrize(
    "entrada",
    [
        "@MrBeast",
        "MrBeast",
        "https://www.youtube.com/@MrBeast",
        "https://m.youtube.com/c/MrBeast",
        "youtube.com/user/MrBeast",
    ],
)
def test_youtube_sigue_resolviendo_entradas_legitimas(entrada, monkeypatch):
    canal = "UC" + "a" * 22
    pedidos = []

    def fake_fetch(url, max_bytes, **kwargs):
        pedidos.append(url)
        return f'<meta itemprop="channelId" content="{canal}">'.encode()

    monkeypatch.setattr(r2, "fetch_public_bytes", fake_fetch)
    assert asyncio.run(youtube_mod._resolve_handle_to_channel_id(entrada)) == canal
    assert all(youtube_mod._is_youtube_url(u) for u in pedidos)


def test_youtube_id_crudo_no_hace_ningun_request(monkeypatch):
    monkeypatch.setattr(r2, "fetch_public_bytes", _no_debe_pedirse)
    canal = "UC" + "b" * 22
    assert asyncio.run(youtube_mod._resolve_handle_to_channel_id(canal)) == canal


def test_is_youtube_url_valida_el_host_real():
    assert youtube_mod._is_youtube_url("https://www.youtube.com/@x")
    assert youtube_mod._is_youtube_url("https://youtube.com/@x")
    assert not youtube_mod._is_youtube_url("https://evil.com/youtube.com")
    assert not youtube_mod._is_youtube_url("https://notyoutube.com/@x")
    assert not youtube_mod._is_youtube_url("https://youtube.com.evil.example/")
