"""Configuración central: variables de entorno y constantes compartidas.

Todos los módulos leen la config desde aquí en vez de hacer os.getenv disperso.
load_env_files() se ejecuta al importar este módulo, así que basta con importar
config antes que cualquier otro módulo propio.
"""

import logging
import os
from zoneinfo import ZoneInfo

from dotenv import dotenv_values, load_dotenv

log = logging.getLogger(__name__)

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Archivos versionados (no secretos). Mandan sobre .env y sobre el entorno del
# proceso: un valor duplicado por accidente en .env no puede ocultarlos.
_VERSIONED_ENV_FILES = ("limits.env", "urls.env")


def duplicated_env_names(root: str = _ROOT_DIR) -> dict[str, list[str]]:
    """Nombres (nunca valores) definidos en .env Y en limits.env / urls.env.

    Devuelve {nombre: [archivos versionados donde también está]}. Sirve para
    avisar al arrancar y para el chequeo de deploy/preflight_check.sh."""
    instance = set(dotenv_values(os.path.join(root, ".env")))
    dups: dict[str, list[str]] = {}
    for fname in _VERSIONED_ENV_FILES:
        for name in dotenv_values(os.path.join(root, fname)):
            if name in instance:
                dups.setdefault(name, []).append(fname)
    return dups


def load_env_files(root: str = _ROOT_DIR) -> None:
    """Carga la configuración. Precedencia (de menor a mayor):

    1. .env -- secretos y config de la instancia. No pisa variables ya
       presentes en el entorno del proceso (p. ej. las de systemd).
    2. limits.env y urls.env -- versionados, **autoritativos**: pisan lo que
       haya puesto .env (o el entorno) con el mismo nombre. Así editar
       limits.env + git pull + reiniciar siempre surte efecto.

    Ninguna variable de .env gana sobre los versionados: si hace falta una
    excepción por instancia, se edita el archivo versionado, no el .env."""
    load_dotenv(os.path.join(root, ".env"))
    for name, files in sorted(duplicated_env_names(root).items()):
        log.warning(
            "%s está en .env y en %s: manda el archivo versionado. Bórrala del .env.",
            name,
            " y ".join(files),
        )
    for fname in _VERSIONED_ENV_FILES:
        load_dotenv(os.path.join(root, fname), override=True)


load_env_files()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    return value if value > 0 else default


