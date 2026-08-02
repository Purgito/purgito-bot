# Purgito

Bot de Discord (Python + discord.py) con panel web. Aprende el estilo de
chat de cada servidor (cadenas de Markov), genera memes, guarda GIFs, pone
música y avisa de videos nuevos de YouTube.

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

- `src/cogs/` — comandos y features del bot (chat, gifs, memes, música,
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
  `MAX_EMBED_IMAGE_UPLOAD_BYTES`, `MAX_SHARE_LINKS_PER_GUILD_DAY`.

Los tres se cargan al importar `src/config.py`.

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
demás sale estático de `/var/www/purgito-landing` (copia separada de
`landing/`, no el repo en sí). Cloudflare está delante de todo — si algo
"no cambia" después de un deploy, sospecha primero de caché antes de
asumir que el código está mal.

**Pendiente en el droplet:** `/es/dashboard/:id` es la única ruta del sitio
con un segmento dinámico y necesita un `location ^~ /es/dashboard/` con
`try_files … /es/dashboard/index.html` (está en DEPLOY.md). Sin agregarlo, esa
URL sirve la homepage. `/es/perfil*` no lo necesita: son carpetas reales.

`DEPLOY.md` ya no contradice esto: se actualizó a Oracle Linux + `conf.d` y
detalla los tres server blocks. Quedan dos puntos sin verificar ahí (ruta
del clon en el servidor, y si `/var/www/purgito-landing` es symlink o copia)
— hasta confirmarlos en el droplet, esta sección manda.

## Identidad visual

Tema oscuro, acento cian/turquesa (`hsl(186 84% 46%)`, color de la mascota
de Purgito). La inspiración de layout/pulido viene de wamellow.com, pero
nunca copiar su violeta, su mascota ni contenido específico de ellos —
solo la técnica.

## Convención de bocetos

Un recuadro vacío junto a un texto en los wireframes de `bocetos/` es un
placeholder de ícono SVG, no un checkbox literal — reemplázalo por un
ícono real salvo que se indique lo contrario.

## URLs útiles

- Invitar el bot: https://discord.com/oauth2/authorize?client_id=1471724794411089920
- Servidor de soporte: https://discord.gg/5U7HKyxnBv
