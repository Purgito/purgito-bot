# Política de Privacidad (Privacy Policy)

**Última actualización:** 6 de noviembre de 2026 (versión 2.1)

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

Los canales marcados como **NSFW** en Discord quedan siempre fuera de este aprendizaje: Purgito nunca guarda mensajes de un canal NSFW, sin excepción ni forma de habilitarlo manualmente para el corpus. Si un canal que ya estaba habilitado para el corpus se marca como NSFW más adelante, el historial que ya se había guardado de ese canal se purga de inmediato.

---

## Multimedia

El bot puede almacenar:

- URLs de imágenes.
- URLs de GIFs.
- Archivos multimedia necesarios para las funciones de la galería de GIFs y las plantillas de anuncios/embeds.

Cuando corresponde, dichos archivos pueden almacenarse de forma persistente mediante Cloudflare R2.

Para cada GIF guardado en la galería, el bot registra además quién lo mandó: ID de usuario, canal y mensaje de origen, y cuántas veces lo compartió (incluye el caso de volver a compartir un GIF que otra persona ya había guardado). El catálogo de GIFs del panel de administración, visible para los administradores del servidor, muestra este dato con link directo al mensaje original y un filtro para ver los GIFs de una persona en particular.

---

## Nombre visible

El nombre visible (Display Name) del usuario puede almacenarse junto con determinados mensajes para permitir funciones como la imitación de usuarios.

---

## Impulsos (boosts) del servidor

Para agradecer un impulso y no repetir el aviso, Purgito guarda el ID de quien impulsa un servidor, el ID del servidor y la fecha desde la que impulsa. Se usa solo para esa función, se incluye en la descarga de tus datos y se elimina cuando solicitas la eliminación.

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

Cuando una persona pide la eliminación de sus datos (desde el Centro de Privacidad), este registro **no se borra**, porque es el historial del servidor: se quita quién fue. Su ID y su nombre se reemplazan por `[eliminado]` en las entradas donde actuó, y su ID desaparece del detalle de las entradas que la mencionan. Lo mismo ocurre con las frases especiales y los anuncios programados que creó: se quedan en el servidor, sin su nombre. Su copia de datos incluye estas entradas, con los identificadores de otras personas ocultos.

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

## Analítica agregada de producto (opcional)

El operador puede habilitar Purgito Studio para medir uso y calidad del bot.
Este módulo guarda conteos horarios por función, comando registrado, resultado
y versión, inventarios de instalación y movimientos observados. Para distinguir
comunidades y medir cohortes usa claves HMAC de servidor, sin exponer el ID de
Discord en el panel. Estas claves son pseudónimos, no identificadores de personas.
No recopila texto, argumentos de comandos, IDs de usuarios ni canales.

Los datos nuevos de Studio se mantienen en el PostgreSQL del bot y no se envían
a servicios de analítica externos. Solo operadores autorizados acceden al panel
privado. La retención es de 90 días por defecto (configurable entre 7 y 365), con
limpieza diaria mientras el colector está activo; los backups mantienen su
política propia. Estas condiciones se refieren a Studio: las demás funcionalidades
e integraciones del bot siguen las secciones anteriores.

---

# 2. Uso de la información

La información recopilada se utiliza exclusivamente para proporcionar las funciones del bot, incluyendo:

- Generación de texto mediante cadenas de Markov locales.
- Galería de GIFs.
- Automatizaciones del servidor.
- Configuración de comandos y preferencias.

Los datos **no se venden** ni se utilizan por Purgito para publicidad.

---

## Aprendizaje a partir de mensajes (cadenas de Markov)

Purgito genera texto con **cadenas de Markov**, un método estadístico simple (secuencias de palabras) calculado en el propio servidor de Purgito sobre una muestra de los mensajes aprendidos **de cada servidor por separado**. No usa servicios de inteligencia artificial de terceros ni envía el contenido de los mensajes a ningún tercero para generar texto (la integración con Groq y los memes automáticos se retiraron). Los modelos se reconstruyen en memoria a partir de lo guardado y se descartan cuando los datos se eliminan. Si no quieres que Purgito aprenda de tus mensajes, puedes excluirte desde el Centro de Privacidad.

## Permisos privilegiados de Discord que usa Purgito

