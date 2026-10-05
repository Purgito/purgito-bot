# Eventos de seguridad, reglas de detección y alertas

Estado: **IMPLEMENTADO** salvo donde se indica. Contexto general en
[OBSERVABILITY.md](OBSERVABILITY.md).

## Tres cosas distintas

| | Qué es | Dónde | Quién lo lee |
|---|---|---|---|
| **Application logs** | Texto de depuración (`log.info/error`) | `bot.log`, journald | quien depura |
| **Audit log** | Historial de cambios de configuración hechos desde el dashboard, por servidor | tabla `audit_log` (PostgreSQL) | admins del servidor, en el dashboard |
| **Security events** | Stream operacional de hechos relevantes para seguridad, de toda la instancia | `data/security.jsonl` → collector | quien opera Purgito |

No todo `ERROR` es un evento de seguridad, y no todo evento de seguridad es un
error. El audit log **no cambia**: sigue siendo la fuente para los admins. Los
eventos de seguridad lo complementan; las acciones sensibles aparecen en ambos
(`security.admin_action` es solo `{guild_id, user_id, action}`, sin el `detail`
que puede traer texto del usuario).

## Eventos de seguridad emitidos

| Evento | Severidad | Dónde | Campos útiles |
|---|---|---|---|
| `auth.login_failure` | warning | `_auth_callback` | `reason` ∈ `oauth_state_invalid`, `token_exchange_failed`, `discord_user_fetch_failed`, `discord_guilds_fetch_failed`, `discord_api_unreachable`, `no_manageable_guilds`; `source_id`, `http_status` |
| `auth.login_success` | info | `_auth_callback` | `user_id` |
| `auth.logout` | info | `_auth_logout` | `user_id` |
| `auth.session_revoked` | warning | `_session_logged_in` (se usó un `sid` ya revocado) | `user_id` |
| `permission.denied` | warning | `check_guild_access` (`reason: not_guild_manager`), endpoints internos (`observability_token_invalid`) | `guild_id`, `user_id`, `endpoint`, `source_id` |
| `webhook.signature_invalid` | warning | `/webhooks/polar` | `source_id` |
| `webhook.rejected` | warning | `/webhooks/polar` | `reason` ∈ `secret_not_configured`, `payload_invalid` |
| `rate_limit.triggered` | warning | `_rate_ok` (todos los buckets) | `bucket`, `source_id`; máx. 1 evento / 10 s por cliente+bucket |
| `security.admin_action` | info | `_log_audit` para: `corpus.amnesia`, `manager_role.set/clear`, `prefix.set/reset`, `exempt_roles.add/remove`, `excluded_users.add/remove`, `updates_channel.set`, `embeds.send/schedule` | `guild_id`, `user_id`, `action` |
| `security.alert_opened` | según la regla | motor de reglas | `rule_id`, `alert_id` |

Lo que **no** se cubre todavía (PENDIENTE): errores de autorización de los
chequeos finos por canal/rol dentro de handlers (hoy solo el control central
`check_guild_access`), cambios de configuración fuera del conjunto sensible
arriba, y fallos de validación de input.

### Privacidad

- No se guarda la IP: `source_id` es un HMAC-SHA256 truncado (12 hex) con `SESSION_SECRET`. Sirve para agrupar ("10 denegados del mismo origen"), no para identificar a nadie, y no se puede revertir sin el secreto.
- `user_id` es el id de Discord (ya presente en `audit_log`).
- Nunca se guarda contenido de mensajes, corpus, cookies, tokens ni el `detail` del audit log.

## Reglas de detección

Declarativas, en `src/observability/rules.py` (`RULES`). Cada una: `rule_id`,
`severity`, tipos de evento, `count` dentro de `window_seconds`, agrupación
opcional y filtros (`where`, `min_fields`). Las ventanas viven en memoria: se
reinician con el proceso.

| `rule_id` | Condición | Agrupa por | Severidad |
|---|---|---|---|
| `auth.login_failure_burst` | 5 × `auth.login_failure` en 5 min | `source_id` | warning |
| `permission.denied_burst` | 10 × `permission.denied` en 5 min | `source_id` | warning |
| `webhook.signature_invalid_burst` | 3 × `webhook.signature_invalid` en 10 min | `source_id` | warning |
| `rate_limit.flood` | 20 × `rate_limit.triggered` en 5 min | `source_id` | warning |
| `service.restart_loop` | `service.started` con `restarts_1h ≥ 3` | global | error |
| `service.crash_detected` | 1 × `service.crash_detected` | global | error |
| `database.connection_failed_repeated` | 3 × (`database.connection_failed` ∪ `database.health_failed`) en 5 min | global | error |
| `background.task_failed_repeated` | 5 × `system.background_task_failed` en 10 min | global | error |

Un evento sin el campo de agrupación (`source_id`) no cuenta: no se inventa un origen.
Agregar una regla = sumar un `Rule(...)` a `RULES` (un test valida que solo use tipos registrados).

**Las reglas no actúan.** No bloquean usuarios, no banean IPs, no ejecutan
comandos, no reinician nada. Detectan y dejan un registro.

## Modelo de alerta

`data/alerts.json` (atómico, máx. 200) y `GET /internal/alerts[?status=open|acknowledged|resolved]` (Bearer, ver OBSERVABILITY.md).

```json
{
  "alert_id": "9f2c1e0ab34d5566",
  "rule_id": "auth.login_failure_burst",
  "severity": "warning",
  "status": "open",
  "created_at": "2026-10-02T17:58:01Z",
  "updated_at": "2026-10-02T17:58:01Z",
  "source": "purgito-bot@purgito",
  "summary": "5 login failures en 5 minutos desde el mismo origen",
  "details": {"reason": "5 eventos auth.login_failure en 300s (source_id=ab12…)",
              "group_key": "ab12cd34ef56", "window_seconds": 300, "threshold": 5, "match_count": 5},
  "related_events": [{"event_id": "…", "timestamp": "…", "event_type": "auth.login_failure",
                      "reason": "oauth_state_invalid", "request_id": "…"}]
}
```

- Estados: `open` → `acknowledged` → `resolved`. Mientras una alerta de (regla, grupo) siga abierta o reconocida, nuevas coincidencias la **actualizan** (`updated_at`, `match_count`) en vez de crear otra; tras `resolved`, una nueva ráfaga abre una nueva.
- `related_events` guarda los últimos 10 como resumen (sin contenido).
- Cambiar el estado hoy se hace desde Python (`AlertStore.acknowledge/resolve`); **no hay endpoint de escritura ni UI** a propósito (PENDIENTE: lo definirá el control plane). El endpoint HTTP es de solo lectura.
- Cada alerta abierta también emite `security.alert_opened`, así que llega al destino central por el mismo canal que el resto de eventos.
