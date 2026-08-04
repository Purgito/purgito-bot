[![License: MIT + Commons Clause](https://img.shields.io/badge/License-MIT%20%2B%20Commons%20Clause-yellow.svg)](LICENSE) [![CI](https://github.com/punkyyy01/bot-discord-purg/actions/workflows/ci.yml/badge.svg)](https://github.com/punkyyy01/bot-discord-purg/actions/workflows/ci.yml) [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/) [![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)

<div align="center">

# 🤖 Purgito Bot

**Bot de Discord que aprende a hablar como tu servidor.**

Cadenas de Markov · Editor de embeds · Colección de GIFs · Notificaciones de YouTube

---

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=flat-square&logo=discord&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?style=flat-square&logo=sqlite&logoColor=white)
![Cloudflare R2](https://img.shields.io/badge/Cloudflare-R2-F38020?style=flat-square&logo=cloudflare&logoColor=white)

</div>

---

## ✨ Características

| | Característica | Descripción |
|---|---|---|
| 🧠 | **Markov automático** | Aprende del chat y genera réplicas al estilo del servidor cada 15 mensajes nuevos, con probabilidad configurable |
| 🎭 | **Imitación de usuarios** | Imita el estilo de escritura de cualquier miembro con `/imitar` |
| 💬 | **Modo chat** | Responde cuando lo mencionas o le respondes |
| 🎞️ | **Colección de GIFs** | Guarda GIFs de Tenor/Giphy automáticamente; los de Discord CDN se suben a R2 |
| ⚙️ | **Configuración del servidor** | Panel `/settings`, onboarding `/setup` y mensaje de bienvenida con acceso rápido |
| 🧩 | **Editor de embeds del panel** | Arma embeds clásicos o layouts con Components V2 y botones interactivos (incluye botones de rol) desde el navegador, con plantillas guardables |
| 📺 | **Notificaciones YouTube** | Sondea canales cada 15 min y avisa cuando hay video nuevo |
| 😂 | **Memes** | Genera memes con `/momo` o con reply a imagen; captions con Groq (llama-4-scout) o Markov |
| ⏱️ | **Memes automáticos** | Postea memes en canales configurables cada 2–24 horas |
| 🎯 | **Pool de imágenes** | Reacciona con 🎯 a una imagen para guardarla en el pool de memes |
| 💬 | **Frases especiales** | Pool de frases fijas que el bot suelta con 5% de probabilidad (cooldown 40 min) |
| 😄 | **Reacciones configurables** | Pool de emojis custom para las reacciones automáticas del bot |
| 🗂️ | **Corpus administrable** | Importa historial, consulta estadísticas, ignorá canales o limpià el corpus |

---

## 🚀 Instalación

### 1. Clonar e instalar dependencias

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Windows (PowerShell)
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus valores:

```env
# ── Obligatorio ────────────────────────────────────────────────────
DISCORD_TOKEN=tu_token_aquí

# ── Bot owner (panel de administración del dashboard) ──────────────
BOT_OWNER_ID=tu_discord_id

# ── Desarrollo (sync instantáneo de slash commands) ────────────────
GUILD_ID=123456789012345678

# ── Intents ────────────────────────────────────────────────────────
ENABLE_MESSAGE_CONTENT=true

# ── Trigger de texto plano para memes por reply ───────────────────
BOT_TRIGGER_NAME=artemis

# ── Puerto del servidor web de la galería ─────────────────────────
WEB_PORT=8080

# ── Límites de importación de historial (corpus) ───────────────────
REFEED_MAX_MESSAGES=80000
REFEED_ALL_MAX_MESSAGES=20000

# ── Markov (muestra de entrenamiento) ──────────────────────────────
MARKOV_TRAINING_MESSAGES=5000
USER_MARKOV_TRAINING_MESSAGES=2000

# ── Auto-generación de respuestas ─────────────────────────────────
AUTO_GENERATE_PROBABILITY=0.6

# ── Retención de datos al salir de un servidor ────────────────────
GUILD_DATA_RETENTION_DAYS=30

# ── Cloudflare R2 (para persistir GIFs de Discord CDN) ────────────
R2_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=tu_key
R2_SECRET_ACCESS_KEY=tu_secret
R2_BUCKET_NAME=nombre-del-bucket
R2_PUBLIC_URL=https://pub-xxx.r2.dev

# ── Groq (captions de memes con visión, opcional) ─────────────────
GROQ_API_KEY=tu_groq_key

# ── Captions de memes / auto memes ────────────────────────────────
GROQ_GUILD_COOLDOWN=10
```

### 3. Arrancar

```bash
python src/bot.py
```

El servidor web de la galería arranca en el mismo proceso en `0.0.0.0:8080`.

---

## 📋 Comandos

### 🤖 Markov y chat

| Comando | Descripción | Permisos |
|---|---|---|
| `/generar` | Genera un mensaje con el modelo Markov del servidor | Todos |
| `/imitar @usuario` | Genera un mensaje imitando el estilo del usuario (mín. 30 msgs) | Todos |
| `/chatmode on [#canal]` | Activa auto-reply al ser mencionado o al responderle | Gestionar servidor |
| `/chatmode off` | Desactiva el auto-reply | Gestionar servidor |
| `/corpus_info` | Muestra cuántos mensajes tiene el corpus del canal actual | Todos |
| `/refeed` | Importa los últimos mensajes del canal al corpus (máx. 80 000 por defecto) | Gestionar servidor |
| `/refeed_all` | Importa mensajes de todos los canales del servidor (máx. 20 000 por canal por defecto) | Gestionar servidor |
| `/corpus_wipe` | Borra todo el corpus y reinicia la caché Markov | Gestionar servidor |
| `/corpus_ignorar add #canal` | Añade un canal a la lista de ignorados | Gestionar servidor |
| `/corpus_ignorar quitar #canal` | Quita un canal de la lista de ignorados | Gestionar servidor |
| `/corpus_ignorar lista` | Lista canales ignorados | Gestionar servidor |
| `/añadir_frase <texto>` | Agrega una frase al pool del servidor | Todos |
| `/ver_frases` | Lista todas las frases con su ID y autor | Todos |
| `/borrar_frase <id>` | Borra una frase (propia o cualquiera si eres administrador) | Todos / Admin |

### 🎞️ GIFs

| Comando | Descripción | Permisos |
|---|---|---|
| `/gif_add <url>` | Añade un GIF manualmente (Tenor, Giphy o Discord CDN) | Gestionar servidor |

### ⚙️ Configuración

| Comando | Descripción | Permisos |
|---|---|---|
| `/settings` | Abre el panel de configuración del servidor | Gestionar servidor |
| `/setup` | Abre la guía de configuración inicial | Gestionar servidor |

### 😂 Memes ⭐ (premium)

> Estas funciones solo están disponibles en servidores premium. El propietario del bot las habilita desde el panel de administración del dashboard.

| Comando | Descripción | Permisos |
|---|---|---|
| `/momo` | Genera un meme usando una imagen del pool (cooldown 45s por usuario) | Todos |
| `/meme` | Alias de `/momo` | Todos |

**Trigger rápido (sin slash):** responde (reply) a un mensaje con imagen y escribe `artemis generar` o `@bot generar`.

### ⏱️ Memes automáticos ⭐ (premium)

| Comando | Descripción | Permisos |
|---|---|---|
| `/meme_auto activar #canal <horas>` | Activa memes automáticos cada 2–24h | Gestionar servidor |
| `/meme_auto desactivar #canal` | Desactiva memes automáticos | Gestionar servidor |
| `/meme_auto lista` | Lista configuración actual | Gestionar servidor |

### 💬 Frases especiales

Pool de frases fijas que el bot puede soltar con un 5% de probabilidad (cooldown de 40 minutos por servidor).

| Comando | Descripción | Permisos |
|---|---|---|
| `/añadir_frase <texto>` | Agrega una frase al pool del servidor | Todos |
| `/ver_frases` | Lista todas las frases con su ID y autor | Todos |
| `/borrar_frase <id>` | Borra una frase (propia o cualquiera si sos admin) | Todos / Admin |

### 😄 Pool de reacciones

El bot reacciona automáticamente al 5% de los mensajes usando emojis del pool. Si el pool está vacío, no reacciona.

| Comando | Descripción | Permisos |
|---|---|---|
| `/reacciones add <emoji>` | Añade un emoji al pool (Unicode o custom del servidor) | Gestionar servidor |
| `/reacciones quitar <id>` | Quita un emoji del pool por su ID | Gestionar servidor |
| `/reacciones lista` | Lista los emojis actuales con sus IDs | Gestionar servidor |

### 📺 YouTube

| Comando | Descripción | Permisos |
|---|---|---|
| `/youtube_add <channel_id> #canal [rol]` | Suscribe un canal de YouTube a un canal de Discord | Gestionar servidor |
| `/youtube_remove <channel_id>` | Elimina una suscripción | Gestionar servidor |
| `/youtube_list` | Lista todas las suscripciones activas del servidor | Gestionar servidor |
| `/youtube_set_mention <channel_id> [rol]` | Configura (o quita) el rol a mencionar en notificaciones | Gestionar servidor |

### 🔧 Utilidades

| Comando | Descripción |
|---|---|
| `/help` | Muestra un embed con todos los comandos disponibles |
| `!ping` | Responde `Pong!` para verificar que el bot está online |

---

## 🌐 Web API

El bot sirve una galería y una API REST en el mismo proceso (puerto `WEB_PORT`, por defecto `8080`).

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Galería HTML pública de GIFs |
| `GET` | `/api/gifs` | Lista todos los GIFs (`{gifs: [...], total: N}`) |
| `POST` | `/api/gifs` | Añade un GIF (`{url: "..."}`) — rate limit 5/min por IP |
| `DELETE` | `/api/gifs/{id}` | Elimina un GIF por ID — rate limit 3/min por IP |
| `GET` | `/health` | Healthcheck (`{ok: true}`) |

---

## ⚙️ Comportamiento automático

<details>
<summary><b>🧠 Construcción del corpus</b></summary>

Cada mensaje de usuario pasa por un filtro antes de guardarse: se eliminan URLs, menciones de Discord, secuencias ANSI típicas de logs y líneas sin letras. Se colapsan espacios y se descartan mensajes que queden vacíos. El corpus deduplica por `(servidor, message_id)`.

El bot mantiene **dos corpus independientes**:
- **Servidor** — para respuestas generales (`/generar`, auto-reply)
- **Por usuario** — exclusivo para `/imitar`

</details>

<details>
<summary><b>⚡ Generación automática</b></summary>

Cada **15 mensajes nuevos** insertados en el corpus de un canal, el bot genera una respuesta. Con un **45% de probabilidad** envía un GIF aleatorio de la colección en lugar del texto.

Con un **5% de probabilidad** (y cooldown de 40 minutos), el bot suelta una frase del pool de frases especiales en lugar de generar con Markov.

La caché del modelo Markov se invalida automáticamente cada **50 inserciones** para mantenerse actualizada.

</details>

<details>
<summary><b>💬 Auto-reply (chatmode)</b></summary>

Si el modo está activo, el bot responde cuando:
- Lo mencionan con `@bot`
- Alguien le hace reply a uno de sus mensajes

Se puede restringir a un canal específico con `/chatmode on #canal`. Requiere el permiso **Gestionar servidor**.

</details>

<details>
<summary><b>🎞️ Colección de GIFs</b></summary>

Los GIFs detectados en mensajes (Tenor, Giphy, adjuntos `.gif`) se guardan automáticamente. Los de `cdn.discordapp.com` se suben a **Cloudflare R2** para que no caduquen cuando Discord elimine el adjunto original.

</details>

<details>
<summary><b>🎯 Pool de imágenes</b></summary>

Al reaccionar con **🎯** a un mensaje con imagen (`.png`, `.jpg`, `.jpeg`, `.webp`), el bot sube la imagen a **R2** (si está configurado) y guarda su URL en la base de datos para usarla luego en `/momo` y en los memes automáticos.

</details>

<details>
<summary><b>😂 Captions de memes</b></summary>

Los captions se generan en dos pasos con fallback automático:

1. **Groq** (si `GROQ_API_KEY` está configurada): envía la imagen al modelo `llama-4-scout-17b-16e-instruct` con una muestra del corpus para generar captions irónicos adaptados al tono del servidor. Cooldown de 10 segundos por guild.
2. **Markov** (fallback): si Groq falla, está en rate limit, o no está configurado, genera el caption con el modelo Markov local.

</details>

<details>
<summary><b>📺 Notificaciones de YouTube</b></summary>

Una tarea en segundo plano sondea el RSS de cada canal suscrito cada **15 minutos**. Si detecta un video nuevo, envía un mensaje en el canal de Discord configurado con el título, enlace y mención al rol (si está configurado).

</details>

---

## 🏗️ Estructura del proyecto

```
.
├── src/
│   ├── bot.py              # Punto de entrada, logging, DB y carga de cogs
│   ├── config.py           # Variables de entorno y constantes compartidas
│   ├── db.py               # Capa de datos: aiosqlite, WAL mode, migraciones
│   ├── generation.py       # Limpieza de corpus, Markov y auto-respuestas
│   ├── gif_gallery.py      # HTML de la galería pública (embebido)
│   ├── help_view.py        # UI de /help
│   ├── i18n.py             # Traducciones y locales por servidor
│   ├── markov_engine.py    # Motor de cadenas de Markov
│   ├── meme_generator.py   # Renderizado de captions con Pillow
│   ├── r2.py               # Integración con Cloudflare R2
│   ├── utils.py            # Helpers compartidos
│   ├── webapi.py           # API HTTP y galería
│   └── cogs/               # Comandos y eventos por dominio
├── assets/
│   └── Impact.ttf          # Fuente para renderizado de captions
├── data/
│   └── bot.db              # Base de datos SQLite (generada al arrancar)
├── requirements.txt
└── locales/               # Textos de interfaz por idioma
```

---

## 🔐 Permisos necesarios

Al generar el enlace de invitación en el **Developer Portal**:

| Categoría | Valores requeridos |
|---|---|
| **OAuth2 Scopes** | `bot`, `applications.commands` |
| **Permisos de bot** | `Read Messages` · `Send Messages` · `Read Message History` · `Add Reactions` · `Embed Links` · `Connect` · `Speak` |
| **Intents privilegiados** | `Message Content Intent` · `Server Members Intent` |

---

## 📝 Notas

> **Los slash commands tardan hasta 1 hora** en propagarse globalmente. Para verlos al instante en desarrollo, pon `GUILD_ID=<id>` en `.env`.

> El modelo Markov necesita al menos **50 mensajes** en el corpus del servidor para generar respuestas, y **30** para `/imitar`.

> La base de datos usa **modo WAL** para mejor concurrencia entre lecturas y escrituras asíncronas.

> Si los slash commands no aparecen después de reiniciar, verificá que el bot esté invitado con el scope `applications.commands`.

> Sin `GROQ_API_KEY`, los captions de memes se generan solo con Markov. Con la key configurada, Groq tiene prioridad y Markov es el fallback.

> El bot registra logs en `data/bot.log` con rotación automática (5 MB, 3 backups).

> Al unirse a un servidor nuevo, el bot envía un embed de bienvenida con instrucciones de setup en el primer canal de texto disponible.

> Los memes automáticos se verifican cada **10 minutos**; el intervalo configurado con `/meme_auto activar` define cada cuántas horas se postea.

> El panel `/settings` y la guía `/setup` muestran el estado real del servidor, incluyendo chat, corpus, reacciones, YouTube y memes automáticos.

---

## 📄 Licencia

Este proyecto usa **MIT + Commons Clause**: eres libre de usarlo, modificarlo, hacer forks y redistribuirlo, pero no está permitido venderlo ni ofrecerlo como servicio pago (hosting, SaaS, soporte) cuyo valor derive sustancialmente del bot. Ver [LICENSE](LICENSE) para el texto completo.