- **Message Content (contenido de mensajes):** necesario para aprender de los mensajes de los canales habilitados (corpus y estilo para la imitación), para activar *triggers* por texto, para detectar los GIFs que se comparten y para releer el historial de un canal cuando un administrador lo pide. Los canales NSFW y los canales que `@everyone` no puede ver quedan fuera de la captura de GIFs; los NSFW, además, fuera del aprendizaje.
- **Server Members (miembros del servidor):** necesario para los mensajes de bienvenida y despedida, para detectar un nuevo impulso (boost) del servidor y para buscar miembros en el panel de administración.

Si Discord no concediera alguno de estos permisos, las funciones que dependen de él dejarían de estar disponibles.

---

# 3. Servicios de terceros

Purgito utiliza servicios externos para determinadas funciones. Cada proveedor procesa únicamente la información necesaria para prestar su servicio.

## Discord y almacenamiento

- **Discord**: Para la comunicación, recepción de eventos, autenticación y envío de mensajes en la plataforma.
- **Cloudflare R2**: Para el almacenamiento persistente de archivos multimedia (GIFs subidos a la galería e imágenes subidas desde el editor de embeds) y, en un espacio privado aparte, de las copias de seguridad cifradas descritas en la sección 4.

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

## Fuente de los datos y proveedores fuera de Chile

Los datos que Purgito guarda provienen de Discord (los mensajes, identificadores y nombres visibles que Discord entrega a Purgito en los servidores donde está) y de lo que las personas hacen en el panel o en el Centro de Privacidad. Los proveedores descritos en esta sección (Cloudflare, Polar.sh y Discord) pueden tratar datos fuera de Chile.

---

# 4. Retención de datos

Los datos recopilados se conservan únicamente mientras sean necesarios para el funcionamiento del bot.

El historial de mensajes no se guarda de forma indefinida ni siquiera mientras el servidor está activo: cada servidor tiene una cuota máxima de mensajes guardados (mayor en servidores con Premium). Al alcanzarse esa cuota, los mensajes más antiguos se descartan automáticamente a medida que se guardan mensajes nuevos, sin que un administrador tenga que hacerlo manualmente.

Además de la cuota, hay un **plazo máximo de 180 días**: los mensajes aprendidos (el corpus del servidor, el estilo guardado de cada persona para `/imitar` y el registro de quién envió cada GIF) se eliminan automáticamente cuando pasan 180 días desde que Purgito los aprendió, aunque la cuota no se haya alcanzado. La purga corre a diario, no depende de ningún administrador y se aplica también a los servidores inactivos. Ese plazo está pensado para no perjudicar el funcionamiento: Purgito genera texto con una muestra aleatoria de como máximo 5 000 mensajes del servidor (2 000 por persona), de modo que un servidor activo repone ese material mucho antes de seis meses y uno inactivo solo pierde lo que ya no refleja cómo conversa.

Los administradores del servidor pueden además eliminar el contenido recopilado en cualquier momento usando el panel interactivo de configuración (comando `/settings`), que incluye botones para vaciar el corpus de mensajes aprendidos y para borrar los GIFs guardados.

Los **GIFs** guardados en la galería llevan asociado quién los envió (usuario, servidor, canal y mensaje) para poder retirarlos. Si borras el mensaje en Discord, ese registro se elimina y, si nadie más compartió ese mismo GIF de forma independiente, el GIF se quita de la colección y su archivo se elimina de nuestro almacenamiento (Cloudflare R2). Si otras personas lo compartieron, el archivo se conserva mientras exista alguna referencia independiente. Al cumplirse los 180 días se elimina el registro de quién lo envió; el GIF puede seguir en la galería del servidor sin esa atribución hasta que un administrador lo quite.

El registro de auditoría del panel (ver sección 1) se conserva un máximo de 90 días desde cada entrada y luego se purga automáticamente, sin intervención manual.

Cuando el bot abandona un servidor (por ejemplo, si es expulsado), los datos de ese servidor se conservan durante un período de gracia de 30 días antes de borrarse de la base de datos activa (las copias de seguridad caducan aparte, ver más abajo). Esto es para que, si el bot es reinvitado dentro de ese plazo, el servidor recupere su configuración y su contenido sin necesidad de configurarlo nuevamente desde el principio. Durante ese período, mientras el bot no esté en el servidor, no es posible acceder al panel de administración para gestionar esos datos. Actualmente no existe una vía de autoservicio para acelerar este borrado a nivel de servidor antes de que se cumplan los 30 días; si eres administrador de un servidor y quieres que sus datos se eliminen antes de ese plazo, puedes solicitarlo contactando al desarrollador (ver "Contacto" más abajo).

