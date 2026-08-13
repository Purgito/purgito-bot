import { apiFetch } from '/js/core/api.js';
import { el, spinner, renderError, toast, formGroup } from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, roleSelect, content } from '/js/panel-shell.js';

// Mismos dos estados que cogs/youtube.py._check_one puede marcar en
// last_error (ver db.YOUTUBE_ERROR_*) y el mismo aviso que ya muestra la
// categoría YouTube de /settings para cada uno.
function errorNote(lastError) {
  if (lastError === 'sin_permiso') return '⚠️ Purgito no tiene permiso para escribir en este canal';
  if (lastError === 'canal_no_encontrado') return '⚠️ el canal configurado ya no existe';
  return null;
}

// Confirmación de borrado en dos pasos, mismo patrón que gifDeleteActions de tabs/gifs.js.
function subDeleteActions(sub, reload) {
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
      const resp = await apiFetch(`/api/server/${GUILD_ID}/youtube/${sub.id}`, { method: 'DELETE' });
      if (!resp.removed) {
        toast('No se encontró esa suscripción', 'warn');
        showButton();
        return;
      }
      toast('Suscripción quitada', 'ok');
      reload();
    } catch (e) {
      toast(e.status === 429 ? 'Rate limit — espera antes de quitar más' : e.message, e.status === 429 ? 'warn' : 'err');
      showButton();
    }
  }

  showButton();
  return wrap;
}

function subRow(sub, roles, reload) {
  const note = errorNote(sub.last_error);
  const sel = roleSelect(roles, sub.mention_role_id, 'Sin mención a rol');
  sel.title = 'Rol a mencionar al avisar nuevos videos';
  sel.onchange = async () => {
    try {
      await apiFetch(`/api/server/${GUILD_ID}/youtube/${sub.id}`, {
        method: 'PATCH', body: { mention_role_id: sel.value || null },
      });
      toast(sel.value ? 'Rol de mención guardado' : 'Mención quitada', 'ok');
    } catch (e) { toast('No se pudo guardar el rol, intenta de nuevo', 'err'); }
  };

  const info = el('div', { style: 'flex:1' },
    el('div', {},
      el('strong', {}, sub.youtube_channel_name),
      ' → #' + (sub.discord_channel_name || sub.discord_channel_id)),
    note ? el('div', { class: 'chan-noperm' }, note) : null);

  return el('li', {}, info, sel, subDeleteActions(sub, reload));
}

export async function loadYoutube() {
  const box = content();
  box.append(spinner());
  try {
    const [data, channels, roles] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/youtube`),
      getChannels(),
      getRoles(),
    ]);
    box.innerHTML = '';

    const idInput = el('input', {
      type: 'text', placeholder: 'ID del canal de YouTube (empieza con UC…)', style: 'flex:1',
    });
    const chanSel = channelSelect(channels);
    const addBtn = el('button', {
      class: 'btn btn-primary',
      onclick: async () => {
        const channel_id = idInput.value.trim();
        if (!channel_id || !chanSel.value) {
          toast('Completa el ID del canal y elige un canal de Discord', 'warn');
          return;
        }
        addBtn.disabled = true;
        try {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/youtube`, {
            method: 'POST', body: { channel_id, discord_channel_id: chanSel.value },
          });
          if (resp.added) {
            toast('Suscripción agregada', 'ok');
            idInput.value = '';
            loadYoutube();
          } else {
            toast('Ese canal ya estaba suscripto', 'warn');
          }
        } catch (e) {
          toast(e.status === 429 ? 'Rate limit — espera antes de agregar más' : e.message, e.status === 429 ? 'warn' : 'err');
        } finally {
          addBtn.disabled = false;
        }
      },
    }, 'Agregar');

    box.append(formGroup('Agregar suscripción',
      el('p', { class: 'dim' },
        'Solo acepta el ID del canal de YouTube (el que empieza con UC…), no la URL completa ni @handle.'),
      el('div', { class: 'add-row' }, idInput, chanSel, addBtn)));

    if (!data.subscriptions.length) {
      box.append(formGroup('Suscripciones activas',
        emptyState('Todavía no hay suscripciones activas. Agrega un canal de YouTube arriba para que Purgito avise cuando haya videos nuevos.')));
    } else {
      const list = el('ul', { class: 'item-list' });
      for (const sub of data.subscriptions) list.append(subRow(sub, roles, loadYoutube));
      box.append(formGroup('Suscripciones activas', list));
    }
  } catch (e) { renderError(box, e); }
}
