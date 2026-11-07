# Política de Privacidad (Privacy Policy)

**Última actualización:** 7 de noviembre de 2026 (versión 2.4)

Esta Política explica qué datos personales trata Purgito, para qué los usa, con quién los comparte, cuánto tiempo los conserva y cómo puedes ejercer tus derechos. Se aplica al bot de Discord y al sitio y panel de purgito.app.

El responsable del tratamiento es el titular de Purgito. Puedes escribirle a contacto@purgito.app o usar el Centro de Privacidad: https://purgito.app/privacidad.

# 1. Datos que tratamos

Los datos provienen de Discord y de lo que haces en el panel y en el Centro de Privacidad.

**Identificadores.** Purgito guarda los IDs de usuarios, servidores y canales, y el nombre visible de quien escribe, para que el bot funcione y para atender tus solicitudes.

**Mensajes.** En los canales donde un administrador activa el aprendizaje, Purgito guarda el texto de los mensajes junto con el ID y el nombre visible de su autor. Con ellos genera respuestas y mensajes espontáneos mediante cadenas de Markov, un método estadístico que se calcula en nuestro propio servidor, y puede imitar el estilo de escritura de una persona del servidor. Lo aprendido en un servidor se usa solo en ese servidor. Los mensajes no se envían a servicios de inteligencia artificial de terceros ni se usan para generar texto fuera de nuestro servidor; solo llegan a Cloudflare dentro de las copias de seguridad cifradas (ver sección 5).

Los canales NSFW quedan siempre fuera del aprendizaje; si un canal ya habilitado pasa a ser NSFW, su historial guardado se elimina de inmediato. Los administradores pueden además ignorar canales y excluir a personas concretas, y si borras un mensaje en Discord, Purgito lo retira de lo aprendido.

**GIFs e imágenes.** Purgito guarda en Cloudflare R2 los GIFs de la galería de cada servidor y las imágenes de las plantillas de anuncios y embeds. De cada GIF registra quién lo envió (usuario, canal y mensaje de origen) y cuántas veces se compartió; los administradores del servidor ven este dato en el catálogo del panel, con un enlace al mensaje y un filtro por persona. No se capturan GIFs de canales NSFW ni de canales que `@everyone` no puede ver.

**Descargas con `!dl`.** El comando descarga el video del enlace que pegas y lo sube al mismo canal. El archivo se borra del servidor de inmediato, no se guarda ni se sube a R2, y quien lo usa es responsable de tener derecho a redistribuirlo (ver los Términos del Servicio).

**Panel de administración.** Al iniciar sesión con Discord pedimos acceso a tu identidad, tu correo y la lista de tus servidores (`identify`, `email` y `guilds`), para mostrarte tu perfil y solo los servidores que administras. Una cookie de sesión mantiene tu sesión abierta; no se usa para publicidad ni para seguimiento. Tu correo de Discord solo se guarda dentro de esa cookie cifrada, no en nuestra base de datos.

Cuando un administrador cambia la configuración desde el panel, queda un registro de auditoría con su ID y nombre visible, la acción realizada y, a veces, un detalle escrito por él. Solo lo ven los administradores de ese servidor, en la pestaña Historial. Los cambios hechos con `/settings` en Discord no se registran ahí.

**Frases especiales e impulsos.** Las frases especiales conservan el ID y el nombre de quien las agregó. Los impulsos (boosts) guardan quién impulsa, el servidor y la fecha, para poder agradecerlo.

