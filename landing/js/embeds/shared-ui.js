// Helpers de UI compartidos por ambos editores de embeds + el ruteo del tab
// Embeds (loadEmbeds / renderEmbedEditor / renderEmbedTemplates) y la carga de
// un link compartido. Es el módulo más acoplado del bloque de embeds.

import {
  GUILD_ID, emojiCache, setEmojiCache, uploadedImagesCache, setUploadedImagesCache,
} from '/js/core/config.js';
import { apiFetch, humanError } from '/js/core/api.js';
import { el, spinner, emptyState, icon, toast, embedImg, renderError, helpIcon } from '/js/core/dom.js';
import { discordTimestampText } from '/js/core/markdown.js';
import {
  detectGif, docFromLayout, docFromEmbeds, templateSnippet, layoutSnippet, colorToHex,
  MAX_WEBHOOK_USERNAME,
} from '/js/embeds/state.js';
import {
  _embedTab, _embedMode, setEmbedTab, setEmbedMode, setLayoutDoc, setEmbedDoc,
} from '/js/embeds/session.js';
import { getRoles, getChannels, content } from '/js/panel-shell.js';
import { saveHistorySnapshot } from '/js/embeds/persistence.js';
import { renderClassicEditor } from '/js/embeds/classic-editor.js';
import { renderLayoutEditor } from '/js/embeds/layout-editor.js';

// Modal genérico del panel (historial, JSON). Cierra con ✗, click afuera o Escape.
export function panelModal(title, body) {
  const overlay = el('div', {
    class: 'modal-overlay',
    onclick: (e) => { if (e.target === overlay) overlay.remove(); },
  },
    el('div', { class: 'modal-box' },
      el('div', { class: 'modal-head' },
        el('strong', {}, title),
        el('button', { class: 'btn btn-secondary btn-sm', onclick: () => overlay.remove() }, '✗')),
      body));
  overlay.tabIndex = -1;
  overlay.onkeydown = (e) => { if (e.key === 'Escape') overlay.remove(); };
  document.body.append(overlay);
  overlay.focus();
  return overlay;
}

export async function getEmojis() {
  if (!emojiCache) setEmojiCache((await apiFetch(`/api/server/${GUILD_ID}/emojis`)).emojis);
  return emojiCache;
}

// Galería de imágenes ya subidas por este guild (persistente entre sesiones y
// plantillas — R2 dedupe por contenido, esto solo lista qué URLs subió el
// guild). Cache en config.js, igual criterio que getEmojis.
export async function getUploadedImages() {
  if (!uploadedImagesCache) setUploadedImagesCache((await apiFetch(`/api/server/${GUILD_ID}/embeds/uploads`)).urls);
  return uploadedImagesCache;
}

// Emojis unicode comunes con palabras clave en español para el buscador.
// Lista curada a propósito (un índice completo de unicode pesa cientos de KB).
const EMOJI_LIST = [
  ['😀', 'sonrisa feliz'], ['😂', 'risa llorar'], ['🤣', 'carcajada risa'], ['😊', 'sonrisa tierna'],
  ['😍', 'enamorado corazones'], ['🥰', 'amor carino'], ['😎', 'lentes cool'], ['🤔', 'pensando duda'],
  ['😅', 'risa nervios'], ['😭', 'llorar triste'], ['😢', 'lagrima triste'], ['😡', 'enojado furia'],
  ['🥺', 'ojitos porfa'], ['😴', 'dormir sueno'], ['🤯', 'explota mente'], ['😱', 'grito susto'],
  ['🙄', 'ojos vueltos'], ['😉', 'guino'], ['🤗', 'abrazo'], ['🤫', 'silencio secreto'],
  ['👍', 'pulgar arriba ok'], ['👎', 'pulgar abajo'], ['👏', 'aplausos'], ['🙌', 'manos celebrar'],
  ['🙏', 'gracias rezar porfa'], ['💪', 'fuerza musculo'], ['🤝', 'apreton trato'], ['👋', 'hola chau saludo'],
  ['✌️', 'paz victoria'], ['🤞', 'suerte dedos'], ['👀', 'ojos mirando'], ['🧠', 'cerebro'],
  ['❤️', 'corazon rojo amor'], ['🧡', 'corazon naranja'], ['💛', 'corazon amarillo'], ['💚', 'corazon verde'],
  ['💙', 'corazon azul'], ['💜', 'corazon violeta'], ['🖤', 'corazon negro'], ['💔', 'corazon roto'],
  ['✨', 'brillos destellos'], ['⭐', 'estrella'], ['🌟', 'estrella brillante'], ['🔥', 'fuego'],
  ['💥', 'explosion boom'], ['🎉', 'fiesta confeti festejo'], ['🎊', 'festejo bola confeti'], ['🎈', 'globo'],
  ['🎁', 'regalo'], ['🏆', 'trofeo campeon'], ['🥇', 'medalla oro primero'], ['🎮', 'juego gamer control'],
  ['🎵', 'musica nota'], ['🎶', 'musica notas'], ['🎤', 'microfono cantar'], ['🎬', 'cine claqueta'],
  ['📢', 'anuncio megafono'], ['📣', 'megafono aviso'], ['🔔', 'campana notificacion'], ['🔕', 'campana silencio'],
  ['📌', 'pin fijado'], ['📍', 'ubicacion pin'], ['📎', 'clip adjunto'], ['🔗', 'link enlace'],
  ['📅', 'calendario fecha'], ['⏰', 'reloj alarma'], ['⏳', 'reloj arena espera'], ['🕐', 'reloj hora'],
  ['✅', 'check listo verde'], ['❌', 'cruz error rojo'], ['⚠️', 'advertencia cuidado'], ['🚫', 'prohibido'],
  ['❓', 'pregunta duda'], ['❗', 'exclamacion importante'], ['💡', 'idea foco'], ['🔒', 'candado bloqueado'],
  ['🔓', 'candado abierto'], ['🔑', 'llave'], ['⚙️', 'engranaje config'], ['🛠️', 'herramientas'],
  ['📝', 'nota escribir'], ['📖', 'libro leer'], ['📊', 'grafico estadisticas'], ['💰', 'dinero bolsa'],
  ['💎', 'diamante gema'], ['🚀', 'cohete lanzamiento'], ['🌈', 'arcoiris'], ['☀️', 'sol'],
  ['🌙', 'luna noche'], ['⛈️', 'tormenta lluvia'], ['❄️', 'nieve copo'], ['🌊', 'ola mar'],
  ['🍕', 'pizza'], ['🍔', 'hamburguesa'], ['🌮', 'taco'], ['🍦', 'helado'],
  ['☕', 'cafe'], ['🍺', 'cerveza'], ['🐱', 'gato'], ['🐶', 'perro'],
  ['🦊', 'zorro'], ['🐸', 'rana'], ['🐢', 'tortuga'], ['🦆', 'pato'],
];

