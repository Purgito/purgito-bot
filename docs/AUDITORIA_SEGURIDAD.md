# Auditoría de seguridad — resumen ejecutivo (Secciones 1, 2 y 3)

Secciones 1 y 2 cerradas el 2026-08-07. Sección 3 (concurrencia, corrupción
y race conditions en SQLite) cerrada el 2026-09-18, retomando exactamente el
punto donde el §7 de este mismo documento la había dejado planteada como
siguiente paso. Mentalidad red team en las tres: cualquier input externo es
potencialmente hostil, cualquier endpoint público recibe tráfico de un
atacante, no se asume "nadie haría eso" — y para la Sección 3 en particular,
ningún `await` entre dos pasos de una secuencia se asume "total, nadie va a
estar escribiendo justo ahí".

Cada sección se corrió en varias pasadas — la primera cubre el alcance
original, las siguientes vuelven sobre la misma superficie con preguntas más
puntuales o ángulos nuevos. Este documento consolida **10 pasadas totales**
(3 + 3 + 4) en un solo lugar para no tener que releerlas todas de nuevo.

**Nota sobre cómo se armó la entrada de la Sección 3:** sus primeras tres
pasadas ya estaban implementadas y testeadas en el código al empezar esta
sesión — vienen de trabajo anterior que corrigió los problemas pero nunca
volvió a este documento a cerrarlos por escrito. `tests/test_race_conditions_db.py`,
`tests/test_guild_cleanup_gif_refs.py`, `tests/test_refeed_channel_guard.py`
y `tests/test_db_rollback.py` (más el propio `_RollbackOnErrorLock` y los
comentarios de `db.py`) son la fuente real de esas tres pasadas; lo que
faltaba era exactamente esto, consolidarlas en un solo lugar. La cuarta
pasada sí se hizo en esta sesión, al revisar si quedaba algún hueco en el
mismo patrón antes de dar la sección por cerrada — ver hallazgo #17.

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

### Sección 3 — SQLite: concurrencia, corrupción y race conditions

Alcance: el patrón exacto que dejó planteado el cierre de la Sección 2 (§3
más abajo) — cualquier secuencia "leer estado → decidir con ese estado →
escribir" partida en más de una adquisición de `_db_lock`, con un `await`
real entre los pasos. Cuatro pasadas:

