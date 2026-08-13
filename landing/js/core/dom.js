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
  chat:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  corpus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  smile:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>',
  sparkle:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/></svg>',
  play:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>',
  image:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/></svg>',
  film:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg>',
  star:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  layout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
  info:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  members:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
};

export function icon(name) {
  const s = el('span', { class: 'nav-icon' });
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
