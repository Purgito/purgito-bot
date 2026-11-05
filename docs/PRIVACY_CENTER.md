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

## Frontend

Pestaña **Privacidad** del perfil: `/es/perfil/privacidad` y `/en/perfil/privacidad` (`landing/js/perfil.js`,
lógica pura en `landing/js/core/privacy.js`, prueba en `landing/test_privacy.mjs`). Usa la sesión de Discord
de purgito.app y la API de arriba. **Cloudflare Access no va delante**: Access protege el panel privado de
Studio (`docs/STUDIO_ACCESS.md`); aquí entra cualquier persona con su propia cuenta y ver solo lo suyo lo
garantiza la API (la sesión, nunca un id enviado por el cliente), no un perímetro de red.

## Garantías y límites

- **Persistencia:** la solicitud vive en PostgreSQL. Si el bot se cae a mitad de un intento, el
  arrendamiento (10 min) vence y el siguiente ciclo (60 s) la retoma.
- **Idempotencia:** el borrado se puede repetir sin efecto. Cada intento lleva un número (token de control):
  uno retrasado que despierta después de que otro retomó la solicitud no puede cerrarla ni degradarla.
- **Plazo:** `due_at = creación + 7 días`. Los fallos se reintentan a 1, 5, 30, 120 y 360 min
  (luego cada 360 min). Un fallo nunca cancela la solicitud.
- **Conservación (confirmada 2026-11-05):** las solicitudes terminadas se borran **90 días después de su cierre**
  (`completed_at`, `RETENTION_DAYS`). El registro encadenado no lleva ids de persona y se conserva.
- **Avisos por Gmail:** exclusivamente administrativos (al titular). Solo número de solicitud, estado, fechas
  e intentos. Sin credenciales (`PRIVACY_ALERT_*`) el aviso queda pendiente y se envía cuando haya configuración.

### Registro encadenado y su ancla externa

La cadena de hashes detecta una fila cambiada, quitada o intercalada. No detecta que alguien con control de
la base **reescriba todo** y recalcule los hashes. Para eso, cada instantánea horaria del registro externo
lleva un `log_anchor` (último `seq` y su hash). Esas instantáneas se cifran y suben desde el runner aislado
(`purgito_backup`, credenciales R2 que el bot no tiene), así que no se pueden reescribir desde la base ni desde
el bot. Ningún servicio ni secreto nuevo.

Verificar (con la clave age, en el equipo del titular o en el servidor):

    age -d -i clave.txt privacy-ledger-AAAAMMDDTHHMMSSZ.jsonl.age > ancla1.jsonl
    .venv/bin/python scripts/verify_privacy_log.py --anchor ancla1.jsonl [--anchor ancla2.jsonl ...]

Códigos: 0 coincide · 1 ALTERADO · 2 ancla posterior a la base (restauración antigua o cola borrada; no se
distingue) · 3 entrada inválida. **Límites:** una fila posterior al último ancla queda sin cubrir hasta la
siguiente instantánea (≤ 1 h); un ancla solo existe mientras viva su instantánea (15 días); y un atacante que
también controlara las credenciales del runner o el bucket podría falsear anclas.

### Límites del registro externo

- **Frescura:** se exporta cada hora. Una eliminación, exclusión, solicitud o lápida hecha en la última hora antes
  de perder TODO el servidor no está en el registro.
- **Mensajes sueltos y canales:** se anotan (id + fecha, sin contenido) **solo si estaban realmente en el corpus**
  en el momento de borrarlos/editarlos. Un mensaje ya recortado del corpus por el límite de tamaño pero presente
  en un backup antiguo no tiene lápida y reaparecería. Tope de 100 000 lápidas de mensaje por instantánea
  (~8 MB); si se supera se exportan las más recientes, el pie marca `truncated` y `reapply_deletions.py` se niega
  a seguir sin `--aceptar-truncado`. Un canal limpiado a propósito (NSFW, purga) también deja lápida: si luego
  vuelve a aprenderse, una restauración dentro de los 15 días lo borraría otra vez.
- **Vigencia:** 15 días por lápida (14 de vida máxima de un backup + 1), como las de usuario y servidor.
- **Solo ids y fechas:** nada de contenido; la instantánea va cifrada con age.

### Datos administrativos: política

Qué contienen y qué se hace cuando la persona pide su eliminación (`/borrar_mis_datos` o el Centro):

| Dato | Información personal | Eliminación | Exportación | Por qué |
|---|---|---|---|---|
| `audit_log.user_id`, `user_name` | id y nombre del admin que actuó | **Seudonimizar** (`0`, `[eliminado]`); la acción, la fecha y el servidor se conservan | Entradas donde fue quien actuó | Es el historial del servidor (90 días, política vigente). Borrar filas lo vaciaría y permitiría a un admin borrar su rastro; quitar solo la identidad cumple el derecho sin perder la integridad. |
| `audit_log.detail` / `previous_detail` | id de la persona afectada en acciones sobre exclusiones (`user_id=N`) | Se reemplaza `user_id=N` por `user_id=[eliminado]` (solo ese id exacto) | Entradas que la mencionan; los ids de **otras** personas salen enmascarados | Una exclusión liga a la persona con una preferencia suya. |
| `scheduled_announcements.created_by` | id del admin que programó | **Seudonimizar** (`0`); el anuncio queda | Anuncios que creó (con su texto, que escribió él) | El anuncio es del servidor. |
| `frases_especiales.user_id`, `user_name` | id y nombre de quien agregó la frase | **Seudonimizar**; la frase queda | Frases que agregó | La frase es del servidor; la política publica que la atribución dura mientras la frase exista, salvo petición. |
| `gif_senders`, `member_boost_records` | id de quien envió un GIF / impulsa el servidor | **Borrar** | Sí | Dato personal sin función de integridad. |

Al restaurar un backup, `reapply_deletions.py` vuelve a aplicar la seudonimización a quien tenga lápida vigente.
Sigue sin cubrirse: `/settings` ejecutado dentro de Discord no deja rastro en `audit_log` (así lo dice la política).

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
   Comprobar con `systemctl start purgito-ledger.service` y el log de `ledger.log`: debe listar
   solicitudes, mensajes, canales y "ancla del registro: 1".
5. Avisos por Gmail (cuando el titular quiera): como el usuario del bot, ejecutar
   `deploy/set_privacy_alert_credentials.sh` (pide los valores sin eco) y reiniciar `bot-purg`.
   Es una contraseña de aplicación de Google; usar una cuenta dedicada.
6. Restaurar un backup (cuando haga falta): `pg_restore` y luego
   `reapply_deletions.py --ledger - --apply < registro.jsonl` antes de arrancar el bot.

Marcha atrás: volver a la rama anterior y reiniciar. Las dos tablas nuevas pueden quedar; no las
lee el código anterior.

## Pendientes que siguen abiertos

- **Cifrado en reposo (P0): NO resuelto.** Estado, opciones y criterio de cierre en `docs/CIFRADO_EN_REPOSO.md`;
  lo mide `deploy/check_encryption_at_rest.sh` (hoy sale con código 1).
- **Markov y condiciones de Discord:** sin interpretar; pendiente de aclaración con Discord.
- **Snapshot de Renas:** sin confirmar (precondición del despliegue).
