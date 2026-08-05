"""DEPLOY.md documenta la config de nginx real del droplet (no versionada);
estos tests son la única red que detecta si alguien reintroduce el bug de
X-Forwarded-For spoofeable, o si el bloque de Authenticated Origin Pulls se
pierde en una edición futura.
"""

import re
from pathlib import Path

DEPLOY = (Path(__file__).resolve().parents[1] / "DEPLOY.md").read_text("utf-8")


def test_ninguna_directiva_usa_proxy_add_x_forwarded_for():
    """$proxy_add_x_forwarded_for anexa a un X-Forwarded-For que puede venir
    forjado por el cliente; _client_ip() en webapi.py lee el primer valor de
    la lista, así que anexar en vez de reemplazar permite spoofearla."""
    directivas = re.findall(r"proxy_set_header X-Forwarded-For [^\n;]+;", DEPLOY)
    assert directivas, "no se encontró ninguna directiva X-Forwarded-For"
    for d in directivas:
        assert d == "proxy_set_header X-Forwarded-For $remote_addr;", d


def test_documenta_authenticated_origin_pulls_comentado():
    assert "ssl_client_certificate" in DEPLOY
    assert "# ssl_verify_client on;" in DEPLOY


def test_documenta_cabeceras_de_seguridad_a_nivel_server():
    for header in (
        "add_header X-Content-Type-Options nosniff always;",
        "add_header X-Frame-Options DENY always;",
        "add_header Referrer-Policy strict-origin-when-cross-origin always;",
    ):
        assert header in DEPLOY, header
