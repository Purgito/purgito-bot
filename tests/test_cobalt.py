"""Cliente de cobalt (src/cobalt.py): respaldo de "!dl". Nada de red real:
requests.post/get y r2.fetch_public_url se reemplazan por respuestas falsas.
Cubre qué se le manda a la instancia, cómo se interpreta cada `status` de su
respuesta, que un tunnel siempre se baje de COBALT_API_URL y no del host que
diga la respuesta, el filtro SSRF para todo lo demás, los topes de tamaño, y
que ningún camino de error deje el directorio temporal en disco.
"""

import os
import tempfile

import pytest
import requests

import cobalt
import r2

BASE = "http://127.0.0.1:9000"
LINK = "https://www.instagram.com/reel/abc123"


class FakeResp:
    def __init__(self, status_code=200, payload=None, headers=None, chunks=()):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._chunks = chunks
        self.closed = False

    def json(self):
        if self._payload is None:
            raise ValueError("no es JSON")
        return self._payload

    def iter_content(self, chunk_size=None):
        yield from self._chunks

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def cobalt_config(monkeypatch):
    monkeypatch.setattr(cobalt, "COBALT_API_URL", BASE)
    monkeypatch.setattr(cobalt, "COBALT_API_KEY", "")


@pytest.fixture
def tmp_dirs(monkeypatch):
    """Anota cada directorio temporal que crea el cliente."""
    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def tracked(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        created.append(d)
        return d

    monkeypatch.setattr(cobalt.tempfile, "mkdtemp", tracked)
    yield created
    import shutil

    for d in created:
        shutil.rmtree(d, ignore_errors=True)


def _patch_http(monkeypatch, post_payload, file_resp=None, post_status=200):
    """Reemplaza requests.post por una respuesta fija y requests.get por una
    que anota la URL pedida. Devuelve la lista `gets` y la de `posts`."""
    posts: list[dict] = []
    gets: list[dict] = []

    def fake_post(url, **kwargs):
        posts.append({"url": url, **kwargs})
        return FakeResp(post_status, post_payload)

    def fake_get(url, **kwargs):
        gets.append({"url": url, **kwargs})
        return file_resp if file_resp is not None else FakeResp(chunks=[b"video"])

    monkeypatch.setattr(cobalt.requests, "post", fake_post)
    monkeypatch.setattr(cobalt.requests, "get", fake_get)
    return posts, gets


# ── configured ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["", "127.0.0.1:9000", "ftp://host", "http://"])
def test_configured_es_false_sin_una_url_http_valida(monkeypatch, value):
    monkeypatch.setattr(cobalt, "COBALT_API_URL", value)
    assert not cobalt.configured()


@pytest.mark.parametrize("value", [BASE, "https://cobalt.example.com"])
def test_configured_es_true_con_una_url_http_o_https(monkeypatch, value):
    monkeypatch.setattr(cobalt, "COBALT_API_URL", value)
    assert cobalt.configured()


# ── la petición ───────────────────────────────────────────────────────────────


def test_pide_el_video_a_la_instancia_propia(monkeypatch, tmp_dirs):
    posts, _ = _patch_http(
        monkeypatch, {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"}
    )

    cobalt.download_video(LINK, 1024)

    assert posts[0]["url"] == f"{BASE}/"
    body = posts[0]["json"]
    assert body["url"] == LINK
    assert body["videoQuality"] == "720"
    # Fuerza el tunnel: así casi nada sale por la ruta de URLs de terceros.
    assert body["alwaysProxy"] is True
    assert "Authorization" not in posts[0]["headers"]


def test_manda_la_api_key_si_esta_configurada(monkeypatch, tmp_dirs):
    monkeypatch.setattr(cobalt, "COBALT_API_KEY", "abc-123")
    posts, _ = _patch_http(
        monkeypatch, {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"}
    )

    cobalt.download_video(LINK, 1024)

    assert posts[0]["headers"]["Authorization"] == "Api-Key abc-123"


# ── tunnel ────────────────────────────────────────────────────────────────────


def test_tunnel_descarga_el_archivo_y_respeta_la_extension(monkeypatch, tmp_dirs):
    _patch_http(
        monkeypatch,
        {"status": "tunnel", "url": f"{BASE}/tunnel?id=1", "filename": "clip.webm"},
        FakeResp(chunks=[b"uno", b"dos"]),
    )

    path = cobalt.download_video(LINK, 1024)

    assert os.path.dirname(path) == tmp_dirs[0]
    assert path.endswith("cobalt_video.webm")
    with open(path, "rb") as f:
        assert f.read() == b"unodos"


def test_tunnel_se_descarga_siempre_de_la_instancia_configurada(monkeypatch, tmp_dirs):
    # La respuesta trae el API_URL público de cobalt (otro host que el
    # loopback con el que habla el bot): se descarga igual de COBALT_API_URL,
    # conservando solo la query firmada.
    _, gets = _patch_http(
        monkeypatch,
        {
            "status": "tunnel",
            "url": "https://cobalt.example.com/tunnel?id=x&sig=y",
            "filename": "a.mp4",
        },
    )

    cobalt.download_video(LINK, 1024)

    assert [g["url"] for g in gets] == [f"{BASE}/tunnel?id=x&sig=y"]
    assert gets[0]["allow_redirects"] is False


@pytest.mark.parametrize(
    "filename", [None, "sin-extension", "raro.exe", "../../etc/passwd", "x.MP4"]
)
def test_la_extension_sale_de_una_lista_cerrada(monkeypatch, tmp_dirs, filename):
    payload = {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"}
    if filename is not None:
        payload["filename"] = filename
    _patch_http(monkeypatch, payload)

    path = cobalt.download_video(LINK, 1024)

    assert path.endswith("cobalt_video.mp4")
    assert os.path.dirname(path) == tmp_dirs[0]


# ── redirect y picker: URLs de terceros, con filtro SSRF ─────────────────────


def test_redirect_pasa_por_el_filtro_ssrf_y_no_por_requests_directo(
    monkeypatch, tmp_dirs
):
    _, gets = _patch_http(
        monkeypatch, {"status": "redirect", "url": "https://cdn.example.com/v.mp4"}
    )
    fetched: list[str] = []

    def fake_fetch(method, url, **kwargs):
        fetched.append(url)
        return FakeResp(chunks=[b"video"])

    monkeypatch.setattr(r2, "fetch_public_url", fake_fetch)

    path = cobalt.download_video(LINK, 1024)

    assert fetched == ["https://cdn.example.com/v.mp4"]
    assert gets == []
    assert os.path.exists(path)


def test_redirect_a_una_ip_interna_se_rechaza_y_limpia_el_directorio(
    monkeypatch, tmp_dirs
):
    _patch_http(
        monkeypatch, {"status": "redirect", "url": "http://169.254.169.254/latest"}
    )

    def blocked(method, url, **kwargs):
        raise r2.BlockedTarget(url)

    monkeypatch.setattr(r2, "fetch_public_url", blocked)

    with pytest.raises(cobalt.CobaltError):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])


def test_picker_elige_el_primer_video_y_saltea_las_fotos(monkeypatch, tmp_dirs):
    _, gets = _patch_http(
        monkeypatch,
        {
            "status": "picker",
            "picker": [
                {"type": "photo", "url": f"{BASE}/tunnel?id=foto"},
                {"type": "video", "url": f"{BASE}/tunnel?id=video"},
                {"type": "video", "url": f"{BASE}/tunnel?id=otro"},
            ],
        },
    )

    cobalt.download_video(LINK, 1024)

    assert [g["url"] for g in gets] == [f"{BASE}/tunnel?id=video"]


def test_picker_solo_con_fotos_es_un_post_sin_video(monkeypatch, tmp_dirs):
    _patch_http(
        monkeypatch,
        {"status": "picker", "picker": [{"type": "photo", "url": f"{BASE}/t?id=1"}]},
    )

    with pytest.raises(cobalt.CobaltNoVideo):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])