def _env_int_or_none(name: str) -> int | None:
    """Como env_int, pero sin default numérico: ausente, vacío (os.getenv
    devuelve "" en vez de aplicar un default) o no-numérico -> None sin excepción.
    "0" también resuelve a None (mismo sentinel de "sin valor" que ya usaba
    BOT_OWNER_ID antes de esta función)."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value or None


def _env_channel_id(name: str, default: int) -> int | None:
    """ID de canal con un default de producción. Ausente -> `default`; presente
    pero vacío o "0" -> None (la función asociada queda apagada, útil para una
    instancia de desarrollo que no debe escribir en el canal de producción)."""
    if os.getenv(name) is None:
        return default
    return _env_int_or_none(name)


def _env_compact(name: str) -> str:
    """Devuelve el valor sin espacios ni saltos.

    Útil para tokens/UUIDs copiados desde paneles que a veces meten espacios o
    saltos al pegarse en un .env."""
    return "".join((os.getenv(name) or "").split())


TOKEN = os.getenv("DISCORD_TOKEN")
ENABLE_MESSAGE_CONTENT = os.getenv(
    "ENABLE_MESSAGE_CONTENT", "true"
).strip().lower() in ("1", "true", "yes")
GUILD_ID_ENV = os.getenv("GUILD_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Sin estas dos, cogs/twitch.py se carga pero no arranca el chequeo periódico
# (feature desactivada, resto del bot funciona igual -- mismo criterio que GROQ_API_KEY).
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
# Default "purgito": el que documentan .env.example, /help y la landing
# ("purgito dl <link>"). Antes caía en "artemis", un nombre viejo que ninguna
# documentación menciona.
BOT_TRIGGER_NAME = (
    os.getenv("BOT_TRIGGER_NAME", "purgito").strip() or "purgito"
).lower()
BOT_OWNER_ID: int | None = _env_int_or_none("BOT_OWNER_ID")
# ID fijo del servidor original PURG4TORY — siempre premium, sin pasar por la tabla.
PURGATORY_GUILD_ID = 1434103563214393347
# Conjunto de IDs de servidores con premium permanente incondicional (no facturados por Polar).
PERMANENT_PREMIUM_GUILD_IDS: set[int] = {
    PURGATORY_GUILD_ID,
    1521362322331795487,
}
# Canal (tipo anuncio) donde Purgito avisa cuando arranca/se apaga (y cuando una
# tarea en segundo plano falla varias veces seguidas). Se puede sobreescribir
# con LIFECYCLE_ANNOUNCE_CHANNEL_ID en .env; vacío o "0" apaga los avisos -- así
# una instancia de desarrollo no escribe en el canal de producción.
LIFECYCLE_ANNOUNCE_CHANNEL_ID: int | None = _env_channel_id(
    "LIFECYCLE_ANNOUNCE_CHANNEL_ID", 1525941934043041822
)
# Canal oficial de Purgito donde se publican las actualizaciones del bot.
OFFICIAL_UPDATES_CHANNEL_ID = 1522754564971958453
# env_int: un WEB_PORT mal escrito ("abc", "") cae al default en vez de tumbar el
# import de config -- y con él el arranque entero, antes de que exista logging.
WEB_PORT = env_int("WEB_PORT", 8080)

REFEED_MAX_MESSAGES = env_int("REFEED_MAX_MESSAGES", 80_000)
REFEED_ALL_MAX_MESSAGES = env_int("REFEED_ALL_MAX_MESSAGES", 20_000)
# Cooldown de /refeed_channels por guild -- corto a propósito, ver el
# comentario junto a _check_refeed_channels_cooldown en cogs/chat.py.
REFEED_GUILD_COOLDOWN_SECONDS = env_int("REFEED_GUILD_COOLDOWN_SECONDS", 60)
MARKOV_TRAINING_MESSAGES = env_int("MARKOV_TRAINING_MESSAGES", 5_000)
USER_MARKOV_TRAINING_MESSAGES = env_int("USER_MARKOV_TRAINING_MESSAGES", 2_000)

SPECIAL_PHRASE_PROBABILITY = 0.05
SPECIAL_PHRASE_COOLDOWN = 40 * 60  # 40 minutos en segundos

GROQ_GUILD_COOLDOWN = 10.0

# [FALLBACK] Frecuencia de los mensajes espontáneos. Desde que existe la tab
# CHAT del dashboard esto se configura **por servidor** (columnas
# settings.auto_generate_every / auto_generate_probability, con los mismos
# valores como default). Estas constantes solo se usan si nadie pasa el
# parámetro a generation.note_message_for_auto_generate.
AUTO_GENERATE_EVERY = 15
AUTO_GENERATE_PROBABILITY = float(os.getenv("AUTO_GENERATE_PROBABILITY", "0.6"))

MEME_MAX_BYTES = 10 * 1024 * 1024
IMAGEFX_MAX_BYTES = 10 * 1024 * 1024

# Timezone para los anuncios programados en modo "hora fija" (cogs/anuncios.py).
ANNOUNCEMENTS_TIMEZONE = ZoneInfo(
    os.getenv("ANNOUNCEMENTS_TIMEZONE", "America/Santiago")
)

# --- Dashboard web (Discord OAuth2) ---
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://localhost:8080").rstrip(
    "/"
)
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
# URL pública del panel, mostrada en /help, /setup y /settings.
PANEL_URL = os.getenv("PANEL_URL", "https://purgito.app").rstrip("/")
# URL pública de la landing (purgito.app); destino del post-login con from=landing.
LANDING_URL = os.getenv("LANDING_URL", "https://purgito.app").rstrip("/")
# Dominio para compartir la cookie de sesión entre subdominios (landing + panel).
# Vacío (None) = cookie atada solo al host del panel, comportamiento clásico.
SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", "").strip() or None
# Orígenes de la landing que pueden hacer requests autenticadas (con cookies)
# al panel; separados por coma. Vacío = solo DASHBOARD_BASE_URL, como siempre.
LANDING_ORIGINS = frozenset(
    o.strip().rstrip("/")
    for o in os.getenv("LANDING_ORIGINS", "").split(",")
    if o.strip()
)
# Links del navbar/footer del panel (rediseño dashboard/perfil). Configurables
# en urls.env; los defaults apuntan a destinos que existen hoy.
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://purgito.app").rstrip("/")
DOCS_URL = os.getenv("DOCS_URL", "https://purgito.app/es/documentacion").rstrip("/")
REPO_URL = os.getenv("REPO_URL", "https://github.com/Purgito/purgito-bot").rstrip("/")

# --- Polar.sh (compra de premium) ---
POLAR_ACCESS_TOKEN = _env_compact("POLAR_ACCESS_TOKEN")
POLAR_WEBHOOK_SECRET = _env_compact("POLAR_WEBHOOK_SECRET")
POLAR_SERVER = os.getenv("POLAR_SERVER", "sandbox").strip().lower() or "sandbox"
POLAR_PRODUCT_ID_MONTHLY = _env_compact("POLAR_PRODUCT_ID_MONTHLY")
POLAR_PRODUCT_ID_ANNUAL = _env_compact("POLAR_PRODUCT_ID_ANNUAL")


def get_invite_url(guild_id: str) -> str:
    """URL para invitar al bot a un guild concreto, con permisos mínimos calculados."""
    return (
        "https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        # 414539926592 + view_audit_log (1 << 7): necesario para identificar
        # quién invitó al bot (DM de bienvenida al admin).
        "&permissions=414539926720"
        "&scope=bot%20applications.commands"
        f"&guild_id={guild_id}"
        "&disable_guild_select=true"
    )


def get_dashboard_url(guild_id, locale: str = "es", path: str = "") -> str:
    """URL al dashboard de un servidor puntual.

    Necesita el prefijo de idioma: la URL sin locale da 404 en producción
    (el sitio no redirige del lado del cliente como se asumía antes).
    Default "es" porque `READY_LANGS` solo tiene ese idioma por ahora — cada
    call site debería pasar el locale real del guild si lo tiene a mano.

    `path` deep-linkea a un tab/subtab puntual, ej. "chat#canales" — se pega
    tal cual detrás del id de guild, con la barra intermedia puesta acá.
    """
    base = f"{PANEL_URL}/{locale}/dashboard/{guild_id}"
    return f"{base}/{path}" if path else base


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes")


# Largo mínimo recomendado de SESSION_SECRET: la clave Fernet de la cookie de
# sesión sale de sha256(SESSION_SECRET), así que un secreto corto y adivinable
# deja forjar una sesión de cualquier usuario. `token_hex(32)` (el comando de
# .env.example) da 64 caracteres.
MIN_SESSION_KEY_LENGTH = 32


def session_secret_is_weak(secret: str) -> bool:
    return 0 < len(secret) < MIN_SESSION_KEY_LENGTH


if session_secret_is_weak(SESSION_SECRET):
    # Solo avisa, no apaga el dashboard: cortar el login de todos en un deploy
    # por un secreto "corto pero funcional" sería peor que el aviso. Rotarlo
    # desloguea a todos una vez (ver docs/RUNBOOK.md § 3).
    log.warning(
        "SESSION_SECRET tiene menos de %d caracteres: genera uno nuevo con "
        'python3 -c "import secrets; print(secrets.token_hex(32))"',
        MIN_SESSION_KEY_LENGTH,
    )

# Por defecto se habilita si hay SESSION_SECRET; se puede forzar off sin borrar el resto.
DASHBOARD_ENABLED = _env_bool("DASHBOARD_ENABLED", bool(SESSION_SECRET))

if DASHBOARD_ENABLED:
    _missing = [
        name
        for name, val in (
            ("DISCORD_CLIENT_ID", DISCORD_CLIENT_ID),
            ("DISCORD_CLIENT_SECRET", DISCORD_CLIENT_SECRET),
            ("SESSION_SECRET", SESSION_SECRET),
        )
        if not val
    ]
    if _missing:
        log.warning(
            "Dashboard deshabilitado: faltan variables obligatorias %s. "
            "Setealas en .env o pon DASHBOARD_ENABLED=false para silenciar este aviso.",
            ", ".join(_missing),
        )
        DASHBOARD_ENABLED = False
