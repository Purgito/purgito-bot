"""Backups a R2: scripts/r2_backup.py y su uso desde deploy/backup_db.sh.

Lo que importa acá es lo que NO debe pasar: un backup que parece hecho y solo
quedó en el disco, una poda que se lleva copias que nunca llegaron a R2, o un
backup que termina en un bucket público.
"""

import importlib.util
import os
import pathlib
import shutil
import stat
import subprocess
import sys

import pytest
from fake_s3 import FakeS3

import r2

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKUP_BUCKET = "purgito-backups"

_spec = importlib.util.spec_from_file_location(
    "r2_backup", ROOT / "scripts" / "r2_backup.py"
)
r2_backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r2_backup)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3(BACKUP_BUCKET, "purgito-images", "purgito-gifs")
    monkeypatch.setattr(r2, "get_client", lambda: fake)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BACKUP_BUCKET)
    return fake


def _files(tmp_path):
    db = tmp_path / "bot-20260812-031700.db"
    flags = tmp_path / "bot-20260812-031700.flags.tar.gz"
    db.write_bytes(b"SQLite format 3\x00" + b"d" * 64)
    flags.write_bytes(b"flags")
    return db, flags


# ─── CLI ──────────────────────────────────────────────────────────────────────


def test_upload_sube_en_el_orden_pedido_y_solo_al_bucket_de_backups(
    s3, tmp_path, capsys
):
    db, flags = _files(tmp_path)

    rc = r2_backup.main(["upload", str(flags), str(db)])

    assert rc == 0
    puts = [key for _op, _bucket, key in s3.ops("put_object")]
    assert puts == [flags.name, db.name]  # los flags antes que la base
    assert s3.keys(BACKUP_BUCKET) == {flags.name, db.name}
    assert s3.keys("purgito-images") == s3.keys("purgito-gifs") == set()
    assert "OK subido" in capsys.readouterr().out


def test_upload_falla_con_codigo_1_si_la_subida_falla(s3, tmp_path, capsys):
    db, flags = _files(tmp_path)
    s3.fail_put = True

    rc = r2_backup.main(["upload", str(flags), str(db)])

    assert rc == 1
    assert "ERROR" in capsys.readouterr().err
    assert s3.keys(BACKUP_BUCKET) == set()


def test_upload_corta_en_el_primer_error_y_no_sube_la_base(s3, tmp_path, monkeypatch):
    """Si los flags no subieron, la base no debe subir sola: un .db en el
    bucket tiene que tener siempre sus flags al lado."""
    db, flags = _files(tmp_path)
    real = r2.upload_backup_file_sync

    def solo_la_base_sube(path, key=None):
        if path.endswith(".flags.tar.gz"):
            raise r2.BackupError("falló")
        return real(path, key)

    monkeypatch.setattr(r2, "upload_backup_file_sync", solo_la_base_sube)

    assert r2_backup.main(["upload", str(flags), str(db)]) == 1
    assert s3.keys(BACKUP_BUCKET) == set()


def test_upload_con_un_archivo_inexistente_falla_sin_subir_nada(s3, tmp_path):
    db, _flags = _files(tmp_path)

    assert r2_backup.main(["upload", str(db), str(tmp_path / "no-existe.db")]) == 1
    assert s3.ops("put_object") == []