---

## Dónde se guardan los datos y copias de seguridad

Toda la información que Purgito guarda (configuración de cada servidor, mensajes aprendidos, registro de auditoría, etc.) vive en una base de datos PostgreSQL en el servidor donde corre el bot. La base de datos solo acepta conexiones desde ese mismo servidor; no está expuesta a Internet. Los datos de la base y los secretos del servicio se guardan en un volumen cifrado (LUKS2). Las imágenes y los GIFs viven en Cloudflare R2.

Para poder recuperar el servicio ante una falla grave, cada día se hace una copia de seguridad de toda la base de datos. Esa copia contiene lo mismo que la base activa, incluidos los mensajes que Purgito aprendió. Se cifra con age antes de salir del servidor y se guarda en un espacio privado de Cloudflare R2 (sin acceso público), además de una copia cifrada en el propio servidor. **En R2 se conservan las copias de los últimos 7 días y las de los 2 últimos domingos; en el servidor, solo las 2 más recientes. Ninguna copia llega a los 14 días: cada una se elimina automáticamente antes de cumplirlos.** No existen otras copias de la base con una retención mayor: el disco de Purgito está excluido de las copias automáticas del equipo anfitrión. Para comprobar que una copia se puede restaurar, el responsable del proyecto la descarga a un equipo propio, la restaura en una base aislada y la borra al terminar. Solo se usan para recuperar el servicio después de un desastre y para esa comprobación; no se consultan ni se usan para aprendizaje ni para ninguna otra función.

---

## Centro de Privacidad: gestiona tus datos

Toda la gestión de tus datos personales se hace desde **https://purgito.app/privacidad**, iniciando sesión con Discord. No hay comandos de Discord para esto. Purgito solo actúa sobre la persona que inició sesión: la identidad sale de la sesión, nunca de un dato que envíe el navegador. Desde ahí puedes:

- **Descargar tus datos:** un archivo JSON con tus mensajes aprendidos por servidor, los GIFs que enviaste, tus boosts, las frases especiales a tu nombre, tus exclusiones y el estado de tus solicitudes.
- **Solicitar la eliminación de tus datos.** La solicitud queda registrada de inmediato y se completa en un plazo máximo de **7 días naturales**; si un intento falla, se reintenta hasta completarla, y puedes consultar su estado en la misma página.
- **Activar o quitar la exclusión global:** desde ese momento Purgito deja de aprender de tus mensajes y de interactuar contigo en **todos** los servidores (tampoco guarda tus GIFs ni al releer el historial). La exclusión no borra lo que ya estaba guardado; para eso sirve la eliminación.
- **Hacer otras solicitudes de derechos** (acceso a la información que tenemos de ti más allá de la descarga, rectificación, oposición, portabilidad, bloqueo temporal del tratamiento u otra consulta) con el formulario del mismo Centro. Pedimos solo el tipo de solicitud, un comentario opcional breve y, si quieres recibir también la respuesta por correo, una dirección que se borra al contestar. Recibes un **acuse de recibo** al instante (número y fecha) y la **respuesta por escrito** queda disponible en el Centro. Respondemos en un máximo de **30 días corridos** (la ley permite prorrogar el plazo una sola vez por hasta 30 días corridos más; Purgito no prevé usarlo y, si tuviera que hacerlo, te lo comunicaría antes de que venza el primer plazo). Las solicitudes de **bloqueo temporal** se responden en 2 días. Si denegamos una solicitud, la respuesta explica el motivo y te informa que dispones de treinta días hábiles para reclamar ante la Agencia de Protección de Datos Personales.
- Si **no puedes iniciar sesión con Discord**, escribe a contacto@purgito.app; te pediremos únicamente lo necesario para comprobar que la cuenta es tuya.

**Qué elimina la solicitud de eliminación**, en la base de datos activa y en **todos** los servidores donde hayas escrito: tu estilo de escritura guardado para la función de imitación; los mensajes que Purgito aprendió de ti (incluida la copia colectiva del servidor, que lleva el ID de su autor); tu registro como remitente de GIFs y, si nadie más compartió ese GIF de forma independiente, el GIF y su archivo en R2; tus boosts; y tus solicitudes de derechos. Tu nombre y tu ID se quitan de las frases especiales, los anuncios programados y el registro de auditoría del panel (ver sección 1), que se conservan porque son historial del servidor. Tus mensajes originales de Discord no se ven afectados: esto borra únicamente lo que Purgito guardó.

