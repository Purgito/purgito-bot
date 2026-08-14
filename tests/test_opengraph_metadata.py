"""Verifica el sistema centralizado de Open Graph, Twitter cards y canonical metadata."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
sys.path.insert(0, str(LANDING))
import build_docs  # noqa: E402


def test_todas_las_paginas_publicas_tienen_opengraph_y_twitter_metadata():
    """Verifica que cada página pública generada e index.html contiene Open Graph completo."""
    pages_to_check = [
        (LANDING / "index.html", "https://purgito.app/"),
    ]
    for page in build_docs.HTML_PAGES + build_docs.PAGES:
        pages_to_check.append(
            (
                LANDING / "es" / page["slug"] / "index.html",
                f"https://purgito.app/es/{page['slug']}",
            )
        )

    required_tags = [
        r'<meta property="og:type" content="[^"]+">',
        r'<meta property="og:site_name" content="Purgito">',
        r'<meta property="og:title" content="[^"]+">',
        r'<meta property="og:description" content="[^"]+">',
        r'<meta property="og:image" content="https://purgito\.app/[^"]+">',
        r'<meta property="og:image:width" content="\d+">',
        r'<meta property="og:image:height" content="\d+">',
        r'<meta property="og:image:alt" content="[^"]+">',
        r'<meta property="og:locale" content="es_ES">',
        r'<meta name="twitter:card" content="summary">',
        r'<meta name="twitter:title" content="[^"]+">',
        r'<meta name="twitter:description" content="[^"]+">',
        r'<meta name="twitter:image" content="https://purgito\.app/[^"]+">',
    ]

    for file_path, canonical_url in pages_to_check:
        assert file_path.exists(), f"El archivo {file_path} no existe"
        html = file_path.read_text("utf-8")

        # Canonical y og:url exactos
        assert f'<meta property="og:url" content="{canonical_url}">' in html, (
            f"og:url incorrecto en {file_path}"
        )
        assert f'<link rel="canonical" href="{canonical_url}">' in html, (
            f"canonical incorrecto en {file_path}"
        )

        # Todas las tags requeridas presentes
        for pattern in required_tags:
            assert re.search(pattern, html), f"Falta el patrón {pattern} en {file_path}"

        # Sin duplicación de tags de metadata
        assert html.count('property="og:title"') == 1, (
            f"og:title duplicado en {file_path}"
        )
        assert html.count('property="og:description"') == 1, (
            f"og:description duplicado en {file_path}"
        )
        assert html.count('property="og:image"') == 1, (
            f"og:image duplicado en {file_path}"
        )
        assert html.count('property="og:url"') == 1, f"og:url duplicado en {file_path}"
        assert html.count('rel="canonical"') == 1, f"canonical duplicado en {file_path}"


def test_asset_de_imagen_og_default_existe_en_disco_y_tiene_dimensiones_validas():
    """Verifica que el fallback og-purgito.png existe en landing/assets/ y es accesible."""
    og_img = LANDING / "assets" / "og-purgito.png"
    assert og_img.exists(), "Falta landing/assets/og-purgito.png"
    # El archivo debe tener tamaño razonable (< 500KB)
    assert 10_000 < og_img.stat().st_size < 500_000