- **Pasada 1** (`tests/test_race_conditions_db.py`): barrido explícito de
  `db.py` buscando más instancias del mismo patrón que ya había tumbado el
  watermark de premium (hallazgo #1). `asyncio.gather` para simular
  concurrencia real, igual que en la Sección 2.
- **Pasada 2** (`tests/test_guild_cleanup_gif_refs.py`): `guild_cleanup_task`
  (`cogs/general.py`), la tarea diaria que purga guilds que se fueron hace
  más de `GUILD_DATA_RETENTION_DAYS`. No es `db.py`, pero orquesta varias
  llamadas a `db.py` cada una con su propio lock — mismo riesgo de fondo.
- **Pasada 3** (`tests/test_refeed_channel_guard.py` +
  `tests/test_db_rollback.py`): dos hallazgos de forma distinta al patrón de
  arriba pero de la misma familia (concurrencia sobre estado compartido en
  SQLite) — múltiples puntos de entrada a una misma operación, y qué pasa
  con el lock mismo cuando una escritura falla a mitad de camino.
- **Pasada 4** (esta sesión): repaso final de `guild_cleanup_task` — el
  chequeo de membresía que la Pasada 2/Sección 5 le agregó es un único punto
  en el tiempo, pero el trabajo que hace después no es instantáneo. Ver
  hallazgo #17.

**Fuera de alcance / diferido:**

- **Los scripts de `scripts/*.py`** (`reconcile_gif_objects.py`,
  `wipe_all_gifs.py`, `backfill_gif_phashes.py`, `audit_cross_guild_gifs.py`,
  `reconcile_premium.py`) abren su propia conexión a `bot.db`, **fuera** de
  `_db_lock` y del proceso del bot — un ángulo de concurrencia real, pero
  mayormente ya cubierto por control operativo, no de código: cada uno
  destructivo documenta en su docstring "conviene parar el bot mientras
  corre", y el único pensado para correr con el bot en marcha
  (`cleanup_dead_cdn_gifs.py`) explica por qué sus SELECT/DELETE puntuales
  no necesitan `_db_lock` para ser seguros. Revisando los seis en esta
  pasada, a `audit_cross_guild_gifs.py --apply` le faltaba esa misma
  advertencia (hallazgo #18) — corregido; `reconcile_premium.py` no la
  necesita, nunca escribe. Sigue siendo un control humano, no un lock —
  ver la deuda conocida más abajo.
- **`trim_corpus_if_needed` / `trim_guild_total_if_needed` /
  `trim_user_corpus_if_needed`** (recorte de cuota del corpus): las tres
  hacen un `COUNT(*)` sin lock y después el `DELETE` bajo `_db_lock` aparte —
  la misma forma que el patrón peligroso, encontradas con el mismo barrido
  de la Pasada 1. Revisadas a fondo y **cerradas sin fix**: el `DELETE` real
  vuelve a calcular qué filas borrar en el momento (`ORDER BY id ASC LIMIT
  ?` contra el estado actual, no contra el conteo viejo), así que el peor
  caso de una lectura desactualizada es recortar de más o de menos por un
  mensaje puntual en una sola pasada — se autocorrige solo en la próxima
  llamada. Es housekeeping de almacenamiento, no un límite de seguridad
  duro ni una superficie con consecuencia irreversible; no amerita el mismo
  tratamiento que un conteo que decide dinero o acceso (comparar con
  hallazgo #15, que sí lo amerita).
- **Multi-proceso sobre `bot.db` fuera de los scripts de arriba**: no
  aplica — `DEPLOY.md` corre el bot como un único proceso systemd
  (`bot-purg.service`); no hay un segundo worker ni un segundo proceso del
  bot mismo escribiendo la misma base concurrentemente.
- **Pool de conexiones / múltiples conexiones aiosqlite**: no aplica —
  `db.py` usa una sola conexión de proceso (`_db`) a propósito, con
  `_db_lock` serializando todo acceso de escritura; no hay una segunda
  conexión que pueda ver un estado a medio confirmar por WAL entre
  procesos.

---

## 2. Hallazgos consolidados

**Nota de conteo:** el total real es **18** (5 + 5 + 8), no 10 — Sección 2
tuvo cinco hallazgos formales, no cuatro (el payload malformado de la Ronda
3 es distinto de la race condition, aunque salieron en la misma pasada), y
la Sección 3 suma ocho entre sus cuatro pasadas (#11-18 en la tabla).

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
| 11 | S3 · P2 | **Alta** | `guild_cleanup_task` borraba los GIFs de un guild expirado con `r2.delete_url(url)` directo; los GIFs con `content_hash` son objetos de R2 compartidos entre guilds (dedup), así que esto podía borrar físicamente el objeto que OTRO guild, todavía activo, seguía necesitando | Usa `db.release_gif_reference` (consciente del `ref_count`), igual que el resto de los caminos de borrado de GIFs | Ninguno — el objeto solo se borra cuando ningún guild lo referencia más |
| 12 | S3 · P3 | **Alta** | `_db_lock` era un `asyncio.Lock` liso: una excepción a mitad de una secuencia de `execute()` bajo el lock (disco lleno, el disparador real) dejaba la transacción abierta y sin confirmar en `_db` — la única conexión del proceso — y el PRÓXIMO caller que tomara el lock confirmaba también esos restos junto con su propio commit, sin que nadie se enterara. Afecta a las ~90 funciones de `db.py` por igual, no a una sola feature | `_db_lock` pasa a ser `_RollbackOnErrorLock` (subclase de `asyncio.Lock`): si el bloque `async with` termina por excepción, hace `_db.rollback()` antes de soltar el lock | Ninguno — la conexión queda utilizable de inmediato para la siguiente escritura |
| 13 | S3 · P1 | Media | `block_gif` leía qué filas borrar ANTES de tomar el lock del INSERT+DELETE; un `save_gif_url` concurrente del mismo `content_hash` podía colar una copia nueva que ese DELETE, armado contra la lista vieja, nunca tocaba — el contenido bloqueado seguía disponible para que el bot lo sorteara | La lectura de qué filas borrar pasa a vivir DENTRO del mismo `_db_lock` que el INSERT del blocklist y el DELETE | Ninguno |
| 14 | S3 · P1 | Media | `wipe_gifs` podía dejar una referencia fantasma en `gif_objects` (`ref_count>0` sin ninguna fila de `corpus_gifs` que la respalde) si un `save_gif_url` de un `content_hash` nuevo caía en la ventana entre su lectura y su DELETE — el barrido periódico (`get_live_gif_keys`) confía en `ref_count` y nunca la detecta sola | La lectura de qué filas soltar y el DELETE van bajo el MISMO `_db_lock` | Ninguno |
| 15 | S3 · P1 | Media | `add_shared_embed` chequeaba el límite diario con `count_shared_embeds_today` sin lock y decidía "¿ya llegó al límite?" en el llamador, aparte del INSERT — N requests casi simultáneos podían pasar todos el mismo conteo viejo y generar más links compartidos por día de los permitidos | El conteo y el INSERT van bajo el MISMO `_db_lock`, con un solo commit | Ninguno |
| 16 | S3 · P3 | Media | `_refeed_channel` tenía tres entradas independientes (`/refeed`, `/refeed_channels`, `on_guild_channel_update`) que no se conocían entre sí; dos podían correr en paralelo sobre el MISMO canal, leyendo y pisando el progreso de `channel_refeed_status` del otro (`upsert_channel_refeed_status` hace un COALESCE simple, sin comparar contra lo que ya había) | Guard en memoria `_refeeding_channels` (mismo patrón que `_refeed_running`): la segunda corrida sobre un canal ya ocupado vuelve sin tocar nada | Ninguno — el guard se libera en un `finally`, incluso si la corrida real tira una excepción |
| 17 | S3 · P4 | Baja | El re-chequeo de membresía de `guild_cleanup_task` (fix de Sección 5) es un único punto en el tiempo, antes de un loop que puede tardar minutos en guilds con muchos GIFs (un `await` a R2 por ítem) — un guild que se reincorpora A MITAD de ese loop no se detecta, y sus referencias siguen liberándose como si el guild siguiera ausente | Re-chequea `bot.get_guild` antes de CADA GIF/imagen liberada, no solo una vez al principio; si detecta el rejoin, aborta sin correr `purge_guild_data` | Sigue quedando una ventana del tamaño de un único `await` (mismo residuo que ya documenta `release_gif_reference`) — cerrarla del todo necesitaría un lease sobre R2, que no existe hoy |
| 18 | S3 · P4 | Baja | `scripts/audit_cross_guild_gifs.py --apply` escribe con su propia conexión `sqlite3`, fuera de `_db_lock` y del proceso del bot, sin la advertencia operativa ("conviene parar el bot mientras corre") que sí tienen sus scripts hermanos (`reconcile_gif_objects.py`, `wipe_all_gifs.py`, `backfill_gif_phashes.py`) | Se agregó la misma advertencia al docstring | No hay riesgo de corrupción real (`ref_count` se recalcula contando `corpus_gifs` en el mismo UPDATE, no se incrementa/decrementa a ciegas) — el residuo es, a lo sumo, un "database is locked" por contención si se corre con el bot activo |

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

**Cierre de este punto:** era la primera cola a tirar y se tiró — la Pasada
1 de la Sección 3 auditó a fondo `release_gif_reference` / `_retain_gif_object`
/ `save_gif_url` / `wipe_gifs`. Resultado: el diseño está bien pensado, no
tiene el mismo hueco que el watermark. El decremento del `ref_count` y el
borrado físico van en DOS pasadas de `_db_lock` a propósito (no una), con
un DELETE final condicionado a `ref_count<=0` justo antes de tocar R2 — ese
DELETE es el chequeo atómico: si algo incrementó el `ref_count` mientras
tanto, no borra nada y el objeto físico nunca se toca. Queda un residuo
documentado (una ventana del tamaño de un único `await` entre ese DELETE y
que `r2.delete_key` termine, que solo un lease sobre el objeto cerraría del
todo), pero es un residuo conocido y aceptado, no un bug. Lo que sí tenía el
mismo hueco que el watermark eran otras tres secuencias de `db.py` que no
llamaban a esta — ver hallazgos #13-15.

---

### El hallazgo más importante de la Sección 3

A diferencia de la Sección 2, acá no hay un solo hallazgo que domine por
impacto de negocio — hay dos que dominan por alcance, y por razones
distintas.

**El hallazgo #12 (`_RollbackOnErrorLock`) es el más profundo.** Los
hallazgos #13-15 son tres instancias puntuales del patrón "lock no atómico"
en tres funciones concretas (`block_gif`, `wipe_gifs`, `add_shared_embed`).
El #12 es distinto: no es una instancia más del patrón, es un hallazgo sobre
el propio mecanismo que todas las ~90 funciones de `db.py` usan para
protegerse. Antes del fix, cualquier excepción sin atrapar a mitad de
CUALQUIER secuencia de escrituras — no una feature puntual, cualquiera,
disparada por algo tan mundano como el disco lleno — dejaba una transacción
a medio confirmar en la única conexión del proceso, y el PRÓXIMO caller que
tomara el lock (para escribir algo completamente distinto, de otra feature)
terminaba confirmando también esos restos junto con su propio commit. El
radio de impacto no está acotado a GIFs ni a premium: es cualquier fila de
cualquier tabla que la mala suerte pusiera "detrás" en la cola del lock.

**El hallazgo #11 (`guild_cleanup_task` con `r2.delete_url` directo) es el
más grave por consecuencia concreta.** A diferencia de los hallazgos de
Pasada 1 (que necesitan una ventana de concurrencia específica para
disparar), este pasaba determinísticamente cada vez que dos guilds
compartían un GIF por deduplicación exacta (el caso normal y esperado de
`gif_objects`, no un edge case) y uno de los dos dejaba de usar el bot: el
otro guild, que seguía activo y nunca hizo nada para provocarlo, terminaba
con un link roto. Sin ambigüedad, sin necesitar mala suerte de timing — la
tarea diaria de limpieza rompía datos de un tercero inocente como
comportamiento normal, no como caso raro.

Los dos comparten la misma lección que ya dejó la Sección 2: código que se
ve correcto **mirado aislado** (cada `_db_lock` bien tomado, cada `try` bien
puesto) puede ser incorrecto en conjunto si no se revisa la secuencia
completa contra qué más puede estar pasando al mismo tiempo, o contra qué
puede fallar a mitad de camino.

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

### Sección 3

- **Tests:** las cuatro pasadas de Sección 3 suman **19 tests** dedicados
  (`test_race_conditions_db.py`: 6, `test_guild_cleanup_gif_refs.py`: 4 —
  3 de la Pasada 2 + 1 de la Pasada 4, `test_refeed_channel_guard.py`: 5,
  `test_db_rollback.py`: 4). No tengo el número base de la suite completa
  antes de que se aplicaran las tres primeras pasadas (vienen de sesiones
  anteriores no documentadas, ver la nota al principio de este documento),
  así que no puedo dar un antes/después global honesto como sí se hizo para
  Secciones 1 y 2 — lo verificable hoy es el estado final.
- **Corrida de verificación de esta sesión:** suite completa, **1663 tests,
  todos verdes**, corrida dos veces (antes y después de aplicar el fix de la
  Pasada 4). El entorno no traía `.venv` armado; se creó desde
  `requirements.txt` + `pytest`/`ruff` para poder correrla.
- **Lint/format:** `ruff check .` y `ruff format --check .` limpios contra
  la versión pineada en CI (`ruff==0.15.8`, no la última de PyPI — instalar
  sin pinear trae reglas nuevas que CI no aplica y da falsos positivos, tal
  como advierte el propio comentario de `.github/workflows/ci.yml`).
  **Corrección sobre la nota de Secciones 1/2:** el único error preexistente
  que se había dejado señalado en `tests/test_layout_buttons.py` ya no
  existe — `ruff check .` da limpio en todo el repo hoy. Se corrigió en
  algún punto entre el cierre de la Sección 2 y esta sesión, no como parte
  de este trabajo.
- **`landing/build_docs.py --check`:** no aplica — la Sección 3 no tocó
  `landing/`, `docs/*.md` de cara al usuario ni ningún `.css`/`.js`.

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

### Sección 3

Las Pasadas 1-3 se implementaron en sesiones anteriores a esta — no hay
registro en este documento de qué se confirmó con vos en su momento, así
que no puedo atestiguar eso acá, solo que el código y los tests existen y
están verdes hoy. Lo que sí decidí en esta sesión (Pasada 4), sin pedir
confirmación previa porque son ambos correcciones acotadas y en la misma
línea que el resto de la sección:

9. **`guild_cleanup_task` re-chequea membresía por cada GIF/imagen
   liberada**, no solo una vez al principio del loop — abre la posibilidad
   de que la tarea "aborte a mitad de camino" con algún residuo puntual
   (ver hallazgo #17), un caso nuevo que no existía antes del fix.
10. **`scripts/audit_cross_guild_gifs.py`** suma la misma advertencia
    operativa que ya tenían sus scripts hermanos — solo texto en el
    docstring, ningún cambio de comportamiento.

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
  pérdida de datos sorpresiva) tras señalarlo en S2·R1 — **confirmado
  explícitamente y cerrado** (Sección 7 lo documentó además en
  `REFUNDS.md`).
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

### Sección 3

- **La ventana residual de un único `await` en `guild_cleanup_task`**
  (hallazgo #17) y en `release_gif_reference` (revisado, correcto, ver §3):
  ambas comparten el mismo límite — cerrarlas del todo necesitaría un lease
  sobre el objeto de R2, que no existe hoy. Aceptado como residuo conocido,
  no bloqueante: el peor caso es un único GIF con link roto en una ventana
  de segundos, no una purga completa de datos ajenos.
- **`trim_corpus_if_needed`/`trim_guild_total_if_needed`/
  `trim_user_corpus_if_needed`** tienen la misma forma "COUNT sin lock,
  DELETE con lock aparte" que el patrón peligroso, pero revisadas y
  cerradas sin fix (ver §1, Sección 3) — housekeeping de almacenamiento
  autocorregible, no una superficie de seguridad. Documentado acá para que
  quede claro que se revisaron, no que se pasaron por alto.
- **Control operativo, no de código, sobre los scripts de `scripts/*.py`.**
  Cada uno destructivo advierte "parar el bot antes de correr" en su propio
  docstring (y ahora los seis, con el fix del hallazgo #18), pero nada en
  el código lo hace cumplir — un operador que ignore la advertencia y corra
  `--apply` con el bot en marcha no tiene ningún guardrail automático que lo
  frene. Aceptado a propósito: son herramientas de mantenimiento manual,
  usadas por vos, no superficie expuesta a terceros.
- **Documentación de Secciones 4-9 pendiente.** Al revisar el código para
  cerrar esta sección encontré referencias explícitas en tests y
  comentarios a rondas ya aplicadas de las Secciones 4 (R2: descargas
  acotadas, bloqueo de IP privada/DNS rebinding, concurrencia de subidas),
  5 (idempotencia de tareas en background y reenvío de eventos del
  gateway), 6 (IDOR de `pack_id` en frase_packs), 7 (investigación forense
  del auto-borrado agresivo de GIFs, retención de audit_log), 8 (límites de
  Markov/reacciones/unblock sin cuota) y 9 (alcance de rol vs. permiso
  amplio, patrón de build_markov_model) — todas con tests verdes hoy, pero
  **ninguna consolidada en este documento** como sí se hizo ahora con la
  Sección 3. No es una vulnerabilidad, es una deuda de documentación: este
  archivo quedó desactualizado respecto al código real durante varias
  sesiones. Recomendación: repetir este mismo ejercicio de consolidación
  para 4-9 — no lo hice en esta sesión porque no fue lo que se pidió, pero
  queda anotado para que no se pierda.

---

## 7. Próxima sección

**Secciones 1, 2 y 3 quedan cerradas.** 18 hallazgos confirmados y
corregidos (3 Alta, 9 Media, 6 Baja) entre las tres, con test de regresión
para cada uno, suite completa verde (1663 tests) y lint/format limpios
contra la versión de `ruff` pineada en CI.

La Sección 3 confirmó la sospecha con la que cerró la Sección 2: el
patrón de lock no-atómico del hallazgo #1 no era un caso aislado. Aparecía
en al menos tres funciones más de `db.py` (#13-15) y en una tarea completa
de background (#11), y la revisión de fondo destapó además un segundo
problema de la misma familia pero más profundo — el propio lock no hacía
rollback ante una excepción a mitad de una secuencia (#12), con radio de
impacto sobre las ~90 funciones del módulo, no una feature puntual.
`release_gif_reference`, señalado explícitamente como "la primera cola a
tirar", resultó estar bien diseñado — no todo lo que parecía sospechoso
tenía en efecto el bug.

**Lo que sigue no es una Sección 4 nueva:** ya existe en el código, con
tests verdes, desde antes de esta sesión (Secciones 4 a 9 — ver la deuda de
documentación en §6 de arriba). El próximo paso real es decidir si vale la
pena repetir este mismo ejercicio de consolidación para esas seis
secciones, o si alcanza con que el código y los tests sigan siendo la
fuente de verdad y este documento quede como está. Ninguna de las dos es
una tarea de seguridad pendiente — es una decisión sobre qué tan al día
querés mantener este archivo.
