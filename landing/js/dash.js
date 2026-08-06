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

// Listener de hashchange de las sub-pestañas del tab CHAT (declarado acá, no
// junto a loadChatTab): activate() corre de forma síncrona en la carga
// inicial de la página, antes de que la evaluación del módulo llegue a
// cualquier código que esté más abajo — un `let` declarado después de ese
// punto todavía estaría en du temporal dead zone cuando activate() lo lea.
let _chatHashHandler = null;

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
  // Salir del tab CHAT no debe dejar un listener global reaccionando a
  // cambios de hash sobre un DOM que ya no existe (content() lo reemplazó).
  if (key !== 'chat' && _chatHashHandler) {
    window.removeEventListener('hashchange', _chatHashHandler);
    _chatHashHandler = null;
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

/* Import de corpus desde un .txt (Fase 8): sube el archivo tal cual en el
   body del request (mismo patrón que uploadImageBlob en embeds/shared-ui.js
   para las imágenes), no un multipart -- el channel_id va en la URL. */
function corpusImportForm(channels) {
  const chanSel = channelSelect(channels, null, 'Elegí un canal…');
  const fileInput = el('input', { type: 'file', accept: '.txt,text/plain' });
  const resultBox = el('div', {});
  const btn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      const file = fileInput.files[0];
      if (!chanSel.value || !file) {
        toast('Elegí un canal y un archivo .txt', 'warn');
        return;
      }
      resultBox.innerHTML = '';
      resultBox.append(spinner());
      let r, data;
      try {
        r = await fetch(`/api/server/${GUILD_ID}/settings/corpus/import/${chanSel.value}`, {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'text/plain' },
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
   tiene sentido pegarle a la API en cada tecla). */
function numberField(label, help, { key, value, min, max, step, suffix, save = saveTunable }) {
  const input = el('input', {
    type: 'number', value: String(value), min: String(min),
    max: String(max), step: String(step || 1), class: 'num-input',
  });
  input.onchange = () => {
    save(key, Number(input.value), label, (saved) => {
      input.value = String(saved);
    });
  };
  return el('div', { class: 'field' },
    el('label', {}, label),
    el('div', { class: 'num-row' }, input, suffix ? el('span', { class: 'dim' }, suffix) : null),
    help ? el('p', { class: 'dim' }, help) : null);
}

/* Probabilidad 0–1 editada como porcentaje entero: el slider y el número van
   sincronizados y solo el `change` (soltar el slider) guarda. */
function percentField(label, help, { key, value, save = saveTunable }) {
  const pct = Math.round(value * 100);
  const range = el('input', { type: 'range', min: '0', max: '100', step: '1', value: String(pct) });
  const out = el('span', { class: 'pct-value' }, `${pct}%`);
  range.oninput = () => { out.textContent = `${range.value}%`; };
  range.onchange = () => {
    save(key, Number(range.value) / 100, label, (saved) => {
      const back = Math.round(saved * 100);
      range.value = String(back);
      out.textContent = `${back}%`;
    });
  };
  return el('div', { class: 'field' },
    el('label', {}, label),
    el('div', { class: 'pct-row' }, range, out),
    help ? el('p', { class: 'dim' }, help) : null);
}

/* Override por canal de los tunables de chat (Fase 2) — reusa numberField y
   percentField tal cual (les agrega `save` para el endpoint de canal en vez
   del de servidor), así que la fila real de edición es exactamente la misma
   que ya conoce el admin en Personalidad/Límites. */

function channelOverrideBadge(active) {
  return el('span', { class: 'badge' + (active ? '' : ' badge-dim') },
    active ? 'Override activo acá' : 'Usando default del servidor');
}

function makeChannelTunableSaver(channelId) {
  return async (key, value, label, onSaved) => {
    try {
      const r = await apiFetch(`/api/guilds/${GUILD_ID}/channels/${channelId}/settings`, {
        method: 'PUT', body: { [key]: value },
      });
      if (onSaved && r.saved && key in r.saved) onSaved(r.saved[key]);
      toast(`${label} actualizado para este canal`, 'ok');
    } catch (e) {
      toast(`No se pudo guardar ${label.toLowerCase()}, intenta de nuevo`, 'err');
    }
  };
}

/* Una fila = un tunable + su estado de override en un canal puntual. El
   toggle prende/apaga el override de verdad (PUT inmediato al marcarlo o
   desmarcarlo, no solo al tocar el valor) para que el badge nunca mienta:
   "activo" siempre corresponde a una fila real en channel_settings, nunca a
   una casilla marcada sin guardar todavía. */
function channelTunableRow(channelId, buildField, label, help, tunable) {
  const { key, effective, format } = tunable;
  let override = tunable.override;
  let isOverride = override !== null && override !== undefined;

  const badge = channelOverrideBadge(isOverride);
  const checkbox = el('input', { type: 'checkbox', checked: isOverride });
  const slot = el('div', {});

  function renderSlot() {
    slot.innerHTML = '';
    if (isOverride) {
      slot.append(buildField(label, help, {
        ...tunable, value: override, save: makeChannelTunableSaver(channelId),
      }));
    } else {
      slot.append(el('p', { class: 'dim' },
        `Valor efectivo acá: ${format(effective)} (default del servidor).`));
    }
  }

  checkbox.onchange = async () => {
    const turningOn = checkbox.checked;
    try {
      if (turningOn) {
        // Arranca en el valor efectivo actual: activar el override no cambia
        // la conducta del canal hasta que se edite el campo.
        const r = await apiFetch(`/api/guilds/${GUILD_ID}/channels/${channelId}/settings`, {
          method: 'PUT', body: { [key]: override !== null && override !== undefined ? override : effective },
        });
        override = r.saved[key];
        toast(`${label}: override activado para este canal`, 'ok');
      } else {
        await apiFetch(`/api/guilds/${GUILD_ID}/channels/${channelId}/settings`, {
          method: 'PUT', body: { [key]: null },
        });
        override = null;
        toast(`${label}: vuelve a usar el default del servidor`, 'ok');
      }
    } catch (e) {
      checkbox.checked = !turningOn;
      toast('No se pudo actualizar el override, intenta de nuevo', 'err');
      return;
    }
    isOverride = turningOn;
    badge.className = 'badge' + (isOverride ? '' : ' badge-dim');
    badge.textContent = isOverride ? 'Override activo acá' : 'Usando default del servidor';
    renderSlot();
  };

  renderSlot();
  return el('div', { class: 'field channel-tunable' },
    el('div', { style: 'display:flex;align-items:center;gap:8px;justify-content:space-between' },
      el('label', {}, label), badge),
    el('label', { class: 'toggle' }, checkbox, ' Override en este canal'),
    slot);
}

/* Multi-select de roles con toggle, gemelo de channelToggleList. Los roles no
   tienen el problema de permisos de los canales, así que es más simple. */
function roleToggleList({ roles, selected, add, remove, listBelow }) {
  const panel = el('div', { class: 'dd-panel chan-panel' });
  const btn = el('button', { class: 'dd-trigger' },
    'Seleccionar roles…', el('span', { class: 'dd-caret' }, '▾'));
  const dd = el('div', { class: 'dd' }, btn, panel);
  btn.onclick = (e) => { e.stopPropagation(); dd.classList.toggle('open'); };
  const list = el('ul', { class: 'item-list chan-list' });

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
    if (!sel.length) list.append(el('li', { class: 'dim' }, listBelow));
    for (const role of sel) {
      list.append(el('li', {},
        roleLabel(role),
        el('button', { class: 'btn btn-danger btn-sm', onclick: () => toggle(role) }, 'Quitar')));
    }
  }
  render();
  return el('div', { class: 'chan-picker' }, dd, list);
}

// Sub-pestañas del tab CHAT (no confundir con TABS, que son las principales
// del dashboard). Viven en el hash de la URL —#canales, #personalidad…— en
// vez de un segmento de path, porque el path ya está tomado por el tab
// principal ('chat') y por el GUILD_ID.
const CHAT_SUBTABS = [
  { key: 'canales', label: 'Canales' },
  { key: 'personalidad', label: 'Personalidad' },
  { key: 'limites', label: 'Límites' },
  { key: 'porcanal', label: 'Por canal' },
  { key: 'frases', label: 'Frases' },
  { key: 'triggers', label: 'Triggers' },
  { key: 'playground', label: 'Playground' },
];

function currentChatSubtab() {
  const key = location.hash.slice(1);
  return CHAT_SUBTABS.some(t => t.key === key) ? key : 'canales';
}

// El listener de hashchange (soporta el botón atrás/adelante y links directos
// a #frases, etc.) vive en `_chatHashHandler`, declarado arriba junto a
// activate() — ver el comentario ahí sobre por qué no puede declararse acá.

// Card con ícono propio para distinguir "dónde responde" de "de dónde
// aprende" — antes eran dos formGroup visualmente idénticos separados por un
// simple divisor, la confusión que motivó separarlos en su propia sub-pestaña.
function channelCard(iconName, title, ...children) {
  return el('div', { class: 'channel-card' },
    el('div', { class: 'channel-card-head' }, icon(iconName), el('h3', {}, title)),
    ...children);
}

async function loadChatTab() {
  const box = content();
  box.append(spinner());
  try {
    const [chat, spontaneousChans, mentionChans, corpus, reactions, frases, fraseChannels, frasePacks, triggers, exempt, channels, roles] =
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
        getChannels(),
        getRoles(),
      ]);
    box.innerHTML = '';
    const lim = chat.limits || {};

    // --- Switch maestro: fuera de las sub-pestañas, igual que hoy ---
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
    box.append(formGroup('Chat',
      el('div', { class: 'field' },
        el('label', { class: 'toggle' }, check, 'Chat activado'),
        el('p', { class: 'dim' }, 'Si está activado, Purgito responde cuando lo mencionan (@Purgito).'))));

    // --- Sub-pestaña: Canales ---
    function buildCanales() {
      const spontaneousSelected = new Set(spontaneousChans.channels.map(c => c.id));
      const mentionSelected = new Set(mentionChans.channels.map(c => c.id));
      const corpusSelected = new Set(corpus.channels.map(c => c.id));
      const ignoredSet = new Set(corpus.ignored || []);
      return el('div', {},
        channelCard('sparkle', 'Canales donde habla espontáneamente',
          el('p', { class: 'dim' },
            'Elige en qué canales puede hablar Purgito por su cuenta. Si no '
            + 'eliges ninguno, puede hacerlo en todos.'),
          channelToggleList({
            channels,
            isSelected: id => spontaneousSelected.has(id),
            add: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels`, {
                method: 'POST', body: { channel_id: ch.id },
              });
              spontaneousSelected.add(ch.id);
            },
            remove: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels/${ch.id}`, {
                method: 'DELETE',
              });
              spontaneousSelected.delete(ch.id);
            },
            listBelow: 'Sin canales elegidos — Purgito puede hablar en cualquiera.',
          })),
        channelCard('chat', 'Canales donde responde a menciones',
          el('p', { class: 'dim' },
            'Elige en qué canales responde Purgito cuando lo mencionan. Si no '
            + 'eliges ninguno, responde en todos.'),
          channelToggleList({
            channels,
            isSelected: id => mentionSelected.has(id),
            add: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels`, {
                method: 'POST', body: { channel_id: ch.id },
              });
              mentionSelected.add(ch.id);
            },
            remove: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels/${ch.id}`, {
                method: 'DELETE',
              });
              mentionSelected.delete(ch.id);
            },
            listBelow: 'Sin canales elegidos — Purgito responde en cualquiera.',
          })),
        channelCard('corpus', 'Canales de los que aprende',
          el('p', { class: 'dim' },
            'Purgito solo guarda mensajes de los canales que elijas acá. Si '
            + 'no eliges ninguno, no aprende de nada.'),
          ignoredSet.size
            ? el('p', { class: 'dim' },
              `${ignoredSet.size} canal(es) ignorado(s) desde /settings quedan fuera `
              + 'aunque los elijas: ahí Purgito está completamente mudo.')
            : null,
          channelToggleList({
            channels,
            isSelected: id => corpusSelected.has(id),
            add: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/corpus`, {
                method: 'POST', body: { channel_id: ch.id },
              });
              corpusSelected.add(ch.id);
            },
            remove: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/corpus/${ch.id}`, {
                method: 'DELETE',
              });
              corpusSelected.delete(ch.id);
            },
            listBelow: 'Purgito no está aprendiendo de ningún canal.',
          })),
        formGroup('Importar corpus desde un archivo',
          el('p', { class: 'dim' },
            'Subí un .txt: cada línea no vacía entra al corpus del canal '
            + 'elegido como si fuera un mensaje real, con la misma limpieza y '
            + 'los mismos límites de siempre.'),
          corpusImportForm(channels)),
        formGroup('Amnesia',
          el('p', { class: 'dim' },
            'Borra el corpus (mensajes y estilo por usuario) de las últimas '
            + '24 horas de todo el servidor. Es irreversible.'),
          amnesiaButton()));
    }

    // --- Sub-pestaña: Personalidad ---
    function buildPersonalidad() {
      const reaccionesBox = el('div', {});
      renderReacciones(reaccionesBox, reactions.reactions);
      return el('div', {},
        formGroup('Frecuencia de mensajes espontáneos',
          el('p', { class: 'dim' },
            'Cada tantos mensajes nuevos que aprende en un canal, Purgito puede '
            + 'decidir hablar solo. La probabilidad evita que sea siempre exacto.'),
          numberField('Cada cuántos mensajes', null, {
            key: 'auto_generate_every',
            value: chat.auto_generate_every,
            min: (lim.auto_generate_every || [1])[0],
            max: (lim.auto_generate_every || [null, 1000])[1],
            suffix: 'mensajes',
          }),
          percentField('Probabilidad de hablar', 'Al llegar a ese número, cuántas veces de cada 100 habla.', {
            key: 'auto_generate_probability',
            value: chat.auto_generate_probability,
          })),
        formGroup('Reacciones',
          el('p', { class: 'dim' }, 'Colección de emojis con los que el bot reacciona a los usuarios.'),
          percentField('Probabilidad de reaccionar', 'De cada 100 mensajes que lee, a cuántos les pone un emoji.', {
            key: 'reaction_probability',
            value: chat.reaction_probability,
          }),
          reaccionesBox),
        formGroup('GIF o texto',
          el('p', { class: 'dim' },
            'Con qué frecuencia responde con un GIF de su galería en vez de un '
            + 'mensaje generado.'),
          percentField('Probabilidad de responder con GIF', null, {
            key: 'gif_response_probability',
            value: chat.gif_response_probability,
          })),
        formGroup('Frases especiales',
          el('p', { class: 'dim' },
            'Con qué frecuencia responde con una frase especial (ver la '
            + 'sub-pestaña Frases) en vez de un mensaje generado por Markov.'),
          percentField('Probabilidad de usar una frase especial', null, {
            key: 'frase_probability',
            value: chat.frase_probability,
          })));
    }

    // --- Sub-pestaña: Límites ---
    function buildLimites() {
      const exemptSelected = new Set(exempt.roles.map(r => r.id));
      return formGroup('Límite de actividad',
        el('p', { class: 'dim' },
          'Tope de interacciones por hora y por usuario, para evitar que alguien '
          + 'genere actividad falsa con Purgito. 0 = sin límite.'),
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
          })));
    }

    // --- Sub-pestaña: Frases ---
    function buildFrases() {
      const frasesBox = el('div', {});
      renderFrases(frasesBox, frases.frases, frasePacks.packs);

      const packsBox = el('div', {});
      renderFrasePacks(packsBox, frasePacks.packs, channels, frasesBox);

      const fraseChannelsSelected = new Set(fraseChannels.channels.map(c => c.id));

      return el('div', {},
        formGroup('Frases',
          el('p', { class: 'dim' }, 'Frases especiales que el bot puede enviar de vez en cuando.'),
          el('p', { class: 'dim' },
            'Podés usar estos tags y se reemplazan al enviarse: ',
            el('code', { class: 'cmd' }, '{{user.mention}}'), ', ',
            el('code', { class: 'cmd' }, '{{user.name}}'), ', ',
            el('code', { class: 'cmd' }, '{{channel.name}}'), ', ',
            el('code', { class: 'cmd' }, '{{channel.mention}}'), ', ',
            el('code', { class: 'cmd' }, '{{guild.name}}'), ', ',
            el('code', { class: 'cmd' }, '{{markov.word}}'), ' y ',
            el('code', { class: 'cmd' }, '{{markov.sentence}}'), '.'),
          frasesBox),
        formGroup('Packs de frases',
          el('p', { class: 'dim' },
            'Agrupá frases en un pack y asignaselo a uno o más canales para que '
            + 'solo salgan esas ahí. Una frase sin pack (o un canal sin pack '
            + 'asignado) usa el pool default del servidor, de arriba.'),
          packsBox),
        channelCard('star', 'Canales donde pueden salir frases especiales',
          el('p', { class: 'dim' },
            'Elegí en qué canales puede aparecer una frase especial. Si no '
            + 'eliges ninguno, puede salir en cualquiera.'),
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

    // --- Sub-pestaña: Triggers ---
    function buildTriggers() {
      const box = el('div', {});
      renderTriggers(box, triggers, channels, frasePacks.packs);
      return formGroup('Triggers de canal',
        el('p', { class: 'dim' },
          'Reglas de auto-respuesta: si el mensaje matchea el patrón, Purgito '
          + 'responde sin esperar mención ni el roll de frecuencia espontánea. '
          + `Con varios en el mismo canal gana el primero que matchea (${triggers.total}/${triggers.limit} usados).`),
        box);
    }

    // --- Sub-pestaña: Playground ---
    function buildPlayground() {
      const sel = channelSelect(channels, null, 'Elegí un canal…');
      const input = el('textarea', {
        rows: '3', placeholder: 'Mensaje de prueba…', style: 'width:100%',
      });
      const resultBox = el('div', {});
      const btn = el('button', {
        class: 'btn btn-primary',
        onclick: async () => {
          const message = input.value.trim();
          if (!sel.value || !message) {
            toast('Elegí un canal y escribí un mensaje de prueba', 'warn');
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

      return formGroup('Playground',
        el('p', { class: 'dim' },
          'Probá cómo respondería Purgito a un mensaje en un canal puntual, con '
          + 'su configuración efectiva (overrides, packs y triggers incluidos). '
          + 'No manda nada de verdad ni gasta el cooldown real de frases '
          + 'especiales. No simula si el canal está habilitado para menciones o '
          + 'respuesta espontánea, ni el límite de menciones por hora — solo el '
          + 'motor de generación.'),
        el('div', { class: 'field' }, el('label', {}, 'Canal'), sel),
        el('div', { class: 'field' }, el('label', {}, 'Mensaje de prueba'), input),
        btn,
        resultBox);
    }

    // --- Sub-pestaña: Por canal (overrides de Personalidad/Límites) ---
    function buildPorCanal() {
      const sel = channelSelect(channels, null, 'Elegí un canal…');
      const resultBox = el('div', {});

      async function loadChannel() {
        resultBox.innerHTML = '';
        if (!sel.value) return;
        const channelId = sel.value;
        resultBox.append(spinner());
        try {
          const data = await apiFetch(`/api/guilds/${GUILD_ID}/channels/${channelId}/settings`);
          resultBox.innerHTML = '';
          const eff = data.effective, ov = data.overrides, lim2 = data.limits || {};
          resultBox.append(
            channelTunableRow(channelId, numberField, 'Cada cuántos mensajes', null, {
              key: 'auto_generate_every', effective: eff.auto_generate_every, override: ov.auto_generate_every,
              min: (lim2.auto_generate_every || [1])[0], max: (lim2.auto_generate_every || [null, 1000])[1],
              suffix: 'mensajes', format: v => `${v} mensajes`,
            }),
            channelTunableRow(channelId, percentField, 'Probabilidad de hablar', null, {
              key: 'auto_generate_probability', effective: eff.auto_generate_probability,
              override: ov.auto_generate_probability, format: v => `${Math.round(v * 100)}%`,
            }),
            channelTunableRow(channelId, percentField, 'Probabilidad de reaccionar', null, {
              key: 'reaction_probability', effective: eff.reaction_probability,
              override: ov.reaction_probability, format: v => `${Math.round(v * 100)}%`,
            }),
            channelTunableRow(channelId, percentField, 'Probabilidad de responder con GIF', null, {
              key: 'gif_response_probability', effective: eff.gif_response_probability,
              override: ov.gif_response_probability, format: v => `${Math.round(v * 100)}%`,
            }),
            channelTunableRow(channelId, numberField, 'Menciones por hora', null, {
              key: 'mention_rate_limit', effective: eff.mention_rate_limit, override: ov.mention_rate_limit,
              min: (lim2.mention_rate_limit || [0])[0], max: (lim2.mention_rate_limit || [null, 1000])[1],
              suffix: 'por usuario', format: v => `${v} por usuario`,
            }),
            channelTunableRow(channelId, percentField, 'Probabilidad de usar una frase especial', null, {
              key: 'frase_probability', effective: eff.frase_probability,
              override: ov.frase_probability, format: v => `${Math.round(v * 100)}%`,
            }));
        } catch (e) { renderError(resultBox, e); }
      }
      sel.onchange = loadChannel;

      return formGroup('Ajustes por canal',
        el('p', { class: 'dim' },
          'Cada canal usa por default los valores de Personalidad y Límites de '
          + 'arriba. Elegí uno acá para revisar u overridear alguno puntualmente.'),
        el('div', { class: 'field' }, el('label', {}, 'Canal'), sel),
        resultBox);
    }

    const BUILDERS = {
      canales: buildCanales,
      personalidad: buildPersonalidad,
      limites: buildLimites,
      porcanal: buildPorCanal,
      frases: buildFrases,
      triggers: buildTriggers,
      playground: buildPlayground,
    };

    const subnav = el('nav', { class: 'chat-subtabs' });
    const panels = {};
    for (const st of CHAT_SUBTABS) {
      panels[st.key] = BUILDERS[st.key]();
      panels[st.key].hidden = true;
      subnav.append(el('a', {
        class: 'chat-subtab',
        'data-key': st.key,
        href: `#${st.key}`,
        onclick: (ev) => { ev.preventDefault(); activateSubtab(st.key); },
      }, st.label));
    }
    const panelsWrap = el('div', {}, CHAT_SUBTABS.map(st => panels[st.key]));

    // Todo se autoguarda al toque (sin botón "Guardar" ni estado sin
    // confirmar), así que cambiar de sub-pestaña nunca pierde nada: no hay
    // que preservar más que qué pestaña estaba activa.
    function activateSubtab(key) {
      subnav.querySelectorAll('.chat-subtab').forEach(n =>
        n.classList.toggle('active', n.dataset.key === key));
      for (const st of CHAT_SUBTABS) {
        const active = st.key === key;
        panels[st.key].hidden = !active;
        // Un dropdown de canales/roles que quedó abierto en una pestaña que
        // se oculta no debe reaparecer abierto solo cuando se vuelve a ella.
        if (!active) panels[st.key].querySelectorAll('.dd.open').forEach(d => d.classList.remove('open'));
      }
      // replaceState (no pushState): cambiar de sub-pestaña no debe acumular
      // entradas en el historial — el botón atrás sigue siendo "otro tab".
      history.replaceState(null, '', `${location.pathname}${location.search}#${key}`);
    }

    box.append(subnav, panelsWrap);
    activateSubtab(currentChatSubtab());

    if (_chatHashHandler) window.removeEventListener('hashchange', _chatHashHandler);
    _chatHashHandler = () => activateSubtab(currentChatSubtab());
    window.addEventListener('hashchange', _chatHashHandler);
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

// `packs` decide si se muestra el selector de pack por frase: sin packs
// creados todavía no tiene sentido mostrar un <select> con una sola opción.
function renderFrases(box, frases, packs) {
  box.innerHTML = '';
  const list = el('ul', { class: 'item-list' });
  if (!frases.length) list.append(el('li', { class: 'dim' }, 'Todavía no has agregado ninguna frase.'));
  for (const f of frases) {
    let packSelect = null;
    if (packs.length) {
      packSelect = el('select', {});
      packSelect.append(el('option', { value: '' }, 'Sin pack (default)'));
      for (const p of packs) packSelect.append(el('option', { value: String(p.id) }, p.name));
      packSelect.value = f.pack_id != null ? String(f.pack_id) : '';
      packSelect.onchange = async () => {
        try {
          await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, {
            method: 'PATCH', body: { pack_id: packSelect.value || null },
          });
          toast('Pack de la frase actualizado', 'ok');
        } catch (e) {
          toast('No se pudo actualizar el pack, intenta de nuevo', 'err');
        }
      };
    }
    list.append(el('li', {},
      el('span', {}, f.frase),
      packSelect,
      el('button', {
        class: 'btn btn-danger btn-sm',
        onclick: async () => {
          try {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, { method: 'DELETE' });
            toast('Frase quitada', 'ok');
          } catch (e) { toast('No se pudo quitar la frase, intenta de nuevo', 'err'); }
          reloadFrases(box, packs);
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
      reloadFrases(box, packs);
    } catch (e) {
      toast(e.status === 409 ? e.message : 'No se pudo agregar la frase, intenta de nuevo', e.status === 409 ? 'warn' : 'err');
    }
  }
  input.onkeydown = (ev) => { if (ev.key === 'Enter') addFrase(); };
  box.append(list, el('div', { class: 'add-row' }, input,
    el('button', { class: 'btn btn-primary', onclick: addFrase }, 'Agregar')));
}

async function reloadFrases(box, packs) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/frases`);
    renderFrases(box, data.frases, packs);
  } catch (e) { /* se queda como estaba */ }
}

// Un <details> por pack (colapsado): adentro, sus canales asignados con el
// mismo channelToggleList de arriba. La lista de canales del pack se pide
// recién al abrirlo (no en el fetch inicial del tab) porque son N pedidos
// más, uno por pack, que la mayoría de las veces nadie va a mirar.
function renderFrasePacks(box, packs, channels, frasesBox) {
  box.innerHTML = '';
  if (!packs.length) {
    box.append(el('p', { class: 'dim' },
      'Sin packs todavía — todas las frases están en el pool default del servidor.'));
  }
  for (const pack of packs) {
    const channelsBox = el('div', {}, el('p', { class: 'dim' }, 'Abrí para ver los canales asignados…'));
    let loaded = false;
    const details = el('details', { class: 'embed-group' },
      el('summary', { class: 'embed-group-title' }, pack.name),
      el('div', { class: 'embed-group-body' },
        channelsBox,
        el('button', {
          class: 'btn btn-danger btn-sm',
          onclick: async () => {
            try {
              await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}`, { method: 'DELETE' });
              toast('Pack eliminado', 'ok');
            } catch (e) { toast('No se pudo eliminar el pack, intenta de nuevo', 'err'); }
            // Las frases que tenía el pack volvieron al pool default en la DB
            // (delete_frase_pack en db.py): refresca también sus selects.
            refreshFrasesAndPacks(frasesBox, box, channels);
          },
        }, 'Eliminar pack')));
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
    renderFrases(frasesBox, frasesData.frases, packsData.packs);
    renderFrasePacks(packsBox, packsData.packs, channels, frasesBox);
  } catch (e) { /* se queda como estaba */ }
}

