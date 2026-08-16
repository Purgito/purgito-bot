"""Verifica el sistema centralizado de Open Graph, Twitter cards y canonical metadata."""

import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
sys.path.insert(0, str(LANDING))
import build_docs  # noqa: E402


def test_todas_las_paginas_publicas_tienen_opengraph_y_twitter_metadata_versionada():
    """Verifica que cada página pública contiene Open Graph y Twitter metadata con hash ?v=."""
    expected_hash = build_docs.og_image_digest()
    assert len(expected_hash) == 8, f"Hash inválido: {expected_hash}"
    expected_image_url = f"https://purgito.app/assets/og-purgito.png?v={expected_hash}"

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
        r'<meta property="og:image" content="https://purgito\.app/assets/og-purgito\.png\?v=[0-9a-f]{8}">',
        r'<meta property="og:image:width" content="\d+">',
        r'<meta property="og:image:height" content="\d+">',
        r'<meta property="og:image:alt" content="[^"]+">',
        r'<meta property="og:locale" content="es_ES">',
        r'<meta name="twitter:card" content="summary">',
        r'<meta name="twitter:title" content="[^"]+">',
        r'<meta name="twitter:description" content="[^"]+">',
        r'<meta name="twitter:image" content="https://purgito\.app/assets/og-purgito\.png\?v=[0-9a-f]{8}">',
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

        # og:image y twitter:image con el hash exacto del asset actual
        assert f'<meta property="og:image" content="{expected_image_url}">' in html, (
            f"og:image con hash desactualizado o incorrecto en {file_path}"
        )
        assert f'<meta name="twitter:image" content="{expected_image_url}">' in html, (
            f"twitter:image con hash desactualizado o incorrecto en {file_path}"
        )

        # Sin referencias estáticas sin versionar
        assert 'content="https://purgito.app/assets/og-purgito.png"' not in html, (
            f"Referencia estática sin ?v= encontrada en {file_path}"
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
        assert html.count('name="twitter:image"') == 1, (
            f"twitter:image duplicado en {file_path}"
        )
        assert html.count('property="og:url"') == 1, f"og:url duplicado en {file_path}"
        assert html.count('rel="canonical"') == 1, f"canonical duplicado en {file_path}"


def test_asset_de_imagen_og_default_existe_en_disco_y_tiene_dimensiones_validas():
    """Verifica que el fallback og-purgito.png existe en landing/assets/ y es accesible."""
    og_img = LANDING / "assets" / "og-purgito.png"
    assert og_img.exists(), "Falta landing/assets/og-purgito.png"
    assert 10_000 < og_img.stat().st_size < 500_000

    # Verifica que el hash calculado coincide byte a byte con el archivo en disco
    actual_hash = hashlib.sha256(og_img.read_bytes()).hexdigest()[:8]
    assert build_docs.og_image_digest() == actual_hash


def test_cambio_en_asset_og_actualiza_hash_y_url(tmp_path, monkeypatch):
    """Verifica que modificar el contenido del asset cambia el hash, la URL y el sellado."""
    fake_landing = tmp_path / "landing"
    fake_assets = fake_landing / "assets"
    fake_assets.mkdir(parents=True)
    og_file = fake_assets / "og-purgito.png"

    for name in ("style.css", "script.js", "dash.css"):
        (fake_landing / name).write_text("/* dummy */", "utf-8")

    # Versión 1
    og_file.write_bytes(b"mock_png_binary_content_v1")
    monkeypatch.setattr(build_docs, "LANDING", fake_landing)

    hash_v1 = build_docs.og_image_digest()
    url_v1 = build_docs.get_default_og_image()
    assert hash_v1 == hashlib.sha256(b"mock_png_binary_content_v1").hexdigest()[:8]
    assert url_v1 == f"https://purgito.app/assets/og-purgito.png?v={hash_v1}"

    # Versión 2 (modificación del asset)
    og_file.write_bytes(b"mock_png_binary_content_v2_with_different_data")
    hash_v2 = build_docs.og_image_digest()
    url_v2 = build_docs.get_default_og_image()
    assert hash_v2 == hashlib.sha256(b"mock_png_binary_content_v2_with_different_data").hexdigest()[:8]
    assert url_v2 == f"https://purgito.app/assets/og-purgito.png?v={hash_v2}"
    assert hash_v1 != hash_v2
    assert url_v1 != url_v2

    # Verifica que stamp() actualiza etiquetas sin versionar o con hash previo
    unversioned_html = '<meta property="og:image" content="https://purgito.app/assets/og-purgito.png">'
    stamped = build_docs.stamp(unversioned_html)
    assert f'content="https://purgito.app/assets/og-purgito.png?v={hash_v2}"' in stamped

    # Verifica que stamp() actualiza una versión previa (re-sellado)
    stamped_again = build_docs.stamp(f'<meta property="og:image" content="https://purgito.app/assets/og-purgito.png?v={hash_v1}">')
    assert f'content="https://purgito.app/assets/og-purgito.png?v={hash_v2}"' in stamped_again
    assert hash_v1 not in stamped_again


def test_no_quedan_referencias_estaticas_sin_version_en_html_del_sitio():
    """Escanea todos los archivos HTML en landing/ para asegurar que no hay URLs de og-purgito sin ?v=."""
    html_files = list(LANDING.rglob("*.html"))
    assert len(html_files) > 0, "No se encontraron archivos HTML en landing/"

    for html_file in html_files:
        content = html_file.read_text("utf-8")
        if "og-purgito.png" in content:
            matches = re.findall(r'https://purgito\.app/assets/og-purgito\.png(?:\?v=([0-9a-f]+))?', content)
            assert matches, f"No se pudo parsear og-purgito.png en {html_file}"
            for m in matches:
                assert len(m) == 8, (
                    f"URL de og-purgito sin hash de 8 caracteres en {html_file}: {m}"
                )

