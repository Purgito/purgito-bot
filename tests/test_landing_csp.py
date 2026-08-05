"""La CSP de la landing (meta http-equiv, generada por build_docs.py) tiene
que cubrir justo lo que el sitio carga -- ver la investigación dejada como
comentario junto a LANDING_CSP en build_docs.py. Si algún día se agrega un
host externo nuevo (otra fuente, otro CDN de gifs) y no se suma acá, el sitio
queda roto en silencio hasta que alguien mira la consola del navegador.
"""

import hashlib
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"

sys.path.insert(0, str(LANDING))
import build_docs  # noqa: E402


def test_las_paginas_generadas_tienen_la_csp():
    for page in build_docs.HTML_PAGES + build_docs.PAGES:
        html = (LANDING / "es" / page["slug"] / "index.html").read_text("utf-8")
        assert '<meta http-equiv="Content-Security-Policy"' in html, page["slug"]
        assert build_docs.LANDING_CSP in html, page["slug"]


def test_la_csp_no_abre_unsafe_inline():
    assert "unsafe-inline" not in build_docs.LANDING_CSP


def test_el_hash_cubre_el_onerror_inline_que_usa_el_sitio():
    """Si el string de onerror cambia y el hash no se actualiza, el fallback
    de imagen rota queda bloqueado en producción (no crashea, pero se rompe
    en silencio)."""
    onerrors = set()
    for path in list((LANDING / "es").rglob("index.html")) + [LANDING / "index.html"]:
        onerrors.update(re.findall(r'onerror="([^"]*)"', path.read_text("utf-8")))
    assert onerrors, "no se encontró ningún onerror inline para verificar"
    for handler in onerrors:
        digest = base64.b64encode(hashlib.sha256(handler.encode()).digest()).decode()
        assert f"sha256-{digest}" in build_docs.LANDING_CSP, handler


def test_permite_las_fuentes_y_el_iframe_de_tenor_que_usa_el_sitio():
    style_css = (LANDING / "style.css").read_text("utf-8")
    assert "fonts.googleapis.com" in style_css  # @import de las fuentes
    assert "fonts.googleapis.com" in build_docs.LANDING_CSP
    assert "fonts.gstatic.com" in build_docs.LANDING_CSP

    gifs_js = (LANDING / "js" / "tabs" / "gifs.js").read_text("utf-8")
    assert "tenor.com/embed" in gifs_js
    assert "frame-src https://tenor.com" in build_docs.LANDING_CSP
