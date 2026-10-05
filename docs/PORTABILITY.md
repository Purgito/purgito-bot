# Portabilidad — qué hay que llevarse al cambiar de servidor

Inventario de dónde el código o el proceso de deploy dependen de que el bot
viva en la misma máquina. Migrar de servidor no es un caso raro acá: ya pasó
con Oracle (Free Trial reclamado sin aviso el 2026-09-05) y es esperable que
vuelva a pasar. El flujo corto está en [`MIGRATION.md`](../MIGRATION.md); la
referencia larga, en [`DEPLOY.md`](../DEPLOY.md).

Estado a 2026-10-02: la base es PostgreSQL y los backups van cifrados con age a
un bucket privado de R2. Esto reemplaza al análisis de la época SQLite, donde el
único dato crítico era un archivo `data/bot.db` sin copia fuera del disco.

## Resumen por severidad

| Severidad | Ítem | Estado |
|---|---|---|
| 🔴 Alta | Perder la clave privada de age: sin ella ningún backup se puede abrir | Una sola clave, guardada fuera del servidor. Un segundo destinatario no está configurado |
| 🔴 Alta | Restaurar un backup sin reaplicar los borrados posteriores (`/borrar_mis_datos`) resucita datos de usuarios | Cubierto: `scripts/reapply_deletions.py --apply` es un paso obligatorio |
| 🟡 Media | El túnel de `cloudflared` y el nodo de Tailscale están atados a la máquina | Hay que moverlos o recrearlos en el servidor nuevo |
| 🟡 Media | `SESSION_SECRET` sin copiar desloguea a todos los usuarios del dashboard | Esperable, no es pérdida de datos |
| 🟢 Baja | `data/bot.log` se pierde en cada migración | Aceptado |
| ✅ Sin riesgo | GIFs e imágenes (viven en R2), rutas hardcodeadas, certificados | Verificado |

---

## 1. La base de datos y sus backups

**Dónde vive:** PostgreSQL local (`DATABASE_URL`), solo accesible desde la propia
máquina. No hay réplica: la única copia viva es la del servidor.

**Cómo se respalda:** [`deploy/backup_db.sh`](../deploy/backup_db.sh) corre por cron
(domingos 03:17 UTC), hace `pg_dump -Fc`, lo verifica con `pg_restore --list`, lo
cifra con age (solo la clave **pública** está en el servidor) y lo sube al bucket
privado `R2_BACKUP_BUCKET`. Se conservan los 2 más recientes, en el disco y en R2.
La copia local está en el mismo disco que la base: lo que sobrevive a perder el
servidor es la copia de R2.

**Qué llevarse al migrar:**

1. Un backup reciente (si la instancia vieja sigue viva, lanza
   `deploy/backup_db.sh` a mano antes de apagarla; si no, el último de R2:
   `python scripts/r2_backup.py download latest --dest <carpeta>`).
2. La **clave privada de age**, que no está en el servidor: sin ella el backup es
   ilegible.
3. El `.env` completo (ver § 3). `urls.env` y `limits.env` ya vienen con el
   `git clone`.

Procedimiento paso a paso: [`POSTGRES.md`](POSTGRES.md) § Restaurar. Siempre termina
con `scripts/reapply_deletions.py --apply` antes de arrancar el bot.

## 2. Flags sueltos de `data/` (solo hasta 2026-10-15)

`data/.images_wiped_v2` y `data/.chat_channels_split_v1` eran flags de migración
de la época SQLite. El código actual ya no los lee. Existen solo mientras dura el
rollback a SQLite (ver [`POSTGRES.md`](POSTGRES.md) § Rollback temporal), porque el
código viejo los usaba para no repetir un `DELETE FROM corpus_images`. No hacen falta
en una migración a un servidor nuevo, y se borran el 2026-10-15 junto con
`data/bot.db`.

## 3. `SESSION_SECRET` no copiado

