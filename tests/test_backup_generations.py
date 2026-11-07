"""Generaciones de backups dentro de UN bucket (`purgito-backups`).

La generación 1 (raíz del bucket: `purgito-*.dump.age`, `luks-header-*`, `privacy-prefs.*`,
cifrados con una clave age perdida) tiene que quedar fuera del alcance de TODO lo que
sube, lista, baja o borra la generación vigente (`gen2/`). Y los backups nuevos solo se
cifran con una clave que no esté revocada.
"""

import importlib.util
import os
import pathlib
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fake_s3 import FakeS3

import backup_recipients
import db
import r2

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUCKET = "purgito-backups"
NEW_KEY = "age169gl5lq3a3s7g3fm3x6h9tyqxsn89p0gucp2zh467lj0n5vzxdcsksh8ca"
OLD_KEY = "age1aa0eyjhwnjzx8hh9h56grrd4fhpgegggy777dt88edrsur8zvdesgrxn87"

_spec = importlib.util.spec_from_file_location(
    "r2_backup", ROOT / "scripts" / "r2_backup.py"
)
r2_backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r2_backup)

LEGACY = [
    "purgito-20261101-031701.dump.age",
    "purgito-20261105-000130.dump.age",
    "purgito-20261105-014330.dump.age",
    "luks-header-20261105.img.age",
    "privacy-prefs.csv.age",
    "gen1/purgito-20260901-000000.dump.age",
    "ledger/privacy-ledger-20261105T000000Z.jsonl.age",
]


@pytest.fixture
def bucket(monkeypatch):
    """Bucket con la generación 1 en la raíz y nada de gen2."""
    fake = FakeS3(BUCKET)
    for k in LEGACY:
        fake.seed(BUCKET, k, b"historico")
    monkeypatch.setattr(r2, "get_backup_client", lambda: fake)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BUCKET)
    monkeypatch.delenv("R2_BACKUP_PREFIX", raising=False)
    return fake


def _historicos(fake):
    return {k for k in fake.keys(BUCKET) if k in LEGACY}


def _dumps_viejos(fake, n=30):
    ahora = datetime.now(timezone.utc)
    for d in range(n):
        name = (ahora - timedelta(days=d)).strftime("purgito-%Y%m%d-031701.dump.age")
        fake.seed(BUCKET, "gen2/" + name, b"nuevo")


# ─── el histórico es invisible e intocable ──────────────────────────────────


def test_list_no_ve_ningun_objeto_historico(bucket):
    assert r2.list_backups_sync() == []
    _dumps_viejos(bucket, 3)
    keys = [k for k, _s, _m in r2.list_backups_sync()]
    assert len(keys) == 3 and all(k.startswith("purgito-") for k in keys)


def test_ninguna_poda_toca_el_historico(bucket):
    _dumps_viejos(bucket, 30)
    bucket.seed(BUCKET, "gen2/ledger/privacy-ledger-20200101T000000Z.jsonl.age", b"x")
    for i in range(4):
        bucket.seed(
            BUCKET, f"gen2/ledger/privacy-ledger-2020010{i}T000000Z.jsonl.age", b"x"
        )

    assert r2_backup.main(["prune-gfs", "--apply"]) == 0
    assert r2_backup.main(["prune-ledger", "--apply"]) == 0
    assert r2_backup.main(["prune", "--keep", "2", "--apply"]) == 0

    assert _historicos(bucket) == set(LEGACY)
    borrados = {k for op, _b, k in bucket.ops("delete_object")}
    assert borrados and all(k.startswith("gen2/") for k in borrados)


def test_borrar_una_key_con_el_mismo_nombre_que_un_historico_borra_solo_la_de_gen2(
    bucket,
):
    nombre = "purgito-20261105-000130.dump.age"
    bucket.seed(BUCKET, "gen2/" + nombre, b"nuevo")
    r2.delete_backup_sync(nombre)
    assert "gen2/" + nombre not in bucket.keys(BUCKET)
    assert nombre in bucket.keys(BUCKET)  # el histórico sigue


@pytest.mark.parametrize(
    "malo",
    [
        "../purgito-x.dump.age",
        "/purgito-x.dump.age",
        "gen1/purgito-x.dump.age",
        "gen2/purgito-x.dump.age",
        "luks-header-20261105.img.age",
        "privacy-prefs.csv.age",
        "ledger/../purgito-x.dump.age",
        "ledger//x",
        "",
        "purgito x",
    ],
)
def test_borrar_rechaza_keys_que_no_son_de_la_generacion(bucket, malo):
    with pytest.raises(r2.BackupError):
        r2.delete_backup_sync(malo)
    assert bucket.ops("delete_object") == []


