"""deploy/check_encryption_at_rest.sh: distingue dispositivos cifrados de en claro (con lsblk/findmnt simulados)."""

import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "check_encryption_at_rest.sh"


def _fake_bin(tmp_path, chains):
    """findmnt devuelve el 'dispositivo' que pide el mapa; lsblk, su cadena de capas."""
    b = tmp_path / "bin"
    b.mkdir()
    (b / "findmnt").write_text(
        '#!/bin/bash\nfor a in "$@"; do last="$a"; done\n'
        'case "$last" in\n' + "".join(f'  {p}) echo {d};;\n' for p, (d, _) in chains.items()) + "  *) echo /dev/plain;;\nesac\n"
    )
    (b / "lsblk").write_text(
        '#!/bin/bash\nfor a in "$@"; do last="$a"; done\n'
        'case "$last" in\n' + "".join(f'  {d}) echo "{c}";;\n' for d, c in {v[0]: v[1] for v in chains.values()}.items()) + '  *) printf "disk\\npart\\n";;\nesac\n'
    )
    (b / "swapon").write_text("#!/bin/bash\nexit 0\n")
    for f in b.iterdir():
        f.chmod(0o755)
    return b


def _run(tmp_path, chains):
    bot = tmp_path / "bot"
    bot.mkdir()
    (bot / ".env").write_text("X=1\n")
    env = {**os.environ, "PATH": f"{_fake_bin(tmp_path, chains)}:{os.environ['PATH']}", "BOT_DIR": str(bot), "PGDATA": str(tmp_path)}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)


def test_todo_en_claro_sale_con_error_y_dice_que_el_p0_sigue_abierto(tmp_path):
    p = _run(tmp_path, {})
    assert p.returncode == 1
    assert "EN CLARO" in p.stdout and "ABIERTO" in p.stdout


def test_si_las_rutas_estan_sobre_dm_crypt_sale_bien(tmp_path):
    cripto = (
        {str(tmp_path): ("/dev/mapper/datos", "crypt part disk")}
        | {str(tmp_path / "bot" / ".env"): ("/dev/mapper/datos", "crypt part disk")}
        | {"/etc/purgito": ("/dev/mapper/datos", "crypt part disk")}
        | {"/var/backups/purgito": ("/dev/mapper/datos", "crypt part disk")}
        | {"/": ("/dev/mapper/datos", "crypt part disk")}
    )
    p = _run(tmp_path, cripto)
    assert "EN CLARO" not in p.stdout, p.stdout
    assert p.returncode == 0 and "todo lo comprobado está en dispositivos cifrados" in p.stdout
