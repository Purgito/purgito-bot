"""deploy/security_check.sh: exposición de puertos, permisos, backups cifrados y
clave privada de age fuera del servidor. Se alimenta con salida de `ss` y
carpetas de mentira (sin tocar el servidor real)."""

import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "security_check.sh"

SS_BIEN = """Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port
tcp   LISTEN 0      128        127.0.0.1:5432      0.0.0.0:*
tcp   LISTEN 0      128        127.0.0.1:8080      0.0.0.0:*
tcp   LISTEN 0      128          0.0.0.0:22        0.0.0.0:*
tcp   LISTEN 0      511          0.0.0.0:80        0.0.0.0:*
tcp   LISTEN 0      128            [::1]:5432         [::]:*
"""


@pytest.fixture
def entorno(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BACKUP_AGE_RECIPIENTS=age1" + "q" * 58 + "\n")
    env_file.chmod(0o600)
    backups = tmp_path / "backups"
    backups.mkdir(mode=0o700)
    backups.chmod(0o700)
    (backups / "purgito-20261002-000000.dump.age").write_bytes(
        b"age-encryption.org/v1\n"
    )
    (backups / "purgito-20261002-000000.dump.age").chmod(0o600)
    home = tmp_path / "home"
    home.mkdir()
    return dict(tmp=tmp_path, env=env_file, backups=backups, home=home)


def correr(e, ss=SS_BIEN):
    env = {
        **os.environ,
        "SS_OUTPUT": ss,
        "ENV_FILE": str(e["env"]),
        "BACKUP_DIR": str(e["backups"]),
        "SEARCH_HOME": str(e["home"]),
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30
    )


def test_todo_bien(entorno):
    p = correr(entorno)
    assert p.returncode == 0, p.stdout
    assert "TODO OK" in p.stdout


@pytest.mark.parametrize(
    "linea",
    [
        "tcp LISTEN 0 128 0.0.0.0:5432 0.0.0.0:*",
        "tcp LISTEN 0 128 *:5432 *:*",
        "tcp LISTEN 0 128 [::]:5432 [::]:*",
        "tcp LISTEN 0 128 10.203.0.2:8080 0.0.0.0:*",
        "tcp LISTEN 0 128 100.95.142.27:5432 0.0.0.0:*",
    ],
)
def test_postgres_o_api_expuestos_fallan(entorno, linea):
    p = correr(entorno, SS_BIEN + linea + "\n")
    assert p.returncode == 1
    assert "FAIL  puerto(s) interno(s) expuesto(s)" in p.stdout


def test_otros_puertos_publicos_no_son_un_fallo(entorno):
    # 22 y 80 públicos (nginx/ssh) no los juzga este chequeo
    assert correr(entorno).returncode == 0


def test_env_con_permisos_de_mas_falla(entorno):
    entorno["env"].chmod(0o644)
    p = correr(entorno)
    assert p.returncode == 1 and ".env tiene permisos 644" in p.stdout


def test_backup_dir_abierto_o_con_archivos_legibles_falla(entorno):
    entorno["backups"].chmod(0o755)
    assert "BACKUP_DIR tiene permisos 755" in correr(entorno).stdout
    entorno["backups"].chmod(0o700)
    (entorno["backups"] / "purgito-x.dump.age").write_bytes(b"x")
    (entorno["backups"] / "purgito-x.dump.age").chmod(0o644)
    p = correr(entorno)
    assert p.returncode == 1 and "permisos de más" in p.stdout


def test_un_dump_en_claro_falla(entorno):
    d = entorno["backups"] / "purgito-20261001-000000.dump"
    d.write_bytes(b"PGDMP")
    d.chmod(0o600)
    p = correr(entorno)
    assert p.returncode == 1 and "sin cifrar" in p.stdout


def test_clave_privada_age_en_el_servidor_falla(entorno):
    (entorno["home"] / "k.txt").write_text("AGE-SECRET-KEY-1" + "A" * 58 + "\n")
    p = correr(entorno)
    assert p.returncode == 1 and "clave privada age en el servidor" in p.stdout
    assert "AAAAAAAA" not in p.stdout  # nunca imprime la clave


def test_la_clave_publica_no_cuenta_como_privada(entorno):
    (entorno["home"] / "pub.txt").write_text("age1" + "q" * 58 + "\n")
    assert correr(entorno).returncode == 0


def test_sin_destinatarios_falla(entorno):
    entorno["env"].write_text("DATABASE_URL=x\n")
    entorno["env"].chmod(0o600)
    p = correr(entorno)
    assert p.returncode == 1 and "falta BACKUP_AGE_RECIPIENTS" in p.stdout
