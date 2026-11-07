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
from datetime import datetime, timedelta, timezone

import pytest
from fake_s3 import FakeS3

import r2

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKUP_BUCKET = "purgito-backups"
G = "gen2/"  # generación vigente de los backups dentro del bucket


def bk_keys(s3):
    """Keys de la generación vigente, sin el prefijo."""
    return {k[len(G) :] for k in s3.keys(BACKUP_BUCKET) if k.startswith(G)}


_spec = importlib.util.spec_from_file_location(
    "r2_backup", ROOT / "scripts" / "r2_backup.py"
)
r2_backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r2_backup)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3(BACKUP_BUCKET, "purgito-images", "purgito-gifs")
    monkeypatch.setattr(r2, "get_client", lambda: fake)
    monkeypatch.setattr(r2, "get_backup_client", lambda: fake)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BACKUP_BUCKET)
    return fake


def _files(tmp_path):
    db = tmp_path / "bot-20260812-031700.db"
    flags = tmp_path / "bot-20260812-031700.flags.tar.gz"
    # El bucket solo acepta archivos age: cabecera de age + cuerpo cualquiera.
    db.write_bytes(r2_backup.AGE_MAGIC + b"\n" + b"d" * 64)
    flags.write_bytes(r2_backup.AGE_MAGIC + b"\nflags")
    return db, flags


# ─── CLI ──────────────────────────────────────────────────────────────────────


def test_upload_sube_en_el_orden_pedido_y_solo_al_bucket_de_backups(
    s3, tmp_path, capsys
):
    db, flags = _files(tmp_path)

    rc = r2_backup.main(["upload", str(flags), str(db)])

    assert rc == 0
    puts = [key for _op, _bucket, key in s3.ops("put_object")]
    assert puts == [G + flags.name, G + db.name]  # los flags antes que la base
    assert bk_keys(s3) == {flags.name, db.name}
    assert s3.keys("purgito-images") == s3.keys("purgito-gifs") == set()
    assert "OK subido" in capsys.readouterr().out


def test_upload_falla_con_codigo_1_si_la_subida_falla(s3, tmp_path, capsys):
    db, flags = _files(tmp_path)
    s3.fail_put = True

    rc = r2_backup.main(["upload", str(flags), str(db)])

    assert rc == 1
    assert "ERROR" in capsys.readouterr().err
    assert bk_keys(s3) == set()


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
    assert bk_keys(s3) == set()


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
    s3.seed(BACKUP_BUCKET, G + "bot-20260812-031700.db", b"123")

    assert r2_backup.main(["list"]) == 0
    assert "bot-20260812-031700.db\t3" in capsys.readouterr().out


def test_download_latest_baja_el_dump_mas_reciente_con_permisos_0600(s3, tmp_path):
    viejo = tmp_path / "purgito-20261001-031700.dump"
    nuevo = tmp_path / "purgito-20261002-031700.dump"
    viejo.write_bytes(b"viejo")
    nuevo.write_bytes(b"nuevo")
    # un backup de la época SQLite en el mismo bucket no compite con `latest`
    legacy = tmp_path / "bot-20269999-999999.db"
    legacy.write_bytes(b"sqlite")
    for f in (viejo, nuevo, legacy):
        r2.upload_backup_file_sync(str(f))
    dest = tmp_path / "restore"

    assert r2_backup.main(["download", "latest", "--dest", str(dest)]) == 0

    assert [p.name for p in dest.iterdir()] == [nuevo.name]
    assert (dest / nuevo.name).read_bytes() == b"nuevo"
    for p in dest.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_download_de_un_backup_sqlite_viejo_baja_tambien_sus_flags(s3, tmp_path):
    db, flags = _files(tmp_path)
    for f in (flags, db):
        r2.upload_backup_file_sync(str(f))
    dest = tmp_path / "restore"

    assert r2_backup.main(["download", db.name, "--dest", str(dest)]) == 0

    assert sorted(p.name for p in dest.iterdir()) == [db.name, flags.name]


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
    f.write_bytes(r2_backup.AGE_MAGIC + b"\nx")
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
    assert "R2 de backups no está configurado" in proc.stderr


# ─── deploy/backup_db.sh: un backup solo local no cuenta como exitoso ─────────

needs_shell_tools = pytest.mark.skipif(
    shutil.which("pg_dump") is None
    or shutil.which("pg_restore") is None
    or shutil.which("bash") is None
    or shutil.which("age") is None
    or shutil.which("age-keygen") is None,
    reason="hace falta el cliente de PostgreSQL (pg_dump/pg_restore) y age",
)


@pytest.fixture
def age_keys(tmp_path):
    """Par de claves age de prueba: la privada vive solo en este tmp_path."""
    identity = tmp_path / "identity.txt"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    public = subprocess.run(
        ["age-keygen", "-y", str(identity)], check=True, capture_output=True, text=True
    ).stdout.strip()
    return identity, public


