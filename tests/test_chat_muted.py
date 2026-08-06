"""Tests del aviso de chat silenciado (cogs/chat.py).

Cubren el throttle por guild (mensaje completo → 🤐 dentro del cooldown) y la
regresión más delicada del reordenamiento de on_message: un canal ignorado
NUNCA debe guardar mensajes al corpus, con o sin mención al bot.

Sin bot ni red: db e i18n se parchean con monkeypatch, discord.Message se
simula con un fake mínimo, y el flujo async se ejecuta con asyncio.run.
"""

import asyncio
from types import SimpleNamespace

import pytest

import i18n
import cogs.chat as chat_mod
from cogs.chat import Chat
from config import get_dashboard_url

BOT_ID = 999


class FakeMessage:
    def __init__(self, mention=True, guild_id=1, channel_id=10, role_ids=()):
        self.id = 123
        self.author = SimpleNamespace(
            bot=False,
            id=5,
            display_name="user",
            mention="<@5>",
            # discord.py trae los roles con el miembro: no hay llamada extra.
            roles=[SimpleNamespace(id=rid) for rid in role_ids],
        )
        self.guild = SimpleNamespace(id=guild_id, name="Guild")
        self.channel_sent: list[str] = []
        self.channel = SimpleNamespace(
            id=channel_id,
            send=self._channel_send,
            name="canal",
            mention=f"<#{channel_id}>",
        )
        self.content = "hola" + (f" <@{BOT_ID}>" if mention else " mundo")
        self.raw_mentions = [BOT_ID] if mention else []
        self.reference = None
        self.replies: list[str] = []
        self.reactions: list[str] = []

    async def reply(self, text):
        self.replies.append(text)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def _channel_send(self, text):
        self.channel_sent.append(text)


@pytest.fixture
def cog(monkeypatch):
    """Cog de Chat aislado: cooldowns limpios, db parcheada, azar desactivado."""
    chat_mod._muted_reply_cooldowns.clear()
    # random() = 1.0: nunca dispara la reacción aleatoria (0.05) ni el GIF (0.45).
    monkeypatch.setattr(chat_mod, "random", SimpleNamespace(random=lambda: 1.0))

    saved: list[str] = []

    async def fake_save(guild_id, channel_id, author_id, name, text, message_id=None):
        saved.append(text)
        return (False, False)

    async def fake_locale(guild_id):
        return "es"

    monkeypatch.setattr(chat_mod, "save_corpus_and_user_message", fake_save)
    monkeypatch.setattr(i18n, "guild_locale", fake_locale)

    bot = SimpleNamespace(user=SimpleNamespace(id=BOT_ID))
    return Chat(bot), saved, monkeypatch


def _patch_ctx(
    monkeypatch,
    ignored=False,
    enabled=True,
    rate_limit=0,
    corpus_allowed=True,
    reply_channels=(),
    spontaneous_channels=(),
    exempt_roles=(),
    gif_probability=0.45,
    frase_probability=0.0,
):
    """rate_limit=0 (sin tope) por default: estos tests miran el aviso de
    silenciado, no el anti-farmeo — ver test_mention_rate_limit.py.

    `corpus_allowed=True` por default porque la allowlist del corpus es un
    concepto aparte del silenciado; los tests que la miran la apagan explícito.
    `reply_channels=()` = responde a menciones en cualquier canal (default
    real), `spontaneous_channels=()` = habla por su cuenta en cualquier canal.
    Son dos allowlists independientes — ver test_mencion_y_espontaneo_son_
    independientes más abajo.
    """

    async def fake_ignored(guild_id, chan_id):
        return ignored

    async def fake_corpus_allowed(guild_id, chan_id):
        return corpus_allowed

    async def fake_settings(guild_id, channel_id):
        return {
            "enabled": enabled,
            "channel_id": None,  # deprecado: la lógica ya no lo lee
            "mention_rate_limit": rate_limit,
            "auto_generate_every": 15,
            "auto_generate_probability": 0.6,
            "reaction_probability": 0.05,
            "gif_response_probability": gif_probability,
            "frase_probability": frase_probability,
        }

    async def fake_mention_channels(guild_id):
        return list(reply_channels)

    async def fake_spontaneous_channels(guild_id):
        return list(spontaneous_channels)

    async def fake_exempt(guild_id):
        return list(exempt_roles)

    chat_mod._mention_hits.clear()
    monkeypatch.setattr(chat_mod, "is_channel_ignored", fake_ignored)
    monkeypatch.setattr(chat_mod, "is_corpus_allowed", fake_corpus_allowed)
    monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_settings)
    monkeypatch.setattr(chat_mod, "list_mention_channels", fake_mention_channels)
    monkeypatch.setattr(
        chat_mod, "list_spontaneous_channels", fake_spontaneous_channels
    )
    monkeypatch.setattr(chat_mod, "list_exempt_roles", fake_exempt)


