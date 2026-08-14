// Dashboard por servidor (/es/dashboard/:id): header con datos del guild, tabs
// INICIO/CHAT/GIFS/MEMES/EMBEDS/PREMIUM/YOUTUBE/HISTORIAL y el contenido de
// INICIO y CHAT, que guardan solo al click (sin botón de guardar) y
// confirman con un toast. GIFS, EMBEDS y PREMIUM reutilizan los loaders del
// panel sin tocarles la lógica; YOUTUBE e HISTORIAL son paridad nueva de la
// categoría YouTube de /settings y de audit_log/db.py respectivamente.
//
// El navbar y el footer NO se arman acá: vienen en el HTML de la página, que
// build_docs.py recorta de index.html. script.js es quien resuelve la sesión
// en el navbar; este módulo solo pinta lo que va debajo.

import { apiFetch, humanError } from '/js/core/api.js';
import {
  el, icon, spinner, emptyState, renderError, guildIcon, toast, formGroup,
  confirmDelBtn, helpIcon, accordionGroup,
} from '/js/core/dom.js';
import { GUILD_ID, currentLocale } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, content } from '/js/panel-shell.js';
import { loadGifs } from '/js/tabs/gifs.js';
import { loadPremium } from '/js/tabs/premium.js';
import { loadYoutube } from '/js/tabs/youtube.js';
import { loadHistorial } from '/js/tabs/historial.js';
import {
  loadEmbeds, loadSharedEmbed, panelModal, getEmojis, uploadImageBlob,
} from '/js/embeds/shared-ui.js';

const TABS = [
  { key: 'inicio', label: 'INICIO', load: loadInicio },
  { key: 'chat', label: 'CHAT', load: loadChatTab },
  { key: 'gifs', label: 'GIFS', load: loadGifs },
  { key: 'memes', label: 'MEMES', load: loadMemes },
  { key: 'embeds', label: 'EMBEDS', load: loadEmbeds },
  { key: 'premium', label: 'PREMIUM', load: loadPremium },
  { key: 'youtube', label: 'YOUTUBE', load: loadYoutube },
  { key: 'historial', label: 'HISTORIAL', load: loadHistorial },
];

const CHAT_SUBTABS = [
  { key: 'comportamiento', label: 'Comportamiento' },
  { key: 'canales', label: 'Canales' },
  { key: 'contenido', label: 'Contenido' },
  { key: 'reacciones', label: 'Reacciones' },
  { key: 'limites', label: 'Límites' },
  { key: 'datos', label: 'Datos' },
  { key: 'playground', label: 'Playground' },
];

function currentChatSubtab() {
  const key = location.hash.slice(1);
  return CHAT_SUBTABS.some(t => t.key === key) ? key : 'comportamiento';
}

// Setter de sub-pestaña de CHAT registrado cuando el tab CHAT está montado
let _activeChatSubtabSetter = null;
let _chatHashHandler = null;

function currentTab() {
  const key = location.pathname.split('/')[4] || 'inicio';
  return TABS.some(t => t.key === key) ? key : 'inicio';
}

function renderSidebar(activeTab, activeSubtab) {
  const nav = document.getElementById('dashTabs');
  if (!nav) return;
  nav.className = 'dash-sidebar';
  nav.innerHTML = '';

  const activeTabObj = TABS.find(t => t.key === activeTab) || TABS[0];
  const activeSubtabObj = activeTab === 'chat'
    ? (CHAT_SUBTABS.find(s => s.key === activeSubtab) || CHAT_SUBTABS[0])
    : null;

  const currentLabelWrap = el('span', { class: 'dash-mobile-nav-current' },
    el('span', { class: 'dash-mobile-tab-name' }, activeTabObj.label),
    activeSubtabObj ? el('span', { class: 'dash-mobile-subtab-sep' }, '·') : null,
    activeSubtabObj ? el('span', { class: 'dash-mobile-subtab-name' },
      activeSubtabObj.key === 'playground' ? 'Probar' : activeSubtabObj.label) : null
  );

  const toggleBtn = el('button', {
    type: 'button',
    class: 'dash-mobile-nav-toggle',
    'aria-expanded': 'false',
    'aria-label': 'Abrir navegación del dashboard',
    onclick: () => {
      const isOpen = nav.classList.toggle('open');
      toggleBtn.setAttribute('aria-expanded', String(isOpen));
    },
  },
    currentLabelWrap,
    el('svg', { class: 'dash-mobile-nav-chev', viewBox: '0 0 24 24', 'aria-hidden': 'true' },
      el('path', { d: 'M6 9l6 6 6-6' }))
  );

  function closeMobileNav() {
    nav.classList.remove('open');
    toggleBtn.setAttribute('aria-expanded', 'false');
  }

  const inner = el('div', { class: 'dash-sidebar-inner' });
  const list = el('ul', { class: 'dash-sidebar-list' });

  for (const t of TABS) {
    const isTabActive = t.key === activeTab;
    const item = el('li', {
      class: 'dash-sidebar-item' + (isTabActive ? ' active' : '') + (t.key === 'chat' && isTabActive ? ' has-subtabs' : ''),
    });

    const tabLink = el('a', {
      class: 'dash-tab' + (isTabActive ? ' active' : ''),
      'data-key': t.key,
      href: `/${currentLocale()}/dashboard/${GUILD_ID}/${t.key}`,
      'aria-current': isTabActive ? 'page' : null,
      onclick: (ev) => {
        ev.preventDefault();
        closeMobileNav();
        activate(t.key, true);
      },
    }, t.label);

    item.append(tabLink);

    if (t.key === 'chat' && isTabActive) {
      const subList = el('ul', { class: 'dash-subtabs-list' });
      for (const st of CHAT_SUBTABS) {
        const isSubActive = st.key === (activeSubtab || 'comportamiento');
        if (st.key === 'playground') {
          subList.append(
            el('li', { class: 'dash-subtab-try-item' },
              el('a', {
                class: 'dash-subtab dash-subtab-try' + (isSubActive ? ' active' : ''),
                'data-key': 'playground',
                href: '#playground',
                onclick: (ev) => {
                  ev.preventDefault();
                  closeMobileNav();
                  if (_activeChatSubtabSetter) _activeChatSubtabSetter('playground');
                  else location.hash = '#playground';
                },
              },
                el('span', { class: 'try-sparkle', 'aria-hidden': 'true' }, '✦'),
                'Probar configuración'))
          );
        } else {
          subList.append(
            el('li', {},
              el('a', {
                class: 'dash-subtab' + (isSubActive ? ' active' : ''),
                'data-key': st.key,
                href: `#${st.key}`,
                onclick: (ev) => {
                  ev.preventDefault();
                  closeMobileNav();
                  if (_activeChatSubtabSetter) _activeChatSubtabSetter(st.key);
                  else location.hash = `#${st.key}`;
                },
              }, st.label))
          );
        }
      }
      item.append(subList);
    }

    list.append(item);
  }

  inner.append(list);
  nav.append(toggleBtn, inner);
}

function activate(key, push) {
  const currentSub = key === 'chat' ? currentChatSubtab() : null;
  renderSidebar(key, currentSub);
  if (push) {
    history.pushState({}, '', `/${currentLocale()}/dashboard/${GUILD_ID}/${key}`);
  }
  if (key !== 'chat') {
    _activeChatSubtabSetter = null;
    if (_chatHashHandler) {
      window.removeEventListener('hashchange', _chatHashHandler);
      _chatHashHandler = null;
    }
  }
  if (key === 'inicio') {
    loadHead();
  }
  TABS.find(t => t.key === key).load();
}

async function loadHead() {
  const head = document.getElementById('dashHead');
  const back = el('a', { class: 'dash-back', href: `/${currentLocale()}/perfil/servidores` },
    el('span', { class: 'dash-back-arrow', 'aria-hidden': 'true' }, '←'), 'Volver atrás');
  try {
    const data = await apiFetch('/api/me/guilds');
    const g = data.configured.find(x => x.id === GUILD_ID);
    if (!g) {
      head.innerHTML = '';
      head.append(back);
      content().append(emptyState('No encontramos ese servidor entre los que administras.'));
      document.getElementById('dashTabs').hidden = true;
      return;
    }
    document.title = `${g.name} · Purgito`;
    head.innerHTML = '';
    head.append(back,
      el('div', { class: 'dash-guild' },
        guildIcon(g),
        el('div', { class: 'dash-guild-info' },
          el('h1', { class: 'dash-guild-name' }, g.name,
            g.is_premium ? el('span', { class: 'badge badge-premium' }, 'PREMIUM') : null),
          el('div', { class: 'dash-guild-members dim' },
            icon('members'),
            g.member_count != null ? `${Number(g.member_count).toLocaleString('es')} miembros` : 'Servidor'))));
  } catch (e) {
    head.innerHTML = '';
    head.append(back);
  }
}

export function initDash() {
  loadHead();
  const shareId = new URLSearchParams(location.search).get('share');
  if (shareId) {
    loadSharedEmbed(shareId).finally(() => activate('embeds', true));
  } else {
    activate(currentTab(), false);
  }
  window.onpopstate = () => activate(currentTab(), false);
}

// Cerrar menú móvil al presionar Escape o hacer click afuera
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    const nav = document.getElementById('dashTabs');
    if (nav && nav.classList.contains('open')) {
      nav.classList.remove('open');
      const toggle = nav.querySelector('.dash-mobile-nav-toggle');
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
    }
  }
});

