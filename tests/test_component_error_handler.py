"""Reliability: manejador de errores para botones/selects/modals.

`bot.tree.on_error` (cogs/general.py, ver test_error_handler.py) cubre slash
commands, pero es un mecanismo separado de `View.on_error`/`Modal.on_error`
-- el default de discord.py para estos dos últimos solo loguea, nunca
responde. Antes de este fix, ninguna de las ~12 clases de View/Modal del bot
(SettingsPanel y sus 8 modals anidados, SetupView, WelcomeView, HelpView,
_ConfirmDeleteView, DynamicLayoutModal, el dispatcher persistente de
layout_buttons) lo sobreescribía: una excepción en cualquier callback de
botón o en `on_submit` dejaba al usuario viendo el "Esta interacción falló"
nativo de Discord, sin ninguna explicación -- el mismo problema que motivó
el fix de tree.on_error (AUDITORIA_UX.md, hallazgo #1), pero para
componentes en vez de slash commands.

`SafeView`/`SafeModal` (utils.py) centralizan el fix: cualquier subclase
nueva lo hereda gratis. El test de cobertura de abajo importa todos los cogs
reales (misma lista que carga bot.py) y recorre `__subclasses__()` para que
agregar una View/Modal nueva sin heredar de estas bases haga fallar la
suite, en vez de descubrirse por un reporte de usuario.
"""

import asyncio
import importlib
import logging
from types import SimpleNamespace

import discord

import bot as bot_mod
from utils import SafeModal, SafeView, report_component_error


class FakeInteraction:
    def __init__(self, done=False, rtype=None, guild=None):
        self.guild = guild
        self.followup_sent: list[tuple] = []
        self.resp_sent: list[tuple] = []
        self.edited: list[str] = []

        async def _send_message(msg, ephemeral=False):
            self.resp_sent.append((msg, ephemeral))

        self.response = SimpleNamespace(
            is_done=lambda: done,
            type=rtype,
            send_message=_send_message,
        )

        async def _followup_send(msg, ephemeral=False):
            self.followup_sent.append((msg, ephemeral))

        self.followup = SimpleNamespace(send=_followup_send)

    async def edit_original_response(self, content=None, embed=None, view=None):
        self.edited.append(content)


def test_not_done_responde_con_mensaje_generico_ephemeral():
    inter = FakeInteraction(done=False)
    asyncio.run(report_component_error(inter, ValueError("boom"), "prueba"))
    assert len(inter.resp_sent) == 1
    assert inter.resp_sent[0][1] is True
    assert inter.followup_sent == [] and inter.edited == []


def test_ya_respondido_usa_followup():
    inter = FakeInteraction(
        done=True, rtype=discord.InteractionResponseType.channel_message
    )
    asyncio.run(report_component_error(inter, ValueError("boom"), "prueba"))
    assert len(inter.followup_sent) == 1
    assert inter.followup_sent[0][1] is True
    assert inter.resp_sent == [] and inter.edited == []


def test_defer_pendiente_edita_la_respuesta_original():
    inter = FakeInteraction(
        done=True, rtype=discord.InteractionResponseType.deferred_channel_message
    )
    asyncio.run(report_component_error(inter, ValueError("boom"), "prueba"))
    assert len(inter.edited) == 1
    assert inter.resp_sent == [] and inter.followup_sent == []


def test_loguea_el_error_real_con_traceback(caplog):
    original = RuntimeError("boom real")
    inter = FakeInteraction(done=False)
    with caplog.at_level(logging.ERROR, logger="utils"):
        asyncio.run(report_component_error(inter, original, "MiView (item=Button)"))
    rec = next(r for r in caplog.records if "MiView" in r.getMessage())
    assert rec.exc_info[1] is original


def test_fallo_al_avisar_no_propaga(caplog):
    """Si hasta el mensaje de error falla (interacción ya expirada), no debe
    tirar una segunda excepción -- mismo criterio que on_app_command_error."""
    inter = FakeInteraction(done=False)

    async def _expired(msg, ephemeral=False):
        raise discord.NotFound(
            SimpleNamespace(status=404, reason="Not Found"), "unknown interaction"
        )

    inter.response.send_message = _expired
    with caplog.at_level(logging.DEBUG, logger="utils"):
        asyncio.run(report_component_error(inter, ValueError("boom"), "prueba"))
    assert any(
        r.levelno == logging.DEBUG and "No se pudo avisar" in r.getMessage()
        for r in caplog.records
    )


def test_safeview_conecta_on_error_con_report_component_error(monkeypatch):
    calls = []

    async def fake_report(interaction, error, source):
        calls.append((interaction, error, source))

    monkeypatch.setattr("utils.report_component_error", fake_report)
    view = SafeView()
    err = RuntimeError("boom")
    fake_item = SimpleNamespace()
    asyncio.run(view.on_error(SimpleNamespace(), err, fake_item))
    assert len(calls) == 1
    assert calls[0][1] is err
    assert "SafeView" in calls[0][2]


def test_safemodal_conecta_on_error_con_report_component_error(monkeypatch):
    calls = []

    async def fake_report(interaction, error, source):
        calls.append((interaction, error, source))

    monkeypatch.setattr("utils.report_component_error", fake_report)
    modal = SafeModal(title="prueba")
    err = RuntimeError("boom")
    asyncio.run(modal.on_error(SimpleNamespace(), err))
    assert len(calls) == 1
    assert calls[0][1] is err
    assert calls[0][2] == "SafeModal"


def _all_subclasses(cls) -> set[type]:
    seen: set[type] = set()
    stack = [cls]
    while stack:
        current = stack.pop()
        for sub in current.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return seen


def test_todas_las_views_y_modals_del_bot_heredan_de_safeview_safemodal():
    """Importa los cogs reales (misma lista que bot.EXTENSIONS) más help_view
    para forzar que sus clases de View/Modal queden definidas, y recorre
    __subclasses__() -- así una View/Modal nueva que suba sin heredar de
    SafeView/SafeModal hace fallar esto en vez de descubrirse por un
    "Esta interacción falló" en producción."""
    importlib.import_module("help_view")
    for ext in bot_mod.EXTENSIONS:
        importlib.import_module(ext)

    bad_views = [
        c
        for c in _all_subclasses(discord.ui.View)
        if c is not SafeView and not issubclass(c, SafeView)
    ]
    bad_modals = [
        c
        for c in _all_subclasses(discord.ui.Modal)
        if c is not SafeModal and not issubclass(c, SafeModal)
    ]
    assert bad_views == [], (
        f"View(s) sin heredar de SafeView (sin on_error, dejan al usuario sin "
        f"respuesta ante una excepción): {bad_views}"
    )
    assert bad_modals == [], f"Modal(s) sin heredar de SafeModal: {bad_modals}"