# ─── Throttle: mensaje completo la primera vez, 🤐 dentro del cooldown ────────


def test_muted_full_message_then_reaction(cog):
    chat, _, mp = cog
    _patch_ctx(mp, enabled=False)

    m1 = FakeMessage()
    asyncio.run(chat.on_message(m1))
    assert m1.replies == [i18n.t("chat.muted.disabled", "es")]
    assert m1.reactions == []

    m2 = FakeMessage()
    asyncio.run(chat.on_message(m2))
    assert m2.replies == []
    assert m2.reactions == ["🤐"]


def test_muted_cooldown_is_per_guild(cog):
    chat, _, mp = cog
    _patch_ctx(mp, enabled=False)

    asyncio.run(chat.on_message(FakeMessage(guild_id=1)))
    other = FakeMessage(guild_id=2)
    asyncio.run(chat.on_message(other))
    # Otro guild no comparte el cooldown: recibe su mensaje completo.
    assert other.replies == [i18n.t("chat.muted.disabled", "es")]


def test_wrong_channel_names_configured_channel(cog):
    """Las menciones usan su propia allowlist (mention_channels), no el
    viejo settings.chat_channel_id."""
    chat, saved, mp = cog
    _patch_ctx(mp, enabled=True, reply_channels=[20])

    m = FakeMessage(channel_id=10)
    asyncio.run(chat.on_message(m))
    assert m.replies == [
        i18n.t(
            "chat.muted.wrong_channel",
            "es",
            channel="<#20>",
            url=get_dashboard_url(m.guild.id),
        )
    ]
    # Canal NO ignorado: el mensaje sí entra al corpus aunque el chat no responda.
    assert saved == ["hola"]


def test_lista_de_canales_vacia_responde_en_cualquiera(cog):
    """Default de un servidor sin configurar: no hay restricción de canal."""
    chat, _, mp = cog
    _patch_ctx(mp, enabled=True, reply_channels=[])
    _patch_generation(mp)

    m = FakeMessage(channel_id=10)
    asyncio.run(chat.on_message(m))
    assert m.replies == ["respuesta"]


def test_mencion_en_canal_de_la_lista_responde(cog):
    chat, _, mp = cog
    _patch_ctx(mp, enabled=True, reply_channels=[10, 20])
    _patch_generation(mp)

    m = FakeMessage(channel_id=10)
    asyncio.run(chat.on_message(m))
    assert m.replies == ["respuesta"]


def test_mencion_y_espontaneo_usan_allowlists_independientes(cog):
    """El canal 10 está habilitado para hablar solo pero NO para responder
    menciones: cada rama tiene que leer su propia tabla, no compartir una."""
    chat, saved, mp = cog
    _patch_ctx(mp, enabled=True, reply_channels=[20], spontaneous_channels=[10])
    _patch_generation(mp)

    async def fake_save_saved(
        guild_id, channel_id, author_id, name, text, message_id=None
    ):
        saved.append(text)
        return (True, True)

    def fake_auto_generate(guild_id, channel_id, every, probability):
        return True

    mp.setattr(chat_mod, "save_corpus_and_user_message", fake_save_saved)
    mp.setattr(
        chat_mod.generation, "note_message_for_auto_generate", fake_auto_generate
    )

    # Sin mención, en el canal 10: está en spontaneous_channels -> habla solo.
    plain = FakeMessage(mention=False, channel_id=10)
    asyncio.run(chat.on_message(plain))
    assert plain.channel_sent == ["respuesta"]

    # Con mención, en el MISMO canal 10: mention_channels solo tiene el 20,
    # así que avisa que está mudo ahí pese a hablar solo en ese canal.
    mentioned = FakeMessage(channel_id=10)
    asyncio.run(chat.on_message(mentioned))
    assert mentioned.replies == [
        i18n.t(
            "chat.muted.wrong_channel",
            "es",
            channel="<#20>",
            url=get_dashboard_url(mentioned.guild.id),
        )
    ]


# ─── Corpus: allowlist positiva ──────────────────────────────────────────────


def test_canal_fuera_del_allowlist_no_guarda_pero_si_responde(cog):
    """El corpus y la respuesta son decisiones independientes: un canal donde
    el bot no aprende igual contesta si lo mencionan."""
    chat, saved, mp = cog
    _patch_ctx(mp, corpus_allowed=False)
    _patch_generation(mp)

    m = FakeMessage()
    asyncio.run(chat.on_message(m))
    assert saved == []
    assert m.replies == ["respuesta"]


