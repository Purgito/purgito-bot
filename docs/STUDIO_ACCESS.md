# Purgito Studio — acceso privado por Internet (Cloudflare Access)

Estado: **preparado, sin aplicar**. Nada de esto se ha ejecutado en Cloudflare, en el DNS ni en la VM.
Las secciones «Cambios exactos» y «Procedimiento» dicen qué aplicar y en qué orden.

Sin Cloudflare configurado, Studio sigue funcionando igual que antes: el panel solo escucha en
`127.0.0.1` y se abre por túnel SSH con `admin` + `OBSERVABILITY_TOKEN` (ver [STUDIO.md](STUDIO.md)).

## Arquitectura

```
Navegador ──HTTPS──▶ Cloudflare Access ──▶ Cloudflare Tunnel ──▶ studio-purg ──▶ bot (backend)
            (login + política)             (cloudflared, ya        127.0.0.1:18081   127.0.0.1:8080
                                            instalado en la VM)    verifica el JWT   /internal/studio/*
                                                                   de Access         Bearer interno
```

- **No se publica ningún puerto.** El túnel es saliente: la VM abre la conexión hacia Cloudflare. nginx no
  interviene y su configuración no cambia.
- **El túnel ya existe.** La VM ya ejecuta `cloudflared` (`cloudflared.service`, token en
  `/etc/cloudflared/token`) y se gestiona desde el panel de Cloudflare. Studio añade un nombre de host
  público a ese mismo túnel; no hay conector nuevo ni cambios locales en `cloudflared`.
- **Dos entradas separadas por el `Host`** en el mismo proceso (`scripts/studio.py`):

| Entrada | Host | Autenticación | Para qué |
|---|---|---|---|
| Local | `127.0.0.1:18081` / `localhost:18081` | Basic `admin` + `OBSERVABILITY_TOKEN` | Administración desde el servidor o por túnel SSH. **Se conserva siempre**, incluso si Cloudflare falla. Rechaza cualquier cabecera de proxy. |
| Remota | `STUDIO_PUBLIC_HOST` (p. ej. `studio.purgito.app`) | JWT de Cloudflare Access, **verificado en el origen** | Acceso desde el navegador. Solo existe si las cuatro variables `STUDIO_ACCESS_*` / `STUDIO_PUBLIC_HOST` están definidas. |

No se implementa ningún sistema propio de cuentas, contraseñas ni sesiones: la identidad la resuelve Access.

## Controles de seguridad

| # | Control | Dónde | Si falla |
|---|---|---|---|
| 1 | Política de Access: solo correos autorizados | Cloudflare (borde) | Cloudflare no llega a enviar la petición |
| 2 | Validación del JWT en el túnel (opcional, recomendada) | `cloudflared` | El túnel rechaza antes de reenviar |
| 3 | **Validación del JWT en el panel**: firma RS256 con las claves públicas de nuestro equipo, `iss`, `aud` (esta aplicación), `exp`/`nbf`/`iat` y correo en `STUDIO_ACCESS_EMAILS` | `src/studio/access.py` | 403 |
| 4 | `Host` exacto + par TCP en loopback (solo `cloudflared`, en el mismo host, puede llegar) | `local_server.py` | 404 |
| 5 | Escrituras: `Origin` obligatorio e igual a `https://<host>`, `Sec-Fetch-Site`, JSON y cabecera `X-Studio-Request` (CSRF) | `local_server.py` | 403 |
| 6 | Autenticación de servicio panel → backend: `Bearer` interno; el navegador **nunca** lo ve; el JWT, las cookies y las cabeceras de proxy **no se reenvían** al backend | `local_server.py` | — |
| 7 | El backend conserva sus puertas: loopback, `Host` loopback, sin cabeceras de proxy y token | `src/studio/http.py` | 404 / 401 |
| 8 | CSP estricta (sin scripts ni estilos en línea, sin recursos externos), `frame-ancestors 'none'`, `no-store`, HSTS en la entrada remota | `local_server.py` | — |
| 9 | Falla cerrado: configuración remota a medias = el panel no arranca; sin configuración, ese `Host` responde 404 | `access.py` | — |
| 10 | Mínimo privilegio: el servicio no lee el `.env` del bot (Discord, base de datos, Polar…); solo `/etc/purgito/studio.env` | systemd + prueba | — |

