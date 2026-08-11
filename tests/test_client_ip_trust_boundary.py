"""Auditoría sección 11, ronda 1, punto 6: header custom controlado
completamente por el cliente, usado para una decisión de seguridad.

_client_ip() es la clave de bucket de TODOS los _rate_ok() de webapi.py.
Prioriza CF-Connecting-IP sobre X-Forwarded-For -- correcto para tráfico que
sí pasó por Cloudflare (ver DEPLOY.md: nginx pisa X-Forwarded-For con
$remote_addr, así que ahí solo llega la IP de borde de Cloudflare, inútil
como clave de rate limit), pero quien le habla DIRECTO a nginx (sin AOP ni
un allowlist de IPs de Cloudflare, ninguno de los dos activo hoy) puede
mandar el CF-Connecting-IP que quiera -- nada en esta capa de código puede
distinguir "esto lo puso Cloudflare" de "esto lo forjó el cliente".

No hay fix de código posible acá (es un problema de infraestructura, ver el
comentario de _client_ip y el bloque de Authenticated Origin Pulls en
DEPLOY.md) -- este test fija el orden de prioridad ACTUAL como documentación
ejecutable, para que quede explícito y no se rompa en silencio en un futuro
refactor.
"""

from types import SimpleNamespace

import webapi


def _request(headers=None, remote="203.0.113.9"):
    return SimpleNamespace(headers=headers or {}, remote=remote)


def test_cf_connecting_ip_gana_aunque_sea_arbitrario():
    """El cliente controla este header por completo si le habla directo a
    nginx: el código lo acepta tal cual, sin ninguna verificación."""
    req = _request(headers={"CF-Connecting-IP": "cualquier-cosa-que-el-cliente-mande"})
    assert webapi._client_ip(req) == "cualquier-cosa-que-el-cliente-mande"


def test_cf_connecting_ip_gana_sobre_x_forwarded_for():
    req = _request(
        headers={
            "CF-Connecting-IP": "1.2.3.4",
            "X-Forwarded-For": "5.6.7.8",
        }
    )
    assert webapi._client_ip(req) == "1.2.3.4"


def test_sin_cf_connecting_ip_usa_x_forwarded_for():
    """X-Forwarded-For sí lo protege nginx (documentado + testeado en
    test_deploy_nginx_docs.py): pisado con $remote_addr, nunca anexado a lo
    que mande el cliente."""
    req = _request(headers={"X-Forwarded-For": "5.6.7.8, 9.9.9.9"})
    assert webapi._client_ip(req) == "5.6.7.8"


def test_sin_headers_cae_a_remote():
    req = _request(headers={}, remote="10.0.0.1")
    assert webapi._client_ip(req) == "10.0.0.1"


def test_generar_ips_distintas_por_request_agota_cada_bucket_por_separado():
    """Consecuencia concreta: sin nada que ate CF-Connecting-IP a la
    conexión real, un valor distinto por request le da a cada uno su propio
    balde de _rate_ok -- ningún límite por IP frena nada."""
    store = webapi.LRUDict(512)
    for i in range(20):
        req = _request(headers={"CF-Connecting-IP": f"forjada-{i}"})
        ip = webapi._client_ip(req)
        # limit=1: la segunda request de la MISMA ip caería, pero acá cada
        # una es "nueva" a ojos de _rate_ok.
        assert webapi._rate_ok(store, ip, limit=1) is True
