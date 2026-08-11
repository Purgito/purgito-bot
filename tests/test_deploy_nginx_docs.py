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


def test_aop_documenta_el_bypass_de_rate_limits_no_solo_waf_cache():
    """Auditoría sección 11, ronda 1: sin AOP (ni un allowlist de IPs de
    Cloudflare como alternativa), cualquiera que le hable directo a nginx
    puede forjar CF-Connecting-IP -- el header que _client_ip() prioriza para
    la clave de TODOS los rate limit por IP de la app. El comentario de AOP
    documentaba esto solo como bypass de WAF/cache; si un futuro editor
    recorta la explicación completa, este test tiene que fallar."""
    inicio = DEPLOY.index("Authenticated Origin Pulls (desactivado)")
    bloque = DEPLOY[inicio : inicio + 2500]
    assert "CF-Connecting-IP" in bloque
    assert "rate limit" in bloque
    assert "cloudflare.com/ips" in bloque


def test_documenta_cabeceras_de_seguridad_a_nivel_server():
    for header in (
        "add_header X-Content-Type-Options nosniff always;",
        "add_header X-Frame-Options DENY always;",
        "add_header Referrer-Policy strict-origin-when-cross-origin always;",
    ):
        assert header in DEPLOY, header


def test_documenta_server_tokens_off():
    """Auditoría sección 12: sin esto nginx manda "Server: nginx/1.x.x" --
    la versión exacta ayuda a buscar CVEs puntuales y no le sirve a nadie
    real. Mismo motivo que webapi.py pisa el Server header de aiohttp."""
    assert "server_tokens off;" in DEPLOY


def test_documenta_activar_hsts_en_cloudflare():
    """Auditoría sección 12: la cookie de sesión ya es Secure (no viaja por
    HTTP), pero eso no cubre el PRIMER request desde una red hostil antes de
    cualquier redirect a HTTPS -- HSTS es lo único que cierra esa ventana."""
    inicio = DEPLOY.index("### Cloudflare (DNS + SSL)")
    bloque = DEPLOY[inicio : inicio + 1200]
    assert "HSTS" in bloque
