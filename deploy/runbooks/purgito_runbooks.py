#!/usr/bin/env python3
"""Runbooks allowlisted de Purgito -- diagnóstico y recuperación por SSH/Tailscale.

NO es un ejecutor de comandos: es un registro CERRADO de runbooks, cada uno una
función de este archivo con parámetros tipados y acotados. Nada de lo que se
pasa por línea de comandos llega a un shell ni a una ruta: los argv de los
subprocesos son constantes y ninguna llamada pasa por un shell.

Uso:
    python3 purgito_runbooks.py list
    python3 purgito_runbooks.py diagnose_purgito [--log-lines 20]
    python3 purgito_runbooks.py diagnose_postgres
    python3 purgito_runbooks.py diagnose_disk
    python3 purgito_runbooks.py diagnose_memory
    python3 purgito_runbooks.py restart_purgito --confirm yes-restart-purgito

Salida: UN objeto JSON por stdout (siempre), con el exit code en el campo
`exit_code` y como código de salida del proceso:
    0 ok · 1 el runbook corrió y encontró un problema · 2 uso inválido
    (runbook/argumento no permitido) · 124 timeout

Solo stdlib. Los diagnósticos son de solo lectura; `restart_purgito` es el
único que muta y exige `--confirm`. Toda salida pasa por la redacción de
secretos de src/observability/redaction.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from observability.redaction import scrub  # noqa: E402

SERVICE = "bot-purg"  # constante: nunca viene de un argumento
DATA_DIR = os.path.join(ROOT, "data")
CONFIRM_RESTART = "yes-restart-purgito"
_SYSTEMCTL = shutil.which("systemctl") or "/usr/bin/systemctl"

EXIT_OK, EXIT_PROBLEM, EXIT_USAGE, EXIT_TIMEOUT = 0, 1, 2, 124


class UsageError(Exception):
    pass


class Timeout(Exception):
    pass


# ---------------- Utilidades ----------------


def _run(argv: list[str], timeout: float = 5.0, env: dict | None = None) -> dict:
    """Ejecuta un argv CONSTANTE (lista, sin shell). Devuelve rc + salida scrubbed."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=env,
        )
        return {
            "rc": proc.returncode,
            "stdout": scrub(proc.stdout.strip())[:8000],
            "stderr": scrub(proc.stderr.strip())[:2000],
        }
    except FileNotFoundError:
        return {"rc": 127, "stdout": "", "stderr": f"no existe: {argv[0]}"}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "stdout": "", "stderr": "timeout"}


def _web_port() -> int:
    raw = os.environ.get("WEB_PORT")
    if raw is None:
        raw = _read_env_file().get("WEB_PORT", "8080")
    return int(raw) if raw.isdigit() else 8080


def _read_env_file() -> dict[str, str]:
    """Lee .env SOLO para extraer valores no secretos o armar el entorno de
    psql; los valores nunca se imprimen."""
    out: dict[str, str] = {}
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    out[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return out


def _http_get(path: str, timeout: float = 3.0) -> dict:
    url = f"http://127.0.0.1:{_web_port()}{path}"
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (loopback fijo)
            body = resp.read(2048).decode("utf-8", "replace")
            return {
                "status": resp.status,
                "ms": round((time.monotonic() - started) * 1000),
                "body": scrub(body),
            }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "ms": round((time.monotonic() - started) * 1000)}
    except Exception as e:  # URLError, timeout, conexión rechazada
        return {"status": None, "error": type(e).__name__}


def _systemd_show() -> dict:
    props = "ActiveState,SubState,Result,NRestarts,MainPID,ExecMainStatus,ActiveEnterTimestamp"
    res = _run([_SYSTEMCTL, "show", SERVICE, "-p", props, "--no-pager"])
    info = {}
    for line in res["stdout"].splitlines():
        key, _, value = line.partition("=")
        info[key] = value
    return info


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------- Runbooks ----------------


def diagnose_purgito(log_lines: int = 20) -> tuple[dict, bool]:
    unit = _systemd_show()
    health = _http_get("/health")
    ready = _http_get("/health/ready")
    state = _read_json(os.path.join(DATA_DIR, "service_state.json")) or {}
    journal = _run(
        [
            "journalctl",
            "-u",
            SERVICE,
            "-p",
            "warning",
            "-n",
            str(log_lines),
            "--no-pager",
            "-o",
            "cat",
        ],
        timeout=8,
    )
    data = {
        "systemd": unit,
        "health": health,
        "ready": ready,
        "service_state": {
            k: state.get(k)
            for k in (
                "state",
                "previous_state",
                "started_at",
                "last_heartbeat",
                "last_clean_shutdown",
                "last_error",
                "previous_run",
            )
        },
        "recent_warnings": journal["stdout"].splitlines() if journal["rc"] == 0 else [],
        "journal_error": journal["stderr"] if journal["rc"] != 0 else None,
    }
    ok = unit.get("ActiveState") == "active" and health.get("status") == 200
    return data, ok


