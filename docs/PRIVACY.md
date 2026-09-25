# Política de Privacidad (Privacy Policy)

**Última actualización:** 21 de septiembre de 2026

Esta Política describe cómo **Purgito** recopila, utiliza, almacena, comparte y protege la información necesaria para ofrecer sus funcionalidades.

Purgito es un bot público de Discord, usado por múltiples servidores. Los datos que recopilamos y cómo los tratamos son los mismos para todos los servidores donde el bot está presente.

---

# 1. Información recopilada

Para funcionar correctamente, el bot puede almacenar la siguiente información:

## Información de Discord

- IDs de usuarios.
- IDs de servidores.
- IDs de canales.

Estos identificadores son utilizados únicamente para el funcionamiento interno del bot.

---

## Contenido de mensajes

Cuando las funciones de aprendizaje están habilitadas, el bot almacena el contenido de mensajes de texto enviados en canales permitidos.

Estos mensajes pueden utilizarse para:

- Entrenar cadenas de Markov locales.
- Generar respuestas automáticas en el chat.
- Imitar el estilo de escritura de los usuarios.
- Servir como muestra acotada de vocabulario en la generación de memes (localmente con Markov o mediante la integración opcional con Groq si está configurada).

Los canales marcados como **NSFW** en Discord quedan siempre fuera de este aprendizaje: Purgito nunca guarda mensajes de un canal NSFW, sin excepción ni forma de habilitarlo manualmente para el corpus. Si un canal que ya estaba habilitado para el corpus se marca como NSFW más adelante, el historial que ya se había guardado de ese canal se purga de inmediato.

---

## Multimedia

El bot puede almacenar:

- URLs de imágenes.
- URLs de GIFs.
- Archivos multimedia necesarios para las funciones de la galería de GIFs, la colección de memes y las plantillas de anuncios/embeds.

Cuando corresponde, dichos archivos pueden almacenarse de forma persistente mediante Cloudflare R2.

Para cada GIF guardado en la galería, el bot registra además quién lo mandó: ID de usuario, canal y mensaje de origen, y cuántas veces lo compartió (incluye el caso de volver a compartir un GIF que otra persona ya había guardado). El catálogo de GIFs del panel de administración, visible para los administradores del servidor, muestra este dato con link directo al mensaje original y un filtro para ver los GIFs de una persona en particular.

---

## Nombre visible

El nombre visible (Display Name) del usuario puede almacenarse junto con determinados mensajes para permitir funciones como la imitación de usuarios.

---

## Frases especiales

Cuando un administrador agrega una frase especial desde el panel (pestaña Chat → Frases), Purgito guarda el ID de Discord y el nombre visible de quien la agregó, junto con el texto de la frase. A diferencia del registro de auditoría (ver más abajo), esta atribución no tiene fecha de vencimiento: se conserva mientras la frase exista.

---

## Inicio de sesión en el panel web

Al iniciar sesión en purgito.app con Discord, se solicitan los permisos (scopes) `identify`, `email` y `guilds`. Esto permite mostrarte tu nombre de usuario, avatar y correo dentro de tu propia sesión, y asociar tu cuenta de Discord con los servidores que administras (el scope `guilds` es lo que permite saber en qué servidores tienes permisos de administración, para mostrarte solo esos en tu panel). Se guarda una cookie de sesión para mantener tu sesión iniciada mientras navegas el sitio; esta cookie no se usa con fines publicitarios ni de rastreo entre sitios.

---

## Registro de auditoría del panel

Cuando un administrador realiza un cambio de configuración desde el dashboard web (purgito.app), Purgito guarda un registro de auditoría propio de ese servidor: el ID de Discord y el nombre visible de quien hizo el cambio, qué tipo de acción fue (por ejemplo, agregar una frase especial, añadir un GIF o sacar un canal de los canales de aprendizaje) y, en algunos casos, un detalle en texto libre que puede incluir contenido escrito literalmente por quien hizo el cambio.

