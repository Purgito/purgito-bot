"""Aislamiento de las credenciales de backups respecto al bot.

El bot carga el .env entero en su entorno y su usuario puede leerlo: las credenciales de
backups no van ahí. Van a /etc/purgito/backup.env (root:root 0600, lo lee solo systemd) y
las usa un runner con usuario propio y código de root. Estas pruebas cubren los scripts que
escriben los secretos (sin mostrarlos), el runner y que el bot no tiene forma de pedirlos.
"""

import importlib.util
import os
import pathlib
import shutil
import subprocess

import pytest
from fake_s3 import FakeS3

import r2

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUCKET, IMG, GIF = "purgito-backups", "purgito-images", "purgito-gifs"
NEW_KEY = "age169gl5lq3a3s7g3fm3x6h9tyqxsn89p0gucp2zh467lj0n5vzxdcsksh8ca"
ID32 = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
SECRET64 = "0123456789abcdef" * 4

_spec = importlib.util.spec_from_file_location(
    "r2_backup", ROOT / "scripts" / "r2_backup.py"
)
r2_backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r2_backup)


def _run(script, stdin, env_file, extra_env=None):
    return subprocess.run(
        ["bash", str(ROOT / "deploy" / script)],
        input=stdin,
        capture_output=True,
        text=True,
        env={**os.environ, "ENV_FILE": str(env_file), **(extra_env or {})},
        timeout=30,
    )


# ─── set_media_credentials.sh (.env del bot) ─────────────────────────────────

BOT_ENV = (
    "DISCORD_TOKEN=token-discord-que-no-se-toca\n"
    "R2_ACCESS_KEY_ID=viejo-id\n"
    "R2_SECRET_ACCESS_KEY=viejo-secreto\n"
    "R2_BACKUP_BUCKET=purgito-backups\n"
    "WEB_PORT=8080\n"
)


def _bot_env(tmp_path, mode=0o600):
    f = tmp_path / ".env"
    f.write_text(BOT_ENV)
    f.chmod(mode)
    return f


def test_media_actualiza_solo_las_dos_variables_y_no_imprime_nada(tmp_path):
    f = _bot_env(tmp_path)
    proc = _run("set_media_credentials.sh", f"{ID32}\n{SECRET64}\n", f)
    assert proc.returncode == 0, proc.stderr
    lines = f.read_text().splitlines()
    assert f"R2_ACCESS_KEY_ID={ID32}" in lines
    assert f"R2_SECRET_ACCESS_KEY={SECRET64}" in lines
    assert "viejo-id" not in f.read_text() and "viejo-secreto" not in f.read_text()
    assert (
        "DISCORD_TOKEN=token-discord-que-no-se-toca" in lines
        and "WEB_PORT=8080" in lines
    )
    assert len([ln for ln in lines if ln.startswith("R2_ACCESS_KEY_ID=")]) == 1
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    out = proc.stdout + proc.stderr
    assert ID32 not in out and SECRET64 not in out and "token-discord" not in out
    assert list(tmp_path.glob(".env.*")) == []  # sin temporales ni copias


@pytest.mark.parametrize(
    "entrada",
    [
        f"corto\n{SECRET64}\n",
        f"{ID32}\ncorto\n",
        f"{ID32}!\n{SECRET64}\n",
        f"{ID32}\n{SECRET64}x\n",
    ],
)
def test_media_rechaza_formatos_raros_sin_cambiar_nada(tmp_path, entrada):
    f = _bot_env(tmp_path)
    proc = _run("set_media_credentials.sh", entrada, f)
    assert proc.returncode != 0 and "No se cambió nada" in proc.stderr
    assert f.read_text() == BOT_ENV
    assert SECRET64 not in proc.stdout + proc.stderr


def test_media_se_niega_si_el_env_no_es_0600(tmp_path):
    f = _bot_env(tmp_path, mode=0o644)
    proc = _run("set_media_credentials.sh", f"{ID32}\n{SECRET64}\n", f)
    assert proc.returncode != 0 and "permisos 644" in proc.stderr
    assert f.read_text() == BOT_ENV


