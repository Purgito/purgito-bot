# Migración a un servidor nuevo — flujo rápido

"Me quedé sin servidor, necesito levantar en otro proveedor ya." Este
documento es el camino corto, en orden, sin la explicación completa de cada
paso — para eso está [`DEPLOY.md`](DEPLOY.md) (sección 0 tiene el mismo
checklist con más detalle y los problemas ya tropezados) y
[`docs/PORTABILITY.md`](docs/PORTABILITY.md) (qué datos hay que salvar y
por qué).

Motivo por el que este documento existe: la migración de Oracle a AWS del
2026-09-05 tomó varias horas porque varios pasos no estaban documentados en
ningún lado. La idea es que la próxima tome minutos.

## 0. Si la instancia vieja todavía está viva

Antes de tocar nada del servidor nuevo, en la instancia vieja:

```bash
# Directorio data/ COMPLETO -- no solo bot.db (ver por qué en
# docs/PORTABILITY.md § 2: hay flags de migración sueltos que no
# entran en un `sqlite3 .backup` de solo el .db)
scp -r <usuario>@<viejo>:<ruta>/data ./migracion-backup/

# .env completo -- no lo reconstruyas variable por variable en el
# servidor nuevo, copialo tal cual (evita perder SESSION_SECRET y
# desloguear a todo el mundo sin necesidad)
scp <usuario>@<viejo>:<ruta>/.env ./migracion-backup/

# si hay backups de cron corriendo (deploy/backup_db.sh), bajate también
# el más reciente por las dudas
scp <usuario>@<viejo>:<ruta-backups>/bot-*.db ./migracion-backup/ 2>/dev/null || true
```

R2 (GIFs) no necesita nada de esto — vive fuera de la instancia por diseño,
las credenciales viajan con el `.env`.

## 1. Crear la instancia nueva

Cualquier VM Linux moderna con salida a internet y un usuario con `sudo`
sirve. Anotá **usuario** y **ruta de checkout** elegidos — se necesitan
exactos más abajo para generar el unit de systemd. Identificá la distro
(`cat /etc/os-release`): Oracle Linux (`dnf`, SELinux) y Ubuntu/Debian
(`apt`, sin SELinux) difieren en varios comandos — DEPLOY.md los marca por
separado.

## 2. Clonar e instalar

```bash
git clone https://github.com/punkyyy01/bot-discord-purg.git <ruta>
cd <ruta>

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# gifsicle -- ver DEPLOY.md § Paquetes del sistema por distro
which gifsicle || echo "falta instalar gifsicle"
```

## 3. Restaurar datos y config

```bash
cp -r /ruta/a/migracion-backup/data ./data
cp /ruta/a/migracion-backup/.env .env
test -f .env && echo "OK: .env es un archivo" || echo "MAL -- revisar"
```

Si no hay backup de la instancia vieja (se perdió sin aviso, como Oracle) y
hay que reconstruir `.env` desde cero, **lista completa de variables
obligatorias**:

| Variable | Obligatoria para | De dónde sale |
|---|---|---|
| `DISCORD_TOKEN` | El bot arranque | Discord Developer Portal → tu app → Bot → Token |
| `DISCORD_CLIENT_ID` | Dashboard web | Developer Portal → OAuth2 → Client ID |
| `DISCORD_CLIENT_SECRET` | Dashboard web | Developer Portal → OAuth2 → Reset Secret |
| `SESSION_SECRET` | Dashboard web | `python3 -c "import secrets; print(secrets.token_hex(32))"` |

Sin las tres del dashboard el bot arranca igual — no hay ningún error hasta
que alguien intenta loguearse al panel y recibe un 404. El resto de
variables (`R2_*`, `GROQ_API_KEY`, `POLAR_*`, límites) son opcionales o
tienen fallback — ver `.env.example` completo y DEPLOY.md § 4 si hace falta
reconstruir más que lo mínimo. `urls.env` y `limits.env` están versionados
en git, vienen con el `git clone`, no hay que reconstruirlos.

## 4. systemd

```bash
deploy/render_service.sh <usuario> <ruta> > /tmp/bot-purg.service
cat /tmp/bot-purg.service   # ¿dice lo que esperás?
sudo cp /tmp/bot-purg.service /etc/systemd/system/bot-purg.service
sudo systemctl daemon-reload
sudo systemctl enable --now bot-purg
sudo systemctl status bot-purg   # confirmar "active (running)"
```

Si falla con `status=203/EXEC`: revisar que no se hayan descomentado
`ProtectHome`/`ReadOnlyPaths`/`ReadWritePaths`/`ProtectSystem=strict` en el
template — esa combinación rompió en systemd real sobre Ubuntu (ver la nota
en `deploy/bot-purg.service.template`).

## 5. nginx

Reconstruir `/etc/nginx/conf.d/purgito.conf` desde DEPLOY.md § Configurar
nginx (no está versionado en el repo). Puntos que ya rompieron antes:

- `location = /es/` y `location = /en/` con `try_files` — **nunca** un
  redirect ahí, genera loop infinito.
- Ubuntu/Debian: `chmod o+x /home/<usuario>` si `/var/www/purgito-landing`
  es un symlink dentro del home (si no, nginx da 500 sirviendo la landing).
- Oracle Linux: `setsebool -P httpd_can_network_connect 1` +
  `restorecon -Rv /var/www/purgito-landing` si da 502/403 (SELinux).

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 6. DNS (Cloudflare)

Actualizar los A records a la IP nueva:

- `purgito.app`
- `www.purgito.app`
- `gifs.purg4t0ry.com` — el dominio "heredado" de la galería, fácil de
  olvidar porque no aparece en ningún lado obvio del dashboard

Purgar caché de Cloudflare después. Si algo "no cambia" tras el deploy,
sospechar de la caché antes que del código.

## 7. Verificar

```bash
deploy/preflight_check.sh
```

Corrige lo que marque en rojo antes de dar la migración por terminada.

## 8. Avisar

Si hubo downtime visible para usuarios (el bot desconectado de Discord, o
la web caída), avisar en el [servidor de soporte](https://discord.gg/5U7HKyxnBv).

## Antes de destruir la instancia vieja

Ver el checklist de 5 minutos en
[`docs/PORTABILITY.md`](docs/PORTABILITY.md#checklist--antes-de-destruir-la-instancia-vieja) — resumen: backup de `data/` completo + `.env` fuera de la instancia, confirmado, antes de dejarla ir.