def test_subir_deja_el_objeto_en_gen2_y_nunca_en_la_raiz(bucket, tmp_path):
    f = tmp_path / "purgito-20261106-031701.dump.age"
    f.write_bytes(b"age-encryption.org/v1\nx")
    assert r2.upload_backup_file_sync(str(f)) == f.name
    assert "gen2/" + f.name in bucket.keys(BUCKET)
    assert f.name not in bucket.keys(BUCKET)
    assert _historicos(bucket) == set(LEGACY)


def test_bajar_no_alcanza_el_historico(bucket, tmp_path):
    with pytest.raises(r2.BackupError):
        r2.download_backup_sync("purgito-20261105-000130.dump.age", str(tmp_path / "x"))
    assert r2_backup.main(["download", "latest", "--dest", str(tmp_path)]) == 1


@pytest.mark.parametrize(
    "prefijo", ["", "/", "gen1/", "gen2", "gen0/", "../", "a/gen2/", "legacy/"]
)
def test_un_prefijo_invalido_corta_todo_antes_de_tocar_r2(bucket, monkeypatch, prefijo):
    monkeypatch.setenv("R2_BACKUP_PREFIX", prefijo or " ")
    if prefijo == "":
        monkeypatch.delenv("R2_BACKUP_PREFIX")
        assert r2.backup_prefix() == "gen2/"  # vacío = el default seguro
        return
    with pytest.raises(r2.BackupError):
        r2.backup_prefix()
    with pytest.raises(r2.BackupError):
        r2.list_backups_sync()
    with pytest.raises(r2.BackupError):
        r2.delete_backup_sync("purgito-20261105-000130.dump.age")
    assert bucket.ops("delete_object", "put_object") == []


def test_gen3_es_un_prefijo_valido_y_aisla_de_gen2(bucket, monkeypatch):
    bucket.seed(BUCKET, "gen2/purgito-20261105-000130.dump.age", b"x")
    monkeypatch.setenv("R2_BACKUP_PREFIX", "gen3/")
    assert r2.list_backups_sync() == []


# ─── preflight ───────────────────────────────────────────────────────────────


