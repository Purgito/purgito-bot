# Migración a un servidor nuevo — flujo rápido

"Me quedé sin servidor, necesito levantar en otro proveedor ya." Este
documento es el camino corto, en orden, sin la explicación completa de cada
paso. Para eso está [`DEPLOY.md`](DEPLOY.md) (sección 0 tiene el mismo
checklist con más detalle y los problemas ya tropezados),
[`docs/POSTGRES.md`](docs/POSTGRES.md) (base de datos, backups y restauración) y
[`docs/PORTABILITY.md`](docs/PORTABILITY.md) (qué hay que llevarse y por qué).

Motivo por el que existe: la migración de Oracle a un servidor nuevo del
2026-09-05 tomó varias horas porque varios pasos no estaban documentados. La
idea es que la próxima tome minutos.

## 0. Si la instancia vieja todavía está viva

Antes de tocar nada del servidor nuevo, en la instancia vieja:

```bash
# Backup fresco, cifrado y subido a R2 (verifica la línea BACKUP COMPLETE)
deploy/backup_db.sh
tail -3 ~/purgito-bot-backups/backup.log

# .env completo -- no lo reconstruyas variable por variable en el servidor
# nuevo, cópialo tal cual (evita perder SESSION_SECRET y desloguear a todo
# el mundo sin necesidad)
scp <usuario>@<viejo>:<ruta>/.env ./migracion-backup/
```

Necesitas además la **clave privada de age**, que no está en el servidor (sin
ella el backup no se puede abrir). R2 (imágenes, GIFs y backups) no necesita
nada de esto: vive fuera de la instancia y las credenciales viajan con el
`.env`. Si la instancia vieja ya no existe, el último backup se baja con
`python scripts/r2_backup.py download latest --dest <carpeta>`.

## 1. Crear la instancia nueva

Cualquier VM Linux moderna con salida a internet y un usuario con `sudo`
sirve. Anota **usuario** y **ruta de checkout**: se necesitan exactos más
abajo para generar el unit de systemd. Identifica la distro
(`cat /etc/os-release`): Oracle Linux (`dnf`, SELinux) y Ubuntu/Debian
(`apt`, sin SELinux) difieren en varios comandos, y DEPLOY.md los marca por
separado.

## 2. Clonar e instalar

```bash
git clone https://github.com/Purgito/purgito-bot.git <ruta>
cd <ruta>

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# gifsicle -- ver DEPLOY.md § Paquetes del sistema por distro
which gifsicle || echo "falta instalar gifsicle"
# age -- para descifrar el backup y para los backups futuros
which age || echo "falta instalar age"
```

## 3. PostgreSQL, datos y config

```bash
cp /ruta/a/migracion-backup/.env .env
test -f .env && echo "OK: .env es un archivo" || echo "MAL -- revisar"
```

Instala PostgreSQL 18, crea el rol y la base, restaura el último backup y
**reaplica los borrados** siguiendo [`docs/POSTGRES.md`](docs/POSTGRES.md)
(§ Preparar una base nueva y § Restaurar). El paso de
`scripts/reapply_deletions.py --apply` es obligatorio antes de arrancar el
bot: sin él, un backup anterior a un `/borrar_mis_datos` resucita los datos de
ese usuario.

Si no hay `.env` de la instancia vieja (se perdió sin aviso) y hay que
reconstruirlo desde cero, **lista mínima de variables obligatorias**:

| Variable | Obligatoria para | De dónde sale |
|---|---|---|
| `DISCORD_TOKEN` | El bot arranque | Discord Developer Portal → tu app → Bot → Token |
| `DATABASE_URL` | El bot arranque | La base que acabas de crear (`docs/POSTGRES.md`) |
| `DISCORD_CLIENT_ID` | Dashboard web | Developer Portal → OAuth2 → Client ID |
| `DISCORD_CLIENT_SECRET` | Dashboard web | Developer Portal → OAuth2 → Reset Secret |
| `SESSION_SECRET` | Dashboard web | `python3 -c "import secrets; print(secrets.token_hex(32))"` |

Sin las tres del dashboard el bot arranca igual: no hay ningún error hasta que
alguien intenta loguearse al panel y recibe un 404. El resto de variables
(`R2_*`, `BACKUP_AGE_RECIPIENTS`, `GROQ_API_KEY`, `POLAR_*`, límites) son
opcionales o tienen fallback; ver `.env.example` y DEPLOY.md § 4. `urls.env` y
`limits.env` están versionados en git y vienen con el `git clone`.

## 4. systemd

```bash
deploy/render_service.sh <usuario> <ruta> > /tmp/bot-purg.service
cat /tmp/bot-purg.service   # ¿dice lo que esperas?
sudo cp /tmp/bot-purg.service /etc/systemd/system/bot-purg.service
sudo systemctl daemon-reload
sudo systemctl enable --now bot-purg
sudo systemctl status bot-purg   # confirmar "active (running)"
```

Si falla con `status=203/EXEC`: revisa que no se hayan descomentado
`ProtectHome`/`ReadOnlyPaths`/`ReadWritePaths`/`ProtectSystem=strict` en el
template; esa combinación rompió en systemd real sobre Ubuntu (ver la nota en
`deploy/bot-purg.service.template`).

Instala también el cron de backups (`17 3 * * 0`, ver DEPLOY.md § Backups de
PostgreSQL) y confirma con el primer disparo que aparece un `BACKUP COMPLETE`.

## 5. nginx

Reconstruir `/etc/nginx/conf.d/purgito.conf` desde DEPLOY.md § Configurar
nginx (no está versionado en el repo). Puntos que ya rompieron antes:

- `location = /es/` y `location = /en/` con `try_files`: **nunca** un redirect
  ahí, genera loop infinito.
- Ubuntu/Debian: `chmod o+x /home/<usuario>` si `/var/www/purgito-landing` es
  un symlink dentro del home (si no, nginx da 500 sirviendo la landing).
- Oracle Linux: `setsebool -P httpd_can_network_connect 1` +
  `restorecon -Rv /var/www/purgito-landing` si da 502/403 (SELinux).

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Túnel, DNS y acceso (Cloudflare / Tailscale)

- **Túnel:** HTTPS lo termina Cloudflare y llega al origen por `cloudflared` hacia
  nginx por loopback. Mueve o recrea el túnel en el servidor nuevo (ver DEPLOY.md
  § Cloudflare).
- **DNS:** actualiza los registros de `purgito.app`, `www.purgito.app` y
  `gifs.purg4t0ry.com` (el dominio "heredado" de la galería, fácil de olvidar).
  Purga la caché de Cloudflare después. Si algo "no cambia" tras el deploy,
  sospecha de la caché antes que del código.
- **Acceso:** une el servidor a Tailscale y repite `deploy/harden_firewall.sh`
  (tiene auto-reversión a los 15 minutos) y `deploy/harden_postgres.sh`.

## 7. Verificar

```bash
deploy/preflight_check.sh
deploy/security_check.sh
```

Corrige lo que marque en rojo antes de dar la migración por terminada.

## 8. Avisar

Si hubo downtime visible para usuarios (el bot desconectado de Discord, o la
web caída), avisa en el [servidor de soporte](https://discord.gg/5U7HKyxnBv).

## Antes de destruir la instancia vieja

Ver el checklist en
[`docs/PORTABILITY.md`](docs/PORTABILITY.md#checklist--antes-de-destruir-la-instancia-vieja).
Resumen: backup cifrado confirmado en R2, `.env` y clave privada de age fuera de
la instancia, y recién entonces dejarla ir.
