"""Tests del aviso de chat silenciado (cogs/chat.py).

Cubren el throttle por guild (mensaje completo → 🤐 dentro del cooldown) y la
regresión más delicada del reordenamiento de on_message: un canal ignorado
NUNCA debe guardar mensajes al corpus, con o sin mención al bot.

Sin bot ni red: db e i18n se parchean con monkeypatch, discord.Message se
simula con un fake mínimo, y el flujo async se ejecuta con asyncio.run.
"""

import asyncio
import itertools
from types import SimpleNamespace

import pytest

import i18n
import cogs.chat as chat_mod
from cogs.chat import Chat
from config import get_dashboard_url

BOT_ID = 999
_next_message_id = itertools.count(1)


class FakeMessage:
    def __init__(self, mention=True, guild_id=1, channel_id=10, role_ids=()):
        # IDs únicas de verdad (como los snowflakes reales): on_message ahora
        # deduplica por message.id (ver _recent_message_ids en cogs/chat.py),
        # así que dos FakeMessage con el mismo id se pisarían entre sí.
        self.id = next(_next_message_id)
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

    async def reply(self, text, **kwargs):
        self.replies.append(text)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def _channel_send(self, text, **kwargs):
        self.channel_sent.append(text)


@pytest.fixture
def cog(monkeypatch):
    """Cog de Chat aislado: cooldowns limpios, db parcheada, azar desactivado."""
    chat_mod._muted_reply_cooldowns.clear()
    chat_mod._recent_message_ids.clear()
    chat_mod._spontaneous_cooldowns.clear()
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
    exempt_channels=(),
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

    async def fake_exempt_channels(guild_id):
        return list(exempt_channels)

    chat_mod._mention_hits.clear()
    chat_mod._rate_limit_warned.clear()
    monkeypatch.setattr(chat_mod, "is_channel_ignored", fake_ignored)
    monkeypatch.setattr(chat_mod, "is_corpus_allowed", fake_corpus_allowed)
    monkeypatch.setattr(chat_mod, "get_effective_chat_settings", fake_settings)
    monkeypatch.setattr(chat_mod, "list_mention_channels", fake_mention_channels)
    monkeypatch.setattr(
        chat_mod, "list_spontaneous_channels", fake_spontaneous_channels
    )
    monkeypatch.setattr(chat_mod, "list_exempt_roles", fake_exempt)
    monkeypatch.setattr(chat_mod, "list_exempt_channels", fake_exempt_channels)


# ─── Sección 5, ronda 1: reenvío de eventos duplicados del gateway ───────────
#
# El gateway de Discord puede reenviar el mismo MESSAGE_CREATE tras un RESUME
# (documentado, no hipotético). Sin dedup, el mismo message.id procesado dos
# veces respondía a la mención dos veces y gastaba doble cupo de
# mention_rate_limit -- el guardado al corpus ya era idempotente por
# UNIQUE(guild_id, message_id), pero la respuesta a mención no.


def test_mismo_message_id_procesado_dos_veces_no_duplica_la_respuesta(cog):
    chat, saved, mp = cog
    _patch_ctx(mp)
    _patch_generation(mp)

    original = FakeMessage()
    duplicate = FakeMessage()
    duplicate.id = original.id  # mismo message.id: reenvío del gateway

    asyncio.run(chat.on_message(original))
    asyncio.run(chat.on_message(duplicate))

    assert original.replies == ["respuesta"]
    assert duplicate.replies == []  # la segunda entrega es un no-op total
    assert saved == ["hola"]  # tampoco se re-intenta guardar al corpus


def test_mismo_message_id_concurrente_tampoco_duplica(cog):
    """Mismo escenario pero con las dos entregas llegando 'a la vez'
    (asyncio.gather), como sugiere el formato de la auditoría para simular
    concurrencia real en vez de secuencial."""
    chat, saved, mp = cog
    _patch_ctx(mp)
    _patch_generation(mp)

    m1 = FakeMessage()
    m2 = FakeMessage()
    m2.id = m1.id

    async def run():
        await asyncio.gather(chat.on_message(m1), chat.on_message(m2))

    asyncio.run(run())

    total_replies = len(m1.replies) + len(m2.replies)
    assert total_replies == 1  # una sola de las dos entregas respondió
    assert saved == ["hola"]