def _run_backup(
    tmp_path,
    python_stub: str,
    bucket: str | None = "purgito-backups",
    recipients: str | None = None,
    **extra_env,
):
    """Corre deploy/backup_db.sh contra una base de pruebas, con un intérprete
    falso en lugar del del venv (sin red, sin boto3)."""
    stub = tmp_path / "fake-python"
    stub.write_text(python_stub)
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("R2_")}
    env.update(
        DATABASE_URL=os.environ["TEST_DATABASE_URL"],
        BACKUP_DIR=str(tmp_path / "backups"),
        PYTHON=str(stub),
        ENV_FILE=str(tmp_path / "sin-env"),
        MIN_FREE_MB="1",
    )
    env.pop("BACKUP_AGE_RECIPIENTS", None)
    if bucket is not None:
        env["R2_BACKUP_BUCKET"] = bucket
    if recipients is not None:
        env["BACKUP_AGE_RECIPIENTS"] = recipients
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(ROOT / "deploy" / "backup_db.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@needs_shell_tools
def test_backup_db_no_reporta_exito_si_falla_la_subida_a_r2(tmp_path, age_keys):
    backups = tmp_path / "backups"
    backups.mkdir()
    viejo = backups / "purgito-19990101-000000.dump"
    viejo.write_bytes(b"viejo")

    proc = _run_backup(
        tmp_path, "#!/bin/bash\necho 'R2 caído' >&2\nexit 1\n", recipients=age_keys[1]
    )

    assert proc.returncode != 0
    assert " OK backup -> " not in proc.stdout + proc.stderr
    assert "NO subió a R2" in proc.stderr
    # el backup local se conserva, y no se poda nada (ni lo viejo)
    assert len(list(backups.glob("purgito-2*.dump.age"))) == 1
    assert viejo.exists()


@needs_shell_tools
def test_backup_db_sube_el_dump_y_reporta_la_subida(tmp_path, age_keys):
    log = tmp_path / "args.log"
    stub = f'#!/bin/bash\nprintf "%s\\n" "$@" >> "{log}"\n'

    proc = _run_backup(tmp_path, stub, recipients=age_keys[1])

    assert proc.returncode == 0, proc.stderr
    assert "subido a R2 (purgito-backups)" in proc.stdout
    args = log.read_text().splitlines()
    assert args[1] == "upload"
    uploaded = [pathlib.Path(a).name for a in args[2:3]]
    assert len(uploaded) == 1 and uploaded[0].endswith(".dump.age")


@needs_shell_tools
def test_backup_db_sin_bucket_configurado_queda_solo_local_y_lo_dice(
    tmp_path, age_keys
):
    proc = _run_backup(
        tmp_path, "#!/bin/bash\nexit 1\n", bucket=None, recipients=age_keys[1]
    )

    assert proc.returncode == 0, proc.stderr
    assert "solo local" in proc.stdout
    assert len(list((tmp_path / "backups").glob("purgito-*.dump.age"))) == 1


# ─── cifrado de los backups ───────────────────────────────────────────────────


def _residuos(backups: pathlib.Path):
    """Cualquier archivo que no sea un .dump.age (dump en claro, temporales)."""
    return [p.name for p in backups.iterdir() if not p.name.endswith(".dump.age")]


@needs_shell_tools
def test_el_backup_queda_cifrado_se_descifra_con_la_privada_y_se_restaura(
    tmp_path, age_keys
):
    identity, public = age_keys
    log = tmp_path / "args.log"
    stub = f'#!/bin/bash\nprintf "%s\\n" "$@" >> "{log}"\n'

    proc = _run_backup(tmp_path, stub, recipients=public)

    assert proc.returncode == 0, proc.stderr
    assert "cifrado con age (1 destinatario(s))" in proc.stdout
    backups = tmp_path / "backups"
    (enc,) = backups.glob("purgito-*.dump.age")
    assert _residuos(backups) == []  # ni dump en claro ni temporales
    assert stat.S_IMODE(enc.stat().st_mode) == 0o600
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700
    assert enc.read_bytes().startswith(r2_backup.AGE_MAGIC)
    # lo que no se puede: leerlo sin la clave
    assert b"PGDMP" not in enc.read_bytes()
    # con la privada: vuelve a ser un dump de PostgreSQL válido
    plain = tmp_path / "descifrado.dump"
    subprocess.run(
        ["age", "-d", "-i", str(identity), "-o", str(plain), str(enc)],
        check=True,
        capture_output=True,
    )
    assert plain.read_bytes().startswith(b"PGDMP")
    listing = subprocess.run(
        ["pg_restore", "--list", str(plain)], capture_output=True, text=True
    )
    assert listing.returncode == 0 and " TABLE DATA " in listing.stdout
    # y lo que se pidió subir es el cifrado, nunca el dump en claro
    uploaded = log.read_text().splitlines()[2:3]
    assert [pathlib.Path(a).name for a in uploaded] == [enc.name]


@needs_shell_tools
def test_varios_destinatarios_cualquiera_puede_descifrar(tmp_path, age_keys):
    identity, public = age_keys
    otra = tmp_path / "otra.txt"
    subprocess.run(["age-keygen", "-o", str(otra)], check=True, capture_output=True)
    otra_pub = subprocess.run(
        ["age-keygen", "-y", str(otra)], check=True, capture_output=True, text=True
    ).stdout.strip()

    proc = _run_backup(
        tmp_path,
        "#!/bin/bash\nexit 0\n",
        bucket=None,
        recipients=f"{public}, {otra_pub}",
    )

    assert proc.returncode == 0, proc.stderr
    assert "2 destinatario(s)" in proc.stdout
    (enc,) = (tmp_path / "backups").glob("purgito-*.dump.age")
    for ident in (identity, otra):
        out = subprocess.run(
            ["age", "-d", "-i", str(ident), str(enc)], capture_output=True
        )
        assert out.returncode == 0 and out.stdout.startswith(b"PGDMP")


@needs_shell_tools
def test_con_bucket_y_sin_destinatarios_no_se_hace_backup_ni_se_sube_nada(tmp_path):
    log = tmp_path / "args.log"
    stub = f'#!/bin/bash\nprintf "%s\\n" "$@" >> "{log}"\n'

    proc = _run_backup(tmp_path, stub, recipients=None)

    assert proc.returncode != 0
    assert "nunca se sube un dump en claro" in proc.stderr
    assert not log.exists()  # el uploader ni se invocó
    backups = tmp_path / "backups"
    assert list(backups.iterdir()) == []  # ni un dump en claro en disco


@needs_shell_tools
def test_sin_bucket_y_sin_destinatarios_queda_en_claro_solo_local_y_avisa(tmp_path):
    proc = _run_backup(tmp_path, "#!/bin/bash\nexit 1\n", bucket=None, recipients=None)

    assert proc.returncode == 0, proc.stderr
    assert "SIN CIFRAR" in proc.stdout
    (dump,) = (tmp_path / "backups").glob("purgito-*.dump")
    assert stat.S_IMODE(dump.stat().st_mode) == 0o600


@needs_shell_tools
def test_una_clave_publica_invalida_se_rechaza(tmp_path):
    proc = _run_backup(tmp_path, "#!/bin/bash\nexit 0\n", recipients="no-es-una-clave")

    assert proc.returncode != 0
    assert "no parece una clave pública age" in proc.stderr
    assert list((tmp_path / "backups").iterdir()) == []


@needs_shell_tools
def test_si_falla_el_cifrado_no_queda_el_dump_en_claro(tmp_path, age_keys):
    proc = _run_backup(
        tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1], AGE="false"
    )

    assert proc.returncode != 0
    assert "no se pudo cifrar" in proc.stderr
    assert list((tmp_path / "backups").iterdir()) == []


