"""Chat: corpus, Markov y respuestas automáticas."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

import discord
import regex
from discord import app_commands
from discord.ext import commands

import generation
import i18n
from cogs.gifs import get_live_gif, save_gif_candidates
from cogs.memes import is_meme_trigger
from config import REFEED_ALL_MAX_MESSAGES, REFEED_MAX_MESSAGES, get_dashboard_url
from db import (
    bump_counter,
    count_corpus_messages,
    count_user_messages,
    get_channel_refeed_status,
    get_effective_chat_settings,
    get_effective_frase_pool,
    get_random_frase_especial,
    get_random_reaction,
    get_welcome_channel_id,
    is_channel_ignored,
    is_corpus_allowed,
    is_frase_allowed,
    list_channel_triggers,
    list_corpus_channels,
    list_exempt_channels,
    list_exempt_roles,
    list_ignored_channels,
    list_mention_channels,
    list_spontaneous_channels,
    mark_migration_applied,
    save_corpus_and_user_message,
    seed_corpus_allowed_channels,
    upsert_channel_refeed_status,
)
from utils import LRUDict, chunk_message, has_admin_permission

log = logging.getLogger(__name__)

# guild_id -> task de /refeed_channels en curso (evita dos corridas en paralelo)
_refeed_running: dict[int, asyncio.Task] = {}

# (guild_id, channel_id) con un _refeed_channel en curso -- _refeed_channel
# tiene tres entradas independientes (/refeed, /refeed_channels vía
# _refeed_guild, on_guild_channel_update) que no se conocen entre sí. Sin
# esto, dos corridas concurrentes sobre el MISMO canal leen el mismo
# channel_refeed_status, hacen el mismo trabajo por duplicado, y la que
# escribe último pisa el progreso de la otra en upsert_channel_refeed_status
# (COALESCE simple, sin comparar contra lo que ya hay) -- no pierde mensajes
# del corpus (UNIQUE(guild_id, message_id) los deduplica igual) pero hace
# retroceder newest/oldest_message_id y puede voltear backfill_complete de
# True a False, forzando un re-backfill innecesario. Guard central en
# _refeed_channel mismo: cubre las tres entradas sin tocar ninguna.
_refeeding_channels: set[tuple[int, int]] = set()

# Mención directa con el chat apagado/restringido/canal ignorado: la explicación
# completa sale a lo sumo una vez cada 15 min por guild; dentro del cooldown solo
# se reacciona con 🤐. Mismo patrón que _empty_reply_cooldowns en generation.py.
_MUTED_REPLY_COOLDOWN = 15 * 60
_muted_reply_cooldowns: LRUDict = LRUDict(256)

# Anti-farmeo de actividad/XP: interacciones por hora y por usuario, con el tope
# configurable por servidor (settings.mention_rate_limit). En memoria a
# propósito — es una ventana de una hora, no una métrica histórica: si el bot
# reinicia, todos arrancan con el cupo entero y no pasa nada.
# ponytail: LRUDict acotado en vez de barrer expirados; a 8192 claves las que se
# desalojan son las menos usadas, que es justo lo contrario de un farmeador.
_MENTION_RATE_WINDOW = 3600.0
_mention_hits: LRUDict = LRUDict(8192)

# (guild_id, user_id) -> inicio de la ventana en la que ya se avisó del tope.
# Antes, pegar contra el tope dejaba al bot completamente mudo con ese usuario:
# indistinguible de "el bot está roto" para quien lo sufre (pasó de verdad).
# Ahora avisa una vez por ventana y después solo reacciona, mismo patrón que
# _muted_reply. Se compara contra el inicio de ventana guardado en
# _mention_hits, así el aviso se rehabilita solo cuando la ventana rota — sin
# ningún barrido ni tarea de limpieza.
_rate_limit_warned: LRUDict = LRUDict(8192)

# El gateway de Discord puede reenviar el mismo MESSAGE_CREATE tras un RESUME
# (documentado, no hipotético): sin este guard, el mismo message.id procesado
# dos veces dispara una respuesta a mención (o un trigger de canal) duplicada
# y gasta doble cupo de mention_rate_limit por nada. El guardado al corpus ya
# es idempotente por UNIQUE(guild_id, message_id) -- esto es lo que le falta
# al resto del handler (reacción, trigger, respuesta a mención).
_recent_message_ids: LRUDict = LRUDict(2048)

# /generar e /imitar llaman a generation.generate_markov_reply/
# generate_markov_for_user (query + build/generate del modelo, en el
# ThreadPoolExecutor default compartido por todo el proceso) y no tenían
# ningún límite: a diferencia de una mención, ningún miembro necesita permiso
# de admin para invocarlos, así que cualquiera podía spamearlos en loop.
# Mismo patrón que _check_meme_cooldown en cogs/memes.py.
_GENERATE_COOLDOWN_SECONDS = 10
_generate_cooldowns: LRUDict = LRUDict(1024)

# Triggers con acción 'markov'/'mezcla': a propósito no comparten el cooldown
# de frases especiales (ver _run_trigger_action) porque un trigger es una
# regla explícita que debe disparar siempre que matchee. Pero "siempre que
# matchee" incluye que cualquier miembro del canal -- no solo quien configuró
# el trigger -- spamee el patrón en loop y fuerce generación real de Markov
# sin ningún freno. Este cooldown es corto a propósito (imperceptible para
# uso normal) y es por canal, no por usuario: frena el loop sin tocar la
# semántica de "siempre responde" para mensajes espaciados normalmente.
_TRIGGER_MARKOV_COOLDOWN = 5.0
_trigger_markov_cooldowns: LRUDict = LRUDict(1024)

# Piso de silencio entre dos mensajes espontáneos en el MISMO canal. De los
# tres caminos que generan texto, este era el único sin ningún freno: una
# mención pasa por mention_rate_limit y un trigger por
# _TRIGGER_MARKOV_COOLDOWN, pero hablar por su cuenta solo dependía de
# auto_generate_every y auto_generate_probability -- los dos configurables
# desde el dashboard. Con every=1 y probability=100% el bot contestaba un
# mensaje por cada mensaje que aprendía, o sea spam 1:1 con el canal, y la
# única salida visible para el servidor era echarlo.
#
# Piso de silencio entre dos mensajes espontáneos en el MISMO canal. De los
# tres caminos que generan texto, este era el único sin ningún freno: una
# mención pasa por mention_rate_limit y un trigger por
# _TRIGGER_MARKOV_COOLDOWN, pero hablar por su cuenta solo dependía de
# auto_generate_every y auto_generate_probability -- los dos configurables
# desde el dashboard. Con every=1 y probability=100% el bot contestaba un
# mensaje por cada mensaje que aprendía, o sea spam 1:1 con el canal, y la
# única salida visible para el servidor era echarlo.
#
# A propósito NO es configurable por servidor: es un piso de seguridad, y un
# piso que el admin puede bajar a 0 no es un piso. Queda holgado (45 s) para
# no cambiarle la conducta a nadie que ya tenga una config sana -- solo corta
# el caso patológico.
#
# NOTA DE SEGURIDAD (S8): Esta constante es una defensa de ritmo por canal en
# Discord. La protección PRINCIPAL contra agotamiento del ThreadPoolExecutor
# compartido por múltiples guilds/canales reside en generation.markov_limiter (semáforo
# global con descarte no-bloqueante), no en un cooldown local.
_SPONTANEOUS_COOLDOWN = 45.0
_spontaneous_cooldowns: LRUDict = LRUDict(1024)


def _check_generate_cooldown(guild_id: int, user_id: int) -> int | None:
    """None si puede generar (y marca el cooldown); si no, segundos restantes."""
    now = time.time()
    key = (guild_id, user_id)
    elapsed = now - _generate_cooldowns.get(key, 0)
    if elapsed < _GENERATE_COOLDOWN_SECONDS:
        return int(_GENERATE_COOLDOWN_SECONDS - elapsed)
    _generate_cooldowns[key] = now
    return None


def _check_trigger_markov_cooldown(guild_id: int, channel_id: int) -> bool:
    """True si un trigger puede generar Markov en este canal ahora (y lo marca)."""
    now = time.monotonic()
    key = (guild_id, channel_id)
    last = _trigger_markov_cooldowns.get(key)
    if last is not None and now - last < _TRIGGER_MARKOV_COOLDOWN:
        return False
    _trigger_markov_cooldowns[key] = now
    return True


def _check_spontaneous_cooldown(guild_id: int, channel_id: int) -> bool:
    """True si el bot puede hablar solo en este canal ahora (y lo marca).

    Se marca al consultar, no al enviar: así también frena los intentos de
    generación cuando el canal viene disparando la oportunidad una y otra vez,
    y cubre por igual el camino del GIF y el del texto.
    """
    now = time.monotonic()
    key = (guild_id, channel_id)
    last = _spontaneous_cooldowns.get(key)
    if last is not None and now - last < _SPONTANEOUS_COOLDOWN:
        return False
    _spontaneous_cooldowns[key] = now
    return True


def _consume_interaction(guild_id: int, user_id: int, limit: int) -> bool:
    """True si al usuario le queda cupo en su ventana de 1 h (y lo consume).

    False cuando ya llegó al tope: quien llama debe callarse por completo, sin
    avisar del límite — el aviso sería otro mensaje spameable.
    """
    if limit <= 0:
        return True  # 0 (o negativo por config vieja) = sin límite
    now = time.monotonic()
    key = (guild_id, user_id)
    # El default arranca la ventana en `now`, no en 0: con el bot recién
    # levantado monotonic() es chico y un 0.0 daría una ventana ya vencida.
    start, count = _mention_hits.get(key, (now, 0))
    if now - start >= _MENTION_RATE_WINDOW:
        start, count = now, 0
    if count >= limit:
        _mention_hits[key] = (start, count)  # refresca el LRU, no el cupo
        return False
    _mention_hits[key] = (start, count + 1)
    return True


def _should_warn_rate_limit(guild_id: int, user_id: int) -> bool:
    """True la primera vez que este usuario pega contra el tope en la ventana
    actual (y lo marca); False el resto de las veces dentro de la misma ventana.

    Se llama solo después de que _consume_interaction devolvió False, así que
    _mention_hits ya tiene la entrada con el inicio de ventana vigente.
    """
    key = (guild_id, user_id)
    start = _mention_hits.get(key, (None, 0))[0]
    if _rate_limit_warned.get(key) == start:
        return False
    _rate_limit_warned[key] = start
    return True


# Reintentos ante errores HTTP transitorios (5xx, timeouts) al paginar el
# historial durante el refeed; discord.Forbidden/NotFound no se reintentan.
_HISTORY_FETCH_RETRIES = 3

# Prefijos de comandos: el propio ("!", commands.Bot) y los más comunes de
# otros bots de Discord (MEE6, Dyno, Carl-bot, FredBoat...). Un mensaje que
# empieza así casi seguro es un comando dirigido a algún bot, no charla real
# -- ni entra al corpus ni dispara una respuesta espontánea o a mención.
# Deja afuera a propósito símbolos que también aparecen en chat normal
# (roleplay con "*acción*", asteriscos de énfasis, "+1"): el costo de un
# falso negativo (aprende de un comando raro) es más bajo que el de bloquear
# charla real.
# ponytail: lista fija; si hace falta por servidor, se vuelve configurable
# con el mismo patrón que las demás allowlists de settings.
OTHER_BOT_PREFIXES = ("!", "?", ".", "-", "$", ">", "~", ";")

# Timeout real para el matching de triggers tipo 'regex' (segundos). El
# módulo `regex` (no `re` de stdlib) acepta un `timeout=` que corta un
# patrón con backtracking catastrófico desde adentro del motor de matching
# -- `re` no tiene forma de interrumpirse a sí mismo. Igual corre en un
# hilo aparte (ver _trigger_matches) para que ese medio segundo, en el peor
# caso, no bloquee el event loop del bot entero.
_TRIGGER_REGEX_TIMEOUT = 0.5


def _regex_search_with_timeout(pattern: str, content: str) -> bool:
    """Sync a propósito: la llama asyncio.to_thread, no directo."""
    try:
        return (
            regex.search(pattern, content, timeout=_TRIGGER_REGEX_TIMEOUT) is not None
        )
    except TimeoutError:
        log.warning("Trigger con regex catastrófico (timeout): %r", pattern)
        return False
    except regex.error:
        log.warning("Trigger con regex inválido: %r", pattern)
        return False


# Todo lo que sale de acá (Markov entrenado con el corpus de CUALQUIER
# miembro, una frase especial escrita por un admin, o el apodo que se puso un
# miembro cualquiera) se manda sin revisión humana previa. Si el texto trae un
# "@everyone"/"@here" literal -- aprendido de un mensaje viejo, o tipeado a
# mano en una frase -- el bot lo repite con sus propios permisos y pinguea al
# servidor entero. everyone=False cubre las dos palabras (Discord las trata
# como el mismo flag "everyone" en allowed_mentions.parse).
#
# roles=False por el mismo motivo: un "<@&id>" literal escondido en una frase
# pinguea al rol entero con los permisos del bot, aunque quien escribió la
# frase no tenga "Mencionar a todos los roles". Es exactamente el agujero que
# TEMPLATE_TAGS evita al no exponer un tag {{role.mention}} -- sin esto, la
# mención cruda por atrás lo dejaba abierto igual. Ningún texto generado
# necesita pinguear roles; los avisos que sí lo hacen a propósito (YouTube)
# arman su propio AllowedMentions con el rol puntual configurado.
_SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False)


async def _trigger_matches(trigger: dict, content: str) -> bool:
    pattern = trigger["pattern"]
    match_type = trigger["match_type"]
    if match_type == "exact":
        return content.lower() == pattern.lower()
    if match_type == "starts_with":
        return content.lower().startswith(pattern.lower())
    if match_type == "regex":
        return await asyncio.to_thread(_regex_search_with_timeout, pattern, content)
    return False


# Tags disponibles en frases especiales -- whitelist CERRADA a propósito:
# reemplazo por string matching simple (str.replace, ver render_frase_template),
# nunca un motor de templates real (Jinja2 y similares) sobre texto que
# escribe un admin del servidor -- eso sí sería una superficie de inyección
# (acceso a atributos/métodos arbitrarios del objeto que se le pase).
#
# Sin tag de mención de rol a propósito: {{role.mention}} sobre un texto que
# cualquier admin puede editar es una forma fácil de esconder un @everyone/
# @here en una frase que dispara sola -- si hace falta en algún momento, se
# avisa antes de agregarlo, no se agrega solo.
TEMPLATE_TAGS = (
    "{{user.mention}}",
    "{{user.name}}",
    "{{channel.name}}",
    "{{channel.mention}}",
    "{{guild.name}}",
    "{{markov.word}}",
    "{{markov.sentence}}",
)


async def render_frase_template(text: str, *, author, channel, guild) -> str:
    """Reemplaza los tags de TEMPLATE_TAGS presentes en `text` por su valor
    real. Cualquier `{{lo que sea}}` que no esté en la whitelist queda tal
    cual, como texto literal -- no se interpreta ni se evalúa nada.

    `author`/`channel`/`guild` en vez de un discord.Message: lo llaman tanto
    on_message (con message.author/channel/guild) como el comando /generar
    (con interaction.user/channel/guild), que no comparten una clase base
    con esos atributos.
    """
    if "{{" not in text:
        return text  # atajo: la gran mayoría de las frases no usa tags
    literal = {
        "{{user.mention}}": author.mention,
        "{{user.name}}": author.display_name,
        "{{channel.name}}": getattr(channel, "name", "") or "",
        "{{channel.mention}}": getattr(channel, "mention", "") or "",
        "{{guild.name}}": guild.name if guild else "",
    }
    for tag, value in literal.items():
        if tag in text:
            text = text.replace(tag, value)
    if guild and "{{markov.word}}" in text:
        word = await generation.generate_markov_word(guild.id)
        text = text.replace("{{markov.word}}", word or "")
    if guild and "{{markov.sentence}}" in text:
        sentence = await generation.generate_markov_reply(guild.id)
        text = text.replace("{{markov.sentence}}", sentence or "")
    return text


# ─── Playground del dashboard (Fase 7) ───────────────────────────────────────
# Reimplementan la decisión de _run_trigger_action/generate_response pero de
# solo lectura: nada de esto puede bumpear contadores, gastar el cooldown
# real de frases especiales ni escribir en el corpus -- probar la config no
# puede tener efectos secundarios sobre la conducta real del bot.


async def _simulate_trigger_action(
    guild_id: int, trigger: dict, settings: dict
) -> tuple[str | None, bool]:
    """Como _run_trigger_action, pero devuelve el texto en vez de mandarlo.
    El segundo valor dice si es una frase (y por lo tanto hay que pasarla
    por render_frase_template) o texto de Markov (que no lleva tags)."""
    action = trigger["action"]
    if action == "frase_de_pack":
        phrase = await get_random_frase_especial(guild_id, trigger["pack_id"])
        return phrase, True
    if action == "markov":
        text = await generation.generate_markov_reply(guild_id)
        return (
            generation.post_process_reply(text) if text is not None else None
        ), False
    # 'mezcla'
    if settings["frase_probability"] >= 1.0:
        phrase = await get_random_frase_especial(guild_id, trigger["pack_id"])
        if phrase is not None:
            return phrase, True
        return None, True
    if random.random() < settings["frase_probability"]:
        phrase = await get_random_frase_especial(guild_id, trigger["pack_id"])
        if phrase is not None:
            return phrase, True
    text = await generation.generate_markov_reply(guild_id)
    return (generation.post_process_reply(text) if text is not None else None), False


async def _simulate_special_or_markov(
    guild_id: int, channel_id: int, probability: float
) -> tuple[str | None, bool]:
    """Como generation.generate_response, pero SIN tocar
    generation._special_phrase_cooldowns -- probar el playground no puede
    gastar el cooldown real de 40 minutos de las frases espontáneas."""
    if probability >= 1.0:
        if not await is_frase_allowed(guild_id, channel_id):
            return None, True
        pack_id = await get_effective_frase_pool(guild_id, channel_id)
        phrase = await get_random_frase_especial(guild_id, pack_id)
        if phrase is None:
            return None, True
        return phrase, True

    if random.random() < probability and await is_frase_allowed(guild_id, channel_id):
        pack_id = await get_effective_frase_pool(guild_id, channel_id)
        phrase = await get_random_frase_especial(guild_id, pack_id)
        if phrase is not None:
            return phrase, True
    text = await generation.generate_markov_reply(guild_id)
    return text, False


async def _entrega_avisos(guild_id: int, channel_id: int, user_id: int, settings: dict):
    """Códigos de aviso sobre lo que frenaría el mensaje ANTES de llegar al
    motor de generación, sin consumir ni gastar nada.

    `simulate_message` no puede devolver un solo veredicto para esto: cada
    freno aplica a una vía distinta de entrega (mención vs. hablar solo) y el
    playground no pregunta por cuál llegaría el mensaje. Así que en vez de
    inventar una respuesta única, se listan los frenos activos y cada texto
    del dashboard aclara a qué vía corresponde -- que es justo la pregunta que
    el admin trae ("¿por qué no me contesta?").
    """
    avisos: list[str] = []

    # `enabled` gatea SOLO la rama de menciones (un único chequeo en
    # on_message): con el chat apagado, los mensajes espontáneos, las
    # reacciones y los triggers siguen saliendo igual.
    if not settings["enabled"]:
        avisos.append("chat_desactivado")

    mention_channels = await list_mention_channels(guild_id)
    if mention_channels and channel_id not in mention_channels:
        avisos.append("canal_sin_menciones")

    spontaneous = await list_spontaneous_channels(guild_id)
    if spontaneous and channel_id not in spontaneous:
        avisos.append("canal_sin_espontaneo")

    # Tope horario de menciones: se mira el cupo real de quien está probando
    # (el admin logueado), sin consumirlo -- por eso no se usa
    # _consume_interaction acá.
    limit = settings["mention_rate_limit"]
    if limit > 0:
        exento = channel_id in await list_exempt_channels(guild_id)
        if not exento:
            start, count = _mention_hits.get((guild_id, user_id), (None, 0))
            vigente = (
                start is not None and time.monotonic() - start < _MENTION_RATE_WINDOW
            )
            if vigente and count >= limit:
                avisos.append("cupo_horario_agotado")

    # Piso de silencio del canal (ver _SPONTANEOUS_COOLDOWN): igual que arriba,
    # se consulta sin marcarlo, para no gastarle el cooldown real al canal.
    last = _spontaneous_cooldowns.get((guild_id, channel_id))
    if last is not None and time.monotonic() - last < _SPONTANEOUS_COOLDOWN:
        avisos.append("cooldown_espontaneo")

    return avisos


async def simulate_message(
    guild_id: int, channel_id: int, content: str, *, author, channel, guild
) -> dict:
    """Corre la lógica de decisión de on_message contra un mensaje de
    prueba -- sin mandar nada a Discord, sin guardar nada al corpus, sin
    bumpear contadores ni gastar cooldowns reales. Usado por el endpoint
    del playground del dashboard.

    `would_respond`/`reason` describen el MOTOR de generación (triggers y la
    decisión frase-vs-Markov) con la config efectiva del canal. Lo que puede
    frenar al mensaje antes de llegar al motor -- chat apagado, allowlists de
    mención/espontáneo, tope horario, piso de silencio -- viene aparte en
    `avisos`, porque depende de por qué vía llegaría el mensaje y el
    playground no lo pregunta (ver _entrega_avisos). El mute total de un canal
    ignorado sí es inequívoco y corta como reason.
    """
    settings = await get_effective_chat_settings(guild_id, channel_id)
    if await is_channel_ignored(guild_id, channel_id):
        # Mute total: los demás avisos serían ruido al lado de esto.
        return {
            "would_respond": False,
            "reason": "canal_ignorado",
            "text": None,
            "avisos": [],
        }

    avisos = await _entrega_avisos(
        guild_id, channel_id, getattr(author, "id", 0), settings
    )

    triggers = await list_channel_triggers(guild_id, channel_id)
    stripped = content.strip()
    for trigger in triggers:
        if await _trigger_matches(trigger, stripped):
            text, is_frase = await _simulate_trigger_action(guild_id, trigger, settings)
            if text is None:
                return {
                    "would_respond": False,
                    "reason": "trigger_sin_contenido",
                    "trigger_id": trigger["id"],
                    "text": None,
                    "avisos": avisos,
                }
            final = (
                await render_frase_template(
                    text, author=author, channel=channel, guild=guild
                )
                if is_frase
                else text
            )
            return {
                "would_respond": True,
                "reason": "trigger",
                "trigger_id": trigger["id"],
                "text": final,
                "avisos": avisos,
            }

    text, is_special = await _simulate_special_or_markov(
        guild_id, channel_id, settings["frase_probability"]
    )
    if text is None:
        return {
            "would_respond": False,
            "reason": "sin_corpus_suficiente",
            "text": None,
            "avisos": avisos,
        }
    final = (
        await render_frase_template(text, author=author, channel=channel, guild=guild)
        if is_special
        else generation.post_process_reply(text)
    )
    return {
        "would_respond": True,
        "reason": "frase_especial" if is_special else "markov",
        "text": final,
        "avisos": avisos,
    }


# Nombre de la migración por servidor que rellena corpus_allowed_channels.
# Cambiar este string haría que la migración corra de nuevo y pise lo que un
# admin haya configurado a mano — no tocar.
CORPUS_ALLOWLIST_MIGRATION = "corpus_allowlist_v1"


async def ensure_corpus_migrated(guild: discord.Guild) -> int | None:
    """Rellena la allowlist del corpus de un guild **que ya existía antes** del
    modelo de allowlist, con su estado real de hoy.

    El modelo de corpus pasó de "ignorar canales" a "solo estos canales". Los
    servidores que ya existían tienen la lista vacía, que en el modelo nuevo
    significa "no aprender de nada": sin este relleno dejarían de aprender de
    golpe el día del deploy.

    Solo la llama on_ready, para guilds donde el bot ya estaba antes del
    deploy. Un guild genuinamente nuevo (on_guild_join) NO pasa por acá — ver
    Chat.on_guild_join.

    Corre **una sola vez por servidor**: el flag se marca primero y solo el que
    logra marcarlo hace el trabajo, así dos llamadas simultáneas de on_ready no
    se pisan ni sobreescriben lo que un admin ya ajustó.

    Devuelve cuántos canales sembró, o None si la migración ya estaba hecha.
    """
    if not await mark_migration_applied(guild.id, CORPUS_ALLOWLIST_MIGRATION):
        return None
    try:
        ignored = set(await list_ignored_channels(guild.id))
        # Los canales de texto reales del guild, no solo los que ya tienen
        # mensajes guardados: un canal vacío igual debe quedar habilitado.
        channel_ids = [c.id for c in guild.text_channels if c.id not in ignored]
        seeded = await seed_corpus_allowed_channels(guild.id, channel_ids)
        log.info(
            "Corpus: %s canales habilitados en %s (%s) por la migración",
            seeded,
            guild.name,
            guild.id,
        )
        return seeded
    except Exception:
        # El flag ya quedó marcado: si esto falla, el guild se queda sin
        # aprender hasta que un admin use el dashboard. Se loguea fuerte
        # porque es exactamente el caso que la migración venía a evitar.
        log.exception(
            "Corpus: falló la migración del guild %s — quedó sin canales de "
            "aprendizaje, hay que configurarlos desde el dashboard",
            guild.id,
        )
        return 0


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Migra los servidores que ya estaban antes del cambio de modelo.

        on_ready se repite en cada reconexión; `ensure_corpus_migrated` es
        idempotente por su flag, así que las corridas siguientes solo hacen una
        consulta indexada por guild.
        """
        for guild in self.bot.guilds:
            await ensure_corpus_migrated(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Un servidor nuevo arranca sin aprender de nada: lista vacía de
        verdad, coherente con lo que promete el dashboard. Solo marca la
        migración como aplicada (no hay nada viejo que preservar en un guild
        recién unido), así on_ready no intenta sembrarla después."""
        await mark_migration_applied(guild.id, CORPUS_ALLOWLIST_MIGRATION)

    async def _exempt_from_rate_limit(self, message: discord.Message) -> bool:
        """True si esta mención se saltea el tope: por canal o por rol del autor.

        El canal se chequea primero porque no depende del miembro (un canal
        exento lo es para todos) y evita recorrer roles al vuelo.
        `message.author.roles` ya viene cacheado con el miembro: no hay llamada
        extra a la API. En un DM el autor es User y no tiene roles.
        """
        exempt_channels = await list_exempt_channels(message.guild.id)
        if message.channel.id in exempt_channels:
            return True
        roles = getattr(message.author, "roles", None)
        if not roles:
            return False
        exempt = await list_exempt_roles(message.guild.id)
        if not exempt:
            return False
        return any(r.id in exempt for r in roles)

    async def _save_message_to_corpus(
        self, guild_id: int, message: discord.Message
    ) -> str:
        """Limpia y guarda un mensaje en corpus + user_corpus.
        Retorna "saved", "discarded" (filtrado por clean_for_corpus) o
        "duplicate" (ya estaba en el corpus, UNIQUE(guild_id, message_id))."""
        cleaned = generation.clean_for_corpus(message.content or "")
        if cleaned is None:
            return "discarded"
        corpus_ins, user_ins = await save_corpus_and_user_message(
            guild_id,
            message.channel.id,
            message.author.id,
            message.author.display_name,
            cleaned,
            message_id=message.id,
        )
        if corpus_ins:
            generation.note_corpus_insert(guild_id, message.channel.id)
        if user_ins:
            generation.note_user_corpus_insert(guild_id, message.author.id)
        return "saved" if corpus_ins else "duplicate"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.id in _recent_message_ids:
            return
        _recent_message_ids[message.id] = True
        try:
            await self._on_message_impl(message)
        except Exception:
            # Si el handler no llegó a terminar (excepción a mitad de camino:
            # una llamada a R2/Discord que falló, un error de DB), NO dejar
            # este message.id marcado como "ya procesado" -- si el gateway
            # reenvía este mismo mensaje (RESUME), merece un intento fresco,
            # no quedar descartado en silencio por el guard de dedup de
            # arriba. discord.py ya loguea la excepción (_run_event/on_error
            # default) y sigue con el resto de los listeners -- acá solo se
            # deshace la marca antes de dejarla propagar.
            _recent_message_ids.pop(message.id, None)
            raise

    async def _on_message_impl(self, message: discord.Message) -> None:
        if is_meme_trigger(self.bot, message):
            return  # lo maneja el cog de memes; no entra al corpus
        if (message.content or "").strip().startswith(OTHER_BOT_PREFIXES):
            return  # comando de prefijo (propio o de otro bot): ver OTHER_BOT_PREFIXES

        auto_generate = False
        ignored = False
        settings = None

        if message.guild:
            # Resuelto por canal: cada tunable puede tener override en
            # channel_settings (tab CHAT del dashboard); si no, cae al
            # default del servidor. Ver get_effective_chat_settings en db.py.
            settings = await get_effective_chat_settings(
                message.guild.id, message.channel.id
            )
            # Un canal ignorado no entra al corpus ni recibe reacciones, pero ya
            # no corta la función: una mención directa merece respuesta (abajo).
            ignored = await is_channel_ignored(message.guild.id, message.channel.id)
            if not ignored:
                # Allowlist positiva del corpus: el canal tiene que estar
                # habilitado explícitamente. Lista vacía = no aprende de nada.
                if await is_corpus_allowed(message.guild.id, message.channel.id):
                    status = await self._save_message_to_corpus(
                        message.guild.id, message
                    )
                    if status == "saved":
                        auto_generate = generation.note_message_for_auto_generate(
                            message.guild.id,
                            message.channel.id,
                            every=settings["auto_generate_every"],
                            probability=settings["auto_generate_probability"],
                        )

                # Reacción aleatoria con emoji del pool configurable
                if random.random() < settings["reaction_probability"]:
                    try:
                        reaction = await get_random_reaction(message.guild.id)
                        if reaction:
                            await message.add_reaction(reaction["emoji_text"])
                    except Exception:
                        log.exception("Error añadiendo reacción emoji")

                # Triggers configurados a mano (tab CHAT del dashboard): si
                # matchea alguno, responde y corta acá -- no espera mención
                # ni el roll de auto_generate_probability. Independiente de
                # corpus_allowed/spontaneous_channels/mention_channels; solo
                # respeta el mute de `ignored` (por eso está adentro del
                # `if not ignored`).
                try:
                    if await self._handle_trigger(message, settings):
                        return
                except Exception:
                    log.exception("Error ejecutando un trigger de canal")

        # Verificar si el bot fue mencionado o si le respondieron a él directamente
        mention_bot = bool(
            self.bot.user and self.bot.user.id in (message.raw_mentions or [])
        )
        reply_to_bot = False
        if message.reference and message.reference.message_id and self.bot.user:
            ref_msg = message.reference.resolved
            if isinstance(ref_msg, discord.Message):
                reply_to_bot = ref_msg.author.id == self.bot.user.id

        if not (mention_bot or reply_to_bot):
            if message.guild and auto_generate:
                # Allowlist de "canales donde habla espontáneamente" (tab CHAT
                # del dashboard). Lista vacía = sin restricción: participa en
                # cualquier canal, que es el default de un servidor recién
                # invitado. Independiente de mention_channels — una mención
                # directa usa su propia allowlist, más abajo.
                allowed = await list_spontaneous_channels(message.guild.id)
                if allowed and message.channel.id not in allowed:
                    return
                # Piso de silencio del canal: lo último antes de generar, así
                # ninguna combinación de every/probability puede saltearlo.
                if not _check_spontaneous_cooldown(
                    message.guild.id, message.channel.id
                ):
                    return
                try:
                    if random.random() < settings["gif_response_probability"]:
                        gif_url = await get_live_gif(message.guild.id)
                        if gif_url:
                            await message.channel.send(gif_url)
                            await bump_counter(message.guild.id, "gifs_enviados")
                            return
                    text, is_special = await generation.generate_response(
                        message.guild.id,
                        message.channel.id,
                        special_phrase_probability=settings["frase_probability"],
                        wait=False,
                    )
                    if text is not None:
                        if is_special:
                            final = await render_frase_template(
                                text,
                                author=message.author,
                                channel=message.channel,
                                guild=message.guild,
                            )
                        else:
                            final = generation.post_process_reply(text)
                        for chunk in chunk_message(final):
                            await message.channel.send(
                                chunk, allowed_mentions=_SAFE_MENTIONS
                            )
                        await bump_counter(message.guild.id, "mensajes_enviados")
                except Exception:
                    log.exception("Error en generación automática de respuesta")
            return

        if not message.guild:
            return

        # Pasado el tope de la hora no hay respuesta generada, pero sí un aviso
        # de por qué (una vez por ventana; después solo una reacción). Va antes
        # de todo lo demás que manda mensajes —incluido _muted_reply— para que
        # este camino sea el único que contesta cuando el cupo se agotó.
        # Los canales y roles exentos se saltan el tope entero.
        if not await self._exempt_from_rate_limit(message):
            if not _consume_interaction(
                message.guild.id, message.author.id, settings["mention_rate_limit"]
            ):
                await self._rate_limited_reply(message)
                return

        # Mención directa pero el bot no puede conversar aquí: avisar por qué
        # en vez de guardar silencio (el usuario cree que el bot está muerto).
        if ignored:
            locale = await i18n.guild_locale(message.guild.id)
            await self._muted_reply(
                message,
                "chat.muted.ignored_channel",
                url=get_dashboard_url(message.guild.id, locale),
            )
            return

        # Respetar restricciones de canal y modo de chat
        if not settings["enabled"]:
            await self._muted_reply(message, "chat.muted.disabled")
            return

        # Allowlist propia de "canales donde responde a menciones" (tab CHAT →
        # Canales del dashboard), independiente de spontaneous_channels.
        # Lista vacía = responde en cualquier canal (default).
        reply_channels = await list_mention_channels(message.guild.id)
        if reply_channels and message.channel.id not in reply_channels:
            locale = await i18n.guild_locale(message.guild.id)
            await self._muted_reply(
                message,
                "chat.muted.wrong_channel",
                channel=", ".join(f"<#{cid}>" for cid in reply_channels[:5]),
                url=get_dashboard_url(message.guild.id, locale),
            )
            return

        if random.random() < settings["gif_response_probability"]:
            gif_url = await get_live_gif(message.guild.id)
            if gif_url:
                await message.reply(gif_url)
                await bump_counter(message.guild.id, "gifs_enviados")
                return

        res = await generation.generate_response(
            message.guild.id,
            message.channel.id,
            special_phrase_probability=settings["frase_probability"],
        )
        text, is_special = res
        if text is None:
            locale = await i18n.guild_locale(message.guild.id)
            if getattr(res, "reason", None) is not None:
                url = get_dashboard_url(
                    message.guild.id,
                    locale,
                    "chat#contenido"
                    if res.reason == "no_phrases"
                    else "chat#canales"
                    if res.reason == "channel_not_allowed"
                    else "",
                )
                reply = generation.empty_frase_reply(
                    message.guild.id, res.reason, locale, throttle=True, url=url
                )
                if reply is None:
                    return
            else:
                # Servidor sin historial suficiente: explicar en vez de contestar "...".
                # throttle=True: las instrucciones completas salen 1 vez cada 15 min por guild.
                reply = generation.empty_corpus_reply(
                    message.guild.id, locale, throttle=True
                )
        elif is_special:
            reply = await render_frase_template(
                text,
                author=message.author,
                channel=message.channel,
                guild=message.guild,
            )
        else:
            reply = generation.post_process_reply(text)
        for chunk in chunk_message(reply):
            await message.reply(chunk, allowed_mentions=_SAFE_MENTIONS)
        await bump_counter(message.guild.id, "mensajes_enviados")

    async def _send_trigger_reply(self, message: discord.Message, text: str) -> None:
        for chunk in chunk_message(text):
            await message.channel.send(chunk, allowed_mentions=_SAFE_MENTIONS)
        await bump_counter(message.guild.id, "mensajes_enviados")

    async def _run_trigger_action(
        self,
        message: discord.Message,
        guild_id: int,
        trigger: dict,
        settings: dict,
    ) -> bool:
        """True si el trigger efectivamente mandó algo. 'frase_de_pack'/
        'mezcla' pueden no mandar nada si el pool de ese pack está vacío --
        eso no es un error, simplemente no hay nada que decir."""
        action = trigger["action"]
        if action == "frase_de_pack":
            phrase = await get_random_frase_especial(guild_id, trigger["pack_id"])
            if phrase is None:
                return False
            rendered = await render_frase_template(
                phrase,
                author=message.author,
                channel=message.channel,
                guild=message.guild,
            )
            await self._send_trigger_reply(message, rendered)
            return True
        if action == "markov":
            if not _check_trigger_markov_cooldown(guild_id, message.channel.id):
                return False
            text = await generation.generate_markov_reply(guild_id)
            if text is None:
                return False
            await self._send_trigger_reply(message, generation.post_process_reply(text))
            return True
        # 'mezcla': mismo roll que la conducta espontánea/de mención
        # (frase_probability), pero con el pack_id de ESTE trigger en vez
        # del que tenga asignado el canal -- así un trigger puede apuntar a
        # un pack puntual sin depender de frase_pack_channels. Sin el
        # cooldown de generation._special_phrase_cooldowns a propósito: ese
        # cooldown es para no saturar de frases las apariciones espontáneas,
        # pero un trigger es una regla explícita que el admin configuró para
        # que dispare siempre que matchee.
        if settings["frase_probability"] >= 1.0:
            phrase = await get_random_frase_especial(guild_id, trigger["pack_id"])
            if phrase is not None:
                rendered = await render_frase_template(
                    phrase,
                    author=message.author,
                    channel=message.channel,
                    guild=message.guild,
                )
                await self._send_trigger_reply(message, rendered)
                return True
            return False
        if random.random() < settings["frase_probability"]:
            phrase = await get_random_frase_especial(guild_id, trigger["pack_id"])
            if phrase is not None:
                rendered = await render_frase_template(
                    phrase,
                    author=message.author,
                    channel=message.channel,
                    guild=message.guild,
                )
                await self._send_trigger_reply(message, rendered)
                return True
        if not _check_trigger_markov_cooldown(guild_id, message.channel.id):
            return False
        text = await generation.generate_markov_reply(guild_id)
        if text is None:
            return False
        await self._send_trigger_reply(message, generation.post_process_reply(text))
        return True

    async def _handle_trigger(self, message: discord.Message, settings: dict) -> bool:
        """True si algún trigger configurado en este canal matcheó y ya se
        respondió -- el llamador tiene que cortar ahí el resto de
        on_message. Se prueban en orden de creación (id ascendente, ver
        list_channel_triggers); el primero que matchea gana, no se
        combinan ni se siguen probando los demás."""
        triggers = await list_channel_triggers(message.guild.id, message.channel.id)
        if not triggers:
            return False
        content = (message.content or "").strip()
        for trigger in triggers:
            if await _trigger_matches(trigger, content):
                return await self._run_trigger_action(
                    message, message.guild.id, trigger, settings
                )
        return False

    async def _muted_reply(self, message: discord.Message, key: str, **fmt) -> None:
        """Explica por qué el bot no conversa aquí. Primera vez en la ventana de
        cooldown del guild: mensaje completo; después solo reacciona con 🤐."""
        guild_id = message.guild.id
        now = time.monotonic()
        last = _muted_reply_cooldowns.get(guild_id)
        if last is not None and now - last < _MUTED_REPLY_COOLDOWN:
            try:
                await message.add_reaction("🤐")
            except discord.HTTPException:
                pass  # sin permiso de reaccionar o mensaje borrado: no importa
            return
        _muted_reply_cooldowns[guild_id] = now
        locale = await i18n.guild_locale(guild_id)
        try:
            await message.reply(i18n.t(key, locale, **fmt))
        except discord.HTTPException:
            log.debug("No se pudo enviar aviso de chat silenciado", exc_info=True)

    async def _rate_limited_reply(self, message: discord.Message) -> None:
        """Avisa que el usuario agotó su cupo de menciones de la hora. Primera vez
        en su ventana: el aviso completo; después solo una reacción ⏳, para que
        el aviso no se vuelva el spam que el propio tope trata de evitar."""
        if not _should_warn_rate_limit(message.guild.id, message.author.id):
            try:
                await message.add_reaction("⏳")
            except discord.HTTPException:
                pass  # sin permiso de reaccionar o mensaje borrado: no importa
            return
        locale = await i18n.guild_locale(message.guild.id)
        try:
            await message.reply(i18n.t("chat.rate_limited", locale))
        except discord.HTTPException:
            log.debug("No se pudo enviar aviso de límite de menciones", exc_info=True)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ):
        """Si un canal ya elegido para el corpus pasa de invisible a visible
        para el bot, lo lee solo y avisa en el canal de bienvenida — sin
        esperar a que alguien corra /refeed_channels. Un canal que nunca se
        eligió no se lee solo por volverse visible: la allowlist manda."""
        if not isinstance(after, discord.TextChannel):
            return
        me = after.guild.me
        if me is None:
            return
        before_perms = before.permissions_for(me)
        after_perms = after.permissions_for(me)
        could_see = before_perms.view_channel and before_perms.read_message_history
        can_see_now = after_perms.view_channel and after_perms.read_message_history
        if could_see or not can_see_now:
            return  # no hubo ganancia de visibilidad
        if await is_channel_ignored(after.guild.id, after.id):
            return
        if not await is_corpus_allowed(after.guild.id, after.id):
            return

        try:
            res = await self._refeed_channel(
                after.guild.id, after, REFEED_ALL_MAX_MESSAGES
            )
        except Exception:
            log.exception(
                "on_guild_channel_update: error leyendo canal recién visible %s (%s)",
                after.id,
                after.guild.id,
            )
            return
        if res["saved"] <= 0:
            return
        channel_id = await get_welcome_channel_id(after.guild.id)
        if not channel_id:
            return
        report_channel = after.guild.get_channel(channel_id)
        if report_channel is None:
            return
        try:
            locale = await i18n.guild_locale(after.guild.id)
            await report_channel.send(
                i18n.t(
                    "chat.channel_visible_report",
                    locale,
                    channel=after.mention,
                    saved=f"{res['saved']:,}",
                )
            )
        except Exception:
            log.debug("on_guild_channel_update: no se pudo avisar en %s", channel_id)

    # --- COMANDOS ---

    @app_commands.command(
        name="generar",
        description="Genera un mensaje usando la memoria del canal.",
    )
    async def generar(self, interaction: discord.Interaction):
        locale = await i18n.guild_locale(
            interaction.guild.id if interaction.guild else None
        )
        if not interaction.guild:
            await interaction.response.send_message(
                i18n.t("general.guild_only", locale), ephemeral=True
            )
            return

        remaining = _check_generate_cooldown(interaction.guild.id, interaction.user.id)
        if remaining is not None:
            await interaction.response.send_message(
                i18n.t("chat.generate_cooldown", locale, seconds=remaining),
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        if interaction.channel is None:
            await interaction.followup.send(
                i18n.t("chat.cannot_determine_channel", locale), ephemeral=True
            )
            return
        settings = await get_effective_chat_settings(
            interaction.guild.id, interaction.channel.id
        )
        res = await generation.generate_response(
            interaction.guild.id,
            interaction.channel.id,
            special_phrase_probability=settings["frase_probability"],
        )
        text, is_special = res
        if text is None:
            if getattr(res, "reason", None) is not None:
                url = get_dashboard_url(
                    interaction.guild.id,
                    locale,
                    "chat#contenido"
                    if res.reason == "no_phrases"
                    else "chat#canales"
                    if res.reason == "channel_not_allowed"
                    else "",
                )
                reply = generation.empty_frase_reply(
                    interaction.guild.id, res.reason, locale, throttle=False, url=url
                )
            else:
                # Comando explícito: siempre el mensaje completo con instrucciones.
                reply = generation.empty_corpus_reply(interaction.guild.id, locale)
        elif is_special:
            reply = await render_frase_template(
                text,
                author=interaction.user,
                channel=interaction.channel,
                guild=interaction.guild,
            )
        else:
            reply = generation.post_process_reply(text)
        await interaction.followup.send(reply, allowed_mentions=_SAFE_MENTIONS)

    @app_commands.command(
        name="imitar",
        description="Genera un mensaje imitando el estilo de un usuario del servidor.",
    )
    @app_commands.describe(usuario="Usuario a imitar")
    async def imitar(self, interaction: discord.Interaction, usuario: discord.Member):
        locale = await i18n.guild_locale(
            interaction.guild.id if interaction.guild else None
        )
        if not interaction.guild:
            await interaction.response.send_message(
                i18n.t("general.guild_only", locale), ephemeral=True
            )
            return

        remaining = _check_generate_cooldown(interaction.guild.id, interaction.user.id)
        if remaining is not None:
            await interaction.response.send_message(
                i18n.t("chat.generate_cooldown", locale, seconds=remaining),
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        count = await count_user_messages(interaction.guild.id, usuario.id)
        if count < 30:
            await interaction.followup.send(
                i18n.t(
                    "chat.imitar_not_enough_messages",
                    locale,
                    user=usuario.display_name,
                    count=count,
                ),
                allowed_mentions=_SAFE_MENTIONS,
            )
            return

        result = await generation.generate_markov_for_user(
            interaction.guild.id, usuario.id
        )
        if result is None:
            await interaction.followup.send(
                i18n.t(
                    "chat.imitar_generation_failed", locale, user=usuario.display_name
                ),
                allowed_mentions=_SAFE_MENTIONS,
            )
            return

        await interaction.followup.send(
            i18n.t(
                "chat.imitar_result", locale, user=usuario.display_name, text=result
            ),
            allowed_mentions=_SAFE_MENTIONS,
        )

    # --- CORPUS ---

    async def _fetch_history_batch(
        self, channel, **kwargs
    ) -> list[discord.Message] | None:
        """channel.history(**kwargs) con reintentos ante HTTPException transitorio
        (5xx, timeouts) o discord.RateLimited (429 con max_ratelimit_timeout agotado).
        Nota: discord.RateLimited NO hereda de HTTPException en discord.py, así que
        se captura aparte; es la única de las dos que trae .retry_after en la práctica.
        Devuelve None si se agotan los reintentos; deja que discord.Forbidden/NotFound
        se propaguen tal cual, sin reintentar."""
        for attempt in range(_HISTORY_FETCH_RETRIES):
            try:
                return [msg async for msg in channel.history(**kwargs)]
            except (discord.Forbidden, discord.NotFound):
                raise
            except (discord.HTTPException, discord.RateLimited) as e:
                if attempt == _HISTORY_FETCH_RETRIES - 1:
                    log.exception(
                        "_refeed_channel: fallo persistente leyendo historial de %s "
                        "tras %d intentos",
                        channel.id,
                        _HISTORY_FETCH_RETRIES,
                    )
                    return None
                wait = getattr(e, "retry_after", None) or 2**attempt
                log.warning(
                    "_refeed_channel: error transitorio leyendo historial de %s "
                    "(intento %d/%d), reintentando en %.1fs",
                    channel.id,
                    attempt + 1,
                    _HISTORY_FETCH_RETRIES,
                    wait,
                )
                await asyncio.sleep(wait)
        return None

    async def _refeed_channel(self, guild_id: int, channel, max_messages: int) -> dict:
        """Wrapper de _refeed_channel_locked con el guard de _refeeding_channels
        (ver su comentario): si este canal ya tiene una corrida en curso
        -- por cualquiera de las tres entradas -- no arranca una segunda,
        devuelve el mismo dict "no hice nada" que la allowlist vacía."""
        key = (guild_id, channel.id)
        if key in _refeeding_channels:
            return {
                "saved": 0,
                "gifs_saved": 0,
                "backfill_complete": False,
                "was_incremental": False,
                "forbidden": False,
            }
        _refeeding_channels.add(key)
        try:
            return await self._refeed_channel_locked(guild_id, channel, max_messages)
        finally:
            _refeeding_channels.discard(key)

    async def _refeed_channel_locked(
        self, guild_id: int, channel, max_messages: int
    ) -> dict:
        """Lee el historial de un canal hacia el corpus, con estado persistente por canal.

        Si el backfill ya terminó, hace lectura incremental hacia adelante (sin límite);
        si no, continúa hacia atrás desde donde quedó, hasta max_messages.
        Retorna {"saved", "backfill_complete", "was_incremental", "forbidden"}.

        Punto único donde se filtra el corpus en las lecturas masivas: acá pasan
        /refeed, /refeed_channels y el canal que se vuelve visible. Un canal
        fuera de la allowlist sale sin leer nada, en vez de pagar la
        paginación para descartar mensaje por mensaje.
        """
        if not await is_corpus_allowed(guild_id, channel.id):
            return {
                "saved": 0,
                "gifs_saved": 0,
                "backfill_complete": False,
                "was_incremental": False,
                "forbidden": False,
            }
        status = await get_channel_refeed_status(guild_id, channel.id)
        saved = 0
        gifs_saved = 0
        discarded = 0
        duplicate = 0
        fetched = 0
        forbidden = False

        if status and status["backfill_complete"]:
            newest = status["newest_message_id"]
            attempt = 0
            while attempt < _HISTORY_FETCH_RETRIES:
                after_obj = discord.Object(id=newest) if newest else None
                try:
                    async for msg in channel.history(
                        limit=None, after=after_obj, oldest_first=True
                    ):
                        fetched += 1
                        if newest is None or msg.id > newest:
                            newest = msg.id
                        if msg.author.bot:
                            continue
                        gifs_saved += await save_gif_candidates(guild_id, msg)
                        result = await self._save_message_to_corpus(guild_id, msg)
                        if result == "saved":
                            saved += 1
                        elif result == "discarded":
                            discarded += 1
                        else:
                            duplicate += 1
                    break
                except discord.Forbidden:
                    forbidden = True
                    break
                except (discord.HTTPException, discord.RateLimited) as e:
                    attempt += 1
                    # newest ya avanzó con lo procesado hasta el corte; el reintento
                    # (o la próxima corrida, si se agotan los intentos) retoma desde ahí.
                    if attempt >= _HISTORY_FETCH_RETRIES:
                        log.exception(
                            "_refeed_channel: error persistente leyendo incremental de %s "
                            "tras %d intentos, se retoma en newest_message_id=%s en la próxima corrida",
                            channel.id,
                            attempt,
                            newest,
                        )
                        break
                    wait = getattr(e, "retry_after", None) or 2**attempt
                    log.warning(
                        "_refeed_channel: error transitorio leyendo incremental de %s "
                        "(intento %d/%d) en newest_message_id=%s, reintentando en %.1fs",
                        channel.id,
                        attempt,
                        _HISTORY_FETCH_RETRIES,
                        newest,
                        wait,
                    )
                    await asyncio.sleep(wait)
            await upsert_channel_refeed_status(
                guild_id, channel.id, newest_message_id=newest
            )
            log.info(
                "_refeed_channel: %s (incremental) fetched=%d saved=%d gifs_saved=%d discarded=%d duplicate=%d",
                channel.id,
                fetched,
                saved,
                gifs_saved,
                discarded,
                duplicate,
            )
            return {
                "saved": saved,
                "gifs_saved": gifs_saved,
                "backfill_complete": True,
                "was_incremental": True,
                "forbidden": forbidden,
            }

        # Backfill hacia atrás: reanuda desde oldest_message_id si una corrida previa quedó a medias.
        newest_seen = status["newest_message_id"] if status else None
        oldest = status["oldest_message_id"] if status else None
        complete = False

        while fetched < max_messages:
            before_obj = discord.Object(id=oldest) if oldest else None
            try:
                batch = await self._fetch_history_batch(
                    channel, limit=100, before=before_obj, oldest_first=False
                )
            except discord.Forbidden:
                forbidden = True
                break
            if batch is None:
                # Reintentos agotados en _fetch_history_batch (ya logueado ahí):
                # se corta acá, oldest_message_id queda guardado para retomar.
                log.warning(
                    "_refeed_channel: backfill de %s cortado en oldest_message_id=%s, "
                    "se retoma en la próxima corrida",
                    channel.id,
                    oldest,
                )
                break
            if not batch:
                complete = True
                break
            fetched += len(batch)
            if newest_seen is None or batch[0].id > newest_seen:
                newest_seen = batch[0].id

            for msg in batch:
                if msg.author.bot:
                    continue
                gifs_saved += await save_gif_candidates(guild_id, msg)
                result = await self._save_message_to_corpus(guild_id, msg)
                if result == "saved":
                    saved += 1
                elif result == "discarded":
                    discarded += 1
                else:
                    duplicate += 1

            oldest = batch[-1].id

        log.info(
            "_refeed_channel: %s (backfill) fetched=%d saved=%d gifs_saved=%d discarded=%d duplicate=%d complete=%s",
            channel.id,
            fetched,
            saved,
            gifs_saved,
            discarded,
            duplicate,
            complete,
        )
        await upsert_channel_refeed_status(
            guild_id,
            channel.id,
            newest_message_id=newest_seen,
            oldest_message_id=oldest,
            backfill_complete=complete,
        )
        return {
            "saved": saved,
            "gifs_saved": gifs_saved,
            "backfill_complete": complete,
            "was_incremental": False,
            "forbidden": forbidden,
        }

    async def _refeed_guild(
        self, guild: discord.Guild, progress_msg, report_channel
    ) -> dict:
        """Recorre los canales que están en la allowlist del corpus (los que el
        admin eligió, no todos los canales de texto del guild) editando
        progress_msg con el avance, y manda el resumen final con
        report_channel.send() (no depende de ningún interaction).
        Retorna el dict totals para que el caller decida el mensaje de cierre."""
        totals = {
            "saved": 0,
            "gifs_saved": 0,
            "completed": 0,
            "incremental": 0,
            "partial": 0,
            "forbidden": 0,
            "errors": 0,
        }
        allowed_channel_ids = await list_corpus_channels(guild.id)
        if not allowed_channel_ids:
            try:
                await report_channel.send(
                    "⚠️ No hay canales elegidos todavía — anda al dashboard "
                    "(tab CHAT > Canales) y elige de dónde quiero aprender."
                )
            except Exception:
                log.warning(
                    "refeed_guild: no se pudo avisar allowlist vacía en %s", guild.id
                )
            return totals
        me = guild.me
        if me is None and self.bot.user is not None:
            me = guild.get_member(self.bot.user.id)
        if me is None:
            log.warning(
                "refeed_guild: no puedo determinar los permisos del bot en %s", guild.id
            )
            return totals
        done_lines: list[str] = []

        def render(current: str | None) -> str:
            # ponytail: colapsa el detalle viejo en un contador para no pasar los 2000 chars
            shown = done_lines[-8:]
            lines = []
            if len(done_lines) > len(shown):
                lines.append(f"✅ {len(done_lines) - len(shown)} canales procesados")
            lines += shown
            if current:
                lines.append(current)
            return "\n".join(lines)[:1990] or "🔄 Leyendo historial…"

        async def update(current: str | None) -> None:
            if progress_msg is None:
                return
            try:
                await progress_msg.edit(content=render(current))
            except Exception:
                log.debug(
                    "refeed_guild: no se pudo editar el mensaje de progreso",
                    exc_info=True,
                )

        for channel_id in allowed_channel_ids:
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            perms = channel.permissions_for(me)
            if not (perms.read_messages and perms.read_message_history):
                continue
            if await is_channel_ignored(guild.id, channel.id):
                continue

            await update(f"🔄 {channel.mention} — leyendo historial…")
            try:
                res = await self._refeed_channel(
                    guild.id, channel, REFEED_ALL_MAX_MESSAGES
                )
            except Exception:
                log.exception(
                    "refeed_guild: error procesando canal %s (%s)", channel.id, guild.id
                )
                totals["errors"] += 1
                done_lines.append(f"❌ {channel.mention} — error inesperado")
                continue

            totals["saved"] += res["saved"]
            totals["gifs_saved"] += res["gifs_saved"]
            if res["forbidden"]:
                totals["forbidden"] += 1
                done_lines.append(
                    f"🚫 {channel.mention} — sin permisos para leer el historial"
                )
            elif res["was_incremental"]:
                totals["incremental"] += 1
                done_lines.append(
                    f"⏭️ {channel.mention} — ya estaba al día ({res['saved']} mensajes nuevos)"
                )
            elif res["backfill_complete"]:
                totals["completed"] += 1
                done_lines.append(
                    f"✅ {channel.mention} — {res['saved']:,} mensajes nuevos (historial completo)"
                )
            else:
                totals["partial"] += 1
                # Un canal parcial tiene >REFEED_ALL_MAX_MESSAGES mensajes: /refeed
                # directo ahí tiene un límite por corrida mucho más alto.
                done_lines.append(
                    f"✅ {channel.mention} — {res['saved']:,} mensajes nuevos (historial incompleto por el límite; "
                    f"tip: `/refeed` directo en ese canal lee hasta {REFEED_MAX_MESSAGES:,} por corrida)"
                )

        await update(None)

        gifs_suffix = (
            f" y {totals['gifs_saved']:,} GIF(s) nuevo(s)"
            if totals["gifs_saved"]
            else ""
        )
        parts = [
            f"🏁 Terminé de leer el historial. Total: {totals['saved']:,} mensajes nuevos guardados{gifs_suffix}."
        ]
        if totals["completed"]:
            parts.append(
                f"✅ {totals['completed']} canal(es) con historial completo por primera vez."
            )
        if totals["incremental"]:
            parts.append(f"⏭️ {totals['incremental']} canal(es) que ya estaban al día.")
        if totals["partial"]:
            parts.append(
                f"⚠️ {totals['partial']} canal(es) quedaron incompletos por el límite de {REFEED_ALL_MAX_MESSAGES:,} mensajes; ejecuta `/refeed_channels` de nuevo para continuar donde quedó."
            )
        if totals["forbidden"]:
            parts.append(f"🚫 {totals['forbidden']} canal(es) sin permisos para leer.")
        if totals["errors"]:
            parts.append(f"❌ {totals['errors']} canal(es) con error.")
        try:
            await report_channel.send("\n".join(parts))
        except Exception:
            log.warning(
                "refeed_guild: no se pudo enviar el resumen final en %s", guild.id
            )
        return totals

    def start_refeed_channels(
        self,
        guild: discord.Guild,
        progress_msg,
        report_channel,
        on_done: Callable[[dict], Awaitable[None]] | None = None,
    ) -> bool:
        """Lanza el refeed de todo el guild en background. False si ya hay uno corriendo.
        on_done recibe el dict totals del refeed."""
        existing = _refeed_running.get(guild.id)
        if existing and not existing.done():
            return False

        async def runner():
            try:
                totals = await self._refeed_guild(guild, progress_msg, report_channel)
                if on_done is not None:
                    await on_done(totals)
            except Exception:
                log.exception("refeed_channels: fallo procesando guild %s", guild.id)
            finally:
                _refeed_running.pop(guild.id, None)

        _refeed_running[guild.id] = asyncio.create_task(runner())
        return True

    @app_commands.command(
        name="refeed",
        description="Importa los últimos mensajes del canal a la memoria del bot.",
    )
    async def refeed(self, interaction: discord.Interaction):
        locale = await i18n.guild_locale(
            interaction.guild.id if interaction.guild else None
        )
        if not interaction.guild:
            await interaction.response.send_message(
                i18n.t("general.guild_only", locale), ephemeral=True
            )
            return

        if not has_admin_permission(interaction):
            await interaction.response.send_message(
                i18n.t("general.error.no_permission", locale), ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send(
                i18n.t("chat.refeed.cannot_read_history", locale)
            )
            return

        if await is_channel_ignored(interaction.guild.id, channel.id):
            await interaction.followup.send(
                i18n.t("chat.refeed.channel_ignored", locale)
            )
            return

        if not await is_corpus_allowed(interaction.guild.id, channel.id):
            await interaction.followup.send(
                i18n.t("chat.refeed.channel_not_allowed", locale)
            )
            return

        res = await self._refeed_channel(
            interaction.guild.id, channel, REFEED_MAX_MESSAGES
        )

        if res["forbidden"] and res["saved"] == 0:
            await interaction.followup.send(i18n.t("chat.refeed.forbidden", locale))
            return
        gifs_suffix = (
            i18n.t("chat.refeed.gifs_suffix", locale, count=res["gifs_saved"])
            if res["gifs_saved"]
            else ""
        )
        if res["was_incremental"]:
            result = i18n.t(
                "chat.refeed.result_incremental",
                locale,
                saved=res["saved"],
                gifs=gifs_suffix,
            )
        elif res["backfill_complete"]:
            result = i18n.t(
                "chat.refeed.result_complete",
                locale,
                saved=res["saved"],
                gifs=gifs_suffix,
            )
        else:
            result = i18n.t(
                "chat.refeed.result_partial",
                locale,
                saved=res["saved"],
                gifs=gifs_suffix,
                limit=f"{REFEED_MAX_MESSAGES:,}",
            )
        await interaction.followup.send(result)

    @app_commands.command(
        name="refeed_channels",
        description="Importa mensajes de los canales elegidos para el corpus a la memoria del bot.",
    )
    async def refeed_channels(self, interaction: discord.Interaction):
        locale = await i18n.guild_locale(
            interaction.guild.id if interaction.guild else None
        )
        if not interaction.guild:
            await interaction.response.send_message(
                i18n.t("general.guild_only", locale), ephemeral=True
            )
            return

        if not has_admin_permission(interaction):
            await interaction.response.send_message(
                i18n.t("general.error.no_permission", locale), ephemeral=True
            )
            return

        existing = _refeed_running.get(interaction.guild.id)
        if existing and not existing.done():
            await interaction.response.send_message(
                i18n.t("chat.refeed_channels.already_running", locale),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            i18n.t("chat.refeed_channels.starting", locale)
        )
        progress_msg = await interaction.original_response()
        # Refetch como Message normal: la edición vía interaction muere a los 15 min con el token.
        if interaction.channel is not None:
            try:
                progress_msg = await interaction.channel.fetch_message(progress_msg.id)
            except Exception:
                log.debug(
                    "refeed_channels: no se pudo refetchear el mensaje de progreso",
                    exc_info=True,
                )

        started = self.start_refeed_channels(
            interaction.guild, progress_msg, interaction.channel
        )
        if not started:
            # El chequeo de _refeed_running de arriba no tiene await entre
            # medio y una escritura, así que no es atómico con el registro
            # real (adentro de start_refeed_channels): dos invocaciones casi
            # simultáneas pueden pasar las DOS el chequeo de arriba y llegar
            # hasta acá, pero solo una gana el registro atómico -- la otra
            # no debe dejar el mensaje "Empezando..." como si su propia
            # corrida hubiera arrancado, cuando en realidad no hizo nada.
            try:
                await progress_msg.edit(
                    content=i18n.t("chat.refeed_channels.race_lost", locale)
                )
            except Exception:
                log.debug(
                    "refeed_channels: no se pudo editar el aviso de carrera perdida",
                    exc_info=True,
                )

    @app_commands.command(
        name="corpus_info",
        description="Muestra cuántos mensajes hay en el corpus del canal actual.",
    )
    async def corpus_info(self, interaction: discord.Interaction):
        locale = await i18n.guild_locale(
            interaction.guild.id if interaction.guild else None
        )
        if not interaction.guild:
            await interaction.response.send_message(
                i18n.t("general.guild_only", locale), ephemeral=True
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message(
                i18n.t("chat.cannot_determine_channel", locale), ephemeral=True
            )
            return

        count = await count_corpus_messages(
            interaction.guild.id, interaction.channel.id
        )
        msg = i18n.t("chat.corpus_info.count", locale, count=count)
        if count < 50:
            msg += "\n" + i18n.t("chat.corpus_info.needs_more", locale)
        await interaction.response.send_message(msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
