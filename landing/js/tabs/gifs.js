import { apiFetch } from '/js/core/api.js';
import { el, spinner, emptyState, renderError, toast } from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { content } from '/js/panel-shell.js';

const GIFS_PAGE = 30;
let _gifPool = [];
let _gifStatsEl = null;

// Misma clasificación que la galería pública (gif_gallery.py).
function classifyGif(gif) {
  if (gif.media_url) return { type: 'img', src: gif.media_url };
  const u = gif.url;
  if (u.includes('cdn.discordapp.com')) return { type: 'img', src: u };
  if (u.includes('giphy.com/gifs/')) {
    const parts = u.split('/gifs/').pop().split('-');
    const id = parts[parts.length - 1];
    return { type: 'img', src: `https://media.giphy.com/media/${id}/giphy.gif` };
  }
  if (u.includes('tenor.com/view/')) {
    const parts = u.split('/');
    const id = parts[parts.length - 1].split('-').pop();
    return { type: 'iframe', src: `https://tenor.com/embed/${id}` };
  }
  // GIFs propios en R2 (u otro host servido directo): sin query string
  // firmado, así que el sufijo .gif ya identifica el archivo servible.
  if (u.toLowerCase().endsWith('.gif')) return { type: 'img', src: u };
  return { type: 'link', src: null };
}

function gifLinkCard(url) {
  return el('a', {
    class: 'gif-placeholder', href: url, target: '_blank', rel: 'noopener', title: url,
    style: 'flex-direction:column;gap:4px',
  },
    el('span', {}, '⛓'),
    el('span', { style: 'font-size:10px;letter-spacing:0.15em' }, 'ABRIR GIF'));
}

function gifThumb(g) {
  const { type, src } = classifyGif(g);
  if (type === 'img') {
    const img = el('img', { src, loading: 'lazy', alt: '' });
    img.onerror = () => img.replaceWith(gifLinkCard(g.url));
    return img;
  }
  if (type === 'iframe') {
    const frame = el('iframe', { src, loading: 'lazy', frameborder: '0' });
    frame.style.cssText = 'width:100%;height:110px;border:none;pointer-events:none;border-radius:3px;background:#000';
    return frame;
  }
  return gifLinkCard(g.url);
}

// Igual que el header de gif_gallery.py: total + desglose preview/link,
// recalculado sobre el pool en memoria (no pide de nuevo al backend).
function updateGifStats() {
  if (!_gifStatsEl) return;
  let preview = 0, link = 0;
  for (const g of _gifPool) {
    if (classifyGif(g).type === 'link') link++; else preview++;
  }
  _gifStatsEl.innerHTML = '';
  _gifStatsEl.append(
    el('strong', { class: 'stat-num' }, String(_gifPool.length)), ' GIFs — ',
    el('strong', { class: 'stat-num' }, String(preview)), ' con preview · ',
    el('strong', { class: 'stat-num' }, String(link)), ' como link');
}

function syncGifMore() {
  const grid = document.getElementById('gifGrid');
  const btn = document.getElementById('gifMoreBtn');
  if (!grid || !btn) return;
  const left = _gifPool.length - grid.querySelectorAll('.gif-card').length;
  btn.parentElement.style.display = left > 0 ? '' : 'none';
  if (left > 0) btn.textContent = `Cargar más (${left} restantes)`;
}

function renderGifBatch() {
  const grid = document.getElementById('gifGrid');
  if (!grid) return;
  const from = grid.querySelectorAll('.gif-card').length;
  const frag = document.createDocumentFragment();
  for (const g of _gifPool.slice(from, from + GIFS_PAGE)) frag.append(gifCard(g));
  grid.append(frag);
  syncGifMore();
}

