"""Auditoría sección 9 (validación de entradas), punto 4: texto que el bot no
escribió terminando en un mensaje con SUS permisos de mención.

Tres orígenes distintos, la misma consecuencia -- un "@everyone" literal
metido por alguien que no tiene el permiso de mencionar a todos, repetido por
el bot que sí lo tiene:

- el apodo de un miembro cualquiera (/imitar lo interpola en la respuesta),
- el título de un video de YouTube (lo escribe quien sube el video),
- el nombre de un canal (el aviso de visibilidad limitada los lista).

Lo que se verifica es el AllowedMentions con el que sale cada mensaje, no el
texto: el texto puede traer lo que sea, el flag es lo que decide si pinguea.
"""

import asyncio
from types import SimpleNamespace

import pytest

import cogs.chat as chat_mod


# ── /imitar: el apodo lo elige el propio miembro ─────────────────────────────


class _FakeFollowup:
    def __init__(self):
        self.calls = []

    async def send(self, content, **kwargs):
        self.calls.append((content, kwargs.get("allowed_mentions")))


class _FakeInteraction:
    def __init__(self, guild_id=1):
        self.followup = _FakeFollowup()
        self.guild = SimpleNamespace(id=guild_id)
        self.user = SimpleNamespace(id=42, display_name="admin")
        self.channel = SimpleNamespace(id=10)
        self.response = SimpleNamespace(send_message=self._noop, defer=self._defer)

    async def _noop(self, *a, **kw):
        pass

    async def _defer(self, **kw):
        pass


def _imitar_cog():
    return chat_mod.Chat.__new__(chat_mod.Chat)


def _run_imitar(monkeypatch, *, count, result):
    """Corre /imitar con un usuario cuyo apodo es un @everyone literal."""
    monkeypatch.setattr(chat_mod.i18n, "guild_locale", _async_const("es"))
    monkeypatch.setattr(chat_mod, "count_user_messages", _async_const(count))
    monkeypatch.setattr(
        chat_mod.generation, "generate_markov_for_user", _async_const(result)
    )
    monkeypatch.setattr(chat_mod, "_check_generate_cooldown", lambda g, u: None)

    interaction = _FakeInteraction()
    usuario = SimpleNamespace(id=7, display_name="@everyone")
    cog = _imitar_cog()
    asyncio.run(cog.imitar.callback(cog, interaction, usuario))
    return interaction.followup.calls


def _async_const(value):
    async def _f(*args, **kwargs):
        return value

    return _f


@pytest.mark.parametrize(
    "count,result",
    [
        (5, None),  # "no tiene suficientes mensajes"
        (100, None),  # "no se pudo generar"
        (100, "texto generado"),  # respuesta real
    ],
)
def test_imitar_nunca_pinguea_everyone(monkeypatch, count, result):
    calls = _run_imitar(monkeypatch, count=count, result=result)

    assert calls, "se esperaba una respuesta de /imitar"
    content, allowed = calls[-1]
    assert "@everyone" in content, "el apodo hostil sí llega al texto"
    assert allowed is not None, "falta allowed_mentions en esta rama de /imitar"
    assert allowed.everyone is False
    assert allowed.roles is False


def test_safe_mentions_bloquea_everyone_y_roles():
    """_SAFE_MENTIONS es el flag compartido de todo lo que genera el chat.

    roles=False no es de adorno: una frase especial con un "<@&123>" escrito a
    mano pinguea al rol entero con los permisos del bot, que es justo lo que
    TEMPLATE_TAGS evita al no exponer un tag {{role.mention}}.
    """
    assert chat_mod._SAFE_MENTIONS.everyone is False
    assert chat_mod._SAFE_MENTIONS.roles is False


# ── YouTube: el título lo escribe quien sube el video ────────────────────────


def test_youtube_solo_permite_el_rol_configurado(monkeypatch):
    """Un video titulado "@everyone ..." no debe pinguear al servidor, pero el
    rol de aviso que configuró el admin sí tiene que seguir sonando."""
    import cogs.youtube as yt

    sent = []

    class _Chan:
        guild = SimpleNamespace(me=object())

        def permissions_for(self, _member):
            return SimpleNamespace(send_messages=True)

        async def send(self, content, allowed_mentions=None):
            sent.append((content, allowed_mentions))

    sub = {
        "guild_id": 1,
        "discord_channel_id": 10,
        "youtube_channel_id": "UCx",
        "last_video_id": "viejo",
        "mention_role_id": 555,
        "last_error": None,
    }
    video = {
        "id": "nuevo",
        "title": "@everyone regalo gratis",
        "url": "https://youtu.be/x",
        "author": "@here",
    }

    monkeypatch.setattr(yt, "get_all_youtube_subs", _async_const([sub]))
    monkeypatch.setattr(yt, "get_latest_video", _async_const(video))
    monkeypatch.setattr(yt, "update_last_video_id", _async_const(None))
    monkeypatch.setattr(yt, "set_youtube_sub_error", _async_const(None))
    monkeypatch.setattr(yt, "guild_locale", _async_const("es"))
    monkeypatch.setattr(yt.discord, "TextChannel", _Chan)

    cog = yt.YouTube.__new__(yt.YouTube)
    cog.bot = SimpleNamespace(get_channel=lambda cid: _Chan())
    asyncio.run(cog.check_youtube.coro(cog))

    assert len(sent) == 1
    content, allowed = sent[0]
    assert "@everyone" in content and "@here" in content
    assert allowed.everyone is False
    assert allowed.users is False
    assert [r.id for r in allowed.roles] == [555]


# ── Bienvenida: los nombres de canal los eligen los mods del servidor ────────


def test_aviso_de_visibilidad_no_menciona_a_nadie():
    """El aviso lista nombres de canal en crudo, así que un canal llamado
    "@everyone" lo convertía en un ping masivo.

    El envío vive dentro del handler on_guild_join, con media docena de
    dependencias de discord.py alrededor; reconstruirlo entero para verificar
    un kwarg cuesta más de lo que aporta, así que se comprueba que el nombre
    hostil efectivamente llega al texto y que ese call lleva el flag.
    """
    import inspect

    import cogs.settings as settings_mod

    canales = [SimpleNamespace(name="@everyone"), SimpleNamespace(name="general")]
    assert "@everyone" in settings_mod._format_channel_names(canales)

    src = inspect.getsource(settings_mod)
    idx = src.index('"welcome.limited_visibility"')
    assert "AllowedMentions.none()" in src[idx : idx + 600]