document.addEventListener('click', (ev) => {
  const nav = document.getElementById('dashTabs');
  if (nav && nav.classList.contains('open') && !nav.contains(ev.target)) {
    nav.classList.remove('open');
    const toggle = nav.querySelector('.dash-mobile-nav-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
  }
});

if (GUILD_ID) initDash();
else document.getElementById('dashHead').append(
  emptyState('Falta el id del servidor en la dirección.'));

// ---------------- INICIO ----------------

/* "14.982 / 15.000" cuando hay cupo conocido, el número solo si no. El
   denominador es lo que le da contexto a estas tarjetas: sin él, nada le dice al
   admin que al tocar el techo el bot empieza a descartar lo más viejo. */
function withCap(used, cap) {
  if (used == null) return null;
  const n = Number(used).toLocaleString('es');
  if (!cap) return n;
  return el('span', { class: 'stat-cap-wrap' },
    el('span', { class: 'stat-num-main' }, n),
    el('span', { class: 'stat-num-cap dim' }, ` / ${Number(cap).toLocaleString('es')}`));
}

function statTile(iconName, value, label) {
  const valEl = el('div', { class: 'stat-value' });
  if (value instanceof Node) {
    valEl.append(value);
  } else {
    valEl.textContent = value != null ? (typeof value === 'number' ? value.toLocaleString('es') : String(value)) : '—';
  }
  return el('div', { class: 'stat-tile' },
    el('div', { class: 'stat-icon-wrap' }, icon(iconName)),
    el('div', { class: 'stat-content' },
      el('div', { class: 'stat-label dim' }, label),
      valEl));
}

async function loadInicio() {
  const box = content();
  box.append(spinner());
  try {
    const [style, updates, stats, channels] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/style`),
      apiFetch(`/api/server/${GUILD_ID}/settings/updates`),
      apiFetch(`/api/server/${GUILD_ID}/stats`),
      getChannels({ force: true }),
    ]);
    box.innerHTML = '';

    // Tarjeta "Cambiar estilo"
    const avatar = style.avatar_url || style.current_avatar_url;
    const nick = style.nick || style.current_nick || 'Purgito';
    box.append(formGroup('Cambiar estilo',
      el('div', { class: 'style-card' },
        el('div', { class: 'style-preview' },
          avatar ? el('img', { class: 'style-avatar', src: avatar, alt: '' }) : null,
          el('div', {},
            el('div', { class: 'style-nick' }, nick,
              el('span', { class: 'dm-badge' }, 'BOT')),
            el('div', { class: 'dim' }, 'Así se ve Purgito en este servidor'))),
        el('button', {
          class: 'btn btn-secondary',
          onclick: () => openStyleModal(style),
        }, 'Editar estilo'))));

    // Canal de actualizaciones del bot (diseño compacto en fila)
    const sel = channelSelect(channels, updates.channel_id, 'Sin canal — no publicar');
    sel.onchange = async () => {
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/updates`, {
          method: 'PUT', body: { channel_id: sel.value || null },
        });
        toast(sel.value ? 'Canal de actualizaciones guardado' : 'Canal de actualizaciones quitado', 'ok');
      } catch (e) { toast('No se pudo guardar el canal, intenta de nuevo', 'err'); }
    };
    box.append(formGroup('Actualizaciones del Bot',
      el('div', { class: 'updates-row' },
        el('div', { class: 'updates-info' },
          el('p', { class: 'dim' }, 'Canal donde Purgito publica anuncios y novedades de actualizaciones.')),
        el('div', { class: 'updates-control' }, sel))));

    // Estados: lo que el bot tiene guardado y de dónde lee ahora mismo.
    const lims = stats.limits || {};
    const tiles = el('div', { class: 'stat-grid' },
      statTile('corpus', withCap(stats.corpus_total, lims.corpus_total), 'Mensajes guardados'),
      statTile('film', withCap(stats.gifs, lims.gifs), 'GIFs guardados'),
      statTile('chat', `${stats.reading_channels} / ${stats.text_channels}`, 'Canales que lee'),
      statTile('layout', `${stats.reply_channels} / ${stats.text_channels}`, 'Canales donde responde'),
      statTile('smile', stats.reactions, 'Emojis de reacción'),
      statTile('sparkle', withCap(stats.frases, lims.frases), 'Frases especiales'));

    const alcanzados = [
      [stats.corpus_total, lims.corpus_total, 'mensajes guardados'],
      [stats.gifs, lims.gifs, 'GIFs'],
      [stats.frases, lims.frases, 'frases especiales'],
    ].filter(([used, cap]) => cap && used >= cap);

    const cerca = [
      [stats.corpus_total, lims.corpus_total, 'mensajes guardados'],
      [stats.gifs, lims.gifs, 'GIFs'],
      [stats.frases, lims.frases, 'frases especiales'],
    ].filter(([used, cap]) => cap && used >= cap * 0.9 && used < cap);

    let quotaNotice = null;
    if (alcanzados.length) {
      quotaNotice = el('p', { class: 'stat-quota-msg dim' },
        `Has alcanzado el límite de ${alcanzados.map(c => c[2]).join(' y ')}. ` +
        'Purgito descarta automáticamente el contenido más antiguo para dar lugar a nuevo contenido.');
    } else if (cerca.length) {
      quotaNotice = el('p', { class: 'stat-quota-msg dim' },
        `Estás cerca del cupo de ${cerca.map(c => c[2]).join(' y ')}: al alcanzarlo, ` +
        'Purgito empezará a descartar lo más antiguo para hacer lugar a lo nuevo.');
    }

    const capCanal = lims.corpus_per_channel || 0;
    const byChannel = el('div', { class: 'stat-channels' },
      stats.corpus_by_channel.map(c => {
        const isFull = capCanal && c.count >= capCanal;
        const isNear = capCanal && c.count >= capCanal * 0.9 && !isFull;
        const chanLabel = c.name
          ? el('span', { class: 'stat-chan-name' }, '#' + c.name)
          : el('span', { class: 'stat-chan-unavailable' },
              el('span', { class: 'stat-chan-unavail-title' }, 'Canal no disponible'),
              el('span', { class: 'stat-chan-id dim' }, `ID: ${c.channel_id}`));
        const countText = capCanal
          ? `${c.count.toLocaleString('es')} de ${capCanal.toLocaleString('es')} mensajes`
          : `${c.count.toLocaleString('es')} mensajes`;
        return el('div', { class: 'stat-channel-row' },
          chanLabel,
          el('span', { class: isFull ? 'stat-chan-full' : (isNear ? 'stat-chan-warn' : 'dim') },
            countText));
      }));

    box.append(formGroup('Estado del bot en este servidor',
      tiles,
      quotaNotice,
      stats.corpus_by_channel.length
        ? el('div', { class: 'stat-by-channel' },
            el('p', { class: 'dim' }, 'Mensajes guardados por canal:'),
            byChannel)
        : null));

    // Logs: acumulado histórico de lo que el bot mandó (guild_counters).
    const counters = stats.counters || {};
    box.append(formGroup('Actividad',
      el('p', { class: 'dim' }, 'Actividad acumulada en este servidor desde que se unió Purgito.'),
      el('div', { class: 'activity-grid' },
        el('div', { class: 'activity-card' },
          el('div', { class: 'activity-icon-wrap' }, icon('film')),
          el('div', { class: 'activity-content' },
            el('div', { class: 'activity-value' }, Number(counters.gifs_enviados || 0).toLocaleString('es')),
            el('div', { class: 'activity-label' }, 'GIFs enviados'),
            el('div', { class: 'activity-sub dim' }, 'Total histórico acumulado'))),
        el('div', { class: 'activity-card' },
          el('div', { class: 'activity-icon-wrap' }, icon('chat')),
          el('div', { class: 'activity-content' },
            el('div', { class: 'activity-value' }, Number(counters.mensajes_enviados || 0).toLocaleString('es')),
            el('div', { class: 'activity-label' }, 'Mensajes enviados'),
            el('div', { class: 'activity-sub dim' }, 'Total histórico acumulado'))))));
  } catch (e) { renderError(box, e); }
}

// Modal "Editar estilo": preview en vivo + subida a R2 (mismo uploader que embeds).
function openStyleModal(style) {
  // undefined = no tocar; null = remover; string = URL nueva en R2.
  const state = {
    nick: style.nick || '',
    avatar: undefined,
    banner: undefined,
  };
  const previewAvatarUrl = () => state.avatar === undefined
    ? (style.avatar_url || style.current_avatar_url)
    : state.avatar;
  const previewBannerUrl = () => state.banner === undefined ? style.banner_url : state.banner;

  const counter = el('span', { class: 'dim style-counter' });
  const nickInput = el('input', {
    type: 'text', maxlength: '20', value: state.nick,
    placeholder: style.current_nick || 'Purgito',
  });

  const preview = el('div', { class: 'style-modal-preview' });
  function renderPreview() {
    counter.textContent = `${nickInput.value.length}/20`;
    preview.innerHTML = '';
    const av = previewAvatarUrl();
    const bn = previewBannerUrl();
    preview.append(el('div', { class: 'style-preview' },
      av ? el('img', { class: 'style-avatar', src: av, alt: '' }) : null,
      el('div', {},
        el('div', { class: 'style-nick' },
          nickInput.value.trim() || style.current_nick || 'Purgito',
          el('span', { class: 'dm-badge' }, 'BOT')),
        el('div', { class: 'dim' }, 'Hoy a las 21:46 — hola, soy yo con el estilo nuevo'))),
      bn ? el('img', { class: 'style-banner', src: bn, alt: '' }) : null);
  }
  nickInput.oninput = renderPreview;

  // Sección de imagen (avatar/banner): checkbox que despliega subir + remover.
  function imageSection(label, key) {
    const body = el('div', { class: 'style-img-body' });
    const check = el('input', { type: 'checkbox' });
    const file = el('input', { type: 'file', accept: 'image/*', hidden: '' });
    file.onchange = async () => {
      if (!file.files.length) return;
      try {
        const url = await uploadImageBlob(file.files[0], file.files[0].name);
        state[key] = url;
        renderPreview();
      } catch (e) { toast(e.message, 'err'); }
    };
    body.append(file,
      el('button', { class: 'btn btn-secondary btn-sm', onclick: () => file.click() },
        `Subir ${label}`),
      el('button', {
        class: 'btn btn-danger btn-sm',
        onclick: () => { state[key] = null; renderPreview(); },
      }, `Remover ${label}`));
    body.style.display = 'none';
    check.onchange = () => {
      body.style.display = check.checked ? '' : 'none';
      if (!check.checked) { state[key] = undefined; renderPreview(); }
    };
    return el('div', { class: 'field' },
      el('label', { class: 'toggle' }, check, `Editar ${label}`), body);
  }

  const overlay = panelModal('Editar estilo', el('div', { class: 'style-modal' },
    el('div', { class: 'field' },
      el('label', {}, 'Nombre de usuario ', counter), nickInput),
    imageSection('Avatar', 'avatar'),
    imageSection('Banner', 'banner'),
    el('div', { class: 'field' }, el('label', {}, 'Previa'), preview),
    el('div', { class: 'style-modal-actions' },
      el('button', { class: 'btn btn-secondary', onclick: () => overlay.remove() }, 'Cancelar'),
      el('button', {
        class: 'btn btn-primary',
        onclick: async (ev) => {
          const btn = ev.currentTarget;
          btn.disabled = true;
          const body = { nick: nickInput.value.trim() };
          if (state.avatar !== undefined) body.avatar_url = state.avatar;
          if (state.banner !== undefined) body.banner_url = state.banner;
          try {
            const r = await apiFetch(`/api/server/${GUILD_ID}/style`, { method: 'PUT', body });
            overlay.remove();
            if (r.warning) toast(r.warning, 'warn');
            else toast('Estilo actualizado', 'ok');
            loadInicio();
          } catch (e) {
            btn.disabled = false;
            toast(e.message, 'err');
          }
        },
      }, 'Actualizar'))));
  renderPreview();
}

// ---------------- CHAT ----------------

