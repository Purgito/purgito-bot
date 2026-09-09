import { apiFetch } from '/js/core/api.js';
import { el, spinner, renderError, toast, formGroup, emptyState } from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, roleSelect, content } from '/js/panel-shell.js';
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'tabsTwitch.notConfigured': 'Purgito no tiene configurada la integración con Twitch en este momento.',
    'tabsTwitch.errNoPermission': '⚠️ Purgito no tiene permiso para escribir en este canal',
    'tabsTwitch.errChannelGone': '⚠️ el canal configurado ya no existe',
    'tabsTwitch.removeBtn': 'Quitar',
    'tabsTwitch.confirmQuestion': '¿Seguro?',
    'tabsTwitch.subNotFound': 'No se encontró esa suscripción',
    'tabsTwitch.subRemoved': 'Suscripción quitada',
    'tabsTwitch.rateLimitRemove': 'Rate limit — espera antes de quitar más',
    'tabsTwitch.noRoleMention': 'Sin mención a rol',
    'tabsTwitch.roleTooltip': 'Rol a mencionar al avisar que empezó a transmitir',
    'tabsTwitch.roleSaved': 'Rol de mención guardado',
    'tabsTwitch.roleRemoved': 'Mención quitada',
    'tabsTwitch.roleSaveError': 'No se pudo guardar el rol, intenta de nuevo',
    'tabsTwitch.idPlaceholder': 'Nombre de usuario o URL del canal de Twitch',
    'tabsTwitch.fillFields': 'Completa el canal y elige un canal de Discord',
    'tabsTwitch.subAdded': 'Suscripción agregada',
    'tabsTwitch.alreadySubscribed': 'Ese canal ya estaba suscripto',
    'tabsTwitch.rateLimitAdd': 'Rate limit — espera antes de agregar más',
    'tabsTwitch.addBtn': 'Agregar',
    'tabsTwitch.addSubTitle': 'Agregar suscripción',
    'tabsTwitch.addSubHint': 'Ingresa el nombre de usuario de Twitch o la URL completa del canal.',
    'tabsTwitch.activeSubsTitle': 'Suscripciones activas',
    'tabsTwitch.emptyState': 'Todavía no hay suscripciones activas. Agrega un canal de Twitch arriba para que Purgito avise cuando empiece a transmitir.',
  },
  en: {
    'tabsTwitch.notConfigured': "Purgito doesn't have the Twitch integration configured right now.",
    'tabsTwitch.errNoPermission': '⚠️ Purgito doesn\'t have permission to post in this channel',
    'tabsTwitch.errChannelGone': '⚠️ the configured channel no longer exists',
    'tabsTwitch.removeBtn': 'Remove',
    'tabsTwitch.confirmQuestion': 'Are you sure?',
    'tabsTwitch.subNotFound': 'That subscription wasn\'t found',
    'tabsTwitch.subRemoved': 'Subscription removed',
    'tabsTwitch.rateLimitRemove': 'Rate limit — wait before removing more',
    'tabsTwitch.noRoleMention': 'No role mention',
    'tabsTwitch.roleTooltip': 'Role to mention when announcing a new live stream',
    'tabsTwitch.roleSaved': 'Mention role saved',
    'tabsTwitch.roleRemoved': 'Mention removed',
    'tabsTwitch.roleSaveError': 'Couldn\'t save the role, try again',
    'tabsTwitch.idPlaceholder': 'Twitch username or channel URL',
    'tabsTwitch.fillFields': 'Fill in the Twitch channel and pick a Discord channel',
    'tabsTwitch.subAdded': 'Subscription added',
    'tabsTwitch.alreadySubscribed': 'That channel was already subscribed',
    'tabsTwitch.rateLimitAdd': 'Rate limit — wait before adding more',
    'tabsTwitch.addBtn': 'Add',
    'tabsTwitch.addSubTitle': 'Add subscription',
    'tabsTwitch.addSubHint': 'Enter the Twitch username or the full channel URL.',
    'tabsTwitch.activeSubsTitle': 'Active subscriptions',
    'tabsTwitch.emptyState': 'No active subscriptions yet. Link a Twitch channel above so Purgito announces when it goes live.',
  },
});

// Mismos dos estados que cogs/twitch.py.check_twitch puede marcar en
// last_error (ver db.TWITCH_ERROR_*), mismo aviso que la categoría Twitch de
// /settings para cada uno.
function errorNote(lastError) {
  if (lastError === 'sin_permiso') return t('tabsTwitch.errNoPermission');
  if (lastError === 'canal_no_encontrado') return t('tabsTwitch.errChannelGone');
  return null;
}

