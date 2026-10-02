# Runbook — qué hacer cuando algo se rompe

Guía de incidentes para quien opera el bot. No es documentación de usuario
(no se publica en la web) y no lleva secretos: nunca pegues aquí valores de
`.env`. Los pasos largos ya viven en otros documentos; aquí solo va el orden
de qué hacer primero y a dónde ir.

Convención: `<usuario>` y `<ruta>` son el usuario y el checkout del servidor
actual (ver el checklist al inicio de [`DEPLOY.md`](../DEPLOY.md) — el
servidor no es fijo).

## Primeros 5 minutos, para cualquier incidente

```bash
ssh <usuario>@<servidor>
sudo systemctl status bot-purg          # ¿corre? ¿cuándo arrancó por última vez?
journalctl -u bot-purg -n 200 --no-pager
tail -n 200 <ruta>/data/bot.log         # mismo log, rotado (3 archivos de 5 MB)
curl -s http://127.0.0.1:8080/health    # {"ok": true} si el proceso web responde
```

Si el proceso está arriba pero el bot no responde en Discord, mira el log
por `Traceback` y por errores del gateway antes de reiniciar: reiniciar borra
el estado en memoria (cooldowns, rate limits) y no arregla un bug de código.

## 1. El bot está caído

1. `sudo systemctl status bot-purg` — el unit tiene `Restart=on-failure` y
   `StartLimitIntervalSec=0`, así que un fallo suelto se recupera solo. Si
   sigue caído, algo falla en cada arranque.
2. `journalctl -u bot-purg -n 200 --no-pager` — busca la primera excepción
   tras el arranque (variable faltante, token rechazado, PostgreSQL caído o
   `DATABASE_URL` mala, disco lleno).
3. `df -h <ruta>/data` — un disco lleno tumba PostgreSQL y el log a la vez. Si Postgres murió,
   mira `/var/log/postgresql/` y `journalctl -k | grep -i oom` (VM de 2 GB: el OOM
   killer ya lo mató una vez).
   Libera espacio (backups viejos en `BACKUP_DIR`, `bot.log.1-3`) y reinicia.
4. `<ruta>/deploy/preflight_check.sh` — valida `.env`, dependencias,
   systemd y nginx.
5. Si el último `git pull` fue lo que lo rompió: `git log -5`, vuelve al
   commit anterior (`git checkout <sha>`) y `sudo systemctl restart bot-purg`.
   No hay CI/CD ni rollback automático: es manual.

## 2. La web/dashboard no carga pero el bot sí responde

1. Prueba `/health` local (arriba). Si responde, el problema está delante:
   nginx (`sudo nginx -t`, `journalctl -u nginx`) o Cloudflare.
2. Cloudflare cachea. Si "no cambia" tras un deploy, purga caché antes de
   sospechar del código.
3. Rutas `/<lang>/dashboard/:id` sirviendo la homepage: falta el `location`
   por regex de nginx (ver `DEPLOY.md` § Configurar nginx).

## 3. Se filtró un secreto

Actúa primero (rota), investiga después. Cada secreto se rota en su origen y
se actualiza en `<ruta>/.env`; después `sudo systemctl restart bot-purg`.

| Secreto | Dónde se rota | Efecto colateral |
|---|---|---|
| `DISCORD_TOKEN` | Developer Portal → Bot → Reset Token | El bot se desconecta hasta reiniciar con el nuevo |
| `DISCORD_CLIENT_SECRET` | Developer Portal → OAuth2 → Reset Secret | El login del dashboard falla hasta reiniciar |
| `SESSION_SECRET` | Generar uno nuevo (`python3 -c "import secrets; print(secrets.token_hex(32))"`) | Todas las sesiones del dashboard dejan de descifrar: todos tienen que volver a iniciar sesión (esperado, no es un bug) |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | Cloudflare → R2 → API Tokens: crear uno nuevo y borrar el viejo | Mientras el bot corra con el token borrado, subir y borrar imágenes y GIFs falla, y `backup_db.sh` no puede subir el backup (la corrida falla a propósito) |
| `POLAR_ACCESS_TOKEN` / `POLAR_WEBHOOK_SECRET` | Panel de Polar (Settings → Developers / el webhook) | Si cambias el webhook secret, actualiza también el `.env` o los webhooks se rechazarán (firma inválida) |
| `GROQ_API_KEY` | Consola de Groq | Los captions de memes con IA vuelven a Markov hasta actualizarla |
| `TWITCH_CLIENT_SECRET` | Consola de Twitch | Los avisos de Twitch fallan hasta actualizarlo |

Si el secreto llegó a un commit: además de rotarlo, corre gitleaks contra el
historial (`gitleaks git --config .gitleaks.toml -v .`); reescribir el
historial no basta, un secreto publicado se considera comprometido.

Los `webhook_token` de canales (tabla `channel_webhooks`) no están en `.env`:
si se filtró un dump de PostgreSQL, la SQLite vieja o un backup, esos tokens permiten
postear en esos canales. No hay rotación automática; borrar y recrear el
webhook desde Discord en cada canal afectado invalida el token viejo.

## 3b. Sospecha de acceso no autorizado al servidor o a PostgreSQL

1. No apagues nada todavía si hace falta conservar evidencia: `sudo ss -tnp`, `last`,
   `sudo journalctl -u ssh --since "-2 days"`, `sudo grep -E "FATAL|ERROR" /var/log/postgresql/postgresql-18-main.log`.