// Multi-select con toggle: dropdown con todos los canales, click agrega/quita
// al toque (autosave); los agregados se listan debajo, con aviso si el bot no
// tiene permisos de lectura/escritura en el canal.
function channelToggleList({ channels, selected, isSelected, add, remove, listBelow }) {
  const wrap = el('div', { class: 'chan-picker' });
  const panel = el('div', { class: 'dd-panel chan-panel' });
  const btn = el('button', { class: 'dd-trigger' },
    'Seleccionar canales…', el('span', { class: 'dd-caret' }, '▾'));
  const dd = el('div', { class: 'dd' }, btn, panel);
  btn.onclick = (e) => { e.stopPropagation(); dd.classList.toggle('open'); };
  // Chips compactos que wrappean en vez de filas de alto completo (revisión
  // UX de CHAT): con 15-20 canales seleccionados, una fila por canal se
  // volvía un scroll largo e incómodo.
  const list = el('div', { class: 'chan-chips' });

  let busy = false;
  async function toggle(ch) {
    if (busy) return;
    busy = true;
    try {
      if (isSelected(ch.id)) {
        await remove(ch);
        toast('Se ha quitado el canal', 'ok');
      } else {
        await add(ch);
        toast('Se ha agregado el canal', 'ok');
      }
    } catch (e) {
      toast(isSelected(ch.id)
        ? 'No se pudo quitar el canal, intenta de nuevo'
        : 'No se pudo agregar el canal, intenta de nuevo', 'err');
    }
    busy = false;
    render();
  }

  function chanLabel(ch) {
    return el('span', { class: 'chan-name' + (ch.can_send === false ? ' chan-noperm' : '') },
      '#' + (ch.name || ch.id),
      ch.can_send === false
        ? el('span', { class: 'chan-warn', title: 'El bot no puede leer o escribir en este canal' }, '⚠')
        : null);
  }

  function render() {
    panel.innerHTML = '';
    for (const ch of channels) {
      panel.append(el('button', {
        class: 'dd-item chan-option' + (isSelected(ch.id) ? ' active' : ''),
        onclick: (e) => { e.stopPropagation(); toggle(ch); },
      }, chanLabel(ch), isSelected(ch.id) ? el('span', { class: 'chan-check' }, '✓') : null));
    }
    list.innerHTML = '';
    const sel = channels.filter(c => isSelected(c.id));
    if (!sel.length) {
      list.append(el('span', { class: 'dim' }, listBelow));
    }
    for (const ch of sel) {
      list.append(el('span', { class: 'chan-chip' },
        chanLabel(ch),
        el('button', {
          class: 'chan-chip-x', 'aria-label': `Quitar #${ch.name || ch.id}`, onclick: () => toggle(ch),
        }, '✕')));
    }
  }
  render();
  wrap.append(dd, list);
  return wrap;
}

/* Import de corpus desde un .txt (Fase 8): sube el archivo tal cual en el
   body del request (mismo patrón que uploadImageBlob en embeds/shared-ui.js
   para las imágenes), no un multipart -- el channel_id va en la URL. */
function corpusImportForm(channels) {
  const chanSel = channelSelect(channels, null, 'Elige un canal…');
  const fileInput = el('input', { type: 'file', accept: '.txt,text/plain' });
  const resultBox = el('div', {});
  const btn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      const file = fileInput.files[0];
      if (!chanSel.value || !file) {
        toast('Elige un canal y un archivo .txt', 'warn');
        return;
      }
      resultBox.innerHTML = '';
      resultBox.append(spinner());
      let r, data;
      try {
        r = await fetch(`/api/server/${GUILD_ID}/settings/corpus/import/${chanSel.value}`, {
          method: 'POST', credentials: 'include',
          // No text/plain: es uno de los tres Content-Type que un <form> ajeno
          // puede mandar sin preflight de CORS (ver _api_corpus_import_post).
          headers: { 'Content-Type': 'application/octet-stream' },
          body: file,
        });
        data = await r.json().catch(() => ({}));
      } catch (e) {
        resultBox.innerHTML = '';
        toast('No se pudo conectar con el servidor', 'err');
        return;
      }
      resultBox.innerHTML = '';
      if (!r.ok) {
        toast(data.error || humanError(r.status), r.status === 429 ? 'warn' : 'err');
        return;
      }
      toast(`${data.imported} mensajes importados`, 'ok');
      fileInput.value = '';
    },
  }, 'Importar');

  return el('div', {},
    el('div', { class: 'add-row' }, chanSel, fileInput, btn),
    resultBox);
}

/* Confirmación en dos pasos (mismo patrón que subDeleteActions de
   tabs/youtube.js): botón -> "¿Seguro? ✓ ✗" -> ejecuta o cancela. Es
   destructivo e irreversible, no puede dispararse con un solo click. */
function amnesiaButton() {
  const wrap = el('div', {});

  function showButton() {
    wrap.innerHTML = '';
    wrap.append(el('button', {
      class: 'btn btn-danger', onclick: showConfirm,
    }, 'Borrar corpus de las últimas 24h'));
  }

  function showConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      'Esto borra mensajes y estilo por usuario de las últimas 24 horas y no se puede deshacer. ¿Seguro?',
      el('button', { class: 'btn btn-danger btn-sm', onclick: doAmnesia }, '✓ Sí, borrar'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButton }, '✗ Cancelar')));
  }

  async function doAmnesia() {
    try {
      const data = await apiFetch(`/api/server/${GUILD_ID}/settings/corpus/amnesia`, {
        method: 'POST',
      });
      toast(
        `Borrados ${data.deleted.corpus_messages} mensajes y ${data.deleted.user_corpus} de estilo por usuario`,
        'ok',
      );
    } catch (e) {
      toast('No se pudo borrar el corpus reciente, intenta de nuevo', 'err');
    }
    showButton();
  }

  showButton();
  return wrap;
}

/* Guarda un ajuste numérico del chat. El backend recorta al rango y devuelve
   lo que quedó, así que el input se corrige solo si te pasaste. */
/* Un <input type="number"> dispara `change` en cada paso del stepper nativo
   (flechita o ↑/↓ con foco), no solo al salir del campo -- confirmado a mano,
   no es la lectura habitual de "change = onBlur". Bajar 3 puntos de una
   tocaba 3 PUT y 3 filas de Historial para el mismo campo. Debounce por
   campo (cada llamada a numberField/probabilityField/channelOverrideRow crea
   su propio temporizador) junta esos pasos en un solo guardado. */
function debounce(fn, delayMs) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

const TUNABLE_SAVE_DEBOUNCE_MS = 500;

async function saveTunable(key, value, label, onSaved) {
  try {
    const r = await apiFetch(`/api/server/${GUILD_ID}/settings/chat/tunables`, {
      method: 'PUT', body: { [key]: value },
    });
    if (onSaved && r.saved && r.saved[key] !== undefined) onSaved(r.saved[key]);
    toast(`${label} actualizado`, 'ok');
  } catch (e) {
    toast(`No se pudo guardar ${label.toLowerCase()}, intenta de nuevo`, 'err');
  }
}

/* Campo numérico con autoguardado al salir del input (change, no input: no
   tiene sentido pegarle a la API en cada tecla) -- debounced, ver nota en
   debounce() arriba. */
function numberField(label, help, { key, value, min, max, step, suffix, save = saveTunable }) {
  const input = el('input', {
    type: 'number', value: String(value), min: String(min),
    max: String(max), step: String(step || 1), class: 'num-input',
  });
  input.onchange = debounce(() => {
    save(key, Number(input.value), label, (saved) => {
      input.value = String(saved);
    });
  }, TUNABLE_SAVE_DEBOUNCE_MS);
  return el('div', { class: 'field' },
    el('label', {}, label),
    el('div', { class: 'num-row' }, input, suffix ? el('span', { class: 'dim' }, suffix) : null),
    help ? el('p', { class: 'dim' }, help) : null);
}

/* Probabilidad 0–1 editada como porcentaje entero: input numérico como
   control primario (se puede escribir el número exacto) + barra de progreso
   de solo lectura debajo como feedback visual -- reemplaza el slider, que
   como único control obligaba a arrastrar con el mouse para acertar un
   número (revisión UX de CHAT). Autoguarda en `change`, igual que antes. */
function probabilityField(label, help, { key, value, save = saveTunable }) {
  const pct = Math.round(value * 100);
  const input = el('input', {
    type: 'number', min: '0', max: '100', step: '1', value: String(pct), class: 'num-input',
  });
  const bar = el('progress', { class: 'prob-bar', value: String(pct), max: '100' });
  input.onchange = debounce(() => {
    const clamped = Math.max(0, Math.min(100, Number(input.value) || 0));
    save(key, clamped / 100, label, (saved) => {
      const back = Math.round(saved * 100);
      input.value = String(back);
      bar.value = back;
    });
  }, TUNABLE_SAVE_DEBOUNCE_MS);
  return el('div', { class: 'field' },
    el('label', {}, label),
    el('div', { class: 'prob-row' }, input, el('span', { class: 'dim' }, '%')),
    bar,
    help ? el('p', { class: 'dim' }, help) : null);
}

/* Ajuste de un canal puntual: una sola fila por tunable, sin checkbox de
   "override" ni frase de estado repetida campo por campo. El input siempre
   muestra el valor que rige acá; atenuado mientras lo hereda del servidor,
   normal (y con botón de volver a heredar) cuando el canal tiene el suyo.
   Editar el input ES activar el override, y ↺ es sacarlo: dos gestos en vez
   de tres controles, y el estado lo carga el propio campo en vez de una
   oración que antes se repetía seis veces por canal. */
function channelOverrideRow(channelId, spec) {
  const { key, label, help, kind, effective, min, max, suffix } = spec;
  let override = spec.override;

  const toInput = v => (kind === 'percent' ? Math.round(v * 100) : v);
  const toApi = v => (kind === 'percent' ? v / 100 : v);

  const input = el('input', {
    type: 'number', class: 'num-input',
    min: String(kind === 'percent' ? 0 : min), max: String(kind === 'percent' ? 100 : max),
    step: '1',
  });
  const reset = el('button', {
    class: 'ovr-reset', title: 'Volver al valor del servidor', 'aria-label': 'Volver al valor del servidor',
    onclick: () => save(null),
  }, '↺');
  const caption = el('span', { class: 'dim ovr-caption' });
  const row = el('div', { class: 'ovr-row' },
    el('label', {}, label, help ? helpIcon(help) : null),
    el('div', { class: 'ovr-control' },
      input,
      suffix ? el('span', { class: 'dim ovr-suffix' }, suffix) : null,
      reset),
    caption);

  const fmt = v => {
    const n = toInput(v);
    if (!suffix) return String(n);
    return kind === 'percent' ? `${n}${suffix}` : `${n} ${suffix}`;
  };

  function paint() {
    const inherited = override === null || override === undefined;
    input.value = String(toInput(inherited ? effective : override));
    row.classList.toggle('is-override', !inherited);
    reset.hidden = inherited;
    caption.textContent = inherited
      ? `${fmt(effective)} · valor del servidor`
      : 'valor propio de este canal';
  }

  async function save(raw) {
    const prev = override;
    try {
      const r = await apiFetch(`/api/guilds/${GUILD_ID}/channels/${channelId}/settings`, {
        method: 'PUT', body: { [key]: raw === null ? null : toApi(raw) },
      });
      override = raw === null ? null : r.saved[key];
      paint();
      toast(raw === null ? `${label}: vuelve al valor del servidor` : `${label} actualizado en este canal`, 'ok');
    } catch (e) {
      override = prev;
      paint();
      toast(`No se pudo guardar ${label.toLowerCase()}, intenta de nuevo`, 'err');
    }
  }

  input.onchange = debounce(() => {
    const lo = kind === 'percent' ? 0 : min;
    const hi = kind === 'percent' ? 100 : max;
    save(Math.max(lo, Math.min(hi, Number(input.value) || 0)));
  }, TUNABLE_SAVE_DEBOUNCE_MS);

  paint();
  return row;
}

