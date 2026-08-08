"""Tercera pasada de la auditoría de Sección 1 (auth/sesión): tamaño de la
cookie, revocación del token en Discord al hacer logout, y rate limit sobre
/auth/callback (el intercambio de code por token le pega a la API de Discord
con nuestro client_id/client_secret -- compartido por todos los guilds).
"""

import asyncio
import base64
import hashlib
import inspect
import json
import re
import secrets

import aiohttp
import pytest
from cryptography.fernet import Fernet

import db
import webapi


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


class _FakeSession(dict):
    def invalidate(self) -> None:
        self.clear()


def _patch_session(monkeypatch, session: dict) -> None:
    async def fake_get_session(_request):
        return session

    monkeypatch.setattr(webapi, "get_session", fake_get_session)


# ── P1: la cookie no puede crecer con la cantidad de guilds del usuario ────


def test_la_sesion_nunca_guarda_la_lista_de_guilds():
    """La lista de guilds administrables vive en _user_guilds_cache (memoria
    del proceso, keyed por user_id) -- NUNCA en la cookie. Si alguien la
    reintrodujera en session[...], un usuario con cientos de guilds podría
    romper el límite práctico de ~4KB por cookie. Este test escanea el código
    fuente real de _auth_callback (única función que arma la sesión desde
    cero) y falla si aparece cualquier clave nueva, sobre todo una con
    "guild" en el nombre."""
    src = inspect.getsource(webapi._auth_callback)
    keys = re.findall(r'session\["(\w+)"\]\s*=', src)
    assert keys == ["user_id", "username", "avatar_url", "email", "access_token", "sid"]
    assert not any("guild" in k for k in keys)


def test_cookie_cifrada_se_mantiene_chica_en_el_peor_caso_realista():
    """Con todos los campos de la sesión en su tope realista (username al
    límite de Discord, un email deliberadamente exagerado, token, sid), la
    cookie cifrada queda muy por debajo del límite práctico de ~4096 bytes
    por cookie -- y ese tamaño es indiferente a cuántos guilds administre el
    usuario, porque esa lista no vive acá (ver test de arriba)."""
    worst_case = {
        "user_id": "1" * 19,
        "username": "x" * 32,  # tope real de Discord para global_name
        "avatar_url": "https://cdn.discordapp.com/avatars/"
        + "1" * 19
        + "/"
        + "a" * 32
        + ".png?size=64",
        "email": ("x" * 64)
        + "@"
        + ("y" * 180)
        + ".com",  # más largo que cualquier email real
        "access_token": "x" * 64,
        "sid": secrets.token_urlsafe(16),
    }
    key = base64.urlsafe_b64encode(hashlib.sha256(b"clave-de-prueba").digest())
    cookie = Fernet(key).encrypt(json.dumps(worst_case).encode())
    assert len(cookie) < 2048


# ── P2: logout revoca el access_token en Discord, no solo en Purgito ──────


class _FakeResp:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeHttpRevoke:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, data=None):
        self.calls.append((url, data))
        return _FakeResp()


class _FakeRequestWithApp:
    def __init__(self, http):
        self.app = {"http": http}


def test_auth_logout_revoca_el_access_token_en_discord(monkeypatch, temp_db):
    session = _FakeSession(user_id="42", sid="sid-tok", access_token="tok-abc")
    _patch_session(monkeypatch, session)
    http = _FakeHttpRevoke()

    async def run():
        with pytest.raises(webapi.web.HTTPFound):
            await webapi._auth_logout(_FakeRequestWithApp(http))

    asyncio.run(run())
    assert len(http.calls) == 1
    url, data = http.calls[0]
    assert url == "https://discord.com/api/oauth2/token/revoke"
    assert data["token"] == "tok-abc"
    assert data["token_type_hint"] == "access_token"


