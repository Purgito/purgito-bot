# Rediseño UX/UI de Bienvenidas / Despedidas / Boosts

## Alcance

Solo frontend: `landing/js/tabs/eventos.js` + `landing/dash.css` (y CSS nueva
compartida con `landing/js/tabs/anuncios.js`, sin tocar su JS). Cero cambios en
`webapi.py`, `db.py` o cogs del bot. Referencia de UX: las 4 capturas en
`referencias/Nekotina/` — modelo de interacción y densidad, no branding.

Explícitamente fuera de alcance (no existen hoy en el backend, no se agregan
en este proyecto): **Ignorar bots**, **Tarjeta con Imagen**.

## Qué ya está bien (no se reestructura)

Iteraciones previas de esta misma sesión ya construyeron: función única
`loadEventPage(eventType)` + `EVENT_CONFIGS` para los 3 módulos, master card
compacta (icono + título + badge de estado + toggle + canal), aviso
contextual de desactivado, secciones de contenido colapsables, acordeón de
opciones avanzadas (Layout V2 + identidad webhook), y preview en vivo sticky.
Esto ya cumple las secciones 3, 4, 5, 12, 14 del pedido original. Se pulen
densidad/espaciado, no se rehacen.

## Cambio real: selector de formato Texto | Embed

Hoy "Mensaje de texto" y "Embed" son dos secciones con toggle independiente
que pueden estar ambas activas (`content_mode: 'composite'`). Pasan a ser un
selector de pills mutuamente excluyente para configuraciones **nuevas**,
reutilizando `.event-mode-pills` / `.mode-pill` / `.mode-pill-icon` — clases
que ya existen en `anuncios.js` pero nunca tuvieron CSS (quedaban sin
estilo). Se define ese CSS una vez; beneficia a ambos módulos.

- Estado JS: `isMessageEnabled` + `isEmbedEnabled` → un solo `format: 'text' |
  'embed'`.
- `currentMessage` y `localEmbedDoc.embeds[0]` viven en memoria siempre,
  sin importar el pill activo. Cambiar de pill solo cambia qué se
  muestra/edita — nunca borra datos en memoria.
- Botones siguen siendo independientes del format (como hoy).
- Layout V2 sigue siendo un toggle dentro de "Opciones avanzadas", no un
  tercer pill — es un paradigma de edición distinto, no existe en Nekotina.

## Configuraciones legacy `composite`

Si `content_mode === 'composite'` y AMBOS mensaje y embed tienen contenido
real al cargar:

- El pill activo por defecto es Embed si tiene contenido real, si no Texto.
- Se muestra un aviso contextual pequeño junto al selector (no un banner
  grande) indicando que hay un [Texto/Embed] guardado además del que se está
  editando, con una acción para cambiar el pill activo y verlo.
- Nada se borra hasta "Guardar". Al guardar, se escribe el formato único
  activo (payload `plain_text`/`classic_embed`, o `composite` si hay
  botones — misma rama de lógica que existe hoy), y la configuración deja de
  ser `composite`.
- Si solo uno de los dos campos tiene contenido real (modo `composite`
  guardado solo por tener botones), no se muestra el aviso — no hay nada
  oculto de verdad.

## Resto de la interfaz

- Editor de Embed: mismos campos y lógica exactos, agrupados visualmente
  (Contenido / Apariencia / Imágenes / Autor & Pie / Campos).
- Botones: misma estructura compacta actual, pulido visual únicamente.
- Preview en vivo: misma estructura, lee `format` en vez de los dos booleans.

## Verificación

- Chequeo de sintaxis (`node --check`) sobre `eventos.js`.
- Revisión visual manual contra las 4 capturas de Nekotina antes de cerrar:
  modelo de interacción (selector, activación, botones, preview), sin copiar
  branding/colores.
- Prueba manual en navegador de los 3 módulos si el entorno lo permite
  (activar, canal, mensaje, cambio de pill, embed, botones, avanzado,
  guardar, prueba, restablecer, responsive <960px). Si no es posible probar
  con sesión real de Discord, se declara explícitamente la limitación.
