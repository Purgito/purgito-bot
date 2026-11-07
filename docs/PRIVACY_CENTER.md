# Centro de Privacidad: backend y despliegue

Guía operativa de la parte de servidor del Centro de Privacidad. La política pública está en
`docs/PRIVACY.md`; el registro externo de eliminaciones, en `docs/POSTGRES.md`. No hay frontend
nuevo: la API está lista para que `landing/` la consuma cuando se diseñe.

## Qué hace

| Pieza | Dónde |
|---|---|
| Exclusión global (aprendizaje + interacción) | `PUT /api/me/privacy/exclusion`; fila `excluded_users.guild_id = 0` |
| Solicitud de eliminación diferida | `POST /api/me/privacy/requests`; tabla `privacy_requests`; trabajador en `cogs/privacy.py` |
| Copia de los datos | `GET /api/me/privacy/export` (`db.build_user_export`) |
| Otros derechos (acceso, rectificación, oposición, portabilidad, limitación) | `POST /api/me/privacy/rights`; tabla `privacy_rights_requests`; plazo interno 30 días; la atiende una persona con `scripts/privacy_inbox.py` |
| Estado | `GET /api/me/privacy` |
| Registro verificable | `privacy_request_log` (hash encadenado, sin ids de persona) |
| Avisos al titular (Gmail) | `privacy_alerts.py`: fallo, menos de 48 h, vencida (se repite cada 24 h) |

Todos los endpoints actúan solo sobre la persona de la sesión; ninguno acepta un `user_id`.

