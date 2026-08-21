import { apiFetch } from '/js/core/api.js';
import { el, spinner, emptyState, renderError, toast } from '/js/core/dom.js';
import { GUILD_ID, getDashboardUrl } from '/js/core/config.js';
import { content } from '/js/panel-shell.js';
import { watchTasks } from '/js/core/tasks.js';
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'tabsGifs.openGif': 'ABRIR GIF',
    'tabsGifs.statsWithLimit': ' de {limit} GIFs — ',
    'tabsGifs.statsNoLimit': ' GIFs — ',
    'tabsGifs.statsPreview': ' con preview · ',
    'tabsGifs.statsLink': ' como link',
    'tabsGifs.quotaReached': 'Llegaste al cupo: cada GIF nuevo que se guarde va a reemplazar al más antiguo.',
    'tabsGifs.quotaNear': 'Estás cerca del cupo — al llegar, cada GIF nuevo reemplaza al más antiguo.',
    'tabsGifs.autoRemovedSingle': 'En los últimos 30 días se quitó 1 GIF solo porque su host dejó de servirlo. ',
    'tabsGifs.autoRemovedPlural': 'En los últimos 30 días se quitaron {count} GIFs solos porque sus hosts dejaron de servirlos. ',
    'tabsGifs.autoRemovedLink': 'Verlos en el historial',
    'tabsGifs.loadMoreRemaining': 'Cargar más ({left} restantes)',
    'tabsGifs.remove': 'Quitar',
    'tabsGifs.block': 'Bloquear',
    'tabsGifs.blockTitle': 'Lo borra ahora y evita que se vuelva a guardar en este servidor',
    'tabsGifs.confirmSure': '¿Seguro?',
    'tabsGifs.blockConfirm': 'Bloqueado — no se va a volver a guardar en este servidor. ¿Seguro?',
    'tabsGifs.notFound': 'No se encontró ese GIF',
    'tabsGifs.deleted': 'GIF eliminado',
    'tabsGifs.rateLimitDelete': 'Rate limit — espera antes de borrar más',
    'tabsGifs.blocked': 'GIF bloqueado para siempre en este servidor',
    'tabsGifs.rateLimitBlock': 'Rate limit — espera antes de bloquear más',
    'tabsGifs.originLink': 'Enlace',
    'tabsGifs.originDirect': 'GIF directo',
    'tabsGifs.kindLink': 'enlace',
    'tabsGifs.kindPreview': 'preview',
    'tabsGifs.unblock': 'Desbloquear',
    'tabsGifs.blockNotFound': 'No se encontró ese bloqueo',
    'tabsGifs.unblocked': 'GIF desbloqueado — se puede volver a guardar',
    'tabsGifs.noBlocked': 'No hay GIFs bloqueados.',
    'tabsGifs.blockedSection': 'GIFs bloqueados',
    'tabsGifs.urlPlaceholder': 'https://tenor.com/… o URL de R2',
    'tabsGifs.verifyTitle': 'Revisa cada GIF contra su host de origen y saca los que estén realmente muertos (los que solo el navegador no puede previsualizar no se tocan). Puede tardar unos minutos.',
    'tabsGifs.verifying': 'Verificando…',
    'tabsGifs.verifyPartial': 'Verificando los {checking} más antiguos de {total} GIFs — el resto se cubre en próximos ciclos',
    'tabsGifs.verifyAll': 'Verificación de {total} GIFs iniciada en segundo plano',
    'tabsGifs.verifyRateLimit': 'Ya hay una verificación reciente — espera antes de disparar otra',
    'tabsGifs.verifyBtn': 'Verificar GIFs',
    'tabsGifs.added': 'GIF agregado',
    'tabsGifs.alreadySaved': 'Ese GIF ya estaba guardado',
    'tabsGifs.rateLimitAdd': 'Rate limit — espera antes de agregar más',
    'tabsGifs.addBtn': 'Agregar',
    'tabsGifs.emptyState': 'Todavía no hay GIFs guardados — añade uno con el campo de arriba.',
    'tabsGifs.loadMore': 'Cargar más',
  },
  en: {
    'tabsGifs.openGif': 'OPEN GIF',
    'tabsGifs.statsWithLimit': ' of {limit} GIFs — ',
    'tabsGifs.statsNoLimit': ' GIFs — ',
    'tabsGifs.statsPreview': ' with preview · ',
    'tabsGifs.statsLink': ' as link',
    'tabsGifs.quotaReached': "You've hit the limit: every new GIF saved will replace the oldest one.",
    'tabsGifs.quotaNear': "You're close to the limit — once you hit it, every new GIF will replace the oldest one.",
    'tabsGifs.autoRemovedSingle': 'In the last 30 days, 1 GIF was automatically removed because its host stopped serving it. ',
    'tabsGifs.autoRemovedPlural': 'In the last 30 days, {count} GIFs were automatically removed because their hosts stopped serving them. ',
    'tabsGifs.autoRemovedLink': 'View them in the history',
    'tabsGifs.loadMoreRemaining': 'Load more ({left} remaining)',
    'tabsGifs.remove': 'Remove',
    'tabsGifs.block': 'Block',
    'tabsGifs.blockTitle': 'Deletes it now and prevents it from being saved again on this server',
    'tabsGifs.confirmSure': 'Are you sure?',
    'tabsGifs.blockConfirm': "Blocked — it won't be saved again on this server. Are you sure?",
    'tabsGifs.notFound': "That GIF wasn't found",
    'tabsGifs.deleted': 'GIF deleted',
    'tabsGifs.rateLimitDelete': 'Rate limit — wait before deleting more',
    'tabsGifs.blocked': 'GIF permanently blocked on this server',
    'tabsGifs.rateLimitBlock': 'Rate limit — wait before blocking more',
    'tabsGifs.originLink': 'Link',
    'tabsGifs.originDirect': 'Direct GIF',
    'tabsGifs.kindLink': 'link',
    'tabsGifs.kindPreview': 'preview',
    'tabsGifs.unblock': 'Unblock',
    'tabsGifs.blockNotFound': "That block wasn't found",
    'tabsGifs.unblocked': 'GIF unblocked — it can be saved again',
    'tabsGifs.noBlocked': 'No blocked GIFs.',
    'tabsGifs.blockedSection': 'Blocked GIFs',
    'tabsGifs.urlPlaceholder': 'https://tenor.com/… or R2 URL',
    'tabsGifs.verifyTitle': "Checks each GIF against its source host and removes the ones that are truly dead (ones the browser just can't preview are left alone). May take a few minutes.",
    'tabsGifs.verifying': 'Verifying…',
    'tabsGifs.verifyPartial': 'Verifying the {checking} oldest of {total} GIFs — the rest will be covered in upcoming cycles',
    'tabsGifs.verifyAll': 'Verification of {total} GIFs started in the background',
    'tabsGifs.verifyRateLimit': 'A verification already ran recently — wait before starting another',
    'tabsGifs.verifyBtn': 'Verify GIFs',
    'tabsGifs.added': 'GIF added',
    'tabsGifs.alreadySaved': 'That GIF was already saved',
    'tabsGifs.rateLimitAdd': 'Rate limit — wait before adding more',
    'tabsGifs.addBtn': 'Add',
    'tabsGifs.emptyState': 'No GIFs saved yet — add one using the field above.',
    'tabsGifs.loadMore': 'Load more',
  },
});

