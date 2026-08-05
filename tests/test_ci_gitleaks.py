"""El escaneo de secretos en CI (.github/workflows/ci.yml + .gitleaks.toml)
no tiene forma de correrse en pytest (necesita el binario de gitleaks y el
historial de git completo), así que estos tests solo verifican que la config
está bien armada: el job existe con lo que gitleaks-action necesita para
escanear todo el historial, y la excepción de referencias/ es un TOML válido
que de verdad cubre el archivo que la motivó (ver CLAUDE.md sobre esa
carpeta).
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")


def test_el_job_de_gitleaks_existe_y_escanea_todo_el_historial():
    assert "gitleaks/gitleaks-action" in CI
    assert "fetch-depth: 0" in CI
    assert "GITLEAKS_CONFIG: .gitleaks.toml" in CI


def test_gitleaksconfig_es_toml_valido_y_extiende_el_default():
    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text("utf-8"))
    assert config["extend"]["useDefault"] is True


def test_la_excepcion_de_referencias_cubre_el_archivo_que_la_motivo():
    """referencias/ quedó en el historial de git (commit 200a080) antes de
    ignorarse; sin esta excepción, gitleaks lo va a marcar en cada corrida
    por un guild ID que la regla discord-client-id confunde con un secreto."""
    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text("utf-8"))
    paths = config["allowlist"]["paths"]
    assert any(re.match(p, "referencias/repomix-wamellow-web.xml") for p in paths), (
        paths
    )
