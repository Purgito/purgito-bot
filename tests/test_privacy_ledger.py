"""Registro de eliminaciones fuera de la base: lápida de servidores purgados,
instantánea cifrada, y reaplicación tras restaurar un backup anterior.

Lo que importa: un restore viejo no puede devolver datos de usuarios o servidores ya
borrados, ni perder exclusiones, aunque la base original (con sus lápidas) se haya perdido.
"""

import asyncio
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

import db
import pg_support
import pgsync
import privacy_ledger
from fake_s3 import FakeS3

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reapply_deletions = _load("reapply_deletions", "scripts/reapply_deletions.py")
export_ledger = _load("export_privacy_ledger", "scripts/export_privacy_ledger.py")

FMT = "%Y-%m-%d %H:%M:%S"
needs_age = pytest.mark.skipif(
    not (shutil.which("age") and shutil.which("age-keygen")), reason="falta age"
)


@pytest.fixture
def conn(monkeypatch):
    c = asyncio.run(pg_support.connect())
    monkeypatch.setattr(db, "_db", c)
    yield c
    asyncio.run(c.close())


def _sql(conn, sql, params=()):
    return asyncio.run(conn.execute(sql, params))


async def _fetch(conn, sql, params):
    cur = await conn.execute(sql, params)
    return await cur.fetchall()


def _rows(conn, sql, params=()):
    return asyncio.run(_fetch(conn, sql, params))