La solicitud, con tu ID, se conserva 90 días tras completarse para poder rendir cuentas y luego se elimina. El registro verificable de sus pasos no contiene tu identificador ni contenido.

**Límite real del borrado: las copias de seguridad.** Las copias que ya se habían hecho antes de tu eliminación pueden seguir conteniendo esos datos, cifrados, hasta que caduquen (máximo 14 días, ver arriba). No se leen ni se restauran, salvo que haya que recuperar el servicio tras un desastre; si eso ocurriera, la eliminación se vuelve a aplicar antes de volver a poner el bot en marcha. Para poder hacerlo se guarda una **lápida**: únicamente tu ID de usuario de Discord y dos fechas (cuándo pediste la eliminación y cuándo caduca la lápida), sin contenido ni servidores. La lápida dura 15 días (los 14 de las copias más uno de margen) y se elimina sola. Lo mismo ocurre cuando Purgito sale de un servidor y, pasados los 30 días de gracia, borra todos sus datos: se guarda el ID del servidor y dos fechas durante 15 días. Para que este registro no se pierda si se pierde el servidor, cada 5 minutos se guarda en el mismo espacio privado de R2 una copia cifrada con esas lápidas vigentes y la lista de personas excluidas del aprendizaje (IDs y fechas, sin mensajes); cada copia se elimina a los 15 días como máximo, y una exclusión se conserva mientras la persona no la quite.

Lo mismo vale para los mensajes que borras en Discord y para los canales que se eliminan o pasan a ser NSFW: Purgito los retira de lo que aprendió (también los GIFs asociados) y, si alguna vez hiciera falta restaurar una copia, esa retirada se vuelve a aplicar (se conserva solo el identificador del mensaje, sin contenido, durante 15 días).

**Lo que no prometemos.** La eliminación opera sobre la base de datos activa y sobre los archivos en R2 mediante borrado lógico; no podemos garantizar la destrucción física inmediata de los bloques en el almacenamiento subyacente. El cifrado de los volúmenes y de las copias reduce ese riesgo, pero no lo elimina.

---

# 5. Derechos de los usuarios

Puedes ejercer tus derechos sobre tus datos personales —acceso, rectificación, supresión (eliminación), oposición y portabilidad, y solicitar el bloqueo temporal del tratamiento— desde el Centro de Privacidad (**https://purgito.app/privacidad**) o, si no puedes iniciar sesión con Discord, escribiendo a contacto@purgito.app (ver sección 4). Acusamos recibo de cada solicitud y respondemos por escrito dentro de los plazos de la sección 4. Si rechazamos una solicitud o no la respondemos a tiempo, puedes reclamar ante la Agencia de Protección de Datos Personales.

La Ley N.º 21.719 sobre protección de datos personales de Chile (publicada el 13 de diciembre de 2024) reconoce estos derechos y, según su disposición transitoria primera, su régimen entra en vigencia el 1 de diciembre de 2026. Purgito ofrece estos canales desde ya. Esta política describe prácticas actuales y no es asesoría legal.

Los administradores del servidor además disponen de herramientas propias para controlar la recopilación de datos de su comunidad (ver sección 4), incluyendo la posibilidad de excluir a usuarios específicos: de forma independiente, pueden marcar que Purgito no interactúe con ese usuario (no le responda, reaccione ni dispare triggers) y/o que no aprenda de sus mensajes (no los use para el corpus ni para la función de imitación).

---

# 6. Menores de edad

Purgito está destinado a usuarios que cumplen con los requisitos mínimos de edad establecidos por Discord.

Para contratar Premium se requiere tener capacidad legal para contratar, o contar con la autorización de un adulto responsable. Purgito no verifica esto activamente; es responsabilidad de quien realiza la compra.

---

# 7. Seguridad

Se adoptan medidas razonables para proteger la información almacenada: la base de datos no es accesible desde Internet, el acceso de administración al servidor está restringido, las copias de seguridad se cifran antes de salir del servidor y las contraseñas y tokens se guardan fuera de la base de datos.

El volumen donde viven la base de datos y los secretos está cifrado en reposo (LUKS2), lo que protege copias del disco; no protege frente a quien tenga acceso administrativo al servidor con el volumen abierto. El acceso a los datos de las personas está limitado a la operación del servicio. Ningún sistema puede garantizar una seguridad absoluta frente a incidentes o accesos no autorizados.

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
