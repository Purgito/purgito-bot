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


def test_index_html_tambien_tiene_la_csp():
    """Auditoría sección 12: index.html se escribe a mano (build_docs.py no
    lo regenera, solo le resella el ?v=) y por eso había quedado afuera de
    la CSP que sí tienen todas las páginas generadas -- justo la de más
    tráfico del sitio entero."""
    html = (LANDING / "index.html").read_text("utf-8")
    assert '<meta http-equiv="Content-Security-Policy"' in html
    assert build_docs.LANDING_CSP in html


def test_el_hash_del_script_de_redirect_de_index_es_correcto():
    html = (LANDING / "index.html").read_text("utf-8")
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"sha256-{digest}" in build_docs.LANDING_CSP


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


def test_el_no_setea_style_por_setattribute():
    """Auditoría sección 12: sin unsafe-inline en style-src, CSP bloquea el
    atributo style="..." sea escrito en HTML o puesto con setAttribute --
    confirmado en un navegador real (no solo por lectura del spec). el() en
    dom.js es la fábrica de nodos que usa TODO el resto del dashboard: si
    vuelve a caer en el fallback genérico de setAttribute(k, v) para la clave
    'style', cada color/display dinámico armado con el(..., { style }) -- la
    barra de color de los embeds, los puntos de color de roles, los toggles
    de display:none -- queda viniendo transparente/sin aplicar en producción,
    en silencio (CSP no crashea, solo descarta el estilo).

    node.style.cssText = v, en cambio, no pasa por el atributo -- confirmado
    que no dispara la CSP -- así que tiene que ser esa rama, no
    setAttribute('style', ...).
    """
    dom_js = (LANDING / "js" / "core" / "dom.js").read_text("utf-8")
    assert "node.style.cssText = v" in dom_js
    assert "setAttribute('style'" not in dom_js
    assert 'setAttribute("style"' not in dom_js