def test_media_agrega_las_variables_si_faltaban(tmp_path):
    f = tmp_path / ".env"
    f.write_text("WEB_PORT=8080\n")
    f.chmod(0o600)
    assert _run("set_media_credentials.sh", f"{ID32}\n{SECRET64}\n", f).returncode == 0
    assert f"R2_ACCESS_KEY_ID={ID32}" in f.read_text()


# ─── set_backup_credentials.sh (/etc/purgito/backup.env) ─────────────────────

BK_ENV = (
    "R2_ENDPOINT_URL=https://cuenta.r2.cloudflarestorage.com\n"
    "R2_BACKUP_BUCKET=purgito-backups\n"
    "R2_BACKUP_PREFIX=gen2/\n"
    f"BACKUP_AGE_RECIPIENTS={NEW_KEY}\n"
    "SKIP_PRUNE=1\n"
)


def _bk_env(tmp_path):
    f = tmp_path / "backup.env"
    f.write_text(BK_ENV)
    f.chmod(0o600)
    return f


def test_backups_escribe_las_dos_credenciales_y_conserva_el_resto(tmp_path):
    f = _bk_env(tmp_path)
    proc = _run("set_backup_credentials.sh", f"{ID32}\n{SECRET64}\n", f)
    assert proc.returncode == 0, proc.stderr
    texto = f.read_text()
    assert f"R2_BACKUP_ACCESS_KEY_ID={ID32}" in texto
    assert f"R2_BACKUP_SECRET_ACCESS_KEY={SECRET64}" in texto
    for linea in BK_ENV.splitlines():
        assert linea in texto
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert (
        ID32 not in proc.stdout + proc.stderr
        and SECRET64 not in proc.stdout + proc.stderr
    )


def test_backups_repetido_no_duplica_ni_deja_las_viejas(tmp_path):
    f = _bk_env(tmp_path)
    _run("set_backup_credentials.sh", f"{ID32}\n{SECRET64}\n", f)
    nuevo_id, nuevo_sec = "f" * 32, "e" * 64
    _run("set_backup_credentials.sh", f"{nuevo_id}\n{nuevo_sec}\n", f)
    lineas = f.read_text().splitlines()
    assert lineas.count(f"R2_BACKUP_ACCESS_KEY_ID={nuevo_id}") == 1
    assert not any(ID32 in ln or SECRET64 in ln for ln in lineas)


def test_backups_con_formato_malo_no_cambia_nada(tmp_path):
    f = _bk_env(tmp_path)
    proc = _run("set_backup_credentials.sh", "corto\nmas-corto\n", f)
    assert proc.returncode != 0
    assert f.read_text() == BK_ENV


def test_backups_sobre_el_archivo_real_exige_root_y_ruta_de_opt():
    """Sin ENV_FILE de prueba, el script se niega si no es root o si no corre desde la copia
    de root de /opt (el checkout del bot es escribible por el usuario del bot)."""
    proc = subprocess.run(
        ["bash", str(ROOT / "deploy" / "set_backup_credentials.sh")],
        input=f"{ID32}\n{SECRET64}\n",
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "ENV_FILE"},
        timeout=30,
    )
    assert proc.returncode != 0
    assert "sudo" in proc.stderr or "/opt/purgito-backup" in proc.stderr
    assert SECRET64 not in proc.stdout + proc.stderr


# ─── backup_db.sh con rol de solo lectura por socket (sin DATABASE_URL) ──────

needs_tools = pytest.mark.skipif(
    not (
        shutil.which("age") and shutil.which("pg_dump") and shutil.which("age-keygen")
    ),
    reason="faltan age o los clientes de PostgreSQL",
)


@needs_tools
def test_backup_db_funciona_con_entorno_libpq_sin_database_url(tmp_path):
    """Es la forma en que corre el runner aislado: PGUSER/PGHOST/PGDATABASE, sin contraseña."""
    from urllib.parse import urlparse

    u = urlparse(os.environ["TEST_DATABASE_URL"])
    stub = tmp_path / "fake-python"
    stub.write_text("#!/bin/bash\nexit 0\n")
    stub.chmod(0o755)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("R2_", "DATABASE_URL", "PG", "TEST_DATABASE"))
    }
    env.update(
        PGUSER=u.username or "",
        PGHOST=u.hostname or "",
        PGPORT=str(u.port or 5432),
        PGDATABASE=u.path.lstrip("/"),
        BACKUP_DIR=str(tmp_path / "bk"),
        PYTHON=str(stub),
        ENV_FILE=str(tmp_path / "no-hay-env"),
        BACKUP_AGE_RECIPIENTS=NEW_KEY,
        R2_BACKUP_BUCKET=BUCKET,
        MIN_FREE_MB="1",
        SKIP_PRUNE="1",
    )
    proc = subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup_db.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PRUNE OMITIDO" in proc.stdout
    assert len(list((tmp_path / "bk").glob("purgito-2*.dump.age"))) == 1