// Inserta texto en la posición del cursor del input/textarea activo y dispara
// 'input' para que los handlers existentes actualicen estado + preview.
export function insertAtCursor(input, text) {
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  input.value = input.value.slice(0, start) + text + input.value.slice(end);
  const pos = start + text.length;
  input.selectionStart = input.selectionEnd = pos;
  input.focus();
  input.dispatchEvent(new Event('input'));
}

// --- Popover unificado de inserción (menciones / fecha / emoji) ---

let _insPop = null;
let _insPopAnchor = null;
let _insPopFrame = null;

export function closeInsertPopover() {
  if (_insPop) { _insPop.remove(); _insPop = null; }
  _insPopAnchor = null;
  if (_insPopFrame !== null) {
    cancelAnimationFrame(_insPopFrame);
    _insPopFrame = null;
  }
  document.removeEventListener('pointerdown', _insPopOutside);
  document.removeEventListener('mousedown', _insPopOutside);
  document.removeEventListener('scroll', _insPopScroll, true);
  window.removeEventListener('resize', _scheduleInsertPopoverPosition);
  window.removeEventListener('orientationchange', _scheduleInsertPopoverPosition);
  window.visualViewport?.removeEventListener('resize', _scheduleInsertPopoverPosition);
  window.visualViewport?.removeEventListener('scroll', _scheduleInsertPopoverPosition);
}
function _insPopOutside(e) {
  if (_insPop && !_insPop.contains(e.target) && (!_insPopAnchor || !_insPopAnchor.contains(e.target))) {
    closeInsertPopover();
  }
}
// El popover es position:fixed anclado a su campo; si el formulario o contenedor
// se mueve por debajo, el popover se reposiciona o cierra si el campo sale de vista.
function _insPopScroll(e) {
  if (_insPop && !_insPop.contains(e.target)) {
    _scheduleInsertPopoverPosition();
  }
}

