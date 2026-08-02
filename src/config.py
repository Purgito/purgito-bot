"""Configuración central: variables de entorno y constantes compartidas.

Todos los módulos leen la config desde aquí en vez de hacer os.getenv disperso.
load_dotenv() se ejecuta al importar este módulo, así que basta con importar
config antes que cualquier otro módulo propio.
"""

import logging
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # .env: secretos y credenciales (token, API keys, DB, R2, Polar, etc.)

# limits.env: límites de almacenamiento no sensibles, versionado en git aparte del .env.
_LIMITS_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "limits.env"
)
load_dotenv(dotenv_path=_LIMITS_ENV_PATH)

# urls.env: URLs/dominios públicos no sensibles, versionado en git aparte del .env.
# Mismo criterio que limits.env: no son secretos, cambian solo al migrar dominio.
_URLS_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "urls.env"
)
load_dotenv(dotenv_path=_URLS_ENV_PATH)

log = logging.getLogger(__name__)


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
BOT_TRIGGER_NAME = os.getenv("BOT_TRIGGER_NAME", "artemis").strip().lower()
BOT_OWNER_ID: int | None = _env_int_or_none("BOT_OWNER_ID")
# ID fijo del servidor original PURG4TORY — siempre premium, sin pasar por la tabla.
PURGATORY_GUILD_ID = 1434103563214393347
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

REFEED_MAX_MESSAGES = env_int("REFEED_MAX_MESSAGES", 80_000)
REFEED_ALL_MAX_MESSAGES = env_int("REFEED_ALL_MAX_MESSAGES", 20_000)
MARKOV_TRAINING_MESSAGES = env_int("MARKOV_TRAINING_MESSAGES", 5_000)
USER_MARKOV_TRAINING_MESSAGES = env_int("USER_MARKOV_TRAINING_MESSAGES", 2_000)

SPECIAL_PHRASE_PROBABILITY = 0.05
SPECIAL_PHRASE_COOLDOWN = 40 * 60  # 40 minutos en segundos

GROQ_GUILD_COOLDOWN = 10.0

# El bot considera generar un mensaje espontáneo cada AUTO_GENERATE_EVERY
# inserts al corpus de un canal; AUTO_GENERATE_PROBABILITY es el azar extra
# para que no sea puramente determinístico por conteo.
AUTO_GENERATE_EVERY = 15
AUTO_GENERATE_PROBABILITY = float(os.getenv("AUTO_GENERATE_PROBABILITY", "0.6"))

MEME_MAX_BYTES = 10 * 1024 * 1024

# Timezone para los anuncios programados en modo "hora fija" (cogs/anuncios.py).
ANNOUNCEMENTS_TIMEZONE = ZoneInfo(os.getenv("ANNOUNCEMENTS_TIMEZONE", "America/Santiago"))

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
    o.strip().rstrip("/") for o in os.getenv("LANDING_ORIGINS", "").split(",") if o.strip()
)
# Links del navbar/footer del panel (rediseño dashboard/perfil). Configurables
# en urls.env; los defaults apuntan a destinos que existen hoy.
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://purgito.app").rstrip("/")
DOCS_URL = os.getenv("DOCS_URL", "https://purgito.app/docs").rstrip("/")
REPO_URL = os.getenv("REPO_URL", "https://github.com/punkyyy01/bot-discord-purg").rstrip("/")

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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes")


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
