import { apiFetch } from '/js/core/api.js';
import { el, spinner, renderError, toast, formGroup } from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, roleSelect, content } from '/js/panel-shell.js';
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'tabsYoutube.errNoPermission': '⚠️ Purgito no tiene permiso para escribir en este canal',
    'tabsYoutube.errChannelGone': '⚠️ el canal configurado ya no existe',
    'tabsYoutube.removeBtn': 'Quitar',
    'tabsYoutube.confirmQuestion': '¿Seguro?',
    'tabsYoutube.subNotFound': 'No se encontró esa suscripción',
    'tabsYoutube.subRemoved': 'Suscripción quitada',
    'tabsYoutube.rateLimitRemove': 'Rate limit — espera antes de quitar más',
    'tabsYoutube.noRoleMention': 'Sin mención a rol',
    'tabsYoutube.roleTooltip': 'Rol a mencionar al avisar nuevos videos',
    'tabsYoutube.roleSaved': 'Rol de mención guardado',
    'tabsYoutube.roleRemoved': 'Mención quitada',
    'tabsYoutube.roleSaveError': 'No se pudo guardar el rol, intenta de nuevo',
    'tabsYoutube.idPlaceholder': 'ID del canal de YouTube (empieza con UC…)',
    'tabsYoutube.fillFields': 'Completa el ID del canal y elige un canal de Discord',
    'tabsYoutube.subAdded': 'Suscripción agregada',
    'tabsYoutube.alreadySubscribed': 'Ese canal ya estaba suscripto',
    'tabsYoutube.rateLimitAdd': 'Rate limit — espera antes de agregar más',
    'tabsYoutube.addBtn': 'Agregar',
    'tabsYoutube.addSubTitle': 'Agregar suscripción',
    'tabsYoutube.addSubHint': 'Solo acepta el ID del canal de YouTube (el que empieza con UC…), no la URL completa ni @handle.',
    'tabsYoutube.activeSubsTitle': 'Suscripciones activas',
    'tabsYoutube.emptyState': 'Todavía no hay suscripciones activas. Agrega un canal de YouTube arriba para que Purgito avise cuando haya videos nuevos.',
  },
  en: {
    'tabsYoutube.errNoPermission': '⚠️ Purgito doesn\'t have permission to post in this channel',
    'tabsYoutube.errChannelGone': '⚠️ the configured channel no longer exists',
    'tabsYoutube.removeBtn': 'Remove',
    'tabsYoutube.confirmQuestion': 'Are you sure?',
    'tabsYoutube.subNotFound': 'That subscription wasn\'t found',
    'tabsYoutube.subRemoved': 'Subscription removed',
    'tabsYoutube.rateLimitRemove': 'Rate limit — wait before removing more',
    'tabsYoutube.noRoleMention': 'No role mention',
    'tabsYoutube.roleTooltip': 'Role to mention when announcing new videos',
    'tabsYoutube.roleSaved': 'Mention role saved',
    'tabsYoutube.roleRemoved': 'Mention removed',
    'tabsYoutube.roleSaveError': 'Couldn\'t save the role, try again',
    'tabsYoutube.idPlaceholder': 'YouTube channel ID (starts with UC…)',
    'tabsYoutube.fillFields': 'Fill in the channel ID and pick a Discord channel',
    'tabsYoutube.subAdded': 'Subscription added',
    'tabsYoutube.alreadySubscribed': 'That channel was already subscribed',
    'tabsYoutube.rateLimitAdd': 'Rate limit — wait before adding more',
    'tabsYoutube.addBtn': 'Add',
    'tabsYoutube.addSubTitle': 'Add subscription',
    'tabsYoutube.addSubHint': 'Only accepts the YouTube channel ID (the one starting with UC…), not the full URL or @handle.',
    'tabsYoutube.activeSubsTitle': 'Active subscriptions',
    'tabsYoutube.emptyState': 'No active subscriptions yet. Link a YouTube channel above so Purgito announces new videos.',
  },
});