/* Multi-select de roles con toggle, gemelo de channelToggleList. Los roles no
   tienen el problema de permisos de los canales, así que es más simple. */
function roleToggleList({ roles, selected, add, remove, listBelow }) {
  const panel = el('div', { class: 'dd-panel chan-panel' });
  const btn = el('button', { class: 'dd-trigger' },
    'Seleccionar roles…', el('span', { class: 'dd-caret' }, '▾'));
  const dd = el('div', { class: 'dd' }, btn, panel);
  btn.onclick = (e) => { e.stopPropagation(); dd.classList.toggle('open'); };
  // Mismos chips que los canales: en Límites conviven las dos listas y una
  // como filas altas junto a la otra como chips se veía como dos componentes
  // distintos sin motivo.
  const list = el('div', { class: 'chan-chips' });

  let busy = false;
  async function toggle(role) {
    if (busy) return;
    busy = true;
    const had = selected.has(role.id);
    try {
      if (had) { await remove(role); toast('Rol quitado', 'ok'); }
      else { await add(role); toast('Rol agregado', 'ok'); }
    } catch (e) {
      toast(had ? 'No se pudo quitar el rol' : 'No se pudo agregar el rol', 'err');
    }
    busy = false;
    render();
  }

  function roleLabel(role) {
    return el('span', { class: 'role-name' },
      el('span', {
        class: 'role-dot',
        style: `background:${role.color && role.color !== '#000000' ? role.color : 'currentColor'}`,
      }),
      '@' + role.name);
  }

  function render() {
    panel.innerHTML = '';
    for (const role of roles) {
      panel.append(el('button', {
        class: 'dd-item chan-option' + (selected.has(role.id) ? ' active' : ''),
        onclick: (e) => { e.stopPropagation(); toggle(role); },
      }, roleLabel(role), selected.has(role.id) ? el('span', { class: 'chan-check' }, '✓') : null));
    }
    list.innerHTML = '';
    const sel = roles.filter(r => selected.has(r.id));
    if (!sel.length) list.append(el('span', { class: 'dim' }, listBelow));
    for (const role of sel) {
      list.append(el('span', { class: 'chan-chip' },
        roleLabel(role),
        el('button', {
          class: 'chan-chip-x', 'aria-label': `Quitar @${role.name}`, onclick: () => toggle(role),
        }, '✕')));
    }
  }
  render();
  return el('div', { class: 'chan-picker' }, dd, list);
}

// Sub-pestañas del tab CHAT (no confundir con TABS, que son las principales
// del dashboard). Viven en el hash de la URL —#canales, #personalidad…— en
// vez de un segmento de path, porque el path ya está tomado por el tab
// principal ('chat') y por el GUILD_ID.
//
// Cada sub-pestaña es una intención del admin ("qué hace", "dónde", "cuánto
// aguanta", "qué dice"), no el nombre del campo en la DB. El orden es la
// jerarquía: no hay captions de grupo intercalados entre los links —
// competían por el mismo espacio que los tabs clickeables.
//
// 'Por canal' ya no existe como pestaña: vive dentro de Canales, que es el
// contexto donde se piensa ("en #general quiero que hable más"). Frases y
// Triggers se unificaron en Contenido: las dos son lo que Purgito dice, y
// un trigger referencia un pack de frases.

// El listener de hashchange (soporta el botón atrás/adelante y links directos
// a #frases, etc.) vive en `_chatHashHandler`, declarado arriba junto a
// activate() — ver el comentario ahí sobre por qué no puede declararse acá.

// Banner "Primeros pasos" (revisión UX de CHAT): sin canales de aprendizaje
// nada del resto de la config tiene efecto práctico, así que esa es la única
// señal que chequeamos -- preferible a un AND de varias condiciones (tunables
// en default + sin frases + sin triggers...), que además de más frágil
// parpadearía en estados de config parcial. Dismissible, no modal: no hay
// wizard que interrumpa. El dismiss se guarda en localStorage por guild (no
// en la DB, sin aprobación para eso todavía): si el admin administra más de
// un servidor, cerrarlo en uno no debe ocultarlo en los demás. Trade-off
// conocido: un admin que ya configuró todo y después queda con la lista de
// canales vacía (a propósito o por error) va a volver a ver el banner aunque
// no sea su primera vez -- no hay un estado real de "primera vez" sin tocar
// el backend, y no hace falta resolverlo en esta pasada.
function chatOnboardingDismissedKey() {
  return `purgito_chat_onboarding_dismissed_${GUILD_ID}`;
}

function buildOnboardingBanner(corpus, activateSubtab) {
  if (corpus.channels.length > 0) return null;
  if (localStorage.getItem(chatOnboardingDismissedKey())) return null;

  const banner = el('div', { class: 'onboarding-banner' },
    el('span', {}, 'Purgito no aprende de ningún canal todavía.'),
    el('a', {
      href: '#canales', onclick: (ev) => { ev.preventDefault(); activateSubtab('canales'); },
    }, 'Elegir canales'),
    el('button', {
      class: 'onboarding-dismiss', 'aria-label': 'Cerrar',
      onclick: () => { localStorage.setItem(chatOnboardingDismissedKey(), '1'); banner.remove(); },
    }, '✕'));
  return banner;
}

/* Matriz de canales: una fila por canal con sus tres pertenencias (habla /
   responde / aprende) y, plegado, sus ajustes propios. Reemplaza tres
   dropdowns con tres listas de chips MÁS la sub-pestaña "Por canal": la
   pregunta real del admin es "¿qué hace Purgito en #general?", y antes había
   que cruzar cuatro pantallas para contestarla. El filtro de arriba es lo que
   mantiene esto usable en un server con muchos canales. */
function channelMatrix({ channels, cols, openOverrides }) {
  const wrap = el('div', { class: 'chan-matrix' });
  const filter = el('input', {
    type: 'search', placeholder: 'Filtrar canales…', class: 'chan-filter', autocomplete: 'off',
  });
  const body = el('div', { class: 'chan-matrix-body' });

  const head = el('div', { class: 'chan-matrix-head' },
    el('span', {}, 'Canal'),
    ...cols.map(c => el('span', { class: 'chan-matrix-col' }, c.short, helpIcon(c.help))),
    el('span', { class: 'chan-matrix-col' }, 'Ajustes'));

  function rowFor(ch) {
    const row = el('div', { class: 'chan-matrix-row' });
    const panel = el('div', { class: 'chan-matrix-panel' });
    panel.hidden = true;
    let loaded = false;

    const gear = el('button', {
      class: 'chan-gear', title: `Ajustes de #${ch.name}`, 'aria-label': `Ajustes de #${ch.name}`,
      onclick: async () => {
        panel.hidden = !panel.hidden;
        row.classList.toggle('open', !panel.hidden);
        if (panel.hidden || loaded) return;
        loaded = true;
        panel.append(spinner());
        try { await openOverrides(ch, panel); } catch (e) { renderError(panel, e); }
      },
    }, '⚙');

    row.append(
      el('span', { class: 'chan-name' + (ch.can_send === false ? ' chan-noperm' : '') },
        '#' + (ch.name || ch.id),
        ch.can_send === false
          ? el('span', { class: 'chan-warn', title: 'El bot no puede leer o escribir en este canal' }, '⚠')
          : null),
      ...cols.map((c) => {
        const box = el('input', { type: 'checkbox', checked: c.isSelected(ch.id) });
        box.onchange = async () => {
          const on = box.checked;
          try {
            if (on) await c.add(ch); else await c.remove(ch);
            toast(`#${ch.name}: ${on ? c.onLabel : c.offLabel}`, 'ok');
          } catch (e) {
            box.checked = !on;
            toast('No se pudo guardar, intenta de nuevo', 'err');
          }
        };
        return el('label', { class: 'chan-matrix-cell', title: c.short }, box);
      }),
      el('span', { class: 'chan-matrix-cell' }, gear));
    return el('div', { class: 'chan-matrix-item' }, row, panel);
  }

  const items = channels.map(ch => ({ ch, node: rowFor(ch) }));
  for (const it of items) body.append(it.node);
  filter.oninput = () => {
    const q = filter.value.trim().toLowerCase();
    for (const it of items) it.node.hidden = q && !(it.ch.name || '').toLowerCase().includes(q);
  };

  wrap.append(filter, head, body);
  return wrap;
}

