"""Runbooks allowlisted (deploy/runbooks/purgito_runbooks.py): solo se ejecuta
lo registrado, los argumentos están acotados y nada llega a un shell."""

import importlib.util
import json
import os
import subprocess
import time

import pytest

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "deploy",
    "runbooks",
    "purgito_runbooks.py",
)
_spec = importlib.util.spec_from_file_location("purgito_runbooks", _PATH)
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    """Ningún test de este archivo puede ejecutar un subproceso real salvo que
    lo habilite explícitamente."""
    calls = []

    def fake_run(argv, *a, **kw):
        calls.append((argv, kw))
        raise AssertionError(f"subprocess.run inesperado: {argv}")

    monkeypatch.setattr(rb.subprocess, "run", fake_run)
    return calls


# ---------------- Allowlist ----------------


@pytest.mark.parametrize(
    "argv",
    [
        ["rm", "-rf", "/"],
        ["bash", "-c", "id"],
        ["diagnose_disk; rm -rf /"],
        ["diagnose_disk && id"],
        ["$(id)"],
        ["../../bin/sh"],
        ["DIAGNOSE_DISK"],
        ["diagnose_disk\n"],
        ["restart_purgito_now"],
        [""],
        [],
    ],
)
def test_runbook_no_permitido_se_rechaza_sin_ejecutar_nada(argv, _no_side_effects):
    result, code = rb.execute(argv)
    assert code == rb.EXIT_USAGE and result["ok"] is False
    assert _no_side_effects == []  # no se lanzó ningún subproceso


@pytest.mark.parametrize(
    "argv",
    [
        ["diagnose_disk", "--path", "/etc"],
        ["diagnose_memory", "extra"],
        ["diagnose_postgres", "--database", "x"],
        ["diagnose_purgito", "--unit", "ssh"],
        ["diagnose_purgito", "--log-lines"],
        ["diagnose_purgito", "--log-lines", "0"],
        ["diagnose_purgito", "--log-lines", "201"],
        ["diagnose_purgito", "--log-lines", "5; id"],
        ["diagnose_purgito", "--log-lines", "-5"],
        ["diagnose_purgito", "--log-lines", "5", "--log-lines", "6"],
        ["list", "x"],
    ],
)
def test_argumentos_invalidos_se_rechazan(argv, _no_side_effects):
    result, code = rb.execute(argv)
    assert code == rb.EXIT_USAGE
    assert _no_side_effects == []


def test_restart_exige_confirmacion_exacta(_no_side_effects):
    for argv in (
        ["restart_purgito"],
        ["restart_purgito", "--confirm", "yes"],
        ["restart_purgito", "--confirm", "yes-restart-purgito; id"],
        ["restart_purgito", "--service", "ssh", "--confirm", "yes-restart-purgito"],
    ):
        _, code = rb.execute(argv)
        assert code == rb.EXIT_USAGE
    assert _no_side_effects == []


def test_restart_solo_toca_la_unidad_fija(monkeypatch):
    seen = []

    def fake_run(argv, timeout=5.0, env=None):
        seen.append(argv)
        out = "active" if "is-active" in argv else ""
        return {"rc": 0, "stdout": out, "stderr": ""}

    monkeypatch.setattr(rb, "_run", fake_run)
    monkeypatch.setattr(rb.time, "sleep", lambda s: None)
    monkeypatch.setattr(rb, "_log_execution", lambda *a: None)
    result, code = rb.execute(["restart_purgito", "--confirm", rb.CONFIRM_RESTART])
    assert code == 0 and result["mutating"] is True
    restart = next(a for a in seen if "restart" in a)
    assert restart[0] == "sudo" and restart[1] == "-n"
    assert restart[-2:] == ["restart", "bot-purg"]


def test_solo_restart_muta_y_el_registro_es_el_esperado():
    assert set(rb.REGISTRY) == {
        "diagnose_purgito",
        "diagnose_postgres",
        "diagnose_disk",
        "diagnose_memory",
        "restart_purgito",
    }
    assert [n for n, s in rb.REGISTRY.items() if s["mutates"]] == ["restart_purgito"]
    for spec in rb.REGISTRY.values():
        assert 0 < spec["timeout"] <= 60


def test_list_describe_el_registro():
    result, code = rb.execute(["list"])
    assert code == 0 and set(result["runbooks"]) == set(rb.REGISTRY)
    assert result["runbooks"]["restart_purgito"]["mutates"] is True