Detalles de la verificación del JWT: solo `RS256` (se rechazan `none`, `HS256` y cualquier otro, también la
confusión RS256/HS256); la identidad sale **solo** de un JWT con firma válida, nunca de cabeceras como
`Cf-Access-Authenticated-User-Email`, que cualquier cliente puede escribir; un token de otra aplicación del
mismo equipo se rechaza por `aud`; las claves se descargan por HTTPS del endpoint del equipo, se cachean 1 h
y un `kid` desconocido no puede forzar descargas (mínimo 5 min entre ellas); si no se pueden obtener las
claves, se **deniega**.

Límites que conviene conocer:

- **No hay roles.** Cualquier persona autorizada puede ver todo y registrar anotaciones. Las notas no guardan
  autor (cambiaría el esquema); la identidad queda solo en el registro de `journald`
  (`studio.access identidad=<correo> POST /internal/studio/annotations`).
- **Quién entra lo decide la política de Access** (fuente de verdad). `STUDIO_ACCESS_EMAILS` repite esa lista
  para que un error en la política (p. ej. «cualquiera con @gmail») no abra el panel.
- **Google + MFA: Access no puede exigir que Google haya hecho MFA.** La regla «Authentication method = mfa» solo
  funciona con Okta, Microsoft Entra y OIDC/SAML genéricos. Con Google, el segundo factor se exige con la **MFA
  independiente de Cloudflare** (app de autenticación, llave de seguridad o biometría), que no depende del
  proveedor. Ver «Quién puede entrar». Con códigos de un solo uso por correo, quien controle el buzón entra.
- El acceso remoto no cambia lo que Studio mide ni guarda: sigue siendo agregado y sin datos de personas.

## Quién puede entrar (decisión pendiente: faltan los correos)

**No se configura ninguna política definitiva hasta tener la lista explícita de correos autorizados.**
Propuesta de partida (preferencia indicada: Google con MFA y sesiones de 8 horas):

- **Identidad:** Google como único método de inicio de sesión de esta aplicación.
- **Política** `Operadores de Studio`: **Allow**, regla **Include → Emails** con la lista explícita (sin
  dominios completos ni «cualquiera con Google»).
- **Segundo factor:** **MFA independiente de Cloudflare** activada en esa política (ver abajo), con app de
  autenticación y/o llave de seguridad. Duración de la autenticación MFA acorde con la sesión (8 h).
- **Sesión de la aplicación:** 8 horas.
- Los mismos correos en `STUDIO_ACCESS_EMAILS` (el panel los vuelve a comprobar contra el JWT).

### Google y MFA, en concreto
- Cloudflare **no puede verificar** que la cuenta de Google tenga la verificación en dos pasos: la exigencia por
  «Authentication method» no está disponible con Google (solo Okta, Entra, OIDC y SAML genéricos). Activar la
  verificación en dos pasos en Google es recomendable, pero Access no lo comprueba.
- Lo que sí se puede exigir es la **MFA independiente de Cloudflare**: *Zero Trust → Access controls → Access
  settings → Allow multi-factor authentication* (elige métodos y duración) y, en la política, *Multi-factor
  authentication (MFA)* con ajustes propios. Cada persona registra su dispositivo en
  `<equipo>.cloudflareaccess.com` → *Account → MFA devices → Add an MFA device* (un autenticador TOTP por
  persona, varias llaves de seguridad o biometrías WebAuthn).
- **A comprobar con tu cuenta antes de depender de ello:** que tu plan de Zero Trust incluya MFA independiente,
  y probar con un usuario real que sin el segundo factor se deniega.
