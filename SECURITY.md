# Política de seguridad

## Versiones soportadas

Solo la rama `main` recibe parches de seguridad.

## Reportar una vulnerabilidad

**No abras un issue público** si encontraste una vulnerabilidad de seguridad.

Reportala directamente abriendo una [Security Advisory privada](https://github.com/punkyyy01/bot-discord-purg/security/advisories/new) en GitHub, o contactando al administrador del proyecto ([@punkyyy01](https://github.com/punkyyy01)) por GitHub.

Incluí:

- Descripción del problema
- Pasos para reproducirlo
- Impacto potencial
- (Opcional) Sugerencia de fix

Respondemos en menos de 72 horas. Una vez corregida la vulnerabilidad, la divulgaremos en el CHANGELOG.

---

## Secretos del proyecto

Las siguientes variables de entorno son sensibles. **Nunca las expongas en logs, commits ni issues públicos.**

| Variable | Por qué es sensible |
|---|---|
| `DISCORD_TOKEN` | Token de autenticación del bot. Con él alguien puede controlar el bot completamente |
| `R2_ACCESS_KEY_ID` | Credencial de acceso al bucket de Cloudflare R2 |
| `R2_SECRET_ACCESS_KEY` | Secret del token R2. Con ambas claves se puede leer, escribir y borrar todos los GIFs |
| `R2_ENDPOINT_URL` | URL del endpoint privado de R2 (no confundir con la URL pública) |
| `GROQ_API_KEY` | Clave de facturación de la API de Groq. Las llamadas cuestan créditos de tu cuenta |

Las variables `R2_BUCKET_NAME`, `R2_PUBLIC_URL`, `HOME_GUILD_ID`, `GUILD_ID`, `WEB_PORT`, `BOT_TRIGGER_NAME` y los límites de Markov no son secretas, pero tampoco deben exponerse innecesariamente.

---

## Datos almacenados

Este bot almacena en SQLite local:

- Texto de mensajes para el corpus de cadenas de Markov
- URLs de GIFs y sus metadatos (autor, fecha)
- IDs de usuario de Discord asociados a GIFs
- Frases del pool especial
- Emojis de reacciones configurados por guild
- Suscripciones de YouTube por guild

No almacena contraseñas, tokens ni datos bancarios.
