"""Tests de /borrar_mis_datos (cogs/privacy.py): interfaz de Discord del
Right to be Forgotten individual. El núcleo de borrado (db.delete_user_data,
generation.forget_user) ya está testeado aparte (tests/test_delete_user_data.py,
tests/test_forget_user_cache_invalidation.py) -- acá solo se cubre la capa de
Discord: identidad, confirmación de dos pasos, ownership del botón, manejo de
resultados/errores e i18n.

Mismo patrón que test_vote_command.py / test_refeed_channel_guard.py: fakes
mínimos con SimpleNamespace, asyncio.run para el flujo async, sin bot ni red.
"""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import cogs.privacy as privacy_mod
import i18n
from cogs.privacy import Privacy, _ConfirmDeleteView

_AUTHOR_A = 111
_AUTHOR_B = 222
_GUILD_ID = 1


class _FakeResponse:
    def __init__(self):
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.deferred: list[dict] = []

    async def send_message(self, content=None, **kwargs):
        if content is not None:
            kwargs["content"] = content
        self.sent.append(kwargs)

    async def edit_message(self, **kwargs):
        self.edited.append(kwargs)

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)


class _FakeMessage:
    def __init__(self):
        self.edits: list[dict] = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeInteraction:
    def __init__(self, user_id: int, guild_id: int | None = _GUILD_ID):
        self.user = SimpleNamespace(id=user_id)
        self.guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
        self.response = _FakeResponse()
        self.edit_original_response_calls: list[dict] = []
        self._message = _FakeMessage()

    async def edit_original_response(self, **kwargs):
        self.edit_original_response_calls.append(kwargs)

    async def original_response(self):
        return self._message


async def _fake_locale(guild_id):
    return "es"


@pytest.fixture(autouse=True)
def _patch_guild_locale(monkeypatch):
    monkeypatch.setattr(privacy_mod, "guild_locale", _fake_locale)


# ─── 1 y 2: identidad exclusiva de interaction.user.id, sin parámetros ──────


def test_comando_no_acepta_ningun_parametro_para_elegir_otro_usuario():
    """No debe existir usuario/user_id/guild_id ni ningún otro parámetro --
    la única fuente de identidad es interaction.user.id."""
    sig = inspect.signature(Privacy.borrar_mis_datos.callback)
    param_names = [p for p in sig.parameters if p not in ("self", "interaction")]
    assert param_names == []


def test_comando_usa_interaction_user_id_como_autor_de_la_confirmacion():
    cog = Privacy(SimpleNamespace())
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(cog.borrar_mis_datos.callback(cog, inter))

    assert len(inter.response.sent) == 1
    view = inter.response.sent[0]["view"]
    assert isinstance(view, _ConfirmDeleteView)
    assert view.author_id == _AUTHOR_A


# ─── 9: ephemeral ────────────────────────────────────────────────────────


def test_respuesta_inicial_es_ephemeral():
    cog = Privacy(SimpleNamespace())
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(cog.borrar_mis_datos.callback(cog, inter))
    assert inter.response.sent[0]["ephemeral"] is True


# ─── 11: sin permisos administrativos ───────────────────────────────────


def test_no_requiere_permisos_administrativos():
    """interaction.user no tiene guild_permissions ni ningún otro atributo de
    permisos -- si el comando alguna vez empezara a chequear admin, esto
    rompería con AttributeError en vez de pasar en silencio."""
    cog = Privacy(SimpleNamespace())
    inter = FakeInteraction(user_id=_AUTHOR_A)
    assert not hasattr(inter.user, "guild_permissions")
    asyncio.run(cog.borrar_mis_datos.callback(cog, inter))
    assert len(inter.response.sent) == 1  # no se rechazó por permisos


# ─── convención guild_only ──────────────────────────────────────────────


def test_fuera_de_un_guild_responde_guild_only():
    cog = Privacy(SimpleNamespace())
    inter = FakeInteraction(user_id=_AUTHOR_A, guild_id=None)
    asyncio.run(cog.borrar_mis_datos.callback(cog, inter))
    assert inter.response.sent[0]["content"] == i18n.t("general.guild_only", "es")
    assert inter.response.sent[0]["ephemeral"] is True


# ─── 3 y 6: ownership del botón ──────────────────────────────────────────


def test_otra_persona_no_puede_confirmar_ni_cancelar():
    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    intruder = FakeInteraction(user_id=_AUTHOR_B)

    allowed = asyncio.run(view.interaction_check(intruder))

    assert allowed is False
    assert intruder.response.sent[0]["content"] == i18n.t(
        "privacy.delete.not_your_request", "es"
    )
    assert intruder.response.sent[0]["ephemeral"] is True


def test_el_autor_original_sigue_autorizado_despues_de_un_intento_ajeno():
    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    intruder = FakeInteraction(user_id=_AUTHOR_B)
    owner = FakeInteraction(user_id=_AUTHOR_A)

    asyncio.run(view.interaction_check(intruder))
    allowed = asyncio.run(view.interaction_check(owner))

    assert allowed is True


# ─── 4: cancelar no borra nada ───────────────────────────────────────────


def test_cancelar_no_llama_a_forget_user(monkeypatch):
    calls = []

    async def fake_forget_user(author_id):
        calls.append(author_id)
        return {}

    monkeypatch.setattr(privacy_mod.generation, "forget_user", fake_forget_user)

    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(view._on_cancel(inter))

    assert calls == []
    assert inter.response.edited[0]["content"] == i18n.t(
        "privacy.delete.cancelled", "es"
    )


# ─── 5: confirmar llama exactamente una vez, con el author_id correcto ──