def _ts(delta_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime(FMT)


def _sync(fn):
    c = pgsync.connect(os.environ["TEST_DATABASE_URL"])
    try:
        out = fn(c)
        c.commit()
        return out
    finally:
        c.close()


def _seed_guild(conn, guild, n=3):
    for i in range(n):
        _sql(
            conn,
            "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
            "VALUES (?, 1, ?, 'x')",
            (guild, guild * 100 + i),
        )


# ─── purge_guild_data deja lápida ────────────────────────────────────────────


def test_purge_de_un_servidor_deja_una_lapida_sin_contenido(conn):
    _seed_guild(conn, 555)
    asyncio.run(db.purge_guild_data(555))
    assert (
        _rows(conn, "SELECT count(*) FROM corpus_messages WHERE guild_id=555")[0][0]
        == 0
    )
    filas = _rows(
        conn,
        "SELECT purged_guild_id, purged_at, expires_at FROM purged_guild_tombstones",
    )
    assert len(filas) == 1 and filas[0][0] == 555
    dias = (
        datetime.strptime(filas[0][2], FMT) - datetime.strptime(filas[0][1], FMT)
    ).days
    assert dias == db.DELETION_TOMBSTONE_RETENTION_DAYS


def test_la_lapida_de_servidor_dura_mas_que_la_antiguedad_maxima_de_un_backup():
    # Política de privacidad: ningún backup supera 14 días; la lápida, 14 + 1 de margen.
    assert db.DELETION_TOMBSTONE_RETENTION_DAYS >= 14 + 1


def test_la_lapida_de_servidor_no_la_borra_la_propia_purga(conn):
    asyncio.run(db.purge_guild_data(7))
    asyncio.run(db.purge_guild_data(7))  # idempotente: sigue habiendo una sola
    assert _rows(conn, "SELECT count(*) FROM purged_guild_tombstones")[0][0] == 1


def test_purgar_vencidas_borra_tambien_las_lapidas_de_servidor(conn):
    _sql(
        conn,
        "INSERT INTO purged_guild_tombstones VALUES (1, ?, ?)",
        (_ts(-20), _ts(-5)),
    )
    _sql(
        conn,
        "INSERT INTO purged_guild_tombstones VALUES (2, ?, ?)",
        (_ts(-1), _ts(14)),
    )
    n = asyncio.run(db.purge_expired_deletion_tombstones())
    assert n == 1
    assert [
        r[0] for r in _rows(conn, "SELECT purged_guild_id FROM purged_guild_tombstones")
    ] == [2]


def test_si_la_purga_falla_no_queda_lapida(conn, monkeypatch):
    monkeypatch.setattr(db, "_GUILD_PURGE_TABLES", ("tabla_que_no_existe",))
    with pytest.raises(Exception):
        asyncio.run(db.purge_guild_data(9))
    assert _rows(conn, "SELECT count(*) FROM purged_guild_tombstones")[0][0] == 0


# ─── instantánea ─────────────────────────────────────────────────────────────


def _seed_registro(conn):
    _sql(
        conn,
        "INSERT INTO deleted_user_tombstones VALUES (10, ?, ?)",
        (_ts(-1), _ts(14)),
    )
    _sql(
        conn,
        "INSERT INTO deleted_user_tombstones VALUES (11, ?, ?)",
        (_ts(-30), _ts(-15)),
    )
    _sql(
        conn,
        "INSERT INTO purged_guild_tombstones VALUES (500, ?, ?)",
        (_ts(-2), _ts(13)),
    )
    _sql(
        conn,
        "INSERT INTO purged_guild_tombstones VALUES (501, ?, ?)",
        (_ts(-30), _ts(-15)),
    )
    _sql(
        conn,
        "INSERT INTO excluded_users (guild_id, user_id, exclude_interaction, exclude_learning) "
        "VALUES (1, 77, 1, 1)",
    )


def test_la_instantanea_lleva_solo_lapidas_vigentes_y_las_exclusiones(conn):
    _seed_registro(conn)
    records = _sync(privacy_ledger.build_snapshot)
    tipos = [r["type"] for r in records]
    assert tipos[0] == "header" and tipos[-1] == "footer"
    counts = records[-1]["counts"]
    # El ancla del registro depende de lo que haya en privacy_request_log (0 o 1): se comprueba aparte.
    assert {
        k: counts[k]
        for k in ("user_tombstone", "guild_tombstone", "exclusion", "deletion_request")
    } == {
        "user_tombstone": 1,
        "guild_tombstone": 1,
        "exclusion": 1,
        "deletion_request": 0,
    }
    assert counts["log_anchor"] in (0, 1)
    ids = {r.get("user_id") for r in records if r["type"] == "user_tombstone"}
    assert ids == {10}  # la vencida (11) no se exporta


def test_la_instantanea_no_lleva_contenido_de_mensajes(conn):
    _seed_guild(conn, 1)
    _seed_registro(conn)
    texto = privacy_ledger.dumps(_sync(privacy_ledger.build_snapshot))
    assert "content" not in texto and '"x"' not in texto


def test_ida_y_vuelta_de_la_instantanea(conn):
    _seed_registro(conn)
    texto = privacy_ledger.dumps(_sync(privacy_ledger.build_snapshot))
    led = privacy_ledger.loads(texto)
    assert [r["user_id"] for r in led["user_tombstones"]] == [10]
    assert [r["guild_id"] for r in led["guild_tombstones"]] == [500]
    assert led["exclusions"][0]["exclude_learning"] == 1


@pytest.mark.parametrize(
    "mutar",
    [
        lambda t: "\n".join(t.splitlines()[:-1]),  # sin pie
        lambda t: t.replace('"version":1', '"version":99'),
        lambda t: "{no es json",
        lambda t: "",
        lambda t: t.replace('"user_tombstone":1', '"user_tombstone":5'),
        lambda t: t.replace('"user_id":10', '"user_id":"10"'),
    ],
)
def test_una_instantanea_corrupta_o_truncada_se_rechaza(conn, mutar):
    _seed_registro(conn)
    texto = privacy_ledger.dumps(_sync(privacy_ledger.build_snapshot))
    with pytest.raises(privacy_ledger.LedgerError):
        privacy_ledger.loads(mutar(texto))


# ─── restore viejo + registro externo ────────────────────────────────────────


def _restaurar_un_backup_viejo(conn):
    """Estado de un backup anterior a los borrados: datos vivos, sin lápidas."""
    for user in (10, 20):
        for g in (1, 500):
            for i in range(2):
                mid = g * 1000 + user * 10 + i
                _sql(
                    conn,
                    "INSERT INTO corpus_messages (guild_id, channel_id, message_id, content) "
                    "VALUES (?, 1, ?, 'x')",
                    (g, mid),
                )
                _sql(
                    conn,
                    "INSERT INTO user_corpus (guild_id, author_id, author_name, channel_id, "
                    "message_id, content) VALUES (?, ?, 'n', 1, ?, 'x')",
                    (g, user, mid),
                )


def _ledger_de(user_ts=True, guild_ts=True, exclusion=True):
    now = datetime.now(timezone.utc)
    recs = [{"type": "header", "version": 1, "exported_at": now.strftime(FMT)}]
    n = {"user_tombstone": 0, "guild_tombstone": 0, "exclusion": 0}
    if user_ts:
        recs.append(
            {
                "type": "user_tombstone",
                "user_id": 10,
                "deleted_at": _ts(-1),
                "expires_at": _ts(14),
            }
        )
        n["user_tombstone"] = 1
    if guild_ts:
        recs.append(
            {
                "type": "guild_tombstone",
                "guild_id": 500,
                "purged_at": _ts(-1),
                "expires_at": _ts(14),
            }
        )
        n["guild_tombstone"] = 1
    if exclusion:
        recs.append(
            {
                "type": "exclusion",
                "guild_id": 1,
                "user_id": 20,
                "exclude_interaction": 0,
                "exclude_learning": 1,
                "created_at": _ts(-3),
            }
        )
        n["exclusion"] = 1
    recs.append({"type": "footer", "counts": n})
    return privacy_ledger.loads(privacy_ledger.dumps(recs))


def test_un_restore_viejo_sin_lapidas_se_corrige_con_el_registro_externo(conn):
    _restaurar_un_backup_viejo(conn)
    assert _rows(conn, "SELECT count(*) FROM deleted_user_tombstones")[0][0] == 0

    def aplicar(c):
        merged = reapply_deletions.merge_ledger(c, _ledger_de())
        stats = reapply_deletions.reapply(c, apply=True)
        return merged, stats

    merged, stats = _sync(aplicar)

    assert merged == {
        "lapidas_usuario": 1,
        "lapidas_servidor": 1,
        "exclusiones": 1,
        "solicitudes": 0,
        "mensajes_registrados": 0,
        "canales_registrados": 0,
    }
    # el usuario 10 desaparece de todos los servidores; el 20 queda (salvo en el servidor 500)
    assert _rows(conn, "SELECT count(*) FROM user_corpus WHERE author_id=10")[0][0] == 0
    # el servidor 500 desaparece entero (incluido el usuario 20 allí)
    assert (
        _rows(conn, "SELECT count(*) FROM corpus_messages WHERE guild_id=500")[0][0]
        == 0
    )
    assert _rows(conn, "SELECT count(*) FROM user_corpus WHERE guild_id=500")[0][0] == 0
    # lo demás se conserva
    assert (
        _rows(
            conn, "SELECT count(*) FROM user_corpus WHERE author_id=20 AND guild_id=1"
        )[0][0]
        == 2
    )
    # y la exclusión perdida vuelve
    assert _rows(
        conn,
        "SELECT exclude_learning FROM excluded_users WHERE guild_id=1 AND user_id=20",
    ) == [(1,)]
    assert stats["lapidas_servidor_vigentes"] == 1


def test_el_registro_externo_nunca_quita_una_exclusion_existente(conn):
    _sql(
        conn,
        "INSERT INTO excluded_users (guild_id, user_id, exclude_interaction, exclude_learning) "
        "VALUES (1, 20, 1, 1)",
    )
    _sync(lambda c: reapply_deletions.merge_ledger(c, _ledger_de(False, False, True)))
    assert _rows(
        conn,
        "SELECT exclude_interaction, exclude_learning FROM excluded_users WHERE guild_id=1 AND user_id=20",
    ) == [(1, 1)]


def test_el_registro_externo_ignora_lapidas_vencidas(conn):
    recs = [
        {"type": "header", "version": 1, "exported_at": ""},
        {
            "type": "user_tombstone",
            "user_id": 10,
            "deleted_at": _ts(-30),
            "expires_at": _ts(-15),
        },
        {
            "type": "footer",
            "counts": {"user_tombstone": 1, "guild_tombstone": 0, "exclusion": 0},
        },
    ]
    led = privacy_ledger.loads(privacy_ledger.dumps(recs))
    merged = _sync(lambda c: reapply_deletions.merge_ledger(c, led))
    assert merged["lapidas_usuario"] == 0
    assert _rows(conn, "SELECT count(*) FROM deleted_user_tombstones")[0][0] == 0


def test_fundir_el_registro_dos_veces_es_idempotente(conn):
    _restaurar_un_backup_viejo(conn)
    for _ in range(2):
        _sync(
            lambda c: (
                reapply_deletions.merge_ledger(c, _ledger_de()),
                reapply_deletions.reapply(c, apply=True),
            )
        )
    assert _rows(conn, "SELECT count(*) FROM deleted_user_tombstones")[0][0] == 1
    assert _rows(conn, "SELECT count(*) FROM excluded_users")[0][0] == 1


def test_dry_run_con_registro_no_guarda_nada(conn, tmp_path, capsys):
    _restaurar_un_backup_viejo(conn)
    f = tmp_path / "led.jsonl"
    f.write_text(
        privacy_ledger.dumps(
            [
                {"type": "header", "version": 1, "exported_at": _ts(0)},
                {
                    "type": "user_tombstone",
                    "user_id": 10,
                    "deleted_at": _ts(-1),
                    "expires_at": _ts(14),
                },
                {
                    "type": "footer",
                    "counts": {
                        "user_tombstone": 1,
                        "guild_tombstone": 0,
                        "exclusion": 0,
                    },
                },
            ]
        )
    )
    rc = reapply_deletions.main(
        ["--dsn", os.environ["TEST_DATABASE_URL"], "--ledger", str(f)]
    )
    assert rc == 0
    assert _rows(conn, "SELECT count(*) FROM deleted_user_tombstones")[0][0] == 0
    assert _rows(conn, "SELECT count(*) FROM user_corpus WHERE author_id=10")[0][0] == 4
    out = capsys.readouterr().out
    assert "dry-run" in out and "10" not in out.replace("100", "")


def test_main_con_registro_invalido_falla_sin_tocar_la_base(conn, tmp_path, capsys):
    _restaurar_un_backup_viejo(conn)
    f = tmp_path / "led.jsonl"
    f.write_text("{truncado")
    rc = reapply_deletions.main(
        ["--dsn", os.environ["TEST_DATABASE_URL"], "--ledger", str(f), "--apply"]
    )
    assert rc == 1
    assert _rows(conn, "SELECT count(*) FROM user_corpus WHERE author_id=10")[0][0] == 4


# ─── exportación cifrada ─────────────────────────────────────────────────────


@pytest.fixture
def age_keys(tmp_path):
    identity = tmp_path / "identity.txt"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    public = subprocess.run(
        ["age-keygen", "-y", str(identity)], check=True, capture_output=True, text=True
    ).stdout.strip()
    return identity, public


def test_sin_destinatarios_no_se_exporta_en_claro():
    with pytest.raises(ValueError, match="BACKUP_AGE_RECIPIENTS"):
        export_ledger.parse_recipients("")
    with pytest.raises(ValueError):
        export_ledger.parse_recipients("no-es-una-clave")


def test_dry_run_no_escribe_ni_sube_nada(conn, tmp_path, monkeypatch, capsys):
    _seed_registro(conn)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "b"))
    assert export_ledger.main(["--dry-run"]) == 0
    assert not (tmp_path / "b").exists()
    out = capsys.readouterr().out
    assert "1 lápida(s) de usuario" in out
    assert "10" not in out.replace("1 lápida", "")


