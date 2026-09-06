# Portabilidad — qué no sobrevive una migración de servidor sola

Auditoría de dónde el código o el proceso de deploy asumen que el bot vive
para siempre en la misma instancia. Motivada por la pérdida del droplet de
Oracle (Free Trial vencido, instancia reclamada sin aviso el 5 de septiembre
de 2026) — migrar de servidor no es un caso raro acá, es el modo de
operación esperado mientras el proyecto corra en free tiers.

No es una lista de bugs a arreglar ya: es un inventario de riesgo, con una
recomendación concreta por ítem. Los cambios de arquitectura grandes
(Postgres, containers, backups a otra región) se evalúan aparte si el riesgo
lo justifica.

## Resumen por severidad

| Severidad | Ítem |
|---|---|
| 🔴 Alta | `data/bot.db` no tiene backup fuera del disco de la instancia |
| 🔴 Alta | Los flags de migración de una sola vez viven en `data/` como archivos sueltos, fuera del `.backup` de sqlite — restaurar solo `bot.db` los pierde y puede re-disparar un `DELETE` |
| 🟡 Media | `SESSION_SECRET` sin copiar en la migración desloguea a todos los usuarios del dashboard (no es pérdida de datos, pero confunde si no se espera) |
| 🟢 Baja | `data/bot.log` se pierde en cada migración | ya aceptado, solo se documenta para confirmar que no esconde nada crítico |
| ✅ Sin riesgo encontrado | Rutas hardcodeadas fuera de `deploy/`, GIFs en disco local, certificados/claves atados a la IP vieja |

---

## 1. `data/bot.db` — la base SQLite

**Dónde vive:** `data/bot.db` (+ `data/bot.db-wal`, `data/bot.db-shm` mientras
el proceso corre en modo WAL), en el disco de la instancia. Es la única
copia — no hay réplica ni motor externo.

**Cómo se respalda hoy:** [`deploy/backup_db.sh`](../deploy/backup_db.sh)
corre por cron, usa `sqlite3 .backup` (seguro contra el modo WAL) y escribe
en `BACKUP_DIR` (default `/home/opc/purgito-bot-backups` — **mismo disco,
misma instancia**, solo fuera del árbol de git). Poda backups de más de 14
días. Según DEPLOY.md, a la fecha de esta auditoría **el cron todavía no
está instalado en el droplet real** — es un procedimiento documentado para
aplicar a mano, no algo que ya esté corriendo.

**El problema:** un backup en el mismo disco que el original protege contra
"until una migración corrompió la base" o "un `DELETE` corrió sin `WHERE`",
pero no contra lo que realmente pasó el 5 de septiembre: la instancia entera
desapareció. Si Oracle hubiera reclamado el droplet con el cron de
`backup_db.sh` ya instalado, los backups habrían desaparecido con la
instancia igual que `bot.db`. No hay ninguna copia hoy que sobreviva a
"se perdió el droplet completo": ni en R2, ni en otro storage, ni fuera del
proveedor.

**Recomendación concreta:**
- Subir el backup diario a R2 (ya está integrado y pagado — `src/r2.py` ya
  tiene cliente S3-compatible) bajo un prefijo separado del de GIFs, ej.
  `db-backups/bot-<fecha>.db`, con su propio ciclo de vida/retención
  (Object Lifecycle Rules de R2, o borrado manual del lado del bucket para
  no reescribir lógica de negocio en `src/`). Es el cambio de más impacto
  de todo este documento: convierte "hay que acordarse de scp-ear el
  archivo a mano antes de que el proveedor decida reclamar la instancia
  sin aviso" en "la migración empieza con `aws s3 cp` (o el CLI de R2)
  desde cualquier lado, sin depender de que la instancia vieja siga viva".
- Mientras eso no esté armado: agregar al checklist de "antes de destruir
  la instancia vieja" (ver más abajo) un `scp` explícito de
  `data/bot.db` + el directorio `data/` completo a una máquina que no sea
  la instancia, no solo confiar en el cron local.
- No se implementó en este pase — es justo el tipo de cambio que el pedido
  original pidió discutir antes (agregar credenciales/lifecycle a R2 desde
  un script de infra, no tocar `src/`), así que queda como recomendación,
  no como código.

## 2. Flags de migración de una sola vez, sueltos en `data/`

**Dónde viven:** `data/.images_wiped_v2` y `data/.chat_channels_split_v1`
(ver `src/db.py`, función `init_db()`, líneas ~869-894). Son archivos
sueltos con el texto `"done"`, sidecars de `bot.db` en el mismo directorio
pero **fuera del archivo sqlite**.

