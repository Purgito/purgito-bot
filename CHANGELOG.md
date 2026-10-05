# Changelog

Todos los cambios notables de este proyecto se documentan acá.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

Este archivo es el registro **técnico** (infraestructura, esquema, seguridad,
dependencias) para quien desarrolla o despliega. Lo que le importa a quien administra
un servidor de Discord, en lenguaje simple, vive en `docs/NOVEDADES.md`
(`/es/novedades`); ver CLAUDE.md § "CHANGELOG vs NOVEDADES".

## [Unreleased]

### Added
- Capa de observabilidad del nodo (`src/observability/`, ver `docs/OBSERVABILITY.md`, `docs/SECURITY_EVENTS.md`, `docs/RUNBOOKS.md`): eventos estructurados con schema v1 (`data/events.jsonl` y `data/security.jsonl`, 5 MB × 4 cada uno), redacción de secretos en logs de texto y JSON, request ids (`X-Request-ID`), heartbeat y estado del servicio sin PostgreSQL (`data/service_state.json`), `/health/ready`, y `/health/details`, `/metrics` (Prometheus) e `/internal/alerts` protegidos por `OBSERVABILITY_TOKEN` (nginx solo publica `/health`). Reglas de detección declarativas y modelo de alertas (`data/alerts.json`); solo detectan, no actúan.
- Monitor externo opcional (`src/observability/monitor.py`, `MONITOR_*`): heartbeat y eventos importantes hacia `purgito-monitor` (Railway) firmados con HMAC-SHA256, best-effort con backoff y outbox acotado para eventos críticos; `/health` ahora devuelve `{"ok": true, "status": "ok"}` con `Cache-Control: no-store`. Métricas `purgito_monitor_*`.
- `deploy/runbooks/purgito_runbooks.py`: runbooks allowlisted (diagnóstico de solo lectura + `restart_purgito` con confirmación), sin shell, con timeout y salida JSON.
- `deploy/vector/vector.toml`: configuración del collector local → destino externo (validada con Vector 0.58.0; no instalado).
- Dependencia nueva: `prometheus-client==0.25.0` (Apache-2.0 AND BSD-2-Clause). Variables nuevas: `OBSERVABILITY_TOKEN`, `PURGITO_ENV`.

### Changed
- Base de datos: SQLite → PostgreSQL 18 (asyncpg vía `src/pgdb.py`, esquema en `src/schema_pg.sql`), cutover del 2026-10-01. Guía en `docs/POSTGRES.md`. `data/bot.db` y su copia pre-cutover se conservan solo como rollback hasta el 2026-10-15.
- R2: tres buckets con rol fijo (imágenes, GIFs, backups privado). El bucket único anterior se eliminó el 2026-10-02 sin migrar contenido histórico.
- Backups: `deploy/backup_db.sh` hace `pg_dump -Fc`, verifica con `pg_restore --list`, cifra con age y sube a R2 (se conservan los 2 más recientes). Cron semanal (domingos 03:17 UTC); primer disparo automático pendiente de verificar.
- Hardening del servidor: UFW, SSH solo por clave, PostgreSQL solo en loopback y unit de systemd endurecido (`deploy/harden_*.sh`, `deploy/security_check.sh`).
- CI: tests y scripts de deploy corren sobre Python 3.14 + PostgreSQL 18 (el stack de producción), con 3.12 + PostgreSQL 16 como piso de compatibilidad en `tests`; el cliente `pg_dump` 18 se instala desde PGDG.
- Documentación: se retiró lo ya ejecutado (migración a 3 buckets, rollback de SQLite, usuario dedicado, `railway.json`) y se pasó a `docs/historico/` lo que solo sirve de contexto.

### Fixed
- Limpieza de referencias al bucket R2 eliminado (2026-10-02): 596 filas de `corpus_gifs` sin archivo recuperable, 510 filas con URL de Tenor/Giphy que conservan la URL pero pierden `media_url`/`content_hash`, 1064 filas de `gif_objects` sin objeto, 46 de `embed_uploaded_images` y avatar/banner de `guild_bot_style`. Las filas de `gif_objects` huérfanas hacían que la deduplicación por `content_hash` no re-subiera un GIF repetido, dejando URLs del bucket nuevo apuntando a un objeto inexistente. Queda 1 plantilla de embed (`embed_templates`) con URLs del host viejo, a propósito (contenido de un admin).
- Se retiró `railway.json` (no era el despliegue de producción) y el directorio vacío `data/tts_cache` (feature TTS eliminada).

