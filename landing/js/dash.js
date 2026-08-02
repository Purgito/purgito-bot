// Dashboard por servidor (/es/dashboard/:id): header con datos del guild, tabs
// INICIO/CHAT/GIFS/MEMES/EMBEDS/PREMIUM y el contenido de INICIO y CHAT, que
// guardan solo al click (sin botón de guardar) y confirman con un toast. GIFS,
// EMBEDS y PREMIUM reutilizan los loaders del panel sin tocarles la lógica.
//
// El navbar y el footer NO se arman acá: vienen en el HTML de la página, que
// build_docs.py recorta de index.html. script.js es quien resuelve la sesión
// en el navbar; este módulo solo pinta lo que va debajo.

import { apiFetch } from '/js/core/api.js';
import {
  el, icon, spinner, emptyState, renderError, guildIcon, toast, formGroup,
} from '/js/core/dom.js';
import { GUILD_ID, currentLocale } from '/js/core/config.js';
import { getChannels, channelSelect, content } from '/js/panel-shell.js';
import { loadGifs } from '/js/tabs/gifs.js';
import { loadPremium } from '/js/tabs/premium.js';
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
];

function currentTab() {
  const key = location.pathname.split('/')[4] || 'inicio';
  return TABS.some(t => t.key === key) ? key : 'inicio';
}

function activate(key, push) {
  document.querySelectorAll('.dash-tab').forEach(n =>
    n.classList.toggle('active', n.dataset.key === key));
  if (push) {
    history.pushState({}, '', `/${currentLocale()}/dashboard/${GUILD_ID}/${key}`);
  }
  TABS.find(t => t.key === key).load();
}

async function loadHead() {
  const head = document.getElementById('dashHead');
  const back = el('a', { class: 'dash-back', href: `/${currentLocale()}/perfil` },
    el('span', { class: 'dash-back-arrow', 'aria-hidden': 'true' }, '←'), 'Volver atrás');
  try {
    const data = await apiFetch('/api/me/guilds');
    const g = data.configured.find(x => x.id === GUILD_ID);
    if (!g) {
      // Guild que el usuario no administra, o donde el bot no está: la API ya
      // lo rechazaría tab por tab, mejor decirlo una vez y ofrecer la salida.
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
        el('div', {},
          el('h1', {}, g.name,
            g.is_premium ? el('span', { class: 'badge badge-premium' }, 'PREMIUM') : null),
          el('div', { class: 'dash-guild-members dim' },
            icon('members'),
            g.member_count != null ? `${g.member_count} miembros` : 'Servidor'))));
  } catch (e) {
    head.innerHTML = '';
    head.append(back);
  }
}

export function initDash() {
  loadHead();
  const nav = document.getElementById('dashTabs');
  for (const t of TABS) {
    nav.append(el('a', {
      class: 'dash-tab',
      'data-key': t.key,
      href: `/${currentLocale()}/dashboard/${GUILD_ID}/${t.key}`,
      onclick: (ev) => { ev.preventDefault(); activate(t.key, true); },
    }, t.label));
  }
  // Link compartido (/es/perfil?share=… → Dashboard): precarga el borrador en
  // el editor y abre EMBEDS, sin importar en qué tab estuviera la URL.
  const shareId = new URLSearchParams(location.search).get('share');
  if (shareId) loadSharedEmbed(shareId).finally(() => activate('embeds', true));
  else activate(currentTab(), false);
  window.onpopstate = () => activate(currentTab(), false);
}

if (GUILD_ID) initDash();
else document.getElementById('dashHead').append(
  emptyState('Falta el id del servidor en la dirección.'));

// ---------------- INICIO ----------------

function statTile(iconName, value, label) {
  return el('div', { class: 'stat-tile' },
    icon(iconName),
    el('div', {},
      el('div', { class: 'stat-value' }, value != null ? String(value) : '—'),
      el('div', { class: 'stat-label dim' }, label)));
}

