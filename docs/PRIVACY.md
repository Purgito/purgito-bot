# Política de Privacidad (Privacy Policy)

**Última actualización:** 2 de agosto de 2026

Esta Política describe cómo **Purgito** recopila, utiliza, almacena y protege la información necesaria para ofrecer sus funcionalidades.

Purgito es un bot público de Discord, usado por múltiples servidores. Purgatory es uno de esos servidores, sin trato especial en lo que respecta a esta Política.

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

- Entrenar cadenas de Markov.
- Generar respuestas automáticas.
- Imitar el estilo de escritura de los usuarios.
- Mejorar funciones relacionadas con memes y generación de texto.

---

## Multimedia

El bot puede almacenar:

- URLs de imágenes.
- URLs de GIFs.
- Archivos multimedia necesarios para las funciones de la galería de GIFs.

Cuando corresponde, dichos archivos pueden almacenarse de forma persistente mediante Cloudflare R2.

---

## Nombre visible

El nombre visible (Display Name) del usuario puede almacenarse junto con determinados mensajes para permitir funciones como la imitación de usuarios.

---

## Inicio de sesión en el panel web

Al iniciar sesión en panel.purgito.app con Discord, se solicitan los permisos (scopes) `identify` y `email`. Esto permite mostrarte tu nombre de usuario, avatar y correo dentro de tu propia sesión, y asociar tu cuenta de Discord con los servidores que administras. Se guarda una cookie de sesión para mantenerte logueado mientras navegas el sitio; esta cookie no se usa con fines publicitarios ni de rastreo entre sitios.

---

El bot **no recopila**:

- Contraseñas.
- Correos electrónicos, salvo el que Discord entrega al iniciar sesión en el panel web (panel.purgito.app) — ese correo se usa únicamente para identificarte dentro de tu propia sesión y no se comparte con terceros.
- Direcciones IP.
- Datos personales ajenos a los proporcionados por la API oficial de Discord.

Sobre datos de pago, ver la sección **"Pagos y suscripciones"** más abajo: Purgito no los almacena, pero el procesador de pagos (Polar.sh) sí los recolecta al procesar una compra.

---

## Pagos y suscripciones

Cuando un servidor contrata premium a través del dashboard (panel.purgito.app), el pago lo procesa **Polar.sh**, no Purgito.

**Purgito almacena únicamente:**

- El ID del servidor (guild_id) que tiene premium activo.
- La fecha en que se activó.
- Una nota de texto identificando el plan (por ejemplo, "Polar — mensual" o "Polar — anual").

Purgito **no almacena** número de tarjeta, datos de facturación, email ni nombre del comprador.

**Polar.sh sí recolecta** los datos necesarios para procesar el pago (tarjeta, email, datos de facturación) bajo su propia [Política de Privacidad](https://polar.sh/legal/privacy). Esa relación de datos es entre quien compra y Polar.sh como procesador/Merchant of Record.

---

# 2. Uso de la información

La información recopilada se utiliza exclusivamente para proporcionar las funciones del bot, incluyendo:

- Generación de texto mediante cadenas de Markov.
- Generación de memes.
- Galería de GIFs.
- Reproducción de música.
- Automatizaciones del servidor.
- Configuración de comandos y preferencias.

Los datos **no se venden** ni se utilizan para publicidad.

---

# 3. Servicios de terceros

Purgito utiliza servicios externos para determinadas funciones.

Actualmente pueden utilizarse:

- **Discord** para la comunicación.
- **Cloudflare R2** para almacenamiento multimedia.
- **Groq API** para generación de memes mediante IA.
- **yt-dlp** para la obtención de contenido multimedia compatible.
- **Polar.sh** como procesador de pagos y Merchant of Record para las suscripciones premium. Ver su [Política de Privacidad](https://polar.sh/legal/privacy).
- Otros servicios estrictamente necesarios para el funcionamiento del bot.

Cada proveedor procesa únicamente la información necesaria para prestar su servicio.

---

# 4. Retención de datos

Los datos recopilados se conservan únicamente mientras sean necesarios para el funcionamiento del bot.

Los administradores del servidor pueden eliminar el contenido recopilado usando el panel interactivo de configuración (comando `/settings`), que incluye botones para vaciar el corpus de mensajes aprendidos y para borrar los GIFs guardados.

Cuando el bot abandona un servidor o el corpus es eliminado, los datos asociados dejan de utilizarse para las funciones de aprendizaje.

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
