# Purgito

Bot de Discord (Python + discord.py) con panel web. Aprende el estilo de
chat de cada servidor (cadenas de Markov), genera memes, guarda GIFs y avisa
de videos nuevos de YouTube.

## Stack

- Bot: Python + discord.py, arquitectura de cogs en `src/cogs/`
- Python 3.11+ — CI corre en 3.12, el venv local está en 3.14
- Web: aiohttp puro (`src/webapi.py`), **solo JSON** — auth OAuth2, `/api/*`
  y los endpoints públicos (webhook de Polar, health check). No renderiza
  HTML. Todo bajo `purgito.app` — ya no hay subdominio `panel.`
- Frontend: HTML/CSS/JS plano en `landing/` — NO usar React/Next.js ni
  ningún framework nuevo, aunque el diseño se inspire en sitios que sí los
  usan (ver "Identidad visual" abajo). El dashboard son páginas estáticas
  más módulos ES nativos en `landing/js/` (sin bundler, sin build step)
- DB: SQLite (`data/bot.db`)

## Comandos

```bash
# Tests — usar el venv: pytest NO está en requirements.txt y el Python del
# sistema no tiene las dependencias (falla al importar aiosqlite).
.venv/bin/python -m pytest tests -q

# Lint y formato — corre en CI (.github/workflows/ci.yml).
ruff check .
ruff format --check .

# Regenera las páginas de landing/es/, resella el ?v= de style.css, dash.css
# y script.js, y reconstruye el import map de landing/js/. Correr después de
# tocar docs/*.md, landing/pages/*, cualquier .css o cualquier .js — el HTML
# generado se commitea. CI corre el --check y falla si quedó viejo.
.venv/bin/python landing/build_docs.py
.venv/bin/python landing/build_docs.py --check

# Check del selector de idioma de la landing (no lo corre CI).
node landing/test_lang.mjs
```

No hay pytest.ini ni configuración de pytest: los tests se descubren solos
desde `tests/`.

## Directorios clave

- `src/cogs/` — comandos y features del bot (chat, gifs, memes, youtube,
  premium, anuncios, layout_buttons)
- `src/webapi.py` — API JSON; ver zonas protegidas abajo
- `landing/` — sitio estático (index.html, style.css, script.js)
- `landing/pages/` — cuerpos escritos a mano; `build_docs.py` les pega el
  navbar/footer/head y los escribe en `landing/es/<slug>/index.html`
- `landing/js/` + `landing/dash.css` — dashboard (`/es/perfil*`,
  `/es/dashboard/:id`). `js/embeds/` y `js/tabs/gifs.js` vienen del panel
  anterior y se reutilizan **sin tocar la lógica**: si hay que cambiar algo
  ahí, primero preguntá
- `bocetos/` — wireframes de referencia (Excalidraw exportado a PNG/SVG)
- `referencias/` — dumps de código externo usados solo como referencia
  visual/técnica (gitignored, no es parte del proyecto — no ejecutar ni
  modificar nada ahí, y no confundir sus rutas internas con las de este repo)

## Variables de entorno

Tres archivos, con reglas distintas:

- `.env` — **secretos, gitignored.** Nunca copiar valores de acá a ningún
  archivo versionado ni a un mensaje. Los nombres esperados están en
  `.env.example`.
- `urls.env` — URLs y dominios públicos, **versionado en git**:
  `PANEL_URL`, `DASHBOARD_BASE_URL`, `LANDING_URL`, `LANDING_ORIGINS`,
  `SESSION_COOKIE_DOMAIN`, `SUPPORT_URL`, `DOCS_URL`, `REPO_URL`
- `limits.env` — cuotas por servidor, **versionado en git**. Casi todas van
  en pares `_FREE` / `_PREMIUM`: `MAX_CORPUS_MESSAGES_PER_GUILD_*`,
  `MAX_CORPUS_MESSAGES_PER_GUILD_TOTAL_*`,
  `MAX_USER_CORPUS_MESSAGES_PER_GUILD_*`, `MAX_GIFS_PER_GUILD_*`,
  `MAX_IMAGES_PER_GUILD_*`, `MAX_ANNOUNCEMENTS_PER_GUILD_*`,
  `MAX_EMBED_TEMPLATES_PER_GUILD_*`. Sin par: `MAX_GIF_DOWNLOAD_BYTES`,
  `MAX_EMBED_IMAGE_UPLOAD_BYTES`, `MAX_SHARE_LINKS_PER_GUILD_DAY`,
  `MAX_LAYOUT_FILE_UPLOAD_BYTES` (bloques "File" de Layout V2 — no persiste
  en R2, vive en memoria del proceso con TTL corto, ver `_pending_layout_files`
  en `webapi.py`), `GIF_LOSSY_LEVEL` (nivel de `--lossy` de gifsicle al subir
  GIFs a R2).

Los tres se cargan al importar `src/config.py`.

## Configuración del chat: qué manda sobre qué

Cuatro listas de canales que se confunden fácil. Son conceptos distintos:

| Tabla | Significa | Lista vacía = |
|---|---|---|
| `spontaneous_channels` | Dónde **habla por su cuenta** (mensajes espontáneos) | habla en todos |
| `mention_channels` | Dónde **responde a menciones** | responde en todos |
| `corpus_allowed_channels` | De dónde **aprende** | no aprende de ninguno |
| `ignored_channels` | Dónde está **completamente mudo** | ninguno mudo |

`spontaneous_channels` y `mention_channels` son independientes: un canal puede
estar en una, en la otra, en ambas o en ninguna — por ejemplo, un canal donde
Purgito habla solo pero no contesta si lo mencionan. Antes eran un solo
concepto (`chat_channels`); esa tabla sigue existiendo pero vestigial, solo
como origen de la migración que copió sus filas a las dos nuevas al separarlas
— nada la lee ni la escribe ya.