Este registro cubre los cambios hechos desde el dashboard web. Las acciones que un administrador ejecuta directamente desde el comando `/settings` en Discord —incluyendo los botones para vaciar el corpus completo o borrar todos los GIFs guardados (ver "Retención de datos")— se aplican de inmediato pero no quedan registradas en este historial.

Este registro es visible únicamente para los administradores de ese mismo servidor, en la pestaña Historial del panel, y existe para que la comunidad pueda ver qué cambios se hicieron y quién los hizo. Se conserva un máximo de 90 días y luego se elimina automáticamente (ver "Retención de datos").

---

El bot **no recopila**:

- Contraseñas.
- Correos electrónicos, salvo el que Discord entrega al iniciar sesión en el panel web (purgito.app) — ese correo se usa únicamente para identificarte dentro de tu propia sesión y no se comparte con terceros.
- Datos personales ajenos a los proporcionados por la API oficial de Discord.

**Direcciones IP:** el dashboard (purgito.app) procesa tu dirección IP de forma transitoria y acotada, únicamente para prevenir abuso (límites de frecuencia de solicitudes). Esa IP vive solo en memoria del proceso durante una ventana corta (segundos a minutos), nunca se guarda en la base de datos ni en ningún registro persistente, y no se comparte con terceros.

Sobre datos de pago, ver la sección **"Pagos y suscripciones"** más abajo.

---

## Pagos y suscripciones

Cuando un servidor contrata Premium a través del dashboard (purgito.app), el pago lo procesa **Polar.sh**, no Purgito.

**Purgito almacena:**

- El ID del servidor (guild_id) que tiene Premium activo, la fecha en que se activó y una nota de texto identificando el plan (por ejemplo, "Polar — mensual" o "Polar — anual").
- El ID de Discord de quien inició la compra, junto con identificadores internos de la suscripción en Polar (IDs de cliente y de suscripción) y su estado (activa, en prueba, cancelada), sus fechas de período y de prueba, y si tiene una cancelación programada. Esto permite a quien pagó ver el estado de su propia suscripción en `/perfil/facturacion` — nadie más del servidor puede ver esta información.

Purgito **no almacena** número de tarjeta, datos de facturación, ni el email o nombre del comprador.

