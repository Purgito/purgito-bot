"""Auditoría sección 9, ronda 3, punto 2: _pick_pool_image leía con
`requests.get(...).content` -- junta el cuerpo entero en memoria ANTES de
que el chequeo `len(...) <= MEME_MAX_BYTES` pudiera actuar. Mismo anti-patrón
que upload_gif_sync ya corrigió por chunks en r2.py (sección 4).

Hoy no hay ruta de entrada real: las URLs en corpus_images están acotadas a
MEME_MAX_BYTES desde que se guardaron (save_image_url solo se llama después
de un chequeo de tamaño, ver cogs/memes.py). El fix (_download_capped) cierra
la dependencia en ese invariante lejano -- ahora el propio punto de descarga
corta apenas se pasa del límite, sin importar qué guarde el pool.
"""

import cogs.memes as memes


class _FakeResp:
    def __init__(self, status_code, chunks):
        self.status_code = status_code
        self._chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_corta_apenas_supera_el_limite(monkeypatch):
    """El total de bytes leídos nunca debe pasar mucho más allá del límite:
    si leyera todo antes de cortar, esto tardaría y ocuparía memoria por el
    tamaño real del archivo, no por el límite configurado."""
    chunks = [b"x" * 100] * 50  # 5000 bytes en chunks de 100
    resp = _FakeResp(200, chunks)

    def fake_get(url, timeout, stream):
        assert stream is True, "sin stream=True se buferea todo antes del corte"
        return resp

    monkeypatch.setattr(memes.requests, "get", fake_get)
    resultado = memes._download_capped("https://x.test/img.png", max_bytes=250)

    assert resultado is None
    assert resp.closed


def test_devuelve_los_bytes_si_entra_en_el_limite(monkeypatch):
    chunks = [b"a" * 10, b"b" * 10, b"c" * 10]
    resp = _FakeResp(200, chunks)
    monkeypatch.setattr(memes.requests, "get", lambda url, timeout, stream: resp)

    resultado = memes._download_capped("https://x.test/img.png", max_bytes=1000)

    assert resultado == b"a" * 10 + b"b" * 10 + b"c" * 10
    assert resp.closed


def test_http_no_200_devuelve_none(monkeypatch):
    resp = _FakeResp(404, [])
    monkeypatch.setattr(memes.requests, "get", lambda url, timeout, stream: resp)

    assert memes._download_capped("https://x.test/img.png", max_bytes=1000) is None
    assert resp.closed


def test_justo_en_el_limite_se_acepta(monkeypatch):
    chunks = [b"x" * 50, b"y" * 50]  # exactamente 100
    resp = _FakeResp(200, chunks)
    monkeypatch.setattr(memes.requests, "get", lambda url, timeout, stream: resp)

    resultado = memes._download_capped("https://x.test/img.png", max_bytes=100)
    assert resultado == b"x" * 50 + b"y" * 50