**Los comandos de Discord `/borrar_mis_datos`, `/mis_datos` y `/privacidad` se retiraron (2026-11):** el Centro (https://purgito.app/privacidad, con Discord OAuth2) es la única interfaz de autoservicio. El cog `Privacy` solo conserva el trabajador de fondo. Contacto alternativo para quien no pueda iniciar sesión: contacto@purgito.app.

**Procedimiento de las solicitudes de derechos (Ley 21.719 art. 11, ver `docs/LEY_21719.md`):** acuse de recibo inmediato en el Centro (`receipt`); por correo (contacto@purgito.app) se acusa recibo el mismo día hábil y se registra la solicitud con el formulario. Responder por escrito dentro del plazo (30 días corridos; 2 días para el bloqueo temporal) con `privacy_inbox.py answer ID --text-file respuesta.txt` (guarda texto y fecha; la persona la ve en el Centro; si dio un correo, enviarla también ahí; el correo se borra al contestar). Para denegar: `--deny` (la respuesta debe fundar la causa; se añade el aviso de los 30 días hábiles para reclamar ante la Agencia).

**Alertas:** las solicitudes de eliminación fallidas, por vencer (< 48 h) o vencidas, y las de derechos vencidas, se envían a Purgito Monitor (`system.warning` crítico → alerta de Discord) además del correo si hay `PRIVACY_ALERT_*`. Los fallos de respaldo (`purgito-backup`, `purgito-ledger`, `purgito-backup-check`) avisan al mismo monitor con `OnFailure=purgito-notify@%n` (`deploy/install_monitor_notify.sh`; credenciales en `/etc/purgito/monitor.env`, root 0600).

**Operación:** `scripts/privacy_inbox.py list|who|answer|check` (bandeja de derechos; `check` sale con 1 si hay algo vencido o por vencer, también de eliminaciones). El trabajador registra un ERROR cada hora si hay solicitudes de derechos vencidas. Los avisos por Gmail siguen requiriendo `PRIVACY_ALERT_*`.

**Atribución del corpus:** `corpus_messages.author_id` (desde 2026-11). Las filas heredadas se atribuyen solo por el vínculo exacto (guild_id, message_id) con `user_corpus`; las que no tienen vínculo se eliminan con `scripts/migrate_corpus_authors.py --apply` (dry-run por defecto; hacer un respaldo antes). `reapply_deletions.py` repite esa regla al restaurar un backup anterior.

**GIFs:** cada GIF lleva su remitente (usuario, servidor, canal, mensaje). Al borrar el mensaje o al eliminar los datos de la persona, si no queda otro remitente independiente se elimina la fila y, por el conteo de referencias de `gif_objects`, el archivo de R2. Solo se capturan GIFs de canales que `@everyone` puede ver y que no son NSFW.

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

### Restauración segura (falla antes que aparentar éxito)

Ningún backup puede volver a poner en marcha el bot sin reconciliación válida:

- **Guardián de arranque** (`src/privacy_guard.py`): el bot escribe cada minuto un latido en la base y en un
  archivo local (`data/privacy_watermark`, dentro del volumen cifrado). Si al arrancar la base es **más antigua**
  que lo último que este servidor vio (o carece de latido, o el servidor no tiene archivo y el latido de la base
  tiene más de 10 minutos), el bot **se niega a arrancar** (código 78; systemd no lo reintenta). Lo único que
  pone la base al día es `scripts/reapply_deletions.py --apply` con un registro válido.
- **El registro se valida**: es obligatorio (`--ledger`; `--sin-registro` es un acto explícito), no puede tener
  más de 2 h ni ser anterior al latido de la base, y se rechaza si está marcado `truncated`. Se puede forzar solo
  con `--aceptar-registro-antiguo` / `--aceptar-truncado`, dejando constancia en pantalla.
- Un backup anterior a estas tablas no las tiene: `reapply_deletions.py` crea el esquema antes de reconciliar.

Procedimiento: parar el bot → `pg_restore` → `reapply_deletions.py --ledger - --apply < registro.jsonl` (el
registro descifrado más reciente de `gen2/ledger/`) → arrancar el bot. Sin el último paso del medio, el paso
final se rechaza.

### Límites del registro externo (revisados)

- **Frescura:** se exporta **cada 5 minutos** (`purgito-ledger.timer`; antes cada hora) y `purgito-backup-check`
  avisa si no hay instantánea de menos de 1 h. Queda irreducible la ventana entre una eliminación y la siguiente
  exportación (≤ 5 min): si se perdiera TODO el servidor en ese lapso, esa eliminación no está en el registro.
- **Vigencia de lápidas: 15 días**, un día más que la vida máxima de un backup (14). Un backup nunca es más viejo
  que la lápida que lo corrige; uno de más de 14 días ya no existe (Lifecycle) y, si apareciera, el registro
  exigido no podría cubrirlo: la restauración lo rechaza por antigüedad.
- **Desbordamiento (antes: tope de 100 000)**: pasado `MAX_MESSAGE_TOMBSTONES` lápidas de mensaje, las de los
  servidores que más acumulan se **sustituyen por un corte por servidor** ("borra todo lo aprendido antes de esta
  fecha"). Sobre-borra a propósito: pierde corpus de ese servidor en el restore, nunca deja reaparecer un
  mensaje. Solo se marca `truncated` (y el restore se niega) si hay más de 1 000 000 de filas.
- **Mensajes sueltos y canales:** se anotan solo si estaban en el corpus al borrarse/editarse. Un mensaje ya
  recortado por tamaño pero presente en un backup antiguo no tiene lápida: es el límite que queda.
- **Ancla:** ver arriba; cubre hasta la última instantánea y mientras viva (15 días).

### Retención por antigüedad del corpus (P0 de retención)

Separada de los 90 días de las solicitudes terminadas. `CORPUS_RETENTION_DAYS=30` (`limits.env`, mínimo 30; era 180 hasta el 2026-11-07):
cada día se borran, en lotes de 20 000, los mensajes del corpus (`corpus_messages`), el estilo por usuario
(`user_corpus`) aprendidos hace más de 30 días y, con su plazo propio (`GIF_SENDER_RETENTION_DAYS=180`), el
registro de remitentes de GIF (`gif_senders`), y se invalidan las cachés de Markov afectadas. El aprendizaje
nuevo y la relectura del historial tampoco admiten mensajes con más de 30 días (`_save_message_to_corpus`). La primera
purga con el plazo de 30 días se hizo el 2026-11-07 con `scripts/corpus_retention.py` (conteos en el informe, sin contenido). No deja lápidas: es el paso normal del tiempo y, si un backup
devolviera filas vencidas, la purga siguiente las quita. Compatible con Markov: entrena con una muestra
aleatoria de ≤ 5 000 mensajes del servidor (≤ 2 000 por persona), que un servidor activo repone en días. Se
cuenta desde que Purgito aprendió el mensaje (`created_at`), no desde que se escribió en Discord. A 2026-11-06 no
hay nada vencido (lo más antiguo tiene 61 días). Convive con la cuota por canal (15 000/50 000) y la total.

### Datos administrativos: política

Qué contienen y qué se hace cuando la persona pide su eliminación (la eliminación de datos (Centro de Privacidad) o el Centro):

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
   `Privacy` (sin comandos). Tras el despliegue los comandos antiguos desaparecen del registro global de Discord.
3. Verificar: `GET /api/me/privacy` con sesión devuelve 200 y https://purgito.app/privacidad redirige al Centro.
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