**Por qué importa:** `sqlite3 .backup` (lo que usa `backup_db.sh`) solo
copia `bot.db`. Restaurar ese backup en un servidor nuevo — o simplemente
clonar el repo y copiar `bot.db` a mano sin copiar el resto de `data/` —
deja la base con las tablas migradas pero **sin los archivos de flag**. En
el próximo arranque, `init_db()` no los encuentra y vuelve a correr esa
rama:

- `.chat_channels_split_v1` ausente → repite el `INSERT OR IGNORE` de
  `chat_channels` hacia `spontaneous_channels`/`mention_channels`. Es
  idempotente por el `OR IGNORE` — no duplica filas ni pisa lo que un admin
  ya cambió a mano. Riesgo real: bajo.
- `.images_wiped_v2` ausente → corre `DELETE FROM corpus_images` **de
  nuevo**, sin condición. Esto sí es destructivo: si la tabla ya tiene
  contenido nuevo (imágenes de memes subidas después de la primera vez que
  corrió esta migración), un servidor nuevo que restaure `bot.db` sin el
  flag las borra todas en el primer arranque, en silencio, sin pedir
  confirmación. Riesgo real: alto, y exactamente el tipo de cosa que nadie
  nota hasta que un usuario pregunta por qué el corpus de imágenes está
  vacío después de una migración.

**Por qué el diseño actual es frágil en general (más allá de estos dos
flags puntuales):** el criterio de "¿ya corrí esto?" vive en el filesystem,
separado del dato que la migración toca, que vive en sqlite. Son dos
sistemas de respaldo distintos (uno no tiene respaldo en absoluto) para un
estado que debería ser uno solo.

**Recomendación concreta:**
- Corto plazo, sin tocar código: el checklist de migración (`DEPLOY.md` y
  `MIGRATION.md`) tiene que decir explícitamente "copiar el directorio
  `data/` completo, no solo `bot.db`" — ítem ya incluido en ambos
  documentos de este mismo cambio.
- Mejor arreglo, para discutir aparte (no se implementa en este pase por
  pedido explícito de no tocar `src/db.py` sin confirmar antes): migrar
  estos dos flags a la tabla `applied_migrations` que **ya existe** en
  `db.py` y que ya se usa para el mismo propósito a nivel de guild
  (`corpus_allowlist_v1`, ver DEPLOY.md § "Migraciones de datos por
  servidor"). Sacaría el estado del filesystem por completo — quedaría
  todo dentro del mismo `bot.db` que ya se respalda, sin que un backup
  parcial pueda dejarlo en un estado inconsistente. Es un cambio de una
  fila de SQL y dos `if` en `init_db()`, pero toca `src/db.py`, así que
  queda pendiente de confirmación antes de tocarlo.

## 3. `SESSION_SECRET` no copiado en la migración

**Dónde vive:** `.env`, variable `SESSION_SECRET` (ver `src/config.py` y
`src/webapi.py:5558-5559` — deriva una clave Fernet de 32 bytes vía
`sha256(SESSION_SECRET)` para cifrar la cookie de sesión del dashboard).

**Por qué importa:** no es pérdida de datos — es una fuente de confusión
predecible. Si el `.env` del servidor nuevo se arma copiando valores a mano
en vez de copiar el archivo completo, es fácil regenerar `SESSION_SECRET`
"por las dudas" en vez de reusar el viejo. Todas las cookies de sesión
activas dejan de descifrar (clave distinta) y cada usuario logueado en el
dashboard aparece deslogueado al primer request después del switch — no es
un bug, pero sin este documento parece uno.

**Recomendación concreta:** el checklist de migración dice explícitamente
"copiar `.env` completo del servidor viejo, no reconstruirlo variable por
variable" como método preferido; si hay que reconstruirlo a mano (servidor
viejo ya no accesible), documentar que perder `SESSION_SECRET` es
aceptable y esperable (todos vuelven a loguearse), no un error a
investigar.

`DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET` no tienen este problema: están
atados a la Application de Discord, no a la instancia — el mismo valor
sirve en cualquier servidor mientras el redirect URI (`{DASHBOARD_BASE_URL}
/auth/callback`, configurado en el Developer Portal) siga apuntando al
dominio correcto, que no cambia en una migración de servidor (solo la IP
detrás del dominio cambia, vía Cloudflare).

## 4. GIFs — confirmado: no hay estado local que sobreviva ni que migrar

Se auditó específicamente si el flujo es "se guarda en disco local primero,
se sube a R2 después" (lo que dejaría un servidor nuevo sin GIFs hasta
recachear). **No es así:** `r2.upload_gif_sync()` (`src/r2.py`) descarga el
GIF de la URL de origen a memoria (`io.BytesIO`), lo optimiza con
`gifsicle` por stdin/stdout (sin archivos temporales) y sube el resultado
directo a R2 — nunca toca el disco de la instancia. No existe un directorio
`gifs/` local; no hay que buscarlo porque no está.