### Security
- `!dl`: si el sitio de origen (Instagram, TikTok, Twitter/X o Facebook) marca el video como contenido sensible (`age_limit` de yt-dlp), ahora solo se sube en canales NSFW — antes se subía igual a cualquier canal, sin ningún filtro.
- Race condition en `release_gif_reference` (`db.py`): si mientras se liberaba la última referencia a un GIF alguien volvía a compartir el mismo contenido antes de que el borrado físico en R2 terminara, la referencia nueva podía quedar apuntando a un objeto recién borrado. El borrado de la fila de `gif_objects` ahora se confirma en una segunda pasada atómica justo antes de tocar R2, así que una referencia revivida a tiempo cancela el borrado físico.
- Bloqueo de aprendizaje NSFW: además del gate ya existente en el mensaje en vivo, `/refeed` y la migración de canales, `on_ready` ahora corre `sanitize_nsfw_corpus_channels` en cada arranque — re-valida toda la allowlist del corpus contra el estado NSFW en vivo de Discord, para cubrir el caso de que un canal haya pasado a NSFW mientras el bot estaba desconectado (`on_guild_channel_update` nunca se disparó).
- Rate limit genérico para los endpoints de escritura de `@guild_api` (POST/PUT/PATCH/DELETE), por usuario de sesión: de los ~80 endpoints bajo ese decorador, la mayoría no tenía ningún límite propio.
- `/api/server/{guild_id}/premium` ahora expone `payment_issue` (true cuando la suscripción del guild está en `past_due`), para que cualquier admin vea que el pago está fallando antes de que Premium desaparezca de golpe cuando Polar termine de reintentar.

### Fixed
- Memes automáticos: cuando `auto_meme_task` salta un canal por no tener imágenes en la colección o por corpus vacío, ahora avisa una vez en el canal configurado en vez de saltearlo en silencio cada 10 minutos para siempre. El aviso no se repite mientras el motivo siga siendo el mismo (`meme_schedule.last_error`), y se limpia solo en cuanto el canal vuelve a postear con éxito.

