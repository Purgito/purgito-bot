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
        'case "$last" in\n'
        + "".join(f"  {p}) echo {d};;\n" for p, (d, _) in chains.items())
        + "  *) echo /dev/plain;;\nesac\n"
    )
    (b / "lsblk").write_text(
        '#!/bin/bash\nfor a in "$@"; do last="$a"; done\n'
        'case "$last" in\n'
        + "".join(
            f'  {d}) echo "{c}";;\n'
            for d, c in {v[0]: v[1] for v in chains.values()}.items()
        )
        + '  *) printf "disk\\npart\\n";;\nesac\n'
    )
    (b / "swapon").write_text("#!/bin/bash\nexit 0\n")
    (b / "systemd-analyze").write_text("#!/bin/bash\necho Storage=volatile\n")
    (b / "systemctl").write_text(
        "#!/bin/bash\necho Environment=TMPDIR=/srv/vault-tmp\n"
    )
    for f in b.iterdir():
        f.chmod(0o755)
    return b


def _run(tmp_path, chains):
    bot = tmp_path / "bot"
    bot.mkdir()
    (bot / ".env").write_text("X=1\n")
    env = {
        **os.environ,
        "PATH": f"{_fake_bin(tmp_path, chains)}:{os.environ['PATH']}",
        "BOT_DIR": str(bot),
        "PGDATA": str(tmp_path),
        "CHECK_ROOT_OPTIONAL": "1",
        "CHECK_JOURNAL_DIR": str(tmp_path / "sin-journal"),
        "PV_KEYFILE": str(tmp_path / "sin-clave"),
        "PV_IMG": str(tmp_path / "sin-imagen"),
        "HOME": str(tmp_path / "home"),
    }
    (tmp_path / "home" / "purgito-bot-backups").mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env
    )


def test_todo_en_claro_sale_con_error_y_dice_que_el_p0_sigue_abierto(tmp_path):
    p = _run(tmp_path, {})
    assert p.returncode == 1
    assert "EN CLARO" in p.stdout and "ABIERTO" in p.stdout


def test_si_las_rutas_estan_sobre_dm_crypt_sale_bien(tmp_path):
    c = ("/dev/mapper/datos", "crypt part disk")
    paths = [
        str(tmp_path),
        str(tmp_path / "bot" / ".env"),
        str(tmp_path / "bot" / "data"),
        "/etc/purgito",
        "/etc/cloudflared",
        "/var/backups/purgito",
        "/var/log/postgresql",
        "/srv/vault-tmp",
        str(tmp_path / "home" / "purgito-bot-backups"),
    ]
    p = _run(tmp_path, {x: c for x in paths})
    assert "EN CLARO" not in p.stdout, p.stdout
    assert (
        p.returncode == 0
        and "todo lo comprobado está en dispositivos cifrados" in p.stdout
    )


def test_una_clave_provisional_o_un_journal_persistente_impiden_el_cierre(tmp_path):
    c = ("/dev/mapper/datos", "crypt part disk")
    paths = [
        str(tmp_path),
        str(tmp_path / "bot" / ".env"),
        str(tmp_path / "bot" / "data"),
        "/etc/purgito",
        "/etc/cloudflared",
        "/var/backups/purgito",
        "/var/log/postgresql",
        "/srv/vault-tmp",
        str(tmp_path / "home" / "purgito-bot-backups"),
    ]
    (tmp_path / "sin-clave").write_text("k")  # la clave provisional sigue en el disco
    p = _run(tmp_path, {x: c for x in paths})
    assert p.returncode == 1 and "PROVISIONAL" in p.stdout and "ABIERTO" in p.stdout
