# Runbooks remotos

Estado: **IMPLEMENTADO** (`deploy/runbooks/purgito_runbooks.py`). El
despachador remoto que los invocaría desde un panel es **PENDIENTE** y no
existe. Contexto en [OBSERVABILITY.md](OBSERVABILITY.md); el procedimiento
humano de incidentes sigue en [RUNBOOK.md](RUNBOOK.md).

## Qué es (y qué no)

Un **registro cerrado** de operaciones, cada una una función del script, con
parámetros tipados y acotados. **No** es una API para mandar comandos shell:

- el nombre del runbook se valida contra el registro (`[a-z_]`, existente) — no hay forma de pasar un comando;
- cada parámetro es un entero con rango o un valor de una lista fija;
- los subprocesos usan `argv` constantes sin `shell`; ningún argumento llega a un shell ni a una ruta;
- la unidad de systemd (`bot-purg`) es una constante, no un parámetro;
- cada runbook tiene un timeout duro (`SIGALRM`) y toda salida pasa por la redacción de secretos.

## Runbooks

| Runbook | Permiso | Parámetros | Qué hace |
|---|---|---|---|
| `diagnose_purgito` | solo lectura | `--log-lines 1..200` (def. 20) | `systemctl show bot-purg` (estado, `NRestarts`, `Result`), `/health` y `/health/ready` por loopback, `service_state.json`, últimos `warning+` del journal |
| `diagnose_postgres` | solo lectura | — | `pg_isready` + una consulta fija (versión, conexiones/`max_connections`, tamaño de la base, transacción más vieja). Credenciales por entorno `PG*`, nunca en argv ni en la salida |
| `diagnose_disk` | solo lectura | — | uso del filesystem, tamaño de `data/`, archivos más grandes. `ok=false` si el disco supera 90 % |
| `diagnose_memory` | solo lectura | — | `/proc/meminfo`, swap, RSS del bot, `loadavg`. `ok=false` si queda < 5 % disponible |
| `restart_purgito` | **muta** | `--confirm yes-restart-purgito` (obligatorio) | `sudo -n systemctl restart bot-purg`, espera 3 s y verifica `is-active` |
| `list` | solo lectura | — | el registro |

`restart_purgito` es el único que modifica algo, y está separado a propósito:
exige una confirmación literal que un diagnóstico nunca necesita.

## Salida y exit codes

Siempre **un objeto JSON** por stdout:

```json
{"runbook": "diagnose_disk", "ok": true, "exit_code": 0, "mutating": false,
 "started_at": "2026-10-02T17:51:19Z", "duration_ms": 3, "data": { … }}
```

| Exit | Significado |
|---|---|
| 0 | corrió y no encontró problemas |
| 1 | corrió y encontró un problema (`ok: false`, detalles en `data`) |
| 2 | uso inválido: runbook o argumento no permitido (no se ejecutó nada) |
| 124 | timeout |

Cada ejecución deja una línea en journald (`logger -t purgito-runbook`, con el
origen SSH si lo hay) que Vector recoge como `deployment.runbook_executed`.

## Uso por SSH sobre Tailscale

Este servidor está en la tailnet y entra por **SSH normal** (clave, por la
interfaz `tailscale0`); **Tailscale SSH no está habilitado** (`RunSSH: false`).
Los runbooks se invocan sobre ese mismo SSH:

```bash
ssh purgito@<nombre-o-ip-tailscale> \
  python3 /home/purgito/purgito-bot/deploy/runbooks/purgito_runbooks.py diagnose_purgito
```

Solo usa la biblioteca estándar de Python 3 del sistema (no necesita el venv).
`diagnose_purgito` lee el journal: el usuario debe estar en el grupo `systemd-journal` o `adm`.

### Endurecimiento opcional para el futuro despachador

Para que una clave del control plane solo pueda correr runbooks, no un shell:

```
# ~/.ssh/authorized_keys del usuario purgito
command="python3 /home/purgito/purgito-bot/deploy/runbooks/purgito_runbooks.py $SSH_ORIGINAL_COMMAND",restrict ssh-ed25519 AAAA… control-plane
```

El shell de login expande `$SSH_ORIGINAL_COMMAND` sin reinterpretar `;`, `&&` ni
`$()` (solo separa por espacios), y el script **valida cada token contra el
registro**: nombre, `--parametros` y valores; cualquier otra cosa devuelve exit 2
sin ejecutar nada (cubierto por `tests/test_obs_runbooks.py`). Esta configuración
de `authorized_keys` **no está probada** en este servidor: probarla con una clave
descartable antes de depender de ella.

Reinicio sin sudo abierto — `/etc/sudoers.d/purgito-runbooks` (hoy el usuario ya tiene sudo sin contraseña; esto es para el día que no):

```
purgito ALL=(root) NOPASSWD: /usr/bin/systemctl restart bot-purg
```

## Qué NO hacen

No ejecutan comandos arbitrarios, no aceptan rutas, no tocan la base (la
consulta de `diagnose_postgres` es una constante de solo lectura), no
modifican archivos, no reinician nada salvo `restart_purgito`, y no se
disparan solos ante una alerta.
