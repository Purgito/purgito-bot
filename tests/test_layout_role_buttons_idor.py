"""Auditoría sección 9, ronda 2, punto 3: role_id de los botones de layout.

validate_layout_v2_payload solo exige que role_id sea un número. El resto lo
tiene que poner el endpoint, y no lo ponía -- mismo patrón de IDOR por id
numérico que pack_id en la sección 6, con un agravante encima:

El panel se entra con MANAGE_GUILD (ver _fetch_manage_guilds), que en Discord
NO incluye gestionar roles. Sin chequeo de jerarquía, quien tuviera acceso al
panel podía fabricar un botón que reparte cualquier rol por debajo del bot --
uno con Administrador incluido -- mandarlo a un canal y clickearlo.

Los dos endpoints que acuñan custom_id (enviar y programar) tienen que cerrar
lo mismo: un anuncio programado es peor, porque sobrevive a reinicios y se
dispara solo.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import webapi

_GUILD = 555
_USER_ID = "42"


class FakeRole:
    def __init__(self, id, position, name="rol", managed=False, default=False):
        self.id = id
        self.position = position
        self.name = name
        self.managed = managed
        self._default = default

    def is_default(self):
        return self._default

    def __ge__(self, other):
        return self.position >= other.position

    def __lt__(self, other):
        return self.position < other.position


# Jerarquía del servidor de prueba, de arriba hacia abajo. Las posiciones
# importan: el caso de escalada necesita un rol que esté POR DEBAJO del bot
# (o sea, asignable por él) y POR ENCIMA de quien maneja el panel.
#
#   intocable(50)   -- por encima de Purgito: ni el bot puede repartirlo
#   purgito(40)     -- top role del bot
#   admin(35)       -- ESCALADA: el bot llega, el moderador no debería
#   moderador(30)   -- top role del usuario del panel
#   bot-integrado(20, managed)
#   miembro(10)     -- reparto legítimo
#   @everyone(0)
ROLES = {
    50: FakeRole(50, 50, "intocable"),
    40: FakeRole(40, 40, "purgito"),
    99: FakeRole(99, 35, "admin"),
    30: FakeRole(30, 30, "moderador"),
    77: FakeRole(77, 20, "bot-integrado", managed=True),
    10: FakeRole(10, 10, "miembro"),
    0: FakeRole(0, 0, "@everyone", default=True),
}


class FakeRequest:
    def __init__(self, body):
        self._body = body
        self.match_info = {"guild_id": str(_GUILD)}
        self.headers = {}
        self.remote = "1.2.3.4"
        self.app = {"bot": SimpleNamespace()}

    async def json(self):
        return self._body


def _guild(owner_id=999, member_top=30):
    """Guild falso; el usuario del panel tiene `member_top` como rol más alto."""
    member = SimpleNamespace(id=int(_USER_ID), top_role=ROLES[member_top])
    return SimpleNamespace(
        id=_GUILD,
        owner_id=owner_id,
        me=SimpleNamespace(top_role=ROLES[40]),
        get_role=ROLES.get,
        get_member=lambda uid: member if uid == int(_USER_ID) else None,
        get_channel=lambda cid: None,
    )


@pytest.fixture(autouse=True)
def sesion(monkeypatch):
    async def fake_get_session(request):
        return {"user_id": _USER_ID, "username": "panelero"}

    monkeypatch.setattr(webapi, "get_session", fake_get_session)


def _layout(role_id):
    return {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "role", "label": "Dame el rol", "role_id": role_id}
                ],
            }
        ]
    }


def _check(layout, guild):
    request = FakeRequest({"layout": layout})
    return asyncio.run(webapi._reject_unassignable_roles(request, _GUILD, layout))


@pytest.fixture
def guild_normal(monkeypatch):
    g = _guild()
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: g)
    return g


def test_rol_de_otro_servidor_se_rechaza(guild_normal):
    """get_role del guild devuelve None: el botón quedaba guardado igual y
    fallaba recién al clickearlo."""
    resp = _check(_layout(123456789), guild_normal)
    assert resp is not None and resp.status == 400


def test_rol_por_encima_del_usuario_se_rechaza(guild_normal):
    """El caso de escalada: 'admin' (35) está por debajo de Purgito (40), o
    sea que el bot SÍ puede repartirlo, pero por encima del moderador (30) que
    maneja el panel. Sin este chequeo, el moderador se lo autoasignaba."""
    resp = _check(_layout(99), guild_normal)
    assert resp is not None and resp.status == 403
    assert "por encima del tuyo" in json.loads(resp.body)["error"]


def test_rol_por_debajo_del_usuario_se_acepta(guild_normal):
    assert _check(_layout(10), guild_normal) is None


def test_el_dueno_del_servidor_no_tiene_techo(monkeypatch):
    """El owner sí puede repartir cualquier rol que el bot alcance -- es la
    misma regla que aplica Discord en su propia UI."""
    g = _guild(owner_id=int(_USER_ID))
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: g)
    assert _check(_layout(99), g) is None


def test_everyone_se_rechaza(guild_normal):
    resp = _check(_layout(0), guild_normal)
    assert resp is not None and resp.status == 400


def test_rol_de_integracion_se_rechaza(guild_normal):
    """Los roles managed no los puede asignar nadie, ni el bot."""
    resp = _check(_layout(77), guild_normal)
    assert resp is not None and resp.status == 400
    assert "integración" in json.loads(resp.body)["error"]


def test_rol_por_encima_del_bot_se_rechaza(monkeypatch):
    """Aunque quien manda sea el dueño del servidor: el bot no puede repartir
    un rol por encima del suyo, así que el botón nacería muerto. Mejor
    decirlo al crearlo que dejar un botón que falla en silencio al clickearlo."""
    g = _guild(owner_id=int(_USER_ID))
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: g)
    resp = _check(_layout(50), g)
    assert resp is not None and resp.status == 400
    assert "por encima del rol de Purgito" in json.loads(resp.body)["error"]


def test_usuario_no_cacheado_se_trata_como_restrictivo(monkeypatch):
    """get_member puede devolver None (miembro no cacheado): ante la duda no
    se reparte nada."""
    g = _guild()
    g.get_member = lambda uid: None
    monkeypatch.setattr(webapi, "_bot_guild", lambda request, guild_id: g)
    resp = _check(_layout(10), g)
    assert resp is not None and resp.status == 403


def test_layout_sin_botones_de_rol_no_toca_nada(monkeypatch):
    """Un layout de solo texto o con botones de enlace no debe pedir guild ni
    sesión: el chequeo sale antes."""
    called = []
    monkeypatch.setattr(
        webapi, "_bot_guild", lambda request, guild_id: called.append(1) or _guild()
    )
    layout = {
        "blocks": [
            {"type": "text", "content": "hola"},
            {
                "type": "action_row",
                "buttons": [{"style": "link", "label": "ir", "url": "https://x.test"}],
            },
        ]
    }
    assert _check(layout, None) is None
    assert called == []


def test_botones_anidados_en_container_tambien_se_revisan(guild_normal):
    """iter_buttons recorre containers y accessories de section; el chequeo no
    puede quedarse solo con los action_row de primer nivel."""
    layout = {
        "blocks": [
            {
                "type": "container",
                "children": [
                    {
                        "type": "section",
                        "texts": ["x"],
                        "accessory": {
                            "type": "button",
                            "style": "role",
                            "label": "b",
                            "role_id": 99,
                        },
                    }
                ],
            }
        ]
    }
    resp = _check(layout, guild_normal)
    assert resp is not None and resp.status == 403


def test_los_endpoints_que_acunan_custom_id_pasan_por_el_chequeo():
    """Enviar, programar y endpoints de anuncios (post y put) mintean custom_id por
    caminos distintos; todos deben pasar por _reject_unassignable_roles."""
    src = (
        __import__("pathlib").Path(__file__).resolve().parent.parent / "src/webapi.py"
    ).read_text(encoding="utf-8")
    acunados = src.count("assign_button_custom_ids(layout)")
    chequeos = src.count("_reject_unassignable_roles(")
    # -1 por la definición de la función.
    assert acunados == 4
    assert chequeos - 1 == acunados