@needs_shell_tools
def test_un_archivo_cifrado_defectuoso_no_pasa_la_verificacion(tmp_path, age_keys):
    # Un "age" que escribe basura: la verificación de cabecera lo detecta.
    falso = tmp_path / "age-falso"
    falso.write_text(
        '#!/bin/bash\nwhile [ "$1" != "-o" ]; do shift; done\necho basura > "$2"\n'
    )
    falso.chmod(0o755)

    proc = _run_backup(
        tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1], AGE=str(falso)
    )

    assert proc.returncode != 0
    assert "no pasó la verificación" in proc.stderr
    assert list((tmp_path / "backups").iterdir()) == []


def test_upload_rechaza_un_dump_en_claro(s3, tmp_path, capsys):
    plano = tmp_path / "purgito-20261002-000000.dump"
    plano.write_bytes(b"PGDMP" + b"x" * 64)

    assert r2_backup.main(["upload", str(plano)]) == 1
    assert "no es un archivo cifrado con age" in capsys.readouterr().err
    assert s3.ops("put_object") == []


def test_upload_rechaza_todo_si_un_solo_archivo_esta_en_claro(s3, tmp_path):
    db, flags = _files(tmp_path)
    flags.write_bytes(b"en claro")

    assert r2_backup.main(["upload", str(flags), str(db)]) == 1
    assert s3.ops("put_object") == []  # ni siquiera el cifrado


def test_download_latest_elige_tambien_los_dump_age(s3, tmp_path):
    s3.seed(BACKUP_BUCKET, G + "purgito-20261001-000000.dump", b"viejo")
    s3.seed(BACKUP_BUCKET, G + "purgito-20261002-000000.dump.age", b"nuevo")

    assert r2_backup.main(["download", "latest", "--dest", str(tmp_path)]) == 0
    assert (tmp_path / "purgito-20261002-000000.dump.age").read_bytes() == b"nuevo"


# ─── retención en R2 (prune): MÁXIMO 2 backups, por cantidad y no por edad ────