def test_auth_logout_no_se_rompe_si_discord_esta_caido(monkeypatch, temp_db):
    """Best-effort a propósito: revoke_session (Purgito) ya es la protección
    primaria. Si Discord no responde, el logout tiene que completar igual --
    sid revocado, cookie invalidada -- en vez de dejar al usuario "atascado"
    logueado por un problema del lado de Discord."""
    session = _FakeSession(user_id="42", sid="sid-boom2", access_token="tok-abc")
    _patch_session(monkeypatch, session)

    class _BoomHttp:
        def post(self, url, data=None):
            raise aiohttp.ClientConnectionError("discord caído")

    async def run():
        with pytest.raises(webapi.web.HTTPFound):
            await webapi._auth_logout(_FakeRequestWithApp(_BoomHttp()))
        return await db.is_session_revoked("sid-boom2")

    assert asyncio.run(run()) is True


def test_auth_logout_no_llama_a_discord_sin_access_token(monkeypatch, temp_db):
    """Sesiones sin access_token (no debería pasar en la práctica, pero
    session.get(...) puede dar None) no deben intentar el POST a Discord."""
    session = _FakeSession(user_id="42", sid="sid-sin-token")
    _patch_session(monkeypatch, session)
    http = _FakeHttpRevoke()

    async def run():
        with pytest.raises(webapi.web.HTTPFound):
            await webapi._auth_logout(_FakeRequestWithApp(http))

    asyncio.run(run())
    assert http.calls == []


# ── P5: /auth/callback tiene rate limit por IP ─────────────────────────────


class _FakeCallbackRequest:
    headers: dict = {}
    remote = "203.0.113.7"
    query = {"code": "x", "state": "y"}


def test_auth_callback_bloquea_tras_superar_el_limite_por_ip(monkeypatch):
    """Sin este límite, un atacante podía scriptear /auth/login + /auth/callback
    en loop: cada vuelta con state válido dispara un POST real a
    discord.com/oauth2/token con nuestro client_id/client_secret -- Discord
    ratea ese endpoint por client_id, compartido por todos los guilds que
    usan el bot. Verifica que el intento que excede el límite se corta ANTES
    de leer la sesión (o sea, antes de poder llegar a pegarle a Discord)."""
    webapi._rate_auth_callback.clear()

    calls = []

    async def spy_get_session(_request):
        calls.append(1)
        return {}

    monkeypatch.setattr(webapi, "get_session", spy_get_session)

    async def run():
        for _ in range(10):
            with pytest.raises(webapi.web.HTTPFound):
                await webapi._auth_callback(_FakeCallbackRequest())
        antes = len(calls)
        with pytest.raises(webapi.web.HTTPFound):
            await webapi._auth_callback(_FakeCallbackRequest())
        return antes, len(calls)

    antes, despues = asyncio.run(run())
    assert antes == 10  # los primeros 10 sí llegaron a leer la sesión
    assert (
        despues == 10
    )  # el intento 11 se cortó por rate limit, no llegó a get_session


def test_auth_callback_no_comparte_limite_entre_ips_distintas(monkeypatch):
    """El límite es por IP -- una IP agotada no debe tumbar a las demás."""
    webapi._rate_auth_callback.clear()

    calls = []

    async def spy_get_session(_request):
        calls.append(1)
        return {}

    monkeypatch.setattr(webapi, "get_session", spy_get_session)

    class _ReqIpA(_FakeCallbackRequest):
        remote = "203.0.113.7"

    class _ReqIpB(_FakeCallbackRequest):
        remote = "198.51.100.9"

    async def run():
        for _ in range(10):
            with pytest.raises(webapi.web.HTTPFound):
                await webapi._auth_callback(_ReqIpA())
        antes = len(calls)
        # IP A ya agotó su límite; IP B todavía tiene que poder intentarlo,
        # o sea, llegar a leer la sesión (no cortarse en el rate limit de A).
        with pytest.raises(webapi.web.HTTPFound):
            await webapi._auth_callback(_ReqIpB())
        return antes, len(calls)

    antes, despues = asyncio.run(run())
    assert despues == antes + 1, "el límite de la IP A frenó también a la IP B"
