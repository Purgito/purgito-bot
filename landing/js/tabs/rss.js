import { apiFetch } from '/js/core/api.js';
import { el, spinner, renderError, toast, formGroup, emptyState } from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, roleSelect, content } from '/js/panel-shell.js';
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'tabsRss.errNoPermission': '⚠️ Purgito no tiene permiso para escribir en este canal',
    'tabsRss.errChannelGone': '⚠️ el canal configurado ya no existe',
    'tabsRss.removeBtn': 'Quitar',
    'tabsRss.confirmQuestion': '¿Seguro?',
    'tabsRss.subNotFound': 'No se encontró esa suscripción',
    'tabsRss.subRemoved': 'Suscripción quitada',
    'tabsRss.rateLimitRemove': 'Rate limit — espera antes de quitar más',
    'tabsRss.noRoleMention': 'Sin mención a rol',
    'tabsRss.roleTooltip': 'Rol a mencionar al avisar nuevas publicaciones',
    'tabsRss.roleSaved': 'Rol de mención guardado',
    'tabsRss.roleRemoved': 'Mención quitada',
    'tabsRss.roleSaveError': 'No se pudo guardar el rol, intenta de nuevo',
    'tabsRss.urlPlaceholder': 'URL del feed RSS o Atom (ej: https://blog.ejemplo.com/feed.xml)',
    'tabsRss.fillFields': 'Completa la URL del feed y elige un canal de Discord',
    'tabsRss.subAdded': 'Suscripción agregada',
    'tabsRss.alreadySubscribed': 'Ese feed ya estaba registrado',
    'tabsRss.rateLimitAdd': 'Rate limit — espera antes de agregar más',
    'tabsRss.addBtn': 'Agregar',
    'tabsRss.addSubTitle': 'Agregar feed RSS / Atom',
    'tabsRss.addSubHint': 'Ingresa la URL completa del feed RSS o Atom de cualquier blog o sitio web.',
    'tabsRss.activeSubsTitle': 'Feeds activos',
    'tabsRss.emptyState': 'Todavía no hay feeds activos. Agrega una URL de RSS arriba para que Purgito avise cuando haya publicaciones nuevas.',
  },
  en: {
    'tabsRss.errNoPermission': '⚠️ Purgito doesn\'t have permission to post in this channel',
    'tabsRss.errChannelGone': '⚠️ the configured channel no longer exists',
    'tabsRss.removeBtn': 'Remove',
    'tabsRss.confirmQuestion': 'Are you sure?',
    'tabsRss.subNotFound': 'That subscription wasn\'t found',
    'tabsRss.subRemoved': 'Subscription removed',
    'tabsRss.rateLimitRemove': 'Rate limit — wait before removing more',
    'tabsRss.noRoleMention': 'No role mention',
    'tabsRss.roleTooltip': 'Role to mention when announcing new posts',
    'tabsRss.roleSaved': 'Mention role saved',
    'tabsRss.roleRemoved': 'Mention removed',
    'tabsRss.roleSaveError': 'Couldn\'t save the role, try again',
    'tabsRss.urlPlaceholder': 'RSS or Atom feed URL (e.g. https://blog.example.com/feed.xml)',
    'tabsRss.fillFields': 'Fill in the feed URL and pick a Discord channel',
    'tabsRss.subAdded': 'Subscription added',
    'tabsRss.alreadySubscribed': 'That feed was already registered',
    'tabsRss.rateLimitAdd': 'Rate limit — wait before adding more',
    'tabsRss.addBtn': 'Add',
    'tabsRss.addSubTitle': 'Add RSS / Atom feed',
    'tabsRss.addSubHint': 'Enter the full RSS or Atom feed URL for any blog or website.',
    'tabsRss.activeSubsTitle': 'Active feeds',
    'tabsRss.emptyState': 'No active feeds yet. Add an RSS URL above so Purgito announces new posts.',
  },
});

function errorNote(lastError) {
  if (lastError === 'sin_permiso') return t('tabsRss.errNoPermission');
  if (lastError === 'canal_no_encontrado') return t('tabsRss.errChannelGone');
  return null;
}