def _b(nombre, size=1):
    return (nombre, size, None)


def _nombres(n):
    return [f"purgito-2026100{i + 1}-000000.dump.age" for i in range(n)]


@pytest.mark.parametrize(
    "cuantos,borra",
    [(0, 0), (1, 0), (2, 0), (3, 1), (4, 2), (7, 5)],
)
def test_prune_keep_last_2_deja_como_maximo_los_2_mas_recientes(cuantos, borra):
    backups = [_b(k) for k in _nombres(cuantos)]

    valid, kept, victims = r2_backup.prune_plan(backups, 2)

    assert len(valid) == cuantos
    assert len(victims) == borra
    assert kept == _nombres(cuantos)[-2:]  # el último y el anterior
    assert victims == _nombres(cuantos)[: cuantos - len(kept)]  # los más viejos
    assert len(kept) <= 2


def test_prune_el_default_es_2_y_no_hay_regla_de_los_3_mas_nuevos():
    assert r2_backup.DEFAULT_KEEP_LAST == 2
    _valid, kept, victims = r2_backup.prune_plan([_b(k) for k in _nombres(3)])
    assert len(kept) == 2 and len(victims) == 1


def test_prune_no_mira_la_edad_ni_borra_el_unico_backup():
    # Un solo backup, aunque tenga un año: se queda.
    assert r2_backup.prune_plan([_b("purgito-20250101-000000.dump.age")], 2)[2] == []


def test_prune_ordena_por_nombre_no_por_el_orden_en_que_llegan():
    barajados = [_b(k) for k in (_nombres(4)[2], _nombres(4)[0], _nombres(4)[3])]

    _valid, kept, victims = r2_backup.prune_plan(barajados, 2)

    assert kept == [_nombres(4)[2], _nombres(4)[3]]
    assert victims == [_nombres(4)[0]]


def test_prune_ignora_lo_que_no_es_un_backup_valido_de_purgito():
    backups = [
        _b("otra-cosa.txt"),
        _b("bot-20260101-000000.db"),  # época SQLite: ni cuenta ni se borra
        _b("purgito-20260101-000000.dump.age.partial"),
        _b("purgito-20260102-000000.dump.age", size=0),  # vacío: no es válido
        _b("purgito-20260103-000000.dump.age"),
        _b("purgito-20260104-000000.dump"),
        _b("purgito-20260105-000000.dump.age"),
    ]

    valid, kept, victims = r2_backup.prune_plan(backups, 2)

    assert valid == [
        "purgito-20260103-000000.dump.age",
        "purgito-20260104-000000.dump",
        "purgito-20260105-000000.dump.age",
    ]
    assert victims == ["purgito-20260103-000000.dump.age"]
    assert kept == [
        "purgito-20260104-000000.dump",
        "purgito-20260105-000000.dump.age",
    ]


def test_prune_keep_menor_que_1_se_rechaza():
    with pytest.raises(ValueError):
        r2_backup.prune_plan([_b(k) for k in _nombres(3)], 0)


def test_prune_cli_keep_menor_que_1_falla_sin_borrar(s3, capsys):
    for k in _nombres(3):
        s3.seed(BACKUP_BUCKET, G + k, b"x")

    assert r2_backup.main(["prune", "--keep", "0", "--apply"]) == 1
    assert len(bk_keys(s3)) == 3


@pytest.mark.parametrize("cuantos,quedan", [(1, 1), (2, 2), (3, 2), (4, 2)])
def test_prune_cli_apply_deja_2_y_dry_run_no_borra(s3, capsys, cuantos, quedan):
    for k in _nombres(cuantos):
        s3.seed(BACKUP_BUCKET, G + k, b"x")
    s3.seed(BACKUP_BUCKET, G + "bot-20260101-000000.db", b"sqlite")  # no se toca

    assert r2_backup.main(["prune"]) == 0  # dry-run
    out = capsys.readouterr().out
    assert f"R2 PRUNE: {cuantos} backup(s) válido(s)" in out
    assert len(bk_keys(s3)) == cuantos + 1

    assert r2_backup.main(["prune", "--apply"]) == 0
    out = capsys.readouterr().out
    assert f"R2 PRUNE: {quedan} conservado(s), {cuantos - quedan} borrados" in out
    assert bk_keys(s3) == set(_nombres(cuantos)[-quedan:]) | {"bot-20260101-000000.db"}
    if cuantos > 2:  # el log dice qué conservó y qué borró
        assert f"conservo {_nombres(cuantos)[-1]}" in out
        assert f"borrado {_nombres(cuantos)[0]}" in out


def test_prune_cli_prefix_acota_a_unos_objetos_de_prueba(s3):
    reales = _nombres(3)
    for k in reales:
        s3.seed(BACKUP_BUCKET, G + k, b"real")
    pruebas = [f"purgito-zztest-{i}.dump.age" for i in range(4)]
    for k in pruebas:
        s3.seed(BACKUP_BUCKET, G + k, b"prueba")

    assert r2_backup.main(["prune", "--prefix", "purgito-zztest-", "--apply"]) == 0

    assert bk_keys(s3) == set(reales) | set(pruebas[-2:])


