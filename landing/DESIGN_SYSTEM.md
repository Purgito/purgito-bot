# Sistema de diseño del dashboard (piloto: CHAT)

Documenta patrones que ya existen y se repitieron dentro del tab CHAT
(`js/dash.js` + `dash.css`), para no reinventarlos al propagar la misma
arquitectura de información a GIFS/MEMES/EMBEDS/PREMIUM/YOUTUBE/HISTORIAL.
No es una spec de componentes que todavía no existen — si CHAT no tiene un
patrón hoy (estado vacío, modal de confirmación), no está acá; se documenta
cuando haya una instancia real.

No confundir con `docs/*.md`: esto es referencia interna para quien toca el
código, no una página pública — `build_docs.py` no lo toca.

## Paleta

Cian de marca como color de **acción/estado**, no decorativo — botones
primarios, valores activos, foco. Definido en `style.css`:

- `--accent: hsl(186 84% 46%)` — fondos de CTA.
- `--accent-2: hsl(186 84% 62%)` — texto/íconos sobre fondo oscuro (links,
  valores destacados como en `.ovr-row.is-override > label`).
- `--accent-soft: #76A6A6` — detalles secundarios, apagados.

## `probabilityField` (dash.js:519)

Input numérico (0–100) + `<progress class="prob-bar">` de solo lectura debajo,
en vez de un slider. El número es la fuente de verdad; la barra es feedback
visual del mismo valor, nunca al revés.

## Chips de canales/roles seleccionados

`channelToggleList`/`roleToggleList` (dash.js:328/616): dropdown con checklist
+ los elegidos abajo como chips con `×` para sacarlos. Mismo patrón para
ambos, roles es la versión sin el problema de permisos de canales.

## Cards de Comportamiento — cadena numerada

`.chain` / `.chain-step` (dash.css:1650): un número (①②③) + título en
pregunta + campos, para pasos que ocurren en secuencia real en el código
(cogs/chat.py). El ⓘ del título dice qué camino (mención vs. espontáneo) pasa
por ese paso — no un párrafo permanente aparte.

## Tabla de Canales — matriz habla/responde/aprende

`.chan-matrix` (dash.css:1766): una fila por canal, una columna por lista
(spontaneous/mention/corpus), checkbox por celda. Cabecera con ⓘ por columna
porque el comportamiento de "lista vacía" es asimétrico entre columnas (ver
`spontaneous_channels`/`mention_channels` vs. `corpus_allowed_channels` en
`CLAUDE.md`) — no adivinable mirando la tabla sola.

Filtro (`channelMatrix`, dash.js): input de texto por nombre + checkbox
"Solo configurados" (un canal cuenta si `cols.some(c => c.isSelected(id))`),
combinables. Si el filtro no deja ninguna fila visible se muestra
`emptyState('Ningún canal coincide con el filtro.')` en vez de dejar la tabla
en blanco sin explicación. `applyFilter()` se vuelve a llamar después de
cada cambio de checkbox de la matriz (no solo al tipear), porque "Solo
configurados" depende de ese estado.

## Estados vacíos y de carga

- **Una línea, tono atenuado**: `emptyState(msg)` (core/dom.js) — para avisos
  breves ("Todavía no hay GIFs guardados…"). Es el default; no le agregues
  ícono ni card a menos que el contexto lo pida.
- **Ícono + título + descripción (+ acción opcional)**: `richEmptyState({icon,
  title, desc, action})` (core/dom.js) — para un módulo vacío que merece más
  contexto que una línea (Anuncios sin ningún anuncio, Playground sin
  canales utilizables). Antes existían `.sim-empty-state` (playground) y
  `.empty-state-card` (anuncios) duplicando el mismo layout con nombres
  distintos; ahora es un único componente sobre `.card.empty-state-card`.
- **Spinner solo**: `spinner()` — carga de una sección completa (reemplaza
  todo el contenido de la caja mientras se pide al backend).
- **Spinner + mensaje en card**: `loadingCard(msg)` — espera localizada que
  no reemplaza toda la sección (ej. el resultado del simulador de CHAT
  mientras corre una simulación), donde un spinner solo no explica qué está
  pasando.

No dupliques estos patrones bajo un nombre nuevo por módulo (`sim-*`,
`*-card` ad hoc) — si el layout ya existe acá, importalo.

## Override por canal — mostrar el valor, no explicar de dónde sale

`channelOverrideRow` (dash.js:547): el estado hereda/propio ya lo carga el
input (atenuado + sin ↺ si hereda; normal + ↺ si no). Debajo de cada campo,
`.ovr-caption` muestra la cifra real:

- Hereda: `"20 mensajes · valor del servidor"`.
- Propio: `"valor propio de este canal"`.

Reemplaza un párrafo único arriba de la grilla explicando la regla en
abstracto — la cifra concreta por campo es más rápida de leer y no obliga a
recordar una regla mientras se mira el input.

## Navegación lateral persistente y sticky (Dashboard)