// Mismos dos estados que cogs/youtube.py._check_one puede marcar en
// last_error (ver db.YOUTUBE_ERROR_*) y el mismo aviso que ya muestra la
// categoría YouTube de /settings para cada uno.
function errorNote(lastError) {
  if (lastError === 'sin_permiso') return t('tabsYoutube.errNoPermission');
  if (lastError === 'canal_no_encontrado') return t('tabsYoutube.errChannelGone');
  return null;
}

// Confirmación de borrado en dos pasos, mismo patrón que gifDeleteActions de tabs/gifs.js.
function subDeleteActions(sub, reload) {
  const wrap = el('div', { class: 'gif-actions' });

  function showButton() {
    wrap.innerHTML = '';
    wrap.append(el('button', { class: 'btn btn-danger btn-sm', onclick: showConfirm }, t('tabsYoutube.removeBtn')));
  }
  function showConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      t('tabsYoutube.confirmQuestion'),
      el('button', { class: 'btn btn-danger btn-sm', onclick: doDelete }, '✓'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButton }, '✗')));
  }
  async function doDelete() {
    try {
      const resp = await apiFetch(`/api/server/${GUILD_ID}/youtube/${sub.id}`, { method: 'DELETE' });
      if (!resp.removed) {
        toast(t('tabsYoutube.subNotFound'), 'warn');
        showButton();
        return;
      }
      toast(t('tabsYoutube.subRemoved'), 'ok');
      reload();
    } catch (e) {
      toast(e.status === 429 ? t('tabsYoutube.rateLimitRemove') : e.message, e.status === 429 ? 'warn' : 'err');
      showButton();
    }
  }

  showButton();
  return wrap;
}

function subRow(sub, roles, reload) {
  const note = errorNote(sub.last_error);
  const sel = roleSelect(roles, sub.mention_role_id, t('tabsYoutube.noRoleMention'));
  sel.title = t('tabsYoutube.roleTooltip');
  sel.onchange = async () => {
    try {
      await apiFetch(`/api/server/${GUILD_ID}/youtube/${sub.id}`, {
        method: 'PATCH', body: { mention_role_id: sel.value || null },
      });
      toast(sel.value ? t('tabsYoutube.roleSaved') : t('tabsYoutube.roleRemoved'), 'ok');
    } catch (e) { toast(t('tabsYoutube.roleSaveError'), 'err'); }
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
      type: 'text', placeholder: t('tabsYoutube.idPlaceholder'), style: 'flex:1',
    });
    const chanSel = channelSelect(channels);
    const addBtn = el('button', {
      class: 'btn btn-primary',
      onclick: async () => {
        const channel_id = idInput.value.trim();
        if (!channel_id || !chanSel.value) {
          toast(t('tabsYoutube.fillFields'), 'warn');
          return;
        }
        addBtn.disabled = true;
        try {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/youtube`, {
            method: 'POST', body: { channel_id, discord_channel_id: chanSel.value },
          });
          if (resp.added) {
            toast(t('tabsYoutube.subAdded'), 'ok');
            idInput.value = '';
            loadYoutube();
          } else {
            toast(t('tabsYoutube.alreadySubscribed'), 'warn');
          }
        } catch (e) {
          toast(e.status === 429 ? t('tabsYoutube.rateLimitAdd') : e.message, e.status === 429 ? 'warn' : 'err');
        } finally {
          addBtn.disabled = false;
        }
      },
    }, t('tabsYoutube.addBtn'));

    box.append(formGroup(t('tabsYoutube.addSubTitle'),
      el('p', { class: 'dim' },
        t('tabsYoutube.addSubHint')),
      el('div', { class: 'add-row' }, idInput, chanSel, addBtn)));

    if (!data.subscriptions.length) {
      box.append(formGroup(t('tabsYoutube.activeSubsTitle'),
        emptyState(t('tabsYoutube.emptyState'))));
    } else {
      const list = el('ul', { class: 'item-list' });
      for (const sub of data.subscriptions) list.append(subRow(sub, roles, loadYoutube));
      box.append(formGroup(t('tabsYoutube.activeSubsTitle'), list));
    }
  } catch (e) { renderError(box, e); }
}
