# PostgreSQL en Purgito

Purgito guarda todo en **una sola base PostgreSQL** (desde la migración del
2026-10-01; antes era SQLite en `data/bot.db`). Los datos de cada servidor de
Discord conviven en las mismas tablas y se separan por la columna `guild_id`
(43 de las 48 tablas la llevan; las otras 5 son globales por diseño:
`gif_objects`, `lifecycle_state`, `pending_message_deletions`,
`revoked_sessions`, `shared_embeds`).
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
| `DELETION_TOMBSTONE_RETENTION_DAYS` | no (`limits.env`, 15) | Cuánto dura la lápida de un `/borrar_mis_datos`. Debe ser ≥ la retención de backups + 1. |

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
> (`df -h /`): con 8.6 GB, el swap, los dumps y la SQLite de rollback pesan.

## Migrar una SQLite existente

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

`deploy/backup_db.sh` (cron **semanal**, domingo 03:17 UTC) hace `pg_dump -Fc`, lo
verifica con `pg_restore --list`, lo **cifra con [age](https://age-encryption.org)**,
sube el cifrado al bucket **privado** `R2_BACKUP_BUCKET` y poda: **se conservan como
máximo 2 backups, el más reciente y el anterior** (`KEEP_LAST=2`), tanto en el disco
como en R2. Al aparecer un tercero se borra el más antiguo; con 1 o 2 no se borra
nada. La retención es por cantidad, no por edad. Los backups quedan en
`~/purgito-bot-backups/` como `purgito-<fecha>.dump.age` (0600; la carpeta, 0700). El
dump en claro solo existe un instante en un temporal 0600 y se borra siempre.

```
pg_dump -Fc → pg_restore --list (verifica) → age -r <pública> → .dump.age 0600
            → R2 privado (r2_backup.py upload: rechaza todo lo que no sea age)
            → prune R2 y disco: solo los 2 más recientes (KEEP_LAST=2)
```

- **Cuánto vive un backup:** con corridas semanales, el más reciente tiene entre 0 y
  7 días y el anterior entre 7 y 14. Si una corrida falla (subida a R2 caída, etc.)
  no se poda nada: los dos backups previos se quedan hasta la siguiente corrida que
  salga bien. El peor caso de pérdida al restaurar es una semana de datos.

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
  pública, esperar 2 corridas semanales (así los 2 backups conservados ya la incluyen
  y ninguno depende solo de la vieja) y quitarla.
- Los backups viejos en R2 y en disco no se descifran con una clave nueva: se
  descifran con la que tenían al hacerse.

En producción el cron ya está instalado (`crontab -l`):
`17 3 * * 0 /home/purgito/purgito-bot/deploy/backup_db.sh >> ~/purgito-bot-backups/backup.log 2>&1`
(domingo 03:17 UTC). El script funciona con el entorno vacío de cron (lee
`DATABASE_URL`, `R2_BACKUP_BUCKET` y `BACKUP_AGE_RECIPIENTS` del `.env`). Revisa
`~/purgito-bot-backups/backup.log`: cada corrida deja una línea por etapa
(`BACKUP START`, `DUMP CREATED`, `DUMP VERIFIED`, `ENCRYPTED`, `UPLOADED`,
`R2 PRUNE`, `LOCAL PRUNE`, `BACKUP COMPLETE: OK backup -> ...`) o un `ERROR`. Cada
`PRUNE` dice cuántos backups encontró, cuáles conserva y cuáles borra.

```bash
bash deploy/backup_db.sh                          # a mano
.venv/bin/python scripts/r2_backup.py list        # ver los de R2
.venv/bin/python scripts/r2_backup.py prune             # dry-run de la retención de R2 (conserva los 2 más recientes)
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

Verificado así el 2026-10-02: `pg_dump` y `age` se encuentran con ese PATH, el
backup queda `.dump.age` 0600, sin archivos en claro, el objeto aparece en R2 y la
prueba de restauración completa (bajar de R2 → descifrar → restaurar en una base
de descarte → comparar catálogo, secuencias, índices, funciones y conteos con
producción → reaplicar una lápida de prueba) pasó. `backup.log` lo crea la shell
del cron con la umask del usuario; no contiene secretos.

### Retención en R2

El token de la app (Object Read & Write sobre los 3 buckets) **no** puede leer ni
escribir reglas de *lifecycle* ni CORS (`AccessDenied`), así que la retención no
depende del dashboard: `backup_db.sh` llama a `r2_backup.py prune --keep 2 --apply`
después de cada subida. La regla es por cantidad: los 2 `purgito-*.dump[.age]` más
recientes (por nombre, que lleva la fecha) y nada más; con 1 o 2 no borra nada. Solo
cuenta objetos `purgito-*` con contenido: no toca otras keys del bucket.

Si además quieres una red de seguridad en Cloudflare, que no choque con esa regla:
una *lifecycle rule* de *Delete objects* tras **35 días o más** (con corridas
semanales nunca debería actuar; una de 14 días podría vaciar el bucket si fallan dos
corridas seguidas) y, si usas *Bucket Lock*, con retención de **7 días como máximo**
(una mayor haría fallar el borrado del backup anterior).

## Restaurar

```bash
sudo systemctl stop bot-purg
# 1. bajar y descifrar (la clave privada se trae temporalmente, desde fuera del servidor)
.venv/bin/python scripts/r2_backup.py download latest --dest ~/restore
age -d -i ~/clave-privada.txt -o ~/restore/restore.dump ~/restore/purgito-<fecha>.dump.age
# 2. restaurar
pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" ~/restore/restore.dump
# 3. REAPLICAR LOS BORRADOS posteriores al backup (obligatorio antes de arrancar)
.venv/bin/python scripts/reapply_deletions.py            # dry-run: cuántas filas
.venv/bin/python scripts/reapply_deletions.py --apply
# 4. limpiar el dump descifrado y la clave, y arrancar
shred -u ~/restore/restore.dump ~/clave-privada.txt
sudo systemctl start bot-purg
```

El paso 3 existe por privacidad: un backup anterior a un `/borrar_mis_datos` aún
tiene los datos del usuario. Cada borrado deja una lápida en
`deleted_user_tombstones` (solo `user_id`, `deleted_at`, `expires_at`; sin
contenido ni servidores; caduca a los `DELETION_TOMBSTONE_RETENTION_DAYS`=15 días
= 14 días de backups (dos semanales) + 1 de margen; la purga `guild_cleanup_task`). El script vuelve a
borrar a esos usuarios con el mismo SQL que `db.delete_user_data`, elimina las
lápidas vencidas y no imprime ids. Límite conocido: el borrado de un *servidor*
(tras los 30 días de gracia) no deja lápida; restaurar un backup anterior puede
resucitar los datos de un servidor ya purgado hasta que el backup caduque.

Las lápidas son datos personales (un id de usuario): solo las ve quien tiene acceso
a la base, caducan solas y no se exponen por ninguna API.

## Rollback temporal a SQLite

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
- Tests: `.venv/bin/python -m pytest tests -q` (1 se salta porque necesita
  Node.js, que no está instalado en el servidor, igual que los
  `landing/test_*.mjs`). Necesitan `TEST_DATABASE_URL` y el puerto de la web app
  libre (8 tests levantan la app real). Con el bot corriendo en la misma máquina,
  no lo pares: `WEB_PORT=18080 .venv/bin/python -m pytest tests -q`.
- `/borrar_mis_datos`, exclusiones y separación por servidor/usuario están
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