@needs_tools
def test_skip_prune_no_borra_nada_ni_en_el_disco(tmp_path):
    bk = tmp_path / "bk"
    bk.mkdir()
    for i in range(4):
        (bk / f"purgito-2026010{i}-000000.dump.age").write_bytes(b"x" * 10)
    from urllib.parse import urlparse

    u = urlparse(os.environ["TEST_DATABASE_URL"])
    stub = tmp_path / "fake-python"
    stub.write_text("#!/bin/bash\nexit 0\n")
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
    env.update(
        DATABASE_URL=os.environ["TEST_DATABASE_URL"],
        BACKUP_DIR=str(bk),
        PYTHON=str(stub),
        ENV_FILE=str(tmp_path / "no"),
        BACKUP_AGE_RECIPIENTS=NEW_KEY,
        R2_BACKUP_BUCKET=BUCKET,
        MIN_FREE_MB="1",
        SKIP_PRUNE="1",
        KEEP_LAST="1",
    )
    proc = subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup_db.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert len(list(bk.glob("purgito-2*.dump.age"))) == 5  # los 4 viejos + el nuevo
    assert u.path


# ─── r2_backup.py: backup-only, media-check, head ────────────────────────────


def _clients(monkeypatch, *, bk_denied, img_denied):
    bk, im = FakeS3(BUCKET, IMG, GIF), FakeS3(BUCKET, IMG, GIF)
    bk.denied, im.denied = set(bk_denied), set(img_denied)
    monkeypatch.setattr(r2, "get_backup_client", lambda: bk)
    monkeypatch.setattr(r2, "get_client", lambda: im)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BUCKET)
    monkeypatch.setenv("R2_IMAGES_BUCKET", IMG)
    monkeypatch.setenv("R2_GIFS_BUCKET", GIF)
    return bk, im


def test_access_check_backup_only_no_necesita_el_token_de_imagenes(monkeypatch, capsys):
    _clients(monkeypatch, bk_denied={IMG, GIF}, img_denied=set())
    monkeypatch.setattr(r2, "get_client", lambda: None)  # el runner no lo tiene
    assert r2_backup.main(["access-check", "--backup-only"]) == 0
    assert "ACCESS-CHECK: OK" in capsys.readouterr().out


def test_access_check_backup_only_falla_si_el_token_de_backups_ve_imagenes(
    monkeypatch, capsys
):
    _clients(monkeypatch, bk_denied={GIF}, img_denied=set())
    assert r2_backup.main(["access-check", "--backup-only"]) == 1
    assert "token de backups puede listar purgito-images" in capsys.readouterr().err


def test_media_check_ok_si_ve_imagenes_y_gifs_pero_no_los_backups(monkeypatch, capsys):
    _clients(monkeypatch, bk_denied=set(), img_denied={BUCKET})
    assert r2_backup.main(["media-check"]) == 0
    assert "MEDIA-CHECK: OK" in capsys.readouterr().out


def test_media_check_falla_si_el_token_de_medios_llega_a_los_backups(monkeypatch):
    _clients(monkeypatch, bk_denied=set(), img_denied=set())
    assert r2_backup.main(["media-check"]) == 1


def test_media_check_falla_si_el_token_de_medios_no_ve_sus_buckets(monkeypatch):
    _clients(monkeypatch, bk_denied=set(), img_denied={IMG, BUCKET})
    assert r2_backup.main(["media-check"]) == 1


