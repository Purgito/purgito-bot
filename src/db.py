import os
import re
import json
import string
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

import aiosqlite

import config
import r2

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "bot.db")

log = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()

# Interacciones con el bot por hora y por usuario, por servidor. Es anti-abuso,
# no un beneficio premium: mismo default para Free y Premium. 0 = sin límite.
DEFAULT_MENTION_RATE_LIMIT = 10
MAX_MENTION_RATE_LIMIT = 1000


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
    UNIQUE(guild_id, url)
);

CREATE TABLE IF NOT EXISTS youtube_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    youtube_channel_id TEXT NOT NULL,
    youtube_channel_name TEXT NOT NULL,
    last_video_id TEXT,
    discord_channel_id INTEGER NOT NULL,
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
);
CREATE INDEX IF NOT EXISTS idx_frases_especiales_guild ON frases_especiales(guild_id);

CREATE TABLE IF NOT EXISTS reaction_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    emoji_text TEXT NOT NULL,
    is_custom INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, emoji_text)
);
CREATE INDEX IF NOT EXISTS idx_reaction_pool_guild ON reaction_pool(guild_id);

CREATE TABLE IF NOT EXISTS chat_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
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
    await _db.commit()
    flag_path = os.path.join(DATA_DIR, ".images_wiped_v2")
    if not os.path.exists(flag_path):
        await _db.execute("DELETE FROM corpus_images")
        await _db.commit()
        with open(flag_path, "w") as f:
            f.write("done")
        log.info("corpus_images wipeado - migracion v2")
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
    db = await get_db()
    async with db.execute(
        "SELECT chat_mode_enabled, chat_channel_id, mention_rate_limit "
        "FROM settings WHERE guild_id=?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return {
                "enabled": True,
                "channel_id": None,
                "mention_rate_limit": DEFAULT_MENTION_RATE_LIMIT,
            }
        return {
            "enabled": bool(row[0]),
            "channel_id": row[1],
            "mention_rate_limit": row[2],
        }


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