# ── respuestas que no sirven ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "error", "error": {"code": "error.api.fetch.empty"}},
        {"status": "error"},
        {"status": "local-processing", "type": "merge"},
        {"status": "inventado"},
        {"status": "tunnel"},
        {"status": "redirect", "url": ""},
        ["no", "es", "un", "objeto"],
    ],
)
def test_respuestas_que_no_sirven_son_cobalt_error_y_limpian(
    monkeypatch, tmp_dirs, payload
):
    _patch_http(monkeypatch, payload)

    with pytest.raises(cobalt.CobaltError):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])


def test_respuesta_que_no_es_json_es_cobalt_error(monkeypatch, tmp_dirs):
    _patch_http(monkeypatch, None, post_status=502)

    with pytest.raises(cobalt.CobaltError):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])


def test_error_json_con_http_4xx_se_lee_igual(monkeypatch, tmp_dirs):
    _patch_http(
        monkeypatch,
        {"status": "error", "error": {"code": "error.api.link.unsupported"}},
        post_status=400,
    )

    with pytest.raises(cobalt.CobaltError, match="error.api.link.unsupported"):
        cobalt.download_video(LINK, 1024)


def test_instancia_caida_es_cobalt_error(monkeypatch, tmp_dirs):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("rechazada")

    monkeypatch.setattr(cobalt.requests, "post", boom)

    with pytest.raises(cobalt.CobaltError):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])


def test_descarga_que_no_devuelve_200_es_cobalt_error(monkeypatch, tmp_dirs):
    _patch_http(
        monkeypatch,
        {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"},
        FakeResp(status_code=404),
    )

    with pytest.raises(cobalt.CobaltError):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])


def test_archivo_vacio_es_cobalt_error(monkeypatch, tmp_dirs):
    _patch_http(
        monkeypatch,
        {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"},
        FakeResp(chunks=[]),
    )

    with pytest.raises(cobalt.CobaltError):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])


# ── topes de tamaño y de tiempo ──────────────────────────────────────────────


def test_rechaza_por_content_length_sin_bajar_nada(monkeypatch, tmp_dirs):
    resp = FakeResp(headers={"Content-Length": "2048"}, chunks=[b"x" * 2048])
    _patch_http(monkeypatch, {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"}, resp)

    with pytest.raises(cobalt.CobaltTooLarge) as exc:
        cobalt.download_video(LINK, 1024)

    assert exc.value.max_bytes == 1024
    assert resp.closed
    assert not os.path.exists(tmp_dirs[0])


def test_corta_mientras_baja_si_no_hay_content_length(monkeypatch, tmp_dirs):
    resp = FakeResp(chunks=[b"x" * 600, b"x" * 600])
    _patch_http(monkeypatch, {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"}, resp)

    with pytest.raises(cobalt.CobaltTooLarge):
        cobalt.download_video(LINK, 1024)

    assert resp.closed
    assert not os.path.exists(tmp_dirs[0])


def test_corta_si_la_descarga_se_pasa_del_tiempo_total(monkeypatch, tmp_dirs):
    monkeypatch.setattr(cobalt, "_DOWNLOAD_DEADLINE_SECONDS", -1)
    _patch_http(
        monkeypatch,
        {"status": "tunnel", "url": f"{BASE}/tunnel?id=1"},
        FakeResp(chunks=[b"a", b"b"]),
    )

    with pytest.raises(cobalt.CobaltError, match="tardó"):
        cobalt.download_video(LINK, 1024)

    assert not os.path.exists(tmp_dirs[0])