const GIFS_PAGE = 30;
let _gifPool = [];
let _gifStatsEl = null;

// Misma clasificación que la galería pública (gif_gallery.py).
function classifyGif(gif) {
  if (gif.media_url && !gif.media_url.endsWith('.png') && !gif.media_url.endsWith('.jpg') && !gif.media_url.endsWith('.jpeg') && !gif.media_url.endsWith('.webp')) {
    return { type: 'img', src: gif.media_url };
  }
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
    el('span', { style: 'font-size:10px;letter-spacing:0.15em' }, t('tabsGifs.openGif')));
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
// recalculado sobre el pool en memoria (no pide de nuevo al backend). El cupo
// (_gifLimit) viene del backend y no cambia al borrar, así que se guarda aparte.
let _gifLimit = 0;

function updateGifStats() {
  if (!_gifStatsEl) return;
  let preview = 0, link = 0;
  for (const g of _gifPool) {
    if (classifyGif(g).type === 'link') link++; else preview++;
  }
  _gifStatsEl.innerHTML = '';
  _gifStatsEl.append(
    el('strong', { class: 'stat-num' }, String(_gifPool.length)),
    _gifLimit ? t('tabsGifs.statsWithLimit', { limit: _gifLimit.toLocaleString('es') }) : t('tabsGifs.statsNoLimit'),
    el('strong', { class: 'stat-num' }, String(preview)), t('tabsGifs.statsPreview'),
    el('strong', { class: 'stat-num' }, String(link)), t('tabsGifs.statsLink'));
  // Al llegar al cupo, guardar uno nuevo desaloja el más viejo: decirlo antes
  // de que pase, no después.
  if (_gifLimit && _gifPool.length >= _gifLimit * 0.9) {
    _gifStatsEl.append(el('p', { class: 'dim' }, _gifPool.length >= _gifLimit
      ? t('tabsGifs.quotaReached')
      : t('tabsGifs.quotaNear')));
  }
}

/* Los GIFs que el chequeo de salud saca solos (3 chequeos "dead" seguidos)
   antes desaparecían sin ningún rastro visible: para el admin era
   indistinguible de un bug. El backend ahora los registra en el historial y
   devuelve el conteo de los últimos 30 días. */