@needs_age
def test_exporta_cifrado_sube_a_ledger_y_no_deja_nada_en_claro(
    conn, tmp_path, monkeypatch, age_keys
):
    identity, public = age_keys
    _seed_registro(conn)
    fake = FakeS3("purgito-backups")
    monkeypatch.setattr(export_ledger.r2, "get_backup_client", lambda: fake)
    monkeypatch.setattr(export_ledger.r2, "get_client", lambda: fake)
    monkeypatch.setenv("R2_BACKUP_BUCKET", "purgito-backups")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "b"))
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", public)

    assert export_ledger.main([]) == 0

    local = sorted((tmp_path / "b" / "ledger").iterdir())
    assert len(local) == 1 and local[0].name.endswith(".jsonl.age")
    assert oct(local[0].stat().st_mode & 0o777) == "0o600"
    assert not any(p.name.startswith(".ledger-") for p in local)
    claves = fake.keys("purgito-backups")
    assert len(claves) == 1 and next(iter(claves)).startswith(
        "gen2/ledger/privacy-ledger-"
    )
    # cifrado de verdad: sin la clave no se lee, con ella sí
    crudo = local[0].read_bytes()
    assert crudo.startswith(b"age-encryption.org/v1") and b"tombstone" not in crudo
    claro = subprocess.run(
        ["age", "-d", "-i", str(identity), str(local[0])],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    led = privacy_ledger.loads(claro)
    assert [r["user_id"] for r in led["user_tombstones"]] == [10]


@needs_age
def test_si_falla_la_subida_el_script_sale_con_error_y_avisa_sin_datos(
    conn, tmp_path, monkeypatch, age_keys, capsys
):
    _, public = age_keys
    _seed_registro(conn)
    monkeypatch.setattr(export_ledger.r2, "get_backup_client", lambda: None)
    monkeypatch.setenv("R2_BACKUP_BUCKET", "purgito-backups")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "b"))
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", public)
    avisos = []
    monkeypatch.setattr(export_ledger, "_alert", lambda: avisos.append(1))

    assert export_ledger.main([]) == 1
    assert avisos == [1]
    err = capsys.readouterr().err
    assert "ERROR" in err and "postgres" not in err


@needs_age
def test_conserva_solo_las_ultimas_3_copias_locales(tmp_path):
    d = tmp_path / "l"
    d.mkdir()
    for i in range(6):
        (d / f"privacy-ledger-2026110{i}T000000Z.jsonl.age").write_bytes(b"x")
    export_ledger.prune_local(str(d))
    assert len(list(d.iterdir())) == 3


def test_el_json_exportado_no_tiene_campos_inesperados(conn):
    _seed_registro(conn)
    for linea in privacy_ledger.dumps(
        _sync(privacy_ledger.build_snapshot)
    ).splitlines():
        rec = json.loads(linea)
        assert set(rec) <= {
            "type",
            "version",
            "exported_at",
            "user_id",
            "guild_id",
            "deleted_at",
            "purged_at",
            "expires_at",
            "exclude_interaction",
            "exclude_learning",
            "created_at",
            "counts",
        }