// Los `position: fixed` se calculan contra el viewport visible. En Safari
// móvil ese viewport cambia al abrir el teclado, contraer la barra URL o rotar
// el dispositivo; requestAnimationFrame agrupa los eventos de resize/scroll en
// una sola lectura y escritura por frame.
function _positionInsertPopover() {
  _insPopFrame = null;
  if (!_insPop || !_insPopAnchor || !_insPopAnchor.isConnected) {
    closeInsertPopover();
    return;
  }
  const margin = 8;
  const anchor = _insPopAnchor.getBoundingClientRect();
  const pop = _insPop.getBoundingClientRect();
  const viewport = window.visualViewport;
  const left = viewport ? viewport.offsetLeft : 0;
  const top = viewport ? viewport.offsetTop : 0;
  const width = viewport ? viewport.width : window.innerWidth;
  const height = viewport ? viewport.height : window.innerHeight;

  // Si el anchor quedó completamente fuera de la vista visible, cerrar.
  if (anchor.bottom < top || anchor.top > top + height) {
    closeInsertPopover();
    return;
  }

  // Decidir si abrir hacia abajo o hacia arriba según el espacio libre en el viewport
  const spaceBelow = top + height - anchor.bottom - 4;
  const spaceAbove = anchor.top - top - 4;
  const fitsBelow = spaceBelow >= pop.height;

  let calculatedTop;
  if (fitsBelow || spaceBelow >= spaceAbove) {
    calculatedTop = anchor.bottom + 4;
  } else {
    calculatedTop = anchor.top - pop.height - 4;
  }

  const maxLeft = Math.max(left + margin, left + width - pop.width - margin);
  const maxTop = Math.max(top + margin, top + height - pop.height - margin);

  _insPop.style.left = Math.max(left + margin, Math.min(anchor.left, maxLeft)) + 'px';
  _insPop.style.top = Math.max(top + margin, Math.min(calculatedTop, maxTop)) + 'px';
}

function _scheduleInsertPopoverPosition() {
  if (_insPopFrame !== null) cancelAnimationFrame(_insPopFrame);
  _insPopFrame = requestAnimationFrame(_positionInsertPopover);
}

const INS_TAB_LABELS = { menciones: 'Menciones', fecha: 'Fecha', emoji: 'Emoji' };

export function openInsertPopover(anchor, input, tabs, initialTab) {
  closeInsertPopover();
  const pop = el('div', { class: 'ins-pop' });
  const body = el('div', { class: 'ins-pop-body' });
  let active = initialTab && tabs.includes(initialTab) ? initialTab : tabs[0];
  const tabBar = el('div', { class: 'ins-pop-tabs' });

  function renderTabs() {
    tabBar.innerHTML = '';
    for (const t of tabs) {
      tabBar.append(el('div', {
        class: 'ins-pop-tab' + (t === active ? ' active' : ''),
        onclick: () => {
          active = t;
          renderTabs();
          renderBody().finally(_scheduleInsertPopoverPosition);
        },
      }, INS_TAB_LABELS[t]));
    }
  }

  function insert(text, ev) {
    insertAtCursor(input, text);
    // Shift+click mantiene el popover abierto para insertar varios seguidos.
    if (!ev || !ev.shiftKey) closeInsertPopover();
  }

  async function renderBody() {
    body.innerHTML = '';
    if (active === 'menciones') {
      body.append(spinner());
      let roles, channels;
      try { [roles, channels] = await Promise.all([getRoles(), getChannels()]); }
      catch (e) { body.innerHTML = ''; body.append(el('p', { class: 'error' }, e.message)); _scheduleInsertPopoverPosition(); return; }
      body.innerHTML = '';
      const search = el('input', { type: 'text', placeholder: 'Buscar rol o canal…' });
      const list = el('div', { class: 'ins-pop-list' });
      function renderList() {
        const q = search.value.trim().toLowerCase();
        list.innerHTML = '';
        for (const r of roles) {
          if (q && !r.name.toLowerCase().includes(q)) continue;
          list.append(el('div', { class: 'ins-pop-item', onclick: (ev) => insert(`<@&${r.id}>`, ev) },
            el('span', { class: 'ins-dot', style: 'background:' + (r.color !== '#000000' ? r.color : 'var(--text-muted)') }),
            '@' + r.name));
        }
        for (const c of channels) {
          if (q && !c.name.toLowerCase().includes(q)) continue;
          list.append(el('div', { class: 'ins-pop-item', onclick: (ev) => insert(`<#${c.id}>`, ev) }, '#' + c.name));
        }
        if (!list.children.length) list.append(el('p', { class: 'dim', style: 'padding:8px' }, 'Sin resultados'));
        _scheduleInsertPopoverPosition();
      }
      search.oninput = renderList;
      body.append(search, list);
      renderList();
      search.focus();
    } else if (active === 'fecha') {
      // datetime-local nativo, redondeado al minuto actual.
      const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      const dt = el('input', { type: 'datetime-local', value: now });
      const list = el('div', { class: 'ins-pop-list' });
      const STYLES = [
        ['t', 'Hora corta'], ['T', 'Hora con segundos'], ['d', 'Fecha corta'],
        ['D', 'Fecha larga'], ['f', 'Fecha y hora'], ['F', 'Fecha y hora completa'],
        ['R', 'Relativo (hace / en…)'],
      ];
      // El formato en sí (Intl.DateTimeFormat/RelativeTimeFormat) vive en
      // discordTimestampText, compartido con el renderer del Preview.
      function renderStyles() {
        const date = dt.value ? new Date(dt.value) : new Date();
        list.innerHTML = '';
        for (const [code, label] of STYLES) {
          list.append(el('div', {
            class: 'ins-pop-item',
            onclick: (ev) => insert(`<t:${Math.floor(date.getTime() / 1000)}:${code}>`, ev),
          },
            el('span', { class: 'ins-item-label' }, label),
            el('span', { class: 'dim' }, discordTimestampText(date, code))));
        }
        _scheduleInsertPopoverPosition();
      }
      dt.onchange = renderStyles;
      body.append(el('div', { class: 'field' }, dt), list);
      renderStyles();
    } else {
      // emoji
      const search = el('input', { type: 'text', placeholder: 'Buscar emoji…' });
      const grid = el('div', { class: 'ins-emoji-grid' });
      let custom = [];
      try { custom = await getEmojis(); } catch (e) { /* sin custom, unicode igual sirve */ }
      function renderGrid() {
        const q = search.value.trim().toLowerCase();
        grid.innerHTML = '';
        for (const em of custom) {
          if (q && !em.name.toLowerCase().includes(q)) continue;
          const code = `<${em.animated ? 'a' : ''}:${em.name}:${em.id}>`;
          grid.append(el('button', {
            class: 'ins-emoji', title: ':' + em.name + ':',
            onclick: (ev) => insert(code, ev),
          }, embedImg({ src: em.url, alt: em.name, class: 'ins-emoji-img' })));
        }
        for (const [ch, keywords] of EMOJI_LIST) {
          if (q && !keywords.includes(q)) continue;
          grid.append(el('button', { class: 'ins-emoji', onclick: (ev) => insert(ch, ev) }, ch));
        }
        if (!grid.children.length) grid.append(el('p', { class: 'dim', style: 'padding:8px' }, 'Sin resultados'));
        _scheduleInsertPopoverPosition();
      }
      search.oninput = renderGrid;
      body.append(search, grid);
      renderGrid();
      search.focus();
    }
  }

  pop.append(tabBar, body);
  pop.onkeydown = (e) => { if (e.key === 'Escape') { closeInsertPopover(); input.focus(); } };
  document.body.append(pop);
  _insPop = pop;
  _insPopAnchor = anchor;
  document.addEventListener('pointerdown', _insPopOutside);
  document.addEventListener('mousedown', _insPopOutside);
  document.addEventListener('scroll', _insPopScroll, true);
  window.addEventListener('resize', _scheduleInsertPopoverPosition);
  window.addEventListener('orientationchange', _scheduleInsertPopoverPosition);
  window.visualViewport?.addEventListener('resize', _scheduleInsertPopoverPosition);
  window.visualViewport?.addEventListener('scroll', _scheduleInsertPopoverPosition);
  renderTabs();
  _scheduleInsertPopoverPosition();
  renderBody().finally(_scheduleInsertPopoverPosition);
}

