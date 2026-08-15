import os
import re
import json
import string
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

import aiosqlite
import regex

import config
import r2

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "bot.db")

log = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


# Caracteres de control C0/C1 (salvo \n y \t, que son texto legítimo) y los
# controles de dirección explícita de Unicode. Los primeros incluyen el NUL,
# que Discord rechaza al enviar -- una frase con un \x00 pegado se guardaba
# bien y después no se podía postear nunca. Los segundos (RLO/LRO/isolates)
# reordenan visualmente el resto de la línea: un nombre de pack con un U+202E
# le da vuelta el renglón entero en la lista del dashboard y en el registro de
# auditoría que ve otro admin. El texto RTL de verdad (árabe, hebreo) no los
# necesita -- el algoritmo bidi de Unicode ya lo resuelve por su cuenta --, así
# que sacarlos no rompe ningún idioma.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")


def clean_admin_text(text: str | None) -> str:
    """Normaliza un texto escrito por un admin antes de guardarlo."""
    return _CONTROL_CHARS_RE.sub("", text or "").strip()


class _RollbackOnErrorLock(asyncio.Lock):
    """asyncio.Lock, pero si el bloque `async with` termina por una
    excepción, hace ROLLBACK de la transacción de SQLite antes de soltar
    el lock.

    Cada función de escritura de este módulo hace `async with _db_lock:
    ...varios execute()... await db.commit()`. Sin esto: si algo entre el
    primer execute() y el commit() tira una excepción (el disparador real
    es disco lleno a mitad de un INSERT/UPDATE, que SQLite reporta como
    OperationalError), `async with` libera el lock igual -- así funciona
    cualquier context manager -- pero la transacción queda ABIERTA y sin
    confirmar en `_db`, la única conexión compartida por todo el proceso.
    El próximo caller que tome el lock seguiría escribiendo sobre ESA
    misma transacción pendiente, y su propio commit() -- pensado para
    confirmar solo sus cambios -- terminaría confirmando también los
    restos a medio aplicar de la operación que falló antes, sin que nadie
    se entere.

    Central a propósito: cambiar el tipo de _db_lock alcanza para cubrir
    las ~90 funciones que ya hacen `async with _db_lock:` tal cual están,
    sin tocar cada una.
    """

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None and _db is not None:
            try:
                await _db.rollback()
            except Exception:
                log.exception(
                    "Fallo haciendo rollback de _db tras una excepción bajo _db_lock"
                )
        await super().__aexit__(exc_type, exc, tb)


_db_lock: asyncio.Lock = _RollbackOnErrorLock()

# Interacciones con el bot por hora y por usuario, por servidor. Es anti-abuso,
# no un beneficio premium: mismo default para Free y Premium. 0 = sin límite.
DEFAULT_MENTION_RATE_LIMIT = 10
MAX_MENTION_RATE_LIMIT = 1000

# Comportamiento del chat, ahora por servidor (antes eran constantes globales en
# config.py). Los defaults replican exactamente lo que hacía el bot con los
# valores fijos, así que migrar no cambia la conducta de ningún servidor.
DEFAULT_AUTO_GENERATE_EVERY = 15
DEFAULT_AUTO_GENERATE_PROBABILITY = 0.6
DEFAULT_REACTION_PROBABILITY = 0.05
DEFAULT_GIF_RESPONSE_PROBABILITY = 0.45
# Iba fijo en config.SPECIAL_PHRASE_PROBABILITY; ahora es un tunable más
# (overrideable por canal como los de arriba, ver channel_settings), pero el
# default replica ese mismo 5% para no cambiarle la conducta a nadie.
DEFAULT_FRASE_PROBABILITY = 0.05
# Techo del contador de mensajes: más alto que esto y el bot no hablaría nunca.
MAX_AUTO_GENERATE_EVERY = 1000


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, "") or default)
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default


def _limit_for_guild(
    guild_id: int | None,
    free_name: str,
    premium_name: str,
    free_default: int,
    premium_default: int,
) -> int:
    """Límite de almacenamiento aplicable a un guild según si es premium o no."""
    from cogs.premium import (
        is_premium_guild,
    )  # import diferido: evita import circular (premium.py importa de db)

    if is_premium_guild(guild_id):
        return _env_int(premium_name, premium_default)
    return _env_int(free_name, free_default)


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Base de datos no inicializada. Llama a init_db() primero.")
    return _db


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER PRIMARY KEY,
    chat_mode_enabled INTEGER NOT NULL DEFAULT 1,
    chat_channel_id INTEGER,
    mention_rate_limit INTEGER NOT NULL DEFAULT 10
);

CREATE TABLE IF NOT EXISTS corpus_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_corpus_messages_guild ON corpus_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_corpus_messages_guild_channel ON corpus_messages(guild_id, channel_id);

CREATE TABLE IF NOT EXISTS corpus_gifs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    media_url TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_health_check TEXT,
    checked_at TEXT,
    dead_streak INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    UNIQUE(guild_id, url)
);

-- Un registro por objeto físico en R2, compartido entre todos los servidores
-- que tengan ese mismo archivo. ref_count = cuántas filas de corpus_gifs lo
-- referencian; cuando llega a 0 el objeto se borra del bucket.
-- Los GIFs de tenor/giphy no pasan por acá (no ocupan storage propio).
CREATE TABLE IF NOT EXISTS gif_objects (
    content_hash TEXT PRIMARY KEY,
    r2_key TEXT NOT NULL,
    ref_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    phash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Veto permanente por guild: un GIF bloqueado se borra ahora (ver block_gif)
-- y save_gif_url lo rechaza para siempre en ESE guild, aunque se vuelva a
-- compartir. content_hash cubre la mayoría (GIFs que pasaron por R2); url es
-- el único identificador para tenor/giphy (no ocupan storage propio) o algún
-- legacy que quedara sin hash -- no se exige ambos, ver is_gif_blocked.
CREATE TABLE IF NOT EXISTS gif_blocklist (
    guild_id INTEGER NOT NULL,
    content_hash TEXT,
    url TEXT,
    blocked_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, content_hash, url)
);

CREATE TABLE IF NOT EXISTS youtube_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    youtube_channel_id TEXT NOT NULL,
    youtube_channel_name TEXT NOT NULL,
    last_video_id TEXT,
    discord_channel_id INTEGER NOT NULL,
    mention_role_id INTEGER,
    last_error TEXT,
    UNIQUE(guild_id, youtube_channel_id)
);

CREATE TABLE IF NOT EXISTS user_corpus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    message_id INTEGER,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_user_corpus_guild_author ON user_corpus(guild_id, author_id);

CREATE TABLE IF NOT EXISTS ignored_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS meme_schedule (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    interval_minutes INTEGER NOT NULL DEFAULT 180,
    last_posted_at TEXT,
    PRIMARY KEY (guild_id, channel_id)
);

-- Webhook propio del bot por canal, para mandar con nombre/avatar
-- personalizado (Fase 3 del editor de embeds/dashboard) sin perder los
-- botones interactivos -- el webhook lo crea Purgito (channel.create_webhook),
-- así que sigue perteneciendo a su aplicación. Ver src/webhook_identity.py.
CREATE TABLE IF NOT EXISTS channel_webhooks (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    webhook_id INTEGER NOT NULL,
    webhook_token TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS scheduled_announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    mode TEXT NOT NULL,
    interval_minutes INTEGER,
    hour INTEGER,
    minute INTEGER,
    last_sent_at TEXT,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    embed_json TEXT DEFAULT NULL,
    content_mode TEXT NOT NULL DEFAULT 'classic_embed',
    delete_after_seconds INTEGER
);
CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_guild ON scheduled_announcements(guild_id);

CREATE TABLE IF NOT EXISTS embed_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    embed_json TEXT NOT NULL,
    content_mode TEXT NOT NULL DEFAULT 'classic_embed',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_embed_templates_guild ON embed_templates(guild_id);

CREATE TABLE IF NOT EXISTS embed_uploaded_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, url)
);
CREATE INDEX IF NOT EXISTS idx_embed_uploaded_images_guild ON embed_uploaded_images(guild_id);

CREATE TABLE IF NOT EXISTS layout_button_actions (
    custom_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    action_data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_layout_button_actions_guild ON layout_button_actions(guild_id);

CREATE TABLE IF NOT EXISTS corpus_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, url)
);

CREATE TABLE IF NOT EXISTS frases_especiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    frase TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    -- pack_id INTEGER se suma por ALTER TABLE en init_db() (la tabla ya
    -- existe en producción). Ver el comentario grande junto a frase_packs
    -- de abajo para la semántica completa.
);
CREATE INDEX IF NOT EXISTS idx_frases_especiales_guild ON frases_especiales(guild_id);

-- Canales donde pueden salir frases especiales. A diferencia de
-- corpus_allowed_channels (que es al revés: vacía = no aprende de
-- ninguno, porque leer mensajes es invasivo), acá vacía = permitido en
-- cualquier canal -- mismo criterio "opt-out" que spontaneous_channels/
-- mention_channels: una frase especial no es más invasiva que cualquier
-- otra respuesta del bot, así que el default abierto es el seguro.
CREATE TABLE IF NOT EXISTS frase_allowed_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Agrupa frases especiales para poder darle a cada canal un pool distinto
-- (ver frase_pack_channels). UNIQUE(guild_id, name): dos packs del mismo
-- servidor no pueden confundirse por nombre en el dashboard.
--
-- Semántica de "sin pack" (frases_especiales.pack_id NULL y canales sin
-- fila en frase_pack_channels), decidida para no romper nada de lo que ya
-- existía antes de esta tabla:
--   - Todas las frases de un servidor que nunca tocó packs quedan con
--     pack_id NULL: son el "pool default" de ese servidor.
--   - Un canal SIN fila en frase_pack_channels usa ese pool default
--     (pack_id NULL) -- el comportamiento de siempre, sin excepciones.
--   - Un canal CON fila en frase_pack_channels usa EXCLUSIVAMENTE las
--     frases de ESE pack, no las mezcla con el pool default.
--   - Borrar un pack no borra sus frases ni deja canales sin pool: las
--     frases vuelven a pack_id NULL y los canales que lo tenían asignado
--     vuelven a usar el pool default (ver delete_frase_pack en db.py).
CREATE TABLE IF NOT EXISTS frase_packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, name)
);

-- Qué pack usa cada canal. PK (guild_id, channel_id): un canal usa a lo
-- sumo un pack a la vez (asignar uno nuevo reemplaza al anterior). Varios
-- canales SÍ pueden compartir el mismo pack_id -- "asignar un pack a
-- varios canales" es eso, varias filas con el mismo pack_id.
CREATE TABLE IF NOT EXISTS frase_pack_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    pack_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS reaction_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    emoji_text TEXT NOT NULL,
    is_custom INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, emoji_text)
);
CREATE INDEX IF NOT EXISTS idx_reaction_pool_guild ON reaction_pool(guild_id);

-- Vestigial: reemplazada por spontaneous_channels + mention_channels (init_db
-- copia sus filas a ambas la primera vez que corre esta versión). Nada la
-- lee ni la escribe ya — igual que settings.chat_channel_id, se deja para no
-- perder el dato de origen de esa migración.
CREATE TABLE IF NOT EXISTS chat_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Canales donde Purgito habla por su cuenta (participación espontánea).
-- Lista vacía = sin restricción, habla en cualquiera. Independiente de
-- mention_channels: un canal puede estar en una lista, en la otra, en
-- ambas o en ninguna.
CREATE TABLE IF NOT EXISTS spontaneous_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Canales donde Purgito responde si lo mencionan. Lista vacía = responde en
-- cualquiera. Ver spontaneous_channels: son dos conceptos independientes.
CREATE TABLE IF NOT EXISTS mention_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Override por canal de los tunables de settings (CHAT_TUNABLES). Mismo
-- criterio que las allowlists de arriba en cuanto a "vacío = permisivo":
-- acá NULL en una columna (o directamente la fila ausente) = usa el valor
-- de `settings` para ese servidor; un valor no-nulo lo pisa SOLO en ese
-- canal. Ver get_effective_chat_settings, la única función que debería
-- leer esto para tomar una decisión (cogs/chat.py no lee esta tabla directo).
CREATE TABLE IF NOT EXISTS channel_settings (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    auto_generate_every INTEGER,
    auto_generate_probability REAL,
    reaction_probability REAL,
    gif_response_probability REAL,
    mention_rate_limit INTEGER,
    PRIMARY KEY (guild_id, channel_id)
);

-- Reglas de auto-respuesta a mano por canal: si el contenido de un mensaje
-- matchea `pattern` según `match_type`, dispara `action` sin esperar
-- mención ni el roll de auto_generate_probability -- independiente de
-- spontaneous_channels/mention_channels, un canal puede tener triggers sin
-- estar en ninguna de esas dos listas. Con varios triggers en el mismo
-- canal gana el primero que matchea, en orden de creación (id ascendente)
-- -- ver list_channel_triggers.
--
-- match_type: 'exact' | 'starts_with' | 'regex' (comparación case-
-- insensitive para las dos primeras; regex usa el patrón tal cual, sin
-- flags forzados -- el admin agrega (?i) si lo quiere insensible).
-- action: 'frase_de_pack' (siempre una frase del pool de pack_id),
-- 'markov' (siempre texto generado), 'mezcla' (mismo roll de
-- frase_probability que la conducta espontánea/de mención, pero con el
-- pack_id de ESTE trigger, no el que tenga asignado el canal).
-- pack_id NULL en 'frase_de_pack'/'mezcla' usa el pool default del
-- servidor (frases sin pack) -- ídem que en frase_pack_channels.
CREATE TABLE IF NOT EXISTS channel_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    match_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    pack_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_channel_triggers_channel
    ON channel_triggers(guild_id, channel_id);

-- Canales de los que el bot SÍ aprende. Allowlist positiva: lo que no está
-- acá no entra al corpus. Ojo con la asimetría respecto de chat_channels:
-- ahí la lista vacía significa "todos", acá significa "ninguno". Es a
-- propósito — leer mensajes de un canal es más invasivo que responder en él,
-- así que el default seguro es no leer nada. Los servidores que ya existían
-- se rellenan una vez con su estado real (ver seed_corpus_allowed_channels).
CREATE TABLE IF NOT EXISTS corpus_allowed_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Roles que se saltan el tope de menciones por hora (moderación, boosters…).
CREATE TABLE IF NOT EXISTS mention_rate_limit_exempt_roles (
    guild_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

-- Canales donde el tope de menciones por hora no aplica (#bot-testing, canales
-- de spam a propósito). Mismo concepto que la tabla de roles de arriba, pero
-- por canal: evita tener que inventar un rol solo para eximir un canal.
CREATE TABLE IF NOT EXISTS mention_rate_limit_exempt_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Migraciones de datos que corren una vez POR SERVIDOR (no por base). Existen
-- porque algunas necesitan la API de Discord —la lista real de canales— y no
-- se pueden resolver con un ALTER en init_db.
CREATE TABLE IF NOT EXISTS applied_migrations (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, name)
);

