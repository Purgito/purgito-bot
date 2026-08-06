# Guía de deploy — bot-discord-purg

Guía completa para levantar Purgito de cero. Cubre setup local para desarrollo y deploy en producción con systemd + nginx + Cloudflare.

> **Producción corre en Oracle Linux** (droplet, usuario `opc`), no en Ubuntu.
> Los comandos de servidor de esta guía usan `dnf`, y la config de nginx va en
> `/etc/nginx/conf.d/` — Oracle Linux no usa `sites-available`/`sites-enabled`.
> El setup local sigue siendo agnóstico del SO.

---

## Índice

1. [Prerrequisitos](#1-prerrequisitos)
2. [Crear el bot en Discord](#2-crear-el-bot-en-discord)
3. [Clonar e instalar](#3-clonar-e-instalar)
4. [Variables de entorno — referencia completa](#4-variables-de-entorno--referencia-completa)
5. [Servicios opcionales](#5-servicios-opcionales)
   - [Cloudflare R2 (persistencia de GIFs)](#cloudflare-r2-persistencia-de-gifs)
   - [Groq (captions de memes con IA)](#groq-captions-de-memes-con-ia)
6. [Correr en desarrollo](#6-correr-en-desarrollo)
7. [Deploy en producción](#7-deploy-en-producción)
   - [Paquetes del sistema](#paquetes-del-sistema)
   - [Clonar en el servidor](#clonar-en-el-servidor)
   - [Configurar systemd](#configurar-systemd)
   - [Configurar nginx](#configurar-nginx)
   - [Cloudflare (DNS + SSL)](#cloudflare-dns--ssl)
8. [Actualizar en producción](#8-actualizar-en-producción)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerrequisitos

### Para desarrollo local

- Python 3.11+
- gifsicle, opcional (`sudo apt install gifsicle` / `brew install gifsicle`) —
  sin él los GIFs se suben a R2 sin comprimir, nada más
- Una cuenta de Discord con permisos para crear bots

### Para producción (droplet)

- Oracle Linux (el droplet actual), usuario `opc` con `sudo`
- Python 3.11+
- gifsicle — comprime los GIFs antes de subirlos a R2 (degrada con gracia si falta)
- nginx
- Dominios apuntando al servidor: `purgito.app` (+ `www`) y los
  `*.purg4t0ry.com` heredados (ver [Configurar nginx](#configurar-nginx))

---

## 2. Crear el bot en Discord

1. Entrá al [Discord Developer Portal](https://discord.com/developers/applications)
2. **New Application** → coloca el nombre
3. En el menú izquierdo: **Bot**
   - Copiá el **Token** (lo vas a necesitar como `DISCORD_TOKEN`)
   - Activa **Message Content Intent** (imprescindible para el corpus de Markov)
   - Activa **Server Members Intent**
4. En **OAuth2 → URL Generator**:
   - Scopes: `bot` + `applications.commands`
   - Permisos de bot: `Read Messages`, `Send Messages`, `Read Message History`, `Add Reactions`, `Embed Links`, `Connect`, `Speak`
5. Copia la URL generada y ábrela para invitar el bot a tu servidor
6. En **OAuth2 → Redirects**, registra `https://purgito.app/auth/callback`.
   Tiene que coincidir exacto con `{DASHBOARD_BASE_URL}/auth/callback` de
   `urls.env`, o el login falla con `invalid_request`.

> **Tip:** para que los slash commands aparezcan al instante en un servidor específico (sin esperar hasta 1 hora de propagación global), coloca `GUILD_ID` en el `.env` con el ID de ese servidor.

---

## 3. Clonar e instalar

```bash
git clone https://github.com/punkyyy01/bot-discord-purg.git
cd bot-discord-purg

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Luego copia el archivo de ejemplo:

```bash
cp .env.example .env
```

Edita `.env` con tus valores (ver sección siguiente).

---

## 4. Variables de entorno — referencia completa

```env
# ═══════════════════════════════════════════════════════════
#  OBLIGATORIO
# ═══════════════════════════════════════════════════════════

# Token del bot de Discord.
# Obtenerlo en: Discord Developer Portal → tu aplicación → Bot → Token
# ⚠️ Nunca commitees este valor.
DISCORD_TOKEN=

# ═══════════════════════════════════════════════════════════
#  CONFIGURACIÓN GENERAL
# ═══════════════════════════════════════════════════════════

# Habilita el intent "Message Content" para leer el texto de los mensajes.
# Debe estar activado también en el Developer Portal (Bot → Privileged Gateway Intents).
# Default: true
ENABLE_MESSAGE_CONTENT=true

# [DEPRECADA] ID del servidor home original. Se lee UNA sola vez al arrancar para
# migrar el guild a la tabla premium_guilds; después ya no tiene efecto. El premium
# se gestiona desde el panel de administración del dashboard.
HOME_GUILD_ID=

# ID del servidor para sincronización instantánea de slash commands (útil en desarrollo).
# Sin esto, los comandos nuevos pueden tardar hasta 1 hora en aparecer globalmente.
GUILD_ID=

# Nombre con el que se activa el trigger de memes por texto plano.
# Ej: si colocas "artemis", escribir "artemis generar" en un reply a una imagen genera un meme.
# Default: artemis
BOT_TRIGGER_NAME=artemis

# Puerto del servidor web de la galería pública (gifs.purg4t0ry.com).
# nginx hace proxy a este puerto. No exponer directamente a internet.
# Default: 8080
WEB_PORT=8080

# ═══════════════════════════════════════════════════════════
#  MARKOV — límites de entrenamiento
# ═══════════════════════════════════════════════════════════

# Máximo de mensajes a leer del canal actual con /refeed.
# Default: 80000
REFEED_MAX_MESSAGES=80000

# Máximo de mensajes por canal con /refeed_channels (los canales elegidos
# para el corpus). El nombre de la variable quedó de cuando el comando se
# llamaba /refeed_all — no vale la pena migrarla solo por el rename.
# Default: 20000
REFEED_ALL_MAX_MESSAGES=20000

# Cuántos mensajes del corpus se cargan a RAM para entrenar el modelo del servidor.
# Valores altos = mejor calidad, más RAM.
# Default: 5000
MARKOV_TRAINING_MESSAGES=5000

# Igual que el anterior pero para el modelo de usuario (/imitar).
# Default: 2000
USER_MARKOV_TRAINING_MESSAGES=2000

# ═══════════════════════════════════════════════════════════
#  OPCIONAL — Groq (captions de memes con visión IA)
# ═══════════════════════════════════════════════════════════

# API Key de Groq para captions con llama-4-scout (modelo de visión).
# Sin esta key los captions se generan con Markov local.
# Obtener en: https://console.groq.com → API Keys
GROQ_API_KEY=

# ═══════════════════════════════════════════════════════════
#  OPCIONAL — Cloudflare R2 (persistencia de GIFs)
# ═══════════════════════════════════════════════════════════

# Sin R2, las URLs de Discord CDN pueden expirar.
# Todas las variables R2_* deben estar presentes para que R2 se active.

# URL del endpoint S3-compatible. Formato: https://<account-id>.r2.cloudflarestorage.com
R2_ENDPOINT_URL=

# Access Key ID del token R2 con permisos "Object Read & Write".
R2_ACCESS_KEY_ID=

# Secret del token R2.
R2_SECRET_ACCESS_KEY=

# Nombre del bucket R2.
R2_BUCKET_NAME=

# URL pública del bucket. Formato: https://pub-xxx.r2.dev
R2_PUBLIC_URL=
```

---

## 5. Servicios opcionales

### Cloudflare R2 (persistencia de GIFs)

1. Cloudflare Dashboard → **R2 Object Storage** → crea un bucket
2. **R2 → Manage R2 API Tokens** → token con permisos **Object Read & Write**
3. Copia el **Access Key ID** y el **Secret Access Key**
4. El **Endpoint URL** está en la página del bucket bajo "S3 API"
5. Completá las variables `R2_*` en `.env`

### Groq (captions de memes con IA)

1. Creá cuenta en [console.groq.com](https://console.groq.com)
2. **API Keys** → **Create API Key**
3. Copia la key → `GROQ_API_KEY` en `.env`

El bot usa `meta-llama/llama-4-scout-17b-16e-instruct` para analizar imágenes. Si la key no está o Groq falla, hace fallback automático a Markov.

---

## 6. Correr en desarrollo

```bash
source .venv/bin/activate
python src/bot.py
```

La galería arranca en el mismo proceso en `http://localhost:8080`. Los slash commands aparecen instantáneamente en el servidor de `GUILD_ID`.

---

## 7. Deploy en producción

### Paquetes del sistema

Oracle Linux usa `dnf`, no `apt`.

```bash
sudo dnf update -y
sudo dnf install -y python3 python3-pip python3-devel nginx git

# gifsicle — comprime los GIFs antes de subirlos a R2. Si falta, el bot sigue
# funcionando y sube los GIFs sin optimizar (solo se paga más storage).
# No está en los repos base de Oracle Linux: viene de EPEL.
sudo dnf install -y epel-release
sudo dnf install -y gifsicle

# Verificar
python3 --version  # 3.11+
gifsicle --version
```

### Clonar en el servidor

```bash
sudo mkdir -p /opt/bot-discord-purg
sudo chown $USER:$USER /opt/bot-discord-purg

git clone https://github.com/punkyyy01/bot-discord-purg.git /opt/bot-discord-purg
cd /opt/bot-discord-purg

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env
```

### Configurar systemd

El unit file canónico vive en el repo: [`deploy/bot-purg.service`](deploy/bot-purg.service).

```bash
sudo cp deploy/bot-purg.service /etc/systemd/system/bot-purg.service
```

> ⚠️ **Seguridad**: crea un usuario dedicado con `sudo useradd -r -s /bin/false bot-purg` y otórgale permisos sobre `/opt/bot-discord-purg`.

Claves del unit:
- `Restart=on-failure` + `RestartSec=15` — reinicio automático si el proceso muere, con espera entre intentos para no entrar en loops agresivos.
- `StartLimitIntervalSec=0` — systemd nunca deja de reintentar, aunque el problema persista (una caída de red larga no deja el bot muerto de forma permanente).
- `After=network-online.target` — no arranca antes de tener red.

```bash
sudo systemctl daemon-reload
sudo systemctl enable bot-purg
sudo systemctl start bot-purg
sudo systemctl status bot-purg
```

Ver logs:

```bash
journalctl -u bot-purg -f
```

### Configurar nginx

> ⚠️ **La config de nginx NO está versionada en este repo.** El archivo real y
> autoritativo vive solo en el droplet, en `/etc/nginx/conf.d/purgito.conf`.
> Lo de abajo describe su estructura para poder reconstruirla, pero ante
> cualquier duda manda el archivo del servidor, no esta guía.

Oracle Linux carga todo lo que esté en `/etc/nginx/conf.d/*.conf` — no hay
`sites-available`/`sites-enabled` ni `ln -s` que hacer.

```bash
sudo nano /etc/nginx/conf.d/purgito.conf
```

Ese archivo contiene **tres server blocks**:

| Server block | Qué hace |
|---|---|
| `gifs.purg4t0ry.com` | Proxy a `127.0.0.1:8080` (dominio heredado de la galería) |
| `panel.purg4t0ry.com` | Proxy a `127.0.0.1:8080` (dominio heredado del panel) |
| `purgito.app` + `www.purgito.app` | **Todo el sitio**: estático desde `/var/www/purgito-landing` + proxy por ruta a la app |

Los dos heredados son el patrón simple de proxy a la app aiohttp:

```nginx
server {
    listen 80;
    server_name panel.purg4t0ry.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # $remote_addr, no $proxy_add_x_forwarded_for: nginx es el único
        # proxy delante de la app, así que no hay nada legítimo que
        # "agregar" a una cadena existente. $proxy_add_x_forwarded_for
        # anexa $remote_addr a cualquier X-Forwarded-For que ya venga en
        # el request — si el cliente manda uno propio, su valor queda
        # primero en la lista, y _client_ip() en webapi.py lee el primer
        # valor de la lista como IP real. Eso permite spoofearla.
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

El de `purgito.app` es el importante: **no hay más subdominio `panel.`**. El
mismo host sirve la landing estática desde disco y proxea a la app las rutas
que la app realmente registra en `webapi.py` (`/auth/*`, `/api/*`,
`/webhooks/polar`, `/health`). Todo lo demás es HTML estático, con `try_files`
por prefijo de idioma para que `/es/terminos` resuelva a
`es/terminos/index.html` y `/es/` caiga en el `index.html` de la raíz.

El **dashboard también es estático**: `/es/perfil`, `/es/perfil/conexiones` y
`/es/perfil/facturacion` son carpetas reales y las cubre el `try_files` de
idioma. La única excepción es `/es/dashboard/<id>`, que necesita su propio
`location` (está más abajo, marcado como obligatorio) porque el id del
servidor no existe como carpeta.

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name purgito.app www.purgito.app;
    root /var/www/purgito-landing;
    index index.html;

    # ── Authenticated Origin Pulls (desactivado) ───────────────────
    # Exige que solo Cloudflare pueda hablarle a este origin (mTLS): sin
    # esto, cualquiera que descubra la IP del droplet puede saltarse
    # Cloudflare (y su WAF/cache) y pegarle directo a nginx. Requiere:
    #   1. Activar "Authenticated Origin Pulls" en Cloudflare (SSL/TLS →
    #      Origin Server) y bajar su CA pull certificate desde ahí.
    #   2. Este server block necesita terminar TLS (listen 443 ssl con
    #      ssl_certificate/ssl_certificate_key — hoy Cloudflare habla HTTP
    #      plano con el origin, ver sección Cloudflare más abajo) antes de
    #      que esto tenga efecto: la verificación de cliente pasa durante
    #      el handshake TLS, no sirve sobre el listener 80.
    # ssl_client_certificate /etc/nginx/certs/cloudflare-origin-pull-ca.pem;
    # ssl_verify_client on;

    # ── Cabeceras de seguridad, para todo lo que sirve este server ──
    # (estático y proxeado). CSP queda afuera a propósito: la API ya pone
    # la suya por request en webapi.py (_security_headers_middleware,
    # restrictiva: default-src 'none') y la landing la suya en el <head>
    # generado (build_docs.py, permite fuentes/tenor/imágenes externas).
    # Sumar una tercera acá, a nivel server, se combinaría con esas dos —
    # el navegador aplica todas las CSP presentes a la vez— y la más
    # estricta rompería la landing en vez de sumar seguridad.
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # ── Dinámico: proxy a la app (rutas registradas en webapi.py) ──
    location /auth/     { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }
    location /api/      { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }
    location /webhooks/ { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }
    location = /health  { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }

    # ── Estático ────────────────────────────────────────────────────
    # ⚠️ OBLIGATORIO para el dashboard: /es/dashboard/<id-del-servidor> es la
    # única ruta del sitio con un segmento dinámico, y ese id no existe como
    # carpeta en disco. Sin este location cae en el try_files de abajo y sirve
    # la homepage. El id lo lee el JS del path (landing/js/core/config.js).
    # `^~` gana sobre el regex de idiomas que viene después.
    location ^~ /es/dashboard/ {
        try_files $uri $uri/ /es/dashboard/index.html;
    }

    # Las páginas legales y las del perfil son directorios reales
    # (es/terminos/index.html, es/perfil/facturacion/index.html).
    # El prefijo de idioma suelto (/es/) no existe en disco: cae al index.
    location ~ ^/(es|en|ru|ja|de)/ {
        try_files $uri $uri/ $uri/index.html /index.html;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Donde `/etc/nginx/purgito_proxy.conf` son las tres cabeceras de siempre, en un
solo archivo en vez de repetirlas en cada `location`:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
# $remote_addr y no $proxy_add_x_forwarded_for -- mismo motivo que en el
# server block heredado de más arriba: nginx es el único proxy delante de
# la app, y anexar a un X-Forwarded-For que ya trae el cliente permite
# spoofear _client_ip() en webapi.py (que lee el primer valor de la lista).
proxy_set_header X-Forwarded-For $remote_addr;
```

Aplicar cambios:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Cloudflare (DNS + SSL)

1. DNS → Add record tipo `A` por cada host (`purgito.app`, `www`, y los
   `*.purg4t0ry.com` heredados), valor = IP del droplet, proxy ✅ (naranja).
   `panel.purgito.app` ya no se usa: no le hace falta registro.
2. Cloudflare maneja el SSL automáticamente. No necesitas certbot ni HTTPS en nginx.

> **Cloudflare cachea la landing.** Si después de un deploy el sitio "no cambia",
> sospecha primero de la caché de Cloudflare (purge) antes de asumir que el
> código está mal.

---

## 8. Actualizar en producción

**El deploy es manual: no hay CI/CD.** El workflow de `.github/workflows/ci.yml`
solo corre lint (`ruff`) sobre los PRs; no despliega nada.

```bash
ssh opc@<droplet>
cd /opt/bot-discord-purg          # ver nota de abajo sobre la ruta
git pull
source .venv/bin/activate
pip install -r requirements.txt   # solo si requirements.txt cambió
sudo systemctl restart bot-purg
sudo systemctl status bot-purg
```

> Si `.env.example` tiene variables nuevas, añádelas manualmente a tu `.env` antes de reiniciar.

### Migraciones de datos por servidor

Además de los `ALTER TABLE` que corre `init_db()`, hay migraciones que
necesitan la API de Discord y por eso corren **desde el bot, una vez por
servidor**, en el `on_ready` del cog correspondiente. Son automáticas: no hay
comando que ejecutar, solo hay que reiniciar el bot y mirar el log.

| Migración | Qué hace | Log a buscar |
|---|---|---|
| `corpus_allowlist_v1` | Rellena `corpus_allowed_channels` con los canales de texto de cada servidor menos los ignorados | `Corpus: N canales habilitados en …` |

**Por qué importa:** el corpus pasó de "aprende de todos los canales menos los
ignorados" a "aprende solo de los canales habilitados". Los servidores que ya
existían tienen la lista vacía, que en el modelo nuevo significa *no aprender de
nada*. Sin esta migración, todos los servidores activos dejarían de aprender el
día del deploy, sin ningún error visible.

Cada servidor se migra una sola vez (`applied_migrations`), así que un reinicio
posterior **no pisa** lo que un admin haya ajustado desde el dashboard. Si el
log muestra que falló para algún servidor, la única salida es configurar los
canales a mano en `/es/dashboard/<id>/chat` → Corpus: el flag ya quedó marcado y
no se reintenta sola (a propósito — reintentarla sobreescribiría configuración
hecha a mano).

Verificar después del restart:

```bash
journalctl -u bot-purg --since "5 min ago" | grep -i "Corpus:"
```

### Reconciliar los GIFs de R2 (una sola vez)

`scripts/reconcile_gif_objects.py` normaliza los objetos que ya están en el
bucket al esquema content-addressed: deduplica el mismo archivo entre
servidores, lo re-comprime con gifsicle y reconstruye la tabla `gif_objects`.
Se corre a mano, una vez, después del deploy que trae la deduplicación.

```bash
sudo systemctl stop bot-purg          # evita subidas en paralelo
cd /opt/bot-discord-purg && source .venv/bin/activate

python scripts/reconcile_gif_objects.py                 # dry-run: solo informa
python scripts/reconcile_gif_objects.py --limit 50      # prueba sobre 50 objetos
python scripts/reconcile_gif_objects.py --apply         # ejecuta de verdad

sudo systemctl start bot-purg
```

Sin `--apply` no escribe nada. Es idempotente: correrlo de nuevo no rompe nada.
Con miles de objetos tarda, porque baja cada uno y espera `--sleep` segundos
(default 0.1) entre llamadas a R2 para no saturar la API. Guardar el log — deja
una línea por objeto subido o borrado.

### Deduplicar GIFs casi-duplicados (dedup perceptual)

`scripts/backfill_gif_phashes.py` complementa al de arriba: ese deduplica por
content_hash exacto (mismos bytes); este detecta el mismo meme reposteado con
distinta compresión/recorte (bytes distintos, mismo dHash perceptual) y
fusiona esos objetos en uno solo. Se corre a mano después del deploy que trae
esta feature, y de ahí en adelante cada vez que se quiera reprocesar el bucket.

```bash
sudo systemctl stop bot-purg          # evita subidas en paralelo
cd /opt/bot-discord-purg && source .venv/bin/activate
pip install -r requirements.txt       # trae imagehash

python scripts/backfill_gif_phashes.py           # backfill de phashes + reporte de clusters, sin fusionar
```

Revisar a ojo el reporte de clusters antes de fusionar nada: `GIF_PHASH_MAX_DISTANCE`
(limits.env, default 6) es un punto de partida conservador y puede necesitar
ajuste — un umbral mal calibrado fusiona memes que en realidad son distintos.
Si algún cluster no convence, subir o bajar el valor en limits.env, hacer
`git commit`, y volver a correr el dry-run hasta que el reporte se vea bien.

```bash
python scripts/backfill_gif_phashes.py --apply   # recién ahora fusiona

sudo systemctl start bot-purg
```

El backfill de phashes (llenar la columna `phash` de `gif_objects`) se escribe
siempre, tenga o no `--apply` el resto — es aditivo, no borra ni fusiona nada.
Es idempotente: en la segunda corrida los objetos ya tienen phash y los
clusters ya fusionados no vuelven a aparecer.

Nunca toca objetos referenciados por `corpus_images` (las imágenes de memes
también pueden ser `.gif`), ni los huérfanos, que solo informa.

### Dos puntos sin verificar

No pude confirmarlos desde la máquina de desarrollo (sin acceso SSH al
droplet). Están documentados como pendientes a propósito, en vez de darlos por
hecho:

1. **Ruta del clon en el servidor.** `deploy/bot-purg.service` declara
   `WorkingDirectory=/opt/bot-discord-purg` (y `User=bot-purg`), pero `CLAUDE.md`
   describe el deploy como `cd purgito-bot && git pull` desde el home de `opc`.
   Verificar cuál es la real:

   ```bash
   systemctl show bot-purg -p WorkingDirectory -p User
   ```

2. **Qué es `/var/www/purgito-landing`.** Si es un symlink al `landing/` del
   clon, `git pull` alcanza para publicar la landing. Si es una copia separada,
   hace falta un paso de sincronización explícito (`cp -r landing/. /var/www/purgito-landing/`
   o `rsync`) que hoy no está documentado en ningún lado. Verificar:

   ```bash
   ls -la /var/www/ | grep purgito
   file /var/www/purgito-landing
   ```

   Ojo: `CLAUDE.md` dice hoy que es una **copia separada**. Si resulta ser un
   symlink, hay que corregir esa línea de `CLAUDE.md` también.

---

## 9. Troubleshooting

| Problema | Causa probable | Fix |
|---|---|---|
| Slash commands no aparecen | `GUILD_ID` no configurado o sin scope `applications.commands` | Poner `GUILD_ID` en `.env` y reiniciar, o esperar 1h si es global |
| GIFs de Discord CDN no se suben a R2 | Faltan vars `R2_*` | Completar todas las `R2_*` en `.env` |
| La galería o el panel no cargan | nginx caído o DNS sin propagar | `systemctl status nginx` + verificar DNS |
| nginx devuelve **502** en los hosts que proxean a `:8080` | SELinux (enforcing por defecto en Oracle Linux) bloquea que nginx abra conexiones de red | `sudo setsebool -P httpd_can_network_connect 1` |
| nginx devuelve **403** solo en `purgito.app` | Contexto SELinux incorrecto en `/var/www/purgito-landing` | `sudo restorecon -Rv /var/www/purgito-landing` |
| El sitio no cambia después de un `git pull` + restart | Caché de Cloudflare, no el código | Purgear caché en Cloudflare y reintentar |
| El bot arranca pero no lee mensajes | `ENABLE_MESSAGE_CONTENT=false` o intent desactivado en el portal | Activar Message Content Intent en el Developer Portal |
| `ModuleNotFoundError` | venv no activado o `pip install` no corrió | `source .venv/bin/activate && pip install -r requirements.txt` |
| Bot se cae y no reinicia | `Restart=always` no está en el `.service` | Verificar el `.service` y `systemctl daemon-reload` |