def test_excepcion_a_mitad_de_camino_no_deja_el_id_bloqueado_para_siempre(cog):
    """Si on_message tira una excepción antes de terminar, el message.id NO
    debe quedar marcado como "ya procesado" -- si el gateway reenvía ESE
    mismo mensaje (el escenario que _recent_message_ids existe para cubrir),
    merece un intento fresco, no quedar descartado en silencio para siempre
    por el guard de dedup."""
    chat, saved, mp = cog

    call_count = {"n": 0}

    async def flaky_settings(guild_id, channel_id):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("fallo transitorio (ej. R2/DB)")
        return {
            "enabled": True,
            "channel_id": None,
            "mention_rate_limit": 0,
            "auto_generate_every": 15,
            "auto_generate_probability": 0.6,
            "reaction_probability": 0.0,
            "gif_response_probability": 0.0,
            "frase_probability": 0.0,
        }

    mp.setattr(chat_mod, "get_effective_chat_settings", flaky_settings)
    mp.setattr(chat_mod, "is_channel_ignored", lambda *a: _async_false())
    mp.setattr(chat_mod, "is_corpus_allowed", lambda *a: _async_false())
    mp.setattr(chat_mod, "list_mention_channels", lambda *a: _async_list())
    mp.setattr(chat_mod, "list_exempt_roles", lambda *a: _async_list())
    mp.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())
    _patch_generation(mp)

    first = FakeMessage()
    with pytest.raises(RuntimeError):
        asyncio.run(chat.on_message(first))
    assert first.id not in chat_mod._recent_message_ids

    # Reenvío del gateway: mismo message.id, la causa del fallo ya no está
    # -- tiene que procesarse de cero, no quedar mudo por el guard.
    redelivered = FakeMessage()
    redelivered.id = first.id
    asyncio.run(chat.on_message(redelivered))
    assert redelivered.replies == ["respuesta"]


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


# ─── Piso de silencio de los mensajes espontáneos ────────────────────────────
#
# De los tres caminos que generan texto, el espontáneo era el único sin ningún
# freno: con auto_generate_every=1 y auto_generate_probability=100% el bot
# mandaba un mensaje por cada mensaje que aprendía (spam 1:1 con el canal), y
# las dos perillas están en el dashboard. _SPONTANEOUS_COOLDOWN es un piso que
# ninguna combinación de settings puede saltear.


def _patch_auto_generate_siempre(mp, saved):
    """El canal dispara la oportunidad de hablar solo en CADA mensaje: es la
    config patológica (every=1, probability=100%) que el piso tiene que cortar."""

    async def fake_save_saved(
        guild_id, channel_id, author_id, name, text, message_id=None
    ):
        saved.append(text)
        return (True, True)

    mp.setattr(chat_mod, "save_corpus_and_user_message", fake_save_saved)
    mp.setattr(
        chat_mod.generation,
        "note_message_for_auto_generate",
        lambda guild_id, channel_id, every, probability: True,
    )


def test_espontaneo_no_habla_dos_veces_seguidas_en_el_mismo_canal(cog):
    chat, saved, mp = cog
    _patch_ctx(mp)
    _patch_generation(mp)
    _patch_auto_generate_siempre(mp, saved)

    primero = FakeMessage(mention=False, channel_id=10)
    asyncio.run(chat.on_message(primero))
    assert primero.channel_sent == ["respuesta"]

    # Mismo canal, en el mismo instante: el piso lo calla, aunque every y
    # probability digan que le toca hablar.
    for _ in range(5):
        seguido = FakeMessage(mention=False, channel_id=10)
        asyncio.run(chat.on_message(seguido))
        assert seguido.channel_sent == []

    # El corpus sigue aprendiendo de todos: el piso frena el hablar, no el leer.
    # ("hola mundo" es el contenido que arma FakeMessage sin mención.)
    assert saved == ["hola mundo"] * 6


def test_el_piso_es_por_canal_no_por_servidor(cog):
    """Un canal activo no debe dejar mudos a los demás del mismo servidor."""
    chat, saved, mp = cog
    _patch_ctx(mp)
    _patch_generation(mp)
    _patch_auto_generate_siempre(mp, saved)

    a = FakeMessage(mention=False, channel_id=10)
    asyncio.run(chat.on_message(a))
    assert a.channel_sent == ["respuesta"]

    b = FakeMessage(mention=False, channel_id=99)
    asyncio.run(chat.on_message(b))
    assert b.channel_sent == ["respuesta"]