async function loadInicio() {
  const box = content();
  box.append(spinner());
  try {
    const [style, updates, stats, channels] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/style`),
      apiFetch(`/api/server/${GUILD_ID}/settings/updates`),
      apiFetch(`/api/server/${GUILD_ID}/stats`),
      getChannels(),
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

    // Canal de actualizaciones del bot
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
      el('p', { class: 'dim' }, 'Canal donde Purgito publica sus anuncios de actualizaciones y novedades.'),
      el('div', { class: 'field' }, sel)));

    // Estados: lo que el bot tiene guardado y de dónde lee ahora mismo.
    const tiles = el('div', { class: 'stat-grid' },
      statTile('corpus', stats.corpus_total, 'Mensajes guardados'),
      statTile('film', stats.gifs, 'GIFs guardados'),
      statTile('chat', `${stats.reading_channels}/${stats.text_channels}`, 'Canales que lee'),
      statTile('layout', `${stats.reply_channels}/${stats.text_channels}`, 'Canales donde responde'),
      statTile('smile', stats.reactions, 'Emojis de reacción'),
      statTile('sparkle', stats.frases, 'Frases especiales'));
    const byChannel = el('div', { class: 'stat-channels' },
      stats.corpus_by_channel.map(c => el('div', { class: 'stat-channel-row' },
        el('span', {}, '#' + (c.name || c.channel_id)),
        el('span', { class: 'dim' }, `${c.count} mensajes`))));
    box.append(formGroup('Estado del bot en este servidor', tiles,
      stats.corpus_by_channel.length
        ? el('div', {}, el('p', { class: 'dim' }, 'Mensajes guardados por canal:'), byChannel)
        : null));

    // Logs: acumulado histórico de lo que el bot mandó (guild_counters).
    const counters = stats.counters || {};
    box.append(formGroup('Actividad',
      el('p', { class: 'dim' }, 'Lo que Purgito lleva enviado en este servidor desde que entró.'),
      el('div', { class: 'stat-grid' },
        statTile('film', counters.gifs_enviados || 0, 'GIFs enviados'),
        statTile('chat', counters.mensajes_enviados || 0, 'Mensajes enviados'))));
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
  const list = el('ul', { class: 'item-list chan-list' });

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
      list.append(el('li', { class: 'dim' }, listBelow));
    }
    for (const ch of sel) {
      list.append(el('li', {},
        chanLabel(ch),
        el('button', { class: 'btn btn-danger btn-sm', onclick: () => toggle(ch) }, 'Quitar')));
    }
  }
  render();
  wrap.append(dd, list);
  return wrap;
}

async function loadChatTab() {
  const box = content();
  box.append(spinner());
  try {
    const [chat, chatChans, ignored, reactions, frases, channels] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/chat`),
      apiFetch(`/api/server/${GUILD_ID}/settings/chat-channels`),
      apiFetch(`/api/server/${GUILD_ID}/settings/corpus`),
      apiFetch(`/api/server/${GUILD_ID}/settings/reacciones`),
      apiFetch(`/api/server/${GUILD_ID}/settings/frases`),
      getChannels(),
    ]);
    box.innerHTML = '';

    // --- Chat ---
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
    const chatSelected = new Set(chatChans.channels.map(c => c.id));
    box.append(formGroup('Chat',
      el('div', { class: 'field' },
        el('label', { class: 'toggle' }, check, 'Chat activado'),
        el('p', { class: 'dim' }, 'Si está activado, Purgito responde cuando lo mencionan (@Purgito).')),
      el('div', { class: 'field' },
        el('label', {}, 'Canales donde responde (participa sin que lo mencionen)'),
        channelToggleList({
          channels,
          isSelected: id => chatSelected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/chat-channels`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            chatSelected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/chat-channels/${ch.id}`, {
              method: 'DELETE',
            });
            chatSelected.delete(ch.id);
          },
          listBelow: 'Sin canales configurados — Purgito puede participar en cualquier canal.',
        }))));

    // --- Corpus --- (el backend guarda los ignorados; acá se muestra el inverso)
    const ignoredSet = new Set(ignored.channels.map(c => c.id));
    box.append(formGroup('Corpus',
      el('div', { class: 'field' },
        el('label', {}, 'Canales donde el bot aprende mensajes'),
        channelToggleList({
          channels,
          isSelected: id => !ignoredSet.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/corpus/${ch.id}`, {
              method: 'DELETE',
            });
            ignoredSet.delete(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/corpus`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            ignoredSet.add(ch.id);
          },
          listBelow: 'El bot no está aprendiendo de ningún canal.',
        }))));

    // --- Reacciones ---
    const reaccionesBox = el('div', {});
    renderReacciones(reaccionesBox, reactions.reactions);
    box.append(formGroup('Reacciones',
      el('p', { class: 'dim' }, 'Colección de emojis con los que el bot reacciona a los usuarios.'),
      reaccionesBox));

    // --- Frases ---
    const frasesBox = el('div', {});
    renderFrases(frasesBox, frases.frases);
    box.append(formGroup('Frases',
      el('p', { class: 'dim' }, 'Frases especiales que el bot puede enviar de vez en cuando.'),
      frasesBox));
  } catch (e) { renderError(box, e); }
}

async function renderReacciones(box, pool) {
  box.innerHTML = '';
  const inPool = new Set(pool.map(r => r.emoji_text));
  const list = el('ul', { class: 'item-list' });
  if (!pool.length) list.append(el('li', { class: 'dim' }, 'Todavía no hay emojis en la colección.'));
  for (const r of pool) {
    list.append(el('li', {},
      el('span', {}, r.emoji_text),
      el('button', {
        class: 'btn btn-danger btn-sm',
        onclick: () => removeReaction(box, r.id),
      }, 'Quitar')));
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

  const input = el('input', { type: 'text', placeholder: 'Emoji (😀)', maxlength: '64' });
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

  box.append(list, addRow, grid.children.length ? grid : null);
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

function renderFrases(box, frases) {
  box.innerHTML = '';
  const list = el('ul', { class: 'item-list' });
  if (!frases.length) list.append(el('li', { class: 'dim' }, 'Todavía no has agregado ninguna frase.'));
  for (const f of frases) {
    list.append(el('li', {},
      el('span', {}, f.frase),
      el('button', {
        class: 'btn btn-danger btn-sm',
        onclick: async () => {
          try {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, { method: 'DELETE' });
            toast('Frase quitada', 'ok');
          } catch (e) { toast('No se pudo quitar la frase, intenta de nuevo', 'err'); }
          reloadFrases(box);
        },
      }, 'Quitar')));
  }
  const input = el('input', { type: 'text', placeholder: 'Nueva frase…', maxlength: '300' });
  async function addFrase() {
    const frase = input.value.trim();
    if (!frase) return;
    try {
      await apiFetch(`/api/server/${GUILD_ID}/settings/frases`, {
        method: 'POST', body: { frase },
      });
      toast('Frase agregada', 'ok');
      reloadFrases(box);
    } catch (e) { toast('No se pudo agregar la frase, intenta de nuevo', 'err'); }
  }
  input.onkeydown = (ev) => { if (ev.key === 'Enter') addFrase(); };
  box.append(list, el('div', { class: 'add-row' }, input,
    el('button', { class: 'btn btn-primary', onclick: addFrase }, 'Agregar')));
}

async function reloadFrases(box) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/frases`);
    renderFrases(box, data.frases);
  } catch (e) { /* se queda como estaba */ }
}

// ---------------- MEMES (stub) ----------------

function loadMemes() {
  const box = content();
  box.append(emptyState('En proceso'));
}
