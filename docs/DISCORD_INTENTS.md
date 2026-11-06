# Privileged Intents: justificación para el formulario de Discord

Texto de apoyo para la solicitud (inglés al final). Se mantiene alineado con la política pública (docs/PRIVACY.md) y el código.

## Message Content Intent
Imprescindible para:
1. **Aprendizaje por servidor** (núcleo del producto): Purgito aprende de los mensajes de canales que el administrador habilita y genera texto con cadenas de Markov. Sin el contenido no hay corpus.
2. **Triggers por texto** configurados por administradores (coincidencia exacta/patrón sobre el mensaje).
3. **Detección de GIFs** compartidos (enlaces de Tenor/Giphy/CDN y adjuntos) para la galería del servidor.
4. **Relectura de historial** de un canal cuando un administrador lo pide (`refeed`).
No imprescindible (no justificamos el intent por ello): respuestas a menciones (llegan con contenido sin el intent) y `!dl` (existe como comando de barra).

## Server Members Intent
Imprescindible para: mensajes de **bienvenida y despedida** (`on_member_join/remove`), detección de un **nuevo boost** (`premium_since`) y **búsqueda de miembros** en el panel de administración. El conteo de miembros no lo requiere.

## Qué se almacena, cuánto y dónde
- Contenido de mensajes de canales habilitados (no NSFW), con `author_id`, `guild_id`, `channel_id`, `message_id` y fecha de aprendizaje. Estilo por persona para `/imitar`. Cuotas por servidor y **máximo 180 días** desde que se aprende.
- Sí se almacena fuera de Discord: PostgreSQL propio (volumen cifrado LUKS2), copias de seguridad cifradas (age) en Cloudflare R2 con **máximo 14 días**. GIFs/imágenes en R2.
- No se vende ni se usa para publicidad. No se envía contenido de mensajes a terceros para generar texto.

## Derechos y eliminación
Centro de Privacidad (https://purgito.app/privacidad, Discord OAuth2): descarga, eliminación en ≤ 7 días con registro y reintentos, exclusión global del aprendizaje, otras solicitudes de derechos (≤ 30 días), contacto alternativo contacto@purgito.app. Borrar un mensaje o editarlo en Discord lo retira de lo aprendido. Los respaldos pueden conservar datos hasta 14 días solo para recuperación ante desastres; una restauración reaplica las eliminaciones antes de arrancar (guardián + registro externo).

## Seguridad
Base de datos sin acceso desde Internet; secretos fuera de la base; volumen cifrado en reposo; backups cifrados; roles de base sin superusuario; acceso administrativo restringido.

## Cadenas de Markov y la Developer Policy (RIESGO PENDIENTE)
Purgito entrena **cadenas de Markov** (modelo estadístico de n-gramas por servidor) con contenido de mensajes. La cláusula de la Developer Policy sobre entrenar modelos de ML/IA con contenido obtenido por la API podría alcanzarlo. **Ya se consultó a Developer Support: indicaron presentar la solicitud de Privileged Intents para que evalúen el caso.** Por eso el formulario debe describirlo con transparencia (no negar el uso) y el riesgo queda abierto hasta la decisión de Discord. No se abre una consulta duplicada ni se retira Markov por iniciativa propia.

## English summary
Message Content: server-scoped learning (Markov chains), text triggers, GIF detection, channel history re-read on admin request. Server Members: welcome/goodbye messages, boost detection, member search in the admin panel. Stored: message content of enabled non-NSFW channels with author/guild/channel/message ids, at most 180 days; own PostgreSQL on an encrypted volume; age-encrypted backups in R2 for at most 14 days. Not sold, not used for ads, not sent to third parties to generate text. Self-service Privacy Center (download, deletion within 7 days, global opt-out, other rights requests within 30 days). Markov chains are disclosed transparently; Discord Developer Support asked us to submit this application so the case is evaluated.