async function loadChatTab() {
  const box = content();
  box.append(spinner());
  try {
    const [chat, spontaneousChans, mentionChans, corpus, reactions, frases, fraseChannels, frasePacks, triggers, exempt, exemptChans, channels, roles] =
      await Promise.all([
        apiFetch(`/api/server/${GUILD_ID}/settings/chat`),
        apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels`),
        apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels`),
        apiFetch(`/api/server/${GUILD_ID}/settings/corpus`),
        apiFetch(`/api/server/${GUILD_ID}/settings/reacciones`),
        apiFetch(`/api/server/${GUILD_ID}/settings/frases`),
        apiFetch(`/api/server/${GUILD_ID}/settings/frases/channels`),
        apiFetch(`/api/server/${GUILD_ID}/frases/packs`),
        apiFetch(`/api/server/${GUILD_ID}/settings/triggers`),
        apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles`),
        apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels`),
        getChannels({ force: true }),
        getRoles(),
      ]);
    box.innerHTML = '';
    const lim = chat.limits || {};

    // --- Switch maestro: una línea, fuera de las sub-pestañas ---
    // Antes era un formGroup entero con título y párrafo, ~100px que se comían
    // en TODAS las sub-pestañas; el detalle de qué apaga exactamente ahora va
    // en el ⓘ.
    const check = el('input', { type: 'checkbox', checked: chat.enabled });
    check.onchange = async () => {
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/chat`, {
          method: 'PUT', body: { enabled: check.checked },
        });
        toast(check.checked ? 'Chat activado' : 'Chat desactivado', 'ok');
      } catch (e) {
        check.checked = !check.checked;
        toast('No se pudo guardar, intenta de nuevo', 'err');
      }
    };
    box.append(el('div', { class: 'chat-master' },
      el('label', { class: 'toggle' }, check, 'Chat activado'),
      helpIcon('Apaga las respuestas a menciones. Los mensajes espontáneos, '
        + 'las reacciones y los triggers no dependen de este switch.')));

    // --- Sub-pestaña: Canales ---
    function buildCanales() {
      const spontaneousSelected = new Set(spontaneousChans.channels.map(c => c.id));
      const mentionSelected = new Set(mentionChans.channels.map(c => c.id));
      const corpusSelected = new Set(corpus.channels.map(c => c.id));
      const ignoredSet = new Set(corpus.ignored || []);

      const cols = [
        {
          short: 'Habla', onLabel: 'habla por su cuenta acá', offLabel: 'ya no habla solo acá',
          help: 'Purgito puede arrancar una charla por su cuenta en este canal. '
            + 'Sin ningún canal marcado, puede hacerlo en todos.',
          isSelected: id => spontaneousSelected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            spontaneousSelected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels/${ch.id}`, { method: 'DELETE' });
            spontaneousSelected.delete(ch.id);
          },
        },
        {
          short: 'Responde', onLabel: 'responde menciones acá', offLabel: 'ya no responde menciones acá',
          help: 'Purgito contesta cuando lo mencionan en este canal. Sin ningún '
            + 'canal marcado, responde en todos.',
          isSelected: id => mentionSelected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            mentionSelected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels/${ch.id}`, { method: 'DELETE' });
            mentionSelected.delete(ch.id);
          },
        },
        {
          short: 'Aprende', onLabel: 'aprende de acá', offLabel: 'ya no aprende de acá',
          help: 'Purgito guarda los mensajes de este canal para armar su estilo. '
            + 'Sin ningún canal marcado, no aprende de nada.',
          isSelected: id => corpusSelected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/corpus`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            corpusSelected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/corpus/${ch.id}`, { method: 'DELETE' });
            corpusSelected.delete(ch.id);
          },
        },
      ];

      // Ajustes propios del canal, plegados dentro de su fila: es el viejo tab
      // "Por canal" pero sin salir del contexto donde se piensa la pregunta.
      async function openOverrides(ch, panel) {
        const data = await apiFetch(`/api/guilds/${GUILD_ID}/channels/${ch.id}/settings`);
        const eff = data.effective, ov = data.overrides, lim2 = data.limits || {};
        const rng = (k, d) => lim2[k] || d;
        panel.innerHTML = '';
        panel.append(
          el('div', { class: 'ovr-grid' },
            channelOverrideRow(ch.id, {
              key: 'auto_generate_every', label: 'Cada cuántos mensajes', kind: 'number',
              effective: eff.auto_generate_every, override: ov.auto_generate_every,
              min: rng('auto_generate_every', [1])[0], max: rng('auto_generate_every', [null, 1000])[1],
              suffix: 'mensajes',
            }),
            channelOverrideRow(ch.id, {
              key: 'auto_generate_probability', label: 'Probabilidad de hablar', kind: 'percent',
              effective: eff.auto_generate_probability, override: ov.auto_generate_probability, suffix: '%',
            }),
            channelOverrideRow(ch.id, {
              key: 'gif_response_probability', label: 'Responde con GIF', kind: 'percent',
              effective: eff.gif_response_probability, override: ov.gif_response_probability, suffix: '%',
            }),
            channelOverrideRow(ch.id, {
              key: 'frase_probability', label: 'Usa una frase especial', kind: 'percent',
              effective: eff.frase_probability, override: ov.frase_probability, suffix: '%',
            }),
            channelOverrideRow(ch.id, {
              key: 'reaction_probability', label: 'Reacciona con emoji', kind: 'percent',
              effective: eff.reaction_probability, override: ov.reaction_probability, suffix: '%',
            }),
            channelOverrideRow(ch.id, {
              key: 'mention_rate_limit', label: 'Menciones por hora', kind: 'number',
              effective: eff.mention_rate_limit, override: ov.mention_rate_limit,
              min: rng('mention_rate_limit', [0])[0], max: rng('mention_rate_limit', [null, 1000])[1],
              suffix: 'por usuario',
            })));
      }

      return el('div', {},
        ignoredSet.size
          ? el('p', { class: 'dim' }, ignoredSet.size === 1
            ? 'Hay 1 canal silenciado desde /settings: queda fuera aunque lo marques acá.'
            : `Hay ${ignoredSet.size} canales silenciados desde /settings: quedan fuera aunque los marques acá.`)
          : null,
        channelMatrix({ channels, cols, openOverrides }));
    }

    // --- Sub-pestaña: Datos ---
    // Importar corpus y Amnesia vivían en Canales solo porque "también son de
    // CHAT" -- sin relación real con elegir canales de aprendizaje/menciones,
    // y Amnesia además es destructiva. Canales ya tiene 3 selectores de
    // canales; meter acciones acá competiría por atención en la misma
    // pantalla, así que quedan en su propia sub-pestaña (revisión UX de
    // CHAT).
    function buildDatos() {
      return el('div', {},
        formGroup('Importar corpus desde un archivo',
          el('p', { class: 'dim' },
            'Sube un .txt: cada línea no vacía entra al corpus del canal '
            + 'elegido como si fuera un mensaje real, con la misma limpieza y '
            + 'los mismos límites de siempre.'),
          corpusImportForm(channels)),
        formGroup('Amnesia',
          el('p', { class: 'dim' },
            'Borra el corpus (mensajes y estilo por usuario) de las últimas '
            + '24 horas de todo el servidor. Es irreversible.'),
          amnesiaButton()));
    }

    // --- Sub-pestaña: Comportamiento ---
    //
    // Una sola cadena, no dos bloques: los pasos 2 y 3 corren tanto cuando
    // Purgito arranca solo como cuando contesta una mención (cogs/chat.py:
    // ~730/736 el camino espontáneo, ~805/812 el de mención, mismos dos
    // rolls). Solo el paso 1 es exclusivo del camino espontáneo, y eso lo
    // dice el ⓘ del paso, no un párrafo permanente.
    function buildComportamiento() {
      return el('div', { class: 'chain' },
        el('div', { class: 'chain-step' },
          el('div', { class: 'chain-step-head' },
            el('span', { class: 'chain-num' }, '1'),
            el('h3', {}, '¿Arranca una charla solo?'),
            helpIcon('Solo para cuando habla por su cuenta (con un piso de silencio de '
              + '45 s en el canal para no spamear). Si lo mencionan responde directo, '
              + 'sin pasar por este paso.')),
          el('div', { class: 'chain-fields' },
            numberField('Cada cuántos mensajes nuevos', null, {
              key: 'auto_generate_every',
              value: chat.auto_generate_every,
              min: (lim.auto_generate_every || [1])[0],
              max: (lim.auto_generate_every || [null, 1000])[1],
              suffix: 'mensajes',
            }),
            probabilityField('Y ahí, cuántas veces habla', null, {
              key: 'auto_generate_probability',
              value: chat.auto_generate_probability,
            }))),
        el('div', { class: 'chain-step' },
          el('div', { class: 'chain-step-head' },
            el('span', { class: 'chain-num' }, '2'),
            el('h3', {}, '¿Manda un GIF o escribe?'),
            helpIcon('Los GIFs salen de la galería del tab GIFS.')),
          el('div', { class: 'chain-fields' },
            probabilityField('Manda un GIF', null, {
              key: 'gif_response_probability',
              value: chat.gif_response_probability,
            }))),
        el('div', { class: 'chain-step' },
          el('div', { class: 'chain-step-head' },
            el('span', { class: 'chain-num' }, '3'),
            el('h3', {}, 'Si escribe, ¿frase tuya o inventada?'),
            helpIcon('Las frases se cargan en Contenido. El resto de las veces '
              + 'arma el mensaje solo, con lo que aprendió del servidor.')),
          el('div', { class: 'chain-fields' },
            probabilityField('Usa una frase tuya', null, {
              key: 'frase_probability',
              value: chat.frase_probability,
            }))));
    }

    // --- Sub-pestaña: Reacciones ---
    // Aparte de la cadena a propósito: el roll de reaction_probability corre
    // en cada mensaje que lee, decida hablar o no (cogs/chat.py ~683, antes y
    // por fuera de auto_generate).
    function buildReacciones() {
      const reaccionesBox = el('div', {});
      renderReacciones(reaccionesBox, reactions.reactions);
      return el('div', {},
        probabilityField('Reacciona con un emoji', null, {
          key: 'reaction_probability',
          value: chat.reaction_probability,
        }),
        el('div', { class: 'field' },
          el('label', {}, 'Emojis que puede usar', helpIcon(
            'Se evalúa en cada mensaje que lee, sin relación con si decide responder.')),
          reaccionesBox));
    }

    // --- Sub-pestaña: Límites ---
    function buildLimites() {
      const exemptSelected = new Set(exempt.roles.map(r => r.id));
      const exemptChannelsSelected = new Set(exemptChans.channels.map(c => c.id));
      return formGroup(el('span', {}, 'Límite de actividad',
        helpIcon('0 = sin límite.')),
        numberField('Menciones por hora', null, {
          key: 'mention_rate_limit',
          value: chat.mention_rate_limit,
          min: (lim.mention_rate_limit || [0])[0],
          max: (lim.mention_rate_limit || [null, 1000])[1],
          suffix: 'por usuario',
        }),
        el('div', { class: 'field' },
          el('label', {}, 'Roles exentos del límite'),
          roleToggleList({
            roles,
            selected: exemptSelected,
            add: async role => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles`, {
                method: 'POST', body: { role_id: role.id },
              });
              exemptSelected.add(role.id);
            },
            remove: async role => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles/${role.id}`, {
                method: 'DELETE',
              });
              exemptSelected.delete(role.id);
            },
            listBelow: 'Ningún rol exento — el límite aplica a todos por igual.',
          })),
        el('div', { class: 'field' },
          el('label', {}, 'Canales exentos del límite'),
          channelToggleList({
            channels,
            isSelected: id => exemptChannelsSelected.has(id),
            add: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels`, {
                method: 'POST', body: { channel_id: ch.id },
              });
              exemptChannelsSelected.add(ch.id);
            },
            remove: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels/${ch.id}`, {
                method: 'DELETE',
              });
              exemptChannelsSelected.delete(ch.id);
            },
            listBelow: 'Ningún canal exento — el límite aplica en todos.',
          })));
    }

    // --- Sub-pestaña: Contenido (frases + packs + triggers) ---
    // Frases y triggers eran dos pestañas separadas pese a ser lo mismo desde
    // la intención del admin ("qué dice Purgito"), y un trigger encima elige
    // un pack de frases: separarlas obligaba a saltar de pestaña para armar
    // una sola cosa. Packs y canales van plegados: son el ajuste fino.
    function buildContenido() {
      const frasesBox = el('div', {});
      renderFrases(frasesBox, frases.frases, frasePacks.packs, frases.limit);

      const packsBox = el('div', {});
      renderFrasePacks(packsBox, frasePacks.packs, channels, frasesBox, frasePacks.limit);

      const fraseChannelsSelected = new Set(fraseChannels.channels.map(c => c.id));
      const triggersBox = el('div', {});
      renderTriggers(triggersBox, triggers, channels, frasePacks.packs);

      const TAGS = ['{{user.mention}}', '{{user.name}}', '{{channel.name}}',
        '{{channel.mention}}', '{{guild.name}}', '{{markov.word}}', '{{markov.sentence}}'];

      return el('div', {},
        formGroup(el('span', {}, 'Frases',
          helpIcon('Con qué frecuencia las usa se ajusta en Comportamiento, paso 3.')),
          frasesBox,
          accordionGroup('Tags que puedes usar en una frase', false,
            el('div', { class: 'tag-list' },
              TAGS.map(t => el('code', { class: 'cmd' }, t))))),
        formGroup(el('span', {}, 'Packs',
          helpIcon('Un pack agrupa frases y se asigna a canales: ahí solo salen '
            + 'esas. Una frase sin pack queda en el pool general del servidor.')),
          packsBox),
        formGroup(el('span', {}, 'Triggers',
          helpIcon('Si el mensaje matchea el patrón, Purgito responde sin esperar '
            + 'mención ni el roll de frecuencia. Con varios en el mismo canal gana '
            + 'el primero que matchea.')),
          triggersBox),
        accordionGroup('Dónde pueden salir las frases especiales', false,
          channelToggleList({
            channels,
            isSelected: id => fraseChannelsSelected.has(id),
            add: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/frases/channels`, {
                method: 'POST', body: { channel_id: ch.id },
              });
              fraseChannelsSelected.add(ch.id);
            },
            remove: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/frases/channels/${ch.id}`, {
                method: 'DELETE',
              });
              fraseChannelsSelected.delete(ch.id);
            },
            listBelow: 'Sin canales elegidos — puede salir en cualquiera.',
          })));
    }

    // --- Sub-pestaña: Playground ---
    function buildPlayground() {
      const sel = channelSelect(channels, null, 'Elige un canal…');
      const input = el('textarea', {
        rows: '3', placeholder: 'Mensaje de prueba…', style: 'width:100%',
      });
      const resultBox = el('div', {});
      const btn = el('button', {
        class: 'btn btn-primary',
        onclick: async () => {
          const message = input.value.trim();
          if (!sel.value || !message) {
            toast('Elige un canal y escribe un mensaje de prueba', 'warn');
            return;
          }
          resultBox.innerHTML = '';
          resultBox.append(spinner());
          try {
            const data = await apiFetch(`/api/server/${GUILD_ID}/chat/playground`, {
              method: 'POST', body: { channel_id: sel.value, message },
            });
            renderPlaygroundResult(resultBox, data);
          } catch (e) { renderError(resultBox, e); }
        },
      }, 'Simular');

      return el('div', {},
        el('div', { class: 'field' },
          el('label', {}, 'Canal', helpIcon(
            'Simula con la configuración efectiva del canal: overrides, packs y '
            + 'triggers incluidos. No manda nada de verdad ni gasta cooldowns.')),
          sel),
        el('div', { class: 'field' }, el('label', {}, 'Mensaje de prueba'), input),
        btn,
        resultBox);
    }

    const BUILDERS = {
      comportamiento: buildComportamiento,
      canales: buildCanales,
      contenido: buildContenido,
      reacciones: buildReacciones,
      limites: buildLimites,
      datos: buildDatos,
      playground: buildPlayground,
    };

    const panelsWrap = el('div', { class: 'chat-panels-wrap' }, CHAT_SUBTABS.map(st => panels[st.key]));

    // Todo se autoguarda al toque (sin botón "Guardar" ni estado sin
    // confirmar), así que cambiar de sub-pestaña nunca pierde nada: no hay
    // que preservar más que qué pestaña estaba activa.
    function activateSubtab(key) {
      document.querySelectorAll('.dash-subtab').forEach(n =>
        n.classList.toggle('active', n.dataset.key === key));
      const mobileSubName = document.querySelector('.dash-mobile-subtab-name');
      if (mobileSubName) {
        const found = CHAT_SUBTABS.find(s => s.key === key);
        mobileSubName.textContent = found ? (found.key === 'playground' ? 'Probar' : found.label) : '';
      }
      for (const st of CHAT_SUBTABS) {
        const active = st.key === key;
        if (panels[st.key]) {
          panels[st.key].hidden = !active;
          if (!active) {
            panels[st.key].querySelectorAll('.dd.open').forEach(d => d.classList.remove('open'));
          }
        }
      }
      history.replaceState(null, '', `${location.pathname}${location.search}#${key}`);
    }

    _activeChatSubtabSetter = activateSubtab;
    const onboarding = buildOnboardingBanner(corpus, activateSubtab);
    if (onboarding) box.append(onboarding);
    box.append(panelsWrap);
    activateSubtab(currentChatSubtab());

    if (_chatHashHandler) window.removeEventListener('hashchange', _chatHashHandler);
    _chatHashHandler = () => activateSubtab(currentChatSubtab());
    window.addEventListener('hashchange', _chatHashHandler);
  } catch (e) { renderError(box, e); }
}

