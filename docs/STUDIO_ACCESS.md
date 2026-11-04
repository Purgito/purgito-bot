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
- Con códigos de un solo uso por correo (One-time PIN), quien controle un buzón autorizado entra. Si eso
  preocupa, usa un proveedor de identidad con MFA (Google, GitHub…) en la misma política.
- El acceso remoto no cambia lo que Studio mide ni guarda: sigue siendo agregado y sin datos de personas.

## Quién puede entrar (decisión pendiente)

Propuesta de partida, a confirmar:

- Política **Allow**, regla **Include → Emails** con los operadores de Purgito (lista corta y nominal).
- Proveedor: **One-time PIN** (ya viene activo, sin configurar nada) o Google con MFA.
- Duración de sesión: **8 horas**.
- Mismos correos en `STUDIO_ACCESS_EMAILS`.

## Cambios exactos

El orden importa: **primero la aplicación de Access, después la ruta del túnel**. Aunque se invirtiera, el
panel exige el JWT en el origen y respondería 403, pero no hay motivo para abrir esa ventana.

### En Cloudflare (Zero Trust)

1. **Proveedor de identidad.** *Settings → Authentication*: comprueba que *One-time PIN* está habilitado (o
   añade el proveedor elegido).
2. **Aplicación de Access.** *Access → Applications → Add an application → Self-hosted*:
   - Nombre: `Purgito Studio`. Duración de sesión: `8 hours`.
   - Dominio de la aplicación: `studio.purgito.app`, **sin ruta** (así protege también `/internal/*`).
   - Política `Operadores de Studio`: acción **Allow**, *Include → Emails* con la lista aprobada.
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

En el navegador: abrir `https://studio.purgito.app`, identificarse con un correo autorizado y comprobar que
el panel carga; con uno **no** autorizado, que Access lo rechaza. Confirmar en `journalctl -u studio-purg`
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