`.dash-sidebar` (dash.css): barra lateral sticky (`top: 5.5rem`) que contiene las
secciones del Dashboard organizadas por categorías conceptuales (Principal, Alertas,
Anuncios, Automatización, Entretenimiento, Utilidades, Premium). Cada módulo cuenta
con una única ubicación coherente y canónica.

- **Modo Rail lateral colapsable persistente**: El usuario puede colapsar o expandir el sidebar
  en cualquier momento mediante el botón en la cabecera (`.dash-sidebar-collapse-btn`, 48px de ancho).
  El estado colapsado o expandido se persiste en `localStorage` (`purgito_dash_sidebar_collapsed`)
  y se mantiene inalterado al navegar entre módulos.
- **Móviles (`<= 860px`)**: Se presenta mediante un selector desplegable accesible (`.dash-mobile-nav-toggle`),
  optimizando el espacio en pantallas pequeñas.

## Checklist de primeros pasos (INICIO)

`buildOnboardingChecklist(stats, style, corpusChannelsCount)` (dash.js)
arma un checklist de 3 pasos en la parte superior de INICIO: canales de
aprendizaje elegidos (`corpusChannelsCount > 0`, de un fetch aparte a
`/settings/corpus` en `loadInicio` — **no** `stats.reading_channels`, que
cuenta canales NO ignorados, una lista totalmente distinta que no baja a 0
al sacar canales del corpus; ver "Configuración del chat" en CLAUDE.md),
si ya aprendió algo (`stats.corpus_total > 0`) y si el estilo del bot fue
personalizado (`style.nick` o `style.avatar_url`). Se autooculta apenas los
tres están completos — no queda como recordatorio permanente en un
servidor ya configurado.

El paso de "aprende de los mensajes nuevos" no tiene botón de acción:
pasa solo apenas hay canales elegidos, sin ningún comando — la instrucción
de `/setup`/`/refeed_channels` que muestra como texto (`.dim`) es solo para
adelantar el historial que ya existía antes de elegir el canal, no un paso
obligatorio (por eso el copy no dice "historial" en el título, para no
sonar como si repitiera el paso 1).

No todos los admins quieren completar los 3 pasos (personalizar nombre/
avatar, sobre todo, es opcional para muchos). `onboarding-dismiss-btn` en
el header oculta el checklist a mano aunque falten pasos, guardado por
servidor en `localStorage` (`purgito_onboarding_dismissed`, un array de
guild IDs) — un admin con varios servidores puede descartarlo en uno y
dejarlo en otro. Es aparte del autooculte por completar los 3 pasos: uno
es "ya terminé", el otro es "no me interesa".

## Aviso de cupo en la sidebar

`loadQuotaAlerts()` (dash.js) pide `/api/server/:id/stats` al entrar al
dashboard o cambiar de servidor (no solo al abrir INICIO, que ya mostraba
este mismo aviso como texto) y guarda en `_quotaAlerts` qué módulos están al
90% o más de su cupo. `renderSidebar` pinta un punto (`.quota-alert-dot`)
sobre el ícono del módulo correspondiente — ámbar si está cerca, rojo
(`.is-full`) si ya llegó al tope — con el detalle en el `title` del link.

A diferencia de `.badge` (oculto en modo rail por `.dash-sidebar.collapsed
.badge`), el punto se sigue viendo con la sidebar colapsada: un cupo por
agotarse no debería depender de que el admin tenga el panel expandido.

Cubre los cupos que además **bloquean** agregar más al llegar al tope
(GIFs, frases) — no el corpus de mensajes aprendidos, que al llegar a su
límite simplemente empieza a rotar los más viejos en vez de trabar nada, así
que no hay una acción urgente que avisar ahí.

## Borrado con deshacer

`confirmDelBtn` (dom.js) pide confirmar en dos pasos antes de ejecutar una
baja; eso evita el click accidental, pero hasta ahora una vez confirmada la
baja era instantánea e irreversible. `undoableDelete(row, {message,
onDelete, errorMessage})` (core/dom.js) agrega la segunda red: al confirmar,
la fila se atenúa (`.is-pending-delete`) y un toast con acción "Deshacer"
da unos segundos antes de recién ahí llamar a `onDelete` (el DELETE real).
Deshacer solo cancela el temporizador y restaura la fila — nunca se llegó a
tocar el backend, así que no hace falta un endpoint de "restaurar".

En uso: frases y triggers (con `confirmDelBtn` + `undoableDelete` en
cadena) y los chips de la colección de reacciones (un solo click, sin
`confirmDelBtn` — perder un emoji es trivial de deshacer). Los packs de
frases quedan solo con `confirmDelBtn`, sin `undoableDelete`: borrar un pack
mueve sus frases al pool default del servidor, un efecto que "deshacer" no
podría revertir limpiamente sin lógica de backend extra — ofrecer un botón
de deshacer que no deshace todo sería peor que no ofrecerlo. El botón de
amnesia (tab Servidor → General) es el mismo caso: borra directo en el
backend, sin deshacer posible, así que también va solo con `confirmDelBtn`
(antes tenía su propia reimplementación local del mismo patrón de dos
pasos, con texto sin traducir — quedó reemplazada por el helper).