async function renderReacciones(box, pool) {
  box.innerHTML = '';
  const inPool = new Set(pool.map(r => r.emoji_text));
  // Chips, no filas de alto completo: un emoji ocupa dos caracteres y una fila
  // entera con un botón "Quitar" rojo por cada uno era la misma incomodidad
  // que la lista de canales.
  const list = el('div', { class: 'chan-chips' });
  if (!pool.length) list.append(el('span', { class: 'dim' }, 'Todavía no hay emojis en la colección.'));
  for (const r of pool) {
    list.append(el('span', { class: 'chan-chip' },
      el('span', {}, r.emoji_text),
      el('button', {
        class: 'chan-chip-x', 'aria-label': `Quitar ${r.emoji_text}`,
        onclick: () => removeReaction(box, r.id),
      }, '✕')));
  }

  async function addEmoji(emojiText) {
    try {
      await apiFetch(`/api/server/${GUILD_ID}/settings/reacciones`, {
        method: 'POST', body: { emoji: emojiText },
      });
      toast('Emoji agregado', 'ok');
      reloadReacciones(box);
    } catch (e) { toast('No se pudo agregar el emoji, intenta de nuevo', 'err'); }
  }

  // autocomplete="off": sin esto, Chrome con una cuenta sincronizada trata
  // este input suelto como un campo de nombre/dirección y ofrece autocompletar
  // con datos de perfil — aparece como un chip con el avatar de la cuenta
  // pegado al input, encima de lo que sea que haya debajo (acá, "Agregar").
  // No es un emoji renderizado por nuestro código, es una sugerencia del
  // navegador que no tiene nada que ver con la lista.
  const input = el('input', {
    type: 'text', placeholder: 'Emoji (😀)', maxlength: '64', autocomplete: 'off',
  });
  const addRow = el('div', { class: 'add-row' }, input,
    el('button', {
      class: 'btn btn-primary',
      onclick: () => { if (input.value.trim()) addEmoji(input.value.trim()); },
    }, 'Agregar'));

  // Emojis del servidor: click agrega, click sobre uno ya agregado lo quita.
  const grid = el('div', { class: 'emoji-grid' });
  try {
    const emojis = await getEmojis();
    for (const e of emojis) {
      const text = `<${e.animated ? 'a' : ''}:${e.name}:${e.id}>`;
      const selected = inPool.has(text);
      grid.append(el('button', {
        class: 'emoji-cell' + (selected ? ' active' : ''),
        title: ':' + e.name + ':',
        onclick: () => {
          if (selected) {
            const row = pool.find(r => r.emoji_text === text);
            if (row) removeReaction(box, row.id);
          } else addEmoji(text);
        },
      }, el('img', { src: e.url, alt: e.name, loading: 'lazy' })));
    }
  } catch (e) { /* sin emojis custom no pasa nada, queda el input */ }

  // append() es el nativo, no el(): un null acá se agrega como el texto
  // "null" (se veía en cualquier servidor sin emojis propios).
  box.append(list, addRow);
  if (grid.children.length) box.append(grid);
}

async function removeReaction(box, id) {
  try {
    await apiFetch(`/api/server/${GUILD_ID}/settings/reacciones/${id}`, { method: 'DELETE' });
    toast('Emoji quitado', 'ok');
  } catch (e) { toast('No se pudo quitar el emoji, intenta de nuevo', 'err'); }
  reloadReacciones(box);
}