// Confirmación de borrado en dos pasos (mismo patrón que attachDelBtn/
// askConfirm de gif_gallery.py): "Quitar" -> "¿Seguro? ✓ ✗" -> ejecuta o revierte.
function gifDeleteActions(gifId, card) {
  const wrap = el('div', { class: 'gif-actions' });

  function showButton() {
    wrap.innerHTML = '';
    wrap.append(el('button', { class: 'btn btn-danger btn-sm', onclick: showConfirm }, 'Quitar'));
  }
  function showConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      '¿Seguro?',
      el('button', { class: 'btn btn-danger btn-sm', onclick: doDelete }, '✓'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButton }, '✗')));
  }
  async function doDelete() {
    try {
      const resp = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs/${gifId}`, { method: 'DELETE' });
      if (!resp.deleted) {
        toast('No se encontró ese GIF', 'warn');
        showButton();
        return;
      }
      toast('GIF eliminado', 'ok');
      card.classList.add('out');
      _gifPool = _gifPool.filter(g => g.id !== gifId);
      updateGifStats();
      setTimeout(() => { card.remove(); syncGifMore(); }, 240);
    } catch (e) {
      toast(e.status === 429 ? 'Rate limit — espera antes de borrar más' : e.message, e.status === 429 ? 'warn' : 'err');
      showButton();
    }
  }

  showButton();
  return wrap;
}

function gifCard(g) {
  const card = el('div', { class: 'gif-card' },
    gifThumb(g),
    el('a', { class: 'gif-url', href: g.url, target: '_blank', rel: 'noopener' }, g.url));
  card.append(gifDeleteActions(g.id, card));
  return card;
}

export async function loadGifs() {
  const box = content();
  box.append(spinner());
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs`);
    box.innerHTML = '';

    _gifPool = data.gifs;
    _gifStatsEl = el('p', { class: 'dim gif-stats' });
    box.append(_gifStatsEl);
    updateGifStats();

    const input = el('input', { type: 'text', placeholder: 'https://tenor.com/… o URL de R2', style: 'flex:1' });
    const verifyBtn = el('button', {
      class: 'btn btn-secondary',
      title: 'Revisa cada GIF contra su host de origen y saca los que estén '
        + 'realmente muertos (los que solo el navegador no puede previsualizar '
        + 'no se tocan). Puede tardar unos minutos.',
      onclick: async () => {
        verifyBtn.disabled = true;
        const original = verifyBtn.textContent;
        verifyBtn.textContent = 'Verificando…';
        try {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs/verify`, { method: 'POST' });
          const msg = resp.checking < resp.total
            ? `Verificando los ${resp.checking} más antiguos de ${resp.total} GIFs — el resto se cubre en próximos ciclos`
            : `Verificación de ${resp.total} GIFs iniciada en segundo plano`;
          toast(`${msg} — recargá esta sección en unos minutos`, 'ok');
        } catch (e) {
          toast(e.status === 429 ? 'Ya hay una verificación reciente — esperá antes de disparar otra' : e.message, e.status === 429 ? 'warn' : 'err');
        } finally {
          verifyBtn.disabled = false;
          verifyBtn.textContent = original;
        }
      },
    }, 'Verificar GIFs');
    box.append(el('div', { class: 'add-row' }, input,
      el('button', {
        class: 'btn btn-primary',
        onclick: async () => {
          const url = input.value.trim();
          if (!url) return;
          try {
            const addResp = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs`, {
              method: 'POST', body: { url },
            });
            if (addResp.inserted) {
              toast('GIF agregado', 'ok');
              loadGifs();
            } else {
              toast('Ese GIF ya estaba guardado', 'warn');
            }
          } catch (e) {
            toast(e.status === 429 ? 'Rate limit — espera antes de agregar más' : e.message, e.status === 429 ? 'warn' : 'err');
          }
        },
      }, 'Agregar'),
      verifyBtn));

    if (!_gifPool.length) {
      box.append(emptyState('Todavía no hay GIFs guardados — añade uno con el campo de arriba.'));
      return;
    }

    const grid = el('div', { class: 'gif-grid', id: 'gifGrid' });
    box.append(grid);
    renderGifBatch();

    const moreBtn = el('button', { class: 'btn btn-secondary', id: 'gifMoreBtn', onclick: renderGifBatch }, 'Cargar más');
    box.append(el('div', { class: 'gif-more-wrap' }, moreBtn));
    syncGifMore();
  } catch (e) { renderError(box, e); }
}