`confirmDelBtn` trae de fábrica la clase `.gif-actions` en su wrapper
(pensada para el pie angosto de una card de GIF: botones a ~50% de ancho,
texto chico). En un contexto con más espacio, como el botón de amnesia,
hay que neutralizar ese tamaño envolviendo el resultado en un contenedor
propio y pisando `.gif-actions .btn` ahí adentro (ver `.amnesia-confirm` en
dash.css) — no editar la regla base, que sí es la correcta para su uso
original en GIFs/frases/triggers.

## Regla de uso de ⓘ (`helpIcon`)

Un tooltip se agrega solo si su ausencia puede llevar a una decisión
equivocada (ej.: "0 = sin límite" en un number field que si no lo sabes,
pensás que 0 es inválido). No se agrega si la interfaz ya lo dice sola (ej.:
un campo llamado "Roles exentos del límite" no necesita un ⓘ aclarando que
"exento" significa "no cuenta acá").

## Nivel de acceso "Gestor" (co-admin sin MANAGE_GUILD)

El dashboard tenía un solo nivel de acceso: MANAGE_GUILD/owner de Discord
(`check_guild_access`/`@guild_api` en webapi.py), todo o nada. "Gestor" es
un segundo nivel, más chico, que el admin real delega eligiendo un ROL de
Discord (tab Servidor → General → "Rol de Gestor", `settings.manager_role_id`)
— cualquier miembro con ese rol entra al panel sin necesitar el permiso de
Discord "Gestionar servidor".

Alcance fijo, no configurable por módulo: Anuncios, Embeds, Frases,
Triggers, Reacciones, GIFs, YouTube, Twitch, RSS (+ `/channels` y `/roles`
de solo lectura, que esas áreas necesitan para sus selectores). Todo lo
demás — Premium, Canales, Chat, Estilo, Estadísticas, Historial, Updates,
el propio General — sigue admin-only. Se decidió así (un nivel fijo, no
permisos granulares por módulo) para no multiplicar la superficie de
autorización: una tabla de permisos por módulo es mucho más código y mucho
más fácil de dejar mal configurada que una lista fija y auditable.

`GESTOR_ALLOWED_MODULES` en dash.js (sidebar/paleta de comandos/redirect en
`activate()`) tiene que reflejar EXACTAMENTE la misma lista de módulos que
`guild_api_manager` en webapi.py acepta del lado del servidor — son dos
listas independientes a propósito (frontend no es el límite de seguridad
real, solo evita que un Gestor vea un link que le va a tirar 403), pero
tienen que coincidir o alguien legítimo no encuentra cómo llegar a algo que
sí puede usar, o ve un link a algo que no puede.

`guild_api_manager` es casi una copia de `guild_api` (mismo cuerpo, cambia
`check_guild_access` por `check_guild_manager_access`) a propósito: se
prefirió duplicar ~15 líneas antes que agregarle un parámetro a `guild_api`
y arriesgar los ~90 endpoints que ya lo usaban. `check_guild_manager_access`
nunca mira permisos de Discord (a diferencia de MANAGE_GUILD): solo si el
usuario tiene, ahora mismo, el rol puntual configurado (`fetch_member`, no
sesión ni cache OAuth). Al guardar el rol, `_api_manager_role_put` rechaza
@everyone (le daría Gestor a todo el servidor de un click) y roles
`managed` (Nitro Booster, integraciones) — no son errores de tipeo, son
casos reales que un admin puede elegir sin querer.

Tener el rol de Gestor NO implica ver todo el servidor en Discord (a
diferencia de MANAGE_GUILD): puede haber canales de staff privados que ni
el bot le muestra a ese miembro puntual. `_gestor_channel_visibility`
(webapi.py) filtra eso — `None` si la request es de un admin real (sin
filtrar, ve todo como siempre), o una función que solo deja pasar los
canales que ESE miembro puntual puede ver en Discord si es Gestor. Se
aplica en los dos lugares donde un canal entra por ID: `_api_channels`
(la lista que alimenta todos los selectores de canal del panel) y
`_reject_gestor_hidden_channel` (el mismo criterio, pero para los
handlers que reciben un channel_id directo en el body en vez de pasar por
`_resolve_target_channel` — frase_channels, frase_pack_channels,
triggers, YouTube, Twitch, RSS). Sin esto, ocultarle el canal en el
picker no alcanzaba: un Gestor que ya conocía o adivinaba el ID podía
mandar el request a mano igual.

## Backlog (no implementar todavía — anotado para cuando duela)

- **Canales → matriz**: filtro de texto + toggle "solo configurados" ya
  implementados (ver arriba). Con cientos de canales el registro completo
  igual se sigue enviando al cliente entero — si eso duele, el siguiente
  paso es paginar o virtualizar la lista, no el filtro en sí.
