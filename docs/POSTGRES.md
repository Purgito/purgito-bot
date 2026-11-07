# PostgreSQL en Purgito

Purgito guarda todo en **una sola base PostgreSQL** (desde la migración del
2026-10-01; antes era SQLite en `data/bot.db`). Los datos de cada servidor de
Discord conviven en las mismas tablas y se separan por la columna `guild_id`
(43 de las 49 tablas la llevan; las otras 6 son globales por diseño:
`deleted_user_tombstones`, `gif_objects`, `lifecycle_state`,
`pending_message_deletions`, `revoked_sessions`, `shared_embeds`).
No hay una base por servidor.

Piezas del código:

| Archivo | Qué hace |
|---|---|
| `src/schema_pg.sql` | Esquema canónico, idempotente (`CREATE ... IF NOT EXISTS`). Se aplica en cada arranque. |
| `src/pgdb.py` | Capa async sobre `asyncpg`: pool, `execute/fetchone/fetchall`, traducción de `?` → `$n` y de `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`. |
| `src/db.py` | Todas las queries del bot. `async with _db_lock:` abre una transacción (ROLLBACK si la excepción sale del bloque). |
| `src/pgsync.py` | Conexión síncrona para los scripts de `scripts/`. |
| `scripts/migrate_sqlite_to_postgres.py` | Migrador SQLite → PostgreSQL con verificación. |

## Variables de entorno

Van en `.env` (secretos, gitignored; los nombres están en `.env.example`):

| Variable | Obligatoria | Qué es |
|---|---|---|
| `DATABASE_URL` | sí | `postgresql://usuario:clave@127.0.0.1:5432/purgito`. Sin ella el bot no arranca. |
| `TEST_DATABASE_URL` | solo para tests | Base **distinta** (`purgito_test`). Los tests la vacían: nunca apuntarla a producción. |
| `DB_POOL_MIN` / `DB_POOL_MAX` | no | Tamaño del pool (default 2 / 10). |
| `BACKUP_AGE_RECIPIENTS` | para backups a R2 | Clave(s) PÚBLICA(S) age (`age1...`) con las que `backup_db.sh` cifra. Sin ella, con R2 configurado, el backup falla (no sube nada en claro). Ver § Backups. |
| `R2_BACKUP_ACCESS_KEY_ID` / `R2_BACKUP_SECRET_ACCESS_KEY` | para backups a R2 | Token de R2 **solo** del bucket de backups (Object Read & Write, "Apply to specific buckets only"). Sin fallback al token de imágenes/GIFs. |
| `R2_BACKUP_PREFIX` | no (`gen2/`) | Generación de backups dentro del bucket. Solo `gen<N>/` con N >= 2; la raíz y `gen1/` (lo histórico) se rechazan. |
| `R2_MIN_AGE_DAYS` | no (6) | La poda de R2 no intenta borrar nada más joven (el Bucket Lock de `gen2/purgito-`). |
| `R2_KEEP_DAILY` / `R2_KEEP_WEEKLY` / `BACKUP_MAX_AGE_DAYS` | no (7 / 2 / 14) | Retención en R2: diarios, domingos y tope de edad. `KEEP_LAST` (2) es solo la del disco. |
| `BACKUP_ALERT_WEBHOOK` | no | Webhook de Discord que recibe un aviso si el backup o la exportación del registro fallan. |
| `DELETION_TOMBSTONE_RETENTION_DAYS` | no (`limits.env`, 15) | Cuánto dura una lápida (usuario o servidor). Debe ser ≥ la antigüedad máxima de un backup (14) + 1. |

## Observabilidad de la base

- `GET /health/ready` (loopback) hace un `SELECT 1` con timeout de 2 s, cacheado 5 s. Si falla emite `database.health_failed` y suma a `purgito_db_connection_errors_total`; 3 fallos en 5 min abren la alerta `database.connection_failed_repeated`.
- Un fallo en `init_db` al arrancar emite `database.connection_failed`.
- El heartbeat del bot (`data/service_state.json`) **no usa PostgreSQL**: con la base caída el bot sigue reportando que está vivo y `/health/ready` da 503.
- Diagnóstico por SSH: `python3 deploy/runbooks/purgito_runbooks.py diagnose_postgres` (`pg_isready`, conexiones vs `max_connections`, tamaño, transacción más vieja). Es solo lectura y no imprime credenciales.
- Los logs nunca van a esta base. Ver [OBSERVABILITY.md](OBSERVABILITY.md).

## Preparar una base nueva (servidor desde cero)

```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-client
sudo systemctl enable --now postgresql

sudo -u postgres psql <<'SQL'
CREATE ROLE purgito_app LOGIN PASSWORD 'cambia-esto';   -- sin superuser, sin CREATEDB
CREATE DATABASE purgito OWNER purgito_app;
CREATE DATABASE purgito_test OWNER purgito_app;          -- solo en desarrollo
CREATE DATABASE purgito_restorecheck OWNER purgito_app;  -- para deploy/restore_check.sh
SQL
```

Pon `DATABASE_URL` en el `.env` y arranca el bot: el esquema se crea solo. La
configuración por defecto de PostgreSQL (`shared_buffers` 128–256 MB,
`max_connections` 40) sobra para este tamaño; no la toques sin medir.