async def wipe_gifs(guild_id: int) -> int:
    """Borra todos los GIFs del guild (DB + R2 si corresponde). Retorna cuántos se borraron."""
    db = await get_db()
    async with db.execute(
        "SELECT url FROM corpus_gifs WHERE guild_id=?", (guild_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    urls = [r[0] for r in rows]

    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM corpus_gifs WHERE guild_id=?", (guild_id,)
        )
        deleted = cursor.rowcount
        await db.commit()

    if urls:
        await asyncio.gather(*(r2.delete_url(u) for u in urls), return_exceptions=True)

    return deleted


async def save_gif_url(guild_id: int, url: str) -> tuple[bool, int | None]:
    """Devuelve (inserted, evicted_id). evicted_id es el id del GIF más viejo
    desalojado por haber llegado al límite del guild, o None si no hubo desalojo."""
    u = (url or "").strip()
    if not u:
        return False, None
    max_gifs = _limit_for_guild(
        guild_id,
        "MAX_GIFS_PER_GUILD_FREE",
        "MAX_GIFS_PER_GUILD_PREMIUM",
        1_500,
        4_000,
    )
    db = await get_db()
    evicted_id: int | None = None
    evicted_url: str | None = None
    async with _db_lock:
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
                    "SELECT id, url FROM corpus_gifs WHERE guild_id=? ORDER BY id ASC LIMIT 1",
                    (guild_id,),
                ) as cur:
                    oldest = await cur.fetchone()
                if oldest:
                    await db.execute("DELETE FROM corpus_gifs WHERE id=?", (oldest[0],))
                    evicted_id, evicted_url = oldest[0], oldest[1]
        cursor = await db.execute(
            "INSERT OR IGNORE INTO corpus_gifs (guild_id, url) VALUES (?, ?)",
            (guild_id, u),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    if evicted_url:
        await r2.delete_url(evicted_url)
    return inserted, evicted_id


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


async def mark_gif_check(gif_id: int, alive: bool, max_fails: int = 3) -> bool:
    """Actualiza el contador de fallos. Retorna True si se borró por superar max_fails.

    No borra el objeto de R2: solo deja de sugerir el GIF desde la DB.
    """
    db = await get_db()
    async with _db_lock:
        if alive:
            await db.execute(
                "UPDATE corpus_gifs SET fail_count=0 WHERE id=?", (gif_id,)
            )
            await db.commit()
            return False
        await db.execute(
            "UPDATE corpus_gifs SET fail_count=fail_count+1 WHERE id=?", (gif_id,)
        )
        async with db.execute(
            "SELECT fail_count FROM corpus_gifs WHERE id=?", (gif_id,)
        ) as cur:
            row = await cur.fetchone()
        borrado = bool(row and row[0] >= max_fails)
        if borrado:
            await db.execute("DELETE FROM corpus_gifs WHERE id=?", (gif_id,))
        await db.commit()
        return borrado


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
        "SELECT id, url, created_at, media_url, last_health_check "
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


async def record_gif_health_check(gif_id: int, status: str) -> bool:
    """Guarda el resultado de un chequeo de salud del backend (ver
    r2.check_gif_url_health). Un solo 'dead' no basta para borrar -- podría
    ser el host caído 30 segundos -- recién se borra al segundo 'dead'
    seguido (dead_streak llega a 2). 'unreachable' se guarda tal cual mismo
    sin sumar al streak: es un fallo puntual, no una confirmación de que el
    link esté muerto de verdad.

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
            "SELECT dead_streak, guild_id, url FROM corpus_gifs WHERE id=?",
            (gif_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row or row[0] < 2:
            await db.commit()
            return False
        streak, guild_id, url = row
        await db.execute("DELETE FROM corpus_gifs WHERE id=?", (gif_id,))
        await db.commit()
    log.warning(
        "Auto-borrado GIF #%s (guild=%s, url=%s): %s chequeos 'dead' seguidos",
        gif_id,
        guild_id,
        url,
        streak,
    )
    await r2.delete_url(url)
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
        "SELECT url FROM corpus_gifs WHERE guild_id=? AND id=?",
        (guild_id, gif_id),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return False
    url = row[0]

    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM corpus_gifs WHERE guild_id=? AND id=?",
            (guild_id, gif_id),
        )
        deleted = cursor.rowcount > 0
        await db.commit()

    if deleted:
        r2_public_url = os.getenv("R2_PUBLIC_URL", "").strip()
        if r2_public_url and url.startswith(r2_public_url):
            try:
                import boto3
                from botocore.config import Config as _BotoConfig

                _ep = os.getenv("R2_ENDPOINT_URL", "").strip()
                _kid = os.getenv("R2_ACCESS_KEY_ID", "").strip()
                _sec = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
                _bkt = os.getenv("R2_BUCKET_NAME", "").strip()
                if _ep and _kid and _sec and _bkt:
                    _key = url[len(r2_public_url.rstrip("/")) + 1 :]

                    def _r2_del():
                        c = boto3.client(
                            "s3",
                            endpoint_url=_ep,
                            aws_access_key_id=_kid,
                            aws_secret_access_key=_sec,
                            config=_BotoConfig(signature_version="s3v4"),
                            region_name="auto",
                        )
                        c.delete_object(Bucket=_bkt, Key=_key)

                    await asyncio.to_thread(_r2_del)
            except Exception:
                log.warning("No se pudo eliminar GIF de R2: %s", url)

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
        "SELECT id, guild_id, channel_id, youtube_channel_id, youtube_channel_name, last_video_id, discord_channel_id, mention_role_id "
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
        }
        for r in rows
    ]


async def get_all_youtube_subs() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, guild_id, channel_id, youtube_channel_id, youtube_channel_name, last_video_id, discord_channel_id, mention_role_id "
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


# Canales de participación proactiva del chat (multi-select del dashboard).
# Sin filas para el guild = comportamiento histórico (habla en cualquier canal
# no ignorado); con filas, solo habla espontáneamente en esos canales.


async def add_chat_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO chat_channels (guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_chat_channel(guild_id: int, channel_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM chat_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_chat_channels(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT channel_id FROM chat_channels WHERE guild_id=? ORDER BY channel_id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


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


async def add_shared_embed(payload: str, guild_id: int) -> tuple[str, str]:
    """Guarda un payload compartido y devuelve (share_id, expires_at)."""
    share_id = await generate_unique_share_id()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=SHARED_EMBED_TTL_DAYS)
    ).strftime("%Y-%m-%d %H:%M:%S")
    db = await get_db()
    async with _db_lock:
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


async def add_frase_especial(
    guild_id: int, user_id: int, user_name: str, frase: str
) -> bool:
    text = (frase or "").strip()
    if not text:
        return False
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT INTO frases_especiales (guild_id, user_id, user_name, frase) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, user_name, text),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def get_random_frase_especial(guild_id: int) -> str | None:
    db = await get_db()
    async with db.execute(
        "SELECT frase FROM frases_especiales WHERE guild_id=? ORDER BY RANDOM() LIMIT 1",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def list_frases_especiales(guild_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT id, user_id, user_name, frase, created_at "
        "FROM frases_especiales WHERE guild_id=? ORDER BY id",
        (guild_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "user_name": r[2],
            "frase": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


async def get_frase_especial(guild_id: int, frase_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT id, user_id, user_name, frase, created_at "
        "FROM frases_especiales WHERE guild_id=? AND id=?",
        (guild_id, frase_id),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "user_name": row[2],
        "frase": row[3],
        "created_at": row[4],
    }


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


_CUSTOM_EMOJI_RE = re.compile(r"^<a?:\w+:\d+>$")


async def add_reaction_to_pool(guild_id: int, emoji_text: str) -> bool:
    text = (emoji_text or "").strip()
    if not text:
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


async def add_premium_guild(guild_id: int, note: str | None = None) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO premium_guilds (guild_id, added_at, note) "
            "VALUES (?, datetime('now'), ?)",
            (guild_id, note),
        )
        inserted = _was_inserted(cursor)
        await db.commit()
    return inserted


async def remove_premium_guild(guild_id: int) -> bool:
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "DELETE FROM premium_guilds WHERE guild_id=?", (guild_id,)
        )
        removed = cursor.rowcount > 0
        await db.commit()
    return removed


async def list_premium_guilds() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT guild_id, added_at, note FROM premium_guilds ORDER BY added_at"
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"guild_id": r[0], "added_at": r[1], "note": r[2]} for r in rows]


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


async def was_auto_refeed_triggered(guild_id: int) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM guild_auto_refeed WHERE guild_id=?", (guild_id,)
    ) as cursor:
        return await cursor.fetchone() is not None


async def mark_auto_refeed_triggered(
    guild_id: int, welcome_channel_id: int | None = None
) -> None:
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


async def mark_auto_refeed_completed(guild_id: int) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE guild_auto_refeed SET completed_at=datetime('now') WHERE guild_id=?",
            (guild_id,),
        )
        await db.commit()


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
        "reaction_pool",
        "premium_guilds",
        "guild_departures",
        "channel_refeed_status",
        "guild_auto_refeed",
        "guild_counters",
    ]
    async with _db_lock:
        for table in tables:
            await db.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))
        await db.commit()
    log.info("purge_guild_data: guild %s purgado de %d tablas", guild_id, len(tables))


# ─── Storage limits ──────────────────────────────────────────────────────────


async def trim_corpus_if_needed(guild_id: int, channel_id: int) -> None:
    """Recorta corpus_messages al límite configurado, por canal (no por guild):
    un canal con mucho historial no debe desplazar el corpus de otros canales
    del mismo guild."""
    max_msgs = _limit_for_guild(
        guild_id,
        "MAX_CORPUS_MESSAGES_PER_GUILD_FREE",
        "MAX_CORPUS_MESSAGES_PER_GUILD_PREMIUM",
        15_000,
        50_000,
    )
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
    cap = _limit_for_guild(
        guild_id,
        "MAX_CORPUS_MESSAGES_PER_GUILD_TOTAL_FREE",
        "MAX_CORPUS_MESSAGES_PER_GUILD_TOTAL_PREMIUM",
        150_000,
        500_000,
    )
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
