# Observabilidad de Purgito

Purgito es el primer **nodo** de una plataforma pequeña de observabilidad y
eventos de seguridad. Este documento describe qué hace hoy el nodo, qué prepara
para un control plane externo y qué falta.

Estado de cada pieza (se usa en todos los docs de esta capa):

- **IMPLEMENTADO** — funciona y tiene tests.
- **PREPARADO** — interfaz/configuración lista; falta infraestructura o una decisión para usarla.
- **PENDIENTE** — no existe todavía.

> **Despliegue.** Todo lo de abajo está en el repo. El proceso de producción
> sigue corriendo el código anterior hasta el próximo `git pull` +
> `sudo systemctl restart bot-purg` (ver [Activar en producción](#activar-en-producción)).

## Arquitectura

```
               purgito.app (landing/dashboard estáticos + /api)
                      |
                control plane            <- PENDIENTE, vive FUERA de este VM
                      |
            ┌─────────┴─────────┐
            |                   |
     monitor externo      logs / eventos centrales   <- PENDIENTE, FUERA del VM
            |                   |
            └─────────┬─────────┘
                      |
                 Purgito VM
                      |
                collector local (Vector)   <- PREPARADO (config validada, no instalado)
                      |
         bot: eventos JSONL, heartbeat, /metrics, alertas, runbooks   <- IMPLEMENTADO
```

### Qué vive dentro del VM y qué fuera

| Pieza | Dónde | Estado |
|---|---|---|
| Eventos estructurados, redacción, request ids | VM (en el bot) | IMPLEMENTADO |
| Heartbeat y estado del servicio | VM (`data/service_state.json`) | IMPLEMENTADO |
| `/health`, `/health/ready`, `/health/details`, `/metrics`, `/internal/alerts` | VM (en el bot) | IMPLEMENTADO |
| Reglas de detección y modelo de alertas | VM (en el bot) | IMPLEMENTADO |
| Runbooks allowlisted | VM (`deploy/runbooks/`) | IMPLEMENTADO |
| Collector (Vector) | VM | PREPARADO |
| Almacenamiento central de logs / eventos | **otro host** | PENDIENTE |
| Almacenamiento de métricas | **otro host** | PENDIENTE |
| Monitor de disponibilidad (Uptime Kuma u otro) | **otro host** | PENDIENTE |
| Motor de alertas central, panel, despachador de runbooks | **otro host** | PENDIENTE |

Reglas de diseño (no negociables):

- El control plane **no** vive en este VM. Si el VM cae, el panel de operación tiene que seguir accesible.
- El monitor externo **no** depende de Purgito para funcionar.
- Los logs críticos **salen** del VM (Vector → destino externo). Un log que solo existe en el disco del VM muerto no sirve para el postmortem.
- Nada de esto guarda logs dentro de PostgreSQL de Purgito.

## Esquema de eventos (IMPLEMENTADO)

Código: `src/observability/events.py`. Un evento es un dict plano, `schema: 1`:

| Campo | Cuándo |
|---|---|
| `timestamp` (UTC, termina en `Z`), `event_id`, `event_type`, `category` (`app`\|`security`), `severity` (`debug`\|`info`\|`warning`\|`error`\|`critical`), `service`, `environment`, `host`, `message` | siempre |
| `guild_id`, `user_id`, `channel_id`, `request_id`, `endpoint`, `method`, `status`, `duration_ms`, `error_type`, `result`, `reason`, `source_id`, `rule_id` | cuando corresponde |
| `data` | cualquier otro campo, anidado |

Los campos nuevos entran primero por `data`; solo se promueven a top-level si
hacen falta en todos lados. Así ningún consumidor se rompe por un campo que no conocía.

`log_event()` nunca lanza en producción: la observabilidad no puede tumbar el bot.
Un tipo no registrado se emite igual con `data.schema_warning`; en tests es un error.

**No se guarda contenido de mensajes ni corpus.** Las claves `content`,
`message_content`, `text`, `body`, `corpus`, `payload` y `prompt` se descartan
siempre, y las que parecen credenciales se enmascaran (ver Redacción).

### Taxonomía (solo tipos que el código emite)

| Tipo | Categoría | Severidad | Se emite en |
|---|---|---|---|
| `service.started` | app | info | `bot.py`, tras `on_ready` + web + lifecycle |
| `service.stopping` / `service.stopped` | app | info | apagado por SIGTERM/SIGINT |
| `service.crash_detected` | app | error | el arranque ve que el proceso anterior no cerró limpio |
| `service.heartbeat` | app | debug | cada 10 min, solo al JSONL |
| `system.unhandled_exception` | app | error | `_error_middleware` (webapi) |
| `system.background_task_failed` | app | error | `utils.restart_loop_after_failure` |
| `discord.ready` / `discord.disconnected` | app | info / warning | `bot.py` |
| `discord.command_error` | app | error | handlers de error de `cogs/general.py` |
| `database.connection_failed` | app | error | `init_db` al arrancar |
| `database.health_failed` | app | error | `/health/ready` |
| `auth.login_success` / `auth.login_failure` / `auth.logout` / `auth.session_revoked` | security | info / warning | OAuth2 de `webapi.py` |
| `permission.denied` | security | warning | `check_guild_access`, token de observabilidad inválido |
| `webhook.signature_invalid` / `webhook.rejected` | security | warning | `/webhooks/polar` |
| `rate_limit.triggered` | security | warning | `_rate_ok` (con throttle de 10 s por cliente/bucket) |
| `security.admin_action` | security | info | acciones sensibles del dashboard |
| `security.alert_opened` | security | warning | una regla abrió una alerta |
| `deployment.runbook_executed` | app | info | rastro de runbooks en journald |

Los prefijos `system`, `service`, `discord`, `database`, `auth`, `permission`,
`webhook`, `rate_limit`, `security` y `deployment` están reservados. Un test
(`test_taxonomia_coincide_con_el_codigo`) falla si el catálogo y el código divergen.

## Logging (IMPLEMENTADO)

| Destino | Formato | Contenido | Rotación |
|---|---|---|---|
| stderr → journald | texto legible | todo, con `event=<tipo> k=v …` para eventos | journald |
| `data/bot.log` | texto legible | igual que siempre | 5 MB × 4 |
| `data/events.jsonl` | JSON por línea | eventos `app` | 5 MB × 4 |
| `data/security.jsonl` | JSON por línea | eventos `security` | 5 MB × 4 |

Tope de disco añadido: ~40 MB (los dos JSONL). El JSONL es la fuente canónica
para el collector; la línea de texto del evento existe para humanos.

### Redacción de secretos

`src/observability/redaction.py`, en dos capas y aplicada al **texto final**
(incluye tracebacks, vía `RedactingFormatter` en bot.log y stderr):

1. Valores exactos de `DISCORD_TOKEN`, `DISCORD_CLIENT_SECRET`, `SESSION_SECRET`, `POLAR_ACCESS_TOKEN`, `POLAR_WEBHOOK_SECRET`, `GROQ_API_KEY`, `TWITCH_CLIENT_SECRET`, claves de R2, `DATABASE_URL`, `OBSERVABILITY_TOKEN`.
2. Patrones: URL de PostgreSQL con contraseña, `Bearer`/`Basic`, token de Discord, clave privada age, cookie `PURGITO_SESSION`, `password=`/`client_secret=`/`access_token=`…

Valores de menos de 8 caracteres no se redactan (taparían medio log sin proteger nada).
Limitación honesta: es una red de seguridad, no un detector perfecto — un
secreto con forma desconocida y que no esté en el entorno pasaría. Por eso los
eventos llevan campos cortos y tipados, no volcados de objetos.

### Correlation ids (IMPLEMENTADO)

`_observability_middleware` (webapi) asigna un `request_id` a cada request,
lo devuelve en `X-Request-ID` y lo adjunta automáticamente (contextvar) a todo
evento emitido durante ese request. Un `X-Request-ID` entrante solo se respeta
si es `[A-Za-z0-9_-]{8,64}`; si no, se genera uno. Con eso se sigue
`request_id → login_failure → permission.denied → system.unhandled_exception`.
No es tracing distribuido.

`source_id` identifica un origen sin guardar su IP: HMAC-SHA256 truncado
(12 hex) con `SESSION_SECRET`. Estable y no reversible.

## Monitor externo en Railway (IMPLEMENTADO en Purgito; el receptor es otro repo)

`src/observability/monitor.py`. Purgito **empuja** heartbeat y eventos al servicio
`Purgito/purgito-monitor`, y Railway **sondea** `GET /health`. Nada más:

```
Purgito VM
   |
   +--> POST /v1/heartbeat ---> Railway   (cada 30 s)
   +--> POST /v1/events ------> Railway   (solo eventos importantes)
   <--- GET /health ----------- Railway   (sondeo del monitor)
```

- **Railway es externo y no depende de Purgito.** Si Purgito muere, el monitor lo ve porque `/health` deja de responder y los heartbeats dejan de llegar; si muere todo el VM, igual: ambas señales se cortan.
- **Purgito no depende de Railway.** Sin configuración, o con Railway caído, funciona igual: el envío corre en dos tareas de fondo propias; `on_event`/`enqueue` solo agregan a una cola en memoria, nunca esperan red.
- **Esta dirección es la única.** Purgito no recibe ni ejecuta nada que venga del monitor (la respuesta HTTP solo se mira por su status; no se siguen redirects). Ejecución remota queda para una fase futura de runbooks.

### Configuración

| Variable | Valor |
|---|---|
| `MONITOR_ENABLED` | `true` para activar (default `false`) |
| `MONITOR_BASE_URL` | `https://…` (`http://` solo a loopback) |
| `MONITOR_NODE_ID` | estable, `[A-Za-z0-9._-]{1,64}`, p. ej. `purgito-prod-01`. No se usa el hostname: cambia al migrar de servidor |
| `MONITOR_SHARED_SECRET` | secreto compartido (nunca se loguea; se redacta como el resto) |
| `MONITOR_HEARTBEAT_INTERVAL` | segundos, default 30, mínimo 10 |

Si falta algo o es inválido, el monitor se desactiva con un WARNING (sin el secreto) y el bot arranca normal.

### Autenticación (HMAC-SHA256)

Cada request lleva `X-Purgito-Timestamp` (unix, segundos) y
`X-Purgito-Signature: sha256=<hex>`, con
`hex = HMAC_SHA256(secret, timestamp + "." + body_bytes)`. El receptor debe:

1. rechazar (401) si faltan cabeceras, la firma no coincide (comparación en tiempo constante) o `|now − timestamp| > 300 s`;
2. verificar sobre los **bytes crudos** del body, antes de parsear;
3. deduplicar por `event_id` (eventos) y, opcionalmente, recordar las firmas vistas durante la ventana de 300 s para rechazar repeticiones exactas.

La referencia es `monitor.verify_signature()` (es la que usan los tests como receptor falso). No hay Bearer estático.

### Heartbeat — `POST /v1/heartbeat`

```json
{"node_id": "purgito-prod-01", "timestamp": "2026-10-02T18:00:00.000Z",
 "started_at": "2026-10-02T17:00:00Z", "uptime_seconds": 3600,
 "service": "purgito", "status": "up",
 "discord_latency_ms": 42, "postgres_status": "ok", "postgres_latency_ms": 3,
 "memory_rss_bytes": 115000000, "disk_free_bytes": 2100000000, "version": "abc1234"}
```

Los seis primeros campos son fijos; el resto es opcional. `postgres_status` sale de un `SELECT 1` con timeout de 1 s (`ok`/`down`). Sin tokens, cookies, corpus, mensajes ni nombres. Se empieza a emitir cuando el bot ya terminó de arrancar. Si hay fallos, el intervalo crece con backoff.

### Eventos — `POST /v1/events`

```json
{"event_id": "…", "node_id": "purgito-prod-01", "timestamp": "…",
 "event_type": "service.restart", "severity": "warning", "service": "purgito",
 "message": "…", "metadata": {}}
```

| Tipo | Origen |
|---|---|
| `service.started` | arranque tras cierre limpio (o primer arranque): `metadata.previous_shutdown` = `clean`\|`none` |
| `service.restart` | arranque tras `previous_shutdown: "unexpected"`, `cause: "unknown"` |
| `service.crash` | 3 o más arranques en la última hora (`restarts_1h`) |
| `service.shutdown` | apagado intencional (SIGTERM/SIGINT) |
| `database.failure` | `database.connection_failed` / `database.health_failed` (máx. 1 por minuto) |
| `security.alert` | una regla de detección abrió una alerta |
| `system.warning` | falló una tarea en segundo plano (máx. 1 cada 5 min) |

**`previous_shutdown` sale de `lifecycle_state`** (PostgreSQL) y del `service_state.json`: si cualquiera dice que el proceso anterior no cerró limpio, es `unexpected`. Eso significa **solo** que el proceso anterior desapareció sin shutdown limpio; no se afirma ninguna causa (ni "PostgreSQL cayó"). No se mandan eventos por cada línea de log. `user_id`/`guild_id`/`channel_id`/`source_id` no viajan.

`event_id` es estable entre reintentos y se deduplica también localmente.

### Si el monitor no responde

- Timeouts: 2 s conexión, 3 s total; sin redirects.
- Un fallo se loguea **una vez** (`monitor unreachable …`, sin traceback) y luego como máximo cada 10 min; al volver, `monitor reachable again`.
- Heartbeat: el siguiente intento espera `max(intervalo, 5 s·2ⁿ)`, tope 300 s. Eventos: backoff 5 s → 300 s; 5 intentos (críticos: 20) y se descartan.
- Un 4xx (firma/`node_id` rechazados) no se reintenta y avisa de revisar la config.
- **Outbox acotado:** en memoria hasta 100 eventos; los **críticos** (`service.restart`, `service.crash`, `database.failure`, `security.alert`, cualquier `error`) se persisten en `data/monitor/outbox.jsonl` (máx. 100 eventos y 256 KB; críticos expiran a 24 h, el resto a 10 min), sobreviven a un reinicio y se borran al confirmarse la entrega. Todo lo demás es **best-effort**: si el monitor está caído, se pierde.
- Al apagar, se intenta entregar `service.shutdown` durante a lo sumo 2 s.

### Métricas del monitor

`purgito_monitor_last_success_timestamp`, `purgito_monitor_send_errors_total{kind=heartbeat|event}`, `purgito_monitor_events_sent_total`.

### `/health`

Sigue siendo el liveness público y barato: `{"ok": true, "status": "ok"}` con `Cache-Control: no-store`. `ok` se conserva por compatibilidad con consumidores existentes; `status` es el formato para el monitor. Sin datos sensibles ni consultas a la base.

## Heartbeat y estado del servicio (IMPLEMENTADO)

`data/service_state.json`, reescrito de forma atómica cada 30 s por una tarea
asyncio liviana. **No usa PostgreSQL**: sirve para saber "el bot sigue
ejecutándose" aunque la base esté caída.

Estados: `starting → running → stopping → stopped`. Si al arrancar el estado
previo **no** es `stopped`, el proceso anterior murió sin cerrar limpio →
`service.crash_detected` con `cause: unknown`. Solo se marca `stopped` cuando
el apagado fue por SIGTERM/SIGINT; un `close()` por error fatal no lo marca.

Guarda: `started_at`, `last_heartbeat`, `state`, `previous_state`,
`last_clean_shutdown`, `last_error` (solo tipo y lugar, nunca el mensaje),
y la lista de arranques recientes (→ `restarts_1h` / `restarts_24h`).
Se **complementa** con `lifecycle_state` de PostgreSQL (que sigue siendo la
fuente del aviso "Purgito volvió" en Discord); no lo reemplaza ni lo duplica.

Si el heartbeat no se actualiza en 90 s, `/health/details` informa `stale: true`.

### Contexto de incidente (IMPLEMENTADO)

`/health/details` → `incident` reconstruye, sin inventar: cuándo estuvo vivo por
última vez (`last_seen_alive`, precisión ±30 s), si cerró limpio, último error,
reinicios recientes y los últimos eventos `warning+` anteriores al arranque
(leídos de los JSONL). Si hubo caída, `cause: "unknown"` y una nota que lo dice.
Lo que el nodo **no** puede saber desde dentro: si fue OOM, un kill externo o un
reinicio de systemd. Para eso, `diagnose_purgito` reporta `NRestarts`/`Result`
de systemd y el journal (ver [RUNBOOKS.md](RUNBOOKS.md)).

## Health (IMPLEMENTADO)

| Endpoint | Auth | Respuesta | Uso |
|---|---|---|---|
| `GET /health` | ninguna | `{"ok": true}` (sin cambios) | liveness; monitor externo |
| `GET /health/ready` | ninguna | `{"ready": bool}`, 200 o 503 | readiness: Discord conectado + `SELECT 1` con timeout de 2 s, cacheado 5 s |
| `GET /health/details` | Bearer | estado, heartbeat, latencia, guilds (cantidad), memoria, alertas abiertas, contexto de incidente | diagnóstico |
| `GET /metrics` | Bearer | formato Prometheus | collector |
| `GET /internal/alerts[?status=]` | Bearer | modelo de alertas | control plane |

Detalles de seguridad:

- Nada de stack traces, ni ids de guild, ni datos de usuarios en ninguna respuesta.
- `/health/details`, `/metrics` e `/internal/alerts` requieren `OBSERVABILITY_TOKEN`. **Sin token configurado devuelven 404** (no existen). Además devuelven 404 si la request trae `CF-Connecting-IP`, `X-Forwarded-For`, `X-Real-IP` o `Forwarded` (llegó por el proxy).
- **nginx solo publica `location = /health`** (ver DEPLOY.md). Todo lo demás se consulta directo en `127.0.0.1:8080` — por SSH, Tailscale o el collector local.
- Un token inválido emite `permission.denied` (cuenta para las reglas).

## Métricas (IMPLEMENTADO)

`prometheus-client` 0.25.0 con registro propio. Solo lo que se puede calcular de forma fiable:

| Métrica | Tipo | Origen |
|---|---|---|
| `purgito_up` | gauge | 1 mientras el proceso responde |
| `purgito_uptime_seconds` | gauge | desde el arranque del módulo |
| `purgito_ready` | gauge | último resultado de readiness |
| `purgito_heartbeat_age_seconds` | gauge | edad del último latido |
| `purgito_discord_latency_seconds` | gauge | `bot.latency` (NaN antes del primer heartbeat de Discord) |
| `purgito_guilds` | gauge | `len(bot.guilds)` |
| `purgito_memory_bytes` | gauge | `VmRSS` de `/proc/self/status` |
| `purgito_alerts_open` | gauge | alertas en estado `open` |
| `purgito_errors_total{source}` | counter | eventos `error`/`critical`, por prefijo de tipo |
| `purgito_command_total{result}` | counter | `ok`/`error` (slash y prefijo) |
| `purgito_background_failures_total{task}` | counter | `restart_loop_after_failure` |
| `purgito_db_connection_errors_total` | counter | `init_db` y readiness |
| `purgito_http_requests_total{method,route,status_class}` | counter | middleware; `route` es la ruta canónica, no la URL |
| `purgito_http_request_duration_seconds{route}` | histogram | idem |
| `purgito_events_total{event_type,severity}` | counter | listener de eventos |

Los contadores son del proceso: se reinician con cada arranque (comportamiento
normal de Prometheus). No hay etiquetas con ids de guild/usuario.

## Reglas y alertas (IMPLEMENTADO)

Ver [SECURITY_EVENTS.md](SECURITY_EVENTS.md). Solo **detectan y catalogan**: no
bloquean usuarios, no ejecutan comandos, no responden automáticamente.

## Vector (PREPARADO)

`deploy/vector/vector.toml` — **validado** con Vector 0.58.0 (`vector validate`
y `vector test`, que incluye 4 tests de redacción/dedupe/enrutado), **no instalado**
(instalarlo y elegir el destino es una decisión de despliegue pendiente).

```
collector local (este VM)  ->  destino EXTERNO (otro host)
```

| Fuente | Qué recoge | Normalización |
|---|---|---|
| `data/events.jsonl`, `data/security.jsonl` | eventos del bot (schema v1) | se parsea y se etiqueta `stream` (`events`\|`security`) |
| journald `bot-purg`, `nginx`, `postgresql@18-main` | logs de aplicación/servicio | sobre compatible con el schema (`event_type: log.journal`, severidad desde `PRIORITY`); las líneas `purgito.event:` se **descartan** (ya llegan por el JSONL → sin duplicados) |
| journald `purgito-runbook` | rastro de runbooks | `deployment.runbook_executed` |
| `/var/log/nginx/error.log` | errores de nginx | `log.nginx_error` |
| `/var/log/nginx/access.log` | accesos | IP **hasheada**, sin query string (el callback OAuth trae `?code=`) |
| `GET 127.0.0.1:8080/metrics` | métricas | `prometheus_scrape` cada 30 s con Bearer |

Después: `redact` (segunda barrera de secretos, porque journald/nginx no pasan
por el bot) → `dedupe` por `event_id` → `route` (seguridad aparte del resto) →
sinks **externos**:

- `logs_external`: HTTP NDJSON a `PURGITO_LOGS_URL` (el ejemplo es VictoriaLogs, Apache-2.0). Búfer en disco acotado a 256 MiB (el mínimo de Vector), `drop_newest` si se llena.
- `metrics_external`: `prometheus_remote_write` a `PURGITO_METRICS_URL`.

No hay ningún sink local. Si falta una variable de destino, Vector no arranca.

Requisitos al instalarlo (notas de la validación):

1. Vector ≥ 0.5x exige `--dangerously-allow-env-var-interpolation` (o `VECTOR_DANGEROUSLY_ALLOW_ENV_VAR_INTERPOLATION=true`) para leer `${PURGITO_LOGS_URL}` etc. Pasarlo desde `/etc/vector/vector.env` (modo 0600), no desde el repo.
2. El usuario `vector` necesita los grupos `systemd-journal` y `adm`, y lectura sobre `data/*.jsonl` (el bot los crea 0600 por `UMask=0077`: dar acceso con un grupo/ACL, no con `chmod 644`).
3. Ajustar la ruta del checkout y el nombre de la unidad de PostgreSQL (`postgresql@18-main.service` en este servidor) en `vector.toml`.
4. Validar: `vector validate --dangerously-allow-env-var-interpolation deploy/vector/vector.toml` y `vector test … deploy/vector/vector.toml`.

> **Privacidad.** Enviar `access.log` fuera del VM saca datos de visitantes del
> servidor. Por eso la IP sale hasheada y sin query. Antes de activar el envío,
> revisar que `docs/PRIVACY.md` cubra el destino. Si no se quiere enviar,
> borrar los bloques `nginx_access*` del toml.

## Monitoreo de disponibilidad (PENDIENTE — externo)

No se instaló Uptime Kuma ni nada parecido en este VM: un monitor dentro del
VM que vigila no detecta que el VM desapareció. Configuración recomendada para
cuando exista otro host (otro proveedor/región):

| Monitor | Chequeo | Intervalo | Alerta tras |
|---|---|---|---|
| Purgito (liveness) | `GET https://purgito.app/health` → 200 y `"ok":true` | 60 s | 3 fallos (~3 min) |
| API | `GET https://purgito.app/api/status` → 200 con `guild_count` | 120 s | 3 fallos |
| Sitio público | `GET https://purgito.app/` → 200 | 120 s | 3 fallos |
| Dashboard estático | `GET https://purgito.app/es/perfil` → 200 | 300 s | 2 fallos |
| PostgreSQL (indirecto) | `GET https://purgito.app/health/ready` → 200 | 60 s | 3 fallos |
| Host | ping/TCP 22 por Tailscale o IP pública | 60 s | 3 fallos |
| Certificado TLS | expiración de `purgito.app` | diario | < 14 días |
| Dead-man | ausencia de `purgito_up` / de métricas empujadas por Vector | 5 min | 10 min sin datos |

- `/health/ready` **no está publicado en nginx**. Para el monitor indirecto de PostgreSQL, añadir en `/etc/nginx/conf.d/purgito.conf` (PREPARADO, no aplicado — nginx vive fuera del repo): `location = /health/ready { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }`. Es seguro de publicar: solo devuelve `{"ready": bool}` y está cacheado 5 s.
- Si Purgito no responde: el monitor alerta por un canal que **no** dependa de Purgito (email/push, no el propio bot de Discord). Cloudflare puede devolver 52x/53x con el origen caído; tratar cualquier no-200 como caída.
- "El VM entero desapareció" solo se detecta desde fuera: es el monitor de host + la ausencia de métricas/logs en el destino central.

## Control plane externo (PENDIENTE)

```
panel.purgito.app  (hoy todo vive bajo purgito.app; el nombre es ilustrativo)
        |
        v
control plane externo  ── en OTRO host, nunca en el VM de Purgito
        |
        +---- monitor de disponibilidad
        +---- almacenamiento de logs     <- recibe de Vector
        +---- almacenamiento de eventos / métricas
        +---- motor de alertas           <- consume /internal/alerts + sus propias reglas
        +---- despachador de runbooks    <- SSH por Tailscale a deploy/runbooks/
        |
        v
Purgito VM
```

Lo que el nodo ya deja listo para conectarlo: schema de eventos estable,
modelo de alerta estable (`/internal/alerts`), métricas Prometheus, JSONL y
config de Vector, runbooks con salida JSON y exit codes. El dashboard debe
seguir accesible aunque Purgito esté muerto: por eso no se monta en el VM.

## Dependencias (licencias)

| Paquete | Versión | Licencia | Motivo |
|---|---|---|---|
| `prometheus-client` | 0.25.0 | Apache-2.0 AND BSD-2-Clause | Exposición de métricas; librería de referencia del proyecto Prometheus, Python puro, sin dependencias propias. Escribir el formato a mano habría sido más código y más riesgo. |

Fuera del runtime de Python: **Vector** (MPL-2.0, binario externo, no instalado)
y, como ejemplo de destino, VictoriaLogs/VictoriaMetrics (Apache-2.0) en otro host.
Se evitó AGPL/GPL (Grafana/Loki, etc.) en el camino crítico.

## Activar en producción

```bash
cd /home/purgito/purgito-bot && git pull
.venv/bin/pip install -r requirements.txt          # prometheus-client
openssl rand -hex 32                               # → OBSERVABILITY_TOKEN en .env (opcional)
sudo systemctl restart bot-purg
curl -s localhost:8080/health/ready                # {"ready": true}
curl -s -H "Authorization: Bearer $TOKEN" localhost:8080/metrics | head
python3 deploy/runbooks/purgito_runbooks.py diagnose_purgito
```

Sin `OBSERVABILITY_TOKEN`, el bot funciona igual; solo `/health` y `/health/ready` responden.
Los archivos nuevos (`events.jsonl`, `security.jsonl`, `service_state.json`, `alerts.json`) son runtime y están bajo `data/` (ignorado por git).

## Fuera de alcance de esta fase

SIEM distribuido, clústeres de logs, Kafka, Elasticsearch/OpenSearch, SOAR, EDR,
feeds de threat intelligence, contención o bloqueo automático de IPs/usuarios,
ejecución remota de comandos arbitrarios, detección de anomalías con ML,
multi-región, alta disponibilidad, provisión de un segundo VM.
