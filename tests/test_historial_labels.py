"""Toda acción que se audita tiene que tener texto legible en HISTORIAL.

`ACTION_LABELS` en `landing/js/tabs/historial.js` traduce el `action` que graba
`db.log_audit` a una frase. El fallback muestra el slug crudo, así que olvidarse
de una entrada no rompe nada visible en los tests -- solo deja al admin leyendo
`corpus.amnesia` en el historial. Doce acciones se habían acumulado así,
incluida la más destructiva del dashboard.

Este test cierra el agujero: agregar un `_log_audit(...)` nuevo sin su etiqueta
falla acá.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORIAL_JS = ROOT / "landing" / "js" / "tabs" / "historial.js"
WEBAPI_PY = ROOT / "src" / "webapi.py"
DB_PY = ROOT / "src" / "db.py"


def _acciones_etiquetadas() -> set[str]:
    texto = HISTORIAL_JS.read_text(encoding="utf-8")
    bloque = re.search(r"ACTION_LABELS = \{(.*?)\n\};", texto, re.S)
    assert bloque, "no se encontró ACTION_LABELS en historial.js"
    return set(re.findall(r"'([a-z_]+\.[a-z_]+)':", bloque.group(1)))


def _acciones_auditadas() -> set[str]:
    """Los strings de acción que se pasan a _log_audit/log_audit.

    Se leen del código en vez de mantener una lista acá: una copia se
    desincronizaría al primer cambio, que es justo lo que hay que detectar.
    Un `action` no literal (armado en runtime) no lo veríamos -- hoy no hay
    ninguno, y si aparece este test no es el lugar donde se nota.
    """
    acciones: set[str] = set()
    for archivo in (WEBAPI_PY, DB_PY):
        texto = archivo.read_text(encoding="utf-8")
        for llamada in re.findall(r"_log_audit\((.*?)\n    \)", texto, re.S):
            acciones.update(re.findall(r'"([a-z_]+\.[a-z_]+)"', llamada))
        for llamada in re.findall(r"log_audit\((.*?)\)", texto, re.S):
            acciones.update(re.findall(r'"([a-z_]+\.[a-z_]+)"', llamada))
    return acciones


def test_toda_accion_auditada_tiene_etiqueta_en_historial():
    auditadas = _acciones_auditadas()
    # Sanity check del parseo: si la regex deja de matchear, el test se
    # volvería verde por vacío en vez de por correcto.
    assert len(auditadas) > 30, f"el parseo encontró solo {len(auditadas)} acciones"

    faltantes = sorted(auditadas - _acciones_etiquetadas())
    assert not faltantes, (
        "estas acciones se auditan pero HISTORIAL las mostraría como slug crudo: "
        + ", ".join(faltantes)
    )


def test_no_hay_etiquetas_para_acciones_que_ya_no_existen():
    """Al revés: una etiqueta huérfana es código muerto que confunde al leer."""
    huerfanas = sorted(_acciones_etiquetadas() - _acciones_auditadas())
    assert not huerfanas, (
        "estas etiquetas de HISTORIAL no corresponden a ninguna acción auditada: "
        + ", ".join(huerfanas)
    )
