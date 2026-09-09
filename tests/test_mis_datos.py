"""Tests de /mis_datos (cogs/privacy.py): complemento simétrico de
/borrar_mis_datos -- exportar en vez de borrar. El núcleo de solo lectura
(db.export_user_data) se testea aparte en tests/test_export_user_data.py;
acá se cubre la capa de Discord: cooldown, archivo adjunto, i18n y manejo
de errores.

Mismo estilo que test_borrar_mis_datos.py: fakes mínimos con SimpleNamespace,
asyncio.run para el flujo async, sin bot ni red.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import cogs.privacy as privacy_mod
import i18n
from cogs.privacy import Privacy, _export_cooldowns

_AUTHOR_A = 111
_AUTHOR_B = 222
_GUILD_ID = 1


class _FakeFollowup:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, content=None, **kwargs):
        if content is not None:
            kwargs["content"] = content
        self.sent.append(kwargs)


class _FakeResponse:
    def __init__(self):
        self.sent: list[dict] = []
        self.deferred: list[dict] = []

    async def send_message(self, content=None, **kwargs):
        if content is not None:
            kwargs["content"] = content
        self.sent.append(kwargs)

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)


class FakeInteraction:
    def __init__(self, user_id: int, guild_id: int | None = _GUILD_ID):
        self.user = SimpleNamespace(id=user_id)
        self.guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()


async def _fake_locale(guild_id):
    return "es"


@pytest.fixture(autouse=True)
def _patch_guild_locale(monkeypatch):
    monkeypatch.setattr(privacy_mod, "guild_locale", _fake_locale)
    _export_cooldowns.clear()


def test_sin_datos_avisa_vacio_sin_adjuntar_archivo(monkeypatch):
    async def fake_export(author_id):
        return {}

    monkeypatch.setattr(privacy_mod, "export_user_data", fake_export)

    cog = Privacy(SimpleNamespace())
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(cog.mis_datos.callback(cog, inter))

    assert inter.followup.sent[0]["content"] == i18n.t("privacy.export.empty", "es")
    assert "file" not in inter.followup.sent[0]
    assert inter.followup.sent[0]["ephemeral"] is True


def test_con_datos_adjunta_json_valido_con_los_mensajes(monkeypatch):
    async def fake_export(author_id):
        return {
            1: [{"channel_id": 10, "content": "hola", "created_at": "2026-01-01"}],
            2: [{"channel_id": 20, "content": "chau", "created_at": "2026-01-02"}],
        }

    monkeypatch.setattr(privacy_mod, "export_user_data", fake_export)

    bot = SimpleNamespace(get_guild=lambda gid: SimpleNamespace(name=f"guild-{gid}"))
    cog = Privacy(bot)
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(cog.mis_datos.callback(cog, inter))

    sent = inter.followup.sent[0]
    assert sent["ephemeral"] is True
    file_obj = sent["file"]
    assert file_obj.filename == "purgito_mis_datos.json"

    payload = json.loads(file_obj.fp.read().decode())
    assert payload["user_id"] == str(_AUTHOR_A)
    assert len(payload["servers"]) == 2
    server_1 = next(s for s in payload["servers"] if s["guild_id"] == "1")
    assert server_1["guild_name"] == "guild-1"
    assert server_1["messages"] == [
        {"channel_id": 10, "content": "hola", "created_at": "2026-01-01"}
    ]


def test_guild_desconocido_no_rompe_y_deja_nombre_nulo(monkeypatch):
    """El bot ya no está en ese guild (lo echaron, o Purgito se fue) --
    get_guild devuelve None, no debe romper con AttributeError."""

    async def fake_export(author_id):
        return {999: [{"channel_id": 1, "content": "x", "created_at": "2026-01-01"}]}

    monkeypatch.setattr(privacy_mod, "export_user_data", fake_export)

    bot = SimpleNamespace(get_guild=lambda gid: None)
    cog = Privacy(bot)
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(cog.mis_datos.callback(cog, inter))

    payload = json.loads(inter.followup.sent[0]["file"].fp.read().decode())
    assert payload["servers"][0]["guild_name"] is None


def test_respeta_el_cooldown_por_usuario(monkeypatch):
    calls = []

    async def fake_export(author_id):
        calls.append(author_id)
        return {}

    monkeypatch.setattr(privacy_mod, "export_user_data", fake_export)

    cog = Privacy(SimpleNamespace())
    inter1 = FakeInteraction(user_id=_AUTHOR_A)
    inter2 = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(cog.mis_datos.callback(cog, inter1))
    asyncio.run(cog.mis_datos.callback(cog, inter2))

    assert len(calls) == 1  # la segunda quedó bloqueada por el cooldown
    assert inter2.response.sent[0]["ephemeral"] is True
    assert "privacy.export.cooldown" not in inter2.response.sent[0]["content"]


def test_el_cooldown_es_por_usuario_no_compartido(monkeypatch):
    calls = []

    async def fake_export(author_id):
        calls.append(author_id)
        return {}

    monkeypatch.setattr(privacy_mod, "export_user_data", fake_export)

    cog = Privacy(SimpleNamespace())
    asyncio.run(cog.mis_datos.callback(cog, FakeInteraction(user_id=_AUTHOR_A)))
    asyncio.run(cog.mis_datos.callback(cog, FakeInteraction(user_id=_AUTHOR_B)))

    assert calls == [_AUTHOR_A, _AUTHOR_B]  # ninguno bloqueó al otro


def test_error_durante_la_exportacion_no_filtra_detalle_y_queda_logueado(
    monkeypatch, caplog
):
    async def boom(author_id):
        raise RuntimeError("fallo de db simulado, no debería llegar al usuario")

    monkeypatch.setattr(privacy_mod, "export_user_data", boom)

    cog = Privacy(SimpleNamespace())
    inter = FakeInteraction(user_id=_AUTHOR_A)

    with caplog.at_level("ERROR", logger="cogs.privacy"):
        asyncio.run(cog.mis_datos.callback(cog, inter))

    content = inter.followup.sent[0]["content"]
    assert content == i18n.t("privacy.export.error", "es")
    assert "fallo de db simulado" not in content
    assert "RuntimeError" not in content
    assert any("privacy.user_export" in r.message for r in caplog.records)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_claves_i18n_resuelven_en_ambos_idiomas(locale):
    for key in (
        "commands.mis_datos.description",
        "privacy.export.error",
        "privacy.export.empty",
    ):
        resolved = i18n.t(key, locale)
        assert resolved != key, f"clave faltante {key!r} en locale {locale!r}"

    cooldown = i18n.t("privacy.export.cooldown", locale, seconds=30)
    assert "30" in cooldown
    result = i18n.t("privacy.export.result", locale, count=5, guilds=2)
    assert "5" in result and "2" in result