> **Memoria.** En una VM de 2 GB el OOM killer puede matar a PostgreSQL (pasó el
> 2026-10-01 al llenar `/tmp`, que es tmpfs, con copias de la SQLite). El
> servidor de producción tiene ahora 2 GB de swap (`/swapfile`, en `/etc/fstab`).
> Si montas otro servidor: `fallocate -l 2G /swapfile && chmod 600 /swapfile &&
> mkswap /swapfile && swapon /swapfile` y la línea de fstab. Vigila el disco
> (`df -h /`): con 8.6 GB, el swap y los dumps pesan (ver § "Capacidad" en DEPLOY.md).

## Migrar una SQLite existente

> **Se retira el 2026-10-15** junto con el rollback (ver § "Rollback temporal a
> SQLite") y con `scripts/migrate_sqlite_to_postgres.py`. La migración de
> producción terminó el 2026-10-01 y no se va a repetir.

```bash
sudo systemctl stop bot-purg                       # opcional: el snapshot es consistente aun con el bot corriendo
.venv/bin/python scripts/migrate_sqlite_to_postgres.py            # base destino vacía
.venv/bin/python scripts/migrate_sqlite_to_postgres.py --verify-only
.venv/bin/python scripts/migrate_sqlite_to_postgres.py --truncate --yes   # reintento sobre una base ya cargada
```

La SQLite se abre en solo lectura (nunca se modifica). El migrador copia con
`COPY` dentro de **una transacción**, reconstruye las secuencias y compara
contra un snapshot: filas por tabla y por `guild_id`, SHA-256 de cada tabla,
huérfanos lógicos y secuencias. Sale con código ≠ 0 ante cualquier diferencia.
Las tablas `tts_*` (feature eliminada) se omiten y quedan solo en la SQLite.

## Arrancar

```bash
sudo systemctl start bot-purg      # el unit depende de postgresql.service
journalctl -u bot-purg -f          # o tail -f data/bot.log
```

## Backups

`deploy/backup_db.sh` (cron **diario**, 03:17 UTC) hace `pg_dump -Fc`, lo verifica con
`pg_restore --list`, lo **cifra con [age](https://age-encryption.org)**, sube el cifrado
al bucket **privado** `R2_BACKUP_BUCKET` y poda. La retención está **separada**:

| Dónde | Qué se conserva | Variable |
|---|---|---|
| Disco | las **2** más recientes (el disco es chico) | `KEEP_LAST=2` |
| R2 | **7 diarios + 2 semanales** (el de cada uno de los 2 últimos domingos) | `R2_KEEP_DAILY=7`, `R2_KEEP_WEEKLY=2` |
| Tope de edad | ningún backup llega a **14 días** (promesa de `docs/PRIVACY.md`) | `BACKUP_MAX_AGE_DAYS=14` |

Los backups quedan en `~/purgito-bot-backups/` como `purgito-<fecha>.dump.age` (0600; la
carpeta, 0700). El dump en claro solo existe un instante en un temporal 0600 y se borra
siempre. R2 usa un **token propio** (`R2_BACKUP_ACCESS_KEY_ID` /
`R2_BACKUP_SECRET_ACCESS_KEY`) restringido en Cloudflare al bucket de backups: el token
de imágenes y GIFs (`R2_ACCESS_KEY_ID`) no puede leerlos ni borrarlos, y el de backups no
toca imágenes ni GIFs. Sin las dos variables propias, los backups a R2 fallan: no hay
fallback al otro token.

```
pg_dump -Fc → pg_restore --list (verifica) → age -r <pública> → .dump.age 0600
            → R2 privado (r2_backup.py upload: rechaza todo lo que no sea age)
            → prune-gfs en R2 (7 diarios + 2 domingos, < 14 días) y prune local (2)
            → si algo falla: aviso a BACKUP_ALERT_WEBHOOK (sin secretos)
```

- **Cuánto vive un backup:** como máximo 13 días y unas horas. `prune-gfs` se niega a
  podar si el backup más nuevo ya tiene 14 días o más (si los backups dejaron de salir,
  podar sería quedarse sin ninguno). El peor caso de pérdida al restaurar es un día.
- **Alertas:** `BACKUP_ALERT_WEBHOOK` (webhook de Discord) recibe un aviso si
  `backup_db.sh` termina con error. Contra el silencio (el cron no corrió), añade una
  comprobación de frescura: `r2_backup.py check --max-age-hours 36` sale con código 1 si
  el último backup de R2 es más viejo (por ejemplo en un cron aparte cada 6 h, o desde
  el monitor externo).

- **Sin `BACKUP_AGE_RECIPIENTS` y con bucket de R2, la corrida falla**: nunca se
  sube un dump en claro. Sin bucket, queda un `.dump` en claro solo local y el log
  lo avisa (`SIN CIFRAR`).
- **Custodia de la clave** (lo importante): el servidor solo conoce la clave
  PÚBLICA (`BACKUP_AGE_RECIPIENTS` en `.env`, `age1...`; varias separadas por
  espacio o coma). La clave PRIVADA (`AGE-SECRET-KEY-1...`) no debe vivir en el
  servidor: sin ella los backups no se pueden descifrar, y con ella en el mismo
  disco el cifrado no protege nada. Guárdala en un gestor de contraseñas y en una
  copia offline. `deploy/security_check.sh` falla mientras haya una en el servidor.
- Generar un par (en TU máquina, no en producción): `age-keygen -o purgito-recovery.txt`
  imprime la pública; pon esa en `BACKUP_AGE_RECIPIENTS`. Rotar = añadir la nueva
  pública, esperar a que todos los backups conservados (14 días) la incluyan, y quitarla.
  Nunca cambies `BACKUP_AGE_RECIPIENTS` antes de comprobar que la clave privada nueva
  descifra (ver § Probar la restauración en Windows).
- Los backups viejos en R2 y en disco no se descifran con una clave nueva: se
  descifran con la que tenían al hacerse.

En producción el cron es (`crontab -l`):
`17 3 * * * /home/purgito/purgito-bot/deploy/backup_db.sh >> ~/purgito-bot-backups/backup.log 2>&1`
(diario, 03:17 UTC). El script funciona con el entorno vacío de cron (lee
`DATABASE_URL`, `R2_BACKUP_BUCKET` y `BACKUP_AGE_RECIPIENTS` del `.env`). Revisa
`~/purgito-bot-backups/backup.log`: cada corrida deja una línea por etapa
(`BACKUP START`, `DUMP CREATED`, `DUMP VERIFIED`, `ENCRYPTED`, `UPLOADED`,
`R2 PRUNE`, `LOCAL PRUNE`, `BACKUP COMPLETE: OK backup -> ...`) o un `ERROR`. Cada
`PRUNE` dice cuántos backups encontró, cuáles conserva y cuáles borra.

```bash
bash deploy/backup_db.sh                          # a mano
.venv/bin/python scripts/r2_backup.py list        # ver los de R2
.venv/bin/python scripts/r2_backup.py prune-gfs         # dry-run de la retención de R2 (7 diarios + 2 domingos, < 14 días)
.venv/bin/python scripts/r2_backup.py check             # falla si el último backup tiene más de 26 h
.venv/bin/python scripts/r2_backup.py download latest --dest ~/restore
AGE_IDENTITY=~/clave-privada.txt bash deploy/restore_check.sh r2:latest   # baja de R2, descifra, restaura, verifica
```

Un backup que no se ha restaurado no cuenta: corre `restore_check.sh` de vez
en cuando (con la clave privada, que se trae temporalmente al sitio de la prueba).

### Probar el backup como lo corre cron

Cron arranca con el entorno casi vacío (`SHELL=/bin/sh`, `PATH=/usr/bin:/bin`).
Para reproducirlo sin esperar a las 3:17:

```bash
env -i HOME=$HOME USER=$USER LOGNAME=$USER SHELL=/bin/sh PATH=/usr/bin:/bin \
  /bin/sh -c "$HOME/purgito-bot/deploy/backup_db.sh >> $HOME/purgito-bot-backups/backup.log 2>&1"
tail -2 ~/purgito-bot-backups/backup.log   # OK backup -> ... cifrado con age ... subido a R2
```

**Estado de la generación 2 (claves age nuevas, prefijo `gen2/` del bucket `purgito-backups`):** se da por
operativa cuando (1) `backup.log` tiene un `BACKUP COMPLETE` con el cifrado nuevo,
(2) `r2_backup.py list` muestra el `.dump.age` en el bucket nuevo y (3) la prueba de
§ "Probar la restauración en Windows" pasó con la clave privada guardada fuera del servidor.

Verificado a mano, con el entorno de cron, el 2026-10-02: `pg_dump` y `age` se encuentran con ese PATH, el
backup queda `.dump.age` 0600, sin archivos en claro, el objeto aparece en R2 y la
prueba de restauración completa (bajar de R2 → descifrar → restaurar en una base
de descarte → comparar catálogo, secuencias, índices, funciones y conteos con
producción → reaplicar una lápida de prueba) pasó. `backup.log` lo crea la shell
del cron con la umask del usuario; no contiene secretos.

### Generaciones dentro de `purgito-backups` y retención en R2

Un solo bucket, dos generaciones separadas por prefijo:

| Generación | Dónde | Cifrado con | Estado |
|---|---|---|---|
| 1 (histórica) | raíz del bucket: `purgito-*.dump.age`, `luks-header-*`, `privacy-prefs.*` | clave age antigua (**perdida**) | no se lee ni se toca; caduca a los 14 días de su creación |
| 2 (vigente) | `gen2/purgito-*.dump.age` y `gen2/ledger/privacy-ledger-*.jsonl.age` | clave age nueva | la usan `backup_db.sh` y `export_ledger.sh` |

`R2_BACKUP_PREFIX` (default `gen2/`) solo acepta `gen<N>/` con N >= 2: la raíz y `gen1/`
nunca son un destino. Todo lo que hace `src/r2.py` con backups (subir, listar, bajar,
borrar) va **bajo ese prefijo**: la generación 1 ni aparece en los listados, así que ninguna
poda puede tocarla, y una key que intente salir del prefijo (`../`, absoluta, de otra
generación) se rechaza antes de llamar a R2. Es una barrera contra errores de código; frente
a un token robado, la protección son las reglas de Cloudflare de más abajo.
`r2_backup.py preflight` (solo lectura) lo comprueba contra el bucket real antes del primer
backup. Además, `deploy/age-revoked-recipients.txt` lista las claves públicas que nunca deben
usarse (la de la generación 1): `backup_db.sh`, el exportador del registro y `preflight` se
niegan a correr si `BACKUP_AGE_RECIPIENTS` contiene alguna.

La retención no depende de reglas del dashboard: `backup_db.sh` llama a
`r2_backup.py prune-gfs --apply` después de cada subida (7 diarios + 2 domingos, nada de 14
días o más; solo cuenta `purgito-*` de la generación vigente). Las reglas de Cloudflare son una
red de seguridad que **tiene que ser compatible** con esos plazos. El token de la app no puede
escribir reglas de *lifecycle* ni de *Bucket Lock* (`AccessDenied`): se ponen a mano en el
dashboard.

**Tokens (todos limitados por bucket; un token de R2 no se puede limitar a un prefijo):**

| Token | Permiso | Buckets | Dónde vive | Para qué |
|---|---|---|---|---|
| Imágenes y GIFs (`R2_ACCESS_KEY_ID`) | Object Read & Write | `purgito-images`, `purgito-gifs` | `.env` del bot | el bot; **no** ve `purgito-backups` |
| Backups (`R2_BACKUP_ACCESS_KEY_ID`) | Object Read & Write | solo `purgito-backups` | `/etc/purgito/backup.env` (root:root 0600), **no** en el `.env` del bot | subir y podar `gen2/` |
| Restauración (solo en tu PC) | **Object Read only** | solo `purgito-backups` | Proton Pass, tu PC | bajar dumps para probarlos; no puede escribir ni borrar |

**Reglas en el dashboard de `purgito-backups`** (la versión vigente y exacta, con segundos y salvedades, está en `docs/R2_REGLAS.md`) (todas por prefijo; ninguna regla sin prefijo,
porque un bloqueo de todo el bucket frenaría la poda de `gen2/`):

| Regla | Prefijo | Valor | Por qué |
|---|---|---|---|
| *Bucket Lock* (antiborrado) | `purgito-` | **14 días** | protege los `.dump.age` históricos de la raíz (los de `gen2/` empiezan por `gen2/`, no coinciden) |
| *Bucket Lock* | `luks-header` y `privacy-prefs` | **14 días** | igual, para el resto de la generación 1 |
| *Bucket Lock* | `gen2/purgito-` | **6 días** como máximo | protege los backups nuevos de un borrado masivo; los diarios se podan a los 7 días, un bloqueo mayor haría fallar la poda (HTTP 409 `ObjectLockedByBucketPolicy`) |

`prune-gfs` no propone borrar nada con menos de `R2_MIN_AGE_DAYS` (6) días: un backup manual el mismo día que el del timer deja dos del mismo día, y el más viejo se conserva unos días más en vez de provocar un 409 en cada pasada (`tests/test_retention_lock_compat.py` simula 400 días contra estas reglas).
| *Object lifecycle*: borrar | `gen2/purgito-` | **13 días** | tope de la política por si el script no corre. 13 y no 14: R2 borra «típicamente dentro de las 24 h» posteriores a la fecha de expiración (documentación de Cloudflare), así que el peor caso real es ~14 días. El Bucket Lock **prevalece** sobre el lifecycle (no se borra nada antes de los 6 días) |
| *Object lifecycle*: borrar | `gen2/ledger/` | **14 días** | idem (peor caso real ~15 días = la vida de una lápida). Expira **después** que los dumps (13 d): con el servidor apagado nunca queda un dump sin su registro |
| *Sin* lifecycle | `gen2/luks-header-`, `gen2/secretos-` | — | un lifecycle borraría también la única cabecera o paquete vigente; se podan a mano (o con una poda propia) conservando siempre el último |
| *Object lifecycle*: borrar (opcional) | `purgito-`, `luks-header`, `privacy-prefs` | 14 días | hace que la generación 1 caduque sola a los 14 días, como promete la política. Si prefieres decidir a mano, no la actives y bórralos tú antes de cumplir los 14 días (o cambia la política) |

Nada de bloqueos indefinidos ni de más de 14 días: incumplirían la política publicada. El
bloqueo no impide que el lifecycle borre el objeto cuando se cumple el plazo del bloqueo.

## Restaurar

```bash
sudo systemctl stop bot-purg
# 1. bajar y descifrar (la clave privada se trae temporalmente, desde fuera del servidor)
.venv/bin/python scripts/r2_backup.py download latest --dest ~/restore
age -d -i ~/clave-privada.txt -o ~/restore/restore.dump ~/restore/purgito-<fecha>.dump.age
# 2. restaurar
pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" ~/restore/restore.dump
# 3. REAPLICAR LOS BORRADOS posteriores al backup (obligatorio antes de arrancar), con
#    el registro de eliminaciones externo (ver más abajo). El registro en claro viaja por
#    la entrada estándar: no toca el disco del servidor.
.venv/bin/python scripts/reapply_deletions.py --ledger - < registro.jsonl     # dry-run
.venv/bin/python scripts/reapply_deletions.py --ledger - --apply < registro.jsonl
# 4. limpiar el dump descifrado y la clave, y arrancar
shred -u ~/restore/restore.dump ~/clave-privada.txt
sudo systemctl start bot-purg
```

El paso 3 existe por privacidad: un backup anterior a un la eliminación de datos (Centro de Privacidad) o a la
purga de un servidor aún tiene esos datos, y uno anterior a una exclusión no la tiene.

### Registro de eliminaciones (lápidas + copia externa)

- Cada la eliminación de datos (Centro de Privacidad) deja una lápida en `deleted_user_tombstones` y cada purga de
  servidor (`purge_guild_data`) una en `purged_guild_tombstones` (solo el id y dos fechas;
  sin contenido). Duran `DELETION_TOMBSTONE_RETENTION_DAYS`=**15** días: los 14 de
  antigüedad máxima de un backup + 1 de margen. Pasado ese plazo ya no existe ningún
  backup anterior al borrado, y conservar el id no tiene justificación; la purga
  diaria (`guild_cleanup_task`) las elimina.
- Si se pierde la base, se pierden también sus lápidas. Por eso `deploy/export_ledger.sh`
  (cron **cada hora**, no instalado por defecto) guarda en R2, cifrada con la clave age de
  los backups, una instantánea con **solo** las lápidas vigentes y las exclusiones activas
  (`gen2/ledger/privacy-ledger-<fecha>.jsonl.age`; ids y fechas, nunca contenido; además de lápidas y exclusiones lleva solicitudes abiertas, lápidas de mensajes y canales y el ancla del registro encadenado). Se
  conservan 15 días como máximo (siempre las 3 últimas), y 3 copias locales en
  `~/purgito-bot-backups/ledger/`. La pérdida máxima del registro es de una hora.
  Cron propuesto: `7 * * * * /home/purgito/purgito-bot/deploy/export_ledger.sh >> ~/purgito-bot-backups/ledger.log 2>&1`.
- `reapply_deletions.py --ledger` funde la instantánea con la base (conserva la
  expiración más lejana y **nunca quita una exclusión**), borra lo de cada usuario y
  servidor con lápida vigente (mismo SQL que `db.delete_user_data` y `purge_guild_data`),
  restaura las exclusiones y elimina las lápidas vencidas. No imprime ids.
  Descifrar la instantánea (`age -d -i <clave> ledger/<archivo>.jsonl.age`) se hace en el
  equipo del titular, con la clave privada.
- Son datos personales (ids de Discord): solo los ve quien tiene acceso a la base o a la
  clave age, caducan solos y no se exponen por ninguna API.
- Los backups de la generación anterior (clave perdida) y cualquier backup restaurado
  **nunca** se restauran sobre producción sin pasar por este paso; para inspeccionarlos,
  usa una base aislada.
- **Mensajes sueltos y canales.** Un mensaje borrado, editado o dentro de un borrado masivo, y un canal
  eliminado, dejan una lápida (solo ids y fechas, 15 días) **si estaban en el corpus**, y el registro externo
  las lleva (con un tope de 100 000; si se supera, el restore exige `--aceptar-truncado`). Límite que sigue
  abierto: un mensaje que ya no estaba en el corpus (recortado por tamaño) pero sí en un backup antiguo no
  tiene lápida. Detalle y demás límites en `docs/PRIVACY_CENTER.md`.
- **Guardián de arranque y registro fresco.** Tras restaurar, el bot no arranca (código 78) hasta que `reapply_deletions.py --apply` reconcilie con un registro de ≤ 2 h y posterior a la base; ver `docs/PRIVACY_CENTER.md` § Restauración segura.
- **Restaurar sin registro.** `reapply_deletions.py` exige `--ledger`: sin él termina con
  código 1 y sin tocar la base. Solo `--sin-registro` (explícito) permite correr con las
  lápidas del propio backup. Si la instantánea falta o es inválida también falla sin tocar
  la base.

### Plazos: 14 días para los dumps, 15 para el registro (excepción documentada)

| Qué | Dónde | Cuánto vive | Por qué |
|---|---|---|---|
| Dump de la base (`gen2/purgito-*.dump.age`, copias locales, copias de prueba en el PC) | R2, disco, equipo del titular | **menos de 14 días** | promesa de `docs/PRIVACY.md` |
| Lápida de usuario o de servidor (`deleted_user_tombstones`, `purged_guild_tombstones`) | base de datos | **15 días** | un dump creado justo antes del borrado vive hasta 14 días: la lápida tiene que durar más que él (+1 de margen) |
| Instantánea del registro (`gen2/ledger/privacy-ledger-*.jsonl.age`) | R2 y 3 copias locales | **15 días** como máximo (siempre quedan las 3 últimas) | contiene lápidas vigentes, que viven hasta 15 días |
| Exclusión del aprendizaje | base de datos y cada instantánea | mientras la persona la mantenga | es una preferencia, no un borrado |

La única excepción a "menos de 14 días" es el registro (15), y es deliberada: sin ella, un
backup de 13 días restaurado podría devolver datos borrados en los últimos 2 días. Está
publicada en la política de privacidad (§ lápidas y copia del registro).

**El registro se recupera sin la base y sin el servidor:** la instantánea está en R2, cifrada
con la clave age de los backups. Con la clave privada (en tu equipo) y sin tocar PostgreSQL:
`age -d -i <clave> -o registro.jsonl gen2/ledger/privacy-ledger-<fecha>.jsonl.age` y
`reapply_deletions.py --ledger - --apply < registro.jsonl` después de restaurar el dump.
Lo único de lo que depende es la clave age y R2 (si quieres una tercera vía independiente,
baja la última instantánea a tu PC junto con el dump de la prueba mensual). La pérdida
máxima es una hora de eliminaciones (cron horario de `export_ledger.sh`).

### Runner aislado de backups (el bot no puede leer sus credenciales)

El bot carga el `.env` entero en su entorno y su usuario (`purgito`) puede leerlo y modificar
los scripts del checkout. Por eso las credenciales de backups **no van al `.env`** y el backup
no corre como el bot:

| Pieza | Dónde | Propietario |
|---|---|---|
| Usuario del runner | `purgito_backup` (sin login ni home) | sistema |
| Código de backups | `/opt/purgito-backup/` (copia de lo commiteado, `git show HEAD:`) | root:root; el bot no puede modificarlo |
| Configuración y credenciales R2 | `/etc/purgito/backup.env` | root:root 0600; lo lee solo systemd (`EnvironmentFile=`) |
| Dumps | `/var/backups/purgito/` | `purgito_backup` 0700 |
| Acceso a PostgreSQL | rol `purgito_backup`, `pg_read_all_data`, socket local con `peer` | sin contraseña |
| Servicio | `purgito-backup.service` (sandbox) y `purgito-backup.timer` (no habilitado) | root |

El bot corre con `NoNewPrivileges=yes`, así que tampoco puede escalar con `sudo`.

```bash
sudo deploy/install_backup_runner.sh --recipient age1...           # dry-run
sudo deploy/install_backup_runner.sh --recipient age1... --apply   # instala (no toca bot, Studio ni cron)
sudo /opt/purgito-backup/deploy/set_backup_credentials.sh          # tú tecleas las 2 credenciales, sin eco
sudo /opt/purgito-backup/deploy/backup_task.sh preflight           # solo lectura
sudo /opt/purgito-backup/deploy/backup_task.sh access-check        # solo lectura (token de backups)
sudo systemctl start purgito-backup.service                        # UN backup (SKIP_PRUNE=1 en backup.env)
```

Otras piezas del runner (todas con el mismo usuario y sandbox; **ningún timer se habilita al instalar**):

| Unidad | Qué hace | Frecuencia |
|---|---|---|
| `purgito-backup.timer` → `.service` | dump cifrado a `gen2/` y poda | diario 03:17 UTC |
| `purgito-ledger.timer` → `.service` | exporta el registro de eliminaciones a `gen2/ledger/` y lo adelgaza (ver abajo) | cada 5 min |
| `purgito-backup-check.timer` → `.service` | falla (y `OnFailure` avisa a Purgito Monitor) si el último backup tiene más de 26 h o el último registro más de 1 h | cada 6 h (:40) |
| `purgito-vault-watch.timer` → `.service` | falla si `/srv/purgito` (la bóveda) no está montada; no depende de ningún fichero de la bóveda | 25 min tras arrancar y cada 10 min |

**Si la VM queda apagada (o la bóveda cerrada) varios días.** Nada del servidor corre: ni el backup, ni la
poda, ni la exportación del registro. Qué ocurre de verdad:
- *R2:* solo actúa el lifecycle de Cloudflare (independiente de la VM), **si está configurado** (verificación
  pendiente en el dashboard). Borra «típicamente dentro de las 24 h» de la expiración, no exactamente; el Bucket
  Lock tiene prioridad (nada antes de 6 días). Con las reglas recomendadas (dumps 13 d, registro 14 d) los
  dumps desaparecen antes que el registro. Sin esas reglas, **nada** borra en R2 hasta que el servicio vuelve.
- *Disco local:* las 2 últimas copias quedan donde están (el cifrado de la bóveda protege el contenido, no el
  plazo). Al reanudarse, la primera copia nueva elimina las locales de 13 días o más
  (`backup_db.sh`, `prune_local`); hasta entonces el plazo de 14 días se puede superar. Al reabrir la bóveda tras
  una parada: `sudo /opt/purgito-backup/deploy/backup_now.sh "tras apagado"` (las guardas lo omiten si ya hay una
  copia de menos de 12 h).
- *Restauración tras una parada larga:* `reapply_deletions.py` se niega si la base es más de 15 días anterior al
  registro; y si el registro ya expiró (>14–15 d) hay que restaurar con `--sin-registro` bajo decisión expresa.
- *Política de privacidad:* por eso promete el límite «mientras el servicio funcione con normalidad».

**Vigilancia sin fallos silenciosos.** Con la bóveda cerrada, `purgito-backup`, `purgito-ledger` y el bot se
*omiten* por `ConditionPathIsMountPoint` (no fallan, así que `OnFailure` no avisa) y los ficheros que usa el
aviso (`/etc/purgito/*.env`) tampoco están. Por eso `purgito-vault-watch` no usa nada de la bóveda: queda
`failed` y el agente externo de Purgito Monitor lo trata como cualquier unidad en fallo (hay que añadirla a su
configuración como `kind: systemd`). Un backup omitido se detecta además con `purgito-backup-check`
(26 h; un `Persistent=true` no recupera una ejecución omitida por una Condition). Para no duplicar el aviso de
disponibilidad, `purgito-vault-watch` empieza a comprobar 25 min después de arrancar.

**Copias manuales.** `purgito-backup.service` lleva `BACKUP_REQUIRE_GUARD=1` (`deploy/backup_guard.sh`):
un solo backup a la vez (`flock`), no empieza otro si hay una copia completa de hace menos de 12 h
(sale con 75, que el servicio acepta: no es un fallo) y cada corrida deja una línea `BACKUP ORIGEN`
(timer o manual, usuario, motivo). A mano: `sudo /opt/purgito-backup/deploy/backup_now.sh "motivo" [--forzar]`.
Cada copia que sube a R2 son ~62 MB que no se pueden borrar hasta pasados 6 días (Bucket Lock): para probar
scripts usa `deploy/backup_db_test.sh` y `deploy/backup_guard_test.sh`, que no tocan R2.

**Adelgazamiento del registro.** Cada instantánea de `gen2/ledger/` es el estado completo; para restaurar
basta la más reciente (`reapply_deletions.py --ledger` exige además que tenga menos de 2 h y no sea anterior a
la base). Se sigue subiendo una cada 5 min, pero `prune-ledger` conserva solo: las 3 últimas, todas las de
las últimas 6 h, una por hora hasta 48 h y una por día hasta el tope de 15 días (~130 objetos en vez de
~4 300). Cada pasada borra como máximo 300 (`--max-delete`).

El webhook de alertas se guarda sin eco: `sudo /opt/purgito-backup/deploy/set_backup_credentials.sh --webhook`.

Las credenciales de imágenes y GIFs sí van en el `.env` del bot: `deploy/set_media_credentials.sh`
(pide los dos valores sin eco) y después `r2_backup.py media-check` (solo lectura) y reiniciar `bot-purg`.

### Activación de la generación 2 (lista de comprobación)

1. Reglas de Bucket Lock y lifecycle en Cloudflare (tabla de arriba), **antes** del primer backup.
2. Tokens separados creados por el titular. Medios → `.env` del bot (`set_media_credentials.sh`);
   backups → `/etc/purgito/backup.env` (`set_backup_credentials.sh`). Comprobación: `media-check`
   (bot) y `backup_task.sh access-check` (runner): cada token ve solo lo suyo.
3. `backup_task.sh preflight` debe dar `PREFLIGHT: OK`.
4. Espacio: `backup_db.sh` se niega a empezar (y a cifrar) si tras el backup no quedan
   `MIN_FREE_MB` (400) libres; el dump usa `nice`. Un `pg_dump` interrumpido no deja nada
   a medias en PostgreSQL y el `trap` borra los temporales.
5. Primer backup manual (`systemctl start purgito-backup.service`), descarga desde R2 y
   restauración real en PostgreSQL 18 aislado (siguiente sección). Solo entonces se quita
   `SKIP_PRUNE=1` de `backup.env` y se habilita el timer (`systemctl enable --now purgito-backup.timer`).

### Probar la restauración en Windows (equipo del titular)

La clave privada nunca va al servidor, así que la prueba se hace en tu PC, con
PostgreSQL 18 en un contenedor desechable. Con PowerShell (Docker Desktop y `age` instalados):

```powershell
$k = "E:\purgito-age-prod-2026-11.txt"            # clave privada (USB con BitLocker)
$w = Join-Path $env:TEMP "purgito-restore"; New-Item -ItemType Directory $w | Out-Null
scp purgito@purgito-vm:purgito-bot-backups/purgito-FECHA.dump.age $w
age -d -i $k -o "$w\restore.dump" "$w\purgito-FECHA.dump.age"
docker run -d --name pg-prueba -e POSTGRES_PASSWORD=desechable -p 127.0.0.1:55432:5432 postgres:18
docker cp "$w\restore.dump" pg-prueba:/tmp/restore.dump
docker exec pg-prueba createdb -U postgres prueba
docker exec pg-prueba pg_restore -U postgres --no-owner --exit-on-error -d prueba /tmp/restore.dump
docker exec pg-prueba psql -U postgres -d prueba -Atc "select (select count(*) from corpus_messages), (select count(*) from user_corpus), (select count(*) from information_schema.tables where table_schema='public')"
docker rm -f pg-prueba
Remove-Item -Recurse -Force $w
```

Compara los tres números con producción (`psql`: mismas consultas; los de producción
serán mayores si hubo mensajes después del backup). Un dump descifrado es dato personal:
hazlo en un disco cifrado (BitLocker) y bórralo al terminar; no lo subas a ningún sitio.
La prueba se repite una vez al mes y siempre tras cambiar de clave age o de versión de
PostgreSQL. **El sistema de backups no cuenta como terminado hasta que esta prueba pasa.**

## Rollback temporal a SQLite

> **Retirada pendiente — 2026-10-15.** Ese día (y solo si no hizo falta volver
> atrás) se borra todo lo que existe únicamente para este procedimiento, y esta
> sección y la de arriba ("Migrar una SQLite existente") se eliminan:
> `data/bot.db`, `data/bot.db-shm`, `data/bot.db-wal`, los flags
> `data/.images_wiped_v2` y `data/.chat_channels_split_v1` (el código SQLite viejo
> los leería para no repetir migraciones; sin ellos podría rehacer un
> `DELETE FROM corpus_images`), y en `~/purgito-bot-backups/`:
> `bot-sqlite-pre-cutover-*.db`, su `.sha256`, `bot-pre-postgres-*.flags.tar.gz` y el
> directorio `pre-gifcleanup-20261002T164117Z/` (CSV con las filas de GIFs que se
> limpiaron el 2026-10-02, por si hacía falta revertir; borrarlo con `shred -u` cuando
> ya no haga falta). Total ≈ 384 MB. Después se puede quitar el aviso de `deploy/preflight_check.sh`
> sobre `data/bot.db` y `scripts/migrate_sqlite_to_postgres.py`.

Es temporal: se conservan `data/bot.db` y `~/purgito-bot-backups/bot-sqlite-pre-cutover-*.db`
(+ `.sha256`) **hasta el 2026-10-15**; pasada esa fecha se pueden borrar y este
procedimiento deja de existir. El código de la rama actual **solo** habla PostgreSQL; volver a SQLite significa
volver al código anterior y a un `bot.db` anterior:

1. `sudo systemctl stop bot-purg`
2. Guarda un dump de PostgreSQL por si hay que reintentar (`bash deploy/backup_db.sh`).
3. Vuelve al código previo a la migración (commit `c2d090b`, el último con
   SQLite; si los cambios de la migración aún no están commiteados,
   `git stash -u`) y `pip install -r requirements.txt`.
4. `data/bot.db` sigue intacto con los datos hasta el corte; copia respaldo:
   `~/purgito-bot-backups/bot-sqlite-pre-cutover-<fecha>.db` (+ `.sha256`).
5. `sudo systemctl start bot-purg`.

Ojo: todo lo que el bot aprendió/escribió **después** del corte vive solo en
PostgreSQL y no vuelve a la SQLite con este procedimiento.

## Desarrollo vs. producción

- Producción: `DATABASE_URL` → `purgito`. Desarrollo: crea tu propia base y
  `purgito_test` para los tests.
- Tests: `.venv/bin/python -m pytest tests -q`. CI corre la suite con Python 3.14 +
  PostgreSQL 18 (el stack de producción) y, como piso de compatibilidad, con 3.12 +
  PostgreSQL 16. (1 test se salta porque necesita
  Node.js, que no está instalado en el servidor, igual que los
  `landing/test_*.mjs`). Necesitan `TEST_DATABASE_URL` y el puerto de la web app
  libre (8 tests levantan la app real). Con el bot corriendo en la misma máquina,
  no lo pares: `WEB_PORT=18080 .venv/bin/python -m pytest tests -q`.
- la eliminación de datos (Centro de Privacidad), exclusiones y separación por servidor/usuario están
  cubiertos por `tests/test_delete_user_data.py`, `test_excluded_users.py` y
  `test_channel_scope_authorization.py`.

## Seguridad de PostgreSQL

Estado en producción (2026-10-02), reproducible con `deploy/harden_postgres.sh`:

- **Red:** `listen_addresses = localhost` (127.0.0.1 y ::1). El bot se conecta por
  TCP a 127.0.0.1:5432; el tráfico nunca sale de la máquina, así que no hay TLS que
  gestionar (PostgreSQL ofrece TLS con el certificado autofirmado de Ubuntu y asyncpg
  lo negocia, pero no se valida: no protege de nada que el loopback no proteja ya).
  Si algún día hay acceso remoto: TLS con certificado propio y `sslmode=verify-full`,
  y solo por Tailscale; nunca abrir 5432 al público.
- **`pg_hba.conf`:** `local` por peer (el superusuario entra por `sudo -u postgres`);
  por TCP solo el rol `purgito_app`, con `scram-sha-256`; sin líneas de replicación.
  `postgres` no puede entrar por TCP.
- **Roles:** solo `postgres` y `purgito_app` (sin superuser, CREATEDB, CREATEROLE,
  replicación ni BYPASSRLS). `purgito_app` es DUEÑO de su base y su esquema porque
  `init_db` aplica el esquema (`CREATE ... IF NOT EXISTS`) en cada arranque; separar
  dueño y rol de la app exigiría sacar el DDL del arranque, y no se hizo.
- **`idle_in_transaction_session_timeout = 5min`** (rol `purgito_app`): corta una
  transacción olvidada. No hay `statement_timeout` a nivel de rol: la app ya usa
  `command_timeout=60` y `pg_dump`/mantenimiento no deben morir por un tope genérico.
- **Log:** `log_min_duration_statement=500ms` con `log_parameter_max_length=0` (la
  query sí, los valores de los parámetros —mensajes de usuarios— nunca),
  `log_lock_waits=on`. El log (`/var/log/postgresql/`) lo lee solo root/adm:
  `sudo grep -E "ERROR|FATAL|duration" /var/log/postgresql/postgresql-18-main.log`.
- **Bases:** `purgito` (producción), `purgito_test` (tests, datos sintéticos) y
  `purgito_restorecheck` (descarte de `restore_check.sh`, vacía). Las copias de datos
  reales para pruebas (`purgito_migtest`) se borraron.

## Consultas a la base desde hilos

El pool de asyncpg está atado al loop del bot. Código síncrono que corre en
`asyncio.to_thread` (p. ej. `r2.upload_gif_bytes_sync`) **no** debe usar
`asyncio.run(db...)`: falla con `another operation is in progress`. Usa
`db.run_from_thread(db.funcion(...))`.

`run_from_thread` es solo para hilos de trabajo: llamada desde el hilo del loop
levanta `RuntimeError` (esperaría algo que solo ese hilo puede ejecutar), y si el
loop no responde en 60 s levanta `TimeoutError` y cancela la corrutina. Desde
código async usa `await`.

## Reglas de `async with db._db_lock`

El bloque abre UNA transacción en UNA conexión del pool (ver el docstring de
`src/pgdb.py`). Reglas:

- **Un statement que falla aborta toda la transacción** (en SQLite no): los
  siguientes dan `InFailedSQLTransactionError`. Si un subpaso puede fallar y el
  bloque debe seguir, envuélvelo en `async with db.savepoint():`. Un `except`
  que no relanza dentro de un lock sin savepoint lo detecta
  `tests/test_pgdb_transactions.py`.
- **`gather()` dentro del bloque no paraleliza**: los statements se turnan sobre
  la única conexión (antes fallaba con `another operation is in progress`).
- **Ninguna tarea creada dentro del bloque puede sobrevivirlo**: si usa la base
  después, `execute` levanta `RuntimeError` claro. Tampoco `gather`/`create_task`/
  `to_thread`/`sleep` dentro del bloque (el test estático lo prohíbe): retiene el
  lock global y una conexión.
- Sin red ni nada lento dentro del bloque.
- `acquire()` espera como máximo `pgdb.ACQUIRE_TIMEOUT` (30 s) por una conexión:
  un pool agotado falla con `TimeoutError` en el log en vez de congelar el bot.
