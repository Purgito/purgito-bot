# Bloqueo absoluto de aprendizaje NSFW + auditoría y saneamiento histórico

Fecha: 2026-08-15

## Contexto

Purgito aprende el estilo de chat de un servidor leyendo mensajes de los
canales listados en `corpus_allowed_channels` y construyendo un modelo de
Markov por servidor. Hoy no existe ninguna comprobación de
`channel.is_nsfw()` en ningún punto del pipeline (confirmado por auditoría
de código: cero referencias a "nsfw" en `src/`, `tests/`, `landing/`).

Riesgo real identificado: `ensure_corpus_migrated` (`src/cogs/chat.py`), la
migración one-shot que sembró `corpus_allowed_channels` la primera vez que
el bot arrancó con la feature de allowlist, agregó **todos** los canales de
texto de cada guild (salvo los `ignored_channels`) — incluyendo canales
NSFW. Cualquier guild que existiera antes de esa migración pudo haber
tenido canales NSFW aprendiendo desde entonces sin ninguna acción del
admin.

## Objetivo

1. Bloqueo no configurable: ningún canal NSFW puede entrar al pipeline de
   aprendizaje, por ningún camino (mensaje en vivo, refeed, migración,
   endpoint, restart).
2. Auditoría retroactiva: determinar qué guilds tienen o tuvieron canales
   NSFW en el aprendizaje, y sanear ese contenido sin borrar corpus sano.

## Principio de diseño

Nunca persistir un booleano "es NSFW" en la base de datos. Discord es la
única fuente de verdad — guardar un flag cacheado es exactamente el tipo de
desincronización que causó el problema original. Cada punto de decisión
pregunta `channel.nsfw` en el momento (lectura de propiedad ya cacheada por
discord.py sobre el objeto de canal del gateway — no es una llamada HTTP
extra, no añade latencia perceptible).

## Componentes

### 1. Gate compartido

`is_learning_allowed(guild, channel) -> bool` en `src/cogs/chat.py`:
`is_corpus_allowed(guild.id, channel.id)` AND NOT `channel.nsfw`.

Reemplaza los usos actuales de `is_corpus_allowed` en solitario en:

- `_on_message_impl` — ingestión en vivo.
- `_refeed_channel_locked` — usado tanto por `/refeed` como por
  `/refeed_channels`.
- `ensure_corpus_migrated` — deja de sembrar canales NSFW en guilds que
  todavía no corrieron esta migración.

### 2. Reacción a flip SAFE → NSFW

`on_guild_channel_update` (`src/cogs/chat.py`) gana una comparación
explícita `before.nsfw` vs `after.nsfw`. Al detectar el flip a NSFW:

- Purga inmediata de `corpus_messages` y `user_corpus` de ese canal.
- `generation.reset_guild_caches(guild_id)`.
- Se saca el canal de `corpus_allowed_channels`.
- Todo esto pasa independientemente del resto de la lógica de visibilidad
  que ya tiene ese handler.

Política: el estado NSFW *actual* es lo único accionable. No se intenta
reconstruir si un canal fue NSFW en el pasado y dejó de serlo — no hay
timestamps confiables para esa reconstrucción y cualquier intento sería
falsa precisión.

### 3. Barrido de auto-saneamiento en cada arranque

En `Chat.on_ready` (ya itera guilds para la migración vieja), por cada
guild: re-validar cada fila de `corpus_allowed_channels` contra el estado
NSFW en vivo. Cualquier canal actualmente NSFW se saca del allowlist, se
purga su corpus, se resetea la cache, y se loguea.

Corre en cada reconexión — barato (solo lectura de propiedades ya
cacheadas), idempotente, autosana cualquier drift ocurrido mientras el bot
estuvo desconectado. No es una migración de un solo uso con flag: es un
invariante que se re-verifica siempre que el bot arranca.

### 4. Cambio de esquema: trazabilidad en `user_corpus`

`user_corpus` (corpus de estilo por autor) no tiene `channel_id` — no se
puede saber de qué canal vino un mensaje que alimentó el estilo de un
usuario.

Migración: `ALTER TABLE user_corpus ADD COLUMN channel_id INTEGER`,
retro-poblada haciendo join por `message_id` contra `corpus_messages` donde
sea posible. Filas donde ese join no encuentra match quedan `NULL` y se
reportan como `UNKNOWN — untraceable`, nunca se asumen seguras.

### 5. Webapi

- `POST /api/server/{id}/settings/corpus` (`_api_corpus_post`) y
  `POST /api/server/{id}/settings/corpus/import/{channel_id}`
  (`_api_corpus_import_post`) ganan la comprobación NSFW.