def test_preflight_ok_informa_y_no_modifica_nada(bucket, monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", NEW_KEY)
    _dumps_viejos(bucket, 20)
    antes = set(bucket.keys(BUCKET))

    assert r2_backup.main(["preflight"]) == 0

    out = capsys.readouterr().out
    assert "generación vigente: gen2/" in out
    assert f"históricos (fuera del prefijo, intocables): {len(LEGACY)}" in out
    assert "del histórico" in out and "0 del histórico" in out
    assert "PREFLIGHT: OK" in out
    assert NEW_KEY not in out  # solo la forma corta
    assert set(bucket.keys(BUCKET)) == antes
    assert bucket.ops("delete_object", "put_object") == []


def test_preflight_falla_con_la_clave_vieja(bucket, monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", OLD_KEY)
    assert r2_backup.main(["preflight"]) == 1
    assert "REVOCADA" in capsys.readouterr().err


def test_preflight_falla_si_se_mezcla_la_clave_vieja_con_la_nueva(bucket, monkeypatch):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", f"{NEW_KEY} {OLD_KEY}")
    assert r2_backup.main(["preflight"]) == 1


def test_preflight_falla_sin_destinatarios(bucket, monkeypatch):
    monkeypatch.delenv("BACKUP_AGE_RECIPIENTS", raising=False)
    assert r2_backup.main(["preflight"]) == 1


def test_preflight_rechaza_una_retencion_mayor_que_la_politica(
    bucket, monkeypatch, capsys
):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", NEW_KEY)
    assert r2_backup.main(["preflight", "--max-age-days", "30"]) == 1
    assert "14 días" in capsys.readouterr().err


def test_preflight_falla_con_prefijo_historico(bucket, monkeypatch):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", NEW_KEY)
    monkeypatch.setenv("R2_BACKUP_PREFIX", "gen1/")
    assert r2_backup.main(["preflight"]) == 1


# ─── destinatarios age ───────────────────────────────────────────────────────


def test_la_clave_vieja_esta_en_la_lista_de_revocadas():
    assert OLD_KEY in backup_recipients.load_revoked()
    assert NEW_KEY not in backup_recipients.load_revoked()


def test_parse_recipients_acepta_la_nueva_y_rechaza_el_resto():
    assert backup_recipients.parse_recipients(NEW_KEY) == [NEW_KEY]
    assert backup_recipients.parse_recipients(f"{NEW_KEY},{NEW_KEY}") == [NEW_KEY]
    for malo in (
        "",
        "   ",
        "no-es-age",
        OLD_KEY,
        f"{NEW_KEY} {OLD_KEY}",
        "AGE-SECRET-KEY-1ABC",
    ):
        with pytest.raises(ValueError):
            backup_recipients.parse_recipients(malo)


def test_sin_la_lista_de_revocadas_se_niega(tmp_path):
    with pytest.raises(ValueError):
        backup_recipients.load_revoked(str(tmp_path / "no-existe.txt"))


needs_shell_tools = pytest.mark.skipif(
    not (
        shutil.which("age") and shutil.which("pg_dump") and shutil.which("pg_restore")
    ),
    reason="faltan age o los clientes de PostgreSQL",
)


def _run_backup_sh(tmp_path, recipients):
    stub = tmp_path / "fake-python"
    stub.write_text("#!/bin/bash\nexit 0\n")
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
    env.update(
        DATABASE_URL=os.environ["TEST_DATABASE_URL"],
        BACKUP_DIR=str(tmp_path / "backups"),
        PYTHON=str(stub),
        ENV_FILE=str(tmp_path / "sin-env"),
        MIN_FREE_MB="1",
        BACKUP_AGE_RECIPIENTS=recipients,
        R2_BACKUP_BUCKET=BUCKET,
    )
    return subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup_db.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@needs_shell_tools
def test_backup_db_no_hace_backup_con_la_clave_vieja(tmp_path):
    proc = _run_backup_sh(tmp_path, OLD_KEY)
    assert proc.returncode != 0
    assert "REVOCADA" in proc.stderr and "No se hizo backup" in proc.stderr
    assert not list((tmp_path / "backups").glob("purgito-2*"))


@needs_shell_tools
def test_backup_db_no_hace_backup_si_la_vieja_va_mezclada(tmp_path):
    proc = _run_backup_sh(tmp_path, f"{NEW_KEY} {OLD_KEY}")
    assert proc.returncode != 0 and "REVOCADA" in proc.stderr
    assert not list((tmp_path / "backups").glob("purgito-2*"))


@needs_shell_tools
def test_backup_db_acepta_la_clave_nueva_y_cifra_solo_para_ella(tmp_path):
    proc = _run_backup_sh(tmp_path, NEW_KEY)
    assert proc.returncode == 0, proc.stderr
    dumps = list((tmp_path / "backups").glob("purgito-2*.dump.age"))
    assert len(dumps) == 1
    head = dumps[0].read_bytes()[:4096]
    assert head.startswith(b"age-encryption.org/v1")
    assert head.count(b"-> X25519 ") == 1  # un solo destinatario


# ─── coherencia retención <-> política de privacidad ─────────────────────────


def test_la_retencion_por_defecto_cumple_la_politica_publicada():
    assert r2_backup.DEFAULT_MAX_AGE_DAYS == 14
    assert r2_backup.DEFAULT_KEEP_DAILY == 7 and r2_backup.DEFAULT_KEEP_WEEKLY == 2
    assert r2_backup.DEFAULT_KEEP_DAILY < r2_backup.DEFAULT_MAX_AGE_DAYS
    # el backup más viejo posible que se conserva es el domingo de hace < 14 días
    hoy = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)  # domingo
    backups = [
        (
            (hoy - timedelta(days=d)).strftime("purgito-%Y%m%d-031701.dump.age"),
            1,
            None,
        )
        for d in range(40)
    ]
    _v, kept, _victims = r2_backup.prune_plan_gfs(backups, hoy)
    edades = [(hoy - r2_backup.backup_time(k)).days for k in kept]
    assert max(edades) < 14 and len(kept) <= 9


def test_la_lapida_dura_mas_que_el_backup_mas_viejo():
    assert db.DELETION_TOMBSTONE_RETENTION_DAYS >= r2_backup.DEFAULT_MAX_AGE_DAYS + 1
    assert r2_backup.DEFAULT_LEDGER_MAX_AGE_DAYS >= db.DELETION_TOMBSTONE_RETENTION_DAYS


def test_la_politica_de_privacidad_dice_lo_mismo_que_el_codigo():
    es = (ROOT / "docs" / "PRIVACY.md").read_text(encoding="utf-8")
    en = (ROOT / "docs" / "PRIVACY.en.md").read_text(encoding="utf-8")
    assert r2_backup.DEFAULT_KEEP_DAILY == 7 and r2_backup.DEFAULT_MAX_AGE_DAYS == 14
    assert "últimos 7 días" in es and "domingos" in es
    assert "14 días" in es and "15 días" in es
    assert "last 7 days" in en and "Sundays" in en
    assert "14 days" in en and "15 days" in en


# ─── guardia de espacio en disco ─────────────────────────────────────────────


@needs_shell_tools
def test_backup_db_no_empieza_si_no_queda_reserva_de_disco(tmp_path):
    stub = tmp_path / "fake-python"
    stub.write_text("#!/bin/bash\nexit 0\n")
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
    env.update(
        DATABASE_URL=os.environ["TEST_DATABASE_URL"],
        BACKUP_DIR=str(tmp_path / "backups"),
        PYTHON=str(stub),
        ENV_FILE=str(tmp_path / "sin-env"),
        BACKUP_AGE_RECIPIENTS=NEW_KEY,
        R2_BACKUP_BUCKET=BUCKET,
        MIN_FREE_MB="999999999",  # imposible: ningún disco tiene tanto libre
    )
    proc = subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup_db.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "espacio insuficiente" in proc.stderr and "No se hizo backup" in proc.stderr
    # no empezó: ni dump, ni temporales, ni nada en el directorio
    assert [p.name for p in (tmp_path / "backups").iterdir()] == []


@needs_shell_tools
def test_backup_db_con_espacio_de_sobra_no_deja_temporales(tmp_path):
    proc = _run_backup_sh(tmp_path, NEW_KEY)
    assert proc.returncode == 0, proc.stderr
    nombres = [p.name for p in (tmp_path / "backups").iterdir()]
    assert not any(n.endswith((".plain", ".partial")) for n in nombres)


# ─── access-check (separación de tokens) ─────────────────────────────────────

IMG, GIF = "purgito-images", "purgito-gifs"


def _tokens(monkeypatch, *, backups_denied, images_denied):
    """Dos "tokens" falsos sobre los mismos tres buckets, con permisos distintos."""
    bk = FakeS3(BUCKET, IMG, GIF)
    im = FakeS3(BUCKET, IMG, GIF)
    bk.denied = set(backups_denied)
    im.denied = set(images_denied)
    monkeypatch.setattr(r2, "get_backup_client", lambda: bk)
    monkeypatch.setattr(r2, "get_client", lambda: im)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BUCKET)
    monkeypatch.setenv("R2_IMAGES_BUCKET", IMG)
    monkeypatch.setenv("R2_GIFS_BUCKET", GIF)
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "clave-imagenes")
    monkeypatch.setenv("R2_BACKUP_ACCESS_KEY_ID", "clave-backups")
    return bk, im