def test_pasado_el_piso_vuelve_a_hablar(cog):
    chat, saved, mp = cog
    _patch_ctx(mp)
    _patch_generation(mp)
    _patch_auto_generate_siempre(mp, saved)

    asyncio.run(chat.on_message(FakeMessage(mention=False, channel_id=10)))

    # Envejecer la marca del canal más allá del piso.
    key = (1, 10)
    chat_mod._spontaneous_cooldowns[key] -= chat_mod._SPONTANEOUS_COOLDOWN + 1

    despues = FakeMessage(mention=False, channel_id=10)
    asyncio.run(chat.on_message(despues))
    assert despues.channel_sent == ["respuesta"]


def test_el_piso_no_afecta_las_respuestas_a_menciones(cog):
    """Una mención directa tiene su propio límite (mention_rate_limit): que el
    bot acabe de hablar solo no puede dejarlo sin contestar a quien lo llama."""
    chat, saved, mp = cog
    _patch_ctx(mp)
    _patch_generation(mp)
    _patch_auto_generate_siempre(mp, saved)

    espontaneo = FakeMessage(mention=False, channel_id=10)
    asyncio.run(chat.on_message(espontaneo))
    assert espontaneo.channel_sent == ["respuesta"]

    mencion = FakeMessage(mention=True, channel_id=10)
    asyncio.run(chat.on_message(mencion))
    assert mencion.replies == ["respuesta"]


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

    async def fake_generate(guild_id, channel_id, *args, **kwargs):
        return reply, True  # is_special=True: se manda tal cual, sin post-proceso

    monkeypatch.setattr(chat_mod.generation, "generate_response", fake_generate)


def test_rate_limit_avisa_una_vez_y_despues_solo_reacciona(cog):
    """Antes, pegar contra el tope dejaba al bot completamente mudo: para quien
    lo sufría era indistinguible de "el bot está roto" (pasó de verdad, con
    capturas). Ahora avisa una vez por ventana y después solo reacciona ⏳."""
    chat, saved, mp = cog
    _patch_ctx(mp, rate_limit=2)
    _patch_generation(mp)

    for _ in range(2):
        m = FakeMessage()
        asyncio.run(chat.on_message(m))
        assert m.replies and not m.reactions  # dentro del cupo: responde

    # Tercera mención de la misma hora: el aviso completo, una sola vez.
    over = FakeMessage()
    asyncio.run(chat.on_message(over))
    assert over.replies == [i18n.t("chat.rate_limited", "es")]
    assert over.reactions == []

    # Cuarta y quinta: ya avisó en esta ventana, solo la reacción corta.
    for _ in range(2):
        again = FakeMessage()
        asyncio.run(chat.on_message(again))
        assert again.replies == []
        assert again.reactions == ["⏳"]

    # El mensaje igual entra al corpus: el tope frena las respuestas, no el aprendizaje.
    assert saved == ["hola"] * 5


def test_rate_limit_vuelve_a_avisar_cuando_rota_la_ventana(cog):
    """El aviso se rehabilita solo al rotar la ventana horaria, sin barrido:
    _rate_limit_warned se compara contra el inicio de ventana de _mention_hits."""
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1)
    _patch_generation(mp)

    asyncio.run(chat.on_message(FakeMessage()))  # consume el único cupo
    primero = FakeMessage()
    asyncio.run(chat.on_message(primero))
    assert primero.replies == [i18n.t("chat.rate_limited", "es")]

    dentro = FakeMessage()
    asyncio.run(chat.on_message(dentro))
    assert dentro.reactions == ["⏳"]  # misma ventana: sin texto

    # Envejecer la ventana del usuario más de una hora: arranca de cero.
    key = (1, 5)
    start, count = chat_mod._mention_hits[key]
    chat_mod._mention_hits[key] = (start - chat_mod._MENTION_RATE_WINDOW - 1, count)

    asyncio.run(chat.on_message(FakeMessage()))  # cupo nuevo: responde
    nueva_ventana = FakeMessage()
    asyncio.run(chat.on_message(nueva_ventana))
    assert nueva_ventana.replies == [i18n.t("chat.rate_limited", "es")]