def test_delete_backup_solo_acepta_keys_de_backup(s3):
    s3.seed(BACKUP_BUCKET, G + "purgito-20261001-000000.dump.age", b"x")

    for malo in ("../x", "gifs/ab/x.gif", "imagen.png", "purgito-x/../../y"):
        with pytest.raises(r2.BackupError, match="no parece un backup|no válida"):
            r2.delete_backup_sync(malo)
    r2.delete_backup_sync("purgito-20261001-000000.dump.age")
    assert bk_keys(s3) == set()


@needs_shell_tools
def test_backup_db_poda_r2_diaria_y_semanal_y_falla_si_la_poda_falla(
    tmp_path, age_keys
):
    log = tmp_path / "args.log"
    # el stub es el intérprete: recibe (uploader, subcomando, ...)
    stub = (
        f'#!/bin/bash\nprintf "%s\\n" "$@" >> "{log}"\n'
        '[ "$2" = prune-gfs ] && { echo "poda caída" >&2; exit 1; }\nexit 0\n'
    )

    proc = _run_backup(tmp_path, stub, recipients=age_keys[1])

    assert proc.returncode != 0
    assert "no se pudo podar" in proc.stderr
    assert "OK backup -> " in proc.stdout  # el de hoy sí quedó subido
    llamadas = log.read_text().splitlines()
    i = llamadas.index("prune-gfs")
    # 7 diarios + 2 semanales, nada de 14 días o más; ya no es "los N últimos"
    assert llamadas[i : i + 10] == [
        "prune-gfs",
        "--daily",
        "7",
        "--weekly",
        "2",
        "--max-age-days",
        "14",
        "--min-age-days",
        "6",
        "--apply",
    ]
    assert "--keep" not in llamadas


@needs_shell_tools
@pytest.mark.parametrize(
    "var,valor",
    [
        ("R2_KEEP_DAILY", "0"),
        ("R2_KEEP_DAILY", "x"),
        ("BACKUP_MAX_AGE_DAYS", "0"),
        ("R2_KEEP_WEEKLY", "-1"),
        ("R2_KEEP_DAILY", "15"),
    ],
)
def test_backup_db_rechaza_retencion_r2_invalida_sin_hacer_backup(
    tmp_path, age_keys, var, valor
):
    proc = _run_backup(
        tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1], **{var: valor}
    )
    assert proc.returncode != 0
    assert "No se hizo backup" in proc.stderr
    assert not list((tmp_path / "backups").glob("purgito-2*"))


@needs_shell_tools
def test_backup_db_avisa_por_webhook_cuando_falla_y_no_filtra_la_url(
    tmp_path, age_keys
):
    """BACKUP_ALERT_WEBHOOK recibe un aviso (sin secretos) si el backup falla; si el
    webhook está caído el resultado del backup no cambia."""
    curl_log = tmp_path / "curl.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_curl = bindir / "curl"
    fake_curl.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" >> "{curl_log}"\nexit 22\n')
    fake_curl.chmod(0o755)
    url = "https://discord.example/api/webhooks/123/SECRETO"

    proc = _run_backup(
        tmp_path,
        "#!/bin/bash\necho 'R2 caído' >&2\nexit 1\n",
        recipients=age_keys[1],
        BACKUP_ALERT_WEBHOOK=url,
        PATH=f"{bindir}:{os.environ['PATH']}",
    )

    assert proc.returncode == 1  # el curl roto no lo cambia
    assert "FALLÓ" in curl_log.read_text()
    assert "SECRETO" not in proc.stdout + proc.stderr


@needs_shell_tools
def test_backup_db_no_avisa_si_todo_sale_bien(tmp_path, age_keys):
    curl_log = tmp_path / "curl.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_curl = bindir / "curl"
    fake_curl.write_text(f'#!/bin/bash\nprintf "x" >> "{curl_log}"\n')
    fake_curl.chmod(0o755)
    proc = _run_backup(
        tmp_path,
        "#!/bin/bash\nexit 0\n",
        recipients=age_keys[1],
        BACKUP_ALERT_WEBHOOK="https://discord.example/api/webhooks/1/x",
        PATH=f"{bindir}:{os.environ['PATH']}",
    )
    assert proc.returncode == 0, proc.stderr
    assert not curl_log.exists()


# ─── deploy/backup_db.sh: retención local KEEP_LAST=2 y logs ──────────────────


def _backups_previos(tmp_path, nombres, extra=()):
    d = tmp_path / "backups"
    d.mkdir(exist_ok=True)
    for n in nombres:
        (d / n).write_bytes(b"x")
    for n in extra:
        (d / n).write_bytes(b"x")
    return d


