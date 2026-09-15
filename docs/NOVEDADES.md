# Novedades

**Última actualización:** 15 de septiembre de 2026

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
- `!dl <link>` / `purgito dl <link>`: descarga un video de Instagram, TikTok o Twitter/X y lo sube al canal.
- Prefijo de comandos de texto personalizable por servidor (antes era fijo, `!`).
- La tab GIFs del dashboard ahora muestra quién mandó cada GIF, con una vista para ver solo los de una persona puntual.
- Tab Estadísticas ampliada: actividad de los últimos 14 días, quién alimentó más el corpus y las palabras más frecuentes.

### Mejorado
- El mensaje de bienvenida ya no menciona memes en servidores sin Premium.
- Frases especiales y reacciones configurables dejaron de ser función Premium: disponibles en todos los servidores.
- Cuando los memes automáticos no pueden postear (sin fotos guardadas o sin suficiente conversación), Purgito avisa una vez en el canal en vez de fallar en silencio cada pocos minutos.

### Corregido
- Un canal con mucho historial ya no le come el cupo de mensajes aprendidos a los demás canales del mismo servidor — el límite ahora es por canal.
- Mismo arreglo para `/imitar`: un miembro muy activo ya no desplaza el estilo guardado de otro miembro del servidor.
- Videos marcados como contenido sensible por Instagram, TikTok o Twitter solo se pueden subir con `!dl` en un canal marcado como NSFW.

## Versión 1.1.0 — 28 de junio de 2026

### Nuevo
- Generación de memes con `/momo` y `/meme`, con textos generados por IA y respaldo automático si no hay conexión.
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