// Confirmación de borrado en dos pasos, mismo patrón que gifDeleteActions de tabs/gifs.js.
function subDeleteActions(sub, reload) {
  const wrap = el('div', { class: 'gif-actions' });

  function showButton() {
    wrap.innerHTML = '';
    wrap.append(el('button', { class: 'btn btn-danger btn-sm', onclick: showConfirm }, t('tabsTwitch.removeBtn')));
  }
  function showConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      t('tabsTwitch.confirmQuestion'),
      el('button', { class: 'btn btn-danger btn-sm', onclick: doDelete }, '✓'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButton }, '✗')));
  }
  async function doDelete() {
    try {
      const resp = await apiFetch(`/api/server/${GUILD_ID}/twitch/${sub.id}`, { method: 'DELETE' });
      if (!resp.removed) {
        toast(t('tabsTwitch.subNotFound'), 'warn');
        showButton();
        return;
      }
      toast(t('tabsTwitch.subRemoved'), 'ok');
      reload();
    } catch (e) {
      toast(e.status === 429 ? t('tabsTwitch.rateLimitRemove') : e.message, e.status === 429 ? 'warn' : 'err');
      showButton();
    }
  }

  showButton();
  return wrap;
}

function subRow(sub, roles, reload) {
  const note = errorNote(sub.last_error);
  const sel = roleSelect(roles, sub.mention_role_id, t('tabsTwitch.noRoleMention'));
  sel.title = t('tabsTwitch.roleTooltip');
  sel.onchange = async () => {
    try {
      await apiFetch(`/api/server/${GUILD_ID}/twitch/${sub.id}`, {
        method: 'PATCH', body: { mention_role_id: sel.value || null },
      });
      toast(sel.value ? t('tabsTwitch.roleSaved') : t('tabsTwitch.roleRemoved'), 'ok');
    } catch (e) { toast(t('tabsTwitch.roleSaveError'), 'err'); }
  };

  const info = el('div', { style: 'flex:1' },
    el('div', {},
      el('strong', {}, sub.twitch_login),
      ' → #' + (sub.discord_channel_name || sub.discord_channel_id)),
    note ? el('div', { class: 'chan-noperm' }, note) : null);

  return el('li', {}, info, sel, subDeleteActions(sub, reload));
}

export async function loadTwitch() {
  const box = content();
  box.append(spinner());
  try {
    const [data, channels, roles] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/twitch`),
      getChannels(),
      getRoles(),
    ]);
    box.innerHTML = '';

    if (!data.configured) {
      box.append(formGroup(t('tabsTwitch.activeSubsTitle'),
        el('p', { class: 'dim' }, t('tabsTwitch.notConfigured'))));
      return;
    }

    const idInput = el('input', {
      type: 'text', placeholder: t('tabsTwitch.idPlaceholder'), style: 'flex:1',
    });
    const chanSel = channelSelect(channels);
    const addBtn = el('button', {
      class: 'btn btn-primary',
      onclick: async () => {
        const channel_login = idInput.value.trim();
        if (!channel_login || !chanSel.value) {
          toast(t('tabsTwitch.fillFields'), 'warn');
          return;
        }
        addBtn.disabled = true;
        try {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/twitch`, {
            method: 'POST', body: { channel_login, discord_channel_id: chanSel.value },
          });
          if (resp.added) {
            toast(t('tabsTwitch.subAdded'), 'ok');
            idInput.value = '';
            loadTwitch();
          } else {
            toast(t('tabsTwitch.alreadySubscribed'), 'warn');
          }
        } catch (e) {
          toast(e.status === 429 ? t('tabsTwitch.rateLimitAdd') : e.message, e.status === 429 ? 'warn' : 'err');
        } finally {
          addBtn.disabled = false;
        }
      },
    }, t('tabsTwitch.addBtn'));

    box.append(formGroup(t('tabsTwitch.addSubTitle'),
      el('p', { class: 'dim' },
        t('tabsTwitch.addSubHint')),
      el('div', { class: 'add-row' }, idInput, chanSel, addBtn)));

    if (!data.subscriptions.length) {
      box.append(formGroup(t('tabsTwitch.activeSubsTitle'),
        emptyState(t('tabsTwitch.emptyState'))));
    } else {
      const list = el('ul', { class: 'item-list' });
      for (const sub of data.subscriptions) list.append(subRow(sub, roles, loadTwitch));
      box.append(formGroup(t('tabsTwitch.activeSubsTitle'), list));
    }
  } catch (e) { renderError(box, e); }
}
