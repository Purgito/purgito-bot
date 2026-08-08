# Auditoría de seguridad — resumen ejecutivo (Secciones 1 y 2)

Fecha de cierre: 2026-08-07. Mentalidad red team en las dos secciones:
cualquier input externo es potencialmente hostil, cualquier endpoint público
recibe tráfico de un atacante, no se asume "nadie haría eso".

Cada sección se corrió en varias rondas — la primera cubre el checklist
original, las siguientes vuelven sobre la misma superficie con preguntas más
puntuales o ángulos nuevos. Este documento consolida las **6 rondas totales**
(3 + 3) en un solo lugar para no tener que releerlas todas de nuevo.

---

## 1. Alcance revisado

### Sección 1 — Auth/OAuth, sesiones y permisos

- OAuth2 de Discord: `state` (generación, validación, un solo uso),
  intercambio `code`→token, qué se guarda en la sesión, expiración.
- `EncryptedCookieStorage`: config real de la cookie, rotación de
  `SESSION_SECRET`, session fixation, logout, multi-dispositivo.
- Permisos: cómo se determina "admin de este guild", IDOR vía `guild_id`,
  dueño del bot vs. admin de guild, endpoints administrativos, chequeos
  que solo viven en el frontend, condiciones de carrera de permisos.
- CSRF sobre las acciones que mutan estado.
- Ronda 2: exclusivamente la superficie *nueva* que dejó la Ronda 1
  (`revoked_sessions`, el propio mecanismo de revocación) — fallos de la
  revocación misma, races entre pestañas, wiring de la purga, cobertura
  completa del gate de sesión, y cualquier endpoint de escritura en GET.
- Ronda 3: tamaño/contenido real de la cookie, blast radius de un
  `SESSION_SECRET` filtrado, logging de secretos, manejo de errores del
  callback OAuth, rate limiting de los endpoints de auth mismos, timing
  attacks, endpoints bulk con múltiples `guild_id`.

**Fuera de alcance / diferido:** Polar y todo lo de premium (es la Sección
2). Rutas pensadas para "el dueño del bot" — se buscaron explícitamente y
**no existe ninguna** en la superficie HTTP actual, así que no había nada
que auditar ahí. Qué subdominios de `purgito.app` existen realmente fuera
del repo — el usuario confirmó que no hay ninguno corriendo algo distinto
al bot/dashboard, así que se cerró sin más acción.

### Sección 2 — Premium, Polar y webhooks

- Verificación de firma del webhook (header, algoritmo, comparación,
  timestamp/replay).
- Idempotencia y orden de entrega de webhooks duplicados/tardíos.
- Asociación `guild_id` ↔ suscripción, incluyendo checkout abandonado y
  guilds que dejan de existir.
- Ciclo de vida completo: activación, trial, renovación, cancelación,
  fallo de pago (dunning), reembolso (total y parcial).
- Enforcement server-side de cada límite Premium/Free y TOCTOU sobre los
  contadores.
- El endpoint del webhook como superficie pública: tamaño de body, manejo
  de excepciones, rate limiting, predictibilidad de la URL.
- Ronda 2: específicamente reembolsos (quedó como duda abierta de la
  Ronda 1 y se resolvió con evidencia), reembolsos parciales, período de
  gracia de dunning, reconciliación tras un fallo transitorio, checkout
  abandonado.
- Ronda 3: la condición de carrera dentro del propio mecanismo de
  watermark de la Ronda 1, payloads malformados/inesperados, tamaño de
  body (orden firma-vs-buffering), predictibilidad de la URL del webhook.

**Fuera de alcance / diferido:**

- **Concurrencia general de SQLite/`_db_lock` en el resto de `db.py`.**
  Señalado explícitamente como candidato fuerte para la Sección 3 — ver
  punto 3 más abajo.
- **Trial abuse cross-guild:** se decidió activamente *no* construir
  tracking propio (razón en la sección 6).
- **Aviso de `past_due` en el dashboard:** identificado, no implementado
  (decisión de producto/UX, no de seguridad).
- **Rate limiting exhaustivo de cada endpoint de la API:** solo se
  auditaron y corrigieron los puntos de mayor riesgo identificados
  explícitamente (`/auth/callback`, `/webhooks/polar`) — no hubo un barrido
  sistemático de los ~80 endpoints del dashboard.