def _pg_env() -> dict | None:
    """Entorno PG* para psql/pg_isready, derivado de DATABASE_URL. Nada de esto se imprime."""
    url = os.environ.get("DATABASE_URL") or _read_env_file().get("DATABASE_URL")
    if not url:
        return None
    p = urlparse(url)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env["PGHOST"] = p.hostname or "127.0.0.1"
    env["PGPORT"] = str(p.port or 5432)
    env["PGDATABASE"] = (p.path or "/postgres").lstrip("/") or "postgres"
    if p.username:
        env["PGUSER"] = unquote(p.username)
    if p.password:
        env["PGPASSWORD"] = unquote(p.password)
    env["PGCONNECT_TIMEOUT"] = "3"
    return env


_PG_QUERY = (
    "SELECT json_build_object("
    "'version', current_setting('server_version'),"
    "'connections', (SELECT count(*) FROM pg_stat_activity),"
    "'max_connections', current_setting('max_connections')::int,"
    "'database_bytes', pg_database_size(current_database()),"
    "'oldest_xact_seconds', (SELECT COALESCE(max(EXTRACT(EPOCH FROM now()-xact_start))::int,0) "
    "FROM pg_stat_activity WHERE xact_start IS NOT NULL AND pid <> pg_backend_pid()),"
    "'in_recovery', pg_is_in_recovery())"
)


def diagnose_postgres() -> tuple[dict, bool]:
    env = _pg_env()
    if env is None:
        return {"error": "DATABASE_URL no está definida"}, False
    isready = _run(["pg_isready", "-t", "3"], env=env)
    data: dict = {
        "host": env["PGHOST"],
        "port": env["PGPORT"],
        "pg_isready": {"rc": isready["rc"], "output": isready["stdout"]},
    }
    ok = isready["rc"] == 0
    if ok:
        q = _run(["psql", "-X", "-A", "-t", "-c", _PG_QUERY], timeout=8, env=env)
        if q["rc"] == 0:
            try:
                data["stats"] = json.loads(q["stdout"])
            except ValueError:
                data["stats_error"] = "salida de psql no parseable"
        else:
            data["stats_error"] = q["stderr"] or "psql falló"
            ok = False
    return data, ok


def _dir_size(path: str) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def diagnose_disk() -> tuple[dict, bool]:
    usage = shutil.disk_usage(ROOT)
    files = []
    try:
        for name in os.listdir(DATA_DIR):
            path = os.path.join(DATA_DIR, name)
            if os.path.isfile(path):
                files.append({"name": name, "bytes": os.path.getsize(path)})
    except OSError:
        pass
    files.sort(key=lambda f: f["bytes"], reverse=True)
    pct = round(usage.used / usage.total * 100, 1)
    data = {
        "filesystem": {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": pct,
        },
        "data_dir_bytes": _dir_size(DATA_DIR),
        "largest_data_files": files[:10],
    }
    return data, pct < 90.0


def _meminfo() -> dict:
    out = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    out[key] = int(parts[0]) * 1024
    except OSError:
        pass
    return out


