# Política de Privacidad (Privacy Policy)

**Última actualización:** 15 de agosto de 2026

Esta Política describe cómo **Purgito** recopila, utiliza, almacena y protege la información necesaria para ofrecer sus funcionalidades.

Purgito es un bot público de Discord, usado por múltiples servidores. Purgatory es uno de esos servidores: los datos que recopilamos y cómo los tratamos son los mismos que para cualquier otro servidor.

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

---

## Multimedia

El bot puede almacenar:

- URLs de imágenes.
- URLs de GIFs.
- Archivos multimedia necesarios para las funciones de la galería de GIFs y la colección de memes.

Cuando corresponde, dichos archivos pueden almacenarse de forma persistente mediante Cloudflare R2.

---

## Nombre visible

El nombre visible (Display Name) del usuario puede almacenarse junto con determinados mensajes para permitir funciones como la imitación de usuarios.

---

## Inicio de sesión en el panel web

Al iniciar sesión en purgito.app con Discord, se solicitan los permisos (scopes) `identify`, `email` y `guilds`. Esto permite mostrarte tu nombre de usuario, avatar y correo dentro de tu propia sesión, y asociar tu cuenta de Discord con los servidores que administras (el scope `guilds` es lo que permite saber en qué servidores tienes permisos de administración, para mostrarte solo esos en tu panel). Se guarda una cookie de sesión para mantenerte logueado mientras navegas el sitio; esta cookie no se usa con fines publicitarios ni de rastreo entre sitios.

---

El bot **no recopila**:

- Contraseñas.
- Correos electrónicos, salvo el que Discord entrega al iniciar sesión en el panel web (purgito.app) — ese correo se usa únicamente para identificarte dentro de tu propia sesión y no se comparte con terceros.
- Datos personales ajenos a los proporcionados por la API oficial de Discord.

**Direcciones IP:** el dashboard (purgito.app) procesa tu dirección IP de forma transitoria y acotada, únicamente para prevenir abuso (límites de frecuencia de requests). Esa IP vive solo en memoria del proceso durante una ventana corta (segundos a minutos), nunca se guarda en la base de datos ni en ningún registro persistente, y no se comparte con terceros.

Sobre datos de pago, ver la sección **"Pagos y suscripciones"** más abajo: Purgito no los almacena, pero el procesador de pagos (Polar.sh) sí los recolecta al procesar una compra.

---

## Pagos y suscripciones

Cuando un servidor contrata premium a través del dashboard (purgito.app), el pago lo procesa **Polar.sh**, no Purgito.

**Purgito almacena únicamente:**

- El ID del servidor (guild_id) que tiene premium activo.
- La fecha en que se activó.
- Una nota de texto identificando el plan (por ejemplo, "Polar — mensual" o "Polar — anual").

Purgito **no almacena** número de tarjeta, datos de facturación, email ni nombre del comprador.

**Polar.sh sí recolecta** los datos necesarios para procesar el pago (tarjeta, email, datos de facturación) bajo su propia [Política de Privacidad](https://polar.sh/legal/privacy). Esa relación de datos es entre quien compra y Polar.sh como procesador/Merchant of Record.

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
- **Alcance acotado**: Groq no procesa las conversaciones habituales del chat ni recibe el corpus completo de ningún servidor. La conversación general de Purgito funciona 100% de forma local.
- **Fallback local**: Si Groq no está configurado, no está disponible o falla, la generación del caption se realiza 100% de forma local mediante cadenas de Markov.
- **Publicidad**: Los datos transmitidos a Groq en esta función no son utilizados por Purgito con fines publicitarios ni de venta de datos.

## Pagos e infraestructura

- **Polar.sh**: Procesador de pagos y Merchant of Record para las suscripciones premium. Ver su [Política de Privacidad](https://polar.sh/legal/privacy).
- Otros servicios de infraestructura estrictamente necesarios para el funcionamiento del bot.

---

# 4. Retención de datos

Los datos recopilados se conservan únicamente mientras sean necesarios para el funcionamiento del bot.

Los administradores del servidor pueden eliminar el contenido recopilado usando el panel interactivo de configuración (comando `/settings`), que incluye botones para vaciar el corpus de mensajes aprendidos y para borrar los GIFs guardados.

Cuando el bot abandona un servidor (por ejemplo, si es expulsado), los datos de ese servidor se conservan durante un período de gracia de 30 días antes de borrarse por completo. Esto es para que, si el bot es reinvitado dentro de ese plazo, el servidor recupere su configuración y su contenido sin tener que empezar de cero. Durante ese período, mientras el bot no esté en el servidor, no hay forma de acceder al panel de administración para gestionar esos datos. Hoy no existe una vía de autoservicio para acelerar el borrado antes de que se cumplan los 30 días; si eres administrador de un servidor y quieres que tus datos se eliminen antes de ese plazo, puedes pedirlo contactando al desarrollador (ver "Contacto" más abajo).

---

# 5. Derechos de los usuarios

Los administradores del servidor disponen de herramientas para controlar la recopilación de datos.

Si consideras que existe información que debería eliminarse o tienes dudas sobre el tratamiento de los datos, puedes contactar al desarrollador.

Cuando sea técnicamente posible, se atenderán las solicitudes razonables de eliminación de información.

---

# 6. Menores de edad

Purgito está destinado a usuarios que cumplen con los requisitos mínimos de edad establecidos por Discord.

Para contratar premium se requiere tener capacidad legal para contratar, o contar con la autorización de un adulto responsable. Purgito no verifica esto activamente; es responsabilidad de quien realiza la compra.

---

# 7. Seguridad

Se adoptan medidas razonables para proteger la información almacenada.

No obstante, ningún sistema puede garantizar una seguridad absoluta frente a incidentes o accesos no autorizados.

---

# 8. Cambios en esta Política

Esta Política podrá actualizarse para reflejar nuevas funcionalidades, mejoras técnicas o cambios legales.

La fecha de "Última actualización" indicará siempre la versión vigente.

---

# 9. Contacto

Si tienes preguntas sobre esta Política o deseas solicitar la eliminación de información relacionada con el bot, puedes contactar al desarrollador mediante:

- GitHub Issues del repositorio oficial.
- Servidor oficial de Discord del proyecto (cuando corresponda).
