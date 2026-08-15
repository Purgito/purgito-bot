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

## Regla de uso de ⓘ (`helpIcon`)

Un tooltip se agrega solo si su ausencia puede llevar a una decisión
equivocada (ej.: "0 = sin límite" en un number field que si no lo sabés,
pensás que 0 es inválido). No se agrega si la interfaz ya lo dice sola (ej.:
un campo llamado "Roles exentos del límite" no necesita un ⓘ aclarando que
"exento" significa "no cuenta acá").

## Backlog (no implementar todavía — anotado para cuando duela)

- **Canales → matriz**: con muchos canales (ej. 100) pierde legibilidad.
  Eventualmente necesita búsqueda/filtro, quizás un toggle "solo
  configurados".
