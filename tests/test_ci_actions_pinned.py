"""Las GitHub Actions de ci.yml tienen que estar pineadas a un SHA de commit,
no a un tag mutable (@v4, @main): si la cuenta que publica la action se
compromete, un tag mutable ejecutaría el código nuevo en el próximo run sin
que nadie en este repo haya tocado una línea."""

import re
from pathlib import Path

CI = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
).read_text("utf-8")

_USES_RE = re.compile(r"^\s*uses:\s*(\S+)@(\S+)", re.MULTILINE)


def test_todas_las_actions_estan_pineadas_a_un_sha():
    usos = _USES_RE.findall(CI)
    assert usos, "no se encontró ningún 'uses:' en ci.yml"
    for action, ref in usos:
        assert re.fullmatch(r"[0-9a-f]{40}", ref), (
            f"{action}@{ref} no está pineado a un SHA de commit"
        )
