"""Endurecimiento de configuración y permisos de archivos:

- SESSION_SECRET corto: aviso al arrancar (no apaga el dashboard).
- WEB_PORT inválido cae al default en vez de tumbar el import de config.
- BOT_TRIGGER_NAME: el default es "purgito" (el que documenta todo lo demás).
- bot.db y los sidecars de WAL se dejan en 0600; el unit de systemd fija
  UMask=0077 para que bot.db y bot.log nazcan así.

config.py lee el entorno al importarse, así que lo que depende de eso se
prueba en un subproceso limpio en vez de recargar el módulo dentro de pytest
(otros módulos ya tienen referencias a sus valores)."""

import os
import pathlib
import subprocess
import sys

import pytest

import config

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _config_en_subproceso(env_extra: dict, expr: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(_ROOT / "src"),
        # Valores neutros para que un .env local no contamine el resultado.
        "SESSION_SECRET": "",
        "DISCORD_CLIENT_ID": "",
        "DISCORD_CLIENT_SECRET": "",
        "BOT_TRIGGER_NAME": "",
        "WEB_PORT": "",
        **env_extra,
    }
    return subprocess.run(
        [sys.executable, "-c", f"import config; print({expr})"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_ROOT),
        timeout=60,
    )


# ── SESSION_SECRET ───────────────────────────────────────────────────────────


def test_session_secret_is_weak():
    assert not config.session_secret_is_weak("")  # sin secreto ya lo cubre _missing
    assert config.session_secret_is_weak("abc")
    assert config.session_secret_is_weak("a" * 31)
    assert not config.session_secret_is_weak("a" * 32)
    assert not config.session_secret_is_weak("a" * 64)


def test_secreto_corto_avisa_al_arrancar_pero_no_apaga_el_dashboard():
    r = _config_en_subproceso(
        {
            "SESSION_SECRET": "corto",
            "DISCORD_CLIENT_ID": "1",
            "DISCORD_CLIENT_SECRET": "x",
        },
        "config.DASHBOARD_ENABLED",
    )
    assert r.returncode == 0, r.stderr
    assert "SESSION_SECRET tiene menos de 32" in r.stderr
    assert r.stdout.strip() == "True"


def test_secreto_largo_no_avisa():
    r = _config_en_subproceso(
        {
            "SESSION_SECRET": "a" * 64,
            "DISCORD_CLIENT_ID": "1",
            "DISCORD_CLIENT_SECRET": "x",
        },
        "config.DASHBOARD_ENABLED",
    )
    assert r.returncode == 0, r.stderr
    assert "menos de 32" not in r.stderr


# ── WEB_PORT / BOT_TRIGGER_NAME ─────────────────────────


@pytest.mark.parametrize("valor", ["abc", "", "0", "-5", "80.5"])
def test_web_port_invalido_cae_al_default(valor):
    r = _config_en_subproceso({"WEB_PORT": valor}, "config.WEB_PORT")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "8080"


def test_web_port_valido_se_respeta():
    r = _config_en_subproceso({"WEB_PORT": "9090"}, "config.WEB_PORT")
    assert r.stdout.strip() == "9090"


def test_trigger_name_vacio_usa_purgito():
    r = _config_en_subproceso({"BOT_TRIGGER_NAME": ""}, "config.BOT_TRIGGER_NAME")
    assert r.stdout.strip() == "purgito"


def test_trigger_name_se_normaliza():
    r = _config_en_subproceso(
        {"BOT_TRIGGER_NAME": "  Artemis "}, "config.BOT_TRIGGER_NAME"
    )
    assert r.stdout.strip() == "artemis"


# ── Permisos de archivos ─────────────────────────────────────────────────────

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="permisos POSIX")


def test_el_unit_de_systemd_fija_umask_restrictiva():
    unit = (_ROOT / "deploy" / "bot-purg.service.template").read_text()
    assert "UMask=0077" in unit