def test_head_muestra_tamano_y_sha256_de_un_objeto_de_gen2(
    monkeypatch, capsys, tmp_path
):
    bk, _ = _clients(monkeypatch, bk_denied=set(), img_denied=set())
    f = tmp_path / "purgito-20261106-031701.dump.age"
    f.write_bytes(b"age-encryption.org/v1\nxx")
    assert r2.upload_backup_file_sync(str(f)) == f.name
    assert r2_backup.main(["head", f.name]) == 0
    out = capsys.readouterr().out
    assert f"purgito-backups/gen2/{f.name}" in out and "sha256:" in out
    assert r2_backup.main(["head", "../x"]) == 1
    assert {c[0] for c in bk.calls} <= {"put_object", "head_object"}


# ─── el bot no tiene forma de pedir las credenciales de backups ──────────────


def test_el_codigo_del_bot_no_usa_las_credenciales_ni_el_cliente_de_backups():
    for p in [
        ROOT / "src" / "bot.py",
        ROOT / "src" / "config.py",
        ROOT / "src" / "webapi.py",
    ] + sorted((ROOT / "src" / "cogs").glob("*.py")):
        texto = p.read_text(encoding="utf-8")
        for prohibido in (
            "get_backup_client",
            "R2_BACKUP_ACCESS_KEY_ID",
            "R2_BACKUP_SECRET_ACCESS_KEY",
            "backup.env",
        ):
            assert prohibido not in texto, f"{p.name} no debería tocar {prohibido}"


def test_el_unit_del_bot_no_carga_el_archivo_de_backups():
    for f in (ROOT / "deploy").glob("*.service*"):
        if f.name.startswith("bot-purg") or f.name.startswith("studio-purg"):
            assert "backup.env" not in f.read_text()


# ─── unidades e instalador ───────────────────────────────────────────────────


def test_el_servicio_de_backup_esta_aislado():
    u = (ROOT / "deploy" / "purgito-backup.service").read_text()
    assert "User=purgito_backup" in u
    assert "EnvironmentFile=/etc/purgito/backup.env" in u
    assert "ExecStart=/opt/purgito-backup/deploy/backup_db.sh" in u  # código de root
    assert "ReadWritePaths=/var/backups/purgito" in u
    for hard in (
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateTmp=yes",
        "CapabilityBoundingSet=",
    ):
        assert hard in u
    assert "/home/purgito" not in u


def test_el_instalador_no_habilita_el_timer_ni_toca_el_cron_ni_el_bot():
    sh = (ROOT / "deploy" / "install_backup_runner.sh").read_text()
    assert "enable" not in sh.replace("disable", "")  # el timer NO se habilita
    for no in (
        "crontab",
        "restart",
        "bot-purg",
        "studio-purg",
        "DROP ",
        "TRUNCATE",
        "DELETE ",
    ):
        assert no not in sh, f"el instalador no debería contener {no!r}"
    assert "pg_read_all_data" in sh and "NOSUPERUSER" in sh
    assert "GRANT CONNECT ON DATABASE" in sh  # la base revoca CONNECT a PUBLIC
    assert (
        'git -C "$repo" show "HEAD:$path"' in sh
    )  # instala lo commiteado, no el árbol de trabajo


