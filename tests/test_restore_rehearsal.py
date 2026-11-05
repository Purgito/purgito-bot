"""Ensayo completo de desastre con los scripts reales: un backup VIEJO restaurado no puede
reintroducir lo que se borró después, ni perder una exclusión.

pg_dump (backup viejo) -> borrados y exclusión "en vivo" -> export_privacy_ledger.py (cifrado con
age) -> restauración del backup viejo (los borrados reaparecen: ese es el riesgo) -> descifrado
y reapply_deletions.py --ledger -  -> los borrados vuelven a aplicarse y la exclusión regresa.
Se hace sobre la base de pruebas con una clave age desechable.
"""

import asyncio
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import db
import pg_support

ROOT = pathlib.Path(__file__).resolve().parent.parent
needs_tools = pytest.mark.skipif(
    not all(
        shutil.which(t) for t in ("age", "age-keygen", "pg_dump", "pg_restore", "psql")
    ),
    reason="faltan age o los clientes de PostgreSQL",
)


def psql(sql):
    out = subprocess.run(
        ["psql", "-X", "-A", "-t", os.environ["TEST_DATABASE_URL"], "-c", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def count(sql):
    return int(psql(f"SELECT count(*) FROM {sql}"))


@needs_tools
def test_un_backup_viejo_no_reintroduce_borrados_ni_pierde_exclusiones(
    tmp_path, monkeypatch
):
    url = os.environ["TEST_DATABASE_URL"]
    conn = asyncio.run(pg_support.connect())
    monkeypatch.setattr(db, "_db", conn)

    # 1) Estado "antiguo": dos usuarios en dos servidores (1 y 500).
    for guild in (1, 500):
        for user in (10, 20):
            for i in range(2):
                mid = guild * 1000 + user * 10 + i
                psql(
                    "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
                    f"VALUES ({guild}, 1, {mid}, 'x');"
                    "INSERT INTO user_corpus (guild_id, author_id, author_name, channel_id, message_id, content) "
                    f"VALUES ({guild}, {user}, 'n', 1, {mid}, 'x')"
                )

    # 2) Backup viejo.
    old = tmp_path / "viejo.dump"
    subprocess.run(["pg_dump", "-Fc", "--no-owner", "-f", str(old), url], check=True)

    # 3) Cosas que pasan DESPUÉS del backup, con el código real de producción.
    asyncio.run(db.delete_user_data(10))  # /borrar_mis_datos
    asyncio.run(
        db.purge_guild_data(500)
    )  # el bot salió del servidor y pasaron los 30 días
    asyncio.run(
        db.set_user_exclusion(1, 20, exclude_interaction=False, exclude_learning=True)
    )
    assert count("user_corpus WHERE author_id=10") == 0
    assert count("corpus_messages WHERE guild_id=500") == 0

    # 4) Registro externo cifrado (clave age desechable, sin subir a ningún sitio).
    ident = tmp_path / "id.txt"
    subprocess.run(["age-keygen", "-o", str(ident)], check=True, capture_output=True)
    pub = subprocess.run(
        ["age-keygen", "-y", str(ident)], check=True, capture_output=True, text=True
    ).stdout.strip()
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "BACKUP_AGE_RECIPIENTS": pub,
        "BACKUP_DIR": str(tmp_path / "bk"),
    }
    exp = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "export_privacy_ledger.py"),
            "--no-upload",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert exp.returncode == 0, exp.stderr
    ledger = next((tmp_path / "bk" / "ledger").glob("privacy-ledger-*.jsonl.age"))
    assert b"tombstone" not in ledger.read_bytes()  # cifrado de verdad

    # 5) DESASTRE: se restaura el backup viejo. Las lápidas y la exclusión no están en él.
    asyncio.run(conn.close())
    subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "-d", url, str(old)],
        check=True,
        capture_output=True,
    )
    assert count("user_corpus WHERE author_id=10") == 4, (
        "el riesgo: los datos borrados reaparecen"
    )
    assert count("corpus_messages WHERE guild_id=500") == 4
    assert count("excluded_users") == 0
    assert count("deleted_user_tombstones") == 0

    # 6) Recuperación: descifrar en el equipo del titular y reaplicar ANTES de arrancar el bot.
    claro = subprocess.run(
        ["age", "-d", "-i", str(ident), str(ledger)], check=True, capture_output=True
    ).stdout
    seco = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reapply_deletions.py"),
            "--dsn",
            url,
            "--ledger",
            "-",
        ],
        input=claro,
        capture_output=True,
        cwd=tmp_path,
    )
    assert seco.returncode == 0, seco.stderr
    assert count("user_corpus WHERE author_id=10") == 4  # el dry-run no tocó nada
    ap = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reapply_deletions.py"),
            "--dsn",
            url,
            "--ledger",
            "-",
            "--apply",
        ],
        input=claro,
        capture_output=True,
        cwd=tmp_path,
    )
    assert ap.returncode == 0, ap.stderr

    # 7) Resultado: lo borrado sigue borrado, la exclusión volvió, lo demás intacto.
    assert count("user_corpus WHERE author_id=10") == 0
    assert count("corpus_messages WHERE guild_id=500") == 0
    assert count("user_corpus WHERE guild_id=500") == 0
    assert count("user_corpus WHERE author_id=20 AND guild_id=1") == 2
    assert (
        psql(
            "SELECT exclude_learning FROM excluded_users WHERE guild_id=1 AND user_id=20"
        )
        == "1"
    )
    assert count("deleted_user_tombstones WHERE user_id=10") == 1
    assert count("purged_guild_tombstones WHERE purged_guild_id=500") == 1