- **Período de gracia exacto del dunning de Polar:** depende de la
  configuración de la organización en Polar, no verificable desde el repo.

---

## 2. Hallazgos consolidados

**Nota de conteo:** el total real es **10** (5 + 5), no 9 — Sección 2 tuvo
cinco hallazgos formales, no cuatro (el payload malformado de la Ronda 3 es
distinto de la race condition, aunque salieron en la misma pasada).

| # | Sección · ronda | Severidad | Problema | Fix | Residual conocido |
|---|---|---|---|---|---|
| 1 | S2 · R3 | **Alta** | Race condition real en la sección crítica del watermark de premium: lectura, decisión y escritura eran llamadas separadas, cada una con su propio `_db_lock` | `apply_premium_webhook_change()` hace todo bajo una sola adquisición del lock | Ninguno — la fix es completa. Ver §3 para el patrón general que expone. |
| 2 | S1 · R1 | Media | Logout no invalidaba la sesión del lado del servidor (cookie robada seguía sirviendo) | Tabla `revoked_sessions` + `sid` por login, chequeado en cada gate de sesión | Sesiones emitidas antes del fix no tienen `sid`, no son revocables individualmente (se autolimpia en 7 días) |
| 3 | S2 · R1 | Media | Webhooks de Polar fuera de orden podían pisar el estado correcto de premium | `premium_event_watermark`: descarta eventos más viejos que el último aplicado | Tenía su propia race condition — resuelta en hallazgo #1 |
| 4 | S1 · R3 | Media | `/auth/callback` sin rate limit — un atacante podía agotar el cupo de Discord para el `client_id`, tirando el login de **todos** los guilds | Rate limit 10/min por IP, antes de tocar Discord | Ninguno |
| 5 | S2 · R2 | Media | Reembolsos con `revoke_benefits=true` no cortaban el acceso | Maneja `refund.created`/`refund.updated`, revoca solo si `status=succeeded` y `revoke_benefits=true` | Ninguno — resuelto con evidencia oficial de Polar, no por inferencia |
| 6 | S2 · R3 | Media | Payload con firma válida pero forma inesperada (JSON inválido, o válido pero sin los campos del schema) tumbaba el handler con 500 sin control | `except Exception` → 400 en vez de propagar | Solo alcanzable con la firma real (no explotable sin el secreto) |
| 7 | S1 · R1 | Baja | Ventana de 5 min donde un admin recién degradado en Discord conservaba acceso de escritura al dashboard | TTL del cache de permisos bajado a 60s | Confirmado por vos — sigue siendo una ventana finita, es un trade-off consciente |
| 8 | S1 · R2 | Baja | `/auth/logout` respondía a GET → un atacante podía forzar el logout de una víctima con solo redirigirla ahí | GET→POST; el frontend dispara `fetch(POST)` en vez de un `<a href>` navegable | Ninguno |
| 9 | S1 · R3 | Baja | Logout no revocaba el `access_token` en Discord — un token filtrado durante la sesión seguía siendo válido contra la API de Discord después del logout | `_revoke_discord_token()` best-effort al hacer logout | Best-effort a propósito: si Discord no responde, el logout completa igual |
| 10 | S2 · R1 | Baja | `/webhooks/polar` sin rate limit — mismo proceso que el dashboard | Rate limit 60/min por IP, generoso para no interferir con reintentos legítimos | Ninguno |

---

## 3. El hallazgo más importante

El hallazgo #1 (race condition en `apply_premium_webhook_change`, Alta) es
el más serio de toda la auditoría hasta ahora, y no solo por la severidad
formal. Dos motivos:

**Primero, el radio de impacto es dinero real y sin ambigüedad.** No es un
escenario hipotético: Polar reintenta webhooks activamente, y dos eventos
distintos para el mismo guild (una resuscripción y una baja, por ejemplo)
pueden llegar separados por milisegundos. El bug hacía que el resultado
final dependiera del scheduling de `asyncio`, no de cuál evento era
realmente el más nuevo — un guild podía terminar sin premium habiendo
pagado, o con premium habiendo cancelado, de forma no determinística y sin
ningún rastro de que algo salió mal (el watermark mismo quedaba corrompido).