async function reloadReacciones(box) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/reacciones`);
    renderReacciones(box, data.reactions);
  } catch (e) { /* se queda como estaba */ }
}

// `packs` decide si se muestra el selector de pack por frase: sin packs
// creados todavía no tiene sentido mostrar un <select> con una sola opción.
/* "12 de 50 usadas" arriba de una lista con cupo. Antes el límite solo se
   descubría al chocarlo (un 409 al agregar): nada mostraba cuánto quedaba. */
/* `singular`/`plural` traen ya el participio concordado ('pack usado',
   'frases usadas'): el género lo pone quien llama, porque acá se usa tanto
   para frases (femenino) como para packs y triggers (masculino) -- estaba
   fijo en "usadas" y salía "3 de 10 triggers usadas". */
function cupoLine(used, limit, singular, plural, lleno_msg) {
  if (!limit) return null;
  const lleno = used >= limit;
  return el('p', { class: lleno ? '' : 'dim' },
    `${used} de ${limit} ${used === 1 ? singular : plural}`,
    lleno ? ` — llegaste al tope: ${lleno_msg}` : '');
}

function renderFrases(box, frases, packs, limit) {
  const state = box._frasesState || {
    search: '',
    page: 1,
    editingId: null,
    editingText: '',
    isSaving: false,
  };
  box._frasesState = state;
  state.frases = frases || [];
  state.packs = packs || [];
  state.limit = limit || 200;

  box.innerHTML = '';
  const container = el('div', { class: 'frases-container' });
  const cupoWrapper = el('div', { class: 'frases-cupo' });
  const searchWrapper = el('div', { class: 'frases-toolbar' });
  const listWrapper = el('div', { class: 'frases-list-wrapper' });
  const paginationWrapper = el('div', { class: 'frases-pagination-wrapper' });

  function updateCupo() {
    cupoWrapper.innerHTML = '';
    const cupo = cupoLine(
      state.frases.length,
      state.limit,
      'frase usada',
      'frases usadas',
      'elimina una para agregar otra.'
    );
    if (cupo) cupoWrapper.append(cupo);
  }

  const searchInput = el('input', {
    type: 'search',
    class: 'frases-search-input',
    placeholder: 'Buscar una frase…',
    value: state.search,
    autocomplete: 'off',
    'aria-label': 'Buscar una frase',
  });

  searchInput.oninput = () => {
    state.search = searchInput.value;
    state.page = 1;
    renderListAndPagination();
  };

  searchWrapper.append(searchInput);

  const PAGE_SIZE = 20;

  function renderListAndPagination() {
    listWrapper.innerHTML = '';
    paginationWrapper.innerHTML = '';

    if (!state.frases.length) {
      searchWrapper.style.display = 'none';
      listWrapper.append(
        el('ul', { class: 'item-list frases-list' },
          el('li', { class: 'dim' }, 'Todavía no has agregado ninguna frase.'))
      );
      return;
    }

    searchWrapper.style.display = '';

    const q = (state.search || '').trim().toLowerCase();
    const filtered = q
      ? state.frases.filter(f => (f.frase || '').toLowerCase().includes(q))
      : state.frases;

    if (!filtered.length) {
      listWrapper.append(
        el('div', { class: 'frases-empty-search' },
          el('p', { class: 'dim' }, 'No hay frases que coincidan con tu búsqueda.'),
          el('button', {
            class: 'btn btn-secondary btn-sm',
            onclick: () => {
              state.search = '';
              searchInput.value = '';
              state.page = 1;
              renderListAndPagination();
              searchInput.focus();
            },
          }, 'Limpiar búsqueda'))
      );
      return;
    }

    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (state.page > totalPages) state.page = totalPages;
    if (state.page < 1) state.page = 1;

    const startIdx = (state.page - 1) * PAGE_SIZE;
    const pageItems = filtered.slice(startIdx, startIdx + PAGE_SIZE);

    const list = el('ul', { class: 'item-list frases-list' });

    for (const f of pageItems) {
      if (state.editingId === f.id) {
        const editInput = el('input', {
          type: 'text',
          class: 'frase-edit-input',
          maxlength: '300',
          value: state.editingText !== undefined ? state.editingText : f.frase,
          disabled: state.isSaving,
          'aria-label': 'Editar frase',
        });

        async function saveCurrentEdit() {
          const newText = editInput.value.trim();
          if (!newText) {
            toast('La frase no puede estar vacía', 'warn');
            return;
          }
          if (newText.length > 300) {
            toast('La frase no puede superar los 300 caracteres', 'warn');
            return;
          }
          if (newText === f.frase) {
            state.editingId = null;
            state.editingText = '';
            renderListAndPagination();
            return;
          }
          state.isSaving = true;
          renderListAndPagination();
          try {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, {
              method: 'PATCH',
              body: { frase: newText },
            });
            f.frase = newText;
            state.editingId = null;
            state.editingText = '';
            state.isSaving = false;
            toast('Frase actualizada', 'ok');
            renderListAndPagination();
          } catch (e) {
            state.isSaving = false;
            toast(e.message || 'No se pudo actualizar la frase, intenta de nuevo', 'err');
            renderListAndPagination();
          }
        }

        editInput.oninput = () => {
          state.editingText = editInput.value;
        };

        editInput.onkeydown = (ev) => {
          if (ev.key === 'Enter') {
            ev.preventDefault();
            saveCurrentEdit();
          } else if (ev.key === 'Escape') {
            state.editingId = null;
            state.editingText = '';
            renderListAndPagination();
          }
        };

        const saveBtn = el('button', {
          class: 'btn btn-primary btn-sm',
          disabled: state.isSaving,
          onclick: saveCurrentEdit,
        }, state.isSaving ? 'Guardando…' : 'Guardar');

        const cancelBtn = el('button', {
          class: 'btn btn-secondary btn-sm',
          disabled: state.isSaving,
          onclick: () => {
            state.editingId = null;
            state.editingText = '';
            renderListAndPagination();
          },
        }, 'Cancelar');

        list.append(
          el('li', { class: 'frase-item frase-item-editing' },
            editInput,
            el('div', { class: 'frase-actions' }, saveBtn, cancelBtn))
        );
        setTimeout(() => editInput.focus(), 0);
      } else {
        let packSelect = null;
        if (state.packs.length) {
          packSelect = el('select', { class: 'frase-pack-select', 'aria-label': 'Pack de la frase' });
          packSelect.append(el('option', { value: '' }, 'Sin pack (default)'));
          for (const p of state.packs) {
            packSelect.append(el('option', { value: String(p.id) }, p.name));
          }
          packSelect.value = f.pack_id != null ? String(f.pack_id) : '';
          packSelect.onchange = async () => {
            const chosen = packSelect.value ? Number(packSelect.value) : null;
            try {
              await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, {
                method: 'PATCH',
                body: { pack_id: chosen },
              });
              f.pack_id = chosen;
              toast('Pack de la frase actualizado', 'ok');
            } catch (e) {
              toast('No se pudo actualizar el pack, intenta de nuevo', 'err');
              packSelect.value = f.pack_id != null ? String(f.pack_id) : '';
            }
          };
        }

        const editBtn = el('button', {
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            state.editingId = f.id;
            state.editingText = f.frase;
            renderListAndPagination();
          },
        }, 'Editar');

        const delBtn = confirmDelBtn('¿Eliminar esta frase? No se puede recuperar.', async () => {
          try {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, { method: 'DELETE' });
            toast('Frase quitada', 'ok');
            state.frases = state.frases.filter(item => item.id !== f.id);
            if (state.editingId === f.id) {
              state.editingId = null;
              state.editingText = '';
            }
            updateCupo();
            renderListAndPagination();
          } catch (e) {
            toast('No se pudo quitar la frase, intenta de nuevo', 'err');
          }
        });

        list.append(
          el('li', { class: 'frase-item' },
            el('span', { class: 'frase-text' }, f.frase),
            packSelect,
            el('div', { class: 'frase-actions' }, editBtn, delBtn)
          )
        );
      }
    }

    listWrapper.append(list);

    if (totalPages > 1) {
      const prevBtn = el('button', {
        class: 'btn btn-secondary btn-sm',
        disabled: state.page <= 1,
        onclick: () => {
          if (state.page > 1) {
            state.page--;
            renderListAndPagination();
          }
        },
      }, '← Anterior');

      const endIdx = Math.min(startIdx + PAGE_SIZE, filtered.length);
      const infoText = `Página ${state.page} de ${totalPages} · Mostrando ${startIdx + 1}–${endIdx} de ${filtered.length}`;

      const nextBtn = el('button', {
        class: 'btn btn-secondary btn-sm',
        disabled: state.page >= totalPages,
        onclick: () => {
          if (state.page < totalPages) {
            state.page++;
            renderListAndPagination();
          }
        },
      }, 'Siguiente →');

      paginationWrapper.append(
        el('div', { class: 'frases-pagination' },
          prevBtn,
          el('span', { class: 'frases-pagination-info' }, infoText),
          nextBtn
        )
      );
    }
  }

  const addInput = el('input', { type: 'text', placeholder: 'Nueva frase…', maxlength: '300' });
  async function addFrase() {
    const frase = addInput.value.trim();
    if (!frase) return;
    try {
      await apiFetch(`/api/server/${GUILD_ID}/settings/frases`, {
        method: 'POST', body: { frase },
      });
      toast('Frase agregada', 'ok');
      addInput.value = '';
      reloadFrases(box, state.packs);
    } catch (e) {
      toast(e.status === 409 ? e.message : 'No se pudo agregar la frase, intenta de nuevo', e.status === 409 ? 'warn' : 'err');
    }
  }
  addInput.onkeydown = (ev) => { if (ev.key === 'Enter') addFrase(); };
  const addRow = el('div', { class: 'add-row' },
    addInput,
    el('button', { class: 'btn btn-primary', onclick: addFrase }, 'Agregar')
  );

  updateCupo();
  renderListAndPagination();

  container.append(cupoWrapper, searchWrapper, listWrapper, paginationWrapper, addRow);
  box.append(container);
}

async function reloadFrases(box, packs) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/frases`);
    renderFrases(box, data.frases, packs, data.limit);
  } catch (e) { /* se queda como estaba */ }
}

// Un <details> por pack (colapsado): adentro, sus canales asignados con el
// mismo channelToggleList de arriba. La lista de canales del pack se pide
// recién al abrirlo (no en el fetch inicial del tab) porque son N pedidos
// más, uno por pack, que la mayoría de las veces nadie va a mirar.
function renderFrasePacks(box, packs, channels, frasesBox, limit) {
  box.innerHTML = '';
  const cupo = cupoLine(packs.length, limit, 'pack usado', 'packs usados',
    'elimina uno para agregar otro.');
  if (cupo) box.append(cupo);
  if (!packs.length) {
    box.append(el('p', { class: 'dim' },
      'Sin packs todavía — todas las frases están en el pool default del servidor.'));
  }
  for (const pack of packs) {
    const channelsBox = el('div', {}, el('p', { class: 'dim' }, 'Abre para ver los canales asignados…'));
    let loaded = false;
    const details = el('details', { class: 'embed-group' },
      el('summary', { class: 'embed-group-title' }, pack.name),
      el('div', { class: 'embed-group-body' },
        channelsBox,
        confirmDelBtn(
          '¿Eliminar este pack? Sus frases no se borran: vuelven al pool '
          + 'default del servidor, así que los canales que tenían este pack '
          + 'asignado van a empezar a usar ese pool.',
          async () => {
            try {
              await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}`, { method: 'DELETE' });
              toast('Pack eliminado', 'ok');
            } catch (e) { toast('No se pudo eliminar el pack, intenta de nuevo', 'err'); }
            // Las frases que tenía el pack volvieron al pool default en la DB
            // (delete_frase_pack en db.py): refresca también sus selects.
            refreshFrasesAndPacks(frasesBox, box, channels);
          },
          { label: 'Eliminar pack' })));
    details.addEventListener('toggle', async () => {
      if (!details.open || loaded) return;
      loaded = true;
      channelsBox.innerHTML = '';
      channelsBox.append(spinner());
      try {
        const data = await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}/channels`);
        const selected = new Set(data.channels.map(c => c.id));
        channelsBox.innerHTML = '';
        channelsBox.append(channelToggleList({
          channels,
          isSelected: id => selected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}/channels`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            selected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}/channels/${ch.id}`, {
              method: 'DELETE',
            });
            selected.delete(ch.id);
          },
          listBelow: 'Sin canales asignados a este pack.',
        }));
      } catch (e) { renderError(channelsBox, e); }
    });
    box.append(details);
  }
  const nameInput = el('input', { type: 'text', placeholder: 'Nombre del pack…', maxlength: '80' });
  async function addPack() {
    const name = nameInput.value.trim();
    if (!name) return;
    try {
      await apiFetch(`/api/server/${GUILD_ID}/frases/packs`, { method: 'POST', body: { name } });
      toast('Pack creado', 'ok');
      nameInput.value = '';
      refreshFrasesAndPacks(frasesBox, box, channels);
    } catch (e) {
      toast(e.status === 409 ? e.message : 'No se pudo crear el pack, intenta de nuevo', e.status === 409 ? 'warn' : 'err');
    }
  }
  nameInput.onkeydown = (ev) => { if (ev.key === 'Enter') addPack(); };
  box.append(el('div', { class: 'add-row' }, nameInput,
    el('button', { class: 'btn btn-primary', onclick: addPack }, 'Crear pack')));
}

