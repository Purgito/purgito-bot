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
    if random.random() < probability and await is_frase_allowed(guild_id, channel_id):
        pack_id = await get_effective_frase_pool(guild_id, channel_id)
        phrase = await get_random_frase_especial(guild_id, pack_id)
        if phrase is not None:
            return phrase, True
    text = await generation.generate_markov_reply(guild_id)
    return text, False


async def simulate_message(
    guild_id: int, channel_id: int, content: str, *, author, channel, guild
) -> dict:
    """Corre la lógica de decisión de on_message contra un mensaje de
    prueba -- sin mandar nada a Discord, sin guardar nada al corpus, sin
    bumpear contadores ni gastar cooldowns reales. Usado por el endpoint
    del playground del dashboard.

    Ojo con el alcance: simula el MOTOR de generación (triggers y la
    decisión frase-vs-Markov) con la config efectiva del canal -- no
    reproduce si ese canal está en las allowlists de mención/espontáneo ni
    el límite de menciones por hora, porque esas dependen de CÓMO llegaría
    el mensaje (¿mención? ¿espontáneo?), algo que el playground no pide.
    Lo único que sí replica sin ambigüedad es el mute total de un canal
    ignorado.
    """
    settings = await get_effective_chat_settings(guild_id, channel_id)
    if await is_channel_ignored(guild_id, channel_id):
        return {"would_respond": False, "reason": "canal_ignorado", "text": None}

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
            }

    text, is_special = await _simulate_special_or_markov(
        guild_id, channel_id, settings["frase_probability"]
    )
    if text is None:
        return {"would_respond": False, "reason": "sin_corpus_suficiente", "text": None}
    final = (
        await render_frase_template(text, author=author, channel=channel, guild=guild)
        if is_special
        else generation.post_process_reply(text)
    )
    return {
        "would_respond": True,
        "reason": "frase_especial" if is_special else "markov",
        "text": final,
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
        """True si el autor tiene algún rol exento del tope de menciones.

        `message.author.roles` ya viene cacheado con el miembro: no hay llamada
        extra a la API. En un DM el autor es User y no tiene roles.
        """
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
                            await message.channel.send(chunk)
                        await bump_counter(message.guild.id, "mensajes_enviados")
                except Exception:
                    log.exception("Error en generación automática de respuesta")
            return

        if not message.guild:
            return

        # Pasado el tope de la hora, esta mención no existe: ni respuesta, ni
        # aviso de límite. Va antes de todo lo que manda mensajes —incluido
        # _muted_reply— para que el propio aviso no se vuelva el spam.
        # Los roles exentos (moderación, boosters…) se saltan el tope entero.
        if not await self._exempt_from_rate_limit(message):
            if not _consume_interaction(
                message.guild.id, message.author.id, settings["mention_rate_limit"]
            ):
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

        text, is_special = await generation.generate_response(
            message.guild.id,
            message.channel.id,
            special_phrase_probability=settings["frase_probability"],
        )
        if text is None:
            # Servidor sin historial suficiente: explicar en vez de contestar "...".
            # throttle=True: las instrucciones completas salen 1 vez cada 15 min por guild.
            locale = await i18n.guild_locale(message.guild.id)
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
            await message.reply(chunk)
        await bump_counter(message.guild.id, "mensajes_enviados")

    async def _send_trigger_reply(self, message: discord.Message, text: str) -> None:
        for chunk in chunk_message(text):
            await message.channel.send(chunk)
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
            await report_channel.send(
                f"👀 Ya pude leer {after.mention}: {res['saved']:,} mensajes nuevos guardados."
            )
        except Exception:
            log.debug("on_guild_channel_update: no se pudo avisar en %s", channel_id)

    # --- COMANDOS ---

    @app_commands.command(
        name="generar",
        description="Genera un mensaje usando la memoria del canal.",
    )
    async def generar(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "Solo en servidores.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        if interaction.channel is None:
            await interaction.followup.send(
                "No puedo determinar el canal.", ephemeral=True
            )
            return
        settings = await get_effective_chat_settings(
            interaction.guild.id, interaction.channel.id
        )
        text, is_special = await generation.generate_response(
            interaction.guild.id,
            interaction.channel.id,
            special_phrase_probability=settings["frase_probability"],
        )
        if text is None:
            # Comando explícito: siempre el mensaje completo con instrucciones.
            locale = await i18n.guild_locale(interaction.guild.id)
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
        await interaction.followup.send(reply)

    @app_commands.command(
        name="imitar",
        description="Genera un mensaje imitando el estilo de un usuario del servidor.",
    )
    @app_commands.describe(usuario="Usuario a imitar")
    async def imitar(self, interaction: discord.Interaction, usuario: discord.Member):
        if not interaction.guild:
            await interaction.response.send_message(
                "Solo en servidores.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        count = await count_user_messages(interaction.guild.id, usuario.id)
        if count < 30:
            await interaction.followup.send(
                f"⚠️ **{usuario.display_name}** solo tiene {count} mensaje(s) guardados. Necesita al menos 30."
            )
            return

        result = await generation.generate_markov_for_user(
            interaction.guild.id, usuario.id
        )
        if result is None:
            await interaction.followup.send(
                f"⚠️ No se pudo generar un mensaje para **{usuario.display_name}**. Prueba más tarde."
            )
            return

        await interaction.followup.send(
            f'🎭 **{usuario.display_name}** diría: "{result}"'
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
        if not interaction.guild:
            await interaction.response.send_message(
                "Solo en servidores.", ephemeral=True
            )
            return

        if not has_admin_permission(interaction):
            await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send("No puedo leer el historial de este canal.")
            return

        if await is_channel_ignored(interaction.guild.id, channel.id):
            await interaction.followup.send(
                "⚠️ Este canal está en la lista de ignorados. Quítalo primero desde `/settings` si quieres incluirlo."
            )
            return

        if not await is_corpus_allowed(interaction.guild.id, channel.id):
            await interaction.followup.send(
                "⚠️ Este canal no está entre los elegidos para aprender. "
                "Agrégalo desde el dashboard (tab CHAT > Canales) y vuelve a intentar."
            )
            return

        res = await self._refeed_channel(
            interaction.guild.id, channel, REFEED_MAX_MESSAGES
        )

        if res["forbidden"] and res["saved"] == 0:
            await interaction.followup.send(
                "❌ Sin permisos para leer el historial de este canal."
            )
            return
        gifs_suffix = (
            f" y {res['gifs_saved']} GIF(s) nuevo(s)" if res["gifs_saved"] else ""
        )
        if res["was_incremental"]:
            result = f"⏭️ Este canal ya estaba al día: {res['saved']} mensajes nuevos guardados{gifs_suffix}."
        elif res["backfill_complete"]:
            result = f"✅ Historial completo leído: {res['saved']} mensajes guardados{gifs_suffix}."
        else:
            result = (
                f"✅ Guardados {res['saved']} mensajes{gifs_suffix} (leyendo el historial por primera vez).\n"
                f"⚠️ Límite de {REFEED_MAX_MESSAGES:,} mensajes alcanzado; ejecuta `/refeed` de nuevo para continuar donde quedó."
            )
        await interaction.followup.send(result)

    @app_commands.command(
        name="refeed_channels",
        description="Importa mensajes de los canales elegidos para el corpus a la memoria del bot.",
    )
    async def refeed_channels(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "Solo en servidores.", ephemeral=True
            )
            return

        if not has_admin_permission(interaction):
            await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )
            return

        existing = _refeed_running.get(interaction.guild.id)
        if existing and not existing.done():
            await interaction.response.send_message(
                "⏳ Ya hay una importación en curso en este servidor; espera a que termine.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "🔄 Empezando a leer el historial de los canales…"
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

        self.start_refeed_channels(interaction.guild, progress_msg, interaction.channel)

    @app_commands.command(
        name="corpus_info",
        description="Muestra cuántos mensajes hay en el corpus del canal actual.",
    )
    async def corpus_info(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "Solo en servidores.", ephemeral=True
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message(
                "No puedo determinar el canal.", ephemeral=True
            )
            return

        count = await count_corpus_messages(
            interaction.guild.id, interaction.channel.id
        )
        msg = f"📊 El corpus de este canal tiene {count} mensajes."
        if count < 50:
            msg += "\n⚠️ Necesita al menos 50 mensajes para generar bien."
        await interaction.response.send_message(msg)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Chat(bot))