def test_access_check_ok_cuando_los_tokens_estan_separados(monkeypatch, capsys):
    _tokens(monkeypatch, backups_denied={IMG, GIF}, images_denied={BUCKET})
    assert r2_backup.main(["access-check"]) == 0
    assert "ACCESS-CHECK: OK" in capsys.readouterr().out


def test_access_check_falla_si_el_token_de_imagenes_llega_a_los_backups(
    monkeypatch, capsys
):
    _tokens(monkeypatch, backups_denied={IMG, GIF}, images_denied=set())
    assert r2_backup.main(["access-check"]) == 1
    captured = capsys.readouterr()
    assert "ACCESS-CHECK: FALLÓ" in captured.out
    assert "token de imágenes/GIFs puede listar purgito-backups" in captured.err


def test_access_check_falla_si_el_token_de_backups_ve_imagenes(monkeypatch, capsys):
    _tokens(monkeypatch, backups_denied={GIF}, images_denied={BUCKET})
    assert r2_backup.main(["access-check"]) == 1
    assert "token de backups puede listar purgito-images" in capsys.readouterr().err


def test_access_check_falla_si_es_el_mismo_token(monkeypatch, capsys):
    _tokens(monkeypatch, backups_denied={IMG, GIF}, images_denied={BUCKET})
    monkeypatch.setenv("R2_BACKUP_ACCESS_KEY_ID", "clave-imagenes")
    assert r2_backup.main(["access-check"]) == 1
    assert "mismo token" in capsys.readouterr().err