function autoRemovedNote(count) {
  if (!count) return null;
  return el('p', { class: 'dim' },
    count === 1
      ? t('tabsGifs.autoRemovedSingle')
      : t('tabsGifs.autoRemovedPlural', { count }),
    el('a', { href: getDashboardUrl(GUILD_ID, 'historial') }, t('tabsGifs.autoRemovedLink')),
    '.');
}

function syncGifMore() {
  const grid = document.getElementById('gifGrid');
  const btn = document.getElementById('gifMoreBtn');
  if (!grid || !btn) return;
  const left = _gifPool.length - grid.querySelectorAll('.gif-card').length;
  btn.parentElement.style.display = left > 0 ? '' : 'none';
  if (left > 0) btn.textContent = t('tabsGifs.loadMoreRemaining', { left });
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

// Confirmación en dos pasos (mismo patrón que attachDelBtn/askConfirm de
// gif_gallery.py): botón -> "¿Seguro? ✓ ✗" -> ejecuta o revierte. "Bloquear"
// además de borrar la card deja el GIF vetado para siempre en este guild
// (gif_blocklist en db.py) -- el texto de confirmación lo deja explícito
// porque, a diferencia de "Quitar", no hay forma de deshacer el veto salvo
// yendo a la sección "GIFs bloqueados" de abajo.
function gifCardActions(gifId, card) {
  const wrap = el('div', { class: 'gif-actions' });

  function showButtons() {
    wrap.innerHTML = '';
    wrap.append(
      el('button', { class: 'btn btn-danger btn-sm', onclick: showDeleteConfirm }, t('tabsGifs.remove')),
      el('button', {
        class: 'btn btn-secondary btn-sm', onclick: showBlockConfirm,
        title: t('tabsGifs.blockTitle'),
      }, t('tabsGifs.block')));
  }
  function showDeleteConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      t('tabsGifs.confirmSure'),
      el('button', { class: 'btn btn-danger btn-sm', onclick: doDelete }, '✓'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButtons }, '✗')));
  }
  function showBlockConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      t('tabsGifs.blockConfirm'),
      el('button', { class: 'btn btn-danger btn-sm', onclick: doBlock }, '✓'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButtons }, '✗')));
  }
  function removeCard() {
    card.classList.add('out');
    _gifPool = _gifPool.filter(g => g.id !== gifId);
    updateGifStats();
    setTimeout(() => { card.remove(); syncGifMore(); }, 240);
  }
  async function doDelete() {
    try {
      const resp = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs/${gifId}`, { method: 'DELETE' });
      if (!resp.deleted) {
        toast(t('tabsGifs.notFound'), 'warn');
        showButtons();
        return;
      }
      toast(t('tabsGifs.deleted'), 'ok');
      removeCard();
    } catch (e) {
      toast(e.status === 429 ? t('tabsGifs.rateLimitDelete') : e.message, e.status === 429 ? 'warn' : 'err');
      showButtons();
    }
  }
  async function doBlock() {
    try {
      const resp = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs/${gifId}/block`, { method: 'POST' });
      if (!resp.blocked) {
        toast(t('tabsGifs.notFound'), 'warn');
        showButtons();
        return;
      }
      toast(t('tabsGifs.blocked'), 'ok');
      removeCard();
    } catch (e) {
      toast(e.status === 429 ? t('tabsGifs.rateLimitBlock') : e.message, e.status === 429 ? 'warn' : 'err');
    }
  }

  showButtons();
  return wrap;
}

function gifOriginLabel(g) {
  if (!g) return t('tabsGifs.originLink');
  const { type } = classifyGif(g);
  const u = (g.url || '').toLowerCase();
  let source = t('tabsGifs.originLink');
  if (u.includes('r2.dev') || (g.media_url && g.media_url.includes('r2.dev'))) source = 'R2';
  else if (u.includes('tenor.com')) source = 'Tenor';
  else if (u.includes('giphy.com')) source = 'Giphy';
  else if (u.includes('discordapp.com') || u.includes('discord.gg')) source = 'Discord';
  else if (u.endsWith('.gif')) source = t('tabsGifs.originDirect');

  const kind = type === 'link' ? t('tabsGifs.kindLink') : t('tabsGifs.kindPreview');
  return `${source} · ${kind}`;
}

function gifCard(g) {
  const origin = gifOriginLabel(g);
  const card = el('div', { class: 'gif-card' },
    gifThumb(g),
    el('a', {
      class: 'gif-url gif-source-badge',
      href: g.url,
      target: '_blank',
      rel: 'noopener',
      title: g.url,
    }, origin));
  card.append(gifCardActions(g.id, card));
  return card;
}