def test_rate_limit_le_gana_al_aviso_de_silenciado(cog):
    """Con el cupo agotado, el aviso que sale es el del tope — no el de 'chat
    desactivado'. El camino del rate limit corta antes que _muted_reply."""
    chat, _, mp = cog
    _patch_ctx(mp, enabled=False, rate_limit=1)

    first = FakeMessage()
    asyncio.run(chat.on_message(first))
    assert first.replies == [i18n.t("chat.muted.disabled", "es")]

    over = FakeMessage(guild_id=1)
    asyncio.run(chat.on_message(over))
    assert over.replies == [i18n.t("chat.rate_limited", "es")]


def test_rate_limit_is_per_user(cog):
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1)
    _patch_generation(mp)

    mine = FakeMessage()
    asyncio.run(chat.on_message(mine))
    assert mine.replies == ["respuesta"]

    blocked = FakeMessage()
    asyncio.run(chat.on_message(blocked))
    assert blocked.replies == [i18n.t("chat.rate_limited", "es")]

    # Otro usuario en el mismo servidor arranca con su cupo entero.
    other = FakeMessage()
    other.author = SimpleNamespace(bot=False, id=6, display_name="otro", roles=[])
    asyncio.run(chat.on_message(other))
    assert other.replies == ["respuesta"]


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
    assert segundo.replies == [i18n.t("chat.rate_limited", "es")]


def test_sin_roles_exentos_configurados_el_tope_aplica_a_todos(cog):
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_roles=[])
    _patch_generation(mp)

    asyncio.run(chat.on_message(FakeMessage(role_ids=[777])))
    bloqueado = FakeMessage(role_ids=[777])
    asyncio.run(chat.on_message(bloqueado))
    assert bloqueado.replies == [i18n.t("chat.rate_limited", "es")]


# ─── Canales exentos del límite ──────────────────────────────────────────────
#
# Mismo concepto que los roles exentos pero por canal (#bot-testing y
# similares): un admin no debería tener que inventar un rol solo para eximir
# un canal.


def test_canal_exento_ignora_el_tope_por_completo(cog):
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_channels=[10])
    _patch_generation(mp)

    # Con tope 1, el segundo mensaje ya estaría topeado en un canal normal.
    for _ in range(5):
        m = FakeMessage(channel_id=10)
        asyncio.run(chat.on_message(m))
        assert m.replies == ["respuesta"]
        assert m.reactions == []


def test_canal_no_exento_sigue_topeado(cog):
    """La exención es del canal listado, no de todo el servidor."""
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_channels=[10])
    _patch_generation(mp)

    primero = FakeMessage(channel_id=99)
    asyncio.run(chat.on_message(primero))
    assert primero.replies == ["respuesta"]

    segundo = FakeMessage(channel_id=99)
    asyncio.run(chat.on_message(segundo))
    assert segundo.replies == [i18n.t("chat.rate_limited", "es")]


def test_canal_exento_no_gasta_cupo_del_usuario(cog):
    """Hablar en un canal exento no debe consumir el cupo que el usuario tiene
    para los demás canales: la exención saltea el conteo, no lo adelanta."""
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_channels=[10])
    _patch_generation(mp)

    for _ in range(3):
        asyncio.run(chat.on_message(FakeMessage(channel_id=10)))

    # El cupo del canal normal sigue intacto.
    normal = FakeMessage(channel_id=99)
    asyncio.run(chat.on_message(normal))
    assert normal.replies == ["respuesta"]


def test_sin_canales_exentos_el_tope_aplica_en_todos(cog):
    chat, _, mp = cog
    _patch_ctx(mp, rate_limit=1, exempt_channels=[])
    _patch_generation(mp)

    asyncio.run(chat.on_message(FakeMessage(channel_id=10)))
    bloqueado = FakeMessage(channel_id=10)
    asyncio.run(chat.on_message(bloqueado))
    assert bloqueado.replies == [i18n.t("chat.rate_limited", "es")]


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
    monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())

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
    monkeypatch.setattr(chat_mod, "list_exempt_channels", lambda *a: _async_list())

    con_override = FakeMessage(channel_id=10)
    asyncio.run(chat.on_message(con_override))
    assert con_override.replies == ["https://tenor.com/x.gif"]

    sin_override = FakeMessage(channel_id=20)
    asyncio.run(chat.on_message(sin_override))
    assert sin_override.replies == ["respuesta"]