-- Contadores de uso acumulado por servidor (los "logs" de la tab INICIO del
-- dashboard). Una fila por (guild, métrica) en vez de una columna por métrica:
-- sumar una nueva no pide migración.
-- ponytail: contador plano, sin serie temporal. Si algún día se quiere el
-- gráfico "gifs enviados por día", esto pasa a (guild_id, name, día).
CREATE TABLE IF NOT EXISTS guild_counters (
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS guild_bot_style (
    guild_id INTEGER PRIMARY KEY,
    nick TEXT,
    avatar_url TEXT,
    banner_url TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS premium_guilds (
    guild_id INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL,
    note TEXT
);

-- Último evento de Polar (por su propio `timestamp`, no por orden de
-- llegada) que de verdad activó/desactivó premium para este guild. Polar no
-- garantiza orden de entrega -- un reintento tardío de un webhook viejo
-- podía llegar DESPUÉS de uno más nuevo y pisar el estado correcto (ej: un
-- "revoked" viejo reintentado después de un "active" real de una
-- resuscripción). Sobrevive independiente de premium_guilds porque hay que
-- seguir comparando contra él incluso después de un downgrade real.
CREATE TABLE IF NOT EXISTS premium_event_watermark (
    guild_id INTEGER PRIMARY KEY,
    last_event_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_departures (
    guild_id INTEGER PRIMARY KEY,
    left_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_refeed_status (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    newest_message_id INTEGER,
    oldest_message_id INTEGER,
    backfill_complete INTEGER NOT NULL DEFAULT 0,
    last_refed_at TEXT,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS guild_auto_refeed (
    guild_id INTEGER PRIMARY KEY,
    triggered_at TEXT NOT NULL,
    completed_at TEXT,
    welcome_channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS shared_embeds (
    share_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,          -- JSON: { embeds: [...], send_options: {...} }
    created_guild_id INTEGER,       -- solo referencia/auditoría, no restringe quién puede abrirlo
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_message_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    delete_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pending_message_deletions_delete_at ON pending_message_deletions(delete_at);

-- Singleton (id siempre 1): guarda si el último apagado fue intencional
-- (SIGTERM/SIGINT interceptado) para que el próximo arranque sepa si avisar
-- de una caída inesperada. Fila ausente = el bot nunca llegó a escribir acá
-- (primer arranque de la historia), distinto de clean_shutdown=0 preexistente.
CREATE TABLE IF NOT EXISTS lifecycle_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    clean_shutdown INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- Quién hizo qué cambio de config desde el dashboard. A diferencia de
-- frases_especiales (la única tabla que ya guardaba user_id/user_name antes
-- de esto), el resto de las tablas de config no dice quién tocó qué -- esta
-- tabla es el registro aparte, no una columna más en cada una.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_log_guild ON audit_log(guild_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(guild_id, user_id, id DESC);

-- sid de sesiones del dashboard invalidadas por logout. EncryptedCookieStorage
-- guarda la sesión entera cifrada en la cookie -- no hay session store del
-- lado del server -- así que sin esta tabla, una copia de la cookie tomada
-- antes del logout (XSS, log, dispositivo compartido) seguiría sirviendo
-- hasta que expire sola (7 días). Un sid entra acá SOLO al momento del
-- logout; nunca se lista para leer, solo se consulta por sid puntual.
CREATE TABLE IF NOT EXISTS revoked_sessions (
    sid TEXT PRIMARY KEY,
    revoked_at TEXT NOT NULL
);
"""


async def init_db():
    global _db
    if _db is not None:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    # Activar modo WAL para mejor concurrencia
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    # Crear tablas
    await _db.executescript(SCHEMA)
    try:
        await _db.execute(
            "ALTER TABLE youtube_subscriptions ADD COLUMN mention_role_id INTEGER"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna mention_role_id ya existe en youtube_subscriptions")
    try:
        await _db.execute(
            "ALTER TABLE youtube_subscriptions ADD COLUMN last_error TEXT"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna last_error ya existe en youtube_subscriptions")
    try:
        await _db.execute("ALTER TABLE corpus_gifs ADD COLUMN media_url TEXT")
        await _db.commit()
    except Exception:
        log.debug("Columna media_url ya existe en corpus_gifs")
    try:
        await _db.execute(
            "ALTER TABLE corpus_gifs ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna fail_count ya existe en corpus_gifs")
    try:
        await _db.execute("ALTER TABLE corpus_gifs ADD COLUMN last_health_check TEXT")
        await _db.commit()
    except Exception:
        log.debug("Columna last_health_check ya existe en corpus_gifs")
    try:
        await _db.execute("ALTER TABLE corpus_gifs ADD COLUMN checked_at TEXT")
        await _db.commit()
    except Exception:
        log.debug("Columna checked_at ya existe en corpus_gifs")
    try:
        await _db.execute(
            "ALTER TABLE corpus_gifs ADD COLUMN dead_streak INTEGER NOT NULL DEFAULT 0"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna dead_streak ya existe en corpus_gifs")
    try:
        await _db.execute("ALTER TABLE corpus_gifs ADD COLUMN content_hash TEXT")
        await _db.commit()
    except Exception:
        log.debug("Columna content_hash ya existe en corpus_gifs")
    try:
        await _db.execute("ALTER TABLE gif_objects ADD COLUMN phash TEXT")
        await _db.commit()
    except Exception:
        log.debug("Columna phash ya existe en gif_objects")
    try:
        await _db.execute("ALTER TABLE settings ADD COLUMN locale TEXT")
        await _db.commit()
    except Exception:
        log.debug("Columna locale ya existe en settings")
    # Canal donde Purgito publica sus anuncios de actualizaciones (dashboard INICIO).
    try:
        await _db.execute("ALTER TABLE settings ADD COLUMN updates_channel_id INTEGER")
        await _db.commit()
    except Exception:
        log.debug("Columna updates_channel_id ya existe en settings")
    # Anti-farmeo: interacciones por hora y por usuario. Los servidores que ya
    # existen quedan con el default (10), igual que uno nuevo.
    try:
        await _db.execute(
            "ALTER TABLE settings ADD COLUMN mention_rate_limit "
            f"INTEGER NOT NULL DEFAULT {DEFAULT_MENTION_RATE_LIMIT}"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna mention_rate_limit ya existe en settings")
    # Comportamiento del chat por servidor. Los defaults son los valores fijos
    # que tenía config.py, así que las filas viejas siguen comportándose igual.
    for _col, _type, _default in (
        ("auto_generate_every", "INTEGER", DEFAULT_AUTO_GENERATE_EVERY),
        ("auto_generate_probability", "REAL", DEFAULT_AUTO_GENERATE_PROBABILITY),
        ("reaction_probability", "REAL", DEFAULT_REACTION_PROBABILITY),
        ("gif_response_probability", "REAL", DEFAULT_GIF_RESPONSE_PROBABILITY),
        ("frase_probability", "REAL", DEFAULT_FRASE_PROBABILITY),
    ):
        try:
            await _db.execute(
                f"ALTER TABLE settings ADD COLUMN {_col} {_type} "
                f"NOT NULL DEFAULT {_default}"
            )
            await _db.commit()
        except Exception:
            log.debug("Columna %s ya existe en settings", _col)
    try:
        await _db.execute(
            "ALTER TABLE guild_auto_refeed ADD COLUMN welcome_channel_id INTEGER"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna welcome_channel_id ya existe en guild_auto_refeed")
    try:
        await _db.execute(
            "ALTER TABLE scheduled_announcements ADD COLUMN embed_json TEXT DEFAULT NULL"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna embed_json ya existe en scheduled_announcements")
    # content_mode: distingue embeds clásicos de layouts Components V2. Al hacer
    # ADD COLUMN con DEFAULT, SQLite rellena las filas viejas con el default, así
    # que todo lo ya guardado queda como 'classic_embed' sin backfill manual.
    for _table in ("embed_templates", "scheduled_announcements"):
        try:
            await _db.execute(
                f"ALTER TABLE {_table} ADD COLUMN content_mode TEXT NOT NULL DEFAULT 'classic_embed'"
            )
            await _db.commit()
        except Exception:
            log.debug("Columna content_mode ya existe en %s", _table)
    try:
        await _db.execute(
            "ALTER TABLE scheduled_announcements ADD COLUMN delete_after_seconds INTEGER"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna delete_after_seconds ya existe en scheduled_announcements")
    # Override por canal del tunable nuevo (Fase 3): igual que el resto de
    # channel_settings, nullable y sin default -- NULL siempre significa "sin
    # override acá", nunca "cero".
    try:
        await _db.execute(
            "ALTER TABLE channel_settings ADD COLUMN frase_probability REAL"
        )
        await _db.commit()
    except Exception:
        log.debug("Columna frase_probability ya existe en channel_settings")
    # NULL = "sin pack" (pool default del servidor) -- ver el comentario largo
    # junto a frase_packs/frase_pack_channels sobre la semántica completa.
    try:
        await _db.execute("ALTER TABLE frases_especiales ADD COLUMN pack_id INTEGER")
        await _db.commit()
    except Exception:
        log.debug("Columna pack_id ya existe en frases_especiales")
    await _db.commit()
    flag_path = os.path.join(DATA_DIR, ".images_wiped_v2")
    if not os.path.exists(flag_path):
        await _db.execute("DELETE FROM corpus_images")
        await _db.commit()
        with open(flag_path, "w") as f:
            f.write("done")
        log.info("corpus_images wipeado - migracion v2")
    # chat_channels se dividió en spontaneous_channels + mention_channels.
    # Copiar una sola vez lo que ya había configurado cada servidor para que
    # ninguno cambie de comportamiento el día del deploy; el flag evita que
    # un admin que después saque un canal de una lista lo vea "resucitar"
    # en el próximo restart.
    split_flag_path = os.path.join(DATA_DIR, ".chat_channels_split_v1")
    if not os.path.exists(split_flag_path):
        await _db.execute(
            "INSERT OR IGNORE INTO spontaneous_channels (guild_id, channel_id) "
            "SELECT guild_id, channel_id FROM chat_channels"
        )
        await _db.execute(
            "INSERT OR IGNORE INTO mention_channels (guild_id, channel_id) "
            "SELECT guild_id, channel_id FROM chat_channels"
        )
        await _db.commit()
        with open(split_flag_path, "w") as f:
            f.write("done")
        log.info("chat_channels dividido en spontaneous_channels/mention_channels")
    # Migrate HOME_GUILD_ID to premium_guilds (idempotent via INSERT OR IGNORE)
    _home_gid = int(os.getenv("HOME_GUILD_ID", "0") or "0")
    if _home_gid:
        await _db.execute(
            "INSERT OR IGNORE INTO premium_guilds (guild_id, added_at, note) "
            "VALUES (?, datetime('now'), 'migrado desde HOME_GUILD_ID')",
            (_home_gid,),
        )
        await _db.commit()


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def get_lifecycle_state() -> dict | None:
    """Estado del último apagado, o None si la fila nunca se escribió (primer
    arranque de la historia) -- distinguir eso de clean_shutdown=0 preexistente
    es lo que evita reportar una caída falsa la primera vez que corre el bot."""
    db = await get_db()
    async with db.execute(
        "SELECT clean_shutdown, updated_at FROM lifecycle_state WHERE id=1"
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {"clean_shutdown": bool(row[0]), "updated_at": row[1]}


async def set_lifecycle_state(clean_shutdown: bool) -> None:
    """Escribe la fila única de lifecycle_state con la hora actual.

    clean_shutdown=False se llama al terminar de arrancar ("estoy corriendo;
    si desaparezco sin volver a marcar esto, fue una caída"). clean_shutdown=True
    lo marca el handler de SIGTERM/SIGINT antes de cerrar."""
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    async with _db_lock:
        await db.execute(
            "INSERT INTO lifecycle_state (id, clean_shutdown, updated_at) "
            "VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "clean_shutdown=excluded.clean_shutdown, updated_at=excluded.updated_at",
            (int(clean_shutdown), now),
        )
        await db.commit()


def _was_inserted(cursor: aiosqlite.Cursor) -> bool:
    return cursor.rowcount == 1


# Settings helpers
async def set_chat_mode(guild_id: int, enabled: bool, channel_id: int | None = None):
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO settings (guild_id, chat_mode_enabled, chat_channel_id) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "    chat_mode_enabled=excluded.chat_mode_enabled, "
            "    chat_channel_id=excluded.chat_channel_id",
            (guild_id, 1 if enabled else 0, channel_id),
        )
        await db.commit()


async def get_chat_settings(guild_id: int):
    """Ajustes de conducta del chat de un servidor.

    `channel_id` (settings.chat_channel_id) está **deprecado**: era un canal
    único y lo reemplazó la lista `chat_channels`. Se sigue devolviendo para no
    romper una migración en caliente, pero la lógica de menciones ya no lo lee
    — ver cogs/chat.py.
    """
    db = await get_db()
    async with db.execute(
        "SELECT chat_mode_enabled, chat_channel_id, mention_rate_limit, "
        "       auto_generate_every, auto_generate_probability, "
        "       reaction_probability, gif_response_probability, frase_probability "
        "FROM settings WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    defaults = {
        "enabled": True,
        "channel_id": None,
        "mention_rate_limit": DEFAULT_MENTION_RATE_LIMIT,
        "auto_generate_every": DEFAULT_AUTO_GENERATE_EVERY,
        "auto_generate_probability": DEFAULT_AUTO_GENERATE_PROBABILITY,
        "reaction_probability": DEFAULT_REACTION_PROBABILITY,
        "gif_response_probability": DEFAULT_GIF_RESPONSE_PROBABILITY,
        "frase_probability": DEFAULT_FRASE_PROBABILITY,
    }
    if not row:
        return defaults
    return {
        "enabled": bool(row[0]),
        "channel_id": row[1],
        "mention_rate_limit": row[2],
        "auto_generate_every": row[3],
        "auto_generate_probability": row[4],
        "reaction_probability": row[5],
        "gif_response_probability": row[6],
        "frase_probability": row[7],
    }


# Rango válido de cada ajuste numérico del chat, en un solo lugar: lo usan el
# setter de abajo y el endpoint del dashboard, así que la API no puede quedar
# aceptando algo que la DB después recorta.
CHAT_TUNABLES = {
    "auto_generate_every": (1, MAX_AUTO_GENERATE_EVERY),
    "auto_generate_probability": (0.0, 1.0),
    "reaction_probability": (0.0, 1.0),
    "gif_response_probability": (0.0, 1.0),
    "mention_rate_limit": (0, MAX_MENTION_RATE_LIMIT),
    "frase_probability": (0.0, 1.0),
}


async def set_chat_tunables(guild_id: int, values: dict) -> dict:
    """Guarda los ajustes numéricos del chat que vengan en `values`.

    Solo toca las claves presentes (el dashboard autoguarda campo por campo) y
    recorta cada una a su rango. Devuelve lo que quedó realmente guardado.
    """
    clean = {}
    for key, raw in values.items():
        if key not in CHAT_TUNABLES or raw is None:
            continue
        low, high = CHAT_TUNABLES[key]
        caster = int if isinstance(low, int) else float
        try:
            clean[key] = max(low, min(high, caster(raw)))
        except (TypeError, ValueError):
            continue
    if not clean:
        return {}
    cols = ", ".join(clean)
    marks = ", ".join("?" for _ in clean)
    updates = ", ".join(f"{k}=excluded.{k}" for k in clean)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"INSERT INTO settings (guild_id, {cols}) VALUES (?, {marks}) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {updates}",
            (guild_id, *clean.values()),
        )
        await db.commit()
    return clean


# ─── Overrides por canal de los tunables de chat (channel_settings) ─────────

_TUNABLE_KEYS = tuple(CHAT_TUNABLES)


async def get_channel_tunables(guild_id: int, channel_id: int) -> dict:
    """Overrides crudos de un canal: cada clave de CHAT_TUNABLES -> su valor
    guardado o None (sin override, hereda el de `settings`). A diferencia de
    get_effective_chat_settings, NO resuelve nada — la usa el endpoint de
    lectura del dashboard para poder distinguir "default" de "override"."""
    db = await get_db()
    cols = ", ".join(_TUNABLE_KEYS)
    async with db.execute(
        f"SELECT {cols} FROM channel_settings WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return dict.fromkeys(_TUNABLE_KEYS)
    return dict(zip(_TUNABLE_KEYS, row))


async def set_channel_tunables(guild_id: int, channel_id: int, values: dict) -> dict:
    """Guarda o borra overrides por canal de los tunables de chat.

    Contrato distinto de set_chat_tunables porque acá "borrar" es una
    operación válida y distinta de "no tocar" (volver a heredar el default
    del servidor no es lo mismo que ignorar el campo):
    - clave ausente en `values`: no se toca.
    - clave presente con valor None: borra el override de esa columna.
    - clave presente con un valor: se recorta a su rango (CHAT_TUNABLES) y
      queda como override.
    Devuelve las claves que se tocaron con el valor que quedó guardado
    (None incluido, para las que se borraron).
    """
    clean: dict[str, float | int | None] = {}
    for key, raw in values.items():
        if key not in CHAT_TUNABLES:
            continue
        if raw is None:
            clean[key] = None
            continue
        low, high = CHAT_TUNABLES[key]
        caster = int if isinstance(low, int) else float
        try:
            clean[key] = max(low, min(high, caster(raw)))
        except (TypeError, ValueError):
            continue
    if not clean:
        return {}
    cols = ", ".join(clean)
    marks = ", ".join("?" for _ in clean)
    updates = ", ".join(f"{k}=excluded.{k}" for k in clean)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"INSERT INTO channel_settings (guild_id, channel_id, {cols}) "
            f"VALUES (?, ?, {marks}) "
            f"ON CONFLICT(guild_id, channel_id) DO UPDATE SET {updates}",
            (guild_id, channel_id, *clean.values()),
        )
        await db.commit()
    return clean


async def get_effective_chat_settings(guild_id: int, channel_id: int) -> dict:
    """Mismo dict que get_chat_settings, pero con los tunables resueltos
    para un canal puntual: override de channel_settings si no es NULL, si no
    el valor de `settings` del servidor. `enabled`/`channel_id` no son
    overrideables por canal y salen tal cual del servidor.

    Punto único de lectura para cogs/chat.py: nada ahí debería leer
    channel_settings ni `settings` directo para un tunable de CHAT_TUNABLES,
    todo pasa por acá."""
    base = await get_chat_settings(guild_id)
    overrides = await get_channel_tunables(guild_id, channel_id)
    resolved = dict(base)
    for key in CHAT_TUNABLES:
        if overrides.get(key) is not None:
            resolved[key] = overrides[key]
    return resolved


async def set_mention_rate_limit(guild_id: int, limit: int) -> None:
    """Interacciones por hora y por usuario. 0 = sin límite.

    No pisa chat_mode_enabled/chat_channel_id (a diferencia de set_chat_mode):
    el dashboard va a editar este campo por separado desde la tab Chat.
    """
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO settings (guild_id, mention_rate_limit) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "    mention_rate_limit=excluded.mention_rate_limit",
            (guild_id, limit),
        )
        await db.commit()


async def get_guild_locale(guild_id: int) -> str | None:
    db = await get_db()
    async with db.execute(
        "SELECT locale FROM settings WHERE guild_id=?", (guild_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row and row[0] else None


async def set_guild_locale(guild_id: int, locale: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO settings (guild_id, locale) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET locale=excluded.locale",
            (guild_id, locale),
        )
        await db.commit()


async def save_corpus_and_user_message(
    guild_id: int,
    channel_id: int,
    author_id: int,
    author_name: str,
    content: str,
    message_id: int | None = None,
) -> tuple[bool, bool]:
    text = (content or "").strip()
    if not text:
        return False, False

    db = await get_db()
    async with _db_lock:
        cur1 = await db.execute(
            "INSERT OR IGNORE INTO corpus_messages (guild_id, channel_id, message_id, content) VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, message_id, text),
        )
        corpus_inserted = _was_inserted(cur1)
        cur2 = await db.execute(
            "INSERT OR IGNORE INTO user_corpus (guild_id, author_id, author_name, message_id, content) VALUES (?, ?, ?, ?, ?)",
            (guild_id, author_id, author_name, message_id, text),
        )
        user_inserted = _was_inserted(cur2)
        await db.commit()
    return corpus_inserted, user_inserted


async def import_corpus_messages(
    guild_id: int, channel_id: int, lines: list[str]
) -> int:
    """Inserta líneas ya limpias (ver generation.clean_for_corpus, lo aplica
    el llamador) directo a corpus_messages, como si fueran mensajes reales
    de ese canal -- message_id NULL porque no vienen de Discord. NO toca
    user_corpus: un import no tiene un autor real al que atribuirle estilo
    personal.

    Un solo executemany (una sola vuelta de _db_lock) en vez de un INSERT
    por línea -- un archivo de texto puede traer miles de líneas, y el bot
    tiene un único _db_lock global sirviendo también a los mensajes reales
    que sigan llegando mientras tanto.

    Respeta los mismos límites que el corpus real: corre
    trim_corpus_if_needed/trim_guild_total_if_needed después del insert,
    igual que cuando llega un mensaje real (ver note_corpus_insert en
    generation.py). Devuelve cuántas líneas se insertaron.
    """
    if not lines:
        return 0
    db = await get_db()
    async with _db_lock:
        await db.executemany(
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
            "VALUES (?, ?, NULL, ?)",
            [(guild_id, channel_id, line) for line in lines],
        )
        await db.commit()
    await trim_corpus_if_needed(guild_id, channel_id)
    await trim_guild_total_if_needed(guild_id)
    return len(lines)


async def delete_recent_corpus(guild_id: int, hours: int = 24) -> dict:
    """ "Amnesia": borra corpus_messages y user_corpus de las últimas
    `hours` horas de un guild -- filtra por created_at (columna propia,
    no algo que dependa de Discord) así que cubre por igual mensajes
    reales e importados. Pensado para cuando el corpus reciente se llenó
    de basura (spam, un raid) y conviene arrancar de nuevo ahí en vez de
    esperar a que el trim normal lo desplace solo -- irreversible, la
    confirmación vive en el dashboard antes de llegar acá.

    No toca frases_especiales, reacciones ni ninguna otra config: solo lo
    que alimenta al Markov. El llamador es responsable de invalidar el
    modelo cacheado (generation.reset_guild_caches) -- este módulo no
    importa generation (generation.py ya importa de acá, sería un ciclo).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    db = await get_db()
    async with _db_lock:
        cur1 = await db.execute(
            "DELETE FROM corpus_messages WHERE guild_id=? AND created_at >= ?",
            (guild_id, cutoff),
        )
        cur2 = await db.execute(
            "DELETE FROM user_corpus WHERE guild_id=? AND created_at >= ?",
            (guild_id, cutoff),
        )
        await db.commit()
    return {"corpus_messages": cur1.rowcount, "user_corpus": cur2.rowcount}


async def count_guild_corpus_messages(guild_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=?", (guild_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0] if row else 0)


async def count_corpus_messages(guild_id: int, channel_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0] if row else 0)


async def get_corpus_messages(guild_id: int, limit: int | None = None) -> list[str]:
    db = await get_db()
    if limit is None:
        query = "SELECT content FROM corpus_messages WHERE guild_id=? ORDER BY RANDOM()"
        params = (guild_id,)
    else:
        query = (
            "SELECT content FROM corpus_messages "
            "WHERE guild_id = ? AND id IN ("
            "    SELECT id FROM corpus_messages WHERE guild_id = ? ORDER BY RANDOM() LIMIT ?"
            ")"
        )
        params = (guild_id, guild_id, limit)
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_corpus_messages_filtered(
    guild_id: int,
    min_words: int = 5,
    limit: int = 300,
) -> list[str]:
    db = await get_db()
    query = (
        "SELECT content FROM corpus_messages "
        "WHERE guild_id = ? "
        "AND (length(content) - length(replace(content, ' ', ''))) >= ? "
        "AND id IN ("
        "    SELECT id FROM corpus_messages "
        "    WHERE guild_id = ? "
        "    AND (length(content) - length(replace(content, ' ', ''))) >= ? "
        "    ORDER BY RANDOM() LIMIT ?"
        ")"
    )
    async with db.execute(
        query, (guild_id, min_words - 1, guild_id, min_words - 1, limit)
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def wipe_corpus(guild_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute("DELETE FROM corpus_messages WHERE guild_id=?", (guild_id,))
        await db.execute("DELETE FROM user_corpus WHERE guild_id=?", (guild_id,))
        await db.commit()


async def _retain_gif_object(
    db, content_hash: str, r2_key: str, size_bytes: int, phash: str | None = None
):
    """Suma una referencia al objeto de R2. Llamar con _db_lock ya tomado.

    phash solo se graba en la fila nueva: el ON CONFLICT no lo toca, así que
    una referencia repetida a un objeto existente no le pisa el phash ya
    calculado (por ejemplo por el backfill).
    """
    await db.execute(
        "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes, phash) "
        "VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(content_hash) DO UPDATE SET ref_count = ref_count + 1",
        (content_hash, r2_key, size_bytes, phash),
    )


async def get_all_gif_phashes() -> list[tuple[str, str, str]]:
    """(content_hash, r2_key, phash) de los objetos que ya tienen phash
    calculado. La usa r2.py para el matching perceptual antes de subir un
    GIF nuevo -- ver upload_gif_sync."""
    db = await get_db()
    async with db.execute(
        "SELECT content_hash, r2_key, phash FROM gif_objects WHERE phash IS NOT NULL"
    ) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


async def release_gif_reference(content_hash: str | None, url: str | None = None):
    """Suelta una referencia a un objeto de R2 y borra el objeto físico recién
    cuando no queda ninguna. Único lugar donde se decide borrar un GIF del
    bucket: todos los caminos de borrado pasan por acá.

    Llamar SIEMPRE fuera de _db_lock (lo toma esta función).

    content_hash None = GIF de tenor/giphy (no ocupa storage, delete_url es
    no-op) o fila anterior a la deduplicación (key propia por guild, 1:1 con
    el objeto): en ambos casos alcanza con el borrado por URL de siempre.
    """
    if not content_hash:
        if url:
            await r2.delete_url(url)
        return
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE gif_objects SET ref_count = ref_count - 1 "
            "WHERE content_hash=? AND ref_count > 0",
            (content_hash,),
        )
        async with db.execute(
            "SELECT r2_key, ref_count FROM gif_objects WHERE content_hash=?",
            (content_hash,),
        ) as cur:
            row = await cur.fetchone()
        if not row or row[1] > 0:
            await db.commit()
            return
        r2_key = row[0]
        await db.execute(
            "DELETE FROM gif_objects WHERE content_hash=?", (content_hash,)
        )
        await db.commit()
    await r2.delete_key(r2_key)


async def get_live_gif_keys() -> set[str]:
    """Keys de R2 que NO son huérfanas, para el barrido periódico.

    Cruza las dos fuentes a propósito: los objetos con ref_count > 0 en
    gif_objects, y las keys que alguna fila de corpus_gifs referencia directo.
    La segunda es la red de seguridad de la primera -- si un ref_count quedara
    mal en cero por un bug, el barrido borraría un GIF que un servidor todavía
    usa, y ese error no se puede deshacer.
    """
    db = await get_db()
    keys: set[str] = set()
    async with db.execute(
        "SELECT r2_key FROM gif_objects WHERE ref_count > 0"
    ) as cursor:
        keys.update(r[0] for r in await cursor.fetchall())

    pub = r2.public_url().rstrip("/")
    if pub:
        prefix = f"{pub}/{r2.GIF_KEY_PREFIX}"
        async with db.execute(
            "SELECT url FROM corpus_gifs WHERE url LIKE ?", (prefix + "%",)
        ) as cursor:
            keys.update(r[0][len(pub) + 1 :] for r in await cursor.fetchall())
    return keys


async def wipe_gifs(guild_id: int) -> int:
    """Borra todos los GIFs del guild (DB + R2 si corresponde). Retorna cuántos se borraron.

    La lectura de qué filas hay que soltar y el DELETE van bajo el MISMO
    _db_lock: si se leyeran por separado (como antes), un GIF nuevo insertado
    por save_gif_url justo en la ventana entre la lectura y el delete
    quedaría borrado de corpus_gifs por el DELETE (que es "todo lo del
    guild", no las filas puntuales leídas) pero nunca liberado de
    gif_objects -- una referencia fantasma que ningún barrido periódico
    puede corregir después, porque get_live_gif_keys confía en ref_count."""
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT url, content_hash FROM corpus_gifs WHERE guild_id=?", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        cursor = await db.execute(
            "DELETE FROM corpus_gifs WHERE guild_id=?", (guild_id,)
        )
        deleted = cursor.rowcount
        await db.commit()

    # En serie, no con gather: release_gif_reference toma _db_lock y los
    # decrementos de un mismo hash tienen que ser uno detrás del otro.
    for url, content_hash in rows:
        await release_gif_reference(content_hash, url)

    return deleted


def gifs_limit(guild_id: int | None) -> int:
    """Máximo de GIFs guardables según plan del guild. Lo usan el insert (que
    desaloja el más viejo al pasarse) y el endpoint que muestra el cupo en el
    dashboard -- antes el literal estaba solo acá adentro y el dashboard no
    tenía forma de mostrar el denominador."""
    return _limit_for_guild(
        guild_id,
        "MAX_GIFS_PER_GUILD_FREE",
        "MAX_GIFS_PER_GUILD_PREMIUM",
        1_500,
        4_000,
    )


async def save_gif_url(
    guild_id: int,
    url: str,
    content_hash: str | None = None,
    size_bytes: int = 0,
    phash: str | None = None,
) -> tuple[bool, int | None]:
    """Devuelve (inserted, evicted_id). evicted_id es el id del GIF más viejo
    desalojado por haber llegado al límite del guild, o None si no hubo desalojo.

    content_hash viene de r2.upload_gif_sync para los GIFs que sí ocupan
    storage propio (cdn.discordapp.com); los de tenor/giphy no lo tienen.

    Único lugar por donde pasan todos los caminos de guardado (harvest
    automático de los cogs, alta manual desde el panel) -- por eso el veto de
    gif_blocklist se aplica acá y no en cada llamador. Un GIF bloqueado
    devuelve (False, None), igual que "ya existía": el caller no debe tratarlo
    como error.

    El chequeo de gif_blocklist va DENTRO del mismo _db_lock que el insert,
    no antes: si se hiciera antes (como pasaba antes de este fix), un
    block_gif concurrente para el mismo content_hash podía insertar la fila
    del blocklist DESPUÉS de que este chequeo ya había dicho "no está
    bloqueado" pero ANTES de que este insert terminara -- dejando una copia
    del contenido recién bloqueado viva en el corpus, exactamente lo que
    block_gif existe para evitar.
    """
    u = (url or "").strip()
    if not u:
        return False, None
    max_gifs = gifs_limit(guild_id)
    db = await get_db()
    evicted_id: int | None = None
    evicted_url: str | None = None
    evicted_hash: str | None = None
    async with _db_lock:
        if await is_gif_blocked(guild_id, content_hash, u):
            return False, None
        async with db.execute(
            "SELECT 1 FROM corpus_gifs WHERE guild_id=? AND url=? LIMIT 1",
            (guild_id, u),
        ) as cur:
            already_exists = await cur.fetchone()
        if not already_exists:
            async with db.execute(
                "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=?", (guild_id,)
            ) as cur:
                row = await cur.fetchone()
            if row and int(row[0]) >= max_gifs:
                async with db.execute(
                    "SELECT id, url, content_hash FROM corpus_gifs "
                    "WHERE guild_id=? ORDER BY id ASC LIMIT 1",
                    (guild_id,),
                ) as cur:
                    oldest = await cur.fetchone()
                if oldest:
                    await db.execute("DELETE FROM corpus_gifs WHERE id=?", (oldest[0],))
                    evicted_id, evicted_url, evicted_hash = oldest
        cursor = await db.execute(
            "INSERT OR IGNORE INTO corpus_gifs (guild_id, url, content_hash) "
            "VALUES (?, ?, ?)",
            (guild_id, u, content_hash),
        )
        inserted = _was_inserted(cursor)
        # Solo se suma referencia si la fila es nueva: si el guild ya tenía
        # este GIF, la referencia que le corresponde ya está contada.
        if inserted and content_hash:
            await _retain_gif_object(
                db, content_hash, r2.gif_key(content_hash), size_bytes, phash
            )
        await db.commit()
    if evicted_id is not None:
        await release_gif_reference(evicted_hash, evicted_url)
    return inserted, evicted_id


async def is_gif_blocked(guild_id: int, content_hash: str | None, url: str) -> bool:
    """content_hash si está disponible (cubre cualquier fila del guild que
    apunte al mismo objeto de R2, sin importar por qué url llegó), si no la
    url exacta.

    Limitación conocida: un GIF de tenor/giphy bloqueado por url (nunca tiene
    content_hash, no ocupan storage propio) solo bloquea esa url puntual --
    la misma animación bajo una url distinta de tenor/giphy no matchea acá.
    """
    db = await get_db()
    if content_hash:
        query, params = (
            "SELECT 1 FROM gif_blocklist WHERE guild_id=? AND content_hash=? LIMIT 1",
            (guild_id, content_hash),
        )
    else:
        query, params = (
            "SELECT 1 FROM gif_blocklist WHERE guild_id=? AND url=? LIMIT 1",
            (guild_id, url),
        )
    async with db.execute(query, params) as cur:
        return bool(await cur.fetchone())


async def block_gif(guild_id: int, content_hash: str | None, url: str) -> None:
    """Vetea un GIF para siempre en este guild: lo borra AHORA (liberando su
    referencia en R2/gif_objects, mismo camino que delete_gif_url_by_id /
    wipe_gifs) y deja una fila en gif_blocklist para que save_gif_url lo
    rechace si se vuelve a compartir -- ver is_gif_blocked.

    Con content_hash, borra cualquier fila del guild que apunte al mismo
    objeto (no solo la url puntual vista en el panel); sin content_hash
    (tenor/giphy) borra por url exacta.

    La lectura de qué filas hay que borrar va DENTRO del mismo _db_lock que
    el INSERT del blocklist y el DELETE: si se leyera antes (como pasaba
    antes de este fix), un save_gif_url concurrente para el mismo
    content_hash podía colar una fila nueva que este DELETE -- armado contra
    la lista vieja de urls -- nunca iba a tocar. El resultado era una copia
    del GIF "bloqueado" sobreviviendo en el corpus, disponible para que el
    bot la siga sorteando, con el blocklist ya insertado pero sin efecto
    sobre esa fila puntual.
    """
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()

    async with _db_lock:
        if content_hash:
            async with db.execute(
                "SELECT url, content_hash FROM corpus_gifs WHERE guild_id=? AND content_hash=?",
                (guild_id, content_hash),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT url, content_hash FROM corpus_gifs WHERE guild_id=? AND url=?",
                (guild_id, url),
            ) as cur:
                rows = await cur.fetchall()

        await db.execute(
            "INSERT OR IGNORE INTO gif_blocklist (guild_id, content_hash, url, blocked_at) "
            "VALUES (?, ?, ?, ?)",
            (guild_id, content_hash, url, now),
        )
        if rows:
            await db.executemany(
                "DELETE FROM corpus_gifs WHERE guild_id=? AND url=?",
                [(guild_id, r[0]) for r in rows],
            )
        await db.commit()

    # Fuera de _db_lock y en serie (no gather): release_gif_reference toma el
    # lock ella misma, y dos decrementos del mismo content_hash tienen que ir
    # uno detrás del otro -- mismo motivo que wipe_gifs.
    for row_url, row_hash in rows:
        await release_gif_reference(row_hash, row_url)


async def unblock_gif(guild_id: int, content_hash: str | None, url: str = "") -> bool:
    """Elimina la fila de gif_blocklist que matchee por content_hash (si se
    pasa) o por url -- mismo criterio que is_gif_blocked/block_gif, no exige
    ambos. Retorna True si había algo que borrar.

    No restaura el GIF ya borrado: solo permite que vuelva a guardarse la
    próxima vez que se comparta.
    """
    db = await get_db()
    async with _db_lock:
        if content_hash:
            cursor = await db.execute(
                "DELETE FROM gif_blocklist WHERE guild_id=? AND content_hash=?",
                (guild_id, content_hash),
            )
        else:
            cursor = await db.execute(
                "DELETE FROM gif_blocklist WHERE guild_id=? AND url=?",
                (guild_id, url),
            )
        deleted = cursor.rowcount > 0
        await db.commit()
    return deleted


async def list_blocked_gifs(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT content_hash, url, blocked_at FROM gif_blocklist "
        "WHERE guild_id=? ORDER BY blocked_at DESC",
        (guild_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [{"content_hash": r[0], "url": r[1], "blocked_at": r[2]} for r in rows]


async def get_gif_by_id(guild_id: int, gif_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT id, url, content_hash FROM corpus_gifs WHERE guild_id=? AND id=?",
        (guild_id, gif_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "url": row[1], "content_hash": row[2]}


async def get_gif_by_url(guild_id: int, url: str) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT id, url, media_url FROM corpus_gifs WHERE guild_id=? AND url=?",
        (guild_id, url),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return {"id": row[0], "url": row[1], "media_url": row[2]}


async def get_random_gif_candidates(guild_id: int, limit: int = 3) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, url, media_url FROM corpus_gifs WHERE guild_id=? ORDER BY RANDOM() LIMIT ?",
        (guild_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"id": r[0], "url": r[1], "media_url": r[2]} for r in rows]


async def count_gif_urls(guild_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM corpus_gifs WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0] if row else 0)


async def list_gif_urls(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, url, created_at, media_url, last_health_check, content_hash "
        "FROM corpus_gifs WHERE guild_id=? ORDER BY id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "url": r[1],
            "created_at": r[2],
            "media_url": r[3],
            "last_health_check": r[4],
            "content_hash": r[5],
        }
        for r in rows
    ]


async def get_gifs_for_health_check(
    guild_id: int | None = None, limit: int = 500
) -> list[dict]:
    """GIFs a revisar en el próximo ciclo: los nunca chequeados primero, luego
    los de checked_at más viejo. Así un corpus grande se termina cubriendo
    entero a lo largo de varios ciclos sin necesitar un cursor aparte."""
    db = await get_db()
    if guild_id is None:
        query = (
            "SELECT id, guild_id, url, media_url FROM corpus_gifs "
            "ORDER BY checked_at IS NOT NULL, checked_at LIMIT ?"
        )
        params: tuple = (limit,)
    else:
        query = (
            "SELECT id, guild_id, url, media_url FROM corpus_gifs WHERE guild_id=? "
            "ORDER BY checked_at IS NOT NULL, checked_at LIMIT ?"
        )
        params = (guild_id, limit)
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [
        {"id": r[0], "guild_id": r[1], "url": r[2], "media_url": r[3]} for r in rows
    ]


_DEAD_STREAK_THRESHOLD = 3


async def record_gif_health_check(gif_id: int, status: str) -> bool:
    """Guarda el resultado de un chequeo de salud del backend (ver
    r2.check_gif_url_health). Un solo 'dead' no basta para borrar -- podría
    ser el host caído 30 segundos -- recién se borra al tercer 'dead'
    seguido (dead_streak llega a _DEAD_STREAK_THRESHOLD). 'unreachable' se
    guarda tal cual mismo sin sumar al streak: es un fallo puntual, no una
    confirmación de que el link esté muerto de verdad.

    Umbral en 3 (no 2) a propósito -- Sección 7 de la auditoría de
    seguridad, tras la investigación forense del auto-borrado agresivo. La
    causa raíz de los dos incidentes reales (claves de oEmbed invertidas)
    ya está corregida, pero "dead" en check_gif_url_health mezcla dos
    señales de confianza distinta: un 404/410 es el host confirmando que el
    contenido ya no existe, mientras que un 200 con Content-Type inválido
    es más ambiguo (podría ser una interstitial de rate-limit o de
    protección anti-bot servida con status 200 en vez de un 429/403
    propio). Tratarlas igual con un umbral de 2 deja margen finito a que dos
    apariciones sucesivas de la señal ambigua, ~24h+ apiradas, borren un GIF
    que en realidad sigue vivo. Subir a 3 sube ese margen a ~48h+ sin
    inventar un tercer estado nuevo -- la postura explícita es priorizar
    menos falsos positivos por sobre la velocidad de limpieza.

    Retorna True si el GIF fue borrado.
    """
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    async with _db_lock:
        if status == "ok":
            await db.execute(
                "UPDATE corpus_gifs SET last_health_check=?, checked_at=?, "
                "dead_streak=0 WHERE id=?",
                (status, now, gif_id),
            )
            await db.commit()
            return False
        if status != "dead":
            await db.execute(
                "UPDATE corpus_gifs SET last_health_check=?, checked_at=? WHERE id=?",
                (status, now, gif_id),
            )
            await db.commit()
            return False
        await db.execute(
            "UPDATE corpus_gifs SET last_health_check=?, checked_at=?, "
            "dead_streak=dead_streak+1 WHERE id=?",
            (status, now, gif_id),
        )
        async with db.execute(
            "SELECT dead_streak, guild_id, url, content_hash FROM corpus_gifs WHERE id=?",
            (gif_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row or row[0] < _DEAD_STREAK_THRESHOLD:
            await db.commit()
            return False
        streak, guild_id, url, content_hash = row
        await db.execute("DELETE FROM corpus_gifs WHERE id=?", (gif_id,))
        await db.commit()
    log.warning(
        "Auto-borrado GIF #%s (guild=%s, url=%s): %s chequeos 'dead' seguidos",
        gif_id,
        guild_id,
        url,
        streak,
    )
    # Que quede en el historial del servidor, no solo en el log del proceso: un
    # GIF que desaparece sin rastro es indistinguible de un bug para el admin
    # (pasó de verdad, y motivó la investigación forense de la Sección 7). El
    # audit_log lo escribían solo las acciones de admin desde webapi; esta es la
    # primera del propio bot, con user_id=0 para distinguirla de una persona.
    # Fuera del `async with _db_lock` de arriba a propósito: log_audit toma el
    # mismo lock y asyncio.Lock no es reentrante.
    await log_audit(
        guild_id,
        0,
        "Purgito",
        "gifs.auto_removed",
        detail=f"url={url} chequeos_dead={streak}",
    )
    await release_gif_reference(content_hash, url)
    return True


async def update_gif_media_url(gif_id: int, media_url: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE corpus_gifs SET media_url=? WHERE id=?",
            (media_url, gif_id),
        )
        await db.commit()


async def get_unresolved_gifs(
    guild_id: int | None = None, limit: int = 30
) -> list[dict]:
    db = await get_db()
    if guild_id is None:
        query = "SELECT id, url FROM corpus_gifs WHERE media_url IS NULL ORDER BY id LIMIT ?"
        params: tuple = (limit,)
    else:
        query = "SELECT id, url FROM corpus_gifs WHERE guild_id=? AND media_url IS NULL ORDER BY id LIMIT ?"
        params = (guild_id, limit)
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [{"id": r[0], "url": r[1]} for r in rows]


async def delete_gif_url_by_id(guild_id: int, gif_id: int) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT url, content_hash FROM corpus_gifs WHERE guild_id=? AND id=?",
        (guild_id, gif_id),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return False
    url, content_hash = row

    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM corpus_gifs WHERE guild_id=? AND id=?",
            (guild_id, gif_id),
        )
        deleted = cursor.rowcount > 0
        await db.commit()

    if deleted:
        await release_gif_reference(content_hash, url)

    return deleted


async def add_youtube_sub(
    guild_id: int,
    channel_id: int,
    youtube_channel_id: str,
    youtube_channel_name: str,
    discord_channel_id: int,
    mention_role_id: int | None = None,
) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO youtube_subscriptions "
            "(guild_id, channel_id, youtube_channel_id, youtube_channel_name, discord_channel_id, mention_role_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                youtube_channel_id,
                youtube_channel_name,
                discord_channel_id,
                mention_role_id,
            ),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_youtube_sub(guild_id: int, youtube_channel_id: str) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM youtube_subscriptions WHERE guild_id=? AND youtube_channel_id=?",
            (guild_id, youtube_channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_youtube_subs(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, guild_id, channel_id, youtube_channel_id, youtube_channel_name, last_video_id, discord_channel_id, mention_role_id, last_error "
        "FROM youtube_subscriptions WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "guild_id": r[1],
            "channel_id": r[2],
            "youtube_channel_id": r[3],
            "youtube_channel_name": r[4],
            "last_video_id": r[5],
            "discord_channel_id": r[6],
            "mention_role_id": r[7],
            "last_error": r[8],
        }
        for r in rows
    ]


async def get_all_youtube_subs() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, guild_id, channel_id, youtube_channel_id, youtube_channel_name, last_video_id, discord_channel_id, mention_role_id, last_error "
        "FROM youtube_subscriptions"
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "guild_id": r[1],
            "channel_id": r[2],
            "youtube_channel_id": r[3],
            "youtube_channel_name": r[4],
            "last_video_id": r[5],
            "discord_channel_id": r[6],
            "mention_role_id": r[7],
            "last_error": r[8],
        }
        for r in rows
    ]


async def update_last_video_id(
    guild_id: int, youtube_channel_id: str, video_id: str
) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE youtube_subscriptions SET last_video_id=? WHERE guild_id=? AND youtube_channel_id=?",
            (video_id, guild_id, youtube_channel_id),
        )
        await db.commit()


YOUTUBE_ERROR_NO_PERMISSION = "sin_permiso"
YOUTUBE_ERROR_CHANNEL_NOT_FOUND = "canal_no_encontrado"
YOUTUBE_ERROR_FEED_NOT_FOUND = "feed_no_encontrado"


async def set_youtube_sub_error(
    guild_id: int, youtube_channel_id: str, error: str | None
) -> None:
    """Marca (o limpia, con error=None) el estado roto de una suscripción:
    YOUTUBE_ERROR_NO_PERMISSION, YOUTUBE_ERROR_CHANNEL_NOT_FOUND o
    YOUTUBE_ERROR_FEED_NOT_FOUND.
    Ver cogs/youtube.py._check_one."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE youtube_subscriptions SET last_error=? WHERE guild_id=? AND youtube_channel_id=?",
            (error, guild_id, youtube_channel_id),
        )
        await db.commit()


async def set_youtube_mention_role(
    guild_id: int, youtube_channel_id: str, role_id: int | None
) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "UPDATE youtube_subscriptions SET mention_role_id=? WHERE guild_id=? AND youtube_channel_id=?",
            (role_id, guild_id, youtube_channel_id),
        )
        updated = cursor.rowcount > 0
        await db.commit()
    return updated


async def remove_youtube_sub_by_id(guild_id: int, sub_id: int) -> bool:
    """Igual que remove_youtube_sub pero por id interno en vez de
    youtube_channel_id -- lo usa el dashboard web, que referencia filas por
    id (mismo patrón que delete_gif_url_by_id/delete_frase_especial)."""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM youtube_subscriptions WHERE guild_id=? AND id=?",
            (guild_id, sub_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def set_youtube_mention_role_by_id(
    guild_id: int, sub_id: int, role_id: int | None
) -> bool:
    """Igual que set_youtube_mention_role pero por id interno -- ver
    remove_youtube_sub_by_id."""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "UPDATE youtube_subscriptions SET mention_role_id=? WHERE guild_id=? AND id=?",
            (role_id, guild_id, sub_id),
        )
        updated = cursor.rowcount > 0
        await db.commit()
    return updated


async def save_user_message(
    guild_id: int,
    author_id: int,
    author_name: str,
    content: str,
    message_id: int | None = None,
) -> bool:
    text = (content or "").strip()
    if not text:
        return False

    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO user_corpus (guild_id, author_id, author_name, message_id, content) VALUES (?, ?, ?, ?, ?)",
            (guild_id, author_id, author_name, message_id, text),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def get_user_messages(
    guild_id: int, author_id: int, limit: int | None = None
) -> list[str]:
    db = await get_db()
    if limit is None:
        query = "SELECT content FROM user_corpus WHERE guild_id=? AND author_id=? ORDER BY RANDOM()"
        params = (guild_id, author_id)
    else:
        query = (
            "SELECT content FROM user_corpus "
            "WHERE guild_id = ? AND author_id = ? AND id IN ("
            "    SELECT id FROM user_corpus WHERE guild_id = ? AND author_id = ? ORDER BY RANDOM() LIMIT ?"
            ")"
        )
        params = (guild_id, author_id, guild_id, author_id, limit)
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def count_user_messages(guild_id: int, author_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM user_corpus WHERE guild_id=? AND author_id=?",
        (guild_id, author_id),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0] if row else 0)


async def add_ignored_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_ignored_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM ignored_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_ignored_channels(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM ignored_channels WHERE guild_id=? ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def set_chat_enabled(guild_id: int, enabled: bool) -> None:
    """Prende/apaga solo la respuesta a menciones, sin tocar chat_channel_id
    (a diferencia de set_chat_mode, que pisa las dos columnas)."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO settings (guild_id, chat_mode_enabled) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "    chat_mode_enabled=excluded.chat_mode_enabled",
            (guild_id, 1 if enabled else 0),
        )
        await db.commit()


# Canales de participación proactiva (spontaneous_channels) y de respuesta a
# menciones (mention_channels) del chat, dos allowlists independientes
# (multi-select del dashboard). Sin filas para el guild = comportamiento
# histórico (responde/habla en cualquier canal no ignorado); con filas, solo
# en esos canales. Ver la nota en chat_channels sobre por qué existe esa
# tabla vieja sin usarse.


async def add_spontaneous_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO spontaneous_channels (guild_id, channel_id) "
            "VALUES (?, ?)",
            (guild_id, channel_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_spontaneous_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM spontaneous_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_spontaneous_channels(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM spontaneous_channels WHERE guild_id=? "
        "ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def add_mention_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO mention_channels (guild_id, channel_id) "
            "VALUES (?, ?)",
            (guild_id, channel_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_mention_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM mention_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_mention_channels(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM mention_channels WHERE guild_id=? ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


# ─── Corpus: allowlist positiva de canales ───────────────────────────────────
#
# Reemplaza al modelo "ignorar canales" como criterio de aprendizaje.
# ignored_channels NO desaparece: sigue siendo su propio concepto (canal
# totalmente mudo). Un canal ignorado nunca aprende, esté o no en esta lista.


async def add_corpus_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO corpus_allowed_channels (guild_id, channel_id) "
            "VALUES (?, ?)",
            (guild_id, channel_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_corpus_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM corpus_allowed_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_corpus_channels(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM corpus_allowed_channels WHERE guild_id=? "
        "ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def is_corpus_allowed(guild_id: int, channel_id: int) -> bool:
    """True si el bot puede aprender de este canal. Lookup por PK: es una
    consulta por mensaje recibido, tiene que ser barata."""
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM corpus_allowed_channels WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ) as cursor:
        return await cursor.fetchone() is not None


# ─── Roles exentos del límite de menciones ───────────────────────────────────


async def add_exempt_role(guild_id: int, role_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO mention_rate_limit_exempt_roles "
            "(guild_id, role_id) VALUES (?, ?)",
            (guild_id, role_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_exempt_role(guild_id: int, role_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM mention_rate_limit_exempt_roles WHERE guild_id=? AND role_id=?",
            (guild_id, role_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_exempt_roles(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT role_id FROM mention_rate_limit_exempt_roles WHERE guild_id=? "
        "ORDER BY role_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


# ─── Canales exentos del límite de menciones ─────────────────────────────────
# Igual que los roles exentos, pero por canal. Lista vacía = el tope aplica en
# todos los canales (default). No se cruza con ignored_channels: un canal
# ignorado sigue mudo, exento o no — la exención solo saltea el conteo horario.


async def add_exempt_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO mention_rate_limit_exempt_channels "
            "(guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_exempt_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM mention_rate_limit_exempt_channels "
            "WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_exempt_channels(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM mention_rate_limit_exempt_channels WHERE guild_id=? "
        "ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


# ─── Migraciones de datos por servidor ───────────────────────────────────────


async def migration_applied(guild_id: int, name: str) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM applied_migrations WHERE guild_id=? AND name=?",
        (guild_id, name),
    ) as cursor:
        return await cursor.fetchone() is not None


async def mark_migration_applied(guild_id: int, name: str) -> bool:
    """Marca la migración como hecha. False si ya lo estaba — quien llama lo
    usa para no repetir el trabajo."""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO applied_migrations (guild_id, name) VALUES (?, ?)",
            (guild_id, name),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def seed_corpus_allowed_channels(guild_id: int, channel_ids: list[int]) -> int:
    """Rellena la allowlist del corpus de un guild en una transacción.

    Solo la usa la migración: `channel_ids` ya viene filtrado (canales de texto
    reales menos los ignorados). INSERT OR IGNORE para que sea reentrante si el
    proceso muere a mitad de camino.
    """
    if not channel_ids:
        return 0
    db = await get_db()
    async with _db_lock:
        await db.executemany(
            "INSERT OR IGNORE INTO corpus_allowed_channels (guild_id, channel_id) "
            "VALUES (?, ?)",
            [(guild_id, cid) for cid in channel_ids],
        )
        await db.commit()
    return len(channel_ids)


async def get_updates_channel(guild_id: int) -> int | None:
    db = await get_db()
    async with db.execute(
        "SELECT updates_channel_id FROM settings WHERE guild_id=?", (guild_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def set_updates_channel(guild_id: int, channel_id: int | None) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO settings (guild_id, updates_channel_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "    updates_channel_id=excluded.updates_channel_id",
            (guild_id, channel_id),
        )
        await db.commit()


async def count_corpus_by_channel(guild_id: int) -> list[dict]:
    """Mensajes aprendidos por canal, de mayor a menor (stats de INICIO)."""
    db = await get_db()
    async with db.execute(
        "SELECT channel_id, COUNT(*) FROM corpus_messages "
        "WHERE guild_id=? GROUP BY channel_id ORDER BY COUNT(*) DESC",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"channel_id": r[0], "count": r[1]} for r in rows]


async def get_bot_style(guild_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT nick, avatar_url, banner_url FROM guild_bot_style WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return {"nick": None, "avatar_url": None, "banner_url": None}
    return {"nick": row[0], "avatar_url": row[1], "banner_url": row[2]}


async def set_bot_style(
    guild_id: int, nick: str | None, avatar_url: str | None, banner_url: str | None
) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO guild_bot_style (guild_id, nick, avatar_url, banner_url, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "    nick=excluded.nick, avatar_url=excluded.avatar_url, "
            "    banner_url=excluded.banner_url, updated_at=excluded.updated_at",
            (guild_id, nick, avatar_url, banner_url),
        )
        await db.commit()


async def is_channel_ignored(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM ignored_channels WHERE guild_id=? AND channel_id=? LIMIT 1",
        (guild_id, channel_id),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


async def add_meme_schedule(
    guild_id: int, channel_id: int, interval_minutes: int
) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR REPLACE INTO meme_schedule (guild_id, channel_id, interval_minutes) VALUES (?, ?, ?)",
            (guild_id, channel_id, interval_minutes),
        )
        inserted = cursor.rowcount > 0
        await db.commit()
    return inserted


async def remove_meme_schedule(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM meme_schedule WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_meme_schedules(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id, interval_minutes, last_posted_at FROM meme_schedule WHERE guild_id=? ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {"channel_id": r[0], "interval_minutes": r[1], "last_posted_at": r[2]}
        for r in rows
    ]


async def get_due_meme_schedules() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT guild_id, channel_id, interval_minutes FROM meme_schedule "
        "WHERE last_posted_at IS NULL "
        "   OR datetime(last_posted_at, '+' || interval_minutes || ' minutes') <= datetime('now')"
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {"guild_id": r[0], "channel_id": r[1], "interval_minutes": r[2]} for r in rows
    ]


async def update_meme_last_posted(guild_id: int, channel_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE meme_schedule SET last_posted_at = datetime('now') WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        await db.commit()


async def add_scheduled_announcement(
    guild_id: int,
    channel_id: int,
    message: str,
    mode: str,
    created_by: int,
    interval_minutes: int | None = None,
    hour: int | None = None,
    minute: int | None = None,
    embed_json: str | None = None,
    content_mode: str = "classic_embed",
    delete_after_seconds: int | None = None,
) -> int | None:
    """Crea un anuncio programado. Devuelve el id insertado, o None si el guild
    ya llegó al límite de anuncios (a diferencia de gifs/imágenes, acá no se
    evictan anuncios viejos: el admin tiene que borrar uno a mano primero).

    embed_json None = anuncio de texto plano (comportamiento clásico); con
    contenido, el loop de anuncios envía embeds o un layout Components V2 según
    content_mode ('classic_embed' | 'layout_v2') en vez del texto de `message`.

    delete_after_seconds None = el mensaje enviado queda (comportamiento
    clásico); con valor, el loop de anuncios lo pasa como delete_after de
    discord.py."""
    max_announcements = _limit_for_guild(
        guild_id,
        "MAX_ANNOUNCEMENTS_PER_GUILD_FREE",
        "MAX_ANNOUNCEMENTS_PER_GUILD_PREMIUM",
        3,
        10,
    )
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT COUNT(*) FROM scheduled_announcements WHERE guild_id=?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
        if row and int(row[0]) >= max_announcements:
            return None
        cursor = await db.execute(
            "INSERT INTO scheduled_announcements "
            "(guild_id, channel_id, message, mode, interval_minutes, hour, minute, created_by, embed_json, content_mode, delete_after_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                message,
                mode,
                interval_minutes,
                hour,
                minute,
                created_by,
                embed_json,
                content_mode,
                delete_after_seconds,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def remove_scheduled_announcement(guild_id: int, announcement_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM scheduled_announcements WHERE guild_id=? AND id=?",
            (guild_id, announcement_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_scheduled_announcements(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, channel_id, message, mode, interval_minutes, hour, minute, "
        "last_sent_at, created_by, created_at, embed_json, content_mode, delete_after_seconds "
        "FROM scheduled_announcements WHERE guild_id=? ORDER BY id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "channel_id": r[1],
            "message": r[2],
            "mode": r[3],
            "interval_minutes": r[4],
            "hour": r[5],
            "minute": r[6],
            "last_sent_at": r[7],
            "created_by": r[8],
            "created_at": r[9],
            "embed_json": r[10],
            "content_mode": r[11],
            "delete_after_seconds": r[12],
        }
        for r in rows
    ]


async def get_due_scheduled_announcements() -> list[dict]:
    """Anuncios listos para enviarse. El modo interval se resuelve en SQL;
    el modo daily se evalúa acá en Python contra la timezone configurada,
    porque hay que comparar hora:minuto y la FECHA local (no solo un delta)."""
    db = await get_db()
    async with db.execute(
        "SELECT id, guild_id, channel_id, message, mode, interval_minutes, hour, minute, last_sent_at, embed_json, content_mode, delete_after_seconds "
        "FROM scheduled_announcements "
        "WHERE (mode='interval' AND (last_sent_at IS NULL "
        "       OR datetime(last_sent_at, '+' || interval_minutes || ' minutes') <= datetime('now'))) "
        "   OR mode='daily'"
    ) as cursor:
        rows = await cursor.fetchall()

    now_local = datetime.now(config.ANNOUNCEMENTS_TIMEZONE)
    due = []
    for r in rows:
        item = {
            "id": r[0],
            "guild_id": r[1],
            "channel_id": r[2],
            "message": r[3],
            "mode": r[4],
            "interval_minutes": r[5],
            "hour": r[6],
            "minute": r[7],
            "last_sent_at": r[8],
            "embed_json": r[9],
            "content_mode": r[10],
            "delete_after_seconds": r[11],
        }
        if item["mode"] == "interval":
            due.append(item)
            continue
        if (now_local.hour, now_local.minute) < (item["hour"], item["minute"]):
            continue
        if item["last_sent_at"]:
            last_local = (
                datetime.strptime(item["last_sent_at"], "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone.utc)
                .astimezone(config.ANNOUNCEMENTS_TIMEZONE)
            )
            if last_local.date() == now_local.date():
                continue
        due.append(item)
    return due


# ─── Plantillas de embeds ────────────────────────────────────────────────────


def normalize_embeds_json(raw: str | None) -> list[dict]:
    """Parsea embed_json a una lista de dicts de embed.

    Tres formatos históricos conviven en DB, todos se leen sin reescribir la
    fila: dict suelto (un solo embed, pre-Fase 1), lista de embeds (Fase 1), y
    wrapper {"embeds": [...], "send_options": {...}} (Fase 5, cuando el envío
    lleva opciones finas). El mismo código de envío maneja los tres sin ramas."""
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        inner = data.get("embeds")
        if isinstance(inner, list):
            return inner
        return [data]
    if isinstance(data, list):
        return data
    return []


def extract_send_options(raw: str | None) -> dict | None:
    """Opciones de envío (silencioso/menciones) guardadas dentro de embed_json.
    Funciona para el wrapper de embeds clásicos y para layouts V2 (ambos las
    llevan como clave "send_options" al tope del dict). None si no hay."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):
        options = data.get("send_options")
        return options if isinstance(options, dict) else None
    return None


def embed_template_limit(guild_id: int | None) -> int:
    """Máximo de plantillas de embed guardables según plan del guild."""
    return _limit_for_guild(
        guild_id,
        "MAX_EMBED_TEMPLATES_PER_GUILD_FREE",
        "MAX_EMBED_TEMPLATES_PER_GUILD_PREMIUM",
        20,
        50,
    )


async def add_embed_template(
    guild_id: int, name: str, embed_json: str, content_mode: str = "classic_embed"
) -> int | None:
    """Guarda una plantilla de embed. Devuelve el id insertado, o None si el
    guild ya llegó al límite (mismo criterio que anuncios: se rechaza el alta,
    no se evicta la plantilla más vieja). content_mode distingue embeds
    clásicos ('classic_embed') de layouts Components V2 ('layout_v2')."""
    max_templates = embed_template_limit(guild_id)
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT COUNT(*) FROM embed_templates WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if row and int(row[0]) >= max_templates:
            return None
        cursor = await db.execute(
            "INSERT INTO embed_templates (guild_id, name, embed_json, content_mode) "
            "VALUES (?, ?, ?, ?)",
            (guild_id, name, embed_json, content_mode),
        )
        await db.commit()
        return cursor.lastrowid


async def list_embed_templates(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, name, embed_json, content_mode, created_at, updated_at "
        "FROM embed_templates WHERE guild_id=? ORDER BY id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "embed_json": r[2],
            "content_mode": r[3],
            "created_at": r[4],
            "updated_at": r[5],
        }
        for r in rows
    ]


async def get_embed_template(template_id: int, guild_id: int) -> dict | None:
    """El guild_id en el WHERE es chequeo de propiedad, no solo de existencia:
    sin él, un guild podría leer/borrar plantillas de otro por IDOR."""
    db = await get_db()
    async with db.execute(
        "SELECT id, name, embed_json, content_mode, created_at, updated_at "
        "FROM embed_templates WHERE id=? AND guild_id=?",
        (template_id, guild_id),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "embed_json": row[2],
        "content_mode": row[3],
        "created_at": row[4],
        "updated_at": row[5],
    }


async def update_embed_template(
    template_id: int,
    guild_id: int,
    name: str,
    embed_json: str,
    content_mode: str = "classic_embed",
) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "UPDATE embed_templates SET name=?, embed_json=?, content_mode=?, "
            "updated_at=datetime('now') WHERE id=? AND guild_id=?",
            (name, embed_json, content_mode, template_id, guild_id),
        )
        updated = cursor.rowcount > 0
        await db.commit()
    return updated


async def delete_embed_template(template_id: int, guild_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM embed_templates WHERE id=? AND guild_id=?",
            (template_id, guild_id),
        )
        deleted = cursor.rowcount > 0
        await db.commit()
    return deleted


# ─── Galería de imágenes ya subidas (reuso entre sesiones/plantillas) ───────
# R2 ya deduplica por hash del contenido (ver _store_upload en webapi.py);
# esta tabla es solo el índice "qué URLs subió este guild" para poblar el
# selector de reutilización del editor. Orden por id (inserción), no por
# created_at: CURRENT_TIMESTAMP de SQLite es de resolución de 1 segundo, así
# que un ON CONFLICT que lo reescribiera para "traer al frente" una imagen
# reusada no se distinguiría de forma confiable de otra fila insertada en el
# mismo segundo. INSERT OR IGNORE (mismo patrón que corpus_images) alcanza.


async def record_uploaded_image(guild_id: int, url: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT OR IGNORE INTO embed_uploaded_images (guild_id, url) VALUES (?, ?)",
            (guild_id, url),
        )
        await db.commit()


async def list_uploaded_images(guild_id: int, limit: int = 40) -> list[str]:
    db = await get_db()
    async with db.execute(
        "SELECT url FROM embed_uploaded_images WHERE guild_id=? "
        "ORDER BY id DESC LIMIT ?",
        (guild_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


# ─── Webhook propio por canal (identidad personalizada, Fase 3) ─────────────


async def get_channel_webhook(guild_id: int, channel_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT webhook_id, webhook_token FROM channel_webhooks "
        "WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return {"webhook_id": row[0], "webhook_token": row[1]}


async def set_channel_webhook(
    guild_id: int, channel_id: int, webhook_id: int, webhook_token: str
) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO channel_webhooks (guild_id, channel_id, webhook_id, webhook_token) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, channel_id) DO UPDATE SET "
            "webhook_id=excluded.webhook_id, webhook_token=excluded.webhook_token",
            (guild_id, channel_id, webhook_id, webhook_token),
        )
        await db.commit()


async def delete_channel_webhook(guild_id: int, channel_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM channel_webhooks WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        await db.commit()


# ─── Embeds compartidos por link ─────────────────────────────────────────────

# TTL fijo de los links compartidos. No se expone al usuario por ahora;
# para cambiarlo basta con editar esta constante.
SHARED_EMBED_TTL_DAYS = 7

_SHARE_ID_ALPHABET = string.ascii_letters + string.digits


def share_links_daily_limit() -> int:
    """Máximo de links compartidos que un guild puede generar por día (UTC).
    Evita que el share se use como storage gratis de terceros."""
    return _env_int("MAX_SHARE_LINKS_PER_GUILD_DAY", 20)


async def generate_unique_share_id(length: int = 8) -> str:
    """Id corto random para el link. Con 62^8 combinaciones la colisión es
    casi imposible, pero si ocurre se reintenta con longitud +1 — mismo patrón
    que generateUniqueShortenKey de Discohook."""
    db = await get_db()
    while True:
        share_id = "".join(secrets.choice(_SHARE_ID_ALPHABET) for _ in range(length))
        async with db.execute(
            "SELECT 1 FROM shared_embeds WHERE share_id=?", (share_id,)
        ) as cursor:
            if await cursor.fetchone() is None:
                return share_id
        length += 1


async def add_shared_embed(
    payload: str, guild_id: int, daily_limit: int | None = None
) -> tuple[str, str] | None:
    """Guarda un payload compartido y devuelve (share_id, expires_at), o
    None si el guild ya llegó al límite diario de links compartidos hoy
    (`daily_limit`, default share_links_daily_limit()).

    El conteo y el insert van bajo el MISMO _db_lock: antes vivían en
    funciones separadas (count_shared_embeds_today sin lock + este insert),
    con la decisión "¿ya llegó al límite?" tomada por el llamador entre
    medio -- dos requests casi simultáneos podían leer el mismo conteo viejo
    y los dos pasar el límite, generando más links de los permitidos por
    día (el límite existe para que el share no se use como storage gratis
    de terceros, ver share_links_daily_limit)."""
    if daily_limit is None:
        daily_limit = share_links_daily_limit()
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT COUNT(*) FROM shared_embeds "
            "WHERE created_guild_id=? AND created_at >= datetime('now', 'start of day')",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row and int(row[0]) >= daily_limit:
            return None
        share_id = await generate_unique_share_id()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=SHARED_EMBED_TTL_DAYS)
        ).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO shared_embeds "
            "(share_id, payload, created_guild_id, created_at, expires_at) "
            "VALUES (?, ?, ?, datetime('now'), ?)",
            (share_id, payload, guild_id, expires_at),
        )
        await db.commit()
    return share_id, expires_at


async def get_shared_embed(share_id: str) -> str | None:
    """Payload JSON del link, o None si no existe o ya venció. No se borra al
    leer: el mismo link puede abrirse varias veces (p. ej. en dos servidores);
    solo se elimina por expiración (purge_expired_shared_embeds)."""
    db = await get_db()
    async with db.execute(
        "SELECT payload FROM shared_embeds "
        "WHERE share_id=? AND expires_at > datetime('now')",
        (share_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def count_shared_embeds_today(guild_id: int) -> int:
    """Links generados por el guild en el día UTC en curso (límite diario)."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM shared_embeds "
        "WHERE created_guild_id=? AND created_at >= datetime('now', 'start of day')",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def purge_expired_shared_embeds() -> int:
    """Borra links vencidos. Lo llama el loop diario de limpieza de guilds."""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM shared_embeds WHERE expires_at <= datetime('now')"
        )
        await db.commit()
    return cursor.rowcount


# ─── Revocación de sesiones del dashboard (logout server-side) ──────────────

# Mismo horizonte que max_age de PURGITO_SESSION (webapi._new_session_storage):
# pasado ese tiempo la cookie ya expiró sola (Fernet la rechaza por ttl), así
# que no hace falta seguir llevando la cuenta del sid.
SESSION_MAX_AGE_DAYS = 7


async def revoke_session(sid: str) -> None:
    """Invalida un sid de sesión (logout). Idempotente: desloguear dos veces
    con el mismo sid no rompe nada."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT OR IGNORE INTO revoked_sessions (sid, revoked_at) "
            "VALUES (?, datetime('now'))",
            (sid,),
        )
        await db.commit()


async def is_session_revoked(sid: str) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM revoked_sessions WHERE sid=?", (sid,)
    ) as cursor:
        return await cursor.fetchone() is not None


async def purge_expired_revoked_sessions() -> int:
    """Borra sid revocados cuya cookie original ya venció de todos modos.
    Lo llama el loop diario de limpieza de guilds."""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM revoked_sessions WHERE revoked_at <= datetime(?, ?)",
            ("now", f"-{SESSION_MAX_AGE_DAYS} days"),
        )
        await db.commit()
    return cursor.rowcount


# ─── Red de seguridad para delete_after de anuncios ──────────────────────────
# El delete_after= que se le pasa a channel.send vive en memoria del proceso
# (asyncio.sleep interno de discord.py) y no sobrevive un restart. Esta tabla
# es el respaldo: anuncios.py registra acá cada borrado programado además de
# pasar delete_after=, y un sweep periódico (y uno al arrancar el bot) limpia
# lo que haya quedado pendiente si el proceso se reinició en el medio.


async def add_pending_deletion(
    channel_id: int, message_id: int, delete_at: datetime
) -> int:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT INTO pending_message_deletions (channel_id, message_id, delete_at) "
            "VALUES (?, ?, ?)",
            (
                channel_id,
                message_id,
                delete_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_due_pending_deletions() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, channel_id, message_id FROM pending_message_deletions "
        "WHERE delete_at <= datetime('now')"
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"id": r[0], "channel_id": r[1], "message_id": r[2]} for r in rows]


async def remove_pending_deletion(deletion_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM pending_message_deletions WHERE id=?", (deletion_id,)
        )
        await db.commit()


# ─── Botones de layouts con acción funcional (Fase 3) ────────────────────────


async def add_button_action(
    custom_id: str, guild_id: int, action_type: str, action_data: str
) -> None:
    """Guarda (o actualiza) el mapeo custom_id -> acción de un botón de layout.
    INSERT OR REPLACE porque custom_id es la clave: reintentar el registro de
    un botón ya existente (ej. reintento de red) no debe fallar por UNIQUE."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT OR REPLACE INTO layout_button_actions "
            "(custom_id, guild_id, action_type, action_data) VALUES (?, ?, ?, ?)",
            (custom_id, guild_id, action_type, action_data),
        )
        await db.commit()


async def get_button_action(custom_id: str) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT custom_id, guild_id, action_type, action_data "
        "FROM layout_button_actions WHERE custom_id=?",
        (custom_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return {
        "custom_id": row[0],
        "guild_id": row[1],
        "action_type": row[2],
        "action_data": row[3],
    }


async def list_button_actions() -> list[dict]:
    """Todas las filas, para reconstruir la vista persistente al arrancar el bot."""
    db = await get_db()
    async with db.execute(
        "SELECT custom_id, guild_id, action_type, action_data FROM layout_button_actions"
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {"custom_id": r[0], "guild_id": r[1], "action_type": r[2], "action_data": r[3]}
        for r in rows
    ]


async def update_announcement_last_sent(announcement_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE scheduled_announcements SET last_sent_at = datetime('now') WHERE id=?",
            (announcement_id,),
        )
        await db.commit()


async def save_image_url(guild_id: int, url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    max_images = _limit_for_guild(
        guild_id,
        "MAX_IMAGES_PER_GUILD_FREE",
        "MAX_IMAGES_PER_GUILD_PREMIUM",
        75,
        200,
    )
    db = await get_db()
    evicted_url: str | None = None
    async with _db_lock:
        async with db.execute(
            "SELECT 1 FROM corpus_images WHERE guild_id=? AND url=? LIMIT 1",
            (guild_id, u),
        ) as cur:
            already_exists = await cur.fetchone()
        if not already_exists:
            async with db.execute(
                "SELECT COUNT(*) FROM corpus_images WHERE guild_id=?", (guild_id,)
            ) as cur:
                row = await cur.fetchone()
            if row and int(row[0]) >= max_images:
                async with db.execute(
                    "SELECT id, url FROM corpus_images WHERE guild_id=? ORDER BY id ASC LIMIT 1",
                    (guild_id,),
                ) as cur:
                    oldest = await cur.fetchone()
                if oldest:
                    await db.execute(
                        "DELETE FROM corpus_images WHERE id=?", (oldest[0],)
                    )
                    evicted_url = oldest[1]
        cursor = await db.execute(
            "INSERT OR IGNORE INTO corpus_images (guild_id, url) VALUES (?, ?)",
            (guild_id, u),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    if evicted_url:
        await r2.delete_url(evicted_url)
    return inserted


async def get_random_image_url(guild_id: int) -> str | None:
    """Retorna una URL de imagen random del pool del server."""
    db = await get_db()
    async with db.execute(
        "SELECT url FROM corpus_images WHERE guild_id=? ORDER BY RANDOM() LIMIT 1",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def count_image_urls(guild_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM corpus_images WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0] if row else 0)


async def delete_image_url(guild_id: int, url: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM corpus_images WHERE guild_id=? AND url=?",
            (guild_id, url),
        )
        await db.commit()


async def get_random_image_url_excluding(
    guild_id: int,
    exclude_url: str | None = None,
) -> str | None:
    db = await get_db()
    if exclude_url:
        async with db.execute(
            "SELECT url FROM corpus_images "
            "WHERE guild_id=? AND url != ? "
            "ORDER BY RANDOM() LIMIT 1",
            (guild_id, exclude_url),
        ) as cursor:
            row = await cursor.fetchone()
    else:
        async with db.execute(
            "SELECT url FROM corpus_images WHERE guild_id=? ORDER BY RANDOM() LIMIT 1",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


def frases_limit(guild_id: int | None) -> int:
    """Máximo de frases especiales guardables según plan del guild."""
    return _limit_for_guild(
        guild_id,
        "MAX_FRASES_PER_GUILD_FREE",
        "MAX_FRASES_PER_GUILD_PREMIUM",
        50,
        200,
    )


async def add_frase_especial(
    guild_id: int,
    user_id: int,
    user_name: str,
    frase: str,
    pack_id: int | None = None,
) -> bool | None:
    """Guarda una frase especial. None si el guild ya llegó al límite de
    frases_limit (mismo criterio que add_embed_template); False si el texto
    está vacío. pack_id=None (default) la deja en el pool default del
    servidor -- ver el comentario en frase_packs sobre esa semántica.

    Recortada a 2000 caracteres (el máximo real de un mensaje de Discord):
    sin tope, una frase gigante dispara chunk_message() y el bot manda
    decenas de mensajes seguidos al canal cuando el trigger/frase dispara."""
    text = clean_admin_text(frase)[:2000]
    if not text:
        return False
    max_frases = frases_limit(guild_id)
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT COUNT(*) FROM frases_especiales WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if row and int(row[0]) >= max_frases:
            return None
        cursor = await db.execute(
            "INSERT INTO frases_especiales (guild_id, user_id, user_name, frase, pack_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, user_name, text, pack_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def get_random_frase_especial(
    guild_id: int, pack_id: int | None = None
) -> str | None:
    """Frase al azar del pool efectivo: pack_id=None es el pool default del
    servidor (frases sin pack asignado), un id puntual restringe a ese pack.
    `pack_id IS ?` y no `=`: la columna puede ser NULL y el parámetro
    también, y '=' con NULL de cualquier lado nunca matchea en SQL."""
    db = await get_db()
    async with db.execute(
        "SELECT frase FROM frases_especiales WHERE guild_id=? AND pack_id IS ? "
        "ORDER BY RANDOM() LIMIT 1",
        (guild_id, pack_id),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


def _frase_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "user_id": row[1],
        "user_name": row[2],
        "frase": row[3],
        "created_at": row[4],
        "pack_id": row[5],
    }


async def list_frases_especiales(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, user_id, user_name, frase, created_at, pack_id "
        "FROM frases_especiales WHERE guild_id=? ORDER BY id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [_frase_row_to_dict(r) for r in rows]


async def get_frase_especial(guild_id: int, frase_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT id, user_id, user_name, frase, created_at, pack_id "
        "FROM frases_especiales WHERE guild_id=? AND id=?",
        (guild_id, frase_id),
    ) as cursor:
        row = await cursor.fetchone()
    return _frase_row_to_dict(row) if row else None


async def delete_frase_especial(guild_id: int, frase_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM frases_especiales WHERE guild_id=? AND id=?",
            (guild_id, frase_id),
        )
        deleted = cursor.rowcount > 0
        await db.commit()
    return deleted


async def update_frase_especial(
    guild_id: int,
    frase_id: int,
    *,
    frase: str | None = None,
    pack_id: int | None = None,
    update_pack: bool = False,
) -> bool:
    """Actualiza el texto y/o el pack de una frase especial existente.

    Valida que la frase pertenezca a guild_id y que pack_id (si se especifica)
    también pertenezca a este guild (evita IDOR).
    """
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT 1 FROM frases_especiales WHERE guild_id=? AND id=?",
            (guild_id, frase_id),
        ) as cur:
            if not await cur.fetchone():
                return False

        cols: list[str] = []
        params: list[object] = []

        if frase is not None:
            text = clean_admin_text(frase)[:2000]
            if not text:
                return False
            cols.append("frase=?")
            params.append(text)

        if update_pack:
            if pack_id is not None:
                async with db.execute(
                    "SELECT 1 FROM frase_packs WHERE guild_id=? AND id=?",
                    (guild_id, pack_id),
                ) as cur:
                    if not await cur.fetchone():
                        return False
            cols.append("pack_id=?")
            params.append(pack_id)

        if not cols:
            return True

        params.extend([guild_id, frase_id])
        updates = ", ".join(cols)
        cursor = await db.execute(
            f"UPDATE frases_especiales SET {updates} WHERE guild_id=? AND id=?",
            params,
        )
        updated = cursor.rowcount > 0
        await db.commit()
    return updated


async def set_frase_pack(guild_id: int, frase_id: int, pack_id: int | None) -> bool:
    """Asigna (o quita, con pack_id=None) el pack de una frase existente.

    Valida que pack_id sea de ESTE guild antes de asignarlo -- sin esto, un
    admin podía apuntar una frase propia a un pack_id ajeno (IDOR: el id es
    un autoincrement global, no algo scopeado por guild). Hoy ningún query
    de lectura junta contenido de otro guild a través de ese pack_id
    (get_random_frase_especial siempre filtra por guild_id Y pack_id juntos),
    pero es el mismo patrón de validación que ya se usa en delete_frase_pack
    -- más vale no dejar un pack_id ajeno colgado en la fila."""
    return await update_frase_especial(
        guild_id, frase_id, pack_id=pack_id, update_pack=True
    )


# ─── Canales permitidos para frases especiales (frase_allowed_channels) ─────


async def add_frase_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO frase_allowed_channels (guild_id, channel_id) "
            "VALUES (?, ?)",
            (guild_id, channel_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_frase_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM frase_allowed_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_frase_channels(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM frase_allowed_channels WHERE guild_id=? "
        "ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def is_frase_allowed(guild_id: int, channel_id: int) -> bool:
    """True si pueden salir frases especiales en este canal. Lista vacía =
    permitido en cualquiera -- a propósito NO es el criterio de
    corpus_allowed_channels (vacía = ninguno): ver el comentario junto a
    CREATE TABLE frase_allowed_channels."""
    allowed = await list_frase_channels(guild_id)
    return not allowed or channel_id in allowed


# ─── Packs de frases especiales ──────────────────────────────────────────────


def frase_pack_limit(guild_id: int | None) -> int:
    """Máximo de packs de frases por guild."""
    return _limit_for_guild(
        guild_id,
        "MAX_FRASE_PACKS_PER_GUILD_FREE",
        "MAX_FRASE_PACKS_PER_GUILD_PREMIUM",
        5,
        20,
    )


async def add_frase_pack(guild_id: int, name: str) -> int | None:
    """Crea un pack. None si el guild llegó al límite de frase_pack_limit o
    si ya existe un pack con ese nombre en el servidor."""
    clean_name = clean_admin_text(name)[:80]
    if not clean_name:
        return None
    max_packs = frase_pack_limit(guild_id)
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT COUNT(*) FROM frase_packs WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if row and int(row[0]) >= max_packs:
            return None
        try:
            cursor = await db.execute(
                "INSERT INTO frase_packs (guild_id, name) VALUES (?, ?)",
                (guild_id, clean_name),
            )
        except aiosqlite.IntegrityError:
            return None
        await db.commit()
    return cursor.lastrowid


async def list_frase_packs(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, name, created_at FROM frase_packs WHERE guild_id=? ORDER BY name",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]


async def delete_frase_pack(guild_id: int, pack_id: int) -> bool:
    """Borra el pack. Nunca borra contenido ni deja un canal sin pool: las
    frases que lo tenían asignado vuelven a pack_id NULL (pool default) y
    los canales que lo usaban dejan de tener pack (también vuelven al pool
    default) -- ver el comentario grande junto a CREATE TABLE frase_packs."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE frases_especiales SET pack_id=NULL WHERE guild_id=? AND pack_id=?",
            (guild_id, pack_id),
        )
        await db.execute(
            "DELETE FROM frase_pack_channels WHERE guild_id=? AND pack_id=?",
            (guild_id, pack_id),
        )
        cursor = await db.execute(
            "DELETE FROM frase_packs WHERE guild_id=? AND id=?", (guild_id, pack_id)
        )
        deleted = cursor.rowcount > 0
        await db.commit()
    return deleted


async def assign_pack_to_channel(guild_id: int, channel_id: int, pack_id: int) -> bool:
    """Un canal usa a lo sumo un pack: asignar uno nuevo reemplaza al que
    tuviera antes (no hace falta desasignar primero).

    Valida que pack_id sea de ESTE guild antes de asignarlo -- mismo IDOR
    que set_frase_pack (pack_id es un autoincrement global). Retorna False
    sin escribir nada si el pack no es de este guild."""
    db = await get_db()
    async with _db_lock:
        async with db.execute(
            "SELECT 1 FROM frase_packs WHERE guild_id=? AND id=?",
            (guild_id, pack_id),
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute(
            "INSERT INTO frase_pack_channels (guild_id, channel_id, pack_id) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, channel_id) DO UPDATE SET pack_id=excluded.pack_id",
            (guild_id, channel_id, pack_id),
        )
        await db.commit()
    return True


async def unassign_pack_from_channel(
    guild_id: int, channel_id: int, pack_id: int
) -> bool:
    """El canal vuelve a usar el pool default (frases sin pack). Exige el
    pack_id esperado (no solo channel_id) para que un pack_id viejo en la
    URL no pueda borrar una reasignación más nueva a otro pack."""
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM frase_pack_channels WHERE guild_id=? AND channel_id=? "
            "AND pack_id=?",
            (guild_id, channel_id, pack_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_pack_channels(guild_id: int, pack_id: int) -> list[int]:
    """Canales que tienen asignado ese pack puntual."""
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM frase_pack_channels WHERE guild_id=? AND pack_id=? "
        "ORDER BY channel_id",
        (guild_id, pack_id),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_effective_frase_pool(guild_id: int, channel_id: int) -> int | None:
    """pack_id efectivo para elegir una frase en un canal: el que tenga
    asignado en frase_pack_channels, o None (pool default, frases sin pack)
    si el canal no tiene ninguno. No valida si el pack sigue existiendo --
    delete_frase_pack ya limpia frase_pack_channels al borrar uno."""
    db = await get_db()
    async with db.execute(
        "SELECT pack_id FROM frase_pack_channels WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


# ─── Triggers por canal (channel_triggers) ───────────────────────────────────

TRIGGER_MATCH_TYPES = ("exact", "starts_with", "regex")
TRIGGER_ACTIONS = ("frase_de_pack", "markov", "mezcla")

# Largo máximo del pattern de un trigger. Un patrón (regex incluido) no tiene
# motivo real para ser más largo, y sin tope nada impide mandar uno de
# megabytes: compilarlo cuesta segundos de CPU y evaluarlo corre contra cada
# mensaje del canal. Lo comparte webapi.py, que lo rechaza ANTES de compilar.
MAX_TRIGGER_PATTERN = 500


def channel_triggers_limit(guild_id: int | None) -> int:
    """Máximo de triggers por guild (no por canal): cada uno corre una
    evaluación más por mensaje en su canal, así que el tope cuida CPU tanto
    como espacio en la DB."""
    return _limit_for_guild(
        guild_id,
        "MAX_CHANNEL_TRIGGERS_PER_GUILD_FREE",
        "MAX_CHANNEL_TRIGGERS_PER_GUILD_PREMIUM",
        10,
        30,
    )


async def add_channel_trigger(
    guild_id: int,
    channel_id: int,
    match_type: str,
    pattern: str,
    action: str,
    pack_id: int | None = None,
) -> int | None:
    """Crea un trigger. None si el guild llegó a channel_triggers_limit, si
    match_type/action no son válidos, o si pattern está vacío, supera
    MAX_TRIGGER_PATTERN o (para match_type='regex') no compila. Esta función
    no confía en que el llamador ya validó -- es la última barrera antes de
    la DB.

    El pattern largo se RECHAZA, no se recorta: recortarlo guardaba un regex
    distinto del que el llamador validó (los últimos caracteres de un regex
    cambian lo que matchea, o lo dejan sin compilar), así que lo que corría
    contra los mensajes del canal no era lo que el admin escribió."""
    clean_pattern = clean_admin_text(pattern)
    if (
        not clean_pattern
        or len(clean_pattern) > MAX_TRIGGER_PATTERN
        or match_type not in TRIGGER_MATCH_TYPES
        or action not in TRIGGER_ACTIONS
    ):
        return None
    if match_type == "regex":
        try:
            regex.compile(clean_pattern)
        except regex.error:
            return None
    max_triggers = channel_triggers_limit(guild_id)
    db = await get_db()
    async with _db_lock:
        if pack_id is not None:
            # pack_id es un autoincrement global, no scopeado por guild --
            # mismo IDOR que set_frase_pack/assign_pack_to_channel (Sección
            # 6): sin esto, un guild podía apuntar su propio trigger al
            # pack_id de otro servidor.
            async with db.execute(
                "SELECT 1 FROM frase_packs WHERE guild_id=? AND id=?",
                (guild_id, pack_id),
            ) as cur:
                if not await cur.fetchone():
                    return None
        async with db.execute(
            "SELECT COUNT(*) FROM channel_triggers WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
        if row and int(row[0]) >= max_triggers:
            return None
        cursor = await db.execute(
            "INSERT INTO channel_triggers "
            "(guild_id, channel_id, match_type, pattern, action, pack_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, match_type, clean_pattern, action, pack_id),
        )
        await db.commit()
    return cursor.lastrowid


def _trigger_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "channel_id": row[1],
        "match_type": row[2],
        "pattern": row[3],
        "action": row[4],
        "pack_id": row[5],
    }


async def list_channel_triggers(guild_id: int, channel_id: int) -> list[dict]:
    """En orden de creación (id ascendente) -- el primero que matchea gana,
    ver _handle_trigger en cogs/chat.py."""
    db = await get_db()
    async with db.execute(
        "SELECT id, channel_id, match_type, pattern, action, pack_id "
        "FROM channel_triggers WHERE guild_id=? AND channel_id=? ORDER BY id",
        (guild_id, channel_id),
    ) as cursor:
        rows = await cursor.fetchall()
    return [_trigger_row_to_dict(r) for r in rows]


async def list_guild_triggers(guild_id: int) -> list[dict]:
    """Todos los triggers del guild, para que el dashboard los agrupe por
    canal en el cliente en vez de pedir uno por canal."""
    db = await get_db()
    async with db.execute(
        "SELECT id, channel_id, match_type, pattern, action, pack_id "
        "FROM channel_triggers WHERE guild_id=? ORDER BY channel_id, id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [_trigger_row_to_dict(r) for r in rows]


async def delete_channel_trigger(guild_id: int, trigger_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM channel_triggers WHERE guild_id=? AND id=?",
            (guild_id, trigger_id),
        )
        deleted = cursor.rowcount > 0
        await db.commit()
    return deleted


async def log_audit(
    guild_id: int,
    user_id: int,
    user_name: str,
    action: str,
    detail: str | None = None,
) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO audit_log (guild_id, user_id, user_name, action, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, user_name, action, detail),
        )
        await db.commit()


async def count_audit_action(guild_id: int, action: str, days: int = 30) -> int:
    """Cuántas veces se registró `action` en los últimos `days` días.

    Para mostrar en el dashboard un "esto pasó N veces" sin traerse el
    historial entero. created_at es un timestamp de SQLite en UTC, así que la
    comparación va contra datetime('now', '-N days'), también UTC.
    """
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE guild_id=? AND action=? "
        f"AND created_at >= datetime('now', '-{int(days)} days')",
        (guild_id, action),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def list_audit_log(guild_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, user_id, user_name, action, detail, created_at "
        "FROM audit_log WHERE guild_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (guild_id, limit, offset),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "user_name": r[2],
            "action": r[3],
            "detail": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


async def get_audit_log_users(guild_id: int) -> list[dict]:
    """Lista de usuarios distintos que figuran en el audit log del guild."""
    db = await get_db()
    async with db.execute(
        "SELECT DISTINCT user_id, user_name FROM audit_log WHERE guild_id=? ORDER BY user_name COLLATE NOCASE ASC",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"user_id": r[0], "user_name": r[1]} for r in rows]


async def list_audit_log_page(
    guild_id: int,
    before_id: int | None = None,
    limit: int = 5,
    q: str | None = None,
    user_id: int | str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[dict], bool]:
    """Paginación por cursor (id descendente) para el tab HISTORIAL del
    dashboard con soporte de búsqueda, filtros por usuario, acción y rango
    de fechas.

    Pide limit+1 y descarta la última fila como señal de si hay más
    páginas, en vez de un COUNT(*) aparte.
    """
    db = await get_db()
    conditions = ["guild_id = ?"]
    params: list[object] = [guild_id]

    if before_id is not None:
        conditions.append("id < ?")
        params.append(before_id)

    if user_id is not None and str(user_id).strip():
        conditions.append("user_id = ?")
        params.append(int(user_id))

    if action:
        act = action.strip()
        if act.startswith("cat:"):
            cat = act[4:]
            if cat == "contenido":
                conditions.append(
                    "(action LIKE 'frases%' OR action LIKE 'frase_%' OR action LIKE 'triggers%' OR action LIKE 'reactions%')"
                )
            elif cat == "chat":
                conditions.append(
                    "(action LIKE 'chat.%' OR action LIKE 'channel_settings%' OR action LIKE 'mention_channels%' OR action LIKE 'exempt_%' OR action LIKE 'spontaneous_%' OR action LIKE 'updates_channel%' OR action LIKE 'corpus%')"
                )
            elif cat == "multimedia":
                conditions.append("action LIKE 'gifs%'")
            elif cat == "embeds":
                conditions.append(
                    "(action LIKE 'embed_template%' OR action LIKE 'embeds%')"
                )
            elif cat == "integraciones":
                conditions.append("action LIKE 'youtube%'")
            elif cat == "otros":
                conditions.append("action LIKE 'style%'")
            else:
                conditions.append("action LIKE ?")
                params.append(f"{cat}%")
        elif act.endswith(".") or act.endswith("_"):
            conditions.append("action LIKE ?")
            params.append(f"{act}%")
        elif "." in act:
            conditions.append("action = ?")
            params.append(act)
        else:
            conditions.append("action LIKE ?")
            params.append(f"{act}%")

    if date_from:
        df = date_from.strip()
        if len(df) == 10:
            df += " 00:00:00"
        conditions.append("created_at >= ?")
        params.append(df)

    if date_to:
        dt = date_to.strip()
        if len(dt) == 10:
            dt += " 23:59:59"
        conditions.append("created_at <= ?")
        params.append(dt)

    if q:
        q_clean = q.strip()
        if q_clean:
            conditions.append("(detail LIKE ? OR user_name LIKE ? OR action LIKE ?)")
            q_param = f"%{q_clean}%"
            params.extend([q_param, q_param, q_param])

    where_clause = " AND ".join(conditions)
    query = (
        f"SELECT id, user_id, user_name, action, detail, created_at "
        f"FROM audit_log WHERE {where_clause} ORDER BY id DESC LIMIT ?"
    )
    params.append(limit + 1)

    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "user_name": r[2],
            "action": r[3],
            "detail": r[4],
            "created_at": r[5],
        }
        for r in rows
    ], has_more


async def purge_old_audit_log_entries(retention_days: int) -> int:
    """Borra entradas de audit_log más viejas que retention_days. Lo llama el
    loop diario de limpieza de guilds -- mismo patrón que
    purge_expired_shared_embeds/purge_expired_revoked_sessions.

    Existe porque `detail` puede llevar texto tal cual escrito por un admin
    (ej. "frases.add" guarda la frase completa) -- sin este purge, borrar esa
    frase desde /settings no la borraba de verdad: quedaba una copia
    indefinida en el audit log, que ninguna otra acción de borrado tocaba
    (Sección 7 de la auditoría de seguridad). Retención mucho más larga que
    GUILD_DATA_RETENTION_DAYS a propósito -- esto es un registro de auditoría
    ("quién cambió qué"), no el dato en sí, así que amerita sobrevivir más
    tiempo que el contenido que describe.
    """
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM audit_log WHERE created_at <= datetime(?, ?)",
            ("now", f"-{retention_days} days"),
        )
        await db.commit()
    return cursor.rowcount


_CUSTOM_EMOJI_RE = re.compile(r"^<a?:\w+:\d+>$")

# Un emoji unicode (hasta con modificadores y ZWJ) o un custom "<a:nombre:id>"
# entran de sobra en 100 caracteres. Era el único campo de texto de admin sin
# tope: la ruta del panel no limita el largo y el pool no tiene cuota de
# filas, así que se podían guardar reacciones de cientos de KB cada una.
MAX_REACTION_TEXT = 100


async def add_reaction_to_pool(guild_id: int, emoji_text: str) -> bool:
    text = clean_admin_text(emoji_text)
    if not text or len(text) > MAX_REACTION_TEXT:
        return False
    is_custom = 1 if _CUSTOM_EMOJI_RE.match(text) else 0
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO reaction_pool (guild_id, emoji_text, is_custom) VALUES (?, ?, ?)",
            (guild_id, text, is_custom),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_reaction_from_pool(guild_id: int, reaction_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM reaction_pool WHERE guild_id=? AND id=?",
            (guild_id, reaction_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_reaction_pool(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, emoji_text, is_custom FROM reaction_pool WHERE guild_id=? ORDER BY id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"id": r[0], "emoji_text": r[1], "is_custom": bool(r[2])} for r in rows]


async def get_random_reaction(guild_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT emoji_text FROM reaction_pool WHERE guild_id=? ORDER BY RANDOM() LIMIT 1",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return {"emoji_text": row[0]} if row else None


# ─── Contadores de uso ───────────────────────────────────────────────────────


async def bump_counter(guild_id: int, name: str, by: int = 1) -> None:
    """Suma al contador de uso del guild. Silencioso a propósito: es telemetría
    para el dashboard, nunca puede voltear el envío que la dispara."""
    try:
        db = await get_db()
        async with _db_lock:
            await db.execute(
                "INSERT INTO guild_counters (guild_id, name, count) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, name) DO UPDATE SET count = count + excluded.count",
                (guild_id, name, by),
            )
            await db.commit()
    except Exception:
        log.debug("No se pudo sumar el contador %s del guild %s", name, guild_id)


async def get_counters(guild_id: int) -> dict[str, int]:
    db = await get_db()
    async with db.execute(
        "SELECT name, count FROM guild_counters WHERE guild_id=?", (guild_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    return {r[0]: r[1] for r in rows}


# ─── Premium guilds ──────────────────────────────────────────────────────────

# Las funciones _locked de acá abajo asumen que el llamador YA tiene
# _db_lock tomado -- existen para que apply_premium_webhook_change pueda
# componer "leer watermark + aplicar cambio + grabar watermark nuevo" como
# UNA sola sección crítica (asyncio.Lock no es reentrante, así que no se
# puede simplemente llamar a add_premium_guild/set_premium_event_watermark
# -- que toman el lock por su cuenta -- desde adentro de otro `async with
# _db_lock`). Las versiones públicas (add_premium_guild, etc.) lo siguen
# usando cada una de a una para los llamadores que no necesitan la garantía
# atómica extra.


async def _add_premium_guild_locked(db, guild_id: int, note: str | None) -> bool:
    cursor = await db.execute(
        "INSERT OR IGNORE INTO premium_guilds (guild_id, added_at, note) "
        "VALUES (?, datetime('now'), ?)",
        (guild_id, note),
    )
    inserted = _was_inserted(cursor)
    await db.commit()
    return inserted


async def add_premium_guild(guild_id: int, note: str | None = None) -> bool:
    db = await get_db()
    async with _db_lock:
        return await _add_premium_guild_locked(db, guild_id, note)


async def _remove_premium_guild_locked(db, guild_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM premium_guilds WHERE guild_id=?", (guild_id,)
    )
    removed = cursor.rowcount > 0
    await db.commit()
    return removed


async def remove_premium_guild(guild_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        return await _remove_premium_guild_locked(db, guild_id)


async def list_premium_guilds() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT guild_id, added_at, note FROM premium_guilds ORDER BY added_at"
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"guild_id": r[0], "added_at": r[1], "note": r[2]} for r in rows]


async def _get_premium_event_watermark_locked(db, guild_id: int) -> str | None:
    async with db.execute(
        "SELECT last_event_at FROM premium_event_watermark WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def get_premium_event_watermark(guild_id: int) -> str | None:
    """Timestamp ISO del último webhook de Polar que activó/desactivó premium
    para este guild, o None si todavía no se procesó ninguno."""
    db = await get_db()
    return await _get_premium_event_watermark_locked(db, guild_id)


async def _set_premium_event_watermark_locked(db, guild_id: int, event_at: str) -> None:
    await db.execute(
        "INSERT INTO premium_event_watermark (guild_id, last_event_at) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET last_event_at=excluded.last_event_at",
        (guild_id, event_at),
    )
    await db.commit()


async def set_premium_event_watermark(guild_id: int, event_at: str) -> None:
    db = await get_db()
    async with _db_lock:
        await _set_premium_event_watermark_locked(db, guild_id, event_at)


async def apply_premium_webhook_change(
    guild_id: int, *, activate: bool, note: str | None, event_at: str | None
) -> bool | None:
    """Activa/desactiva premium por un webhook de Polar junto con el chequeo
    de orden del watermark, TODO bajo un único _db_lock.

    Sin esto, dos webhooks del mismo guild casi simultáneos (Polar
    reintentando en paralelo, o dos eventos legítimos muy seguidos) podían
    cada uno leer el mismo watermark viejo por su lado -- ambos pasaban el
    chequeo de "no está obsoleto" porque ninguno veía todavía el resultado
    del otro -- y aplicar sus cambios (y grabar su propio watermark) en un
    orden que no respeta cuál evento era realmente el más nuevo, dejando
    tanto premium_guilds como el watermark mismo en un estado que no
    corresponde a ningún evento individual real.

    Retorna None si el evento se descartó por más viejo (o igual) que el
    último ya aplicado para este guild. Si no, True/False -- mismo shape que
    add_premium_guild/remove_premium_guild (fila nueva / había algo que
    borrar).
    """
    db = await get_db()
    async with _db_lock:
        if event_at is not None:
            watermark = await _get_premium_event_watermark_locked(db, guild_id)
            if watermark is not None:
                try:
                    is_stale = datetime.fromisoformat(
                        event_at
                    ) <= datetime.fromisoformat(watermark)
                except ValueError:
                    is_stale = False
                if is_stale:
                    return None
        if activate:
            changed = await _add_premium_guild_locked(db, guild_id, note)
        else:
            changed = await _remove_premium_guild_locked(db, guild_id)
        if event_at is not None:
            await _set_premium_event_watermark_locked(db, guild_id, event_at)
        return changed


# ─── Guild departures ────────────────────────────────────────────────────────


async def mark_guild_departed(guild_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO guild_departures (guild_id, left_at) VALUES (?, datetime('now')) "
            "ON CONFLICT(guild_id) DO UPDATE SET left_at=datetime('now')",
            (guild_id,),
        )
        await db.commit()


async def clear_guild_departure(guild_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute("DELETE FROM guild_departures WHERE guild_id=?", (guild_id,))
        await db.commit()


async def get_expired_departures(retention_days: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT guild_id FROM guild_departures "
        "WHERE datetime(left_at, '+' || ? || ' days') <= datetime('now')",
        (retention_days,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


# ─── Refeed status ───────────────────────────────────────────────────────────


async def get_channel_refeed_status(guild_id: int, channel_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT newest_message_id, oldest_message_id, backfill_complete, last_refed_at "
        "FROM channel_refeed_status WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return {
        "newest_message_id": row[0],
        "oldest_message_id": row[1],
        "backfill_complete": bool(row[2]),
        "last_refed_at": row[3],
    }


async def upsert_channel_refeed_status(
    guild_id: int,
    channel_id: int,
    *,
    newest_message_id: int | None = None,
    oldest_message_id: int | None = None,
    backfill_complete: bool | None = None,
) -> None:
    """Actualiza solo los campos no-None; last_refed_at se pisa siempre."""
    bf = None if backfill_complete is None else int(backfill_complete)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO channel_refeed_status "
            "(guild_id, channel_id, newest_message_id, oldest_message_id, backfill_complete, last_refed_at) "
            "VALUES (?, ?, ?, ?, COALESCE(?, 0), datetime('now')) "
            "ON CONFLICT(guild_id, channel_id) DO UPDATE SET "
            "    newest_message_id=COALESCE(excluded.newest_message_id, newest_message_id), "
            "    oldest_message_id=COALESCE(excluded.oldest_message_id, oldest_message_id), "
            "    backfill_complete=COALESCE(?, backfill_complete), "
            "    last_refed_at=datetime('now')",
            (guild_id, channel_id, newest_message_id, oldest_message_id, bf, bf),
        )
        await db.commit()


async def remember_welcome_channel(guild_id: int, welcome_channel_id: int) -> None:
    """Guarda dónde se mandó la bienvenida, para avisos posteriores (ej. un
    canal recién visible en cogs/chat.py:on_guild_channel_update).

    La tabla se llamaba guild_auto_refeed de cuando también trackeaba el
    auto-refeed al unirse a un servidor (ya no existe, ver Settings.on_guild_join);
    triggered_at/completed_at quedaron sin lector, no vale la pena migrar el
    schema solo para renombrarla."""
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "INSERT INTO guild_auto_refeed (guild_id, triggered_at, welcome_channel_id) "
            "VALUES (?, datetime('now'), ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "    welcome_channel_id=COALESCE(excluded.welcome_channel_id, welcome_channel_id)",
            (guild_id, welcome_channel_id),
        )
        await db.commit()


async def get_welcome_channel_id(guild_id: int) -> int | None:
    """Canal donde se mandó la bienvenida original (para avisos posteriores)."""
    db = await get_db()
    async with db.execute(
        "SELECT welcome_channel_id FROM guild_auto_refeed WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def purge_guild_data(guild_id: int) -> None:
    """Delete all DB rows for a guild. R2 cleanup must be handled by the caller first."""
    db = await get_db()
    tables = [
        "settings",
        "corpus_messages",
        "user_corpus",
        "corpus_gifs",
        "corpus_images",
        "youtube_subscriptions",
        "ignored_channels",
        "meme_schedule",
        "scheduled_announcements",
        "embed_templates",
        "layout_button_actions",
        "frases_especiales",
        "frase_allowed_channels",
        "frase_packs",
        "frase_pack_channels",
        "channel_triggers",
        "reaction_pool",
        "premium_guilds",
        "premium_event_watermark",
        "guild_departures",
        "channel_refeed_status",
        "guild_auto_refeed",
        "guild_counters",
        "chat_channels",
        "spontaneous_channels",
        "mention_channels",
        "channel_settings",
        "corpus_allowed_channels",
        "mention_rate_limit_exempt_roles",
        "mention_rate_limit_exempt_channels",
        "applied_migrations",
        "audit_log",
    ]
    async with _db_lock:
        for table in tables:
            await db.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))
        await db.commit()
    log.info("purge_guild_data: guild %s purgado de %d tablas", guild_id, len(tables))


# ─── Storage limits ──────────────────────────────────────────────────────────


def corpus_channel_limit(guild_id: int | None) -> int:
    """Tope de mensajes de corpus POR CANAL (el nombre del env dice
    PER_GUILD por historia, pero trim_corpus_if_needed lo aplica por canal)."""
    return _limit_for_guild(
        guild_id,
        "MAX_CORPUS_MESSAGES_PER_GUILD_FREE",
        "MAX_CORPUS_MESSAGES_PER_GUILD_PREMIUM",
        15_000,
        50_000,
    )


def corpus_total_limit(guild_id: int | None) -> int:
    """Tope del TOTAL de corpus del guild (todos los canales sumados)."""
    return _limit_for_guild(
        guild_id,
        "MAX_CORPUS_MESSAGES_PER_GUILD_TOTAL_FREE",
        "MAX_CORPUS_MESSAGES_PER_GUILD_TOTAL_PREMIUM",
        150_000,
        500_000,
    )


async def trim_corpus_if_needed(guild_id: int, channel_id: int) -> None:
    """Recorta corpus_messages al límite configurado, por canal (no por guild):
    un canal con mucho historial no debe desplazar el corpus de otros canales
    del mismo guild."""
    max_msgs = corpus_channel_limit(guild_id)
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM corpus_messages WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    ) as cur:
        row = await cur.fetchone()
    count = int(row[0]) if row else 0
    if count <= max_msgs:
        return
    to_delete = count - max_msgs
    async with _db_lock:
        await db.execute(
            "DELETE FROM corpus_messages WHERE guild_id=? AND channel_id=? AND id IN "
            "(SELECT id FROM corpus_messages WHERE guild_id=? AND channel_id=? ORDER BY id ASC LIMIT ?)",
            (guild_id, channel_id, guild_id, channel_id, to_delete),
        )
        await db.commit()
    log.debug(
        "trim_corpus: guild %s canal %s eliminados %d msgs (era %d, límite %d)",
        guild_id,
        channel_id,
        to_delete,
        count,
        max_msgs,
    )


def _water_fill_threshold(counts: list[int], cap: int) -> int:
    """Mayor entero T tal que sum(min(c, T) for c in counts) <= cap.

    Recortar cada canal a min(count_canal, T) reparte el excedente de forma
    proporcional: los canales ya por debajo de T no pierden nada, los que
    estaban muy por encima se recortan hasta emparejarse cerca de T. Es la
    política opuesta a "más antiguo global" (el bug que ya arreglamos en
    trim_corpus_if_needed): acá el orden de inserción entre canales nunca
    entra en la decisión, solo el tamaño relativo de cada canal.

    Búsqueda binaria sobre T en vez de un loop mensaje por mensaje: O(n log
    max_count) con n = cantidad de canales del guild.
    """
    if not counts or sum(counts) <= cap:
        return max(counts, default=0)
    lo, hi = 0, max(counts)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sum(min(c, mid) for c in counts) <= cap:
            lo = mid
        else:
            hi = mid - 1
    return lo


async def trim_guild_total_if_needed(guild_id: int) -> None:
    """Segunda capa de seguridad sobre trim_corpus_if_needed: recorta el
    TOTAL de corpus_messages de un guild (todos los canales sumados) cuando
    la cantidad de canales activos hace que la suma crezca sin límite real
    aunque cada canal individual respete su propio tope.

    Política water-filling (ver _water_fill_threshold), NO "más antiguo
    global": dentro de cada canal recortado sí se borra más viejo primero
    (ahí es correcto, es el mismo canal), pero qué canal se recorta y cuánto
    depende de su tamaño relativo a los demás, no de cuándo se insertó."""
    cap = corpus_total_limit(guild_id)
    db = await get_db()
    async with db.execute(
        "SELECT channel_id, COUNT(*) FROM corpus_messages WHERE guild_id=? GROUP BY channel_id",
        (guild_id,),
    ) as cur:
        rows = await cur.fetchall()
    counts = {int(r[0]): int(r[1]) for r in rows}
    total = sum(counts.values())
    if total <= cap:
        return
    threshold = _water_fill_threshold(list(counts.values()), cap)
    async with _db_lock:
        affected = 0
        for channel_id, count in counts.items():
            to_delete = count - threshold
            if to_delete <= 0:
                continue
            affected += 1
            await db.execute(
                "DELETE FROM corpus_messages WHERE guild_id=? AND channel_id=? AND id IN "
                "(SELECT id FROM corpus_messages WHERE guild_id=? AND channel_id=? ORDER BY id ASC LIMIT ?)",
                (guild_id, channel_id, guild_id, channel_id, to_delete),
            )
        await db.commit()
    log.debug(
        "trim_guild_total: guild %s threshold=%d total=%d cap=%d canales_recortados=%d",
        guild_id,
        threshold,
        total,
        cap,
        affected,
    )


async def trim_user_corpus_if_needed(guild_id: int, author_id: int) -> None:
    """Recorta user_corpus al límite configurado, por autor (no por guild):
    un autor muy activo no debe desplazar el corpus de otros autores del
    mismo servidor."""
    max_msgs = _limit_for_guild(
        guild_id,
        "MAX_USER_CORPUS_MESSAGES_PER_GUILD_FREE",
        "MAX_USER_CORPUS_MESSAGES_PER_GUILD_PREMIUM",
        2_000,
        8_000,
    )
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM user_corpus WHERE guild_id=? AND author_id=?",
        (guild_id, author_id),
    ) as cur:
        row = await cur.fetchone()
    count = int(row[0]) if row else 0
    if count <= max_msgs:
        return
    to_delete = count - max_msgs
    async with _db_lock:
        await db.execute(
            "DELETE FROM user_corpus WHERE guild_id=? AND author_id=? AND id IN "
            "(SELECT id FROM user_corpus WHERE guild_id=? AND author_id=? ORDER BY id ASC LIMIT ?)",
            (guild_id, author_id, guild_id, author_id, to_delete),
        )
        await db.commit()
    log.debug(
        "trim_user_corpus: guild %s autor %s eliminados %d msgs (era %d, límite %d)",
        guild_id,
        author_id,
        to_delete,
        count,
        max_msgs,
    )


async def list_image_urls(guild_id: int) -> list[str]:
    db = await get_db()
    async with db.execute(
        "SELECT url FROM corpus_images WHERE guild_id=? ORDER BY id", (guild_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]