// Un pack nuevo o eliminado cambia qué opciones tiene el <select> de pack de
// CADA frase (renderFrases) -- refrescar solo la lista de packs dejaría esos
// selects desactualizados hasta que se recargue el tab entero.
async function refreshFrasesAndPacks(frasesBox, packsBox, channels) {
  try {
    const [frasesData, packsData] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/frases`),
      apiFetch(`/api/server/${GUILD_ID}/frases/packs`),
    ]);
    renderFrases(frasesBox, frasesData.frases, packsData.packs, frasesData.limit);
    renderFrasePacks(packsBox, packsData.packs, channels, frasesBox, packsData.limit);
  } catch (e) { /* se queda como estaba */ }
}

const TRIGGER_MATCH_TYPE_LABELS = {
  exact: 'Texto exacto', starts_with: 'Empieza con', regex: 'Regex',
};
/* Los de arriba son rótulos de <option>; en la vista previa van dentro de una
   oración y en minúscula quedaban como "si el mensaje texto exacto...". */
const TRIGGER_MATCH_PHRASES = {
  exact: p => `es exactamente "${p}"`,
  starts_with: p => `empieza con "${p}"`,
  regex: p => `matchea la regex "${p}"`,
};
const TRIGGER_ACTION_LABELS = {
  frase_de_pack: 'Frase de un pack', markov: 'Markov (generado)', mezcla: 'Mezcla (frase o Markov)',
};

/* Arma la oración legible de un trigger ("#general — Texto exacto "gg" →
   Frase de un pack (Victorias)"), compartida entre la lista de triggers ya
   creados y el preview en vivo del formulario de alta -- así ninguno de los
   dos textos puede quedar desincronizado del otro. `trig` puede ser un
   trigger real (con id) o el estado actual del formulario (sin id todavía). */
function describeTrigger(trig, channels, packs) {
  const chan = channels.find(c => c.id === trig.channel_id);
  const pack = trig.pack_id != null && trig.pack_id !== ''
    ? packs.find(p => String(p.id) === String(trig.pack_id)) : null;
  return {
    channelLabel: '#' + (chan ? chan.name : trig.channel_id),
    matchLabel: TRIGGER_MATCH_TYPE_LABELS[trig.match_type] || trig.match_type,
    pattern: trig.pattern,
    actionLabel: TRIGGER_ACTION_LABELS[trig.action] || trig.action,
    packName: pack ? pack.name : null,
  };
}

function renderTriggers(box, data, channels, packs) {
  box.innerHTML = '';
  const list = el('ul', { class: 'item-list' });
  const cupo = cupoLine(data.triggers.length, data.limit, 'trigger usado', 'triggers usados',
    'elimina uno para agregar otro.');
  if (cupo) box.append(cupo);
  if (!data.triggers.length) list.append(el('li', { class: 'dim' }, 'Todavía no configuraste ningún trigger.'));
  for (const trig of data.triggers) {
    const d = describeTrigger(trig, channels, packs);
    list.append(el('li', { class: 'trigger-card' },
      el('div', { class: 'trigger-card-main' },
        el('span', { class: 'badge trigger-chan-badge' }, d.channelLabel),
        el('span', {}, d.matchLabel, ' ', el('code', { class: 'cmd' }, `"${d.pattern}"`)),
        el('span', { class: 'trigger-arrow' }, '→'),
        el('span', { class: 'trigger-action' }, d.actionLabel, d.packName ? ` (${d.packName})` : '')),
      confirmDelBtn('¿Eliminar este trigger? Hay que volver a escribirlo desde cero.', async () => {
        try {
          await apiFetch(`/api/server/${GUILD_ID}/settings/triggers/${trig.id}`, { method: 'DELETE' });
          toast('Trigger eliminado', 'ok');
        } catch (e) { toast('No se pudo eliminar el trigger, intenta de nuevo', 'err'); }
        reloadTriggers(box, channels, packs);
      })));
  }
  box.append(list, triggerForm(box, channels, packs, data));
}

function triggerForm(box, channels, packs, data) {
  const chanSel = channelSelect(channels);
  const matchSel = el('select', {});
  for (const mt of data.match_types) matchSel.append(el('option', { value: mt }, TRIGGER_MATCH_TYPE_LABELS[mt] || mt));
  const patternInput = el('input', { type: 'text', placeholder: 'gg, !ban, ^hola.*' });
  const actionSel = el('select', {});
  for (const ac of data.actions) actionSel.append(el('option', { value: ac }, TRIGGER_ACTION_LABELS[ac] || ac));
  const packSel = el('select', {});
  packSel.append(el('option', { value: '' }, 'Sin pack (default)'));
  for (const p of packs) packSel.append(el('option', { value: String(p.id) }, p.name));

  const packField = el('div', { class: 'field' }, el('label', {}, 'Pack'), packSel);
  const previewLine = el('p', { class: 'dim trigger-preview' });

  function syncPackVisibility() { packField.style.display = actionSel.value === 'markov' ? 'none' : ''; }

  function updatePreview() {
    const pattern = patternInput.value.trim();
    if (!chanSel.value || !pattern) {
      previewLine.textContent = 'Elige un canal y escribe un patrón para ver la vista previa.';
      return;
    }
    const d = describeTrigger({
      channel_id: chanSel.value, match_type: matchSel.value, pattern,
      action: actionSel.value, pack_id: actionSel.value !== 'markov' ? packSel.value : null,
    }, channels, packs);
    const phrase = (TRIGGER_MATCH_PHRASES[matchSel.value] || (p => `matchea "${p}"`))(d.pattern);
    previewLine.textContent =
      `Vista previa: en ${d.channelLabel}, si el mensaje ${phrase}, responde con `
      + `${d.actionLabel.toLowerCase()}${d.packName ? ` (${d.packName})` : ''}.`;
  }

  chanSel.onchange = updatePreview;
  matchSel.onchange = updatePreview;
  patternInput.oninput = updatePreview;
  actionSel.onchange = () => { syncPackVisibility(); updatePreview(); };
  packSel.onchange = updatePreview;
  syncPackVisibility();
  updatePreview();

  const addBtn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      const pattern = patternInput.value.trim();
      if (!chanSel.value || !pattern) {
        toast('Elige un canal y completa el patrón', 'warn');
        return;
      }
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/triggers`, {
          method: 'POST',
          body: {
            channel_id: chanSel.value, match_type: matchSel.value, pattern,
            action: actionSel.value,
            pack_id: actionSel.value !== 'markov' && packSel.value ? packSel.value : null,
          },
        });
        toast('Trigger agregado', 'ok');
        patternInput.value = '';
        reloadTriggers(box, channels, packs);
      } catch (e) {
        toast(e.status === 409 ? e.message : 'No se pudo agregar el trigger, intenta de nuevo', e.status === 409 ? 'warn' : 'err');
      }
    },
  }, 'Agregar');

  return el('div', {},
    el('div', { class: 'add-row trigger-form' },
      el('div', { class: 'field' }, el('label', {}, 'Canal'), chanSel),
      el('div', { class: 'field' }, el('label', {}, 'Tipo de match'), matchSel),
      el('div', { class: 'field', style: 'flex:1;min-width:180px' }, el('label', {}, 'Patrón'), patternInput),
      el('div', { class: 'field' }, el('label', {}, 'Acción'), actionSel),
      packs.length ? packField : null,
      addBtn),
    previewLine);
}

async function reloadTriggers(box, channels, packs) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/triggers`);
    renderTriggers(box, data, channels, packs);
  } catch (e) { /* se queda como estaba */ }
}

const PLAYGROUND_NO_RESPONSE_LABELS = {
  canal_ignorado: 'El canal está silenciado (ignorado) — Purgito no respondería ahí.',
  sin_corpus_suficiente: 'Todavía no hay corpus suficiente para generar una respuesta.',
  trigger_sin_contenido: 'Matcheó un trigger, pero el pool de frases de ese trigger está vacío.',
};
const PLAYGROUND_REASON_LABELS = {
  trigger: 'Disparado por un trigger',
  frase_especial: 'Frase especial',
  markov: 'Texto generado (Markov)',
};

/* Frenos que actúan ANTES del motor de generación. Cada texto dice a qué vía
   de entrega aplica (mención o hablar solo): el playground no pregunta por
   cuál llegaría el mensaje, así que un "no respondería" a secas mentiría en
   la mitad de los casos. Es la respuesta a "¿por qué no me contesta?" que
   antes el Playground no daba. */
const PLAYGROUND_AVISO_LABELS = {
  chat_desactivado:
    'El chat está desactivado: no responde a menciones. Los mensajes '
    + 'espontáneos, las reacciones y los triggers no dependen de este switch y '
    + 'siguen saliendo.',
  canal_sin_menciones:
    'Este canal no está en la lista de canales donde responde a menciones: '
    + 'si lo mencionan acá, avisa que solo contesta en los canales elegidos.',
  canal_sin_espontaneo:
    'Este canal no está en la lista de canales donde habla por su cuenta: '
    + 'acá nunca va a arrancar una charla solo.',
  cupo_horario_agotado:
    'Ya agotaste tu cupo de menciones de esta hora: a vos no te contestaría '
    + 'ahora mismo (a otro miembro sí, cada uno tiene el suyo).',
  cooldown_espontaneo:
    'Acabó de hablar solo en este canal: por el piso de silencio entre '
    + 'mensajes espontáneos no volvería a hacerlo todavía. No afecta a las '
    + 'menciones.',
};

function playgroundAvisos(avisos) {
  if (!avisos || !avisos.length) return null;
  return el('div', { class: 'playground-avisos' },
    el('p', { class: 'dim' }, avisos.length === 1
      ? 'Hay un freno activo fuera del motor de generación:'
      : `Hay ${avisos.length} frenos activos fuera del motor de generación:`),
    el('ul', { class: 'item-list' }, avisos.map(code =>
      el('li', {}, el('span', {}, PLAYGROUND_AVISO_LABELS[code] || code)))));
}

function renderPlaygroundResult(box, data) {
  box.innerHTML = '';
  const avisos = playgroundAvisos(data.avisos);
  if (!data.would_respond) {
    box.append(el('p', { class: 'dim' },
      PLAYGROUND_NO_RESPONSE_LABELS[data.reason] || 'No respondería.'));
    if (avisos) box.append(avisos);
    return;
  }
  box.append(
    el('p', { class: 'dim' }, PLAYGROUND_REASON_LABELS[data.reason] || data.reason),
    el('div', {
      style: 'border:1px solid var(--border);border-radius:var(--radius-sm);'
        + 'padding:12px;background:var(--surface-card)',
    }, data.text));
  if (avisos) box.append(avisos);
}

// ---------------- MEMES (stub) ----------------

function loadMemes() {
  const box = content();
  box.append(emptyState('En proceso'));
}
