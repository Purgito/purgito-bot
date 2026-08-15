// Helpers de DOM puros (sin fetch, sin estado del panel). el() es la fábrica de
// nodos que usa todo el resto.
//
// guildIcon y embedImg viven acá (no en perfil.js / classic-editor.js como
// podría sugerir dónde nacieron): ambos los comparten varios módulos —
// guildIcon lo usan perfil.js y dash.js; embedImg lo usan core/markdown.js y
// embeds/shared-ui.js— así que su lugar natural es este módulo base, que no
// importa a nadie.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node[k] = v;
    else if (k === 'checked' || k === 'value') node[k] = v;
    // style vía cssText, no setAttribute: la CSP del sitio (ver LANDING_CSP
    // en build_docs.py) no tiene 'unsafe-inline' en style-src, y CSP trata
    // el atributo style="..." (sea escrito en el HTML o puesto con
    // setAttribute) como estilo inline -- lo bloquea igual. cssText, como
    // cualquier asignación a propiedades de node.style, no pasa por el
    // atributo y CSP no lo toca. Sin este caso especial, todo color/display
    // dinámico armado con el(..., { style }) — la barra de color de los
    // embeds, los puntos de color de roles, los toggles de display:none —
    // quedaba viniendo transparente/sin aplicar en producción.
    else if (k === 'style') node.style.cssText = v;
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function spinner() { return el('div', { class: 'spinner' }); }

export function emptyState(msg) { return el('div', { class: 'empty-state' }, msg); }

export function flash(container, ok, msg) {
  const box = el('div', { class: 'flash ' + (ok ? 'flash-ok' : 'flash-err') }, msg);
  container.prepend(box);
  setTimeout(() => box.remove(), 3000);
}

// Toast flotante reusable: esquina inferior izquierda, una sola instancia
// (requiere <div id="toast"></div> en la página). Es la confirmación de todo
// lo que se autoguarda al click en INICIO y CHAT; `type` es 'ok' | 'err' |
// 'warn' y el CSS le da a cada uno un color distinto. flash() sigue existiendo
// para los avisos que van pegados a un formulario, no flotando.
let _toastTimer = null;
// action opcional: { label, onclick } — para avisos que ofrecen deshacer/
// descartar algo (ej. el borrador recuperado). El resto de llamadas sigue
// pasando solo (msg, type).
export function toast(msg, type, action) {
  const box = document.getElementById('toast');
  if (!box) return;
  box.innerHTML = '';
  box.append(document.createTextNode(msg));
  if (action) {
    box.append(el('button', {
      class: 'toast-action',
      onclick: () => { clearTimeout(_toastTimer); box.className = ''; action.onclick(); },
    }, action.label));
  }
  box.className = 'show ' + (type || '');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { box.className = ''; }, action ? 6000 : 3200);
}

export function renderError(box, e) {
  box.innerHTML = '';
  box.append(el('p', { class: 'error' }, e.message));
}

export function guildIcon(g) {
  if (g.icon_url) return el('img', { class: 'guild-icon', src: g.icon_url, alt: '' });
  return el('div', { class: 'guild-icon guild-initial' }, (g.name || '?').trim().charAt(0).toUpperCase());
}

export function delBtn(box, fn, reload) {
  return el('button', {
    class: 'btn btn-danger btn-sm',
    onclick: async () => {
      try { await fn(); reload(); }
      catch (e) { flash(box, false, e.message); }
    },
  }, 'Quitar');
}

/* Borrado en dos pasos: botón -> "<pregunta> ✓ ✗" -> ejecuta o cancela.
   Mismo patrón que ya usaban GIFs, YouTube y Amnesia; acá se factoriza para
   que frases, packs, triggers y reacciones dejen de borrar con un solo click
   sin confirmar (no tienen undo, y un pack además devuelve sus frases al pool
   default del servidor).

   `question` es la pregunta completa: cuando la acción tiene un efecto
   colateral, decilo ahí y no en un genérico "¿Seguro?". */