const TRIGGER_MATCH_TYPE_LABELS = {
  exact: 'Texto exacto', starts_with: 'Empieza con', regex: 'Regex',
};
const TRIGGER_ACTION_LABELS = {
  frase_de_pack: 'Frase de un pack', markov: 'Markov (generado)', mezcla: 'Mezcla (frase o Markov)',
};

function renderTriggers(box, data, channels, packs) {
  box.innerHTML = '';
  const list = el('ul', { class: 'item-list' });
  if (!data.triggers.length) list.append(el('li', { class: 'dim' }, 'Todavía no configuraste ningún trigger.'));
  for (const trig of data.triggers) {
    const chan = channels.find(c => c.id === trig.channel_id);
    const pack = trig.pack_id != null ? packs.find(p => String(p.id) === String(trig.pack_id)) : null;
    const parts = [
      '#' + (chan ? chan.name : trig.channel_id),
      '—', TRIGGER_MATCH_TYPE_LABELS[trig.match_type] || trig.match_type,
      `"${trig.pattern}"`, '→', TRIGGER_ACTION_LABELS[trig.action] || trig.action,
    ];
    if (pack) parts.push(`(${pack.name})`);
    list.append(el('li', {},
      el('span', {}, parts.join(' ')),
      el('button', {
        class: 'btn btn-danger btn-sm',
        onclick: async () => {
          try {
            await apiFetch(`/api/server/${GUILD_ID}/settings/triggers/${trig.id}`, { method: 'DELETE' });
            toast('Trigger eliminado', 'ok');
          } catch (e) { toast('No se pudo eliminar el trigger, intenta de nuevo', 'err'); }
          reloadTriggers(box, channels, packs);
        },
      }, 'Quitar')));
  }
  box.append(list, triggerForm(box, channels, packs, data));
}