def diagnose_memory() -> tuple[dict, bool]:
    mem = _meminfo()
    pid = _systemd_show().get("MainPID", "0")
    rss = None
    if pid.isdigit() and int(pid) > 0:
        try:
            with open(f"/proc/{int(pid)}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1]) * 1024
        except OSError:
            pass
    try:
        load = open("/proc/loadavg").read().split()[:3]
    except OSError:
        load = []
    available = mem.get("MemAvailable")
    total = mem.get("MemTotal")
    data = {
        "mem_total_bytes": total,
        "mem_available_bytes": available,
        "swap_total_bytes": mem.get("SwapTotal"),
        "swap_free_bytes": mem.get("SwapFree"),
        "purgito_rss_bytes": rss,
        "loadavg": load,
    }
    ok = bool(total and available and available / total > 0.05)
    return data, ok


def restart_purgito(confirm: str) -> tuple[dict, bool]:
    """ÚNICO runbook que muta. Reinicia SOLO la unidad fija `bot-purg`."""
    if confirm != CONFIRM_RESTART:
        raise UsageError(f"restart_purgito exige --confirm {CONFIRM_RESTART}")
    res = _run(["sudo", "-n", _SYSTEMCTL, "restart", SERVICE], timeout=45)
    time.sleep(3)
    active = _run([_SYSTEMCTL, "is-active", SERVICE])
    data = {
        "restart_rc": res["rc"],
        "restart_stderr": res["stderr"],
        "is_active_after": active["stdout"],
    }
    return data, res["rc"] == 0 and active["stdout"] == "active"


# ---------------- Registro (allowlist) ----------------
# nombre -> (función, mutates, timeout_total_s, params)
# params: nombre -> ("int", min, max) | ("choice", (valores...))
REGISTRY: dict[str, dict] = {
    "diagnose_purgito": {
        "fn": diagnose_purgito,
        "mutates": False,
        "timeout": 30,
        "params": {"log_lines": ("int", 1, 200)},
    },
    "diagnose_postgres": {
        "fn": diagnose_postgres,
        "mutates": False,
        "timeout": 20,
        "params": {},
    },
    "diagnose_disk": {
        "fn": diagnose_disk,
        "mutates": False,
        "timeout": 20,
        "params": {},
    },
    "diagnose_memory": {
        "fn": diagnose_memory,
        "mutates": False,
        "timeout": 15,
        "params": {},
    },
    "restart_purgito": {
        "fn": restart_purgito,
        "mutates": True,
        "timeout": 60,
        "params": {"confirm": ("choice", (CONFIRM_RESTART,))},
    },
}

_NAME_RE = re.compile(r"^[a-z_]{1,32}$")


def parse_args(argv: list[str]) -> tuple[str, dict]:
    """Valida `runbook [--param valor ...]` contra el registro. Lanza UsageError."""
    if not argv:
        raise UsageError("falta el nombre del runbook (usa: list)")
    name, rest = argv[0], argv[1:]
    if name == "list":
        if rest:
            raise UsageError("list no acepta argumentos")
        return "list", {}
    if not _NAME_RE.match(name) or name not in REGISTRY:
        raise UsageError(f"runbook no permitido: {name[:40]!r}")
    spec = REGISTRY[name]["params"]
    kwargs: dict = {}
    i = 0
    while i < len(rest):
        flag = rest[i]
        if not flag.startswith("--") or not _NAME_RE.match(flag[2:].replace("-", "_")):
            raise UsageError(f"argumento no permitido: {flag[:40]!r}")
        key = flag[2:].replace("-", "_")
        if key not in spec:
            raise UsageError(f"parámetro no permitido para {name}: {key}")
        if key in kwargs:
            raise UsageError(f"parámetro repetido: {key}")
        if i + 1 >= len(rest):
            raise UsageError(f"falta el valor de --{key}")
        raw = rest[i + 1]
        kind = spec[key]
        if kind[0] == "int":
            if not re.fullmatch(r"\d{1,6}", raw) or not kind[1] <= int(raw) <= kind[2]:
                raise UsageError(
                    f"--{key} debe ser un entero entre {kind[1]} y {kind[2]}"
                )
            kwargs[key] = int(raw)
        else:  # choice
            if raw not in kind[1]:
                raise UsageError(f"--{key} no es un valor permitido")
            kwargs[key] = raw
        i += 2
    if name == "restart_purgito" and "confirm" not in kwargs:
        raise UsageError(f"restart_purgito exige --confirm {CONFIRM_RESTART}")
    return name, kwargs


def _log_execution(name: str, ok: bool, exit_code: int, mutates: bool) -> None:
    """Deja rastro en journald (SYSLOG_IDENTIFIER=purgito-runbook) para que
    Vector lo recoja como deployment.runbook_executed. Best-effort."""
    who = (
        os.environ.get("SSH_CONNECTION", "local").split(" ")[0]
        if "SSH_CONNECTION" in os.environ
        else "local"
    )
    line = (
        f"event=deployment.runbook_executed runbook={name} ok={ok} "
        f"exit_code={exit_code} mutating={mutates} from={who}"
    )
    try:
        subprocess.run(
            ["logger", "-t", "purgito-runbook", "-p", "user.info", line],
            timeout=3,
            check=False,
        )
    except Exception:
        pass


def _alarm(_signum, _frame):
    raise Timeout()


def execute(argv: list[str]) -> tuple[dict, int]:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    try:
        name, kwargs = parse_args(argv)
    except UsageError as e:
        return {"ok": False, "exit_code": EXIT_USAGE, "error": str(e)}, EXIT_USAGE

    if name == "list":
        listing = {
            n: {
                "mutates": s["mutates"],
                "timeout_s": s["timeout"],
                "params": list(s["params"]),
            }
            for n, s in REGISTRY.items()
        }
        return {"ok": True, "exit_code": EXIT_OK, "runbooks": listing}, EXIT_OK

    spec = REGISTRY[name]
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(spec["timeout"])
    try:
        data, ok = spec["fn"](**kwargs)
        code = EXIT_OK if ok else EXIT_PROBLEM
    except UsageError as e:
        data, ok, code = {"error": str(e)}, False, EXIT_USAGE
    except Timeout:
        data, ok, code = (
            {"error": f"timeout tras {spec['timeout']}s"},
            False,
            EXIT_TIMEOUT,
        )
    except Exception as e:
        data, ok, code = {"error": f"{type(e).__name__}"}, False, EXIT_PROBLEM
    finally:
        signal.alarm(0)

    result = {
        "runbook": name,
        "ok": ok,
        "exit_code": code,
        "mutating": spec["mutates"],
        "started_at": started.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "duration_ms": round((time.monotonic() - t0) * 1000),
        "data": data,
    }
    _log_execution(name, ok, code, spec["mutates"])
    return result, code


def main() -> int:
    result, code = execute(sys.argv[1:])
    print(scrub(json.dumps(result, ensure_ascii=False, sort_keys=True)))
    return code


if __name__ == "__main__":
    sys.exit(main())