function subDeleteActions(sub, reload) {
  const wrap = el('div', { class: 'gif-actions' });

  function showButton() {
    wrap.innerHTML = '';
    wrap.append(el('button', { class: 'btn btn-danger btn-sm', onclick: showConfirm }, t('tabsRss.removeBtn')));
  }
  function showConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      t('tabsRss.confirmQuestion'),
      el('button', { class: 'btn btn-danger btn-sm', onclick: doDelete }, '✓'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButton }, '✗')));
  }
  async function doDelete() {
    try {
      const resp = await apiFetch(`/api/server/${GUILD_ID}/rss/${sub.id}`, { method: 'DELETE' });
      if (!resp.removed) {
        toast(t('tabsRss.subNotFound'), 'warn');
        showButton();
        return;
      }
      toast(t('tabsRss.subRemoved'), 'ok');
      reload();
    } catch (e) {
      toast(e.status === 429 ? t('tabsRss.rateLimitRemove') : e.message, e.status === 429 ? 'warn' : 'err');
      showButton();
    }
  }

  showButton();
  return wrap;
}

function subRow(sub, roles, reload) {
  const note = errorNote(sub.last_error);
  const sel = roleSelect(roles, sub.mention_role_id, t('tabsRss.noRoleMention'));
  sel.title = t('tabsRss.roleTooltip');
  sel.onchange = async () => {
    try {
      await apiFetch(`/api/server/${GUILD_ID}/rss/${sub.id}`, {
        method: 'PATCH', body: { mention_role_id: sel.value || null },
      });
      toast(sel.value ? t('tabsRss.roleSaved') : t('tabsRss.roleRemoved'), 'ok');
    } catch (e) { toast(t('tabsRss.roleSaveError'), 'err'); }
  };

  const info = el('div', { style: 'flex:1' },
    el('div', {},
      el('strong', {}, sub.feed_title || sub.feed_url),
      ' → #' + (sub.discord_channel_name || sub.discord_channel_id)),
    el('div', { class: 'dim', style: 'font-size:0.85em' }, sub.feed_url),
    note ? el('div', { class: 'chan-noperm' }, note) : null);

  return el('li', {}, info, sel, subDeleteActions(sub, reload));
}

export async function loadRss() {
  const box = content();
  box.append(spinner());
  try {
    const [data, channels, roles] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/rss`),
      getChannels(),
      getRoles(),
    ]);
    box.innerHTML = '';

    const urlInput = el('input', {
      type: 'url', placeholder: t('tabsRss.urlPlaceholder'), style: 'flex:1',
    });
    const chanSel = channelSelect(channels);
    const addBtn = el('button', {
      class: 'btn btn-primary',
      onclick: async () => {
        const feed_url = urlInput.value.trim();
        if (!feed_url || !chanSel.value) {
          toast(t('tabsRss.fillFields'), 'warn');
          return;
        }
        addBtn.disabled = true;
        try {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/rss`, {
            method: 'POST', body: { feed_url, discord_channel_id: chanSel.value },
          });
          if (resp.added) {
            toast(t('tabsRss.subAdded'), 'ok');
            urlInput.value = '';
            loadRss();
          } else {
            toast(t('tabsRss.alreadySubscribed'), 'warn');
          }
        } catch (e) {
          toast(e.status === 429 ? t('tabsRss.rateLimitAdd') : e.message, e.status === 429 ? 'warn' : 'err');
        } finally {
          addBtn.disabled = false;
        }
      },
    }, t('tabsRss.addBtn'));

    box.append(formGroup(t('tabsRss.addSubTitle'),
      el('p', { class: 'dim' },
        t('tabsRss.addSubHint')),
      el('div', { class: 'add-row' }, urlInput, chanSel, addBtn)));

    if (!data.subscriptions.length) {
      box.append(formGroup(t('tabsRss.activeSubsTitle'),
        emptyState(t('tabsRss.emptyState'))));
    } else {
      const list = el('ul', { class: 'item-list' });
      for (const sub of data.subscriptions) list.append(subRow(sub, roles, loadRss));
      box.append(formGroup(t('tabsRss.activeSubsTitle'), list));
    }
  } catch (e) { renderError(box, e); }
}
