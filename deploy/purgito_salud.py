#!/usr/bin/python3 -I
"""Vigilante de salud de Purgito dentro de la VM: avisa a Purgito Monitor (-> Discord) cuando Purgito no se
recupera solo. Lo lanza purgito-salud.timer cada 2 min como root.

Por qué existe: el sondeo externo del monitor (https://purgito.app/health) ya avisa de que Purgito está caído,
pero no dice por qué. Este vigilante dice la causa (bóveda sin desbloquear, Tang que no responde, una unidad
parada, Studio, temporizador de respaldos, memoria o disco) y no depende de la bóveda: sus credenciales están
en /etc/purgito-alertas/monitor.env (root 0600, fuera del volumen cifrado).

    purgito_salud.py                    # una comprobación (lo que hace el timer)
    purgito_salud.py --estado           # muestra lo que ve ahora, sin avisar
    purgito_salud.py mantenimiento 30   # silencia los avisos 30 min (reinicios planificados)
    purgito_salud.py mantenimiento fin
    purgito_salud.py --prueba           # envía una alerta de PRUEBA etiquetada como tal

Reglas: un problema solo se avisa si aparece en dos comprobaciones seguidas; un aviso por episodio (con
recordatorio cada 6 h si sigue); nada durante los primeros minutos tras arrancar ni en mantenimiento.
Los mensajes no llevan datos de personas ni secretos.
"""

import http.client
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor_notify import sign  # noqa: E402  (misma firma HMAC del contrato /v1/events)

STATE_DIR = os.environ.get("SALUD_STATE_DIR", "/var/lib/purgito-salud")
STATE = os.path.join(STATE_DIR, "estado.json")
MAINT = os.path.join(STATE_DIR, "mantenimiento-hasta")
VAULT_MNT = "/srv/purgito"
VAULT_TOOL = "/opt/purgito-vault/purgito-vault"
TANG_ADV = os.environ.get("SALUD_TANG_URL", "http://10.203.0.1:7500") + "/adv"
UNITS = {
    "postgresql@18-main.service": "PostgreSQL",
    "bot-purg.service": "el bot",
    "studio-purg.service": "Studio",
    "cloudflared.service": "el túnel de Cloudflare",
    "nginx.service": "nginx",
}
BOOT_GRACE_S = int(
    os.environ.get("SALUD_BOOT_GRACE_S", "360")
)  # el desbloqueo automático tarda < 1 min
REMIND_S = 6 * 3600
TANG_TEST_EVERY_S = 3600


