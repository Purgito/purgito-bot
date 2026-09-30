"""Endurecimiento de configuración y permisos de archivos:

- SESSION_SECRET corto: aviso al arrancar (no apaga el dashboard).
- WEB_PORT inválido cae al default en vez de tumbar el import de config.
- BOT_TRIGGER_NAME: el default es "purgito" (el que documenta todo lo demás).
- LIFECYCLE_ANNOUNCE_CHANNEL_ID: se puede sobreescribir o apagar por .env.
- bot.db y los sidecars de WAL se dejan en 0600; el unit de systemd fija
  UMask=0077 para que bot.db y bot.log nazcan así.

config.py lee el entorno al importarse, así que lo que depende de eso se
prueba en un subproceso limpio en vez de recargar el módulo dentro de pytest
(otros módulos ya tienen referencias a sus valores)."""

import asyncio
import os
import pathlib
import stat
import subprocess
import sys

import pytest

import config
import db

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
        "LIFECYCLE_ANNOUNCE_CHANNEL_ID": "__ausente__",
        **env_extra,
    }
    if env["LIFECYCLE_ANNOUNCE_CHANNEL_ID"] == "__ausente__":
        del env["LIFECYCLE_ANNOUNCE_CHANNEL_ID"]
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


# ── WEB_PORT / BOT_TRIGGER_NAME / canal de lifecycle ─────────────────────────


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


def test_lifecycle_channel_sin_definir_usa_el_de_produccion():
    r = _config_en_subproceso(
        {"LIFECYCLE_ANNOUNCE_CHANNEL_ID": "__ausente__"},
        "config.LIFECYCLE_ANNOUNCE_CHANNEL_ID",
    )
    assert r.stdout.strip() == "1525941934043041822"


@pytest.mark.parametrize("valor, esperado", [("", "None"), ("0", "None"), ("77", "77")])
def test_lifecycle_channel_se_puede_apagar_o_cambiar(valor, esperado):
    r = _config_en_subproceso(
        {"LIFECYCLE_ANNOUNCE_CHANNEL_ID": valor},
        "config.LIFECYCLE_ANNOUNCE_CHANNEL_ID",
    )
    assert r.stdout.strip() == esperado


def test_aviso_de_lifecycle_no_hace_nada_si_esta_apagado(monkeypatch):
    import bot as bot_mod

    class _BotQueNoDebeTocarse:
        def get_channel(self, _id):
            raise AssertionError("no debía buscar ningún canal")

    monkeypatch.setattr(config, "LIFECYCLE_ANNOUNCE_CHANNEL_ID", None)
    monkeypatch.setattr(bot_mod, "bot", _BotQueNoDebeTocarse())
    asyncio.run(bot_mod._send_lifecycle_notice("hola"))


# ── Permisos de archivos ─────────────────────────────────────────────────────

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="permisos POSIX")


def _modo(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@posix_only
def test_restrict_db_permissions_cierra_db_y_sidecars(tmp_path, monkeypatch):
    base = tmp_path / "bot.db"
    monkeypatch.setattr(db, "DB_PATH", str(base))
    for sufijo in ("", "-wal", "-shm"):
        (tmp_path / f"bot.db{sufijo}").write_text("x")
        os.chmod(tmp_path / f"bot.db{sufijo}", 0o644)

    db._restrict_db_permissions()

    for sufijo in ("", "-wal", "-shm"):
        assert _modo(tmp_path / f"bot.db{sufijo}") == 0o600


@posix_only
def test_restrict_db_permissions_no_falla_si_no_hay_sidecars(tmp_path, monkeypatch):
    (tmp_path / "bot.db").write_text("x")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "bot.db"))
    db._restrict_db_permissions()  # no hay -wal ni -shm: no debe levantar
    assert _modo(tmp_path / "bot.db") == 0o600


@posix_only
def test_init_db_deja_la_base_en_0600(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    # Base preexistente con permisos abiertos, como la de producción hoy.
    (tmp_path / "test.db").write_bytes(b"")
    os.chmod(tmp_path / "test.db", 0o644)

    async def run():
        await db.init_db()
        await db.close_db()

    asyncio.run(run())
    assert _modo(tmp_path / "test.db") == 0o600


def test_el_unit_de_systemd_fija_umask_restrictiva():
    unit = (_ROOT / "deploy" / "bot-purg.service.template").read_text()
    assert "UMask=0077" in unit