function triggerForm(box, channels, packs, data) {
  const chanSel = channelSelect(channels);
  const matchSel = el('select', {});
  for (const mt of data.match_types) matchSel.append(el('option', { value: mt }, TRIGGER_MATCH_TYPE_LABELS[mt] || mt));
  const patternInput = el('input', { type: 'text', placeholder: 'Patrón…', style: 'flex:1' });
  const actionSel = el('select', {});
  for (const ac of data.actions) actionSel.append(el('option', { value: ac }, TRIGGER_ACTION_LABELS[ac] || ac));
  const packSel = el('select', {});
  packSel.append(el('option', { value: '' }, 'Sin pack (default)'));
  for (const p of packs) packSel.append(el('option', { value: String(p.id) }, p.name));
  function syncPackVisibility() { packSel.style.display = actionSel.value === 'markov' ? 'none' : ''; }
  actionSel.onchange = syncPackVisibility;
  syncPackVisibility();

  const addBtn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      const pattern = patternInput.value.trim();
      if (!chanSel.value || !pattern) {
        toast('Elegí un canal y completá el patrón', 'warn');
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

  return el('div', { class: 'add-row' },
    chanSel, matchSel, patternInput, actionSel, packs.length ? packSel : null, addBtn);
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

function renderPlaygroundResult(box, data) {
  box.innerHTML = '';
  if (!data.would_respond) {
    box.append(el('p', { class: 'dim' },
      PLAYGROUND_NO_RESPONSE_LABELS[data.reason] || 'No respondería.'));
    return;
  }
  box.append(
    el('p', { class: 'dim' }, PLAYGROUND_REASON_LABELS[data.reason] || data.reason),
    el('div', {
      style: 'border:1px solid var(--border);border-radius:var(--radius-sm);'
        + 'padding:12px;background:var(--surface-card)',
    }, data.text));
}

// ---------------- MEMES (stub) ----------------

function loadMemes() {
  const box = content();
  box.append(emptyState('En proceso'));
}