def test_canal_dentro_del_allowlist_si_guarda(cog):
    chat, saved, mp = cog
    _patch_ctx(mp, corpus_allowed=True)
    _patch_generation(mp)

    asyncio.run(chat.on_message(FakeMessage()))
    assert saved == ["hola"]


# ─── Regresión de corpus: canal ignorado nunca guarda ────────────────────────


def test_ignored_channel_never_saves_corpus(cog):
    chat, saved, mp = cog
    _patch_ctx(mp, ignored=True)

    # Sin mención: silencio total y nada al corpus (comportamiento original).
    plain = FakeMessage(mention=False)
    asyncio.run(chat.on_message(plain))
    assert plain.replies == [] and plain.reactions == []
    assert saved == []

    # Con mención: ahora explica por qué no responde, pero SIGUE sin guardar.
    mentioned = FakeMessage()
    asyncio.run(chat.on_message(mentioned))
    assert mentioned.replies == [
        i18n.t(
            "chat.muted.ignored_channel",
            "es",
            url=get_dashboard_url(mentioned.guild.id),
        )
    ]
    assert saved == []


# ─── Anti-farmeo: pasado el tope, on_message no emite absolutamente nada ─────


def _patch_generation(monkeypatch, reply="respuesta"):
    """Corta el Markov: estos tests miran si el bot habla o no, no qué dice.
    Sin esto la rama de respuesta real iría a la DB, que acá no está montada."""

    async def fake_generate(guild_id, channel_id, *, special_phrase_probability=None):
        return reply, True  # is_special=True: se manda tal cual, sin post-proceso

    monkeypatch.setattr(chat_mod.generation, "generate_response", fake_generate)


def test_rate_limit_silences_mentions_without_any_notice(cog):
    chat, saved, mp = cog
    _patch_ctx(mp, rate_limit=2)
    _patch_generation(mp)

    for _ in range(2):
        m = FakeMessage()
        asyncio.run(chat.on_message(m))
        assert m.replies and not m.reactions  # dentro del cupo: responde

    # Tercera mención de la misma hora: ni respuesta, ni reacción, ni aviso.
    over = FakeMessage()
    asyncio.run(chat.on_message(over))
    assert over.replies == [] and over.reactions == []
    # El mensaje igual entra al corpus: el tope frena las respuestas, no el aprendizaje.
    assert saved == ["hola", "hola", "hola"]


def test_rate_limit_beats_the_muted_notice(cog):
    """El aviso de 'chat desactivado' también es un mensaje spameable."""
    chat, _, mp = cog
    _patch_ctx(mp, enabled=False, rate_limit=1)

    first = FakeMessage()
    asyncio.run(chat.on_message(first))
    assert first.replies == [i18n.t("chat.muted.disabled", "es")]

    over = FakeMessage(guild_id=1)
    asyncio.run(chat.on_message(over))
    assert over.replies == [] and over.reactions == []


def test_rate_limit_is_per_user(cog):
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1)
    _patch_generation(mp)

    mine = FakeMessage()
    asyncio.run(chat.on_message(mine))
    assert mine.replies

    blocked = FakeMessage()
    asyncio.run(chat.on_message(blocked))
    assert blocked.replies == []

    # Otro usuario en el mismo servidor arranca con su cupo entero.
    other = FakeMessage()
    other.author = SimpleNamespace(bot=False, id=6, display_name="otro", roles=[])
    asyncio.run(chat.on_message(other))
    assert other.replies


# ─── Roles exentos del límite ────────────────────────────────────────────────


def test_rol_exento_ignora_el_tope_por_completo(cog):
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_roles=[777])
    _patch_generation(mp)

    # Con tope 1, el segundo mensaje de un usuario normal ya estaría mudo.
    for _ in range(5):
        m = FakeMessage(role_ids=[777])
        asyncio.run(chat.on_message(m))
        assert m.replies == ["respuesta"]


def test_rol_no_exento_sigue_topeado(cog):
    """Tener roles no alcanza: tiene que ser uno de la lista."""
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_roles=[777])
    _patch_generation(mp)

    primero = FakeMessage(role_ids=[123])
    asyncio.run(chat.on_message(primero))
    assert primero.replies == ["respuesta"]

    segundo = FakeMessage(role_ids=[123])
    asyncio.run(chat.on_message(segundo))
    assert segundo.replies == []


def test_sin_roles_exentos_configurados_el_tope_aplica_a_todos(cog):
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_roles=[])
    _patch_generation(mp)

    asyncio.run(chat.on_message(FakeMessage(role_ids=[777])))
    bloqueado = FakeMessage(role_ids=[777])
    asyncio.run(chat.on_message(bloqueado))
    assert bloqueado.replies == []


# ─── Probabilidades por servidor ─────────────────────────────────────────────