**Segundo, y esto es lo que importa para la Sección 3: yo mismo introduje
este bug.** El mecanismo de watermark nació en la Ronda 1 de la Sección 2
como el fix correcto para el problema de *orden* de entrega — pero lo
implementé como cuatro llamadas async independientes (leer watermark →
decidir → aplicar cambio → escribir watermark nuevo), cada una con su
propia adquisición de `_db_lock`, en vez de una sola sección crítica. Es
exactamente el mismo error que el propio código YA sabía evitar en otros
lados: cuando audité el TOCTOU de los límites de recursos en esa misma
ronda (`save_gif_url`, `add_embed_template`, etc.), confirmé que **todos**
hacen el chequeo-y-escritura dentro de un único `async with _db_lock`. Mi
propio fix violó el patrón que el resto del codebase ya respetaba
correctamente, y pasó dos rondas de revisión (Ronda 1 y Ronda 2 de la
Sección 2) sin que nadie —yo incluido— lo notara, hasta que la Ronda 3 lo
pidió explícitamente.

**El patrón general a vigilar en la Sección 3:** cualquier secuencia
"leer estado → decidir con ese estado → escribir" que esté partida en
más de una llamada a una función que toma `_db_lock` por su cuenta, en vez
de una sola función que tome el lock una vez para toda la secuencia. Un
lock que protege cada paso individualmente **no** protege la secuencia
completa si hay un `await` entre pasos — esto es fácil de pasar por alto
precisamente porque cada pieza, mirada aislada, parece correcta.

Durante la lectura de `db.py` en la Sección 2 encontré comentarios que
sugieren que los desarrolladores ya venían pensando en los límites exactos
del scope del lock en más de un lugar — por ejemplo, el manejo de
referencias de GIFs (`_retain_gif_object`/`release_gif_reference` en
`save_gif_url`) corre deliberadamente *fuera* de `_db_lock` y en serie, con
un comentario explícito justificando por qué. Eso puede estar perfectamente
bien pensado, o puede tener el mismo tipo de ventana que el watermark —
no lo verifiqué a fondo porque estaba fuera del alcance de las Secciones 1
y 2. Es la primera cola a tirar en la Sección 3.

---

## 4. Estado final verificable

- **Tests:** 532 → 578 (**+46 tests nuevos** en total entre ambas
  secciones). El número base (532) es el de la suite completa *antes* de
  tocar nada en la Sección 1.
- **Corridas de verificación:** la suite completa se corrió antes y
  después de cada ronda (12 rondas de "antes/después" en total). Después
  del hallazgo #1 específicamente, se corrió **25 veces seguidas** con
  timeout duro (no una sola vez) — un hang real en los tests casi pasó
  desapercibido con una sola corrida limpia; documentado en el cierre de
  esa ronda.
- **Lint/format:** `ruff check` y `ruff format --check` limpios en
  absolutamente todo lo tocado en las 6 rondas. Existe un único error de
  `ruff check` en todo el repo (`tests/test_layout_buttons.py`, import sin
  usar) que es **preexistente**, no tocado por esta auditoría, confirmado
  contra `git status` en la primera ronda que lo notó.
- **`landing/build_docs.py --check`:** limpio (solo se tocó el frontend
  una vez, para el fix de `/auth/logout`).

---

## 5. Decisiones tomadas sin pedir permiso explícito en el momento

Cambios de comportamiento/protocolo aplicados como parte de fixes, en un
solo lugar para revisar de un vistazo:

1. **TTL del cache de permisos por guild:** 300s → 60s (S1·R1).
   *Confirmado explícitamente por vos al cierre de esa ronda.*
2. **`/auth/logout`:** GET → POST, con el frontend disparando
   `fetch(POST)` en vez de un link navegable (S1·R2).
3. **Rate limit nuevo en `/auth/callback`:** 10 req/min por IP (S1·R3).
4. **Logout revoca el `access_token` en Discord**, best-effort, además de
   invalidar la sesión local (S1·R3).
5. **Rate limit nuevo en `/webhooks/polar`:** 60 req/min por IP (S2·R1).
6. **Log level de eventos de webhook ignorados:** `debug` → `info` — a
   nivel de producción (`INFO`), antes eran completamente invisibles
   (S2·R1).
7. **`scripts/reconcile_premium.py`:** herramienta nueva, de solo lectura
   a propósito (sin `--apply`) — decisión propia de no darle modo de
   corrección automática porque un falso positivo cortaría el servicio a
   un cliente que sí pagó (S2·R2).