def test_upload_sin_bucket_configurado_es_un_error_no_un_exito_silencioso(
    s3, tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("R2_BACKUP_BUCKET")
    db, _flags = _files(tmp_path)

    assert r2_backup.main(["upload", str(db)]) == 1
    assert "R2_BACKUP_BUCKET" in capsys.readouterr().err
    assert s3.calls == []


def test_list_muestra_los_backups(s3, capsys):
    s3.seed(BACKUP_BUCKET, "bot-20260812-031700.db", b"123")

    assert r2_backup.main(["list"]) == 0
    assert "bot-20260812-031700.db\t3" in capsys.readouterr().out


def test_download_latest_baja_la_base_y_sus_flags_con_permisos_0600(s3, tmp_path):
    db, flags = _files(tmp_path)
    viejo = tmp_path / "bot-20260701-031700.db"
    viejo.write_bytes(b"viejo")
    for f in (viejo, flags, db):
        r2.upload_backup_file_sync(str(f))
    dest = tmp_path / "restore"

    assert r2_backup.main(["download", "latest", "--dest", str(dest)]) == 0

    assert sorted(p.name for p in dest.iterdir()) == [db.name, flags.name]
    assert (dest / db.name).read_bytes() == db.read_bytes()
    for p in dest.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_download_de_algo_que_no_esta_falla(s3, tmp_path, capsys):
    assert (
        r2_backup.main(["download", "bot-1999.db", "--dest", str(tmp_path / "x")]) == 1
    )
    assert "no está" in capsys.readouterr().err


def test_download_latest_sin_backups_falla(s3, tmp_path):
    assert r2_backup.main(["download", "latest", "--dest", str(tmp_path / "x")]) == 1


def test_el_script_real_arranca_y_falla_fuerte_sin_configuracion(tmp_path):
    """Proceso aparte, como lo lanza backup_db.sh desde cron. Las variables de
    R2 van vacías a propósito: dotenv no pisa lo que ya está definido, así que
    jamás llega a un bucket real aunque exista un .env."""
    f = tmp_path / "bot-1.db"
    f.write_bytes(b"x")
    env = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
    for name in (
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BACKUP_BUCKET",
    ):
        env[name] = ""

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "r2_backup.py"), "upload", str(f)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert proc.returncode == 1
    assert "R2 no está configurado" in proc.stderr


# ─── deploy/backup_db.sh: un backup solo local no cuenta como exitoso ─────────

needs_shell_tools = pytest.mark.skipif(
    shutil.which("sqlite3") is None or shutil.which("bash") is None,
    reason="hace falta el CLI de sqlite3 (en CI lo trae ubuntu-latest)",
)


def _run_backup(tmp_path, python_stub: str, bucket: str | None = "purgito-backups"):
    """Corre deploy/backup_db.sh contra una base de mentira, con un intérprete
    falso en lugar del del venv (sin red, sin boto3)."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    db = data / "bot.db"
    subprocess.run(
        ["sqlite3", str(db), "CREATE TABLE t(x); INSERT INTO t VALUES (1);"], check=True
    )
    (data / ".images_wiped_v2").write_text("done")
    stub = tmp_path / "fake-python"
    stub.write_text(python_stub)
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
    env.update(
        DB_SRC=str(db),
        BACKUP_DIR=str(tmp_path / "backups"),
        PYTHON=str(stub),
        ENV_FILE=str(tmp_path / "sin-env"),
    )
    if bucket is not None:
        env["R2_BACKUP_BUCKET"] = bucket
    return subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup_db.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@needs_shell_tools
def test_backup_db_no_reporta_exito_si_falla_la_subida_a_r2(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    viejo = backups / "bot-19990101-000000.db"
    viejo.write_bytes(b"viejo")
    os.utime(viejo, (1, 1))  # 1970: muy por encima de la retención

    proc = _run_backup(tmp_path, "#!/bin/bash\necho 'R2 caído' >&2\nexit 1\n")

    assert proc.returncode != 0
    assert " OK backup -> " not in proc.stdout + proc.stderr
    assert "NO subió a R2" in proc.stderr
    # el backup local se conserva, y no se poda nada (ni lo viejo)
    assert len(list(backups.glob("bot-2*.db"))) == 1
    assert viejo.exists()


@needs_shell_tools
def test_backup_db_sube_los_flags_antes_que_la_base_y_reporta_la_subida(tmp_path):
    log = tmp_path / "args.log"
    stub = f'#!/bin/bash\nprintf "%s\\n" "$@" >> "{log}"\n'

    proc = _run_backup(tmp_path, stub)

    assert proc.returncode == 0, proc.stderr
    assert "subido a R2 (purgito-backups)" in proc.stdout
    args = log.read_text().splitlines()
    assert args[1] == "upload"
    uploaded = [pathlib.Path(a).name for a in args[2:]]
    assert uploaded[0].endswith(".flags.tar.gz") and uploaded[1].endswith(".db")


@needs_shell_tools
def test_backup_db_sin_bucket_configurado_queda_solo_local_y_lo_dice(tmp_path):
    proc = _run_backup(tmp_path, "#!/bin/bash\nexit 1\n", bucket=None)

    assert proc.returncode == 0, proc.stderr
    assert "solo local" in proc.stdout
    assert len(list((tmp_path / "backups").glob("bot-*.db"))) == 1
