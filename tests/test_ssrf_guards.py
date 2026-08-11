"""Auditoría sección 9, ronda 2, punto 1: SSRF en lo que el servidor fetchea.

Dos superficies distintas:

- r2.check_gif_url_health, que sale a buscar `media_url or url` de cada GIF y
  le devuelve el resultado tri-estado al panel. Sin filtro era un oráculo para
  sondear la red interna del droplet (y seguía redirects, así que ni siquiera
  hacía falta guardar una URL interna: alcanzaba con que un host permitido
  redirigiera).
- cogs.gifs.resolve_media_url, que guarda en media_url lo que devuelva un
  oEmbed de terceros. Ese valor después se postea en Discord, se fetchea acá y
  se carga como <img src> en el dashboard.
"""

import asyncio
import http.server
import socketserver
import threading

import pytest

import r2
from cogs import gifs


# ── Servidor local que hace de "destino interno" ─────────────────────────────


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        if self.path == "/redir":
            self.send_response(302)
            self.send_header(
                "Location", f"http://127.0.0.1:{self.server.server_address[1]}/interno"
            )
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/gif")
        self.end_headers()

    do_GET = do_HEAD

    def log_message(self, *args):
        pass


@pytest.fixture
def servidor_local():
    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()


def test_health_check_no_toca_una_ip_interna(servidor_local):
    assert r2.check_gif_url_health(f"{servidor_local}/interno") == "unreachable"


def test_health_check_no_sigue_un_redirect_a_ip_interna(servidor_local):
    """El filtro se aplica en CADA salto: si solo se validara el host inicial,
    un host permitido que redirige alcanzaba para evadirlo entero."""
    assert r2.check_gif_url_health(f"{servidor_local}/redir") == "unreachable"


def test_destino_bloqueado_no_cuenta_como_dead(servidor_local):
    """ "dead" acumula strikes que terminan borrando el GIF; _public_ip_for_host
    también devuelve None si el DNS falla, así que un corte de DNS no puede
    traducirse en un borrado masivo de corpus."""
    assert r2.check_gif_url_health(f"{servidor_local}/interno") != "dead"


@pytest.mark.parametrize(
    "host",
    ["localhost", "metadata.google.internal"],
)
def test_public_ip_for_host_rechaza_destinos_internos(host):
    assert r2._public_ip_for_host(host) is None


def test_fetch_public_url_corta_cadenas_de_redirects_infinitas(monkeypatch):
    """Un bucle de redirects entre hosts públicos no debe colgar el thread."""
    saltos = []

    class _Resp:
        status_code = 302
        headers = {"Location": "https://b.test/x"}

        def close(self):
            pass

    def _fake(url, **kwargs):
        saltos.append(url)
        return _Resp()

    monkeypatch.setattr(r2, "_public_ip_for_host", lambda h: "93.184.216.34")
    monkeypatch.setattr(
        r2, "_pinned_dns", lambda h, ip: __import__("contextlib").nullcontext()
    )

    with pytest.raises(r2.BlockedTarget):
        r2.fetch_public_url(_fake, "https://a.test/x")
    assert len(saltos) == r2._MAX_REDIRECTS + 1


def test_fetch_public_url_deja_pasar_un_host_publico(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {"Content-Type": "image/gif"}

        def close(self):
            pass

    monkeypatch.setattr(r2, "_public_ip_for_host", lambda h: "93.184.216.34")
    monkeypatch.setattr(
        r2, "_pinned_dns", lambda h, ip: __import__("contextlib").nullcontext()
    )

    resp = r2.fetch_public_url(
        lambda url, **kw: _Resp(), "https://media.tenor.com/x.gif"
    )
    assert resp.status_code == 200


# ── resolve_media_url: lo que devuelve el oEmbed no es de fiar ───────────────


def _fake_oembed(payload):
    class _Resp:
        def json(self):
            return payload

    return lambda url, **kwargs: _Resp()


@pytest.mark.parametrize(
    "devuelto",
    [
        "http://169.254.169.254/latest/meta-data/",  # metadata de cloud
        "http://127.0.0.1:8080/health",  # servicio interno
        "https://evil.test/pixel.gif",  # host cualquiera
        "javascript:alert(1)",  # no es ni http
        "file:///etc/passwd",
        None,
        123,
    ],
)
def test_media_url_fuera_de_los_hosts_de_gifs_se_descarta(monkeypatch, devuelto):
    import requests

    monkeypatch.setattr(requests, "get", _fake_oembed({"thumbnail_url": devuelto}))
    resultado = asyncio.run(gifs.resolve_media_url("https://tenor.com/view/algo-123"))
    assert resultado is None


def test_media_url_de_un_host_de_gifs_se_acepta(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        _fake_oembed({"thumbnail_url": "https://media.tenor.com/x.png"}),
    )
    resultado = asyncio.run(gifs.resolve_media_url("https://tenor.com/view/algo-123"))
    assert resultado == "https://media.tenor.com/x.png"


def test_giphy_usa_el_campo_url(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        _fake_oembed({"url": "https://media.giphy.com/media/x/giphy.gif"}),
    )
    resultado = asyncio.run(gifs.resolve_media_url("https://giphy.com/gifs/algo-123"))
    assert resultado == "https://media.giphy.com/media/x/giphy.gif"


def test_host_se_compara_de_verdad_no_por_substring(monkeypatch):
    """ "https://evil.test/?x=tenor.com" contiene "tenor.com" pero no es tenor:
    con el chequeo por substring, esa URL disparaba el oEmbed igual."""
    import requests

    llamadas = []

    def _spy(url, **kwargs):
        llamadas.append(url)
        raise AssertionError("no debería haberse consultado ningún oEmbed")

    monkeypatch.setattr(requests, "get", _spy)
    assert asyncio.run(gifs.resolve_media_url("https://evil.test/?x=tenor.com")) is None
    assert asyncio.run(gifs.resolve_media_url("https://evil.test/giphy.com/x")) is None
    assert llamadas == []