def test_el_instalador_exige_root_y_no_aplica_sin_apply():
    if os.geteuid() == 0:
        pytest.skip("se ejecuta como root")
    proc = subprocess.run(
        [
            "bash",
            str(ROOT / "deploy" / "install_backup_runner.sh"),
            "--recipient",
            NEW_KEY,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0 and "sudo" in proc.stderr


def test_backup_task_solo_admite_subcomandos_de_lectura():
    sh = (ROOT / "deploy" / "backup_task.sh").read_text()
    for permitido in ("preflight", "list", "check", "access-check", "head"):
        assert permitido in sh
    for no in ("upload", "prune", "download", "delete"):
        assert (
            f"{no})" not in sh and f" {no} " not in sh.split("case")[1].split("esac")[0]
        )


# ─── registro de eliminaciones y vigilancia en el runner ─────────────────────

RUNNER_UNITS = ["purgito-backup", "purgito-ledger", "purgito-backup-check"]


@pytest.mark.parametrize("unit", RUNNER_UNITS)
def test_las_unidades_del_runner_estan_aisladas_y_su_timer_no_se_habilita_solo(unit):
    service = (ROOT / "deploy" / f"{unit}.service").read_text()
    assert "User=purgito_backup" in service
    assert "EnvironmentFile=/etc/purgito/backup.env" in service
    assert "ExecStart=/opt/purgito-backup/deploy/" in service  # código de root
    assert "ReadWritePaths=/var/backups/purgito" in service
    for hard in (
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "CapabilityBoundingSet=",
    ):
        assert hard in service
    assert "/home/purgito" not in service
    timer = (ROOT / "deploy" / f"{unit}.timer").read_text()
    assert "OnCalendar=" in timer


def test_el_instalador_incluye_el_registro_y_la_vigilancia():
    sh = (ROOT / "deploy" / "install_backup_runner.sh").read_text()
    for f in (
        "scripts/export_privacy_ledger.py",
        "src/privacy_ledger.py",
        "deploy/export_ledger.sh",
        "deploy/backup_check.sh",
    ):
        assert f in sh
    for u in RUNNER_UNITS:
        assert u in sh


def test_el_exportador_del_registro_no_necesita_drivers_de_python():
    """El python3 del sistema no tiene asyncpg/psycopg: el exportador lee con psql."""
    codigo = (ROOT / "scripts" / "export_privacy_ledger.py").read_text()
    for prohibido in (
        "import pgsync",
        "import asyncpg",
        "import psycopg",
        "from pgsync",
    ):
        assert prohibido not in codigo
    assert "psql" in codigo


@needs_tools
def test_el_exportador_funciona_con_entorno_libpq_sin_database_url(
    tmp_path, monkeypatch
):
    from urllib.parse import urlparse

    spec = importlib.util.spec_from_file_location(
        "export_privacy_ledger", ROOT / "scripts" / "export_privacy_ledger.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    u = urlparse(os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PGUSER", u.username or "")
    monkeypatch.setenv("PGHOST", u.hostname or "")
    monkeypatch.setenv("PGPORT", str(u.port or 5432))
    monkeypatch.setenv("PGDATABASE", u.path.lstrip("/"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "b"))
    assert mod.main(["--dry-run"]) == 0
    assert not (tmp_path / "b").exists()


def test_check_ledger_falla_si_la_ultima_instantanea_es_vieja(monkeypatch):
    from datetime import datetime, timedelta, timezone

    fake = FakeS3(BUCKET)
    monkeypatch.setattr(r2, "get_backup_client", lambda: fake)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BUCKET)

    def key(dt):
        return (
            "gen2/ledger/privacy-ledger-" + dt.strftime("%Y%m%dT%H%M%S") + "Z.jsonl.age"
        )

    ahora = datetime.now(timezone.utc)
    assert r2_backup.main(["check", "--ledger"]) == 1  # no hay ninguna
    fake.seed(BUCKET, key(ahora - timedelta(hours=5)))
    assert r2_backup.main(["check", "--ledger", "--max-age-hours", "3"]) == 1
    fake.seed(BUCKET, key(ahora - timedelta(minutes=20)))
    assert r2_backup.main(["check", "--ledger", "--max-age-hours", "3"]) == 0


def test_set_backup_credentials_webhook_solo_toca_esa_variable(tmp_path):
    f = _bk_env(tmp_path)
    hook = "https://discord.com/api/webhooks/123456789/AbC_def-GHI"
    proc = subprocess.run(
        ["bash", str(ROOT / "deploy" / "set_backup_credentials.sh"), "--webhook"],
        input=hook + "\n",
        capture_output=True,
        text=True,
        env={**os.environ, "ENV_FILE": str(f)},
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert f"BACKUP_ALERT_WEBHOOK={hook}" in f.read_text()
    for linea in BK_ENV.splitlines():
        assert linea in f.read_text()
    assert "AbC_def" not in proc.stdout + proc.stderr
    assert oct(f.stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize(
    "malo",
    [
        "http://discord.com/api/webhooks/1/x",
        "https://evil.example/api/webhooks/1/x",
        "no-es-url",
        "",
    ],
)
def test_set_backup_credentials_webhook_rechaza_urls_raras(tmp_path, malo):
    f = _bk_env(tmp_path)
    proc = subprocess.run(
        ["bash", str(ROOT / "deploy" / "set_backup_credentials.sh"), "--webhook"],
        input=malo + "\n",
        capture_output=True,
        text=True,
        env={**os.environ, "ENV_FILE": str(f)},
        timeout=30,
    )
    assert proc.returncode != 0
    assert f.read_text() == BK_ENV