- Hallazgo adicional de la auditoría, fuera del pedido original pero
  directamente relevante: `_api_corpus_import_post` hoy no tiene **ningún**
  chequeo de permisos — acepta cualquier `channel_id` del guild sin
  verificar `_member_can_view_channel`. Se corrige en el mismo cambio,
  porque dejarlo abierto sería un bypass del gate NSFW desde el día uno.
- Un `channel_id` manipulado en cualquiera de los dos endpoints se rechaza
  en el servidor sin importar qué mandó el frontend.

### 6. Frontend

`GET /api/guilds/{id}/channels` (`_api_channels`) gana un campo `nsfw` por
canal. La columna "Aprende" del selector de canales en
`landing/js/dash.js` deshabilita el toggle para canales NSFW con una
etiqueta corta explicando por qué, en vez de dejar que el click viaje y
vuelva con un 403. El rechazo del backend sigue siendo la protección real;
esto es solo evitar la vuelta redonda inútil.

### 7. Herramienta de auditoría/saneamiento: `scripts/audit_learning_sources.py`

Script standalone. Se loguea a Discord con el token del bot (intent de
guilds solamente, no necesita message content) para leer el estado NSFW en
vivo, y cruza contra la DB.

**Modo por defecto (sin flags): solo reporte, no destructivo.**

Por guild:

- Cada canal en `corpus_allowed_channels` clasificado `SAFE` /
  `NSFW_CURRENTLY` / `UNKNOWN_CANNOT_VERIFY` (canal borrado, bot expulsado,
  sin permiso de ver — nunca se asume seguro ante duda).
- Conteo de filas en `corpus_messages` por canal.
- Filas de `user_corpus` con `channel_id` NULL por guild (tras la
  migración del punto 4).

**Modo `--apply`**: ejecuta el saneamiento sobre todo lo clasificado
`NSFW_CURRENTLY` — borra `corpus_messages` y las filas trazables de
`user_corpus` de ese canal, lo saca de `corpus_allowed_channels`. Ignora
`UNKNOWN` (nunca destructivo ante ambigüedad — se imprime aparte para
juicio manual). Pide confirmación salvo `--yes`. Al terminar imprime un
recordatorio operativo: reiniciar el proceso del bot después, porque la
cache de Markov es en RAM por proceso y no se autoinvalida hasta el
próximo barrido de `on_ready` o un restart.

### 8. Tests

- `tests/test_nsfw_learning_guard.py` (nivel DB): `is_learning_allowed`,
  que la migración de seed salte canales NSFW, purga en
  `on_guild_channel_update` al detectar el flip.
- `tests/test_nsfw_learning_api.py` (nivel webapi): ambos endpoints
  rechazan NSFW, el endpoint de import rechaza un canal sin permiso de
  vista, `channel_id` manipulado se rechaza en el servidor.
- `tests/test_audit_learning_sources.py`: lógica del script contra una DB
  en memoria con un cliente de Discord mockeado — clasificación SAFE /
  NSFW_CURRENTLY / UNKNOWN, `--apply` solo toca lo clasificado
  NSFW_CURRENTLY, `UNKNOWN` nunca se toca.

Cubre los 15 escenarios listados en el pedido original: canal NSFW nuevo no
configurable, migración bloquea configuración vieja, no aparece en
selector, request manipulada rechazada, worker no procesa NSFW, SAFE pasa,
SAFE→NSFW deja de aprender, backfill excluye NSFW, reindexación excluye
NSFW, reinicio no reintroduce NSFW, corpus con trazabilidad se limpia,
corpus agregado se reconstruye solo con fuentes válidas, datos sin
trazabilidad se detectan y reportan, admin/owner/Premium no puede saltarse
la restricción (no existe ningún override en el diseño — el gate no lee
ningún flag de permisos), restauración desde datos antiguos no reintroduce
canales bloqueados (cubierto por el barrido de arranque).

## Fuera de alcance

- `spontaneous_channels` / `mention_channels`: gobiernan que el bot
  *hable*, no que *aprenda*. El pedido es específicamente sobre
  aprendizaje.
- Reconstruir "desde cuándo" un canal está en el allowlist más allá de lo
  que ya tiene `audit_log` (que solo cubre altas hechas desde el
  dashboard, no el seed de la migración). No existe timestamp confiable
  para esto y no se va a inventar uno.
- No se persiste ningún flag NSFW en la DB (ver "Principio de diseño").
