# Changelog

Todos los cambios notables de este proyecto se documentan acá.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

## [Unreleased]

### Added
- Sistema de servidores premium: tabla `premium_guilds`, gestionada por el bot owner desde el panel de administración del dashboard (endpoints `/api/admin/*`). Las features restringidas (memos, pool de imágenes, frases especiales, reacciones) siguen siempre activas en PURGATORY_GUILD_ID hardcodeado; para otros servidores se controla desde la tabla. `HOME_GUILD_ID` se migra automáticamente a la tabla en el primer arranque.
- Limpieza diferida de datos al salir de un servidor: `on_guild_remove` registra la salida en `guild_departures`; task diaria purga datos (DB + R2) después de `GUILD_DATA_RETENTION_DAYS` (default 30). Reinvitar al bot dentro del período cancela el borrado.
- Límites de almacenamiento por servidor: `MAX_CORPUS_MESSAGES_PER_GUILD_FREE/PREMIUM`
  (15k/50k, **por canal**, no por guild — un canal con mucho historial no
  desplaza el corpus de otros canales del mismo servidor), `MAX_USER_CORPUS_MESSAGES_PER_GUILD_FREE/PREMIUM`
  (2k/8k, **por autor**, no por guild — mismo motivo que el de arriba), `MAX_GIFS_PER_GUILD` (300), `MAX_IMAGES_PER_GUILD` (200) — eviction del registro más viejo al insertar uno nuevo, con limpieza de R2 cuando aplica.
- Límite de tamaño de GIF antes de subir a R2: `MAX_GIF_DOWNLOAD_BYTES` (8MB default); GIFs más grandes se descartan silenciosamente sin guardar la URL en la DB.
- Mensaje de bienvenida en `on_guild_join` adaptado: servidores no-premium no ven referencias a `/momo`, 🎯 ni memes. `/help` marca con ⭐ las funciones premium.
- Categoría **Frases** en `/settings`: agregar, listar y borrar frases especiales desde el panel (antes solo por comando).
- Categoría **YouTube** ampliada en `/settings`: ahora permite agregar suscripciones y configurar el rol de mención directo desde el panel, no solo remover.
- Categoría **Memes** ampliada en `/settings`: ahora permite activar memes automáticos en un canal desde el panel (antes solo remover).
- Categoría **Corpus** ampliada en `/settings`: botón para vaciar el corpus del servidor, con confirmación obligatoria (escribir el nombre exacto del servidor) antes de borrar.

### Changed
- `is_home_guild()` renombrado a `is_premium_guild()` y ahora consulta un `set` en memoria cargado al arrancar (sin hit a DB por evento/comando).
- `HOME_GUILD_ID` marcada como deprecada en `.env.example` — se sigue leyendo una vez para migrar, luego no tiene efecto en runtime.
- Frases especiales (`/añadir_frase`, `/ver_frases`, `/borrar_frase`) y pool de reacciones (`/reacciones add|quitar|lista`) liberados del gate premium; ahora disponibles en todos los servidores.

### Removed
- `/chatmode`, `/corpus_ignorar` (`add`, `quitar`, `lista`), `/reacciones` (`add`, `quitar`, `lista`), `/youtube_add`, `/youtube_remove`, `/youtube_list`, `/youtube_set_mention`, `/meme_auto` (`activar`, `desactivar`, `lista`), `/añadir_frase`, `/ver_frases`, `/borrar_frase` y `/corpus_wipe` — reemplazados por completo por las categorías correspondientes del panel `/settings`. Total de slash commands: 43 → 25.

### Fixed
- El bot ya no responde `"..."` cuando todavía no tiene mensajes suficientes del servidor (el estado de cualquier servidor recién agregado): al mencionarlo/responderle o al usar `/generar` ahora explica en lenguaje simple que necesita aprender del historial y sugiere `/refeed_all` o `/setup`. En menciones, las instrucciones completas salen a lo sumo una vez cada 15 min por servidor (después responde una versión corta). Texto nuevo integrado a i18n (es/en).
- Pérdida de mensajes en el backfill de corpus (`/refeed`, `/refeed_all`): el trim de `corpus_messages` era FIFO global por servidor (ordenado por id de inserción), así que backfillear un canal podía desplazar el historial ya guardado de otro canal del mismo servidor. Ahora el trim y el límite (`MAX_CORPUS_MESSAGES_PER_GUILD_FREE/PREMIUM`) son por canal. De paso: `_refeed_channel` reintenta con backoff ante `discord.HTTPException`/`discord.RateLimited` en vez de abortar el canal a medias, conserva el progreso para retomar en la próxima corrida, y loguea fetched/saved/discarded por corrida para auditar la tasa de filtrado.
- Mismo bug en `user_corpus` (alimenta `/imitar`): el trim también era FIFO global por servidor, así que un autor muy activo podía desplazar el historial de otro autor menos activo del mismo servidor. Ahora el trim y el límite (`MAX_USER_CORPUS_MESSAGES_PER_GUILD_FREE/PREMIUM`, bajado de 5k/20k a 2k/8k al pasar de "total del guild" a "por autor") son por autor.

## [1.1.0] — 2026-06-28

### Added
- Generación de memes con `/momo` y `/meme` (Pillow + fuente Impact)
- Captions inteligentes con Groq (llama-4-scout) con fallback a Markov
- Pool de imágenes para memes: reacción 🎯 para guardar plantillas en R2
- Memes automáticos en canales configurables (`/meme_auto activar/desactivar/lista`)
- Pool de frases especiales (`/añadir_frase`, `/ver_frases`, `/borrar_frase`) con 5% de probabilidad y cooldown de 40 min
- Pool de reacciones configurables (`/reacciones add/quitar/lista`) — el bot reacciona al 5% de los mensajes
- Notificaciones de YouTube por RSS cada 15 min (`/youtube_add`, `/youtube_remove`, `/youtube_list`, `/youtube_set_mention`)
- Modo chat: auto-reply cuando mencionan al bot o le hacen reply (`/chatmode on/off`)
- Canales ignorados para el corpus (`/corpus_ignorar add/quitar/lista`)
- Imitación de usuarios individuales con `/imitar @usuario` (corpus por usuario)
- Embed de bienvenida al unirse a un servidor nuevo
- Trigger rápido por texto plano: reply a imagen + `<trigger> generar`
- Panel de configuración `/settings` por categorías
- Onboarding guiado con `/setup` para servidores nuevos

### Changed
- Motor Markov reemplazado por implementación propia (`SimpleMarkov`) sin dependencia de markovify en runtime
- Caché Markov se invalida automáticamente cada 50 inserciones

## [1.0.0] — 2026-06-01

### Added
- Bot base con discord.py y comandos slash
- Sistema de GIFs con almacenamiento en Cloudflare R2 y SQLite
- Galería pública de GIFs en https://gifs.purg4t0ry.com (aiohttp)
- Generación de texto con cadenas de Markov entrenadas en el corpus del servidor
- Reproducción de música con yt-dlp y FFmpeg
- Restricción de comandos al servidor home (PURG4TORY)
- Rate limiting por guild para respuestas especiales
- Clasificación de URLs de GIF: R2, Discord CDN, Giphy, Tenor (embeds)
- Reverse proxy con nginx + Cloudflare (SSL gratuito)

[Unreleased]: https://github.com/punkyyy01/bot-discord-purg/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/punkyyy01/bot-discord-purg/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/punkyyy01/bot-discord-purg/releases/tag/v1.0.0