def test_la_probabilidad_de_gif_sale_de_los_settings(cog, monkeypatch):
    """random() = 0.5: con el default (0.45) manda texto; subiéndolo a 0.9 el
    mismo azar cae del lado del GIF."""
    chat, _, mp = cog
    _patch_generation(mp)
    monkeypatch.setattr(chat_mod, "random", SimpleNamespace(random=lambda: 0.5))

    async def fake_gif(guild_id):
        return "https://tenor.com/x.gif"

    monkeypatch.setattr(chat_mod, "get_live_gif", fake_gif)
    monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

    _patch_ctx(mp)  # gif_response_probability = 0.45
    texto = FakeMessage()
    asyncio.run(chat.on_message(texto))
    assert texto.replies == ["respuesta"]

    _patch_ctx(mp, gif_probability=0.9)
    gif = FakeMessage()
    asyncio.run(chat.on_message(gif))
    assert gif.replies == ["https://tenor.com/x.gif"]


# ─── Templating de frases especiales (Fase 5) ────────────────────────────────


def test_frase_especial_con_tag_se_renderiza_en_la_mencion_directa(cog):
    """Integración end-to-end: on_message aplica render_frase_template a la
    frase especial antes de responder a una mención -- el detalle de qué
    tags existen y cómo se resuelven ya se prueba en
    test_frase_templating.py, acá solo el enganche."""
    chat, _, mp = cog
    _patch_ctx(mp)

    async def fake_generate(guild_id, channel_id, *, special_phrase_probability=None):
        return "hola {{user.mention}}!", True

    mp.setattr(chat_mod.generation, "generate_response", fake_generate)

    m = FakeMessage()
    asyncio.run(chat.on_message(m))
    assert m.replies == ["hola <@5>!"]


async def _noop_counter(guild_id, name, by=1):
    return None


# ─── Overrides por canal (Fase 2) ────────────────────────────────────────────
# on_message resuelve settings vía get_effective_chat_settings; el detalle de
# cómo se resuelve (override de canal vs default del servidor) ya se prueba
# en test_chat_config.py -- acá solo se confirma el enganche: que on_message
# le pasa el channel_id correcto y que un cambio ahí de verdad afecta la
# conducta observable.


def test_on_message_resuelve_settings_con_el_channel_id_del_mensaje(cog, monkeypatch):
    chat, _, mp = cog
    _patch_generation(mp)

    calls = []

    async def spy_settings(guild_id, channel_id):
        calls.append((guild_id, channel_id))
        return {
            "enabled": True,
            "channel_id": None,
            "mention_rate_limit": 0,
            "auto_generate_every": 15,
            "auto_generate_probability": 0.6,
            "reaction_probability": 0.05,
            "gif_response_probability": 0.0,
            "frase_probability": 0.0,
        }

    monkeypatch.setattr(chat_mod, "get_effective_chat_settings", spy_settings)
    monkeypatch.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
    monkeypatch.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_false())
    monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
    monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())

    m = FakeMessage(channel_id=42)
    asyncio.run(chat.on_message(m))

    assert calls == [(m.guild.id, 42)]


async def _async_false():
    return False


async def _async_list():
    return []


def test_override_de_canal_cambia_la_conducta_observable(cog, monkeypatch):
    """gif_response_probability=1.0 solo en el canal 10: ahí manda GIF, en
    cualquier otro canal (sin override) sigue mandando texto."""
    chat, _, mp = cog
    _patch_generation(mp)
    monkeypatch.setattr(chat_mod, "random", SimpleNamespace(random=lambda: 0.5))
    monkeypatch.setattr(chat_mod, "bump_counter", _noop_counter)

    async def fake_gif(guild_id):
        return "https://tenor.com/x.gif"

    monkeypatch.setattr(chat_mod, "get_live_gif", fake_gif)

    async def fake_effective(guild_id, channel_id):
        gif_probability = 1.0 if channel_id == 10 else 0.0
        return {
            "enabled": True,
            "channel_id": None,
            "mention_rate_limit": 0,
            "auto_generate_every": 15,
            "auto_generate_probability": 0.6,
            "reaction_probability": 0.0,
            "gif_response_probability": gif_probability,
            "frase_probability": 0.0,
        }

    monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_effective)
    monkeypatch.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
    monkeypatch.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_false())
    monkeypatch.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
    monkeypatch.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())

    con_override = FakeMessage(channel_id=10)
    asyncio.run(chat.on_message(con_override))
    assert con_override.replies == ["https://tenor.com/x.gif"]

    sin_override = FakeMessage(channel_id=20)
    asyncio.run(chat.on_message(sin_override))
    assert sin_override.replies == ["respuesta"]