- Cloudflare avisa de que algunos proveedores devuelven valores `amr` no estándar: no se usa la coincidencia por
  `amr`; se usa la MFA independiente.

### Alta de Google como proveedor (una vez)
En Google Cloud Console → *APIs y servicios → Credenciales → Crear ID de cliente de OAuth* (tipo «Aplicación
web»); como URI de redirección autorizada: `https://<equipo>.cloudflareaccess.com/cdn-cgi/access/callback`.
Copia el ID y el secreto de cliente a *Zero Trust → Settings → Authentication → Login methods → Add new →
Google*. El secreto de cliente de Google es un secreto: se pega solo en el panel de Cloudflare.

## Secuencia de activación

Cada paso se verifica antes de pasar al siguiente. Si uno falla, se detiene y se revierte solo ese paso.
Nada de esto se ha ejecutado.

1. **Merge aprobado, con el CI en verde.** Lo decide una persona; no se fusiona automáticamente. El único fallo
   admisible es el de `pip-audit` por Pillow 12.3.0, ajeno a Studio, mientras la PR #136 no se integre.
2. **Instalación y verificación del servicio local en la VM** («En la VM» abajo): código desplegado, entorno
   `/etc/purgito/studio.env`, unit `studio-purg`. Verificación local: 401 en la entrada local sin contraseña,
   403 en la remota sin JWT, 404 con otro `Host`, y solo 127.0.0.1 en escucha. **El bot no se reinicia.**
3. **Cloudflare Access** con la **lista explícita de correos** (sin definir aún) y MFA: aplicación
   `studio.purgito.app`, Google como único método, política Allow por correos y MFA independiente, sesión de 8 h.
4. **Validación de la identidad en el origen:** `STUDIO_ACCESS_TEAM`, `STUDIO_ACCESS_AUD` (la etiqueta de la
   aplicación del paso 3) y `STUDIO_ACCESS_EMAILS` en `/etc/purgito/studio.env`; reiniciar solo `studio-purg`;
   el registro debe decir «Acceso remoto activo…». Sin la etiqueta AUD correcta el panel rechaza todo (falla
   cerrado), que es lo esperado hasta este paso.
5. **Ruta pública del túnel existente:** `studio.purgito.app` → `http://127.0.0.1:18081`, con *Protect with
   Access* activado. Solo después de los pasos 3 y 4.
6. **Pruebas reales, permitido y denegado, sin exponer tokens:** (a) un correo autorizado entra, supera la MFA y
   ve el panel; (b) una cuenta de Google **no** autorizada es rechazada por Access; (c) un correo autorizado
   **sin** segundo factor registrado no entra; (d) sin sesión, `curl` a `/` y a `/internal/studio/report` da 302
   al inicio de sesión de Cloudflare, nunca datos; (e) en `journalctl -u studio-purg` aparece la identidad del
   acceso permitido y el código del denegado, sin el token.
7. **Verificación del frontend con datos reales:** las siete vistas, filtros, comparación, tablas, anotaciones y
   estados vacíos con los datos productivos, en escritorio y móvil. Hasta aquí solo se ha probado con datos
   sintéticos.
8. **Reversión sin afectar al bot** (sección «Reversión»): cortar la ruta del túnel, o `systemctl stop
   studio-purg`, o quitar la aplicación de Access. El bot, la base de datos y los datos de Studio no se tocan.

## Cambios exactos

El orden importa: **primero la aplicación de Access, después la ruta del túnel**. Aunque se invirtiera, el
panel exige el JWT en el origen y respondería 403, pero no hay motivo para abrir esa ventana.

### En Cloudflare (Zero Trust)

1. **Proveedor de identidad.** *Settings → Authentication*: añade **Google** (ver arriba) y activa la **MFA
   independiente** (*Access controls → Access settings*).
