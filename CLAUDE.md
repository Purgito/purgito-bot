# Purgito

Bot de Discord (Python + discord.py) con panel web. Aprende el estilo de
chat de cada servidor (cadenas de Markov), genera memes, guarda GIFs, pone
música y avisa de videos nuevos de YouTube.

## Stack

- Bot: Python + discord.py, arquitectura de cogs en `src/cogs/`
- Python 3.11+ — CI corre en 3.12, el venv local está en 3.14
- Web: aiohttp puro (`src/webapi.py`), sirve el panel (`panel.purgito.app`)
  y algunos endpoints públicos (webhook de Polar, health check)
- Frontend: HTML/CSS/JS plano en `landing/` — NO usar React/Next.js ni
  ningún framework nuevo, aunque el diseño se inspire en sitios que sí los
  usan (ver "Identidad visual" abajo)
- DB: SQLite (`data/bot.db`)

## Comandos

```bash
# Tests — usar el venv: pytest NO está en requirements.txt y el Python del
# sistema no tiene las dependencias (falla al importar aiosqlite).
.venv/bin/python -m pytest tests -q

# Lint y formato — es lo único que corre en CI (.github/workflows/ci.yml).
ruff check .
ruff format --check .

# Check del selector de idioma de la landing (no lo corre CI).
node landing/test_lang.mjs
```

No hay pytest.ini ni configuración de pytest: los tests se descubren solos
desde `tests/`.

## Directorios clave

- `src/cogs/` — comandos y features del bot (chat, gifs, memes, música,
  premium, anuncios, layout_buttons)
- `src/webapi.py` — servidor web; ver zonas protegidas abajo
- `landing/` — sitio estático (index.html, style.css, script.js)
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
`sites-enabled`). `purgito.app` sirve estático directo desde
`/var/www/purgito-landing` (copia separada de `landing/`, no el repo en
sí). `panel.purgito.app` proxea a esta app en el puerto 8080. Cloudflare
está delante de todo — si algo "no cambia" después de un deploy, sospecha
primero de caché antes de asumir que el código está mal.

Ojo: `DEPLOY.md` describe otro escenario (Ubuntu, `sites-enabled`, dominio
`gifs.purg4t0ry.com`). Está desactualizado — esta sección manda.

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