export function confirmDelBtn(question, onConfirm, { label = 'Quitar' } = {}) {
  const wrap = el('div', { class: 'gif-actions' });

  function showButton() {
    wrap.innerHTML = '';
    wrap.append(el('button', {
      class: 'btn btn-danger btn-sm', onclick: showConfirm,
    }, label));
  }

  function showConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      question,
      el('button', { class: 'btn btn-danger btn-sm', onclick: run }, '✓'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButton }, '✗')));
  }

  async function run() {
    // Vuelve al botón antes de await: si onConfirm recarga la lista, este
    // nodo ya no existe cuando termine, y tocar wrap.innerHTML ahí no haría
    // nada visible igual.
    showButton();
    await onConfirm();
  }

  showButton();
  return wrap;
}

// Imagen que se oculta sola si la URL no carga (igual que hace Discord).
export function embedImg(attrs) {
  const img = el('img', attrs);
  img.onerror = () => { img.style.display = 'none'; };
  return img;
}

// Íconos de línea (estilo Lucide, currentColor, viewBox 24). Se inyectan por
// innerHTML sobre un <span class="nav-icon">; el parser HTML del navegador crea
// los nodos SVG con el namespace correcto.
const ICONS = {
  chat:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  corpus:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  smile:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
  sparkle:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/></svg>',
  play:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>',
  image:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/></svg>',
  film:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg>',
  star:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  layout:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
  info:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  members:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  home:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
  youtube:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"/><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"/></svg>',
  history:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  panelClose:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/><path d="M16 15l-3-3 3-3"/></svg>',
  panelOpen:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/><path d="M13 15l3-3-3-3"/></svg>',
  menu:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
  search:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  x:            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  settings:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  sliders:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>',
  palette:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.563-2.512 5.563-5.563C22 6.5 17.5 2 12 2z"/></svg>',
  zap:          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
  bell:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
  clock:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  trash:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
  activity:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
  shoppingBag:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>',
  chevronDown:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
  chevronRight: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>',
  check:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  newspaper:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/></svg>',
  server:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>',
  externalLink: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
  command:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3 3 3 0 0 0-3-3H6a3 3 0 0 0-3 3 3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3 3 3 0 0 0-3 3 3 3 0 0 0 3 3h12a3 3 0 0 0 3-3 3 3 0 0 0-3-3z"/></svg>',
};

export function icon(name) {
  const s = el('span', { class: 'nav-icon', 'aria-hidden': 'true' });
  s.innerHTML = ICONS[name] || '';
  return s;
}

// Ícono "?" con tooltip nativo (title): para contexto breve donde un párrafo
// .dim sería ruido — junto a un label compacto, un toggle en una fila densa.
// Para explicaciones más largas seguí usando un <p class="dim"> como en el
// resto del panel (ver formGroup/accordionGroup).
export function helpIcon(msg) {
  const s = icon('info');
  s.classList.add('help-icon');
  s.title = msg;
  s.tabIndex = 0;
  return s;
}

// Grupo de campos con eyebrow-caret (la firma de Purgito). El caret ▍ es
// decorativo y se pinta con ::before en CSS, así el lector de pantalla no lo
// anuncia antes del título.
export function formGroup(title, ...children) {
  return el('div', { class: 'form-group' },
    el('div', { class: 'form-group-title' }, title), ...children);
}

// Variante colapsable de formGroup (editor de embeds clásico): <details>
// nativo, así el toggle es accesible (teclado, lector de pantalla) sin JS.
// `open` indica si arranca expandido — se pasa según el estado del embed.
export function accordionGroup(title, open, ...children) {
  return el('details', { class: 'embed-group', open: open ? '' : null },
    el('summary', { class: 'embed-group-title' }, title),
    el('div', { class: 'embed-group-body' }, ...children));
}

// Estado vacío del preview con el caret parpadeante en vez de un rectángulo muerto.
export function previewEmpty(msg) {
  return el('div', { class: 'preview-empty' },
    el('div', { class: 'caret', 'aria-hidden': 'true' }, '▍'),
    el('div', {}, msg || 'Tu embed aparecerá acá…'));
}

// Error de validación inline y persistente (a diferencia del toast). Vaciar con msg falsy.
export function showFormAlert(box, msg) {
  box.innerHTML = '';
  if (msg) box.append(el('div', { class: 'form-alert', role: 'alert' }, msg));
}

// Textarea que crece con su contenido (tope 400px, luego scroll interno).
export function autoGrow(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 400) + 'px';
}
