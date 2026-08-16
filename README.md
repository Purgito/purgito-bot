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
| 🗂️ | **Corpus administrable** | Importa historial, consulta estadísticas, ignora canales o limpia el corpus |

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

### 🤖 Markov, chat y moderación

| Comando | Descripción | Permisos |
|---|---|---|
| `/generar` | Genera un mensaje con el modelo Markov del servidor | Todos |
| `/imitar @usuario` | Genera un mensaje imitando el estilo del usuario (mín. 30 msgs) | Todos |
| `/refeed_channels` | Importa historial de mensajes al corpus (por canal o servidor) | Gestionar servidor |
| `/corpus_info` | Muestra cuántos mensajes tiene el corpus del canal actual | Todos |
| `/corpus_wipe` | Borra todo el corpus del servidor y reinicia la caché Markov | Gestionar servidor |
| `/gif_add <url>` | Añade un GIF al pool del servidor (Tenor, Giphy o Discord CDN) | Gestionar servidor |
| `/borrar_mis_datos` | Elimina permanentemente los mensajes y datos guardados del usuario | Todos |

### ⚙️ Configuración y gestión

| Comando | Descripción | Permisos |
|---|---|---|
| `/settings` | Abre el panel interactivo de configuración en Discord | Gestionar servidor |
| `/setup` | Abre el asistente de configuración inicial paso a paso | Gestionar servidor |
| `/help` | Muestra un embed de ayuda con comandos y enlaces al panel | Todos |
| `/invitame` | Entrega el link de invitación oficial del bot | Todos |

### 😂 Memes ⭐ (premium)

> Requiere suscripción Premium en el servidor.

| Comando | Descripción | Permisos |
|---|---|---|
| `/momo` | Genera un meme usando una imagen del pool (cooldown 3s por usuario) | Todos |
| `/meme` | Alias de `/momo` | Todos |

**Trigger por mención/reply:** responde (reply) a un mensaje con imagen escribiendo `artemis momo` o mencionando al bot.

---

## 🌐 Panel Web y Dashboard

Purgito incluye un panel de administración web completo (`/es/dashboard`), protegido mediante autenticación Discord OAuth2:

- **Chat y Aprendizaje**: Canales activos/ignorados, frecuencia y probabilidad de respuestas espontáneas, triggers de auto-respuesta y **Exclusión de usuarios** (bloqueo independiente de respuestas y aprendizaje).
- **Frases Especiales y Packs**: Frases fijas, cooldowns y asignación de packs por canal.
- **Reacciones**: Emojis personalizados para reacciones automáticas.
- **Galería de GIFs**: Gestión, visualización, subida y verificación de estado de GIFs.
- **Editor de Embeds**: Diseñador visual con plantillas, botones interactivos (Components V2) y asignación de roles.
- **Anuncios Programados**: Mensajes automáticos por intervalo o a horas fijas con zona horaria configurable.
- **YouTube**: Notificaciones automáticas de nuevos videos con mención de rol opcional.
- **Historial de Auditoría**: Registro de cambios administrativos en el servidor.

La documentación técnica completa de la API REST está disponible en `/es/documentacion/api`.

---

## ⚙️ Comportamiento automático

<details>
<summary><b>🧠 Construcción del corpus</b></summary>

Cada mensaje de usuario pasa por un filtro antes de guardarse: se eliminan URLs, menciones de Discord, secuencias ANSI típicas de logs y líneas sin letras. Se colapsan espacios y se descartan mensajes vacíos o de usuarios excluidos de aprendizaje. El corpus deduplica por `(servidor, message_id)`.

El bot mantiene **dos corpus independientes**:
- **Servidor** (`corpus_messages`) — para respuestas generales (`/generar`, auto-reply)
- **Por usuario** (`user_corpus`) — exclusivo para `/imitar`

</details>

<details>
<summary><b>⚡ Generación automática</b></summary>

Cada **N mensajes nuevos** (configurable por servidor, default 15) en un canal habilitado, el bot evalúa la probabilidad (default 60%) de emitir una respuesta espontánea, respetando un cooldown de silencio de 45 segundos por canal.

Con un **5% de probabilidad** (y cooldown de 40 minutos), el bot puede soltar una frase del pool de frases especiales en lugar de generar con Markov.

La caché del modelo Markov se invalida automáticamente tras nuevas inserciones o cambios en la exclusión de usuarios.

</details>

<details>
<summary><b>💬 Respuestas a menciones y replies</b></summary>

En canales habilitados, el bot responde cuando:
- Lo mencionan con `@Purgito`
- Alguien le responde (reply) directamente a uno de sus mensajes

Los usuarios con exclusión de interacción son ignorados automáticamente sin disparar respuestas, reacciones ni triggers.

</details>

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

> Si los slash commands no aparecen después de reiniciar, verifica que el bot esté invitado con el scope `applications.commands`.

> Sin `GROQ_API_KEY`, los captions de memes se generan solo con Markov. Con la key configurada, Groq tiene prioridad y Markov es el fallback.

> El bot registra logs en `data/bot.log` con rotación automática (5 MB, 3 backups).

> Al unirse a un servidor nuevo, el bot envía un embed de bienvenida con instrucciones de setup en el primer canal de texto disponible.

> Los memes automáticos se verifican cada **10 minutos**; el intervalo configurado con `/meme_auto activar` define cada cuántas horas se postea.

> El panel `/settings` y la guía `/setup` muestran el estado real del servidor, incluyendo chat, corpus, reacciones, YouTube y memes automáticos.

---

## 📄 Licencia

Este proyecto usa **MIT + Commons Clause**: eres libre de usarlo, modificarlo, hacer forks y redistribuirlo, pero no está permitido venderlo ni ofrecerlo como servicio pago (hosting, SaaS, soporte) cuyo valor derive sustancialmente del bot. Ver [LICENSE](LICENSE) para el texto completo.
