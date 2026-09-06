# Guía de deploy — bot-discord-purg

Guía completa para levantar Purgito de cero. Cubre setup local para desarrollo y deploy en producción con systemd + nginx + Cloudflare.

> **Esta guía es agnóstica de distro donde importa.** Producción corrió en
> Oracle Linux hasta el 5 de septiembre de 2026 (Oracle reclamó esa
> instancia al vencer el Free Trial sin aviso) y desde entonces corre en
> Ubuntu, sobre AWS. Los pasos que dependen del gestor de paquetes, de
> SELinux o de la estructura de nginx están marcados explícitamente como
> **Oracle Linux** o **Ubuntu/Debian** — no asumas que uno es "el real" y el
> otro "el de repaso": la próxima migración puede caer en cualquiera de los
> dos, o en un tercero. El setup local (sección 1-6) sigue siendo agnóstico
> del SO por completo.
>
> Si te quedaste sin servidor y necesitás levantar en otro proveedor ya,
> `MIGRATION.md` tiene el flujo corto end-to-end; `docs/PORTABILITY.md`
> tiene el inventario de qué hay que copiar para no perder datos en el
> camino. Esta guía (`DEPLOY.md`) es la referencia larga y detallada de cada
> paso.

---

## Índice

0. [Checklist de migración a un servidor nuevo](#0-checklist-de-migración-a-un-servidor-nuevo)
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

## 0. Checklist de migración a un servidor nuevo

Todos los pasos de un deploy de cero, en orden, con los problemas ya
tropezados en la migración Oracle→AWS (2026-09-05) como ítems explícitos a
verificar — no solo como prosa a leer, como checklist a tildar. Cada ítem
linkea a la sección con el detalle. Para el flujo corto sin toda la
explicación, ver `MIGRATION.md`.

**Antes de tocar el servidor nuevo:**

- [ ] ¿La instancia vieja todavía está viva? Si sí, corré el checklist de
      "antes de destruir la instancia vieja" de `docs/PORTABILITY.md`
      primero (backup de `data/` completo, no solo `bot.db`, y del `.env`).

**Sistema operativo — identificar cuál es ANTES de copiar comandos:**

- [ ] ¿Es Oracle Linux (`dnf`, SELinux enforcing por default) o
      Ubuntu/Debian (`apt`, sin SELinux)? Ver [Paquetes del
      sistema](#paquetes-del-sistema) — los comandos de instalación difieren.
- [ ] Si es Oracle Linux: confirmar que SELinux está en `enforcing`
      (`getenforce`) — vas a necesitar `setsebool`/`restorecon` más abajo.
      Si es Ubuntu/Debian: no hay SELinux, ese paso completo no aplica.

**Clonar e instalar (sección 3, con la ruta real del servidor nuevo):**

- [ ] `git clone` en la ruta elegida (no asumas `/opt/bot-discord-purg`
      del ejemplo de la guía — anotá la ruta real, la vas a necesitar para
      el unit de systemd).
- [ ] `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- [ ] **Problema conocido:** confirmar que `.env` es un ARCHIVO, no un
      directorio, antes de asumir que `cp .env.example .env` funcionó
      (`test -f .env`; un `mkdir .env` accidental durante un setup manual
      ya pasó una vez). `deploy/preflight_check.sh` lo chequea solo.
- [ ] Completar `.env` — ver [sección 4](#4-variables-de-entorno--referencia-completa).
      **Problema conocido:** `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` y
      `SESSION_SECRET` son fáciles de saltear porque sin ellas el bot
      arranca igual, sin ningún error — solo loguea `Dashboard
      deshabilitado: faltan variables obligatorias ...` y cualquiera que
      intente loguearse al panel se encuentra con un 404 sin explicación.
      Si el servidor nuevo debe tener dashboard, las tres son obligatorias.
- [ ] Restaurar `data/bot.db` (y el resto de `data/`, no solo el `.db` —
      ver `docs/PORTABILITY.md` § flags de migración) desde el backup de la
      instancia vieja.

**systemd (sección 7):**

- [ ] Generar el unit con `deploy/render_service.sh <usuario> <ruta>` en vez
      de copiar `deploy/bot-purg.service.template` a mano y editarlo — el
      template tiene placeholders (`{{DEPLOY_USER}}`, `{{DEPLOY_PATH}}`),
      no una ruta/usuario que sirva de ningún droplet real.
      **Problema conocido:** el unit viejo tenía hardcodeado
      `/home/opc/purgito-bot` y `User=bot-purg` (usuario que nunca se creó
      en ningún droplet real) — si estás copiando el `.service` de memoria
      en vez de generarlo, vas a repetir ese error.
- [ ] **Problema conocido:** si activás `ProtectHome`/`ReadOnlyPaths`/
      `ReadWritePaths`/`ProtectSystem=strict` (comentados por default en el
      template), probalos con cuidado — en systemd real sobre Ubuntu
      26.04 esta combinación tiró `status=203/EXEC` con el binario andando
      perfecto a mano. Ver la nota en
      `deploy/bot-purg.service.template` antes de descomentarlas.
- [ ] `sudo systemctl daemon-reload && sudo systemctl enable --now bot-purg`
      y confirmar `active (running)` antes de seguir.

**nginx (sección 7):**

- [ ] Reconstruir `/etc/nginx/conf.d/purgito.conf` desde [Configurar
      nginx](#configurar-nginx) — no está versionado en el repo.
- [ ] **Problema conocido (Ubuntu/Debian):** `/home/<usuario>` viene 750
      (`drwxr-x---`) por default, lo que bloquea a `www-data` de atravesar
      el directorio hacia `/var/www/purgito-landing` si es un symlink
      dentro del home — nginx devuelve 500 en la landing. Nunca pasa en
      Oracle Linux (SELinux maneja el acceso distinto). Fix:
      `chmod o+x /home/<usuario>` + `chmod -R o+rX
      /home/<usuario>/purgito-bot/landing`.
- [ ] **Problema conocido:** confirmar que `location = /es/` y
      `location = /en/` usan `try_files` (no `redirect`/`return 301`) — un
      redirect ahí genera loop infinito, porque el JS de `index.html`
      vuelve a mandar a `/es/` apenas carga en `/`. Ver la nota en la
      sección de nginx.
- [ ] `sudo nginx -t && sudo systemctl reload nginx`.
- [ ] Si es Oracle Linux y nginx da 502/403: ver [Troubleshooting](#9-troubleshooting)
      (SELinux). Si es Ubuntu/Debian, ese troubleshooting no aplica —
      revisar permisos de archivo en cambio.

**Cloudflare / DNS:**

- [ ] Actualizar los A records de `purgito.app`, `www.purgito.app` y
      `gifs.purg4t0ry.com` a la IP del servidor nuevo (fácil de olvidar
      justo este último por ser el dominio "heredado").
- [ ] Purgar caché de Cloudflare después del primer deploy — si "no
      cambia nada" después de publicar, sospechar de la caché antes que
      del código.

**Verificación final:**

- [ ] Correr `deploy/preflight_check.sh` en el servidor nuevo y confirmar
      que todo pasa (o entender por qué no).
- [ ] Avisar en el servidor de soporte si hubo downtime visible para
      usuarios.

---

## 1. Prerrequisitos

### Para desarrollo local

- Python 3.11+
- gifsicle, opcional (`sudo apt install gifsicle` / `brew install gifsicle`) —
  sin él los GIFs se suben a R2 sin comprimir, nada más
- Una cuenta de Discord con permisos para crear bots

### Para producción (droplet)

- Un usuario con `sudo` sobre el servidor — cualquier distro Linux moderna
  sirve. Ya corrió en Oracle Linux (`opc`) y corre hoy en Ubuntu (`ubuntu`,
  sobre AWS); los comandos exactos de instalación de paquetes difieren por
  distro, ver [Paquetes del sistema](#paquetes-del-sistema).
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
#  OBLIGATORIO PARA EL DASHBOARD WEB
# ═══════════════════════════════════════════════════════════
#
# ⚠️ Sin las tres, el bot arranca igual y no tira ningún error visible — solo
# loguea "Dashboard deshabilitado: faltan variables obligatorias ..." (ver
# DASHBOARD_ENABLED en config.py) y cualquiera que intente loguearse al
# panel se encuentra con un 404 sin explicación. Fáciles de saltear en un
# setup manual porque nada rompe hasta que alguien las necesita.

# ID de la aplicación de Discord (Developer Portal → tu app → OAuth2 →
# Client ID). Es público — aparece en cualquier link de invitación — pero
# igual va acá por conveniencia, junto al resto del setup de OAuth2.
DISCORD_CLIENT_ID=

# Secret de la aplicación (Developer Portal → OAuth2 → Client Secret →
# "Reset Secret" si no lo tenés a mano). Este SÍ es secreto — nunca lo
# commitees.
DISCORD_CLIENT_SECRET=

# Clave random para firmar/cifrar la cookie de sesión del dashboard.
# Generarla con: python3 -c "import secrets; print(secrets.token_hex(32))"
# Si se pierde o cambia (ej. se regeneró "por las dudas" en una migración en
# vez de copiar el .env viejo), todas las sesiones activas se invalidan —
# no es pérdida de datos, cada usuario logueado vuelve a loguearse.
SESSION_SECRET=

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

Identificá primero la distro del servidor nuevo (`cat /etc/os-release`) — los
comandos de instalación no son intercambiables.

#### Oracle Linux (`dnf`)

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

Oracle Linux trae SELinux en `enforcing` por default (`getenforce` para
confirmar) — eso agrega dos pasos que en Ubuntu/Debian no existen, ver
[Troubleshooting](#9-troubleshooting) (`setsebool`/`restorecon`) más abajo
cuando llegues a nginx.

#### Ubuntu / Debian (`apt`)

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx git gifsicle

# Verificar
python3 --version  # 3.11+
gifsicle --version
```

`gifsicle` sí está en los repos base de Ubuntu/Debian — no hace falta nada
como EPEL acá. Ubuntu/Debian no tiene SELinux: todo el troubleshooting de
`setsebool`/`restorecon` de la sección 9 no aplica en esta distro. En
cambio, mirá el punto de permisos de `/home/<usuario>` en [Configurar
nginx](#configurar-nginx) — ese sí es específico de Ubuntu/Debian.

### Clonar en el servidor

> **Estado real en producción:** hasta el 2026-08-12 el droplet de Oracle
> tenía el clon en `/home/opc/purgito-bot`, corriendo como `opc` (usuario
> con sudo), no como un usuario dedicado. Desde la migración a AWS
> (2026-09-05) es `/home/ubuntu/purgito-bot`, corriendo como `ubuntu` — mismo
> patrón, otro usuario. Ninguna de las dos es "la ruta correcta": la ruta y
> el usuario reales son lo que elijas al clonar, y el unit de systemd se
> genera a partir de eso (ver [Configurar systemd](#configurar-systemd)
> abajo) — no hay que editarlo a mano ni hacerlo coincidir con ningún
> ejemplo de esta guía.

```bash
sudo mkdir -p /opt/bot-discord-purg
sudo chown $USER:$USER /opt/bot-discord-purg

git clone https://github.com/punkyyy01/bot-discord-purg.git /opt/bot-discord-purg
cd /opt/bot-discord-purg

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Confirmar que copió un ARCHIVO, no un directorio (un `mkdir .env`
# accidental durante un setup manual ya pasó una vez y es fácil no notarlo
# hasta que el bot falla al arrancar con un error de parseo confuso):
test -f .env && echo "OK: .env es un archivo" || echo "MAL: revisar .env"

nano .env
```

### Configurar systemd

El unit real se **genera** a partir de la plantilla del repo,
[`deploy/bot-purg.service.template`](deploy/bot-purg.service.template) —
esa plantilla tiene placeholders (`{{DEPLOY_USER}}`, `{{DEPLOY_PATH}}`), no
sirve copiada tal cual. Generarla con
[`deploy/render_service.sh`](deploy/render_service.sh):

```bash
deploy/render_service.sh <usuario> </ruta/al/checkout> > /tmp/bot-purg.service
# ejemplo real (AWS, 2026-09-05):
#   deploy/render_service.sh ubuntu /home/ubuntu/purgito-bot > /tmp/bot-purg.service

cat /tmp/bot-purg.service   # revisar antes de copiar -- ¿dice lo que esperás?
sudo cp /tmp/bot-purg.service /etc/systemd/system/bot-purg.service
```

Este cambio existe justamente porque el unit viejo tenía
`/home/opc/purgito-bot` y `User=bot-purg` (un usuario que nunca se creó en
ningún droplet real) hardcodeados directo en el archivo versionado — cada
migración requería acordarse de editarlo a mano, y una vez se olvidó (ver
[Actualizar en producción § Desplegar un cambio de
infraestructura](#8-actualizar-en-producción)).

> ⚠️ **Seguridad**: crea un usuario dedicado con `sudo useradd -r -s /bin/false bot-purg` y otórgale permisos sobre el checkout, en vez de correr el bot con un usuario que tiene sudo. **Ni el droplet de Oracle ni el de AWS hicieron esto** -- corren como el usuario real con sudo (`opc`/`ubuntu`). Cualquier RCE en el proceso del bot (una dependencia comprometida, un parser de imagen/feed malicioso) hoy equivale a comprometer una cuenta con sudo, no solo la cuenta del bot. Ver "Migrar a un usuario dedicado" abajo.

#### Migrar a un usuario dedicado (pendiente)

No se aplicó todavía en ningún droplet real -- requiere una ventana con el
bot parado. Comandos propuestos, para correr a mano y con aprobación
explícita antes de tocar producción (reemplazar `<usuario>`/`<ruta>` por
los reales del servidor):

```bash
sudo useradd -r -s /sbin/nologin bot-purg
sudo chown -R bot-purg:bot-purg <ruta>
# el usuario real (opc/ubuntu/el que sea) sigue necesitando poder
# actualizar el código (git pull) -- agregarlo al grupo alcanza para eso
# sin volver a correr todo como ese usuario:
sudo usermod -aG bot-purg <usuario>
sudo chmod -R g+rX <ruta>

deploy/render_service.sh bot-purg <ruta> | sudo tee /etc/systemd/system/bot-purg.service
sudo systemctl daemon-reload
sudo systemctl restart bot-purg
sudo systemctl status bot-purg   # confirmar que arrancó como bot-purg
journalctl -u bot-purg -f        # mirar por errores de permisos
```

Claves del unit:
- `Restart=on-failure` + `RestartSec=15` — reinicio automático si el proceso muere, con espera entre intentos para no entrar en loops agresivos.
- `StartLimitIntervalSec=0` — systemd nunca deja de reintentar, aunque el problema persista (una caída de red larga no deja el bot muerto de forma permanente).
- `After=network-online.target` — no arranca antes de tener red.
- Sandboxing (`ProtectHome`, `ReadOnlyPaths`, `ReadWritePaths`,
  `ProtectSystem=strict`) queda **comentado por default** en la plantilla:
  esta combinación tiró `status=203/EXEC` en systemd real sobre Ubuntu
  26.04 durante la migración a AWS, con el mismo binario andando perfecto
  corrido a mano. La causa exacta de la interacción no se identificó — ver
  la nota completa dentro de `deploy/bot-purg.service.template` antes de
  descomentarlas en un servidor nuevo.

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

Oracle Linux **y** Ubuntu/Debian cargan por default todo lo que esté en
`/etc/nginx/conf.d/*.conf` (confirmado en ambas distros) — no hace falta
`sites-available`/`sites-enabled` ni `ln -s` en ninguna de las dos.

```bash
sudo nano /etc/nginx/conf.d/purgito.conf
```

Ese archivo contiene **dos server blocks**:

| Server block | Qué hace |
|---|---|
| `gifs.purg4t0ry.com` | Proxy a `127.0.0.1:8080` (dominio heredado de la galería) |
| `purgito.app` + `www.purgito.app` | **Todo el sitio**: estático desde `/var/www/purgito-landing` + proxy por ruta a la app |

> `panel.purg4t0ry.com` **ya no existe** — el dashboard vive dentro de
> `purgito.app` desde que se retiró ese subdominio (ver sección de
> Cloudflare más abajo, que ya tenía esto bien). Si estás reconstruyendo la
> config desde cero y ves un server block para `panel.purg4t0ry.com` en un
> backup viejo, no lo copies.

El heredado es el patrón simple de proxy a la app aiohttp:

```nginx
server {
    listen 80;
    server_name gifs.purg4t0ry.com;

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
    #
    # No es solo WAF/cache: _client_ip() en webapi.py (la clave de bucket de
    # TODOS los rate limit por IP de la app) prioriza el header
    # CF-Connecting-IP, y este server block lo deja pasar sin tocarlo. Sin
    # AOP, cualquiera que le hable directo a nginx manda el
    # CF-Connecting-IP que quiera y se salta CADA rate limit de la app (login,
    # embeds/send, triggers, checkout de premium, todos) --
    # X-Forwarded-For no sirve de red de respaldo acá: con
    # $remote_addr en vez de $proxy_add_x_forwarded_for (ver más abajo), lo
    # único que llega en X-Forwarded-For para tráfico legítimo es la IP de
    # borde de Cloudflare, compartida por miles de visitantes.
    #
    # Si activar AOP completo (con el cambio de TLS que pide) no es viable
    # todavía, un allowlist de IPs de Cloudflare en nginx alcanza para lo
    # mismo sin tocar TLS: bajar https://www.cloudflare.com/ips/ y agregar
    # un `allow <rango>;` por línea + `deny all;` al final de este server
    # block (o el equivalente vía firewall del droplet). Más simple que AOP,
    # mismo resultado: nada que no venga de Cloudflare llega a nginx.

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
    # Sin esto, nginx manda "Server: nginx/1.x.x" -- la versión exacta ayuda
    # a buscar CVEs puntuales y no le sirve a nadie real. server_tokens
    # también vale en http{} para cubrir los dos server blocks heredados de
    # más arriba de una sola vez, si se prefiere no repetirlo acá.
    server_tokens off;

    # ── Dinámico: proxy a la app (rutas registradas en webapi.py) ──
    location /auth/     { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }
    location /api/      { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }
    location /webhooks/ { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }
    location = /health  { proxy_pass http://127.0.0.1:8080; include /etc/nginx/purgito_proxy.conf; }

    # ── Estático ────────────────────────────────────────────────────
    # ⚠️ OBLIGATORIO para el dashboard: /<lang>/dashboard/<id-del-servidor> es
    # la única ruta del sitio con un segmento dinámico, y ese id no existe
    # como carpeta en disco. Sin este location cae en el try_files de abajo y
    # sirve la homepage. El id lo lee el JS del path (landing/js/core/config.js).
    # Location por regex (no `^~`): nginx evalúa los location por regex en el
    # orden en que aparecen en el archivo y usa el PRIMERO que matchee — este
    # tiene que seguir apareciendo antes que el regex de idiomas de abajo.
    # Generalizado a los 5 códigos (no solo /es/) para que un idioma nuevo con
    # dashboard propio (landing/<lang>/dashboard/) no rompa en silencio: antes
    # esto estaba fijo a /es/dashboard/ y cualquier otro idioma caía en el
    # try_files genérico de abajo, que sirve la homepage en vez del dashboard
    # porque el id tampoco existe como carpeta ahí.
    location ~ ^/(es|en|ru|ja|de)/dashboard(/.*)?$ {
        try_files $uri $uri/ /$1/dashboard/index.html;
    }

    # ⚠️ OBLIGATORIO: /es/ pelado (sin nada después) es un caso especial.
    # landing/es/ SÍ existe como directorio real (tiene subcarpetas de
    # contenido: terminos/, guia/, etc.) pero NO tiene su propio index.html
    # -- la home en español vive en la raíz (index.html). Con try_files
    # normal ($uri $uri/ $uri/index.html /index.html, el de más abajo),
    # nginx encuentra que /es/ ES un directorio real, intenta servirlo como
    # tal (busca index.html adentro), no lo encuentra, y devuelve 403 ahí
    # mismo -- NUNCA llega a probar el fallback /index.html, porque
    # try_files corta apenas $uri/ resuelve a un directorio existente sin
    # index, no sigue a los parámetros siguientes en ese caso.
    #
    # El fix NO es un redirect (`return 301 /;` o similar): el JS de
    # index.html detecta el idioma del navegador y redirige de / a /es/ (o
    # /en/) apenas carga -- un redirect acá crea un loop infinito entre / y
    # /es/. Servir la home en español directo, sin mover la URL:
    location = /es/ {
        try_files /index.html =404;
    }
    # /en/ sí tiene hoy su propio landing/en/index.html (existe como
    # archivo real), así que en teoría el try_files genérico de abajo ya lo
    # resuelve solo -- este location se agrega igual, por las dudas: si el
    # día de mañana ese archivo deja de generarse o de commitearse, la
    # regresión sería el mismo 403 silencioso que /es/, y sin este location
    # explícito nadie lo notaría hasta que un usuario reporte el link roto.
    location = /en/ {
        try_files /index.en.html =404;
    }

    # Las páginas legales y las del perfil son directorios reales
    # (es/terminos/index.html, es/perfil/facturacion/index.html).
    # El prefijo de idioma suelto (/es/, /en/) ya está cubierto arriba;
    # esto es para el resto de rutas de un solo nivel (/es/terminos, etc.)
    # y para ru/ja/de si algún día tienen contenido propio.
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

> ⚠️ **Ubuntu/Debian:** si `/var/www/purgito-landing` es un symlink que
> apunta dentro del `$HOME` del usuario del deploy (patrón actual, ver
> "Dos puntos que ya estaban sin verificar" más abajo), nginx puede devolver
> **500** al servir la landing aunque el symlink y los archivos estén bien.
> Causa: `/home/<usuario>` viene con permisos `750` (`drwxr-x---`) por
> default en Ubuntu/Debian, lo que bloquea a `www-data` (el usuario de
> nginx) de siquiera atravesar ese directorio para llegar al symlink. Esto
> **no pasa en Oracle Linux** -- ahí SELinux + contextos de archivo manejan
> el acceso de otra forma. Fix:
> ```bash
> chmod o+x /home/<usuario>
> chmod -R o+rX /home/<usuario>/purgito-bot/landing
> ```
> `o+x` en el home alcanza para que nginx pueda *atravesarlo* sin poder
> *listarlo* (no expone el resto de archivos del usuario); el `-R o+rX`
> sobre `landing/` es lo que de verdad habilita leer y servir los archivos.

### Cloudflare (DNS + SSL)

1. DNS → Add record tipo `A` por cada host (`purgito.app`, `www`, y los
   `*.purg4t0ry.com` heredados), valor = IP del droplet, proxy ✅ (naranja).
   `panel.purgito.app` ya no se usa: no le hace falta registro.
2. Cloudflare maneja el SSL automáticamente. No necesitas certbot ni HTTPS en nginx.
3. SSL/TLS → Edge Certificates → activa **HSTS**. El panel maneja sesión con
   cookie (`Secure`, per Sección 1/9 de la auditoría), pero eso protege la
   cookie una vez que la conexión ya es HTTPS -- HSTS es lo que evita que el
   PRIMER request de una red hostil (wifi pública, router comprometido)
   viaje en HTTP plano antes de cualquier redirect (sslstrip clásico). Un
   toggle en Cloudflare, no requiere tocar nginx ni la app.

> **Cloudflare cachea la landing.** Si después de un deploy el sitio "no cambia",
> sospecha primero de la caché de Cloudflare (purge) antes de asumir que el
> código está mal.

---

## 8. Actualizar en producción

**El deploy es manual: no hay CI/CD.** El workflow de `.github/workflows/ci.yml`
solo corre lint (`ruff`) sobre los PRs; no despliega nada.

> Después de un deploy en un servidor nuevo (o de cualquier cambio a
> systemd/nginx), correr [`deploy/preflight_check.sh`](deploy/preflight_check.sh)
> antes de darlo por terminado -- chequea `.env`, dependencias del sistema,
> el estado del servicio y que nginx responda bien, todo de una vez.

```bash
ssh <usuario>@<servidor>          # ej. ubuntu@<ip-aws> hoy, opc@<ip-oracle> en el droplet viejo
cd <ruta-del-checkout>             # ej. /home/ubuntu/purgito-bot hoy
git pull
source .venv/bin/activate
pip install -r requirements.txt   # solo si requirements.txt cambió
sudo systemctl restart bot-purg
sudo systemctl status bot-purg
```

> Si `.env.example` tiene variables nuevas, añádelas manualmente a tu `.env` antes de reiniciar.
> No copies `<usuario>`/`<ruta-del-checkout>` de un ejemplo viejo de esta
> guía sin verificar contra el servidor real primero (`whoami`, `pwd`) —
> ambos cambiaron entre el droplet de Oracle y el de AWS, y van a volver a
> cambiar en la próxima migración.

### Desplegar un cambio de infraestructura (systemd, nginx-adjacente)

Un cambio a `deploy/bot-purg.service` (o cualquier archivo que se copia a mano
fuera del checkout, como la config de nginx) **no existe para el droplet
hasta que se pushea y se pullea ahí.** Ya pasó una vez (2026-08-12): un fix
de rutas + hardening en `deploy/bot-purg.service` quedó commiteado solo en
local, nunca llegó al droplet, y al reinstalar el servicio se copió la
versión vieja del unit —con `WorkingDirectory`/`ExecStart` apuntando a una
ruta que ya no existía— y el bot quedó en crash-loop (`status=203/EXEC`)
hasta que se parcheó a mano en caliente.

Antes de tocar el unit de systemd en el droplet:

1. `git diff` local del archivo que vas a desplegar — confirmar que es el
   cambio que creés que es.
2. Commitear y pushear.
3. En el droplet: `git pull`, y después **confirmar con `cat`** que el
   archivo que acabás de bajar es el que esperás — no asumir que el pull
   trajo lo que pensás, es exactamente el paso que faltó la vez anterior.
   ```bash
   cat deploy/bot-purg.service   # ¿dice lo que el repo local dice?
   ```
4. Recién ahí copiar el unit:
   ```bash
   sudo cp deploy/bot-purg.service /etc/systemd/system/bot-purg.service
   sudo systemctl daemon-reload
   sudo systemctl restart bot-purg
   ```
5. **No cortar la sesión SSH todavía.** Mirar que arranque bien en vivo:
   ```bash
   journalctl -u bot-purg -f
   ```
   Si no levanta (`status=203/EXEC`, permisos, rutas que no existen), el
   rollback es volver a copiar la versión anterior del unit (`git show
   HEAD~1:deploy/bot-purg.service > /tmp/bot-purg.service.bak` si hace falta
   reconstruirla) y repetir 4-5 con esa.

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

### Backups de `data/bot.db`

Automatizado con [`deploy/backup_db.sh`](deploy/backup_db.sh): corre diario
por cron, usa `sqlite3 .backup` (no `cp` -- la base corre en modo WAL, `cp`
sobre un archivo en uso puede copiar un estado inconsistente entre
`bot.db`/`bot.db-wal`) y borra los backups de más de 14 días después de cada
corrida exitosa. Antes de esto no había nada automatizado -- solo dos
copias sueltas en `data/` (`bot.db.back-pre-gif-debup`, `bot.db.bak-20260711`)
que alguien sacó a mano antes de una migración riesgosa puntual, en el mismo
disco que la base real.

**No está instalado en el droplet todavía** -- lo de abajo es para aplicar a
mano por SSH, revisando cada paso antes de correrlo. Los comandos concretos
de esta sección son el registro de lo que se verificó en el droplet de
Oracle el 2026-08-12 -- no se re-confirmó todavía en el servidor de AWS
actual (otro usuario, otra ruta). Antes de instalar el cron en cualquier
servidor nuevo, repetir el paso 1 (el `test -r`) con el usuario y la ruta
reales de ESE servidor, no asumir que el resultado de 2026-08-12 sigue
aplicando.

> ⚠️ Sea cual sea el resultado, este backup vive en el mismo disco que la
> instancia (`BACKUP_DIR` es solo "fuera del árbol de git", no "fuera del
> droplet") -- no protege contra perder la instancia entera, que es
> justamente lo que pasó con Oracle. Ver `docs/PORTABILITY.md` § 1 para el
> detalle y la recomendación de subir el backup a R2.

**1. Permisos -- confirmado en Oracle Linux (2026-08-12), pendiente de
re-confirmar en el servidor actual.** El cron corría como `opc`.
Después del `chown -R bot-purg:bot-purg data/` (ronda de hardening de
permisos), se verificó en el droplet que `opc` conserva lectura sobre
`bot.db`:

```bash
$ sudo -u opc test -r /home/opc/purgito-bot/data/bot.db && echo "opc puede leer" || echo "opc NO puede leer"
opc puede leer
```

No hace falta ningún ajuste de grupo. Si en el futuro se re-aplica el
`chown` con bits de permiso distintos y esto deja de cumplirse, el ajuste
mínimo -- sin reabrir el resto del esquema de permisos -- es sumar `opc` al
grupo `bot-purg` y dar lectura de grupo sobre la base:

```bash
sudo usermod -aG bot-purg opc
sudo chmod g+rx /home/opc/purgito-bot/data
sudo chmod g+r /home/opc/purgito-bot/data/bot.db
sudo chmod g+r /home/opc/purgito-bot/data/bot.db-wal /home/opc/purgito-bot/data/bot.db-shm 2>/dev/null || true
```

Cron no necesita que `opc` reabra sesión para que el grupo nuevo tenga
efecto: cada corrida es un proceso nuevo que lee `/etc/group` en el momento.

**2. Instalar el cron.** El destino queda fuera del árbol del repo a
propósito -- si algo corrompe `data/` o rompe el checkout, los backups no
se van con él:

```bash
mkdir -p /home/opc/purgito-bot-backups
crontab -e
```

Agregar (corre a las 3:17 AM, horario de bajo tráfico del bot):

```cron
17 3 * * * DB_SRC=/home/opc/purgito-bot/data/bot.db BACKUP_DIR=/home/opc/purgito-bot-backups /home/opc/purgito-bot/deploy/backup_db.sh >> /home/opc/purgito-bot-backups/backup.log 2>&1
```

**3. Confirmar que corre bien** (opcional, antes de esperar a las 3 AM):

```bash
DB_SRC=/home/opc/purgito-bot/data/bot.db BACKUP_DIR=/home/opc/purgito-bot-backups /home/opc/purgito-bot/deploy/backup_db.sh
cat /home/opc/purgito-bot-backups/backup.log   # si se corrió por cron
ls /home/opc/purgito-bot-backups/
```

**Restaurar desde un backup:**

```bash
sudo systemctl stop bot-purg
sqlite3 /home/opc/purgito-bot/data/bot.db ".restore '/home/opc/purgito-bot-backups/bot-20260812-031700.db'"
sudo systemctl start bot-purg
```

`.restore` sobreescribe la base activa -- parar el bot antes, o se restaura
sobre un archivo con escrituras en curso.

Sigue siendo un backup en el mismo droplet -- protege contra "una migración
corrompió la base" o "se llenó el disco de golpe", no contra "se perdió la
instancia entera". Sacarlo fuera del droplet (al bucket R2 que ya se usa
para GIFs, por ejemplo) queda pendiente como mejora futura, no se implementó
acá.

### Dos puntos que ya estaban sin verificar, confirmados (histórico)

1. **Ruta del clon en el servidor:** en el droplet de Oracle (hasta
   2026-09-05) era `/home/opc/purgito-bot`, corriendo como `opc` (no
   `bot-purg` -- ese usuario dedicado nunca se creó). En el servidor de AWS
   actual es `/home/ubuntu/purgito-bot`, corriendo como `ubuntu` -- mismo
   patrón, otro usuario y otra ruta. Ninguna de las dos es "la" ruta
   correcta: `deploy/bot-purg.service.template` + `deploy/render_service.sh`
   (ver [Configurar systemd](#configurar-systemd)) generan el unit real a
   partir de lo que sea que decidas al clonar, así que esto no debería volver
   a quedar hardcodeado en ningún archivo versionado.
2. **`/var/www/purgito-landing` es un symlink** al `landing/` dentro del
   checkout (confirmado tanto en Oracle como, tras la migración, en AWS).
   `git pull` alcanza para publicar cambios de la landing, no hace falta
   ningún paso de sincronización aparte.

---

## 9. Troubleshooting

| Problema | Causa probable | Fix |
|---|---|---|
| Slash commands no aparecen | `GUILD_ID` no configurado o sin scope `applications.commands` | Poner `GUILD_ID` en `.env` y reiniciar, o esperar 1h si es global |
| GIFs de Discord CDN no se suben a R2 | Faltan vars `R2_*` | Completar todas las `R2_*` en `.env` |
| La galería o el panel no cargan | nginx caído o DNS sin propagar | `systemctl status nginx` + verificar DNS |
| Dashboard da 404 al loguearse, o `/es/dashboard/*` no responde | Faltan `DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET`/`SESSION_SECRET` en `.env` -- el bot arranca igual, sin error visible | `journalctl -u bot-purg \| grep -i "Dashboard deshabilitado"` para confirmar; completar las tres variables (ver sección 4) y reiniciar |
| `.env` "no tiene efecto" / bot no arranca con error de parseo raro | `.env` es un directorio, no un archivo (`mkdir` accidental en vez de `cp`) | `test -f .env`; si falla, `rmdir .env && cp .env.example .env` |
| **[Oracle Linux]** nginx devuelve **502** en los hosts que proxean a `:8080` | SELinux (enforcing por defecto en Oracle Linux) bloquea que nginx abra conexiones de red | `sudo setsebool -P httpd_can_network_connect 1` |
| **[Oracle Linux]** nginx devuelve **403** solo en `purgito.app` | Contexto SELinux incorrecto en `/var/www/purgito-landing` | `sudo restorecon -Rv /var/www/purgito-landing` |
| **[Ubuntu/Debian]** nginx devuelve **500** al servir la landing (sin nada en el log de la app) | `/home/<usuario>` viene `750` por default -- bloquea a `www-data` de atravesar hacia el symlink de `/var/www/purgito-landing`. No aplica en Oracle Linux. | `chmod o+x /home/<usuario>` + `chmod -R o+rX /home/<usuario>/purgito-bot/landing` (ver [Configurar nginx](#configurar-nginx)) |
| `/es/` pelado da **403** (pero `/es/terminos` funciona bien) | Falta el `location = /es/` explícito -- el `try_files` genérico corta en 403 apenas `$uri/` resuelve a un directorio real sin `index.html` adentro | Agregar `location = /es/ { try_files /index.html =404; }` (ver [Configurar nginx](#configurar-nginx)); **nunca** un `return 301`, genera loop infinito con el redirect JS de `index.html` |
| El sitio no cambia después de un `git pull` + restart | Caché de Cloudflare, no el código | Purgear caché en Cloudflare y reintentar |
| El bot arranca pero no lee mensajes | `ENABLE_MESSAGE_CONTENT=false` o intent desactivado en el portal | Activar Message Content Intent en el Developer Portal |
| `ModuleNotFoundError` | venv no activado o `pip install` no corrió | `source .venv/bin/activate && pip install -r requirements.txt` |
| Bot se cae y no reinicia | `Restart=always` no está en el `.service` | Verificar el `.service` y `systemctl daemon-reload` |
| Servicio falla con `status=203/EXEC` aunque el binario anda bien a mano | `ProtectHome`/`ReadOnlyPaths`/`ReadWritePaths`/`ProtectSystem=strict` activados -- combinación no resuelta en systemd real (ver nota en `deploy/bot-purg.service.template`) | Comentar esas 4 directivas en el unit generado, `daemon-reload` + `restart` |