2. Contener: `sudo ufw status verbose` debe seguir activo; `deploy/security_check.sh`
   dice qué cambió (5432/8080 expuestos, permisos, `trust` en `pg_hba`).
   Desde Tailscale admin, quita el dispositivo sospechoso.
3. Rota en este orden: contraseña de `purgito_app` (`sudo -u postgres psql -c "ALTER
   ROLE purgito_app PASSWORD '...'"` + `DATABASE_URL`), `DISCORD_TOKEN`,
   `SESSION_SECRET`, token de R2 (§ 3). Si hubo acceso a la base o a un backup, los
   `webhook_token` de `channel_webhooks` también se consideran comprometidos.
4. Si hubo acceso al disco, el corpus de mensajes se considera expuesto: decide si hay
   que avisar a los administradores de los servidores afectados.
5. Si hay que reconstruir, sigue [`MIGRATION.md`](../MIGRATION.md) con un backup cifrado
   anterior al incidente y `reapply_deletions.py`.

## 4. La base de datos está corrupta o se perdió

1. Para el bot: `sudo systemctl stop bot-purg`.
2. Guarda lo que quede antes de tocar nada: `pg_dump -Fc "$DATABASE_URL" -f
   /ruta/seguro.dump` si Postgres responde (si no, copia el directorio de datos
   con Postgres parado).
3. Comprueba: `psql "$DATABASE_URL" -c "SELECT count(*) FROM settings"` y
   `systemctl status postgresql`. Si responde bien, el problema no es la DB.
4. Si no, restaura el backup más reciente que pase la verificación (hay como máximo
   2, el último y el anterior; se hacen cada semana, así que lo escrito después del
   último se pierde). Los backups
   son `.dump.age` (cifrados): hace falta la clave PRIVADA de age, que NO está en el
   servidor (tu gestor de contraseñas / copia offline). Si solo queda la copia de R2:
   `python scripts/r2_backup.py download latest --dest <carpeta>`. Luego
   `AGE_IDENTITY=<clave> deploy/restore_check.sh <ruta-al-backup>` y el procedimiento de
   `docs/POSTGRES.md` § "Restaurar" (incluye `scripts/reapply_deletions.py --apply`,
   obligatorio antes de arrancar: vuelve a borrar a quien pidió `/borrar_mis_datos`
   después del backup). Si el servidor es nuevo, copia también los
   flags sueltos de `data/` (`.images_wiped_v2`, etc.; ver `docs/PORTABILITY.md`
   § 2): viven fuera de la base y sin ellos el arranque puede repetir
   migraciones destructivas.
5. `sudo systemctl start bot-purg` y revisa el log.
6. Si perdiste todo el servidor (el caso de Oracle): sigue
   [`MIGRATION.md`](../MIGRATION.md).

Los backups son semanales y se conservan como máximo 2 (el más reciente y el
anterior), en `BACKUP_DIR` y en R2 (`docs/POSTGRES.md` § Backups). Los de `BACKUP_DIR`
viven en el mismo disco que la base. Si el
servidor completo se perdió, la copia que sobrevive es la del bucket privado de
R2 (`R2_BACKUP_BUCKET`), siempre que `backup_db.sh` la haya estado subiendo; sin
ella, no hay copia salvo que la hayas bajado a mano — por eso el checklist de
`docs/PORTABILITY.md` pide sacar `data/` y `.env` fuera de la instancia antes de
dejarla ir.

## 5. Premium desincronizado (alguien pagó y no tiene Premium, o al revés)

1. Mira el log por `/webhooks/polar` (los eventos ignorados se registran a
   nivel `info`).
2. `python scripts/reconcile_premium.py` compara Polar contra
   `premium_guilds` y solo reporta, nunca escribe. Revisa cada diferencia a
   mano: un Premium sin suscripción en Polar puede ser una cortesía
   otorgada a mano.
3. `_webhook_polar` en `webapi.py` es zona protegida: no lo edites en
   caliente para arreglar un caso puntual.

## 6. Fallan los GIFs (links rotos, subidas que no funcionan)

1. Confirma que las credenciales `R2_*` de `.env` siguen vigentes (un token
   expirado o borrado rompe subidas y borrados).
2. Los scripts de `scripts/` (`reconcile_gif_objects.py`,
   `cleanup_dead_cdn_gifs.py`, etc.) documentan en su docstring cuándo hay
   que parar el bot antes de correrlos. Léelo antes de usar `--apply`.

## 7. Después del incidente

- Anota qué pasó, qué lo detectó y cuánto tardó en detectarse. Hoy la
  detección depende en gran parte de que alguien note el problema: no hay
  monitor externo. Lo único automático son dos avisos en el canal del proyecto
  (`LIFECYCLE_ANNOUNCE_CHANNEL_ID`): "Purgito volvió" tras un reinicio o una
  caída, y "la tarea `X` falló N veces" cuando un loop en segundo plano se
  reinicia varias veces seguidas (mira el log por el traceback de esa tarea).
- Si el arreglo fue un cambio visible para admins de servidor, regístralo en
  `docs/NOVEDADES.md` y `docs/NOVEDADES.en.md` (ambos idiomas) y corre
  `landing/build_docs.py`.
- Si un procedimiento de este runbook no funcionó como dice, corrígelo aquí
  en el mismo commit que arregla el problema.