El "barrido de huérfanos" que aparece en los logs (`run_gif_orphan_sweep()`,
`src/cogs/gifs.py`) opera exclusivamente sobre **keys de R2** vs.
referencias en `gif_objects` (la tabla de sqlite) — es limpieza del bucket,
no del disco local. Confirma que R2 + `bot.db` son las dos únicas fuentes
de verdad; ninguna vive solo en el disco de la instancia aparte de la DB ya
cubierta en el punto 1.

**Consecuencia real de una migración:** un servidor nuevo sirve la galería
y el dashboard con normalidad desde el primer arranque, siempre que
`bot.db` (con las URLs/hashes en `gif_objects`) y las credenciales `R2_*`
en `.env` estén presentes. No hace falta re-cachear nada porque nunca hubo
caché local que perder.

## 5. Rutas hardcodeadas — confirmado: ninguna fuera de `deploy/`

Se buscó en `src/` y `scripts/` cualquier path absoluto tipo `/home/opc/` o
`/opt/bot-discord-purg/` escrito directo en código Python. No apareció
ninguno — `src/db.py`, `src/bot.py` y `src/meme_generator.py` calculan sus
rutas (`DATA_DIR`, `_LOG_PATH`, `_FONT_PATH`) relativas a
`os.path.dirname(os.path.abspath(__file__))`, así que siguen al checkout
sin importar dónde viva. Los únicos lugares con la ruta vieja hardcodeada
son exactamente los ya identificados en la migración Oracle→AWS:
`deploy/bot-purg.service` y `deploy/backup_db.sh` (sus defaults
`DB_SRC`/`BACKUP_DIR`) — ambos se generalizan en este mismo cambio (ver
`deploy/bot-purg.service.template` y `deploy/render_service.sh`).

## 6. Certificados, claves, config atada a la IP vieja

El bot no genera ni guarda ninguna clave SSH ni certificado propio. TLS lo
termina Cloudflare, no nginx (el origin habla HTTP plano con Cloudflare —
ver DEPLOY.md § Cloudflare); no hay `ssl_certificate` en el origin que
migrar o revocar. No se encontró configuración de Cloudflare (reglas de
página, WAF, Workers) que dependa de la IP vieja más allá de los A records
obvios, que ya están en el checklist de DNS de `MIGRATION.md`. Ítem sin
riesgo encontrado, se deja documentado para que la próxima auditoría no
tenga que repetir la búsqueda desde cero.

## 7. `bot.log`

Vive en `data/bot.log` (+ rotados `bot.log.1`, `.2`, `.3` —
`RotatingFileHandler(maxBytes=5_000_000, backupCount=3)`, ver `src/bot.py`).
Se pierde en cada migración si no se copia a mano — **a propósito, esto está
bien**: es el único ítem de esta lista donde la recomendación es "no hacer
nada". Se confirma acá que ningún dato necesario para debugging vive
*solo* en este log — todo lo que importa para operar el bot (config,
estado de guilds, migraciones aplicadas) está en `bot.db`, y todo lo que
importa para depurar un incidente puntual se pierde igual en cualquier
`journalctl` si no se exportó antes, sea o no la primera migración.

---

## Checklist — antes de destruir la instancia vieja

Pensado para correr en 5 minutos cuando un proveedor decide reclamar el
servidor sin aviso (o antes de un apagado planeado). En orden:

1. [ ] `scp` (o `rsync`) el directorio `data/` **completo** — no solo
       `bot.db` — a una máquina que no sea esta instancia (tu laptop, otro
       servidor, un bucket). Incluye los flags de migración
       (`.images_wiped_v2`, `.chat_channels_split_v1`) y `bot.db-wal`/
       `-shm` si el bot sigue corriendo (o pará el bot primero y copiá solo
       `bot.db` ya consolidado).
2. [ ] `scp` el `.env` completo (no reconstruirlo de memoria en el servidor
       nuevo — ver punto 3 arriba sobre `SESSION_SECRET`).
3. [ ] Confirmar que las credenciales `R2_*` en ese `.env` siguen siendo
       válidas (R2 no depende de esta instancia, pero confirmá que el
       token no tiene expiración próxima).
4. [ ] Anotar la IP del droplet viejo únicamente para poder compararla
       después con la nueva en los A records de Cloudflare — no hace falta
       nada más de la IP en sí.
5. [ ] Si hay un backup de `bot.db` corriendo por cron (`backup_db.sh`),
       bajate también el más reciente de `BACKUP_DIR` — es una copia
       adicional en caso de que el `scp` del paso 1 falle a mitad.
6. [ ] Solo después de 1-5: destruir/dejar expirar la instancia vieja.

Ver [`MIGRATION.md`](../MIGRATION.md) para el flujo completo de levantar en
el servidor nuevo a partir de estos archivos.
