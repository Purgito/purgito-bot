"""Núcleo de Purgito: limpieza de corpus, modelos Markov y generación de respuestas.

Este módulo concentra la "personalidad" del bot (post-proceso, frases especiales,
cadencia de generación). Cualquier cambio aquí afecta el tono en producción.
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import random
import re
import string
import time

import regex

import config
from db import (
    delete_user_data,
    get_corpus_messages,
    get_effective_frase_pool,
    get_random_frase_especial,
    get_user_messages,
    is_frase_allowed,
    is_user_excluded_from_learning,
    trim_corpus_if_needed,
    trim_guild_total_if_needed,
    trim_user_corpus_if_needed,
)
from i18n import t
from markov_engine import SimpleMarkov
from utils import LRUDict

log = logging.getLogger(__name__)

# Conectores comunes para recortar finales de frases incompletas.
_CONECTORES_FINALES = [
    " y",
    " o",
    " con",
    " pero",
    " de",
    " para",
    " a",
    " que",
    " entonces",
    " como",
]

_markov_cache: LRUDict = LRUDict(128)
_message_counter: LRUDict = LRUDict(256)
# "Termostato" de actividad reciente por canal (Fase 6): (score, last_update)
# en vez de una lista de timestamps -- un float que decae con el tiempo en
# memoria, no algo que necesite sobrevivir un reinicio ni que valga la pena
# escribir en SQLite en cada mensaje (el bot ya tiene un _db_lock global
# serializando escrituras; sumarle un write por mensaje solo para contar
# actividad lo saturaría). Ver _bump_channel_activity/_activity_multiplier.
_channel_activity: LRUDict = LRUDict(1024)
_ACTIVITY_HALF_LIFE = 45.0
# ponytail: valores de partida sin datos reales de producción para calibrar
# -- ajustar mirando cuánto sube auto_generate_probability en un canal
# activo típico antes de subir esto a config/settings.
_ACTIVITY_PER_BOOST = 5.0
_ACTIVITY_BOOST_CAP = 2.0
_corpus_insert_counter: LRUDict = LRUDict(256)
_guild_total_insert_counter: LRUDict = LRUDict(256)
# 10x el umbral por canal (50): trim_guild_total_if_needed hace un GROUP BY
# sobre todos los canales del guild, más caro que el COUNT de un solo canal
# — se dispara con menos frecuencia porque es una red de seguridad, no el
# mecanismo principal (ese es trim_corpus_if_needed, por canal).
_GUILD_TOTAL_TRIM_EVERY = 500
_user_markov_cache: LRUDict = LRUDict(128)
_user_corpus_insert_counter: LRUDict = LRUDict(256)
_special_phrase_cooldowns: LRUDict = LRUDict(256)

# Aviso de "todavía no tengo mensajes" al mencionar al bot: la versión completa
# (con instrucciones) sale a lo sumo una vez cada 15 min por guild.
_EMPTY_REPLY_COOLDOWN = 15 * 60
_empty_reply_cooldowns: LRUDict = LRUDict(256)
_EMPTY_FRASE_COOLDOWN = 15 * 60
_empty_frase_cooldowns: LRUDict = LRUDict(256)

_EMOJI_RE = regex.compile(
    r"[\p{Extended_Pictographic}\p{Emoji_Component}]+", regex.UNICODE
)

# Referencias a tasks fire-and-forget: sin esto el GC puede cancelar un trim en curso.
_bg_tasks: set = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


_ANSI_ESCAPE_RE = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")
_ANSI_BRACKET_RE = re.compile(r"\]\d*;[^\]]*")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DISCORD_MENTIONS_RE = re.compile(r"<a?:\w+:\d+>|<@!?\d+>|<#\d+>|<@&\d+>")


# Postproceso para recortar muletillas y finales raros.
def post_process_reply(text: str) -> str:
    if not text:
        return "no pude generar una respuesta, intenta de nuevo"

    # Limpieza básica
    text = text.lower().strip()
    text = _EMOJI_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)

    # Filtro de conectores finales
    changed = True
    while changed:
        changed = False
        for con in _CONECTORES_FINALES:
            if text.endswith(con):
                text = text[: -len(con)].strip()
                changed = True

    if text.endswith("."):
        text = text.rstrip(".")

    if not text.strip():
        text = "no tengo respuesta para eso"

    return text.strip()


def clean_for_corpus(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None

    # Eliminar secuencias ANSI y basura típica de logs
    t = _ANSI_ESCAPE_RE.sub(" ", t)
    t = _ANSI_BRACKET_RE.sub(" ", t)
    t = t.replace("[0m", " ").replace("][", " ")

    # Eliminar URLs y menciones Discord
    t = _URL_RE.sub(" ", t)
    t = _DISCORD_MENTIONS_RE.sub(" ", t)
    t = re.sub(r"\b\d{5,}\b", "", t)

    # Eliminar líneas que sean solo números/símbolos/caracteres especiales
    kept_lines: list[str] = []
    for line in t.splitlines():
        s = line.strip()
        if not s:
            continue
        if not any(ch.isalpha() for ch in s):
            continue
        kept_lines.append(s)

    t = " ".join(kept_lines)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    return t


_PUNCT_STRIP = string.punctuation + "¿¡«»“”‘’…"


def tokenize_message(text: str) -> list[str]:
    """Tokeniza un mensaje para el motor Markov separando signos de puntuación periféricos
    y descartando puntuación flotante aislada o markdown residual."""
    if not text:
        return []
    raw_tokens = text.split()
    tokens: list[str] = []
    for raw in raw_tokens:
        tok = raw.strip(_PUNCT_STRIP).lower()
        if tok:
            tokens.append(tok)
    return tokens


def note_corpus_insert(guild_id: int, channel_id: int) -> None:
    key = (guild_id, channel_id)
    n = _corpus_insert_counter.get(key, 0) + 1
    if n >= 50:
        _corpus_insert_counter[key] = 0
        _markov_cache.pop(guild_id, None)
        _spawn(trim_corpus_if_needed(guild_id, channel_id))
    else:
        _corpus_insert_counter[key] = n

    gn = _guild_total_insert_counter.get(guild_id, 0) + 1
    if gn >= _GUILD_TOTAL_TRIM_EVERY:
        _guild_total_insert_counter[guild_id] = 0
        _spawn(trim_guild_total_if_needed(guild_id))
    else:
        _guild_total_insert_counter[guild_id] = gn


def note_user_corpus_insert(guild_id: int, author_id: int) -> None:
    key = (guild_id, author_id)
    n = _user_corpus_insert_counter.get(key, 0) + 1
    if n >= 50:
        _user_corpus_insert_counter[key] = 0
        _user_markov_cache.pop(key, None)
        _spawn(trim_user_corpus_if_needed(guild_id, author_id))
    else:
        _user_corpus_insert_counter[key] = n


def _channel_activity_score(guild_id: int, channel_id: int) -> float:
    """Score de actividad del canal decayendo hasta ahora, SIN sumarle un
    mensaje nuevo -- lo que había antes de este mensaje, no con él incluido."""
    key = (guild_id, channel_id)
    now = time.monotonic()
    score, last = _channel_activity.get(key, (0.0, now))
    return score * (0.5 ** ((now - last) / _ACTIVITY_HALF_LIFE))


def _bump_channel_activity(guild_id: int, channel_id: int) -> float:
    """Suma este mensaje al termostato del canal (para las próximas
    consultas) y devuelve el score resultante. Decae exponencialmente con
    el tiempo transcurrido (vida media _ACTIVITY_HALF_LIFE) en vez de
    contarse con una ventana de timestamps -- así es un solo float por
    canal sin importar cuántos mensajes pasen, no una lista que crece."""
    new_score = _channel_activity_score(guild_id, channel_id) + 1.0
    _channel_activity[(guild_id, channel_id)] = (new_score, time.monotonic())
    return new_score


def _activity_multiplier(score: float) -> float:
    """1.0 sin actividad reciente (ninguna diferencia con el timer fijo de
    siempre); sube con el score hasta _ACTIVITY_BOOST_CAP."""
    return min(_ACTIVITY_BOOST_CAP, 1.0 + score / _ACTIVITY_PER_BOOST)


_MAX_CONCURRENT_MARKOV_TASKS = 4


class MarkovConcurrencyLimiter:
    """Límite global de concurrencia para generación y entrenamiento Markov (S8).

    Protege el ThreadPoolExecutor global compartido contra saturación por
    múltiples guilds/canales intentando generar o entrenar modelos en paralelo.

    - slot(wait=False): Adquiere un slot de forma no bloqueante y atómica. Si no
      hay slots libres, yield False de inmediato. Usado por la generación espontánea
      para descartar la oportunidad de inmediato sin encolar trabajo en el executor.
    - slot(wait=True): Adquisición asíncrona estándar (espera slot). Usado por
      comandos explícitos del usuario (/generar, /imitar, menciones, playground)
      donde el usuario espera activamente una respuesta.
    """

    def __init__(self, max_concurrent: int = _MAX_CONCURRENT_MARKOV_TASKS):
        self.max_concurrent = max_concurrent
        self._sem: asyncio.Semaphore | None = None

    def _get_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.max_concurrent)
        return self._sem

    def try_acquire(self) -> bool:
        sem = self._get_sem()
        if sem.locked():
            return False
        # En el bucle de eventos single-threaded de asyncio, decrementar _value
        # de forma síncrona cuando not locked() es atómico y sin carreras.
        sem._value -= 1
        return True

    async def acquire(self) -> None:
        sem = self._get_sem()
        await sem.acquire()

    def release(self) -> None:
        sem = self._get_sem()
        sem.release()

    @asynccontextmanager
    async def slot(self, *, wait: bool = False):
        if not wait:
            if not self.try_acquire():
                yield False
                return
        else:
            await self.acquire()
        try:
            yield True
        finally:
            self.release()


markov_limiter = MarkovConcurrencyLimiter()


def note_message_for_auto_generate(
    guild_id: int,
    channel_id: int,
    every: int | None = None,
    probability: float | None = None,
) -> bool:
    """Cuenta un insert al corpus del canal y decide si el bot habla espontáneamente.

    Cada `every` inserts hay una oportunidad de generación, gateada por
    `probability` para que no sea determinística por conteo -- el "timer
    fijo" de siempre. Encima de eso, la probabilidad efectiva de esa
    oportunidad sube con qué tan activo estuvo el canal ANTES de este
    mensaje (ver _channel_activity_score/_activity_multiplier): una racha
    de mensajes hace que el bot intervenga con más ganas, no solo cuando el
    contador fijo se cumple. Un canal recién creado (sin historial de
    actividad todavía) arranca en multiplicador 1.0 -- ningún cambio de
    conducta hasta que de verdad haya actividad que medir.

    Si el admin configuró explícitamente probability >= 1.0 (100%), la probabilidad
    es 1.0 exacta. Para valores menores a 1.0, el boost por actividad está topeado en 0.95
    para mantener margen de sorpresa en uso casual.

    `every`/`probability` son por servidor y los pasa cogs/chat.py desde
    get_effective_chat_settings; los de config.py quedaron solo como
    fallback para quien no los pase.
    """
    if every is None:
        every = config.AUTO_GENERATE_EVERY
    if probability is None:
        probability = config.AUTO_GENERATE_PROBABILITY
    activity_before = _channel_activity_score(guild_id, channel_id)
    _bump_channel_activity(guild_id, channel_id)
    key = (guild_id, channel_id)
    n = _message_counter.get(key, 0) + 1
    # `every` viene de la DB acotado a >= 1, pero un 0 acá dejaría el contador
    # sin avanzar nunca y el bot mudo: se trata igual que 1.
    if n >= max(1, every):
        _message_counter[key] = 0
        if probability >= 1.0:
            return True
        boosted = min(0.95, probability * _activity_multiplier(activity_before))
        return random.random() < boosted
    _message_counter[key] = n
    return False


def reset_guild_caches(guild_id: int) -> None:
    """Limpia todos los caches en memoria de un guild (tras corpus_wipe)."""
    _markov_cache.pop(guild_id, None)
    _special_phrase_cooldowns.pop(guild_id, None)
    _empty_frase_cooldowns.pop(guild_id, None)
    _empty_reply_cooldowns.pop(guild_id, None)
    for cache in (
        _corpus_insert_counter,
        _message_counter,
        _channel_activity,
        _user_corpus_insert_counter,
        _user_markov_cache,
    ):
        for key in [k for k in cache.keys() if k[0] == guild_id]:
            cache.pop(key, None)


async def forget_user(author_id: int) -> dict:
    """Núcleo del Right to be Forgotten individual, ya con invalidación de
    cachés -- el borrado de SQLite en sí vive en db.delete_user_data (db.py
    no puede importar este módulo, generation.py ya importa de db, sería un
    ciclo). Esta es la función pensada como punto único que un futuro
    comando de Discord (/borrar_mis_datos) y un futuro endpoint del
    dashboard/API deberían llamar -- ninguno de los dos existe todavía.

    Invalida reset_guild_caches() para TODOS los guilds que devuelva
    db.delete_user_data(), incluso si el autor solo tenía filas UNKNOWN: el
    modelo Markov cacheado de ese guild se armó en algún momento con ese
    corpus, borrado o no de forma trazable, así que sigue habiendo que
    tirarlo.

    No valida permisos ni identidad -- exactamente igual que
    db.delete_user_data, confía en que el llamador ya resolvió que
    `author_id` es la persona autenticada que pide su propio borrado.
    """
    report = await delete_user_data(author_id)
    for guild_id in report["guild_ids"]:
        reset_guild_caches(guild_id)
    return report


async def build_markov_model(guild_id: int) -> SimpleMarkov | None:
    cached = _markov_cache.get(guild_id)
    if cached is not None:
        return cached

    corpus = await get_corpus_messages(guild_id, limit=config.MARKOV_TRAINING_MESSAGES)
    if len(corpus) < 50:
        return None

    def build() -> SimpleMarkov:
        m = SimpleMarkov()
        for msg in corpus:
            tokens = tokenize_message(msg)
            if tokens:
                m.add(tokens)
        return m

    try:
        model = await asyncio.to_thread(build)
    except Exception:
        log.exception("Error construyendo modelo Markov para guild %s", guild_id)
        return None

    _markov_cache[guild_id] = model
    return model


async def generate_markov_reply(guild_id: int, *, wait: bool = True) -> str | None:
    async with markov_limiter.slot(wait=wait) as acquired:
        if not acquired:
            log.debug(
                "Generación Markov descartada por saturación global (guild %s)",
                guild_id,
            )
            return None
        model = await build_markov_model(guild_id)
        if not model or model.is_empty:
            return None

        try:
            sentence = await asyncio.to_thread(
                model.generate,
                max_words=20,
                max_attempts=5,
                min_words=1,
            )
        except Exception:
            log.exception("Error generando frase Markov para guild %s", guild_id)
            sentence = None

        return sentence


async def generate_markov_word(guild_id: int, *, wait: bool = True) -> str | None:
    """Una sola palabra del modelo Markov del guild -- para el tag
    {{markov.word}} de las frases especiales (ver render_frase_template en
    cogs/chat.py). Mismo modelo cacheado que generate_markov_reply."""
    async with markov_limiter.slot(wait=wait) as acquired:
        if not acquired:
            return None
        model = await build_markov_model(guild_id)
        if not model or model.is_empty:
            return None
        try:
            word = await asyncio.to_thread(
                model.generate, max_words=1, max_attempts=5, min_words=1
            )
        except Exception:
            log.exception("Error generando palabra Markov para guild %s", guild_id)
            word = None
        return word


async def generate_markov_for_user(
    guild_id: int, author_id: int, *, wait: bool = True
) -> str | None:
    if await is_user_excluded_from_learning(guild_id, author_id):
        return None
    async with markov_limiter.slot(wait=wait) as acquired:
        if not acquired:
            return None
        key = (guild_id, author_id)
        model = _user_markov_cache.get(key)
        if model is None:
            corpus = await get_user_messages(
                guild_id, author_id, limit=config.USER_MARKOV_TRAINING_MESSAGES
            )
            if len(corpus) < 30:
                return None

            def build() -> SimpleMarkov:
                m = SimpleMarkov()
                for msg in corpus:
                    tokens = tokenize_message(msg)
                    if tokens:
                        m.add(tokens)
                return m

            try:
                model = await asyncio.to_thread(build)
            except Exception:
                log.exception(
                    "Error construyendo modelo Markov para usuario %s", author_id
                )
                return None
            _user_markov_cache[key] = model

        try:
            sentence = await asyncio.to_thread(
                model.generate,
                max_words=20,
                max_attempts=5,
                min_words=1,
            )
        except Exception:
            log.exception("Error generando frase Markov para usuario %s", author_id)
            sentence = None
        return sentence


class GenerationResult(tuple):
    """Resultado de generate_response. Subclase de tuple de 2 elementos
    (texto, es_especial) para compatibilidad total hacia atrás con desempaquetado
    `text, is_special = await generate_response(...)`.

    Expone además `.reason`:
    - None: éxito (frase generada o Markov generado) o Markov sin corpus (special_phrase_probability < 1.0)
    - "no_phrases": 100% frase requerida, pero no hay frases disponibles en el pool
    - "channel_not_allowed": 100% frase requerida, pero el canal no está en la whitelist de frases
    - "cooldown": 100% frase requerida, pero el cooldown de frases especiales está activo
    """

    def __new__(
        cls,
        text: str | None,
        is_special: bool,
        reason: str | None = None,
    ):
        instance = super().__new__(cls, (text, is_special))
        instance._reason = reason
        return instance

    @property
    def text(self) -> str | None:
        return self[0]

    @property
    def is_special(self) -> bool:
        return self[1]

    @property
    def reason(self) -> str | None:
        return self._reason


def empty_corpus_reply(guild_id: int, locale: str, throttle: bool = False) -> str:
    """Mensaje amigable cuando el bot aún no tiene mensajes suficientes para generar.

    Con throttle=False (/generar, pedido explícito) siempre devuelve la versión
    completa con instrucciones. Con throttle=True (menciones/replies) la versión
    completa sale a lo sumo una vez por guild cada _EMPTY_REPLY_COOLDOWN; dentro
    del cooldown se responde una versión corta para no repetir el sermón.
    """
    if throttle:
        now = time.monotonic()
        last = _empty_reply_cooldowns.get(guild_id)
        if last is not None and now - last < _EMPTY_REPLY_COOLDOWN:
            return t("chat.empty_reply.short", locale)
        _empty_reply_cooldowns[guild_id] = now
    return t("chat.empty_reply.full", locale)


def empty_frase_reply(
    guild_id: int,
    reason: str,
    locale: str,
    *,
    throttle: bool = False,
    url: str = "",
) -> str | None:
    """Mensaje amigable cuando frase_probability=100% pero no se pudo usar una frase.

    Con throttle=False (/generar, comando explícito) siempre devuelve el mensaje explicativo.
    Con throttle=True (menciones/mensajes) sale a lo sumo una vez por guild cada
    _EMPTY_FRASE_COOLDOWN; dentro del cooldown retorna None para guardar silencio y no spamear.
    """
    if throttle:
        now = time.monotonic()
        last = _empty_frase_cooldowns.get(guild_id)
        if last is not None and now - last < _EMPTY_FRASE_COOLDOWN:
            return None
        _empty_frase_cooldowns[guild_id] = now

    key = f"chat.frase_fallback.{reason}"
    return t(key, locale, url=url)


async def generate_response(
    guild_id: int,
    channel_id: int,
    *,
    special_phrase_probability: float = config.SPECIAL_PHRASE_PROBABILITY,
    wait: bool = True,
) -> GenerationResult:
    """Decide entre frase especial o Markov. Retorna GenerationResult(texto, es_especial).
    es_especial=True indica que el texto no debe pasar por post_process_reply.

    Cuando special_phrase_probability >= 1.0 (100%), el uso de frase propia es OBLIGATORIO:
    si la frase no está disponible (sin frases, canal no permitido o en cooldown),
    NO cae a Markov y retorna GenerationResult(None, True, reason=...), permitiendo
    al llamador explicar la causa y evitar el fallback silencioso.

    Para probabilidades menores (0.0 <= p < 1.0), si la frase no está disponible
    continúa normalmente con la generación Markov.

    `special_phrase_probability` la resuelve el llamador vía
    get_effective_chat_settings (channel_settings.frase_probability puede
    overridearla por canal, ver Fase 2) -- generation.py no lee la config del
    chat directo, igual que note_message_for_auto_generate recibe `every`/
    `probability` en vez de leerlos de settings él mismo. El default de la
    firma solo cubre a /imitar y otros llamadores que todavía no la resuelven.
    `wait=False` descarta inmediatamente si el semáforo Markov global está ocupado.
    """
    if special_phrase_probability >= 1.0:
        if not await is_frase_allowed(guild_id, channel_id):
            return GenerationResult(None, True, reason="channel_not_allowed")

        pack_id = await get_effective_frase_pool(guild_id, channel_id)
        phrase = await get_random_frase_especial(guild_id, pack_id)
        if phrase is None:
            return GenerationResult(None, True, reason="no_phrases")

        now = time.monotonic()
        cooldown_ok = (
            now - _special_phrase_cooldowns.get(guild_id, -float("inf"))
            >= config.SPECIAL_PHRASE_COOLDOWN
        )
        if not cooldown_ok:
            return GenerationResult(None, True, reason="cooldown")

        _special_phrase_cooldowns[guild_id] = now
        return GenerationResult(phrase, True)

    now = time.monotonic()
    cooldown_ok = (
        now - _special_phrase_cooldowns.get(guild_id, -float("inf"))
        >= config.SPECIAL_PHRASE_COOLDOWN
    )
    if (
        cooldown_ok
        and random.random() < special_phrase_probability
        and await is_frase_allowed(guild_id, channel_id)
    ):
        pack_id = await get_effective_frase_pool(guild_id, channel_id)
        phrase = await get_random_frase_especial(guild_id, pack_id)
        if phrase:
            _special_phrase_cooldowns[guild_id] = now
            return GenerationResult(phrase, True)
    try:
        reply = await generate_markov_reply(guild_id, wait=wait)
    except TypeError:
        reply = await generate_markov_reply(guild_id)
    return GenerationResult(reply, False)