8. **Reembolsos:** la interpretación de cuándo un `refund.*` debe cortar
   el acceso (`status=succeeded` **y** `revoke_benefits=true`, ninguna de
   las dos sola) es una decisión de diseño mía, aunque basada en evidencia
   directa del modelo de datos de Polar, no en inferencia (S2·R2).

---

## 6. Deuda o limitaciones conocidas que quedaron fuera

- **Aviso de `subscription.past_due` en el dashboard.** Identificado en
  S2·R2: el admin no tiene ninguna señal de que el pago falló hasta que el
  premium desaparece de golpe. No implementado — es una decisión de
  producto/UX (dónde y cómo mostrarlo), no una vulnerabilidad. **Pendiente
  de tu confirmación explícita para implementarlo.**
- **Downgrade no destructivo.** Cuando un guild pasa de Premium a Free,
  los datos existentes por encima del nuevo límite (GIFs, embeds, etc.) no
  se borran ni se recortan de inmediato — convergen solo cuando se agregan
  ítems nuevos. Es el comportamiento que dejé como razonable (evitar
  pérdida de datos sorpresiva), pero a diferencia del TTL de arriba,
  **nunca lo reconfirmaste explícitamente** después de que lo señalé en
  S2·R1 — sigue técnicamente abierto.
- **Trial abuse cross-guild.** Decisión activa de *no* construir tracking
  propio: bloquear por `guild_id` es trivialmente evadible (créditos desde
  otro guild) y Purgito no tiene una noción confiable de "misma persona"
  entre guilds — esa deduplicación le corresponde a Polar, que sí ve el
  customer y el método de pago real. Recomendación dada, no bloqueo;
  pendiente de tu confirmación si preferís que igual se intente algo.
- **`scripts/reconcile_premium.py` sin probar contra la API real de
  Polar.** Construido y testeado contra los modelos exactos del SDK
  instalado, pero no tengo credenciales de Polar en este entorno para una
  prueba end-to-end. Recomendado correrlo una vez contra sandbox antes de
  confiar ciegamente en su output.
- **Grace period exacto del dunning.** Confirmado que existe y que
  `subscription.revoked` es el evento terminal confiable, pero la
  duración exacta es configuración de la organización en Polar — externa
  al repo, no verificable ni controlable desde el código.
- **`BOT_OWNER_ID` sin ningún endpoint que lo use.** Notado en S1·R1: la
  variable existe en `config.py` pero no la referencia ningún handler de
  `webapi.py`. No es una vulnerabilidad (no hay ruta rota, simplemente no
  hay ruta) — es código/documentación potencialmente desactualizada, fuera
  del alcance de una auditoría de seguridad. No tocado.
- **Rate limiting del resto de la API.** Solo se atacaron los dos
  endpoints públicos no autenticados de mayor riesgo. El resto de los
  endpoints (`@guild_api`, ya detrás de sesión + permiso de guild) no se
  revisó sistemáticamente por rate limit — el modelo de amenaza ahí es
  distinto (requiere ya estar autenticado como admin de un guild real).
- **El patrón de lock no-atómico del hallazgo #1**, posiblemente presente
  en otras partes de `db.py` no auditadas todavía (ver §3) — es la razón
  concreta por la que la Sección 3 existe a continuación, no una deuda
  "resuelta y pendiente", sino la motivación directa del próximo paso.

---

## 7. Próxima sección

**Secciones 1 y 2 quedan cerradas.** Diez hallazgos confirmados y
corregidos (1 Alta, 5 Media, 4 Baja), con test de regresión para cada uno,
suite completa verde y lint limpio.

**Sección 3 (SQLite: concurrencia, corrupción y race conditions) es la
siguiente.** Y sí — el hallazgo #1 hace que espere que sea una sección
densa, no liviana: no es una sospecha abstracta, es que ya encontré una
instancia real y confirmada del patrón exacto que esa sección
va a estar buscando, la introduje yo mismo en una sección que se suponía
ya auditada, y hay al menos un lugar más en `db.py` (`release_gif_reference`
y el manejo de referencias de GIFs) con un diseño "fuera del lock, a
propósito" que merece la misma vara de revisión antes de asumir que está
bien.