def _dump_age(d):
    return sorted(p.name for p in d.glob("purgito-*.dump.age"))


# Fechas relativas a hoy (1 a 3 días): el tope de edad de la poda local (13 días) no entra en juego.
PREVIOS = [
    f"purgito-{(datetime.now(timezone.utc) - timedelta(days=d)).strftime('%Y%m%d')}-000000.dump.age"
    for d in (3, 2, 1)
]


@needs_shell_tools
@pytest.mark.parametrize("previos", [0, 1, 2, 3])
def test_backup_db_local_conserva_como_maximo_2_con_el_nuevo(
    tmp_path, age_keys, previos
):
    # 0 previos + el nuevo = 1 backup (se conserva); 1 + nuevo = 2 (ambos);
    # 2 + nuevo = 3 -> borra el más viejo; 3 + nuevo = 4 -> borra 2.
    d = _backups_previos(tmp_path, PREVIOS[:previos])

    proc = _run_backup(tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1])

    assert proc.returncode == 0, proc.stderr
    quedan = _dump_age(d)
    nuevo = quedan[-1]
    assert nuevo not in PREVIOS  # el último es el que acaba de hacer
    assert quedan == (PREVIOS[:previos] + [nuevo])[-2:]
    assert len(quedan) == min(previos + 1, 2)
    assert f"LOCAL PRUNE: {previos + 1} backup(s) válido(s)" in proc.stdout


@needs_shell_tools
def test_backup_db_local_nunca_deja_mas_de_2_ni_siquiera_con_muchos(tmp_path, age_keys):
    hoy = datetime.now(timezone.utc)
    nombres = [
        f"purgito-{(hoy - timedelta(days=d)).strftime('%Y%m%d')}-000000.dump.age"
        for d in range(9, 0, -1)  # 9 copias de hace 1 a 9 días: dentro del tope de edad
    ]
    d = _backups_previos(tmp_path, nombres)

    proc = _run_backup(tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1])

    assert proc.returncode == 0, proc.stderr
    quedan = _dump_age(d)
    assert len(quedan) == 2
    assert quedan[0] == nombres[-1]  # el anterior
    assert "10 backup(s) válido(s)" in proc.stdout
    assert "conservo " + nombres[-1] in proc.stdout
    assert "borrado " + nombres[0] in proc.stdout
    assert "2 conservado(s), 8 borrado(s)" in proc.stdout


@needs_shell_tools
def test_backup_db_local_no_toca_nada_que_no_sea_un_backup_ni_la_edad_cuenta(
    tmp_path, age_keys
):
    otros = ("backup.log", "bot-sqlite-pre-cutover.db", "pg_hba.conf.pre-hardening.bak")
    d = _backups_previos(tmp_path, PREVIOS, extra=otros)
    for n in PREVIOS + list(otros):
        os.utime(d / n, (1, 1))  # 1970: la edad no decide nada

    proc = _run_backup(tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1])

    assert proc.returncode == 0, proc.stderr
    assert all((d / n).exists() for n in otros)
    assert len(_dump_age(d)) == 2


@needs_shell_tools
def test_backup_db_keep_last_se_puede_ajustar_pero_nunca_a_menos_de_1(
    tmp_path, age_keys
):
    d = _backups_previos(tmp_path, PREVIOS)

    proc = _run_backup(
        tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1], KEEP_LAST="1"
    )
    assert proc.returncode == 0, proc.stderr
    assert len(_dump_age(d)) == 1

    for malo in ("0", "-1", "dos", ""):
        antes = _dump_age(d)
        proc = _run_backup(
            tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1], KEEP_LAST=malo
        )
        if malo == "":
            assert proc.returncode == 0  # vacío = default 2
            continue
        assert proc.returncode != 0 and "KEEP_LAST" in proc.stderr
        assert _dump_age(d) == antes  # ni backup ni poda


@needs_shell_tools
def test_backup_db_loguea_cada_etapa_en_orden_sin_secretos(tmp_path, age_keys):
    proc = _run_backup(tmp_path, "#!/bin/bash\nexit 0\n", recipients=age_keys[1])

    assert proc.returncode == 0, proc.stderr
    etapas = [
        "BACKUP START",
        "DUMP CREATED",
        "DUMP VERIFIED",
        "ENCRYPTED",
        "UPLOADED",
        "LOCAL PRUNE",
        "BACKUP COMPLETE",
    ]
    posiciones = [proc.stdout.index(e) for e in etapas]
    assert posiciones == sorted(posiciones)
    assert "AGE-SECRET-KEY" not in proc.stdout + proc.stderr
    assert "PGPASSWORD" not in proc.stdout + proc.stderr


@needs_shell_tools
def test_backup_db_avisa_si_queda_un_retention_days_viejo(tmp_path, age_keys):
    proc = _run_backup(
        tmp_path,
        "#!/bin/bash\nexit 0\n",
        recipients=age_keys[1],
        RETENTION_DAYS="14",
    )

    assert proc.returncode == 0, proc.stderr
    assert "RETENTION_DAYS ya no se usa" in proc.stderr