2. **Aplicación de Access.** *Access → Applications → Add an application → Self-hosted*:
   - Nombre: `Purgito Studio`. Duración de sesión: `8 hours`. Métodos de inicio de sesión aceptados: **solo
     Google** (desactiva One-time PIN para esta aplicación).
   - Dominio de la aplicación: `studio.purgito.app`, **sin ruta** (así protege también `/internal/*`).
   - Política `Operadores de Studio`: acción **Allow**, *Include → Emails* con la lista aprobada, y en la
     política la **MFA independiente** activada (app de autenticación y/o llave de seguridad).
   - En los ajustes de cookies: *HTTP Only* activado.
   - Guarda y copia la **Application Audience (AUD) Tag** (64 caracteres hex) → `STUDIO_ACCESS_AUD`.
   - El **nombre del equipo** (`<equipo>.cloudflareaccess.com`) está en *Settings → Custom pages* → `STUDIO_ACCESS_TEAM`.
3. **Ruta del túnel.** *Networks → Tunnels →* el túnel existente *→ Public Hostname → Add*:
   - Subdominio `studio`, dominio `purgito.app`, ruta vacía.
   - Servicio: tipo **HTTP**, URL `127.0.0.1:18081`.
   - En *Additional application settings → Access*: activa **Protect with Access** y elige la aplicación
     (segunda validación del JWT, en el propio túnel).
4. **DNS.** No debería hacer falta tocarlo. Hoy `*.purgito.app` resuelve a Cloudflare (inferido de consultas
   públicas; no he visto el panel de DNS): `studio.purgito.app` responde ya un 404 de Cloudflare porque el
   túnel no tiene esa ruta. Si al crear la ruta el panel avisa de un registro en conflicto, sustituye el
   existente por el que propone el túnel.

### En la VM (usuario con `sudo`)

```bash
cd /home/purgito/purgito-bot            # con el código de Studio ya desplegado (ver «Actualización»)

# 1. Entorno del servicio. Sin mostrar secretos: solo se copia OBSERVABILITY_TOKEN, sin imprimirlo.
sudo install -d -m 0755 /etc/purgito
sudo install -m 0600 -o root -g root /dev/null /etc/purgito/studio.env
grep -E '^OBSERVABILITY_TOKEN=' .env | sudo tee -a /etc/purgito/studio.env >/dev/null
read -rp 'Equipo (<equipo>.cloudflareaccess.com): ' TEAM
read -rp 'AUD tag (64 hex): ' AUD
read -rp 'Correos autorizados (coma): ' EMAILS
printf 'WEB_PORT=8080\nSTUDIO_ACCESS_TEAM=%s\nSTUDIO_ACCESS_AUD=%s\nSTUDIO_PUBLIC_HOST=studio.purgito.app\nSTUDIO_ACCESS_EMAILS=%s\n' \
  "$TEAM" "$AUD" "$EMAILS" | sudo tee -a /etc/purgito/studio.env >/dev/null
sudo stat -c '%a %U:%G %n' /etc/purgito/studio.env        # esperado: 600 root:root

# 2. Servicio
deploy/render_studio_service.sh purgito /home/purgito/purgito-bot > /tmp/studio-purg.service
sudo cp /tmp/studio-purg.service /etc/systemd/system/studio-purg.service
systemd-analyze security studio-purg.service | tail -1     # exposición baja («OK»)
sudo systemctl daemon-reload && sudo systemctl enable --now studio-purg
journalctl -u studio-purg -n 15 --no-pager
```

El registro debe decir `Acceso local en http://127.0.0.1:18081` y `Acceso remoto activo para
studio.purgito.app (N correos autorizados, ...)`. **El bot no se reinicia**: `bot-purg` y `studio-purg` son
unidades independientes, y un fallo de una no afecta a la otra.

## Verificación

