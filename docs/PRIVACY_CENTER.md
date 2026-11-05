# Centro de Privacidad: backend y despliegue

Guía operativa de la parte de servidor del Centro de Privacidad. La política pública está en
`docs/PRIVACY.md`; el registro externo de eliminaciones, en `docs/POSTGRES.md`. No hay frontend
nuevo: la API está lista para que `landing/` la consuma cuando se diseñe.

## Qué hace

| Pieza | Dónde |
|---|---|
| Exclusión global (aprendizaje + interacción) | `/privacidad` y `PUT /api/me/privacy/exclusion`; fila `excluded_users.guild_id = 0` |
| Solicitud de eliminación diferida | `POST /api/me/privacy/requests`; tabla `privacy_requests`; trabajador en `cogs/privacy.py` |
| Copia de los datos | `/mis_datos` y `GET /api/me/privacy/export` (misma función: `db.build_user_export`) |
| Estado | `GET /api/me/privacy` |
| Registro verificable | `privacy_request_log` (hash encadenado, sin ids de persona) |
| Avisos al titular (Gmail) | `privacy_alerts.py`: fallo, menos de 48 h, vencida (se repite cada 24 h) |

Todos los endpoints actúan solo sobre la persona de la sesión; ninguno acepta un `user_id`.

## Garantías y límites

- **Persistencia:** la solicitud vive en PostgreSQL. Si el bot se cae a mitad de un intento, el
  arrendamiento (10 min) vence y el siguiente ciclo (60 s) la retoma.
- **Plazo:** `due_at = creación + 7 días`. Los fallos se reintentan a 1, 5, 30, 120 y 360 min
  (luego cada 360 min). Un fallo nunca cancela la solicitud.
- **Registro:** `privacy_requests.verify_log()` recalcula la cadena y devuelve la primera fila
  alterada. Está en la misma base: protege contra edición accidental o parcial, **no** contra
  quien tenga control total de la base y recalcule toda la cadena. Para eso haría falta anclar el
  último hash fuera del servidor (pendiente, no implementado).
- **Tras un restore:** las solicitudes abiertas viajan en el registro externo (`deletion_request`) y
  `reapply_deletions.py --ledger` las recrea con su plazo original. Las completadas ya están en la
  lápida del usuario (15 días).
- **Conservación:** las solicitudes terminadas se borran a los 90 días (`RETENTION_DAYS`); el
  registro, que no lleva ids de persona, se conserva.
- **Avisos:** el correo solo lleva el número de solicitud, estado, fechas e intentos. Sin
  credenciales (`PRIVACY_ALERT_*`) la solicitud se procesa igual y el aviso queda pendiente hasta
  que haya configuración; un aviso solo se marca enviado si el correo salió.

## Despliegue (orden importa)

Precondición: autorización explícita del titular y snapshot reciente de la VM.

1. En el checkout de producción, traer la rama (`git fetch` + `git merge --ff-only` de
   `dev/privacidad-p0p1`, o la que se acuerde). Sin push desde la VM.
2. `sudo systemctl restart bot-purg`. `init_db()` crea `privacy_requests` y `privacy_request_log`
   (esquema idempotente); no hay migración destructiva. Comprobar en el log que arranca el cog
   `Privacy` y que `/privacidad` queda registrado (si no, sincronizar comandos como en cada deploy).
3. Verificar: `GET /api/me/privacy` con sesión devuelve 200; `/privacidad accion:Ver mi estado`.
4. **Después** de que las tablas existan, reinstalar el runner de backups para que el exportador del
   registro incluya las solicitudes: `sudo deploy/install_backup_runner.sh` (el exportador viejo sigue
   funcionando sin ellas; el nuevo falla si la tabla no existe, por eso va en segundo lugar).
   Comprobar con `systemctl start purgito-ledger.service` y el log de `ledger.log`.
5. Avisos por Gmail (cuando el titular quiera): como el usuario del bot, ejecutar
   `deploy/set_privacy_alert_credentials.sh` (pide los valores sin eco) y reiniciar `bot-purg`.
   Es una contraseña de aplicación de Google; usar una cuenta dedicada.
6. Restaurar un backup (cuando haga falta): `pg_restore` y luego
   `reapply_deletions.py --ledger - --apply < registro.jsonl` antes de arrancar el bot.

Marcha atrás: volver a la rama anterior y reiniciar. Las dos tablas nuevas pueden quedar; no las
lee el código anterior.

## Pendientes que siguen abiertos

- **Cifrado en reposo (P0): NO resuelto.** Nada de este trabajo lo implementa. Se marcará resuelto
  solo cuando exista una implementación comprobable (disco o base cifrados, con prueba de arranque
  y de recuperación).
- **Markov y condiciones de Discord:** sin interpretar; pendiente de aclaración con Discord.
- **Frontend del Centro de Privacidad:** no existe (solo la API).
- **Datos administrativos:** `audit_log` (acciones de admins) y `scheduled_announcements.created_by`
  siguen fuera del borrado y la exportación; falta decidir su tratamiento en la política.
- **Mensajes sueltos eliminados en Discord:** no entran al registro externo (ver `docs/POSTGRES.md`).
- **Anclaje externo del registro verificable** (ver arriba).