# ─── token de backups independiente ──────────────────────────────────────────


def _reset_backup_client(monkeypatch):
    monkeypatch.setattr(r2, "_backup_client", None)
    monkeypatch.setattr(r2, "_backup_checked", False)


def test_el_token_de_imagenes_no_sirve_para_los_backups(monkeypatch):
    """Sin R2_BACKUP_ACCESS_KEY_ID/SECRET no hay cliente de backups, aunque estén las
    credenciales de imágenes y GIFs: nunca se cae en ellas."""
    _reset_backup_client(monkeypatch)
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "img-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "img-secret")
    monkeypatch.delenv("R2_BACKUP_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_BACKUP_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("R2_BACKUP_BUCKET", BACKUP_BUCKET)
    assert r2.get_backup_client() is None
    assert r2.backups_available() is False
    with pytest.raises(r2.BackupError, match="no se usa para los backups"):
        r2.list_backups_sync()


def test_el_cliente_de_backups_usa_solo_sus_credenciales(monkeypatch):
    _reset_backup_client(monkeypatch)
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "img-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "img-secret")
    monkeypatch.setenv("R2_BACKUP_ACCESS_KEY_ID", "bak-key")
    monkeypatch.setenv("R2_BACKUP_SECRET_ACCESS_KEY", "bak-secret")
    client = r2.get_backup_client()
    assert client is not None
    assert client._request_signer._credentials.access_key == "bak-key"


@pytest.mark.parametrize(
    "key",
    ["../x", "purgito-1/../2", "ledger/", "ledger/a/b", "images/a.png", "/purgito-x"],
)
def test_delete_backup_rechaza_keys_que_no_son_backups(s3, key):
    with pytest.raises(r2.BackupError):
        r2.delete_backup_sync(key)


# ─── retención diaria + semanal (política de privacidad: máximo 14 días) ─────


_NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)  # jueves


def _dump(dt, ext=".dump.age"):
    return _b("purgito-" + dt.strftime("%Y%m%d-%H%M%S") + ext)


def _diarios(dias, hora=3):
    return [
        _dump((_NOW - timedelta(days=d)).replace(hour=hora, minute=17, second=1))
        for d in range(dias)
    ]


def test_gfs_con_backups_diarios_deja_7_diarios_y_2_domingos_y_nada_de_14_dias():
    backups = _diarios(30)
    valid, kept, victims = r2_backup.prune_plan_gfs(backups, _NOW)
    ages = [(_NOW - r2_backup.backup_time(k)).days for k in kept]
    assert max(ages) < 14
    assert len(kept) <= 9
    # los 7 días más recientes están
    assert all(
        _dump(_NOW.replace(hour=3, minute=17, second=1) - timedelta(days=d))[0] in kept
        for d in range(7)
    )
    # los dos domingos (8 y 1 de noviembre)
    assert "purgito-20261108-031701.dump.age" in kept
    assert "purgito-20261101-031701.dump.age" in kept
    assert set(kept) | set(victims) == set(valid)
    assert not set(kept) & set(victims)


def test_gfs_nunca_conserva_nada_de_14_dias_o_mas_aunque_sea_domingo():
    backups = _diarios(20)
    _valid, kept, _victims = r2_backup.prune_plan_gfs(backups, _NOW)
    for k in kept:
        assert _NOW - r2_backup.backup_time(k) < timedelta(days=14)


def test_gfs_se_niega_a_podar_si_el_mas_nuevo_ya_es_viejo():
    backups = [_dump(_NOW - timedelta(days=15)), _dump(_NOW - timedelta(days=20))]
    with pytest.raises(r2_backup.PrunePlanError):
        r2_backup.prune_plan_gfs(backups, _NOW)


def test_gfs_el_mas_nuevo_siempre_se_conserva_y_pocos_backups_no_borran_nada():
    backups = _diarios(3)
    _valid, kept, victims = r2_backup.prune_plan_gfs(backups, _NOW)
    assert victims == [] and len(kept) == 3


def test_gfs_con_varios_backups_el_mismo_dia_deja_el_mas_reciente():
    a = _dump(_NOW.replace(hour=1, minute=0))
    b = _dump(_NOW.replace(hour=2, minute=0))
    _valid, kept, victims = r2_backup.prune_plan_gfs([a, b], _NOW)
    assert kept == [b[0]] and victims == [a[0]]


def test_gfs_no_toca_lo_que_no_es_un_backup_de_purgito_ni_los_sin_fecha():
    backups = _diarios(10) + [
        _b("privacy-prefs.csv.age"),
        _b("luks-header-20261105.img.age"),
        _b("purgito-sin-fecha.dump.age"),
    ]
    valid, kept, victims = r2_backup.prune_plan_gfs(backups, _NOW)
    assert "privacy-prefs.csv.age" not in valid
    assert "purgito-sin-fecha.dump.age" in kept
    assert "purgito-sin-fecha.dump.age" not in victims