La asimetría de la lista vacía es a propósito: leer mensajes es más invasivo que
responder, así que el default seguro es no leer. Un canal ignorado nunca aprende
ni responde, esté o no en las otras listas.

`settings.chat_channel_id` está **deprecado** (era un canal único para las
menciones): sigue en la tabla para no romper una migración en caliente, pero
ninguna lógica lo lee.

Las probabilidades y frecuencias del chat (`auto_generate_every`,
`auto_generate_probability`, `reaction_probability`,
`gif_response_probability`, `mention_rate_limit`) viven en `settings`, por
servidor. Las constantes de `config.py` quedaron solo como fallback. Rango
válido en un único lugar: `db.CHAT_TUNABLES`.

## Zonas protegidas — no tocar sin confirmar antes

En `src/webapi.py`, estas piezas sostienen funcionalidad real en
producción: `_webhook_polar` + `_POLAR_*` (activa Premium), `_api_health`,
`_api_premium_get`/`_api_premium_checkout` (inicia compras nuevas),
`start_web_server`/`stop_web_server`. Si una tarea toca este archivo,
identifica primero qué de esto se vería afectado y dilo antes de proceder.

## Deploy — es manual, no hay CI/CD

```bash
ssh opc@<droplet>
cd purgito-bot && git pull
sudo systemctl restart bot-purg
```

La config de nginx vive FUERA de este repo, en
`/etc/nginx/conf.d/purgito.conf` en el droplet (Oracle Linux — no usa
`sites-enabled`). Un solo server block cubre `purgito.app` +
`www.purgito.app` y distingue **por ruta**: `/auth/*`, `/api/*`,
`/webhooks/*` y `/health` proxean a esta app en el puerto 8080; todo lo
demás sale estático de `/var/www/purgito-landing` (symlink a `landing/`
dentro del clon real, confirmado 2026-08-12 — no una copia separada: un
`git pull` alcanza para publicar cambios de la landing, sin paso de sync
aparte). Cloudflare está delante de todo — si algo
"no cambia" después de un deploy, sospecha primero de caché antes de
asumir que el código está mal.

**Pendiente en el droplet:** `/<lang>/dashboard/:id` es la única ruta del
sitio con un segmento dinámico y necesita un `location` por regex
(`^/(es|en|ru|ja|de)/dashboard/`) con `try_files … /$1/dashboard/index.html`
(está en DEPLOY.md, generalizado a los 5 idiomas el 2026-08-09 para que un
idioma nuevo con dashboard propio no rompa en silencio). Sin agregarlo, esa
URL sirve la homepage. `/es/perfil*` no lo necesita: son carpetas reales.

`DEPLOY.md` ya no contradice esto: se actualizó a Oracle Linux + `conf.d` y
detalla los tres server blocks. Ruta real del clon confirmada en el droplet
(2026-08-12): `/home/opc/purgito-bot`, corriendo como `opc` — no como el
usuario dedicado `bot-purg` que documenta `deploy/bot-purg.service` (esa
migración quedó pendiente, ver DEPLOY.md § "Migrar a un usuario dedicado").

## Voz y copy

Todo texto nuevo dirigido al usuario (claves de `src/locales/*.json`, embeds,
mensajes de comandos, texto de `landing/`) sigue estas reglas — se detectaron
por una auditoría de tono que encontró texto con "voz de IA" colado en varias
claves:

- Purgito nunca se auto-justifica ni se defiende preventivamente de algo que
  nadie cuestionó (mal: *"No estoy roto, es un límite..."* — nadie lo acusó
  de estar roto).
- Nunca narra su propio estado interno como un asistente virtual en vez de
  dar la instrucción directa (mal: *"Todavía no estoy aprendiendo de
  nada..."* — mejor decir qué hacer primero).
- Sin aperturas de "asistente haciendo onboarding" (mal: *"Te guío por los
  ajustes esenciales..."*; también evitar "aquí tienes...", "no dudes en...").
- Sin redundancia de relleno: decir la misma idea de una sola forma, no tres
  (mal: *"Son irreversibles — úsalas con cuidado"* después de ya decir que
  "borran datos").
- Instrucciones directas, tono natural y casual, sin hedging (evitar "podría
  ser que...", "tal vez quieras...").
- **Español:** tuteo neutro, sin voseo ni regionalismos ("elige"/"tienes"/
  "puedes", nunca "elegí"/"tenés"/"podés"). Confirmalo con grep antes de dar
  por buena una clave nueva.
- **Inglés:** neutro e internacional — sin britishisms mezclados con
  americanisms, sin slang regional.

## Identidad visual

Tema oscuro, acento cian/turquesa (`hsl(186 84% 46%)`, color de la mascota
de Purgito). La inspiración de layout/pulido viene de wamellow.com, pero
nunca copiar su violeta, su mascota ni contenido específico de ellos —
solo la técnica.

Patrones de UI ya validados en el tab CHAT del dashboard (paleta de uso,
`probabilityField`, chips, matriz de canales, override por canal, regla de
uso de ⓘ) están documentados en `landing/DESIGN_SYSTEM.md` — revisarlo antes
de reinventar algo parecido al propagar la arquitectura de CHAT a otros tabs.

## Convención de bocetos

Un recuadro vacío junto a un texto en los wireframes de `bocetos/` es un
placeholder de ícono SVG, no un checkbox literal — reemplázalo por un
ícono real salvo que se indique lo contrario.

## URLs útiles

- Invitar el bot: https://discord.com/oauth2/authorize?client_id=1471724794411089920
- Servidor de soporte: https://discord.gg/5U7HKyxnBv
