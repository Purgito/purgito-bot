"""La pestaña PREMIUM del dashboard no puede prometer un límite que no existe.

`landing/js/tabs/premium.js` hardcodea la tabla comparativa Free/Premium y el
recibo de "Premium activo". Los límites reales viven en `limits.env` y los lee
`db._limit_for_guild` -- son dos copias sin nada que las ate, y ya driftearon
una vez: la tabla decía 5.000/20.000 mensajes de usuario cuando el límite real
era 2.000/8.000, o sea que la página de compra ofrecía 2,5x lo que entregaba.

Esto es una página de pago: un número inflado acá no es un detalle cosmético.
El test compara las dos copias en vez de re-hardcodear los valores esperados,
así seguir a limits.env es lo único que lo mantiene verde.
"""

import re
from pathlib import Path

import config  # noqa: F401  -- importarlo carga limits.env en os.environ
import db

ROOT = Path(__file__).resolve().parents[1]
PREMIUM_JS = ROOT / "landing" / "js" / "tabs" / "premium.js"

# Etiqueta de la fila en premiumRows -> (env del plan free, env del premium).
# "Memes automáticos programados" queda afuera a propósito: es la única fila
# que no es numérica ("No disponible"/"Disponible").
FILAS = {
    "Mensajes guardados en memoria (corpus)": (
        "MAX_CORPUS_MESSAGES_PER_GUILD_FREE",
        "MAX_CORPUS_MESSAGES_PER_GUILD_PREMIUM",
    ),
    "Mensajes de usuario en memoria": (
        "MAX_USER_CORPUS_MESSAGES_PER_GUILD_FREE",
        "MAX_USER_CORPUS_MESSAGES_PER_GUILD_PREMIUM",
    ),
    "GIFs guardados": ("MAX_GIFS_PER_GUILD_FREE", "MAX_GIFS_PER_GUILD_PREMIUM"),
    "Imágenes en la colección de memes": (
        "MAX_IMAGES_PER_GUILD_FREE",
        "MAX_IMAGES_PER_GUILD_PREMIUM",
    ),
    "Plantillas de embeds guardadas": (
        "MAX_EMBED_TEMPLATES_PER_GUILD_FREE",
        "MAX_EMBED_TEMPLATES_PER_GUILD_PREMIUM",
    ),
}


def _es(n: int) -> str:
    """15000 -> '15.000': el punto como separador de miles, como está escrito
    en la tabla (y en landing/pages/premium.html)."""
    return f"{n:,}".replace(",", ".")


def _filas_del_js() -> dict[str, tuple[str, str]]:
    """Etiqueta -> (free, premium) tal como están escritos en premiumRows."""
    texto = PREMIUM_JS.read_text(encoding="utf-8")
    bloque = re.search(r"premiumRows = \[(.*?)\n    \];", texto, re.S)
    assert bloque, "no se encontró premiumRows en premium.js"
    filas = re.findall(r"\['([^']+)', '([^']+)', '([^']+)'\]", bloque.group(1))
    assert filas, "premiumRows quedó vacío o cambió de forma"
    return {etiqueta: (free, prem) for etiqueta, free, prem in filas}


def test_la_tabla_comparativa_coincide_con_limits_env():
    filas = _filas_del_js()
    for etiqueta, (free_env, premium_env) in FILAS.items():
        assert etiqueta in filas, f"desapareció la fila '{etiqueta}' de premiumRows"
        free_js, premium_js = filas[etiqueta]
        free_real = db._env_int(free_env, -1)
        premium_real = db._env_int(premium_env, -1)
        assert free_js == _es(free_real), (
            f"'{etiqueta}' (Free): la tabla dice {free_js} y {free_env} vale {free_real}"
        )
        assert premium_js == _es(premium_real), (
            f"'{etiqueta}' (Premium): la tabla dice {premium_js} "
            f"y {premium_env} vale {premium_real}"
        )


def test_el_recibo_de_premium_activo_no_promete_de_mas():
    """El recibo repite los mismos topes en prosa; es la otra mitad que
    drifteó la vez pasada, así que también tiene que seguir a limits.env."""
    texto = PREMIUM_JS.read_text(encoding="utf-8")
    recibo = re.search(r"premium-receipt'.*?\)\)\)\);", texto, re.S)
    assert recibo, "no se encontró la lista premium-receipt en premium.js"
    for _, premium_env in FILAS.values():
        esperado = _es(db._env_int(premium_env, -1))
        assert esperado in recibo.group(0), (
            f"el recibo de Premium activo no menciona {esperado} "
            f"({premium_env}) — ¿quedó un número viejo?"
        )