def sh(*cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def uptime_s() -> float:
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def http_status(host: str, port: int, path: str, timeout: float = 5) -> int | None:
    try:
        c = http.client.HTTPConnection(host, port, timeout=timeout)
        c.request("GET", path, headers={"Host": f"{host}:{port}"})
        return c.getresponse().status
    except OSError:
        return None


def tang_responde() -> bool:
    try:
        with urllib.request.urlopen(TANG_ADV, timeout=5) as r:
            return r.status == 200 and b"payload" in r.read(4096)
    except (urllib.error.URLError, OSError):
        return False


def load(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def check(state: dict) -> dict[str, str]:
    """Problemas presentes ahora: código -> texto para una persona."""
    p: dict[str, str] = {}
    mounted = os.path.ismount(VAULT_MNT)
    if not mounted:
        auto = sh(
            "systemctl", "is-enabled", "purgito-vault-auto.service"
        ).stdout.strip()
        tang = "responde" if tang_responde() else "NO responde"
        p["boveda"] = (
            "La bóveda cifrada sigue cerrada: PostgreSQL, bot, Studio y túnel no pueden arrancar. "
            f"Servidor Tang del host: {tang}. Desbloqueo automático: {auto or 'no instalado'}. "
            "Si Tang no responde: en el host `sudo bash ~/purgito-lab/host-setup.sh ensure`; "
            "si no, desbloqueo manual `sudo purgito-vault open`."
        )
    else:
        for unit, name in UNITS.items():
            st = sh("systemctl", "is-active", unit).stdout.strip()
            if st != "active":
                p[f"unidad:{unit}"] = (
                    f"{name} ({unit}) está {st or 'desconocido'} con la bóveda abierta."
                )
        if (
            "unidad:bot-purg.service" not in p
            and http_status("127.0.0.1", 8080, "/health") != 200
        ):
            p["bot-health"] = (
                "El bot está activo pero /health no responde 200 en 127.0.0.1:8080."
            )
        if (
            "unidad:studio-purg.service" not in p
            and http_status("127.0.0.1", 18081, "/") is None
        ):
            p["studio"] = "Studio está activo pero no responde en 127.0.0.1:18081."
        if (
            sh("systemctl", "is-active", "purgito-backup.timer").stdout.strip()
            != "active"
        ):
            p["respaldos"] = (
                "El temporizador de respaldos (purgito-backup.timer) no está activo."
            )
        # Tang: comprobación proactiva (sin abrir ni cerrar nada) para no descubrir el fallo en el próximo reinicio.
        if (
            os.access(VAULT_TOOL, os.X_OK)
            and time.time() - state.get("tang_ok_at", 0) > TANG_TEST_EVERY_S
        ):
            r = sh(VAULT_TOOL, "tang-test", timeout=120)
            if r.returncode == 0:
                state["tang_ok_at"] = time.time()
                state.pop("tang_fail", None)
            elif "no hay ninguna ranura" not in r.stderr:
                state["tang_fail"] = True
        if state.get("tang_fail"):
            p["tang"] = (
                "El servidor Tang del host no abre la ranura de desbloqueo automático: el PRÓXIMO reinicio "
                "dejará la bóveda cerrada. En el host: `sudo bash ~/purgito-lab/host-setup.sh ensure`."
            )
    for mnt in ("/", VAULT_MNT) if mounted else ("/",):
        du = shutil.disk_usage(mnt)
        if du.used / du.total > 0.92:
            p[f"disco:{mnt}"] = f"Disco {mnt} al {100 * du.used / du.total:.0f} %."
    try:
        with open("/proc/pressure/memory") as f:
            full = float(f.read().split("full ")[1].split("avg300=")[1].split()[0])
        if full > 20:
            p["memoria"] = (
                f"Presión de memoria sostenida (PSI full avg300={full:.0f} %): la VM se está ahogando."
            )
    except (OSError, IndexError, ValueError):
        pass
    return p


def send(
    problems: dict[str, str], *, test: bool = False, reminder: bool = False
) -> bool:
    env = {}
    for path in ("/etc/purgito-alertas/monitor.env",):
        try:
            for line in open(path):
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.rstrip("\n").split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
        except OSError:
            pass
    base = env.get("MONITOR_BASE_URL", "").rstrip("/")
    node = env.get("MONITOR_NODE_ID", "")
    secret = "".join(env.get("MONITOR_SHARED_SECRET", "").split())
    if not (base.startswith("https://") and node and secret):
        print(
            "purgito_salud: faltan credenciales en /etc/purgito-alertas/monitor.env",
            file=sys.stderr,
        )
        return False
    if test:
        msg = "PRUEBA de alerta de salud de Purgito (sin incidencia real)."
    else:
        head = (
            "Purgito sigue con problemas"
            if reminder
            else "Purgito no se ha recuperado solo"
        )
        msg = head + ": " + " | ".join(problems.values())
    event = {
        "event_id": uuid.uuid4().hex,
        "node_id": node,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_type": "system.warning",
        "severity": "critical",
        "service": "purgito",
        "message": msg[:1000],
        "reason": "vault_locked" if "boveda" in problems else "health_check_failed",
        "metadata": {
            "source": "purgito-salud",
            "problems": sorted(problems)[:20],
            "test": test,
        },
    }
    body = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode()
    for attempt in range(1, 4):
        ts = str(int(time.time()))
        req = urllib.request.Request(
            base + "/v1/events",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Purgito-Timestamp": ts,
                "X-Purgito-Signature": sign(secret, ts, body),
                "User-Agent": "purgito-salud",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(
                    f"purgito_salud: aviso {event['event_id'][:8]} entregado (HTTP {resp.status})"
                )
                return True
        except urllib.error.HTTPError as e:
            if e.code not in (408, 425, 429) and e.code < 500:
                print(
                    f"purgito_salud: el monitor rechazó el aviso (HTTP {e.code})",
                    file=sys.stderr,
                )
                return False
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2 * attempt)
    print(
        "purgito_salud: no se pudo avisar al monitor (se reintentará)", file=sys.stderr
    )
    return False


def main(argv: list[str]) -> int:
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    if argv[:1] == ["mantenimiento"]:
        arg = argv[1] if len(argv) > 1 else "30"
        if arg == "fin":
            if os.path.exists(MAINT):
                os.remove(MAINT)
            print("mantenimiento terminado")
        else:
            until = time.time() + int(arg) * 60
            with open(MAINT, "w") as f:
                f.write(str(int(until)))
            print(
                f"avisos silenciados {arg} min (hasta {datetime.fromtimestamp(until, timezone.utc):%H:%M} UTC)"
            )
        return 0
    if "--prueba" in argv:
        return 0 if send({}, test=True) else 1

    state = load(STATE, {})
    now = time.time()
    current = check(state)
    if "--estado" in argv:
        print(
            json.dumps(current, ensure_ascii=False, indent=1)
            if current
            else "sin problemas"
        )
        return 0

    try:
        maint_until = float(open(MAINT).read().strip())
    except (OSError, ValueError):
        maint_until = 0
    quiet = uptime_s() < BOOT_GRACE_S or now < maint_until

    prev = set(state.get("seen", []))
    confirmed = {
        k: v for k, v in current.items() if k in prev
    }  # dos comprobaciones seguidas
    state["seen"] = sorted(current)
    notified = set(state.get("notified", []))
    new = {k: v for k, v in confirmed.items() if k not in notified}
    remind = (
        bool(confirmed) and not new and now - state.get("notified_at", 0) > REMIND_S
    )

    if confirmed and not quiet and (new or remind):
        if send(confirmed, reminder=remind):
            state["notified"] = sorted(confirmed)
            state["notified_at"] = now
    elif not current and notified:
        print("purgito_salud: recuperado (" + ", ".join(sorted(notified)) + ")")
        state["notified"] = []
    else:
        # Lo ya avisado que se resolvió deja de contar; lo que sigue queda como avisado.
        state["notified"] = sorted(notified & set(current))

    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE)
    if current:
        print(
            "purgito_salud: "
            + ", ".join(sorted(current))
            + (" (silenciado)" if quiet else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