// Envuelve un input/textarea con el botón de inserción asistida + atajos
// Ctrl/Cmd+M (menciones), Ctrl/Cmd+P (fecha), Ctrl/Cmd+E (emoji).
export function insertWrap(input, tabs) {
  const btn = el('button', {
    type: 'button', class: 'ins-btn', title: 'Insertar mención, fecha o emoji',
    onclick: () => openInsertPopover(btn, input, tabs),
  });
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>';
  const SHORTCUTS = { m: 'menciones', p: 'fecha', e: 'emoji' };
  input.addEventListener('keydown', (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || ev.shiftKey) return;
    const tab = SHORTCUTS[ev.key.toLowerCase()];
    // preventDefault SOLO para las combinaciones propias (no pisar otras del navegador).
    if (tab && tabs.includes(tab)) { ev.preventDefault(); openInsertPopover(btn, input, tabs, tab); }
  });
  return el('div', { class: 'ins-wrap' }, input, btn);
}

// --- Subida directa de imágenes (5.2) ---

export async function uploadImageBlob(blob) {
  let r;
  try {
    r = await fetch(`/api/server/${GUILD_ID}/embeds/upload`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': blob.type || 'application/octet-stream' },
      body: blob,
    });
  } catch (e) {
    throw new Error('No se pudo conectar con el servidor.');
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || humanError(r.status));
  // El backend ya la indexó en la galería persistente del guild; si el cache
  // local ya está cargado, adelantamos el resultado sin esperar un refetch.
  if (uploadedImagesCache && !uploadedImagesCache.includes(data.url)) {
    setUploadedImagesCache([data.url, ...uploadedImagesCache]);
  }
  return data.url;
}

// Resuelve un link de tenor.com/view/... al .gif animado real (Fase 4) —
// corre del lado del servidor porque CORS no deja pegarle a tenor.com desde
// acá. null si no se pudo (el caller cae al aviso manual de siempre).
export async function resolveTenorUrl(url) {
  try {
    const resp = await apiFetch(`/api/server/${GUILD_ID}/embeds/resolve-gif`, {
      method: 'POST', body: { url },
    });
    return resp.url || null;
  } catch (e) {
    return null;
  }
}

