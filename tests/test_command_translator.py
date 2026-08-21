"""Test de i18n.CommandTranslator: localiza la descripción de los slash
commands para clientes de Discord en inglés, sin tocar sus nombres.

Mismo patrón que test_error_handler.py: fakes con SimpleNamespace,
asyncio.run para el flujo async, sin bot ni red.
"""

import asyncio
from types import SimpleNamespace

from discord import Locale, app_commands

from i18n import CommandTranslator


def _ctx(location, name="generar"):
    return app_commands.TranslationContext(location, SimpleNamespace(name=name))


def test_traduce_descripcion_para_cliente_en_ingles():
    translated = asyncio.run(
        CommandTranslator().translate(
            app_commands.locale_str("x"),
            Locale.american_english,
            _ctx(app_commands.TranslationContextLocation.command_description),
        )
    )
    assert (
        translated == "Generates a message using what Purgito learned from the server."
    )


def test_no_traduce_el_nombre_del_comando():
    translated = asyncio.run(
        CommandTranslator().translate(
            app_commands.locale_str("x"),
            Locale.american_english,
            _ctx(app_commands.TranslationContextLocation.command_name),
        )
    )
    assert translated is None


def test_locale_sin_soporte_devuelve_none_y_discord_usa_el_base():
    translated = asyncio.run(
        CommandTranslator().translate(
            app_commands.locale_str("x"),
            Locale.spain_spanish,
            _ctx(app_commands.TranslationContextLocation.command_description),
        )
    )
    assert translated is None


def test_comando_sin_clave_de_traduccion_devuelve_none():
    translated = asyncio.run(
        CommandTranslator().translate(
            app_commands.locale_str("x"),
            Locale.american_english,
            _ctx(
                app_commands.TranslationContextLocation.command_description,
                name="comando_inexistente",
            ),
        )
    )
    assert translated is None
