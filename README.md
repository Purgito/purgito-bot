[![License: MIT + Commons Clause](https://img.shields.io/badge/License-MIT%20%2B%20Commons%20Clause-yellow.svg)](LICENSE) [![CI](https://github.com/Purgito/purgito-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/Purgito/purgito-bot/actions/workflows/ci.yml) [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/) [![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)

<div align="center">

# 🤖 Purgito

**Bot de Discord que aprende a hablar como tu servidor.**

Cadenas de Markov · Editor de embeds · Colección de GIFs · Notificaciones de YouTube

[purgito.app](https://purgito.app) · [Invitar el bot](https://discord.com/oauth2/authorize?client_id=1471724794411089920) · [Soporte](https://discord.gg/5U7HKyxnBv)

</div>

---

## ✨ Qué hace

- **Markov automático** — aprende del chat y suelta respuestas al estilo del servidor, con frecuencia y probabilidad configurables
- **`/imitar`** — imita el estilo de escritura de un miembro
- **Responde a menciones y replies** en los canales que elijas
- **Memes** (`/momo`) — capciones con Groq (llama-4-scout) o Markov como fallback, sobre imágenes guardadas con 🎯 o subidas a mano
- **Colección de GIFs** — los detecta en el chat y persiste en Cloudflare R2 los que vienen de Discord CDN
- **YouTube** — avisa cuando un canal suscrito sube video nuevo
- **Anuncios programados**, frases especiales, reacciones custom, editor de embeds/botones (Components V2)

Todo esto se configura desde el [dashboard web](https://purgito.app) (OAuth2 con Discord) o desde `/settings` y `/setup` en Discord.

---

## 🚀 Empezar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar DISCORD_TOKEN como mínimo
python src/bot.py
```

Guía completa (variables de entorno, R2, Groq, deploy en producción) en
[`CONTRIBUTING.md`](CONTRIBUTING.md) y [`DEPLOY.md`](DEPLOY.md).

---

## 📋 Comandos

| Comando | Descripción | Permisos |
|---|---|---|
| `/generar` | Genera un mensaje con el modelo Markov del servidor | Todos |
| `/imitar @usuario` | Genera un mensaje imitando el estilo del usuario | Todos |
| `/momo`, `/meme` ⭐ | Genera un meme del pool de imágenes del servidor | Todos |
| `/refeed` | Importa el historial del canal actual al corpus | Gestionar servidor |
| `/refeed_channels` | Importa el historial de los canales configurados | Gestionar servidor |
| `/corpus_info` | Cuántos mensajes aprendió Purgito en el canal actual | Todos |
| `/gif_add <url>` ⭐ | Agrega un GIF a la colección del servidor | Gestionar servidor |
| `/settings` | Panel de configuración rápida | Gestionar servidor |
| `/setup` | Asistente de configuración inicial | Gestionar servidor |
| `/help` | Comandos y enlaces al dashboard | Todos |
| `/vote` | Link para votar por Purgito en top.gg | Todos |
| `/borrar_mis_datos` | Elimina tus datos guardados por Purgito | Todos |

⭐ Requiere suscripción Premium en el servidor.

---

## 🏗️ Estructura

```
.
├── src/
│   ├── bot.py         # Entry point: logging, DB, carga de cogs
│   ├── cogs/          # Comandos y eventos por dominio
│   ├── webapi.py      # API JSON del dashboard (auth, /api/*, webhooks)
│   ├── db.py          # aiosqlite, modo WAL, migraciones
│   ├── markov_engine.py, generation.py   # Motor Markov y auto-respuestas
│   ├── meme_generator.py, r2.py          # Memes (Pillow) y Cloudflare R2
│   └── locales/       # Traducciones
├── landing/            # Sitio estático + dashboard (HTML/CSS/JS plano, sin build step)
├── data/bot.db         # SQLite (se genera al arrancar)
└── requirements.txt
```

---

## 🔐 Permisos del bot (Developer Portal)

`bot`, `applications.commands` · `Send Messages`, `Read Message History`, `Add Reactions`, `Embed Links` · Intents: `Message Content`, `Server Members`.

---

## 📄 Licencia

**MIT + Commons Clause**: libre para usar, modificar y redistribuir, pero no para venderlo ni ofrecerlo como servicio pago (hosting, SaaS, soporte) cuyo valor derive sustancialmente del bot. Texto completo en [LICENSE](LICENSE).