**Pagos.** Los pagos de Premium los procesa Polar.sh, que actúa como Merchant of Record y trata tu tarjeta y tus datos de facturación según su [Política de Privacidad](https://polar.sh/legal/privacy). Purgito guarda qué servidor tiene Premium, desde cuándo y con qué plan, además del ID de Discord de quien compró, los identificadores de cliente y de suscripción de Polar, su estado y fechas, y si hay una cancelación programada. Quien pagó puede verlo en `/perfil/facturacion`; nadie más del servidor. No guardamos tarjeta, datos de facturación, correo ni nombre del comprador.

**Dirección IP y registros técnicos.** purgito.app funciona detrás de Cloudflare, que ve la IP de quienes navegan. En nuestro servidor la IP se usa solo para limitar el abuso y no se guarda en la base de datos. Si se detecta actividad sospechosa, el registro de seguridad guarda un código derivado de la IP, que permite reconocer un mismo origen sin mostrarla. Los registros de acceso del servidor web guardan la ruta visitada y el navegador, pero no la IP.

**Estadísticas de uso.** Para medir el uso y la calidad del bot, el operador usa una herramienta interna que guarda recuentos por hora de funciones, comandos y resultados, sin texto de mensajes, argumentos, usuarios ni canales. Los servidores se identifican con códigos que no revelan su ID de Discord. Solo acceden operadores autorizados y los datos no se envían a servicios de analítica externos.

No solicitamos tu contraseña de Discord ni almacenamos datos de tarjetas bancarias.

# 2. Para qué usamos los datos

Usamos los datos para que el bot funcione: generar texto con cadenas de Markov, mantener la galería de GIFs, ejecutar las automatizaciones y la configuración de cada servidor, gestionar Premium y atender tus solicitudes. No vendemos datos personales ni los usamos para publicidad.

Para ello Purgito usa dos permisos privilegiados de Discord. El de contenido de mensajes sirve para aprender de los canales habilitados, activar disparadores por texto, detectar GIFs y releer el historial de un canal cuando un administrador lo pide. El de miembros del servidor sirve para los mensajes de bienvenida y despedida, detectar impulsos y buscar miembros en el panel. Sin estos permisos, las funciones que dependen de ellos dejarían de estar disponibles.

# 3. Con quién compartimos los datos

Purgito se apoya en proveedores que tratan datos solo en la medida necesaria para prestar su servicio:

- **Discord**, la plataforma en la que opera el bot y que entrega los mensajes y nombres que Purgito trata.
- **Cloudflare**, que provee la red y la protección de purgito.app, gestiona el reenvío del correo de contacto y aloja en R2 los GIFs, las imágenes y las copias de seguridad cifradas.
- **Polar.sh**, que procesa los pagos de Premium.
- **Railway**, donde se aloja Purgito Monitor, un servicio propio de vigilancia que recibe señales de estado y avisos de fallo sin identificadores de usuarios, servidores ni canales.
- **Twitch**, solo si un administrador configura avisos de transmisiones: el bot consulta datos públicos y no envía datos de las personas del servidor.

Discord, Cloudflare, Polar.sh y Railway pueden tratar datos fuera de Chile, de modo que parte de la información puede procesarse en otros países. Todavía no hemos evaluado el nivel de protección de datos de cada uno de ellos; limitamos lo que enviamos a cada proveedor a lo que necesita para su servicio.

# 4. Cuánto tiempo conservamos los datos

Los datos se conservan solo mientras son necesarios, con estos plazos:

- **Mensajes aprendidos, estilo de escritura por persona y registro de quién envió cada GIF:** hasta 180 días desde que Purgito los aprendió. Antes, si el servidor llega a su límite de mensajes (mayor con Premium), se descartan los más antiguos. La purga es diaria y alcanza también a los servidores inactivos.
- **GIFs:** si borras el mensaje original en Discord, se elimina el registro del remitente y, si nadie más lo compartió de forma independiente, también el GIF y su archivo. Al cumplirse los 180 días se elimina igualmente ese registro, pero el GIF puede seguir en la galería sin atribución hasta que un administrador lo quite.
- **Registro de auditoría y estadísticas de uso:** 90 días.
- **Frases especiales y anuncios programados:** mientras existan.
- **Registros técnicos del servidor, incluido el código derivado de la IP:** hasta 30 días. Los registros de acceso del servidor web, unos 14 días.
- **Solicitudes de derechos y de eliminación:** 90 días después de resolverse.
- **Datos de un servidor del que el bot sale:** se conservan 30 días por si el bot es invitado de nuevo y se borran después. Mientras tanto no es posible administrarlos desde el panel; si eres administrador y quieres que se eliminen antes, escríbenos.

Los administradores pueden además vaciar los mensajes aprendidos o borrar los GIFs guardados en cualquier momento con `/settings`.

# 5. Copias de seguridad y eliminación

Para poder recuperar el servicio ante una falla grave, cada día se hace una copia de seguridad de toda la base de datos, incluidos los mensajes aprendidos. La copia se cifra antes de salir del servidor y se guarda en un espacio privado de Cloudflare R2 y, además, en el propio servidor. Solo se usa para recuperar el servicio y para comprobar que puede restaurarse, y no para ninguna otra función.

Nuestro límite es que ninguna de estas copias supere los 14 días mientras el servicio funcione con normalidad. En R2 se conservan las de los últimos 7 días y las de los domingos de las dos últimas semanas, y en el servidor las dos más recientes. Una copia adicional hecha por mantenimiento puede conservarse unos días más, siempre dentro de ese límite. Si el servidor estuviera apagado o el servicio interrumpido, una copia podría superar ese plazo hasta que se reanude; se elimina con las copias siguientes.

Todavía existen algunas copias anteriores al 5 de noviembre de 2026, cifradas con una clave que se perdió: no pueden leerse ni restaurarse, y se eliminan a partir del 19 de noviembre de 2026.

Las copias hechas antes de una eliminación pueden seguir conteniendo esos datos, cifrados, hasta que caduquen. No se leen ni se restauran salvo para recuperar el servicio y, si eso ocurriera, las eliminaciones ya solicitadas se aplican de nuevo antes de volver a ponerlo en marcha.

Para ello guardamos durante 15 días un registro mínimo, sin mensajes ni otro contenido: tu ID de Discord (o el del servidor) con las fechas de la solicitud, y los IDs de los mensajes y canales eliminados. Guardamos también la lista de personas excluidas del aprendizaje, hasta que retiren la exclusión. Una copia cifrada de este registro se conserva además en el espacio privado de R2 y se elimina a los 15 días o, si el servicio estuviera interrumpido, en cuanto se reanude.

La eliminación se hace sobre la base de datos activa y los archivos en R2 mediante borrado lógico. No podemos garantizar la destrucción física inmediata de los bloques del almacenamiento; el cifrado reduce ese riesgo, pero no lo elimina.

# 6. Tus derechos y cómo ejercerlos

Puedes ejercer tus derechos de acceso, rectificación, supresión, oposición y portabilidad, y pedir el bloqueo temporal del tratamiento, desde el Centro de Privacidad (https://purgito.app/privacidad), iniciando sesión con Discord (el bot no tiene comandos para esto). Allí puedes:

- **Descargar tus datos** en un archivo JSON: mensajes aprendidos por servidor, GIFs enviados, impulsos, frases especiales, exclusiones y estado de tus solicitudes.
- **Pedir la eliminación de tus datos.** La solicitud queda registrada de inmediato y nos proponemos completarla en 7 días naturales. Es un objetivo operativo, no una garantía absoluta: si falla, se retrasa o se acerca al plazo, el sistema avisa al responsable para que intervenga; si el servicio estuviera interrumpido, se completa en cuanto se reanude. Puedes seguir su estado en la misma página.
- **Excluirte del aprendizaje y de la interacción con Purgito** en todos los servidores, incluidos tus GIFs y la relectura del historial. La exclusión no borra lo ya guardado; para eso sirve la eliminación.
- **Hacer otras solicitudes** (acceso adicional, rectificación, oposición, portabilidad, bloqueo temporal u otras consultas) con el formulario del Centro. Pedimos solo el tipo de solicitud, un comentario opcional y, si quieres la respuesta por correo, una dirección que se borra al contestar.

Cada solicitud recibe un acuse de recibo inmediato, con número y fecha, y la respuesta escrita queda disponible en el Centro. Respondemos dentro de 30 días corridos; la ley permite prorrogar ese plazo una sola vez por hasta 30 días más, algo que no prevemos hacer y que, de ser necesario, te comunicaríamos antes de que venza el primero. Las solicitudes de bloqueo temporal se responden en 2 días.

Si rechazamos una solicitud, la respuesta explica el motivo e informa que dispones de treinta días hábiles para reclamar ante la Agencia de Protección de Datos Personales, a la que también puedes acudir si no respondemos a tiempo.

La eliminación borra, en todos los servidores donde hayas escrito, tu estilo de escritura, los mensajes que Purgito aprendió de ti (incluida la copia colectiva del servidor), tu registro como remitente de GIFs (y el GIF y su archivo, si nadie más lo compartió de forma independiente), tus impulsos y tus solicitudes de derechos. Tu nombre y tu ID se quitan de las frases especiales, los anuncios programados y el registro de auditoría, que se conservan como historial del servidor con tu identificación reemplazada por `[eliminado]`. Tus mensajes originales en Discord no se ven afectados. La solicitud de eliminación, con tu ID, se conserva 90 días tras completarse para poder rendir cuentas.

Si no puedes iniciar sesión con Discord, escribe a contacto@purgito.app; te pediremos solo lo necesario para comprobar que la cuenta es tuya. Los administradores de un servidor, por su parte, pueden excluir a personas concretas de la interacción con el bot, del aprendizaje o de ambos.

La Ley N.º 21.719, sobre protección de datos personales, publicada el 13 de diciembre de 2024, entra en vigencia el 1 de diciembre de 2026; hasta entonces rige la Ley N.º 19.628. Ofrecemos estos canales desde ahora.

# 7. Seguridad

Aplicamos medidas razonables para proteger la información. La base de datos no es accesible desde Internet, el acceso de administración al servidor está restringido y se limita a lo necesario para operar el servicio, y las contraseñas y tokens se guardan fuera de la base. Las copias de seguridad se cifran antes de salir del servidor.

Los datos y los secretos del servicio viven en un volumen cifrado, que protege frente a copias del disco pero no frente a quien tenga acceso administrativo con el volumen abierto. Ningún sistema ofrece seguridad absoluta frente a incidentes o accesos no autorizados.

# 8. Menores de edad

Purgito está destinado a personas que cumplen la edad mínima que exige Discord. Si eres madre, padre o tutor y crees que Purgito guarda datos de un menor, escribe a contacto@purgito.app y lo revisaremos.

Para contratar Premium se requiere capacidad legal para contratar o la autorización de un adulto responsable. Purgito no lo verifica activamente: corresponde a quien compra.

# 9. Cambios y contacto

Podemos actualizar esta Política para reflejar nuevas funciones, cambios técnicos o cambios legales. La fecha y la versión indican siempre el texto vigente, y el historial de cambios del código es público en GitHub.

Para preguntas sobre esta Política o para pedir la eliminación de tus datos, escribe a contacto@purgito.app o usa el Centro de Privacidad. También puedes pasar por el servidor de soporte en Discord (https://discord.gg/5U7HKyxnBv), pero para asuntos sobre tus datos usa el correo o el Centro de Privacidad, no el chat público.