**Polar.sh sí recolecta** los datos necesarios para procesar el pago (tarjeta, email, datos de facturación) bajo su propia [Política de Privacidad](https://polar.sh/legal/privacy). Esa relación es entre quien compra y Polar.sh, en su carácter de procesador de pagos y Merchant of Record.

---

# 2. Uso de la información

La información recopilada se utiliza exclusivamente para proporcionar las funciones del bot, incluyendo:

- Generación de texto mediante cadenas de Markov locales.
- Generación de memes y captions (de forma local o mediante la integración opcional con Groq).
- Galería de GIFs.
- Automatizaciones del servidor.
- Configuración de comandos y preferencias.

Los datos **no se venden** ni se utilizan por Purgito para publicidad.

---

# 3. Servicios de terceros

Purgito utiliza servicios externos para determinadas funciones. Cada proveedor procesa únicamente la información necesaria para prestar su servicio.

## Discord y almacenamiento

- **Discord**: Para la comunicación, recepción de eventos, autenticación y envío de mensajes en la plataforma.
- **Cloudflare R2**: Para el almacenamiento persistente de archivos multimedia (imágenes de memes del pool del servidor y GIFs subidos a la galería).

## Groq API (Captions de memes con IA)

- **Qué es y para qué se utiliza**: Groq es un proveedor externo de inferencia de modelos de inteligencia artificial (visión y lenguaje) utilizado de forma opcional y exclusiva para analizar imágenes y redactar captions en la función de memes.
- **Qué datos pueden enviarse**: La imagen utilizada para el meme (codificada en base64) y una muestra limitada del corpus del servidor (hasta un máximo de 25 mensajes cortos y 15 mensajes largos, como referencia de vocabulario y tono).
- **Cuándo interviene**: Únicamente al solicitar o ejecutarse la generación de un meme (comando `/momo`, respuesta con trigger a imagen o meme programado) y siempre que la clave `GROQ_API_KEY` haya sido configurada por el operador del bot.
- **Alcance acotado**: Groq no procesa las conversaciones habituales del chat ni recibe el corpus completo de ningún servidor. La conversación general de Purgito funciona en su totalidad de forma local.
- **Fallback local**: Si Groq no está configurado, no está disponible o falla, la generación del caption se realiza íntegramente de forma local mediante cadenas de Markov.
- **Publicidad**: Los datos transmitidos a Groq en esta función no son utilizados por Purgito con fines publicitarios ni de venta de datos.

## Twitch API (avisos de transmisiones en vivo)

- **Qué es y para qué se utiliza**: Twitch es la plataforma de streaming cuya API se consulta, de forma opcional, para avisar en un canal de Discord cuando un canal de Twitch configurado por un administrador empieza una transmisión en vivo.
- **Qué se envía**: Ninguna información de los usuarios del servidor. El bot usa credenciales propias de la aplicación (no de ningún usuario de Discord) para consultar datos públicos de Twitch, como si el canal está en vivo y el título del stream.
- **Cuándo interviene**: Únicamente si el operador del bot configuró `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET`; si no, la función queda desactivada.

## Descarga de video de redes sociales (`!dl`)

- **Qué es y para qué se utiliza**: El comando `!dl` descarga un video público de Instagram, TikTok, Twitter/X o Facebook a partir de un link que pega un usuario, y lo sube al mismo canal de Discord.
- **Qué se procesa**: Únicamente la URL pegada y el video descargado de esa URL. El archivo se guarda en un directorio temporal del proceso y se borra inmediatamente después de enviarlo al canal — no se almacena de forma persistente ni se sube a Cloudflare R2.
- **Responsabilidad**: Purgito no verifica si quien pega el link tiene derecho a redistribuir ese contenido (ver "Contenido de terceros redistribuido" en las Condiciones del Servicio).

## Pagos e infraestructura

- **Polar.sh**: Procesador de pagos y Merchant of Record para las suscripciones premium. Ver su [Política de Privacidad](https://polar.sh/legal/privacy).
- Otros servicios de infraestructura estrictamente necesarios para el funcionamiento del bot.

---

# 4. Retención de datos

Los datos recopilados se conservan únicamente mientras sean necesarios para el funcionamiento del bot.

El historial de mensajes no se guarda de forma indefinida ni siquiera mientras el servidor está activo: cada servidor tiene una cuota máxima de mensajes guardados (mayor en servidores con Premium). Al alcanzarse esa cuota, los mensajes más antiguos se descartan automáticamente a medida que se guardan mensajes nuevos, sin que un administrador tenga que hacerlo manualmente.

Los administradores del servidor pueden además eliminar el contenido recopilado en cualquier momento usando el panel interactivo de configuración (comando `/settings`), que incluye botones para vaciar el corpus de mensajes aprendidos y para borrar los GIFs guardados.

El registro de auditoría del panel (ver sección 1) se conserva un máximo de 90 días desde cada entrada y luego se purga automáticamente, sin intervención manual.

Cuando el bot abandona un servidor (por ejemplo, si es expulsado), los datos de ese servidor se conservan durante un período de gracia de 30 días antes de borrarse por completo. Esto es para que, si el bot es reinvitado dentro de ese plazo, el servidor recupere su configuración y su contenido sin necesidad de configurarlo nuevamente desde el principio. Durante ese período, mientras el bot no esté en el servidor, no es posible acceder al panel de administración para gestionar esos datos. Actualmente no existe una vía de autoservicio para acelerar este borrado a nivel de servidor antes de que se cumplan los 30 días; si eres administrador de un servidor y quieres que sus datos se eliminen antes de ese plazo, puedes solicitarlo contactando al desarrollador (ver "Contacto" más abajo).

---

## Borrado de tus propios datos (derecho al olvido individual)

Independientemente de lo anterior, cualquier usuario puede solicitar en cualquier momento que se elimine su propia información, sin depender de ser administrador de ningún servidor ni de esperar los 30 días del punto anterior.

El comando `/borrar_mis_datos`, disponible para cualquier persona en cualquier servidor donde esté Purgito, borra de forma permanente e inmediata, en **todos** los servidores donde hayas escrito:

- Tu estilo de escritura guardado para la función de imitación (`/imitar`).
- Los mensajes que Purgito aprendió de ti para generar texto.

Tus mensajes originales de Discord no se ven afectados: esto borra únicamente la copia que Purgito guardó para aprender de tu forma de escribir. Por tratarse de una acción irreversible, el comando solicita una confirmación explícita antes de ejecutar el borrado.

Este borrado está pensado específicamente para los datos de aprendizaje de mensajes descritos arriba, y no cubre automáticamente otras categorías que puedas haber generado en un servidor — por ejemplo, GIFs o imágenes que hayas aportado al pool del servidor, tu registro como remitente en el catálogo de GIFs, o tu propia aparición en el registro de auditoría del panel si eres administrador — ya que esas quedan asociadas al servidor donde se generaron, no solo a tu cuenta. Si quieres solicitar la eliminación de alguna de ellas, puedes contactar al desarrollador (ver "Contacto").

---

## Descargar tus propios datos (portabilidad)

Cualquier usuario puede además solicitar una copia de su propia información con el comando `/mis_datos`, disponible en cualquier servidor donde esté Purgito. Genera un archivo JSON con tu estilo de escritura guardado y los mensajes que Purgito aprendió de ti, agrupados por servidor, y te lo envía de forma privada. Es el complemento de solo lectura de `/borrar_mis_datos`: no borra nada.

---

# 5. Derechos de los usuarios

Cualquier usuario puede eliminar su propia información en cualquier momento usando el comando `/borrar_mis_datos`, y descargar una copia con `/mis_datos` (ver sección 4) — ambos sin necesidad de ser administrador de ningún servidor.

Los administradores del servidor además disponen de herramientas propias para controlar la recopilación de datos de su comunidad (ver sección 4), incluyendo la posibilidad de excluir a usuarios específicos: de forma independiente, pueden marcar que Purgito no interactúe con ese usuario (no le responda, reaccione ni dispare triggers) y/o que no aprenda de sus mensajes (no los use para el corpus ni para la función de imitación).

Si consideras que existe información que debería eliminarse y no está cubierta por estas herramientas de autoservicio, o tienes dudas sobre el tratamiento de los datos, puedes contactar al desarrollador.

Cuando sea técnicamente posible, se atenderán las solicitudes razonables de eliminación de información.

---

# 6. Menores de edad

Purgito está destinado a usuarios que cumplen con los requisitos mínimos de edad establecidos por Discord.

Para contratar Premium se requiere tener capacidad legal para contratar, o contar con la autorización de un adulto responsable. Purgito no verifica esto activamente; es responsabilidad de quien realiza la compra.

---

# 7. Seguridad

Se adoptan medidas razonables para proteger la información almacenada.

No obstante, ningún sistema puede garantizar una seguridad absoluta frente a incidentes o accesos no autorizados.

---

# 8. Cambios en esta Política

Esta Política podrá actualizarse para reflejar nuevas funcionalidades, mejoras técnicas o cambios legales.

La fecha de "Última actualización" indicará siempre la versión vigente.

El código de Purgito está alojado en GitHub, donde se mantiene un control de versiones público.

---

# 9. Contacto

Si tienes preguntas sobre esta Política o deseas solicitar la eliminación de información relacionada con el bot, puedes contactar al desarrollador mediante:

- Correo: contacto@purgito.app.
- Servidor oficial de Discord del proyecto (cuando esté disponible).