def test_confirmar_llama_forget_user_exactamente_una_vez(monkeypatch):
    calls = []

    async def fake_forget_user(author_id):
        calls.append(author_id)
        return {
            "user_corpus_deleted": 3,
            "corpus_messages_deleted": 2,
            "guild_ids": [1],
        }

    monkeypatch.setattr(privacy_mod.generation, "forget_user", fake_forget_user)

    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    inter = FakeInteraction(user_id=_AUTHOR_A)

    async def run():
        await view._on_delete(inter)  # primer click: solo arma
        await view._on_delete(inter)  # segundo click: ejecuta

    asyncio.run(run())

    assert calls == [_AUTHOR_A]


def test_primer_click_no_borra_nada_todavia(monkeypatch):
    calls = []

    async def fake_forget_user(author_id):
        calls.append(author_id)
        return {"user_corpus_deleted": 0, "corpus_messages_deleted": 0, "guild_ids": []}

    monkeypatch.setattr(privacy_mod.generation, "forget_user", fake_forget_user)

    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(view._on_delete(inter))

    assert calls == []
    assert view._armed is True
    assert inter.response.edited[0]["content"] == i18n.t(
        "privacy.delete.confirm_again", "es"
    )


# ─── 6 y 7: resultados ───────────────────────────────────────────────────


def test_resultado_exitoso_con_datos_eliminados(monkeypatch):
    async def fake_forget_user(author_id):
        return {
            "user_corpus_deleted": 5,
            "corpus_messages_deleted": 4,
            "guild_ids": [1, 2],
        }

    monkeypatch.setattr(privacy_mod.generation, "forget_user", fake_forget_user)

    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    view._armed = True
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(view._on_delete(inter))

    expected = i18n.t(
        "privacy.delete.result_success", "es", user_corpus_deleted=5, guilds=2
    )
    assert inter.edit_original_response_calls[0]["content"] == expected
    assert inter.response.deferred == [{}]


def test_resultado_exitoso_sin_datos_no_es_tratado_como_error(monkeypatch):
    async def fake_forget_user(author_id):
        return {"user_corpus_deleted": 0, "corpus_messages_deleted": 0, "guild_ids": []}

    monkeypatch.setattr(privacy_mod.generation, "forget_user", fake_forget_user)

    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    view._armed = True
    inter = FakeInteraction(user_id=_AUTHOR_A)
    asyncio.run(view._on_delete(inter))

    assert inter.edit_original_response_calls[0]["content"] == i18n.t(
        "privacy.delete.result_empty", "es"
    )


# ─── 8: error durante el borrado ─────────────────────────────────────────


def test_error_durante_el_borrado_no_afirma_exito_y_queda_logueado(monkeypatch, caplog):
    async def boom(author_id):
        raise RuntimeError("disco lleno simulado, no debería llegar al usuario")

    monkeypatch.setattr(privacy_mod.generation, "forget_user", boom)

    view = _ConfirmDeleteView(author_id=_AUTHOR_A, locale="es")
    view._armed = True
    inter = FakeInteraction(user_id=_AUTHOR_A)

    with caplog.at_level("ERROR", logger="cogs.privacy"):
        asyncio.run(view._on_delete(inter))

    content = inter.edit_original_response_calls[0]["content"]
    assert content == i18n.t("privacy.delete.error", "es")
    # nunca se filtra el detalle real de la excepción al usuario
    assert "disco lleno simulado" not in content
    assert "RuntimeError" not in content
    # pero sí queda registrado internamente
    assert any("privacy.user_delete" in r.message for r in caplog.records)
    assert any(str(_AUTHOR_A) in r.message for r in caplog.records)


# ─── 10: i18n es/en ───────────────────────────────────────────────────────


@pytest.mark.parametrize("locale", ["es", "en"])
def test_claves_i18n_resuelven_en_ambos_idiomas(locale):
    for key in (
        "privacy.delete.title",
        "privacy.delete.body",
        "privacy.delete.button_start",
        "privacy.delete.button_confirm",
        "privacy.delete.button_cancel",
        "privacy.delete.confirm_again",
        "privacy.delete.cancelled",
        "privacy.delete.not_your_request",
        "privacy.delete.error",
        "privacy.delete.result_empty",
        "commands.borrar_mis_datos.description",
    ):
        resolved = i18n.t(key, locale)
        assert resolved != key, f"clave faltante {key!r} en locale {locale!r}"

    result = i18n.t(
        "privacy.delete.result_success", locale, user_corpus_deleted=7, guilds=3
    )
    assert "7" in result
    assert "3" in result


def test_result_success_no_se_rompe_por_placeholders_sin_resolver():
    for locale in ("es", "en"):
        result = i18n.t(
            "privacy.delete.result_success", locale, user_corpus_deleted=1, guilds=1
        )
        assert "{" not in result and "}" not in result


# ─── 12: no toca mensajes originales de Discord ──────────────────────────


def test_no_hay_llamadas_a_borrado_o_edicion_de_mensajes_de_discord():
    """Guardrail: la vista de confirmación no debe invocar ninguna API de
    borrado/edición de mensajes de Discord (message.delete, purge, etc.) --
    el RTBF de Purgito borra SOLO su propio corpus, nunca contenido de
    Discord en sí."""
    source = inspect.getsource(privacy_mod._ConfirmDeleteView)
    forbidden = [".delete(", ".purge(", "bulk_delete", "delete_messages"]
    for pattern in forbidden:
        assert pattern not in source, (
            f"{pattern!r} no debería aparecer en _ConfirmDeleteView"
        )
