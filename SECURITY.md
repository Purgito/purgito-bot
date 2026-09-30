# Política de seguridad

## Versiones soportadas

Solo la rama `main` recibe parches de seguridad.

## Reportar una vulnerabilidad

**No abras un issue público** si encontraste una vulnerabilidad de seguridad.

Repórtala abriendo una [Security Advisory privada](https://github.com/Purgito/purgito-bot/security/advisories/new) en GitHub, o contacta al administrador del proyecto ([@punkyyy01](https://github.com/punkyyy01)) por GitHub.

Incluye:

- Descripción del problema
- Pasos para reproducirlo
- Impacto potencial
- (Opcional) Sugerencia de fix

Respondemos en menos de 72 horas. Una vez corregida la vulnerabilidad, la divulgaremos en el CHANGELOG.

---

## Secretos del proyecto

Las siguientes variables de entorno son sensibles. **Nunca las expongas en logs, commits ni issues públicos.** Viven en `.env` (ignorado por git); el procedimiento para rotar cada una está en [`docs/RUNBOOK.md`](docs/RUNBOOK.md) § 3.

| Variable | Por qué es sensible |
|---|---|
| `DISCORD_TOKEN` | Token de autenticación del bot. Con él alguien puede controlar el bot completamente |
| `DISCORD_CLIENT_SECRET` | Secreto de la aplicación de Discord (login del dashboard) |
| `SESSION_SECRET` | Clave con la que se cifra la cookie de sesión del dashboard. Con ella se pueden forjar sesiones de cualquier usuario; usa al menos 32 caracteres aleatorios |
| `R2_ACCESS_KEY_ID` | Credencial de acceso a los buckets de Cloudflare R2 (imágenes, GIFs y backups; las mismas credenciales sirven para los tres) |
| `R2_SECRET_ACCESS_KEY` | Secret del token R2. Con ambas claves se puede leer, escribir y borrar todas las imágenes, los GIFs y los backups de la base (que llevan lo mismo que `bot.db`) |
| `R2_ENDPOINT_URL` | Endpoint S3 de la cuenta de R2, sin nombre de bucket (no confundir con las URLs públicas de imágenes y GIFs) |
| `POLAR_ACCESS_TOKEN` / `POLAR_WEBHOOK_SECRET` | Acceso a la cuenta de Polar y firma de sus webhooks. Con el secret de webhook se puede forjar un evento de pago y activar Premium gratis |
| `GROQ_API_KEY` | Clave de facturación de la API de Groq. Las llamadas cuestan créditos de tu cuenta |
| `TWITCH_CLIENT_SECRET` | Secreto de la aplicación de Twitch |

Las variables `R2_IMAGES_BUCKET`, `R2_IMAGES_PUBLIC_URL`, `R2_GIFS_BUCKET`, `R2_GIFS_PUBLIC_URL`, `R2_BACKUP_BUCKET`, `HOME_GUILD_ID`, `GUILD_ID`, `WEB_PORT`, `BOT_TRIGGER_NAME`, `LIFECYCLE_ANNOUNCE_CHANNEL_ID` y los límites de Markov no son secretas, pero tampoco deben exponerse innecesariamente.

El bucket de backups de R2 es **privado**: no tiene URL pública (no existe `R2_BACKUP_PUBLIC_URL`) y no se le activa la *Public Development URL*, un dominio personalizado ni CORS. Solo se lee con el token S3.

---

## Datos almacenados

Todo vive en un SQLite local (`data/bot.db`) y, para GIFs e imágenes, en un bucket de Cloudflare R2. La lista completa y lo que ve cada persona está en la [política de privacidad](docs/PRIVACY.md). Lo relevante para seguridad:

- **Mensajes:** el texto de los mensajes de los canales permitidos para aprender, con el ID y el nombre visible de quien los escribió.
- **GIFs e imágenes:** URLs, hashes y quién mandó cada GIF (ID de usuario, canal y mensaje).
- **Configuración de cada servidor:** canales, roles, prefijo, frases, triggers, anuncios, plantillas de embeds, eventos y suscripciones de YouTube, Twitch y RSS.
- **Tokens de webhook de canal** (`channel_webhooks`): permiten publicar en ese canal con la identidad de Purgito. Se guardan en texto plano dentro de `bot.db`; quien obtenga una copia de la base o de un backup puede usarlos hasta que se borre y recree el webhook desde Discord.
- **Premium:** IDs de servidor, IDs de cliente y suscripción de Polar e ID de quien compró.
- **Registro de auditoría:** quién cambió qué desde el dashboard; se conserva 90 días.

`bot.db` y los backups se crean con permisos `0600` (solo el usuario del bot). **No se cifran en disco**: si tu proveedor lo permite, activa el cifrado del volumen.

La sesión del dashboard es una cookie cifrada que incluye el token de acceso OAuth de Discord de la persona; en el servidor solo se guardan los identificadores de sesión ya cerrados.

No se almacenan contraseñas ni datos de tarjeta de pago (los procesa Polar).