def test_el_codigo_no_usa_shell_ni_exec_dinamico():
    src = open(_PATH, encoding="utf-8").read()
    assert "shell=True" not in src
    assert "os.system" not in src and "eval(" not in src and "exec(" not in src
    assert "shell=False" in src


# ---------------- Salida estructurada, timeout, secretos ----------------


def test_diagnose_disk_y_memory_devuelven_json_estructurado():
    for name in ("diagnose_disk", "diagnose_memory"):
        result, code = rb.execute([name])
        json.dumps(result)  # serializable
        assert code in (0, 1) and result["exit_code"] == code
        assert result["runbook"] == name and result["mutating"] is False
        assert result["duration_ms"] >= 0 and result["started_at"].endswith("Z")
        assert "data" in result


def test_diagnose_purgito_con_subprocesos_falsos(monkeypatch):
    def fake_run(argv, timeout=5.0, env=None):
        assert isinstance(argv, list)  # siempre argv, nunca string de shell
        if argv[1:2] == ["show"]:
            return {
                "rc": 0,
                "stdout": "ActiveState=active\nNRestarts=2\nMainPID=0",
                "stderr": "",
            }
        return {"rc": 0, "stdout": "linea warning", "stderr": ""}

    monkeypatch.setattr(rb, "_run", fake_run)
    monkeypatch.setattr(
        rb,
        "_http_get",
        lambda path, timeout=3.0: {"status": 200, "ms": 3, "body": "{}"},
    )
    monkeypatch.setattr(rb, "_log_execution", lambda *a: None)
    result, code = rb.execute(["diagnose_purgito", "--log-lines", "5"])
    assert code == 0
    assert result["data"]["systemd"]["NRestarts"] == "2"
    assert result["data"]["recent_warnings"] == ["linea warning"]


def test_timeout_devuelve_124(monkeypatch):
    monkeypatch.setitem(
        rb.REGISTRY,
        "diagnose_disk",
        {
            "fn": lambda: time.sleep(5) or ({}, True),
            "mutates": False,
            "timeout": 1,
            "params": {},
        },
    )
    monkeypatch.setattr(rb, "_log_execution", lambda *a: None)
    result, code = rb.execute(["diagnose_disk"])
    assert code == rb.EXIT_TIMEOUT and "timeout" in result["data"]["error"]


def test_excepcion_interna_no_filtra_detalles(monkeypatch):
    def broken():
        raise RuntimeError("clave=supersecreta123")

    monkeypatch.setitem(
        rb.REGISTRY,
        "diagnose_disk",
        {"fn": broken, "mutates": False, "timeout": 5, "params": {}},
    )
    monkeypatch.setattr(rb, "_log_execution", lambda *a: None)
    result, code = rb.execute(["diagnose_disk"])
    assert code == rb.EXIT_PROBLEM
    assert "supersecreta123" not in json.dumps(result)


def test_la_salida_de_subprocesos_se_redacta(monkeypatch):
    monkeypatch.setattr(
        rb.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv,
            0,
            stdout="dsn postgresql://u:pw123456789@h/db Bearer abcdefghijklmnop",
            stderr="",
        ),
    )
    out = rb._run(["echo", "x"])
    assert (
        "pw123456789" not in out["stdout"] and "abcdefghijklmnop" not in out["stdout"]
    )


def test_postgres_sin_database_url_falla_limpio(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(rb, "_read_env_file", lambda: {})
    monkeypatch.setattr(rb, "_log_execution", lambda *a: None)
    result, code = rb.execute(["diagnose_postgres"])
    assert code == rb.EXIT_PROBLEM and "DATABASE_URL" in result["data"]["error"]


def test_entorno_de_postgres_no_se_imprime(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://usr:pass%40word99@10.0.0.5:5433/dbx"
    )
    env = rb._pg_env()
    assert (env["PGHOST"], env["PGPORT"], env["PGDATABASE"], env["PGUSER"]) == (
        "10.0.0.5",
        "5433",
        "dbx",
        "usr",
    )
    assert env["PGPASSWORD"] == "pass@word99"

    seen = []
    monkeypatch.setattr(
        rb,
        "_run",
        lambda argv, timeout=5.0, env=None: (
            seen.append(argv) or {"rc": 1, "stdout": "no response", "stderr": ""}
        ),
    )
    monkeypatch.setattr(rb, "_log_execution", lambda *a: None)
    result, _ = rb.execute(["diagnose_postgres"])
    assert "pass" not in json.dumps(result)
    assert all("pass" not in " ".join(a) for a in seen)  # la contraseña no va en argv