### Added
- `!dl`: respaldo opcional con [cobalt](https://github.com/imputnet/cobalt). Si yt-dlp no logra bajar un link y hay una instancia propia configurada (`COBALT_API_URL`, y `COBALT_API_KEY` si exige autenticación), `!dl` lo intenta ahí antes de fallar. Sin esas variables no cambia nada. Rige la misma lista de sitios que yt-dlp, y un video que llega por cobalt no se marca como sensible (cobalt no informa `age_limit`), así que el filtro de canal NSFW no le aplica. Instalación en `DEPLOY.md` § cobalt; `deploy/preflight_check.sh` comprueba que la instancia responda.
- `!dl` / `purgito dl` ahora también descarga videos de Facebook (`facebook.com`, `fb.watch`), sumado a Instagram, TikTok y Twitter/X.
- Sistema de servidores premium: tabla `premium_guilds`, activada/desactivada por los webhooks de Polar.sh (`/webhooks/polar`) al procesar una suscripción — sin ningún endpoint de administración manual. Las features restringidas (memes, pool de imágenes) siguen siempre activas en `PURGATORY_GUILD_ID` hardcodeado, incondicionalmente; para el resto de los servidores depende exclusivamente de tener una suscripción activa en Polar. `HOME_GUILD_ID` se migra automáticamente a la tabla en el primer arranque.
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
- `/mis_datos`: exporta en un JSON descargable todos los mensajes que el bot guardó del usuario, agrupados por servidor. Cooldown de 60s por persona.
- `/imitar_mezcla @usuario1 @usuario2`: combina el corpus de ambos usuarios en un solo modelo Markov para generar un mensaje que mezcle el estilo de los dos, incluso cuando ninguno por separado llega al mínimo de mensajes que pide `/imitar`.
- Categoría **Plantillas** del panel: exportar la plantilla que se está editando como JSON e importar un archivo exportado — importar siempre crea una plantilla nueva, nunca sobrescribe una existente.
- Anuncios recurrentes: modo **semanal**, además de intervalo y diario — se elige un subconjunto de días de la semana y una hora fija de envío.
- Tab **Estadísticas** del dashboard ampliada con actividad reciente: mensajes aprendidos por día (últimos 14 días), quién alimentó más el corpus del servidor y las palabras más frecuentes (excluyendo muletillas comunes, URLs y menciones). De paso se activó el desglose de mensajes por canal, que la API ya calculaba pero el panel nunca mostraba.
- Avisos de Twitch en vivo: nueva categoría **Twitch** en `/settings` y tab propia en el dashboard, con el mismo diseño que YouTube (mención por rol opcional, aviso de canal borrado/sin permiso). Requiere credenciales opcionales (`TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET`, ver `.env.example`) — sin ellas, la categoría queda visible pero no deja agregar canales, el resto del bot funciona igual.
- `!dl <link>` / `purgito dl <link>`: descarga un video de Instagram, TikTok o Twitter/X (post público) con `yt-dlp` y lo sube al mismo canal. YouTube queda deliberadamente afuera por el bloqueo activo de descargas fuera del navegador. Respeta `guild.filesize_limit` (según el nivel de boost del servidor) además de un tope duro (`MAX_DL_VIDEO_BYTES`, 100MB default, en `limits.env`).
- Prefijo de comandos de texto configurable por servidor: `command_prefix` de discord.py pasó de ser un string fijo (`"!"`) a resolverse por guild (`settings.custom_prefix`, tab **Prefijo** del dashboard, categoría Servidor) — además siempre funciona el prefijo de palabra fijo `purgito ` (mismo `BOT_TRIGGER_NAME` que ya usaba el trigger de texto de memes). El filtro que evita que un comando propio entre al corpus (`OTHER_BOT_PREFIXES` en `cogs/chat.py`) ahora también reconoce el prefijo custom del guild, no solo el `"!"` default.
- Quién mandó cada GIF: `corpus_gifs` solo guardaba la URL deduplicada por servidor, sin autor ni mensaje. Tabla nueva `gif_senders` (usuario + canal/mensaje del envío más reciente + contador) que se actualiza en cada guardado. La tab **GIFs** del dashboard muestra ahora, sobre cada miniatura, un badge con el avatar de quien lo mandó más recientemente (+N si lo mandó más de una persona) con link directo al mensaje de origen, y suma una vista **Por persona** para ver solo los GIFs de alguien puntual. Los GIFs guardados antes de este cambio no tienen remitente conocido.

### Changed
- `is_home_guild()` renombrado a `is_premium_guild()` y ahora consulta un `set` en memoria cargado al arrancar (sin hit a DB por evento/comando).
- `HOME_GUILD_ID` marcada como deprecada en `.env.example` — se sigue leyendo una vez para migrar, luego no tiene efecto en runtime.
- Frases especiales (`/añadir_frase`, `/ver_frases`, `/borrar_frase`) y pool de reacciones (`/reacciones add|quitar|lista`) liberados del gate premium; ahora disponibles en todos los servidores.

### Removed
- `/chatmode`, `/corpus_ignorar` (`add`, `quitar`, `lista`), `/reacciones` (`add`, `quitar`, `lista`), `/youtube_add`, `/youtube_remove`, `/youtube_list`, `/youtube_set_mention`, `/meme_auto` (`activar`, `desactivar`, `lista`), `/añadir_frase`, `/ver_frases`, `/borrar_frase` y `/corpus_wipe` — reemplazados por completo por las categorías correspondientes del panel `/settings`. Total de slash commands: 43 → 25.
- Reproducción de música (`/play`, `/skip`, `/pause`, `/resume`, `/queue`, `/loop`, `/stop`, `/nowplaying`, `/volume`, `/shuffle`, `/leave`): se descartó migrar (SoundCloud-only, proxy residencial) y se eliminó el cog completo (`cogs/musica.py`, `music_player.py`), junto con las dependencias `yt-dlp`, `FFmpeg` y `PyNaCl`, y el setup de `cookies.txt`.

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

[Unreleased]: https://github.com/Purgito/purgito-bot/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Purgito/purgito-bot/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Purgito/purgito-bot/releases/tag/v1.0.0