@pytest.mark.parametrize(
    "daily,weekly,age", [(0, 2, 14), (7, -1, 14), (7, 2, 0), (15, 2, 14)]
)
def test_gfs_parametros_invalidos_se_rechazan(daily, weekly, age):
    with pytest.raises(ValueError):
        r2_backup.prune_plan_gfs(_diarios(3), _NOW, daily, weekly, age)


def test_gfs_cli_apply_borra_solo_los_victimas_y_dry_run_no_borra(s3, capsys):
    ahora = datetime.now(timezone.utc)
    for d in range(20):
        s3.seed(BACKUP_BUCKET, G + _dump(ahora - timedelta(days=d))[0])
    s3.seed(BACKUP_BUCKET, G + "privacy-prefs.csv.age")
    antes = len(bk_keys(s3))
    assert r2_backup.main(["prune-gfs"]) == 0
    assert len(bk_keys(s3)) == antes
    assert r2_backup.main(["prune-gfs", "--apply"]) == 0
    quedan = bk_keys(s3)
    assert "privacy-prefs.csv.age" in quedan
    assert len(quedan) <= 9 + 1


def test_check_falla_si_el_ultimo_backup_es_viejo(s3):
    ahora = datetime.now(timezone.utc)
    s3.seed(BACKUP_BUCKET, G + _dump(ahora - timedelta(hours=60))[0])
    assert r2_backup.main(["check", "--max-age-hours", "36"]) == 1
    s3.seed(BACKUP_BUCKET, G + _dump(ahora - timedelta(hours=2))[0])
    assert r2_backup.main(["check", "--max-age-hours", "36"]) == 0


def test_check_falla_sin_backups(s3):
    assert r2_backup.main(["check"]) == 1


def _ledger_key(dt):
    return "ledger/privacy-ledger-" + dt.strftime("%Y%m%dT%H%M%S") + "Z.jsonl.age"


def test_ledger_prune_borra_lo_vencido_pero_conserva_las_3_mas_nuevas():
    viejos = [
        (_ledger_key(_NOW - timedelta(days=20, hours=h)), 5, None) for h in range(6)
    ]
    keys, kept, victims = r2_backup.prune_plan_ledger(viejos, _NOW)
    assert len(kept) == 3 and len(victims) == 3
    assert set(kept) == set(sorted(k for k, _s, _m in viejos)[-3:])


def test_ledger_prune_adelgaza_conservando_recientes_una_por_hora_y_una_por_dia():
    items = [
        (_ledger_key(_NOW - timedelta(minutes=5 * n)), 5, None)
        for n in range(12 * 24 * 14)  # 14 días a ritmo de 5 min
    ]
    keys, kept, victims = r2_backup.prune_plan_ledger(items, _NOW)
    assert len(keys) == len(kept) + len(victims)
    ages = sorted(_NOW - r2_backup.ledger_time(k) for k in kept)
    assert len(kept) <= 140
    # las últimas 6 h, completas (cada 5 min)
    assert sum(1 for a in ages if a < timedelta(hours=6)) == 72
    # entre 6 y 48 h: a lo sumo una por hora UTC; después, a lo sumo una por día UTC
    horas = {}
    for k in kept:
        t = r2_backup.ledger_time(k)
        if timedelta(hours=6) <= _NOW - t < timedelta(hours=48):
            horas[(t.date(), t.hour)] = horas.get((t.date(), t.hour), 0) + 1
    assert horas and max(horas.values()) == 1
    # siempre quedan las 3 más recientes y la más nueva de cada día
    assert set(sorted(keys)[-3:]) <= set(kept)
    # lo conservado es siempre lo más nuevo de su franja: ninguna víctima es más nueva que su sustituta
    assert max(r2_backup.ledger_time(k) for k in victims) < _NOW - timedelta(hours=6)


def test_ledger_prune_max_delete_acota_cada_pasada(s3):
    for n in range(40):
        s3.seed(
            BACKUP_BUCKET,
            G
            + _ledger_key(
                datetime.now(timezone.utc) - timedelta(days=3, minutes=5 * n)
            ),
            b"x",
        )
    antes = len(s3.ops("delete_object"))
    assert (
        r2_backup.main(["prune-ledger", "--apply", "--thin", "--max-delete", "5"]) == 0
    )
    assert len(s3.ops("delete_object")) - antes == 5


def test_ledger_prune_no_borra_lo_reciente_ni_otras_keys():
    items = [(_ledger_key(_NOW - timedelta(hours=h)), 5, None) for h in range(48)]
    items += [("privacy-prefs.csv.age", 5, None), ("ledger/otra-cosa.txt", 5, None)]
    _keys, _kept, victims = r2_backup.prune_plan_ledger(items, _NOW)
    assert victims == []
