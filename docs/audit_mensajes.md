# Auditoría de lenguaje — mensajes de cara al usuario

Barrido completo de strings visibles para el usuario final (Discord + dashboard web).
**Ningún cambio aplicado todavía.** Estándar propuesto: tuteo ("tú") consistente, español neutro.

## 1. Jerga / acento detectado — REEMPLAZO PROPUESTO

### Voseo rioplatense (rompe la consistencia de tuteo del resto del proyecto)

| # | Archivo:línea | Texto original | Propuesta |
|---|---------------|----------------|-----------|
| 1 | `src/cogs/premium.py:57` | `no tenés permiso` | `No tienes permiso.` |
| 2 | `src/cogs/premium.py:81` | `no tenés permiso` | `No tienes permiso.` |
| 3 | `src/cogs/premium.py:102` | `no tenés permiso` | `No tienes permiso.` |
| 4 | `src/static/panel.js:378` | `Completá el canal de YouTube, el nombre y el canal de Discord` | `Completa el canal de YouTube, el nombre y el canal de Discord` |
| 5 | `src/static/panel.js:413` | `Contactá al owner del bot para activarlo.` | `Contacta al dueño del bot para activarlo.` |
| 6 | `src/static/panel.js:438` | `Elegí un canal y un intervalo entre 2 y 24 horas` | `Elige un canal y un intervalo entre 2 y 24 horas` |
| 7 | `src/webapi.py:203` | `sesión expirada, reingresá` | `sesión expirada, inicia sesión de nuevo` |
| 8 | `src/webapi.py:506` | `sesión expirada, reingresá` | `sesión expirada, inicia sesión de nuevo` |
| 9 | `src/webapi.py:434` | `No administrás ningún servidor de Discord.` | `No administras ningún servidor de Discord.` |

### Regionalismos leves en `src/locales/es.json`

| # | Línea | Texto original | Propuesta |
|---|-------|----------------|-----------|
| 10 | 107 | `todavía estoy en blanco por acá 👀` | `todavía estoy en blanco por aquí 👀` ("acá" suena a Cono Sur) |
| 11 | 113 | `…cómo habla la gente acá, dale acceso a Purgito…` | `…cómo habla la gente aquí, dale acceso a Purgito…` ("dale acceso" es neutro, se mantiene) |
| 12 | 115 | `Voy a hablar medio soso por ahora` | `Voy a sonar algo soso por ahora` ("medio" como adverbio es coloquial regional) |

## 2. Casos límite — DECISIÓN TUYA (no los toco sin confirmación)

| # | Archivo:línea | Texto | Observación |
|---|---------------|-------|-------------|
| A | `src/cogs/memes.py:107` | `introducí un sujeto, expectativa o contexto que no encaje` | Voseo, pero está dentro del **prompt interno a Groq** (no lo ve el usuario; influye en el tono de los captions generados, que por tu regla son contenido dinámico). Propongo corregirlo igual a `introduce…` — costo cero y evita que el modelo copie el voseo. |
| B | `src/gif_gallery.py` (galería pública) | `⊕ SUMMON`, `Invocando…`, `GIF summonado al vault`, `Ese GIF ya habita en el vault`, `VAULT VACÍO` | No es jerga regional: es **tematización de marca** (estética "purgatorio") con spanglish deliberado. Cualquier hispanohablante lo entiende. Propongo **no tocar** para preservar la personalidad; avísame si prefieres neutralizarlo. |
| C | `src/locales/es.json:111,130` y otros | `Corre /refeed_all`, `corre /setup` | "Correr un comando" es uso extendido en LatAm; en España se diría "ejecuta". Es entendible universalmente. Propongo dejarlo (o cambiar a "ejecuta" si quieres máxima neutralidad). |

## 3. Inconsistencias de estilo, NO de jerga (opcional)

Mensajes en minúscula y sin puntuación final, contrastan con el resto del bot que usa mayúscula inicial + emoji. Son neutros en dialecto; los listo por si quieres unificar tono en la misma pasada:

| Archivo:línea | Texto |
|---------------|-------|
| `src/cogs/memes.py:252` | `necesito que respondas a un mensaje que tenga una imagen` |
| `src/cogs/memes.py:262` | `la imagen supera el límite de 10MB` |
| `src/cogs/memes.py:269,303` | `ocurrió un error, intenta de nuevo` |
| `src/cogs/memes.py:276,296` | `no pude generar el meme, intenta de nuevo` |
| `src/cogs/memes.py:435` / `src/cogs/gifs.py:190` | `esta función no está disponible en este servidor` |
| `src/cogs/memes.py:444` | `espera {remaining} segundos antes de generar otro meme` |
| `src/cogs/memes.py:489` | `se rompió algo, revisa los logs.` — además, "revisa los logs" no le sirve al usuario final; sugerencia: `Ocurrió un error inesperado. Intenta de nuevo más tarde.` |
| `src/generation.py:78` | `no pude generar una respuesta, intenta de nuevo` |
| `src/generation.py:98` | `no tengo respuesta para eso` |
| `src/cogs/youtube.py:72` | `subió un video nuevo!` — falta `¡` de apertura |

## 4. Archivos revisados y limpios (sin jerga)

- `src/cogs/chat.py`, `src/cogs/general.py`, `src/cogs/musica.py`, `src/cogs/settings.py`, `src/cogs/gifs.py` (salvo lo listado arriba)
- `src/help_view.py`, `src/music_player.py`, `src/generation.py` (salvo estilo)
- `src/locales/en.json` — inglés neutro, sin slang
- `src/pages/panel.py`, `src/pages/selector.py`, `src/webapi.py` (resto de mensajes de error de API: neutros)
- `src/bot.py`, `src/config.py`, `src/i18n.py`, `src/utils.py`, `src/meme_generator.py`, `src/r2.py`, `src/db.py` — solo logs internos o sin texto de usuario
- No hay archivos de configuración (JSON/YAML/TOML) con mensajes predefinidos fuera de `src/locales/`

## Resumen

- **12 strings con jerga/voseo confirmado** en 4 archivos (`premium.py`, `panel.js`, `webapi.py`, `es.json`)
- **3 casos límite** que requieren tu decisión (A, B, C)
- **~10 strings de estilo inconsistente** (opcional, no es jerga)
- El proyecto ya usa tuteo en el ~95% de los mensajes → estandarizar a "tú" solo requiere corregir los 9 casos de voseo
