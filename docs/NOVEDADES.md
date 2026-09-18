# Novedades

**Última actualización:** 18 de septiembre de 2026

Un resumen de las funciones nuevas, mejoras y arreglos de Purgito, en
lenguaje simple. El detalle técnico completo, para quien quiera leerlo,
vive en el [repositorio en GitHub](https://github.com/punkyyy01/bot-discord-purg).

# 2026

## Novedades recientes

### Nuevo
- Límites de uso visibles por servidor: mensajes aprendidos, GIFs e imágenes de memes tienen un tope, y el dashboard avisa cuando un servidor se acerca a agotarlo.
- Categoría **Frases** en `/settings`: agregar, ver y borrar frases especiales desde Discord, sin pasar por el dashboard.
- **YouTube** y **Memes automáticos** ampliados en `/settings`: ahora se pueden agregar suscripciones y activar memes automáticos directo desde el panel de Discord, no solo quitarlos.
- Botón para vaciar el corpus de un servidor desde `/settings`, con confirmación obligatoria antes de borrar.
- `/mis_datos`: descarga en un archivo todo lo que Purgito guardó de tu estilo de escritura.
- `/imitar_mezcla`: combina el estilo de dos miembros del servidor en un solo mensaje generado.
- Exportar e importar plantillas de embeds como archivo, para reutilizarlas entre servidores.
- Anuncios programados: modo semanal (elegir días de la semana y una hora fija), además de por intervalo o diario.
- Avisos de Twitch en vivo: misma idea que las notificaciones de YouTube, con mención por rol opcional.
- `!dl <link>` / `purgito dl <link>`: descarga un video de Instagram, TikTok, Twitter/X o Facebook y lo sube al canal — también funciona respondiendo a un mensaje que tiene el link, sin tener que repetirlo.
- Comandos de edición de imagen (`!deepfry`, `!caption`, `!triggered`, `!wasted`, `!wanted` y otros — lista completa en `/help`): se aplican a la imagen que subas, a la que respondas, o a tu avatar si no hay ninguna de las dos. Funcionan con `!` o `purgito` adelante, igual que `!dl`.
- `!gif`: convierte un video en GIF -- adjunto, o un link de Instagram/TikTok/Twitter-X/Facebook (propio o del mensaje que respondas), igual que `!dl`. `!gifcaption`, `!gifspeed`, `!gifreverse` y `!gifwide` editan un GIF que ya tengas (agregarle texto, cambiar la velocidad, invertirlo, estirarlo).
- Prefijo de comandos de texto personalizable por servidor (antes era fijo, `!`).
- La tab GIFs del dashboard ahora muestra quién mandó cada GIF, con una vista para ver solo los de una persona puntual.
- Tab Estadísticas ampliada: actividad de los últimos 14 días, quién alimentó más el corpus y las palabras más frecuentes.
- Rol de Gestor (tab Servidor → General): delega un rol de Discord con acceso a Anuncios, Embeds, Frases, Triggers, Reacciones, GIFs y YouTube/Twitch/RSS, sin darle Administrador ni "Gestionar servidor" completo.
- Exportar e importar el comportamiento del chat (activado, frecuencia y probabilidades) como archivo, para reutilizarlo en otro servidor.
- Aviso en el canal de actualizaciones cuando un servidor se acerca o llega al tope de GIFs o frases especiales guardadas.
- Checklist de Primeros pasos en INICIO: tres pasos (elegir canales de aprendizaje, que el servidor ya tenga algo aprendido, personalizar el estilo) que se marcan solos a medida que se cumplen, y el checklist se esconde cuando terminan.
- Página pública de Novedades (`/es/novedades`, `/en/changelog`): resume en lenguaje simple qué cambió en Purgito — enlazada desde Recursos en el menú del sitio.
- Filtro para ver solo los canales ya configurados en la matriz de canales, además de buscar por nombre.
- Deshacer al borrar una frase, un trigger o una reacción: un aviso da unos segundos para cancelar antes de borrarlo de verdad.

### Mejorado
- El scroll de la barra lateral en la Guía de Purgito ya no usa el color por defecto del navegador.
- El selector para cambiar de servidor en el dashboard ya no se ve apretado contra el borde del menú.
- Un solo buscador de módulos en el dashboard: antes había dos que hacían lo mismo, y el de la barra lateral se perdía al colapsarla.
- Espaciado más consistente entre título, descripción y contenido dentro de la tab Estadísticas.
- El mensaje de bienvenida ya no menciona memes en servidores sin Premium.
- Frases especiales y reacciones configurables dejaron de ser función Premium: disponibles en todos los servidores.
- Cuando los memes automáticos no pueden postear (sin fotos guardadas o sin suficiente conversación), Purgito avisa una vez en el canal en vez de fallar en silencio cada pocos minutos.
- CHAT y Canales avisan antes de salir si un cambio se sigue guardando o no se pudo guardar, para no perderlo sin darte cuenta.
- La matriz de canales (habla/responde/aprende) se ve como tarjetas legibles en el celular, en vez de una tabla apretada con casillas diminutas.
- La guía de Primeros pasos en INICIO se puede ocultar aunque falten pasos, y el paso sobre aprender mensajes nuevos ya no se confunde con elegir canales.
- Menos módulos redundantes en el dashboard: Personalización se edita directo desde INICIO (antes llevaba a una página aparte con lo mismo), y Prefijo de comandos + Limpieza de memoria se unieron en un solo módulo, General. El canal de novedades del bot se movió a Automatización, junto a YouTube/Twitch/RSS.
- El menú lateral del dashboard arranca con las categorías colapsadas (solo se abre la del módulo que estás viendo), para que no tenga su propio scroll separado del resto de la página.
- `/refeed_channels` tiene un cooldown de 60 segundos por servidor, para evitar relanzarlo sin querer varias veces seguidas.
- El filtro de HISTORIAL por tipo de acción suma opciones específicas para más cambios (exclusión de usuarios, prefijo de comandos, Twitch, canales de menciones, canal de novedades, frases), antes solo visibles agrupados en "Todas las acciones".
- El dashboard carga más rápido, sobre todo la primera vez que se abre en una sesión.
- `!gif` ahora también convierte una imagen (PNG, JPG o WEBP) en GIF, no solo un video -- adjunta, del mensaje que respondas, o embebida en el resultado de otro bot.

### Corregido
- El módulo YouTube del dashboard mostraba un error ("emptyState is not defined") en vez de la lista de suscripciones.
- Estadísticas mostraba todos los canales de texto como "leídos" aunque solo unos pocos estuvieran habilitados para aprender.
- En Reacciones automáticas, agregar un emoji cerraba el modal (había que reabrirlo para cada uno) y se bloqueaba seguido por exceso de solicitudes al agregar varios de una sentada.
- Un canal con mucho historial ya no le come el cupo de mensajes aprendidos a los demás canales del mismo servidor — el límite ahora es por canal.
- Mismo arreglo para `/imitar`: un miembro muy activo ya no desplaza el estilo guardado de otro miembro del servidor.
- Videos marcados como contenido sensible por Instagram, TikTok o Twitter solo se pueden subir con `!dl` en un canal marcado como NSFW.
- El paso "Elige de qué canales aprende" de Primeros pasos en INICIO ya refleja bien si sacas todos los canales de aprendizaje — antes quedaba marcado como hecho para siempre.
- Agregar una frase especial idéntica a otra que ya existe en el mismo pool ahora se rechaza, en vez de guardarla duplicada.
- Un GIF nuevo con una miniatura parecida a la de otro servidor ya no se confunde con contenido de ese servidor.
- `!dl` y `!gif` encuentran el video al responder a un mensaje de otro bot, sea que lo muestre como link de vista previa, archivo adjunto o video embebido en el mensaje (ej. el resultado de otro bot de memes) — antes `!gif` podía pedir un video igual, aunque se viera perfecto en Discord.

## Versión 1.1.0 — 28 de junio de 2026

### Nuevo
- Generación de memes con `/momo` y `/meme`, con textos generados por IA.
- Colección de imágenes para memes: reaccionar con 🎯 a una foto la guarda como plantilla.
- Memes automáticos programables por canal.
- Frases especiales configurables, con una probabilidad baja de aparecer y un tiempo mínimo entre una y otra.
- Reacciones automáticas configurables a mensajes del chat.
- Notificaciones de YouTube cuando un canal sube un video nuevo.
- Modo chat: Purgito responde automáticamente al mencionarlo o responderle.
- `/imitar @usuario`: genera un mensaje imitando el estilo de un miembro puntual.
- Mensaje de bienvenida al agregar el bot a un servidor nuevo.
- Panel de configuración `/settings`, organizado por categorías.
- `/setup`: guía paso a paso para configurar un servidor nuevo.

## Versión 1.0.0 — 1 de junio de 2026

### Nuevo
- Primera versión pública: colección de GIFs por servidor y generación de texto a partir de lo que el bot aprende del chat.