Antes de crear la ruta en Cloudflare (desde la VM):

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18081/                              # 401 (local, sin contraseña)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: studio.purgito.app' http://127.0.0.1:18081/ # 403 (remota, sin JWT)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: otro.example' http://127.0.0.1:18081/       # 404
ss -ltn | grep 18081                                                                          # solo 127.0.0.1
```

Después de crear la aplicación y la ruta (desde fuera, sin sesión):

```bash
curl -sI https://studio.purgito.app/ | head -3                       # 302 al login de Cloudflare, nunca 200
curl -s -o /dev/null -w '%{http_code}\n' https://studio.purgito.app/internal/studio/report   # 302, nunca datos
```

En el navegador: abrir `https://studio.purgito.app`, identificarse con Google con un correo autorizado, superar la
MFA y comprobar que el panel carga; con uno **no** autorizado, que Access lo rechaza; y con uno autorizado pero
sin segundo factor, que no entra. Confirmar en `journalctl -u studio-purg`
una línea `studio.access identidad=<correo> GET /`. Un acceso denegado en el origen deja
`studio.access denegado status=403 motivo=<código>` (sin el token).

## Actualización

Studio se actualiza con el mismo procedimiento que el bot (la VM no hace `git pull`: se lleva el código con
`git bundle`, ver la memoria de despliegue), y después:

```bash
sudo systemctl restart studio-purg     # solo el panel; el bot sigue sin interrupción
```

Si cambia la lista de correos, edita `/etc/purgito/studio.env` **y** la política de Access, y reinicia el
servicio. Si se rota `OBSERVABILITY_TOKEN` en el `.env` del bot, copia el nuevo valor a
`/etc/purgito/studio.env` (mismo comando de arriba, sustituyendo la línea) y reinicia **ambos** servicios.

## Reversión

Del menos al más drástico; ninguno toca los datos de Studio ni el bot:

1. **Cortar solo Internet:** en Cloudflare, elimina la ruta pública `studio.purgito.app` del túnel (o
   `sudo systemctl stop studio-purg`). El panel local por túnel SSH sigue disponible.
2. **Quitar la entrada remota del panel:** borra las variables `STUDIO_ACCESS_*`/`STUDIO_PUBLIC_HOST` de
   `/etc/purgito/studio.env` y `sudo systemctl restart studio-purg`: ese `Host` pasa a responder 404.
3. **Quitar el servicio:** `sudo systemctl disable --now studio-purg`, y borra
   `/etc/systemd/system/studio-purg.service` y `/etc/purgito/studio.env`.
4. **Quitar la aplicación de Access** en Cloudflare cuando ya no haya ruta.

Administración local de emergencia, sin Cloudflare ni servicio:
`cd <checkout> && .venv/bin/python scripts/studio.py` + `ssh -L 18081:127.0.0.1:18081 <usuario>@<vm>` y abrir
`http://127.0.0.1:18081` (usuario `admin`, contraseña `OBSERVABILITY_TOKEN`). Desactivar Studio por completo
sigue siendo `STUDIO_ENABLED=false` en el `.env` del bot (ver STUDIO.md): conserva los datos.

## Qué cubren las pruebas

`tests/test_studio_access.py`: configuración todo-o-nada; JWT válido/caducado/futuro, firma alterada,
otra clave, emisor, audiencia (incluida la de otra aplicación), correo, algoritmo (`none`, `HS256`, mayúsculas…),
`kid`, rotación de claves y descargas acotadas, fallo del endpoint de claves; entrada remota con/sin JWT, con
identidad suplantada por cabecera, con `Host` ajeno; que el token interno, el JWT y las cookies no cruzan al
navegador/backend; CSRF de escrituras; entrada local intacta; peers que no son loopback; y que el proceso del
panel no carga la configuración del bot. Las comprobaciones de seguridad se validaron además por mutación
(debilitar cada control hace fallar al menos una prueba).

No probado (requiere cuenta y red reales): el flujo de login de Access, la descarga de claves desde Cloudflare
y el arranque del servicio bajo systemd en la VM.
