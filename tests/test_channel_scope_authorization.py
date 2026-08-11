"""Auditoría sección 10, ronda 1, puntos 4 y 5: escalada de privilegios por
alcance de canal.

`guild_api` (y por transición check_guild_access/_fetch_manage_guilds) exige
MANAGE_GUILD en algún lado del servidor -- pero MANAGE_GUILD no incluye ver
canales con overwrites que se los esconden a un rol puntual (Discord los
trata como permisos separados). Antes de este fix, cualquier endpoint que
aceptaba un channel_id de body/path lo usaba tal cual sin comprobar que la
persona detrás de la sesión (no el bot) pudiera VER ese canal.

El manifiesto más severo es corpus_allowed_channels: el corpus del Markov se
arma por GUILD ENTERO (generation.build_markov_model no separa por canal),
así que un admin con MANAGE_GUILD pero sin acceso a un canal privado podía
anotarlo ahí -- el bot sí lo ve y aprende de ese contenido, que después sale
mezclado en cualquier respuesta pública. Es la misma familia de bug que R1
de la Sección 9 (role_id): un permiso amplio no implica el alcance puntual
que la acción necesita.

Esta ronda cierra el manifiesto más grave (corpus, que filtra CONTENIDO
ajeno). Las demás allowlists de canal (spontaneous/mention/frases/triggers/
exempt/embeds send-schedule/updates/youtube) comparten la causa raíz pero su
impacto es menor -- el bot ESCRIBE ahí, no filtra nada hacia afuera -- y
quedan documentadas para una ronda siguiente.
"""

import asyncio
from types import SimpleNamespace

import aiosqlite
import discord
import pytest

import db
import webapi

_GUILD = 42
_USER_ID = "777"
_CHANNEL_VISIBLE = 100
_CHANNEL_PRIVADO = 200
_CHANNEL_INEXISTENTE = 999


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


class FakeRequest:
    def __init__(self, body=None):
        self._body = body
        self.match_info = {"guild_id": str(_GUILD)}
        self.headers = {"Content-Type": "application/json"}
        self.remote = "1.2.3.4"

    async def json(self):
        return self._body


def _fake_channel(cid, *, visible: bool):
    return SimpleNamespace(
        id=cid,
        permissions_for=lambda member: SimpleNamespace(view_channel=visible),
    )


def _fake_guild(*, fetch_member_result=None, fetch_member_raises=None):
    channels = {
        _CHANNEL_VISIBLE: _fake_channel(_CHANNEL_VISIBLE, visible=True),
        _CHANNEL_PRIVADO: _fake_channel(_CHANNEL_PRIVADO, visible=False),
    }

    async def fetch_member(member_id):
        if fetch_member_raises is not None:
            raise fetch_member_raises
        return fetch_member_result or SimpleNamespace(id=member_id)

    return SimpleNamespace(
        get_channel=lambda cid: channels.get(cid),
        fetch_member=fetch_member,
    )


@pytest.fixture(autouse=True)
def sesion(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": "panelero"}

    async def fake_check_guild_access(request, guild_id):
        return None

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_guild_access)
    monkeypatch.setattr(webapi, "_rate_post", webapi.LRUDict(64))


def _run_corpus_post(monkeypatch, guild, channel_id):
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, gid: guild)
    return asyncio.run(webapi._api_corpus_post(FakeRequest({"channel_id": channel_id})))


# ── _member_can_view_channel: el helper en aislamiento ───────────────────────


def test_member_can_view_channel_true_si_el_permiso_lo_permite():
    guild = _fake_guild()
    channel = _fake_channel(1, visible=True)
    request = FakeRequest()
    assert asyncio.run(webapi._member_can_view_channel(request, guild, channel)) is True


def test_member_can_view_channel_false_si_el_permiso_lo_niega():
    guild = _fake_guild()
    channel = _fake_channel(1, visible=False)
    request = FakeRequest()
    assert (
        asyncio.run(webapi._member_can_view_channel(request, guild, channel)) is False
    )


def test_member_can_view_channel_usa_fetch_no_cache():
    """El bot corre con Intents.default() (sin el intent privilegiado de
    members), así que get_member() no es confiable -- tiene que ser
    fetch_member (llamada en vivo a Discord)."""
    llamado = []

    async def fetch_member(member_id):
        llamado.append(member_id)
        return SimpleNamespace(id=member_id)

    guild = SimpleNamespace(fetch_member=fetch_member)
    channel = _fake_channel(1, visible=True)
    asyncio.run(webapi._member_can_view_channel(FakeRequest(), guild, channel))
    assert llamado == [int(_USER_ID)]


@pytest.mark.parametrize(
    "excepcion",
    [
        discord.NotFound(SimpleNamespace(status=404, reason=""), "no encontrado"),
        discord.Forbidden(SimpleNamespace(status=403, reason=""), "prohibido"),
    ],
)
def test_member_can_view_channel_niega_ante_cualquier_error(excepcion):
    """Ya no es miembro del guild, o Discord falló: ante la duda, no se
    otorga acceso -- mismo criterio restrictivo que _reject_unassignable_roles
    (sección 9, R1)."""
    guild = _fake_guild(fetch_member_raises=excepcion)
    channel = _fake_channel(1, visible=True)
    request = FakeRequest()
    assert (
        asyncio.run(webapi._member_can_view_channel(request, guild, channel)) is False
    )


# ── _api_corpus_post: el endpoint completo ───────────────────────────────────


def test_corpus_post_rechaza_canal_que_el_admin_no_puede_ver(memory_db, monkeypatch):
    guild = _fake_guild()
    resp = _run_corpus_post(monkeypatch, guild, _CHANNEL_PRIVADO)
    assert resp.status == 403
    assert asyncio.run(db.list_corpus_channels(_GUILD)) == []


def test_corpus_post_acepta_canal_que_el_admin_puede_ver(memory_db, monkeypatch):
    guild = _fake_guild()
    resp = _run_corpus_post(monkeypatch, guild, _CHANNEL_VISIBLE)
    assert resp.status == 200
    assert _CHANNEL_VISIBLE in asyncio.run(db.list_corpus_channels(_GUILD))


def test_corpus_post_rechaza_canal_inexistente_en_el_guild(memory_db, monkeypatch):
    """Antes de este fix add_corpus_channel ni siquiera comprobaba que el
    channel_id perteneciera al guild -- aceptaba cualquier entero."""
    guild = _fake_guild()
    resp = _run_corpus_post(monkeypatch, guild, _CHANNEL_INEXISTENTE)
    assert resp.status == 400
    assert asyncio.run(db.list_corpus_channels(_GUILD)) == []


def test_corpus_post_no_llega_a_escribir_si_el_chequeo_falla(memory_db, monkeypatch):
    """El guard corre ANTES de add_corpus_channel -- confirmado por el efecto
    (la tabla queda vacía), no solo por el código de respuesta."""
    guild = _fake_guild()
    _run_corpus_post(monkeypatch, guild, _CHANNEL_PRIVADO)
    entradas = asyncio.run(db.list_audit_log(_GUILD))
    assert entradas == []