// --- Subida de archivos para bloques File de Layout V2 (Fase 2 ronda 2) ---
// A diferencia de uploadImageBlob, esto NO persiste en R2: el backend lo
// guarda en memoria del proceso con un TTL corto (ver _pending_layout_files
// en webapi.py), solo hasta que se manda con "Enviar ahora" — por eso este
// tipo de bloque no se puede programar ni guardar en plantillas. Devuelve
// { id, filename } para guardar en el bloque; el id es lo único que el envío
// necesita para encontrar los bytes reales.
export async function uploadLayoutFile(file) {
  let r;
  try {
    r = await fetch(`/api/server/${GUILD_ID}/embeds/upload-file/${encodeURIComponent(file.name)}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
  } catch (e) {
    throw new Error('No se pudo conectar con el servidor.');
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || humanError(r.status));
  return { id: data.upload_id, filename: data.filename };
}

// Modal con la galería de imágenes ya subidas por el guild; clickear una la
// elige. Carga perezosa (solo al abrir), no en cada render del campo.
function openImageLibrary(onPick) {
  const body = el('div', { class: 'img-library' }, spinner());
  panelModal('Imágenes subidas antes', body);
  getUploadedImages().then((urls) => {
    body.innerHTML = '';
    if (!urls.length) {
      body.append(emptyState('Todavía no subiste ninguna imagen en este servidor.'));
      return;
    }
    const grid = el('div', { class: 'img-library-grid' });
    for (const u of urls) {
      grid.append(el('button', {
        type: 'button', class: 'img-library-item', title: u,
        onclick: () => { onPick(u); document.querySelector('.modal-overlay')?.remove(); },
      }, embedImg({ src: u, alt: '' })));
    }
    body.append(grid);
  }).catch((e) => { body.innerHTML = ''; body.append(el('p', { class: 'error' }, e.message)); });
}

const _PASTE_HINT = /mac/i.test(navigator.platform || '') ? '⌘V' : 'Ctrl+V';

// Widget combinado de imagen: URL manual + subir archivo + pegar del
// portapapeles + reusar ya subida. Guarda la URL final en obj[key].
export function imageField(obj, key, onChange, opts = {}) {
  const wrap = el('div', { class: 'img-field' });

  function set(url) { obj[key] = url; onChange(); render(); }

  async function handleUpload(file) {
    // Estado de carga claro dentro del widget (no dejar el botón inerte).
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'img-uploading' }, spinner(), el('span', {}, 'Subiendo imagen…')));
    try {
      const url = await uploadImageBlob(file);
      set(url);
      toast('Imagen subida', 'ok');
    } catch (e) {
      // El error queda visible en el campo (además del toast), no solo un toast
      // que desaparece.
      render();
      wrap.prepend(el('div', { class: 'img-error' }, 'No se pudo subir: ' + e.message));
      toast(e.message, e.status === 429 ? 'warn' : 'err');
    }
  }

  function render() {
    wrap.innerHTML = '';
    const val = (obj[key] || '').trim();
    if (val) {
      wrap.append(el('div', { class: 'img-chip' },
        embedImg({ src: val, class: 'img-chip-thumb', alt: '' }),
        el('span', { class: 'img-chip-name', title: val }, val.length > 42 ? val.slice(0, 42) + '…' : val),
        el('button', { class: 'btn btn-danger btn-sm', onclick: () => set('') }, '✗')));
      return;
    }

    const url = el('input', { type: 'url', placeholder: '…o pega un enlace de imagen' });
    const gifNote = el('div', { class: 'embed-gif-note' });
    url.oninput = () => {
      if (!opts.gif) return;
      const d = detectGif(url.value);
      gifNote.className = 'embed-gif-note' + (d ? (d.warn ? ' warn' : ' ok') : '');
      gifNote.textContent = d ? d.note : '';
    };
    url.onchange = async () => {
      let v = url.value.trim();
      if (!v) return;
      if (opts.gif) {
        const d = detectGif(v);
        if (d && !d.warn) {
          v = d.url; // Giphy: se deriva del lado del cliente, sin ir al backend.
        } else if (d && d.warn) {
          // Tenor: la página no expone el .gif directo en la URL misma (a
          // diferencia de Giphy), así que hay que resolverla del lado del
          // servidor (CORS no deja pegarle a tenor.com desde el navegador).
          // Si falla, se manda igual la URL de la página como antes de esto
          // — queda como chip roto con el mismo aviso manual de siempre.
          gifNote.className = 'embed-gif-note';
          gifNote.textContent = 'Resolviendo GIF de Tenor…';
          const resolved = await resolveTenorUrl(v);
          if (resolved) v = resolved;
        }
      }
      set(v);
    };

    const fileInput = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/gif,image/webp', style: 'display:none' });
    fileInput.onchange = () => { if (fileInput.files[0]) handleUpload(fileInput.files[0]); };
    // Ajuste 5.2: "Subir" es la acción primaria (visual y funcionalmente), el
    // campo de URL pasa a secundario para que el usuario no-técnico no vea
    // "esto empieza con una URL".
    const uploadBtn = el('button', { type: 'button', class: 'btn btn-primary', onclick: () => fileInput.click() },
      icon('image'), 'Subir imagen');
    const uploadHint = helpIcon('PNG, JPG, GIF o WEBP, hasta 8 MB.');
    const pasteBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm', title: 'También puedes pegar con ' + _PASTE_HINT + ' con el campo enfocado',
      onclick: async () => {
        // clipboard.read() solo anda en Chromium con permiso; el paste con
        // teclado (listener de abajo) es el camino universal.
        try {
          const items = await navigator.clipboard.read();
          for (const item of items) {
            const type = item.types.find(t => t.startsWith('image/'));
            if (type) { handleUpload(await item.getType(type)); return; }
          }
          toast('No hay imagen en el portapapeles', 'warn');
        } catch (e) {
          toast('Usa ' + _PASTE_HINT + ' con el campo de URL enfocado', 'warn');
        }
      },
    }, 'Pegar (' + _PASTE_HINT + ')');
    url.addEventListener('paste', (ev) => {
      const file = [...(ev.clipboardData?.files || [])].find(f => f.type.startsWith('image/'));
      if (file) { ev.preventDefault(); handleUpload(file); }
    });

    const libraryBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm',
      onclick: () => openImageLibrary(set),
    }, 'Elegir de subidas anteriores');
    const secondary = el('div', { class: 'img-field-secondary' }, url, pasteBtn, libraryBtn);
    wrap.append(
      el('div', { class: 'img-field-primary' }, uploadBtn, fileInput, uploadHint),
      secondary, gifNote);
  }

  render();
  return wrap;
}

// Presets rápidos: el acento propio de Purgito primero, después un puñado de
// colores reconocibles (paleta de Discord + básicos) — mismo criterio que los
// swatches de rol de Discohook, sin pretender cubrir cada hue posible.
const COLOR_PRESETS = [
  ['#13C4D8', 'Purgito'], ['#ED4245', 'Rojo'], ['#FEE75C', 'Amarillo'],
  ['#57F287', 'Verde'], ['#5865F2', 'Blurple'], ['#EB459E', 'Rosa'],
  ['#9B59B6', 'Violeta'], ['#FFFFFF', 'Blanco'], ['#2B2D31', 'Negro'],
];

// Swatch nativo + input de texto para hex, sincronizados en ambos sentidos,
// más una fila de presets rápidos.
export function colorField(obj, key, onChange) {
  const swatch = el('input', { type: 'color', value: /^#[0-9a-fA-F]{6}$/.test(obj[key]) ? obj[key] : '#8B6EF5' });
  const text = el('input', {
    type: 'text',
    class: 'color-hex-input',
    value: obj[key] || '',
    placeholder: '#8B6EF5',
    maxlength: '7',
    spellcheck: 'false',
  });

  swatch.oninput = () => {
    obj[key] = swatch.value;
    text.value = swatch.value;
    text.classList.remove('invalid');
    onChange();
  };

  text.oninput = () => {
    let v = text.value.trim();
    if (v && !v.startsWith('#')) v = '#' + v;
    if (v === '') {
      obj[key] = '';
      text.classList.remove('invalid');
      onChange();
      return;
    }
    if (/^#[0-9a-fA-F]{6}$/.test(v)) {
      obj[key] = v;
      swatch.value = v;
      text.classList.remove('invalid');
      onChange();
    } else {
      // Se deja escribir libremente (por si está a medio pegar/tipear), pero
      // no se guarda en `obj` ni se dispara onChange hasta que sea un hex
      // válido de 6 dígitos.
      text.classList.add('invalid');
    }
  };

  text.onblur = () => { text.value = obj[key] || ''; text.classList.remove('invalid'); };

  const presets = el('div', { class: 'color-presets' });
  for (const [hex, name] of COLOR_PRESETS) {
    presets.append(el('button', {
      type: 'button', class: 'color-preset', style: 'background:' + hex, title: name,
      onclick: () => { obj[key] = hex; swatch.value = hex; text.value = hex; text.classList.remove('invalid'); onChange(); },
    }));
  }

  return el('div', { class: 'color-field-wrap' }, el('div', { class: 'color-field' }, swatch, text), presets);
}

// Panel colapsable (details/summary nativo) con las opciones de envío.
// `channels` (con can_manage_webhooks por canal, ver _api_channels) y `chSel`
// (el <select> de canal destino ya armado por el caller) son opcionales —
// sin ellos simplemente no se muestra el aviso de permisos de Fase 4.
export function sendOptionsPanel(o, roles, channels, chSel) {
  const silent = el('input', { type: 'checkbox', checked: o.silent });
  silent.onchange = () => { o.silent = silent.checked; };
  const restrict = el('input', { type: 'checkbox', checked: o.restrict });
  const roleSel = el('select', { multiple: 'multiple', size: '5', class: 'send-opts-roles' });
  for (const r of roles) {
    const opt = el('option', { value: r.id }, '@' + r.name);
    opt.selected = o.roleIds.includes(r.id);
    roleSel.append(opt);
  }
  roleSel.onchange = () => { o.roleIds = [...roleSel.selectedOptions].map(x => x.value); };
  const roleBlock = el('div', { class: 'field', style: o.restrict ? '' : 'display:none' },
    el('label', {}, 'Roles que SÍ pueden ser pingueados (vacío = nadie; Ctrl+click para varios)'),
    roleSel);
  restrict.onchange = () => { o.restrict = restrict.checked; roleBlock.style.display = o.restrict ? '' : 'none'; };

  // Identidad personalizada (Fase 3): completar cualquiera de los dos hace
  // que el envío pase de channel.send() a un webhook propio del canal (ver
  // wants_custom_identity en message_options.py) — los botones de rol siguen
  // funcionando igual, el webhook sigue siendo de la app de Purgito.
  const username = el('input', {
    type: 'text', maxlength: String(MAX_WEBHOOK_USERNAME), placeholder: 'Purgito', value: o.username,
  });
  username.oninput = () => { o.username = username.value; };
  const avatarField = imageField(o, 'avatarUrl', () => {});

  // Aviso proactivo (Fase 4): un permiso de canal faltante recién se
  // enteraba al enviar y llevarse el error del webhook — esto lo anticipa
  // apenas se elige el canal. No bloqueante: el resto del formulario sigue
  // usable, el aviso solo dice que ESTOS DOS campos no van a funcionar ahí.
  const identityWarn = el('div', { class: 'embed-warn', style: 'display:none' });
  function refreshIdentityWarn() {
    if (!channels || !chSel) return;
    const ch = channels.find(c => c.id === chSel.value);
    const blocked = !!ch && ch.can_manage_webhooks === false;
    identityWarn.style.display = blocked ? '' : 'none';
    identityWarn.textContent = blocked
      ? 'El bot no tiene permiso de "Gestionar webhooks" en este canal, así '
        + 'que nombre/avatar personalizado no va a funcionar acá — revisa '
        + 'los permisos del canal o vuelve a invitar al bot.'
      : '';
  }
  if (chSel) chSel.addEventListener('change', refreshIdentityWarn);
  refreshIdentityWarn();

  const identityBlock = el('div', { class: 'field' },
    el('label', {}, 'Nombre y avatar personalizado'),
    el('p', { class: 'dim' },
      'Si completas alguno, el mensaje se manda con un webhook propio del '
      + 'canal en vez de como Purgito — los botones siguen funcionando igual.'),
    identityWarn,
    el('div', { class: 'embed-two' },
      el('div', {}, el('label', {}, 'Nombre'), username),
      el('div', {}, el('label', {}, 'Avatar'), avatarField)));

  const details = el('details', { class: 'send-opts' },
    el('summary', {}, 'Opciones de envío'),
    el('div', { class: 'field' }, el('label', { class: 'toggle' }, silent, 'Envío silencioso (sin notificación push)')),
    el('div', { class: 'field' }, el('label', { class: 'toggle' }, restrict, 'No mencionar a nadie salvo lo explícito')),
    roleBlock,
    identityBlock);
  if (o.silent || o.restrict || o.username || o.avatarUrl) details.open = true;
  return details;
}

export async function loadEmbeds() {
  closeInsertPopover();
  // Cambiar de tab/bloque/modo también persiste una versión en el historial.
  saveHistorySnapshot();
  const box = content();
  const tabs = el('div', { class: 'embed-tabs' },
    el('div', { class: 'embed-tab' + (_embedTab === 'editor' ? ' active' : ''), onclick: () => { setEmbedTab('editor'); loadEmbeds(); } }, 'Crear / Enviar'),
    el('div', { class: 'embed-tab' + (_embedTab === 'templates' ? ' active' : ''), onclick: () => { setEmbedTab('templates'); loadEmbeds(); } }, 'Mis plantillas'));
  const view = el('div', {});
  box.append(tabs, view);
  if (_embedTab === 'editor') await renderEmbedEditor(view);
  else await renderEmbedTemplates(view);
}

function modeRadio(mode, label) {
  return el('label', { class: 'toggle' },
    el('input', {
      type: 'radio', name: 'contentMode', checked: _embedMode === mode,
      onchange: () => { setEmbedMode(mode); loadEmbeds(); },
    }), label);
}

export async function renderEmbedEditor(box) {
  box.append(spinner());
  let channels, roles;
  // roles solo lo usa el modo Layout (botones de "asignar rol"), pero
  // getChannels/getRoles cachean tras la primera visita, así que pedirlo
  // siempre es barato y evita otro roundtrip al cambiar de modo.
  try { [channels, roles] = await Promise.all([getChannels(), getRoles()]); }
  catch (e) { renderError(box, e); return; }
  box.innerHTML = '';

  // Selector de modo: embeds clásicos vs Layout V2 (excluyentes en Discord).
  box.append(el('div', { class: 'embed-mode-sel' },
    modeRadio('classic', 'Embeds clásicos'),
    modeRadio('layout', 'Layout V2')));
  const inner = el('div', {});
  box.append(inner);
  if (_embedMode === 'layout') renderLayoutEditor(inner, channels, roles);
  else renderClassicEditor(inner, channels, roles);
}

export async function renderEmbedTemplates(box) {
  box.append(spinner());
  let data;
  try { data = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`); }
  catch (e) { renderError(box, e); return; }
  box.innerHTML = '';

  box.append(el('p', { class: 'dim gif-stats' },
    el('strong', { class: 'stat-num' }, String(data.total)), ` / ${data.limit} plantillas usadas`));

  if (!data.templates.length) {
    box.append(emptyState('Todavía no hay plantillas guardadas — crea una desde "Crear / Enviar".'));
    return;
  }

  const list = el('ul', { class: 'item-list' });
  for (const t of data.templates) {
    const isLayout = t.content_mode === 'layout_v2';
    const embeds = t.embeds || [];
    const first = embeds.find(x => x && Object.keys(x).length) || {};
    const color = colorToHex(first.color) || '#8B6EF5';
    const badge = isLayout
      ? el('span', { class: 'badge badge-premium' }, 'LAYOUT')
      : (embeds.length > 1 ? el('span', { class: 'badge' }, embeds.length + ' embeds') : null);
    const snippet = isLayout ? layoutSnippet(t.layout) : templateSnippet(embeds);
    // Payload que reusa el "Renombrar" (PUT exige revalidar todo el contenido;
    // send_options viaja de vuelta para no perderse en el re-guardado).
    const renameBody = (name) => isLayout
      ? { name, content_mode: 'layout_v2', layout: t.layout, send_options: t.send_options || undefined }
      : { name, embeds, send_options: t.send_options || undefined };
    list.append(el('li', {},
      el('span', {},
        el('span', { class: 'tpl-dot', style: 'background:' + color }), ' ',
        el('strong', {}, t.name),
        badge,
        ' — ',
        el('span', { class: 'dim' }, snippet.slice(0, 60))),
      el('button', {
        class: 'btn btn-secondary btn-sm',
        onclick: () => {
          if (isLayout) { setEmbedMode('layout'); setLayoutDoc(docFromLayout(t.layout, t.id, t.name, t.send_options)); }
          else { setEmbedMode('classic'); setEmbedDoc(docFromEmbeds(embeds, t.id, t.name, t.send_options)); }
          setEmbedTab('editor'); loadEmbeds();
        },
      }, 'Cargar en el editor'),
      el('button', {
        class: 'btn btn-secondary btn-sm',
        onclick: async () => {
          const name = (prompt('Nuevo nombre:', t.name) || '').trim();
          if (!name || name === t.name) return;
          try {
            await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${t.id}`, { method: 'PUT', body: renameBody(name) });
            loadEmbeds();
          } catch (err) { toast(err.message, 'err'); }
        },
      }, 'Renombrar'),
      el('button', {
        class: 'btn btn-danger btn-sm',
        onclick: async () => {
          if (!confirm(`¿Eliminar la plantilla "${t.name}"?`)) return;
          try {
            await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${t.id}`, { method: 'DELETE' });
            toast('Plantilla eliminada', 'ok');
            loadEmbeds();
          } catch (err) { toast(err.message, 'err'); }
        },
      }, 'Eliminar')));
  }
  box.append(list);
}

// Carga el payload de un link compartido en el editor clásico ANTES del primer
// render (activate corre en el .finally del caller). El ?share= se limpia de
// la URL para que un refresh no re-dispare la carga; el id queda en
// sessionStorage para sobrevivir un cambio de servidor vía selector.
export async function loadSharedEmbed(shareId) {
  try {
    const data = await apiFetch(`/api/embeds/share/${encodeURIComponent(shareId)}`);
    setEmbedTab('editor');
    setEmbedMode('classic');
    setEmbedDoc(docFromEmbeds(data.embeds, null, '', data.send_options));
    sessionStorage.setItem('purgito_share_id', shareId);
    toast('Embed cargado desde un link compartido', 'ok');
  } catch (e) {
    sessionStorage.removeItem('purgito_share_id');
    toast(e.message || 'Este link ya expiró o no existe', 'err');
  }
  history.replaceState({}, '', location.pathname);
}