**Dónde vive:** `.env`, variable `SESSION_SECRET` (se deriva una clave Fernet con
`sha256` para cifrar la cookie de sesión del dashboard).

No es pérdida de datos: si el `.env` del servidor nuevo se arma a mano y se
regenera `SESSION_SECRET`, todas las cookies activas dejan de descifrar y cada
usuario vuelve a iniciar sesión. Lo preferido es copiar el `.env` completo; si el
servidor viejo ya no existe, regenerarlo es aceptable y esperable.

`DISCORD_CLIENT_ID` y `DISCORD_CLIENT_SECRET` no tienen este problema: están atados
a la aplicación de Discord, no a la instancia, mientras el redirect URI
(`{DASHBOARD_BASE_URL}/auth/callback`) siga apuntando al dominio, que no cambia.

## 4. GIFs e imágenes: no hay estado local

`r2.upload_gif_sync()` descarga el GIF a memoria, lo optimiza con `gifsicle` por
stdin/stdout y lo sube directo a R2: nunca toca el disco de la instancia. No existe
un directorio `gifs/` local. El barrido de huérfanos (`run_gif_orphan_sweep()`)
compara keys de R2 contra la tabla `gif_objects`, es decir R2 + PostgreSQL son las
únicas fuentes de verdad.

Consecuencia: un servidor nuevo sirve la galería con normalidad desde el primer
arranque, siempre que la base restaurada y las credenciales `R2_*` estén presentes.

## 5. Rutas hardcodeadas: ninguna fuera de `deploy/`

`src/` y `scripts/` calculan sus rutas relativas al checkout. Usuario y ruta se
fijan solo al generar el unit de systemd con `deploy/render_service.sh <usuario>
<ruta>`.

## 6. Red, certificados y accesos atados a la máquina

- **TLS:** lo termina Cloudflare, que llega al origen por un túnel saliente de
  `cloudflared` hacia nginx por loopback. No hay certificado propio que migrar,
  pero el **túnel hay que moverlo o recrearlo** en el servidor nuevo y apuntar el
  DNS (ver `DEPLOY.md` § Cloudflare).
- **Acceso de administración:** SSH solo por clave y a través de Tailscale. El nodo
  de Tailscale es de la máquina vieja; en el servidor nuevo hay que unirlo de nuevo
  y repetir `deploy/harden_firewall.sh` (tiene auto-reversión a los 15 minutos).
- La config de nginx vive fuera del repo (`/etc/nginx/conf.d/purgito.conf`); se
  reconstruye desde `DEPLOY.md` § Configurar nginx.

## 7. `bot.log`

Vive en `data/bot.log` (+ rotados, `RotatingFileHandler` de 5 MB × 3, ver
`src/bot.py`). Se pierde al migrar y **está bien**: nada necesario para operar el
bot vive solo ahí (la configuración y el estado están en PostgreSQL).

---

## Checklist — antes de destruir la instancia vieja

Pensado para correr en pocos minutos cuando un proveedor reclama el servidor sin
aviso o antes de un apagado planeado. En orden:

1. [ ] Lanza `deploy/backup_db.sh` a mano (si la base todavía responde) y confirma
       en `~/purgito-bot-backups/backup.log` la línea `BACKUP COMPLETE`, o baja el
       último de R2 con `scripts/r2_backup.py`.
2. [ ] Copia el `.env` completo fuera de la instancia (no reconstruirlo de memoria;
       ver § 3).
3. [ ] Confirma que tienes la **clave privada de age** (no está en el servidor).
4. [ ] Confirma que las credenciales `R2_*` del `.env` siguen vigentes.
5. [ ] Anota la IP vieja solo para compararla con la nueva al mover el túnel y el
       DNS en Cloudflare.
6. [ ] Solo después de 1-5: destruir o dejar expirar la instancia vieja.

Ver [`MIGRATION.md`](../MIGRATION.md) para levantar el servidor nuevo a partir de
estos elementos.