def test_access_check_solo_lista_nunca_escribe_ni_borra(monkeypatch):
    bk, im = _tokens(monkeypatch, backups_denied={IMG, GIF}, images_denied={BUCKET})
    r2_backup.main(["access-check"])
    for fake in (bk, im):
        assert {c[0] for c in fake.calls} <= {"list_objects_v2"}


# ─── gen2_config.sh (configuración con vuelta atrás) ─────────────────────────

CONFIG_SH = ROOT / "deploy" / "gen2_config.sh"
ENV_ORIGINAL = (
    "DISCORD_TOKEN=secreto-que-no-se-toca\n"
    f"BACKUP_AGE_RECIPIENTS={OLD_KEY}\n"
    "R2_SECRET_ACCESS_KEY=otro-secreto\n"
    "WEB_PORT=8080\n"
)


def _config(tmp_path, *args, env_text=ENV_ORIGINAL):
    envf = tmp_path / ".env"
    if not envf.exists():
        envf.write_text(env_text)
        envf.chmod(0o600)
    proc = subprocess.run(
        ["bash", str(CONFIG_SH), *args],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "ENV_FILE": str(envf),
            "STATE_FILE": str(tmp_path / "estado" / "prev"),
        },
        timeout=30,
    )
    return proc, envf


def test_config_dry_run_no_cambia_nada(tmp_path):
    proc, envf = _config(tmp_path, "apply", NEW_KEY)
    assert proc.returncode == 0, proc.stderr
    assert envf.read_text() == ENV_ORIGINAL
    assert "dry-run" in proc.stdout
    assert not (tmp_path / "estado").exists()


def test_config_apply_cambia_solo_dos_variables_y_conserva_permisos(tmp_path):
    proc, envf = _config(tmp_path, "apply", NEW_KEY, "--yes")
    assert proc.returncode == 0, proc.stderr
    texto = envf.read_text()
    assert f"BACKUP_AGE_RECIPIENTS={NEW_KEY}" in texto
    assert "R2_BACKUP_PREFIX=gen2/" in texto
    assert OLD_KEY not in texto
    for intacta in (
        "DISCORD_TOKEN=secreto-que-no-se-toca",
        "R2_SECRET_ACCESS_KEY=otro-secreto",
        "WEB_PORT=8080",
    ):
        assert intacta in texto
    assert oct(envf.stat().st_mode & 0o777) == "0o600"
    # nunca se imprimen las otras líneas del .env
    assert "secreto" not in proc.stdout + proc.stderr
    state = tmp_path / "estado" / "prev"
    assert oct(state.stat().st_mode & 0o777) == "0o600"
    assert OLD_KEY in state.read_text()


def test_config_revert_restaura_el_env_exacto_y_quita_el_prefijo(tmp_path):
    _config(tmp_path, "apply", NEW_KEY, "--yes")
    proc, envf = _config(tmp_path, "revert", "--yes")
    assert proc.returncode == 0, proc.stderr
    assert sorted(envf.read_text().splitlines()) == sorted(ENV_ORIGINAL.splitlines())
    assert "R2_BACKUP_PREFIX" not in envf.read_text()
    assert oct(envf.stat().st_mode & 0o777) == "0o600"
    assert not (tmp_path / "estado" / "prev").exists()


def test_config_no_se_aplica_dos_veces_ni_con_la_clave_vieja_ni_con_basura(tmp_path):
    assert _config(tmp_path, "apply", NEW_KEY, "--yes")[0].returncode == 0
    assert (
        _config(tmp_path, "apply", NEW_KEY, "--yes")[0].returncode != 0
    )  # ya aplicado
    nuevo = tmp_path / "otro"
    nuevo.mkdir()
    assert _config(nuevo, "apply", OLD_KEY, "--yes")[0].returncode != 0  # revocada
    assert _config(nuevo, "apply", "age1corta", "--yes")[0].returncode != 0
    assert (nuevo / ".env").read_text() == ENV_ORIGINAL


def test_config_revert_sin_estado_falla_sin_tocar_el_env(tmp_path):
    proc, envf = _config(tmp_path, "revert", "--yes")
    assert proc.returncode != 0
    assert envf.read_text() == ENV_ORIGINAL