// Fila de la sección "GIFs bloqueados": el objeto ya no tiene id (la fila de
// corpus_gifs se borró al bloquear) -- content_hash o url identifica el veto.
function blockedGifRow(b, list) {
  const key = b.content_hash || b.url;
  const btn = el('button', { class: 'btn btn-secondary btn-sm' }, t('tabsGifs.unblock'));
  const label = b.url ? `${gifOriginLabel(b)} · ${b.url}` : b.content_hash;
  const row = el('div', { class: 'gif-blocked-row' },
    el('span', { class: 'gif-url', title: b.url || b.content_hash }, label), btn);
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      const resp = await apiFetch(
        `/api/server/${GUILD_ID}/settings/gifs/blocked/${encodeURIComponent(key)}`,
        { method: 'DELETE' });
      if (!resp.unblocked) {
        toast(t('tabsGifs.blockNotFound'), 'warn');
        btn.disabled = false;
        return;
      }
      toast(t('tabsGifs.unblocked'), 'ok');
      row.remove();
      if (!list.querySelector('.gif-blocked-row')) {
        list.append(el('p', { class: 'dim' }, t('tabsGifs.noBlocked')));
      }
    } catch (e) {
      toast(e.message, 'err');
      btn.disabled = false;
    }
  };
  return row;
}

// <details>/<summary> nativo, mismo patrón que "Opciones de envío" del
// editor de embeds (.send-opts): la lista se pide recién la primera vez que
// se abre, no en cada carga del tab.
function blockedGifsSection() {
  const details = el('details', { class: 'gif-blocked-section' },
    el('summary', {}, t('tabsGifs.blockedSection')));
  const list = el('div', { class: 'gif-blocked-list' });
  details.append(list);
  details.addEventListener('toggle', async () => {
    if (!details.open || list.dataset.loaded) return;
    list.dataset.loaded = '1';
    list.append(spinner());
    try {
      const data = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs/blocked`);
      list.innerHTML = '';
      if (!data.blocked.length) {
        list.append(el('p', { class: 'dim' }, t('tabsGifs.noBlocked')));
      } else {
        for (const b of data.blocked) list.append(blockedGifRow(b, list));
      }
    } catch (e) {
      list.innerHTML = '';
      renderError(list, e);
    }
  });
  return details;
}

export async function loadGifs() {
  const box = content();
  box.append(spinner());
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs`);
    box.innerHTML = '';

    const taskBanner = el('div', { class: 'task-banner-wrap' });
    box.append(taskBanner);
    watchTasks(taskBanner);

    _gifPool = data.gifs;
    _gifLimit = data.limit || 0;
    _gifStatsEl = el('div', { class: 'dim gif-stats' });
    box.append(_gifStatsEl);
    updateGifStats();
    const autoRemoved = autoRemovedNote(data.auto_removed_30d || 0);
    if (autoRemoved) box.append(autoRemoved);

    const input = el('input', { type: 'text', placeholder: t('tabsGifs.urlPlaceholder'), style: 'flex:1' });
    const verifyBtn = el('button', {
      class: 'btn btn-secondary',
      title: t('tabsGifs.verifyTitle'),
      onclick: async () => {
        verifyBtn.disabled = true;
        const original = verifyBtn.textContent;
        verifyBtn.textContent = t('tabsGifs.verifying');
        try {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/settings/gifs/verify`, { method: 'POST' });
          const msg = resp.checking < resp.total
            ? t('tabsGifs.verifyPartial', { checking: resp.checking, total: resp.total })
            : t('tabsGifs.verifyAll', { total: resp.total });
          toast(msg, 'ok');
          watchTasks(taskBanner);
        } catch (e) {
          toast(e.status === 429 ? t('tabsGifs.verifyRateLimit') : e.message, e.status === 429 ? 'warn' : 'err');
        } finally {
          verifyBtn.disabled = false;
          verifyBtn.textContent = original;
        }
      },
    }, t('tabsGifs.verifyBtn'));
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
              toast(t('tabsGifs.added'), 'ok');
              loadGifs();
            } else {
              toast(t('tabsGifs.alreadySaved'), 'warn');
            }
          } catch (e) {
            toast(e.status === 429 ? t('tabsGifs.rateLimitAdd') : e.message, e.status === 429 ? 'warn' : 'err');
          }
        },
      }, t('tabsGifs.addBtn')),
      verifyBtn));

    box.append(blockedGifsSection());

    if (!_gifPool.length) {
      box.append(emptyState(t('tabsGifs.emptyState')));
      return;
    }

    const grid = el('div', { class: 'gif-grid', id: 'gifGrid' });
    box.append(grid);
    renderGifBatch();

    const moreBtn = el('button', { class: 'btn btn-secondary', id: 'gifMoreBtn', onclick: renderGifBatch }, t('tabsGifs.loadMore'));
    box.append(el('div', { class: 'gif-more-wrap' }, moreBtn));
    syncGifMore();
  } catch (e) { renderError(box, e); }
}
