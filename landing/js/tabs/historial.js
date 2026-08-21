import { apiFetch } from '/js/core/api.js';
import { el, icon, spinner, emptyState, renderError, formGroup, toast } from '/js/core/dom.js';
import { GUILD_ID, formatDateTime } from '/js/core/config.js';
import { content } from '/js/panel-shell.js';
import { t, addStrings } from '../core/i18n.js';

const PAGE_SIZE = 5;

addStrings({
  es: {
    'tabsHistorial.action.chat.settings_update': 'Actualizó la configuración del chat',
    'tabsHistorial.action.chat.tunables_update': 'Ajustó los parámetros del chat',
    'tabsHistorial.action.channel_settings.update': 'Cambió los ajustes de un canal puntual',
    'tabsHistorial.action.corpus.add': 'Agregó un canal de aprendizaje',
    'tabsHistorial.action.corpus.remove': 'Quitó un canal de aprendizaje',
    'tabsHistorial.action.corpus.amnesia': 'Borró el corpus de las últimas 24 horas (amnesia)',
    'tabsHistorial.action.embed_template.create': 'Creó una plantilla de embed',
    'tabsHistorial.action.embed_template.update': 'Editó una plantilla de embed',
    'tabsHistorial.action.embed_template.delete': 'Eliminó una plantilla de embed',
    'tabsHistorial.action.embeds.schedule': 'Programó un anuncio con embed',
    'tabsHistorial.action.embeds.send': 'Envió un embed',
    'tabsHistorial.action.events.welcome.update': 'Actualizó el evento de bienvenida',
    'tabsHistorial.action.events.welcome.enabled': 'Activó el evento de bienvenida',
    'tabsHistorial.action.events.welcome.disabled': 'Desactivó el evento de bienvenida',
    'tabsHistorial.action.events.welcome.delete': 'Restableció el evento de bienvenida',
    'tabsHistorial.action.events.welcome.test': 'Envió prueba del evento de bienvenida',
    'tabsHistorial.action.events.goodbye.update': 'Actualizó el evento de despedida',
    'tabsHistorial.action.events.goodbye.enabled': 'Activó el evento de despedida',
    'tabsHistorial.action.events.goodbye.disabled': 'Desactivó el evento de despedida',
    'tabsHistorial.action.events.goodbye.delete': 'Restableció el evento de despedida',
    'tabsHistorial.action.events.goodbye.test': 'Envió prueba del evento de despedida',
    'tabsHistorial.action.events.boost.update': 'Actualizó el evento de boost',
    'tabsHistorial.action.events.boost.enabled': 'Activó el evento de boost',
    'tabsHistorial.action.events.boost.disabled': 'Desactivó el evento de boost',
    'tabsHistorial.action.events.boost.delete': 'Restableció el evento de boost',
    'tabsHistorial.action.events.boost.test': 'Envió prueba del evento de boost',
    'tabsHistorial.action.excluded_users.add': 'Excluyó a un usuario de interacciones o aprendizaje',
    'tabsHistorial.action.excluded_users.update': 'Actualizó la exclusión de un usuario',
    'tabsHistorial.action.excluded_users.remove': 'Eliminó la exclusión de un usuario',
    'tabsHistorial.action.exempt_channels.add': 'Agregó un canal exento del límite de menciones',
    'tabsHistorial.action.exempt_channels.remove': 'Quitó un canal exento del límite de menciones',
    'tabsHistorial.action.exempt_roles.add': 'Agregó un rol exento del límite de menciones',
    'tabsHistorial.action.exempt_roles.remove': 'Quitó un rol exento del límite de menciones',
    'tabsHistorial.action.frases.add': 'Agregó una frase especial',
    'tabsHistorial.action.frases.edit': 'Editó una frase especial',
    'tabsHistorial.action.frases.remove': 'Eliminó una frase especial',
    'tabsHistorial.action.frases.set_pack': 'Cambió el pack de una frase',
    'tabsHistorial.action.frase_channels.add': 'Habilitó un canal para frases especiales',
    'tabsHistorial.action.frase_channels.remove': 'Deshabilitó un canal para frases especiales',
    'tabsHistorial.action.frase_packs.create': 'Creó un pack de frases',
    'tabsHistorial.action.frase_packs.delete': 'Eliminó un pack de frases',
    'tabsHistorial.action.frase_packs.assign_channel': 'Asignó un pack de frases a un canal',
    'tabsHistorial.action.frase_packs.unassign_channel': 'Quitó un pack de frases de un canal',
    'tabsHistorial.action.gifs.add': 'Agregó un GIF',
    'tabsHistorial.action.gifs.auto_removed': 'Quitó solo un GIF porque su host dejó de servirlo',
    'tabsHistorial.action.gifs.remove': 'Eliminó un GIF',
    'tabsHistorial.action.gifs.block': 'Bloqueó un GIF',
    'tabsHistorial.action.gifs.unblock': 'Desbloqueó un GIF',
    'tabsHistorial.action.mention_channels.add': 'Agregó un canal de menciones',
    'tabsHistorial.action.mention_channels.remove': 'Quitó un canal de menciones',
    'tabsHistorial.action.reactions.add': 'Agregó una reacción',
    'tabsHistorial.action.reactions.remove': 'Quitó una reacción',
    'tabsHistorial.action.spontaneous_channels.add': 'Agregó un canal de participación espontánea',
    'tabsHistorial.action.spontaneous_channels.remove': 'Quitó un canal de participación espontánea',
    'tabsHistorial.action.style.update': 'Actualizó el estilo del bot',
    'tabsHistorial.action.triggers.create': 'Creó un trigger de canal',
    'tabsHistorial.action.triggers.delete': 'Eliminó un trigger de canal',
    'tabsHistorial.action.updates_channel.set': 'Configuró el canal de novedades',
    'tabsHistorial.action.youtube.add': 'Agregó una suscripción de YouTube',
    'tabsHistorial.action.youtube.remove': 'Eliminó una suscripción de YouTube',
    'tabsHistorial.action.youtube.update_mention_role': 'Cambió el rol de mención de YouTube',
    'tabsHistorial.emptyState': 'Todavía no hay cambios registrados en este servidor.',
    'tabsHistorial.searchPlaceholder': 'Buscar cambios por texto, usuario o acción…',
    'tabsHistorial.searchAria': 'Buscar cambios',
    'tabsHistorial.filterUserAria': 'Filtrar por usuario',
    'tabsHistorial.allUsers': 'Todos los usuarios',
    'tabsHistorial.filterActionAria': 'Filtrar por acción',
    'tabsHistorial.allActions': 'Todas las acciones',
    'tabsHistorial.groupContent': 'Contenido',
    'tabsHistorial.optAllContent': 'Todo en Contenido',
    'tabsHistorial.optFrases': 'Frases especiales',
    'tabsHistorial.optFrasePacks': 'Packs de frases',
    'tabsHistorial.optTriggers': 'Triggers de canal',
    'tabsHistorial.optReactions': 'Reacciones',
    'tabsHistorial.groupChat': 'Chat y configuración',
    'tabsHistorial.optAllChat': 'Todo en Chat y canales',
    'tabsHistorial.optChatSettings': 'Configuración del chat',
    'tabsHistorial.optChannelSettings': 'Ajustes de canales',
    'tabsHistorial.optCorpus': 'Memoria y aprendizaje',
    'tabsHistorial.optExempt': 'Exenciones de menciones',
    'tabsHistorial.groupMultimedia': 'Multimedia',
    'tabsHistorial.optGifs': 'GIFs',
    'tabsHistorial.groupEmbeds': 'Embeds',
    'tabsHistorial.optEmbeds': 'Embeds y plantillas',
    'tabsHistorial.groupIntegrations': 'Integraciones',
    'tabsHistorial.optYoutube': 'YouTube',
    'tabsHistorial.groupGeneral': 'General',
    'tabsHistorial.optStyle': 'Estilo del bot',
    'tabsHistorial.dateFromTitle': 'Fecha inicial',
    'tabsHistorial.dateToTitle': 'Fecha final',
    'tabsHistorial.dateFromLabel': 'Desde',
    'tabsHistorial.dateToLabel': 'Hasta',
    'tabsHistorial.filterDateAria': 'Filtrar por fecha',
    'tabsHistorial.dateAny': 'Cualquier fecha',
    'tabsHistorial.dateToday': 'Hoy',
    'tabsHistorial.dateYesterday': 'Ayer',
    'tabsHistorial.date7d': 'Últimos 7 días',
    'tabsHistorial.date30d': 'Últimos 30 días',
    'tabsHistorial.dateCustom': 'Personalizado…',
    'tabsHistorial.chipText': 'Texto: "{q}"',
    'tabsHistorial.chipUser': 'Usuario: {name}',
    'tabsHistorial.chipAction': 'Acción: {label}',
    'tabsHistorial.chipDate': 'Fecha: {label}',
    'tabsHistorial.clearFilters': 'Limpiar filtros',
    'tabsHistorial.removeFilterAria': 'Quitar filtro {text}',
    'tabsHistorial.sectionTitle': 'Historial de cambios',
    'tabsHistorial.noMore': 'No hay más acciones',
    'tabsHistorial.loadMore': 'Cargar más',
    'tabsHistorial.loading': 'Cargando…',
    'tabsHistorial.noMatchFiltered': 'No hay cambios que coincidan con estos filtros.',
  },
  en: {
    'tabsHistorial.action.chat.settings_update': 'Updated the chat settings',
    'tabsHistorial.action.chat.tunables_update': 'Adjusted the chat parameters',
    'tabsHistorial.action.channel_settings.update': 'Changed settings for a specific channel',
    'tabsHistorial.action.corpus.add': 'Added a learning channel',
    'tabsHistorial.action.corpus.remove': 'Removed a learning channel',
    'tabsHistorial.action.corpus.amnesia': 'Cleared the corpus from the last 24 hours (amnesia)',
    'tabsHistorial.action.embed_template.create': 'Created an embed template',
    'tabsHistorial.action.embed_template.update': 'Edited an embed template',
    'tabsHistorial.action.embed_template.delete': 'Deleted an embed template',
    'tabsHistorial.action.embeds.schedule': 'Scheduled an embed announcement',
    'tabsHistorial.action.embeds.send': 'Sent an embed',
    'tabsHistorial.action.events.welcome.update': 'Updated the welcome event',
    'tabsHistorial.action.events.welcome.enabled': 'Enabled the welcome event',
    'tabsHistorial.action.events.welcome.disabled': 'Disabled the welcome event',
    'tabsHistorial.action.events.welcome.delete': 'Reset the welcome event',
    'tabsHistorial.action.events.welcome.test': 'Sent a welcome event test',
    'tabsHistorial.action.events.goodbye.update': 'Updated the goodbye event',
    'tabsHistorial.action.events.goodbye.enabled': 'Enabled the goodbye event',
    'tabsHistorial.action.events.goodbye.disabled': 'Disabled the goodbye event',
    'tabsHistorial.action.events.goodbye.delete': 'Reset the goodbye event',
    'tabsHistorial.action.events.goodbye.test': 'Sent a goodbye event test',
    'tabsHistorial.action.events.boost.update': 'Updated the boost event',
    'tabsHistorial.action.events.boost.enabled': 'Enabled the boost event',
    'tabsHistorial.action.events.boost.disabled': 'Disabled the boost event',
    'tabsHistorial.action.events.boost.delete': 'Reset the boost event',
    'tabsHistorial.action.events.boost.test': 'Sent a boost event test',
    'tabsHistorial.action.excluded_users.add': 'Excluded a user from interactions or learning',
    'tabsHistorial.action.excluded_users.update': 'Updated a user exclusion',
    'tabsHistorial.action.excluded_users.remove': 'Removed a user exclusion',
    'tabsHistorial.action.exempt_channels.add': 'Added a channel exempt from the mention limit',
    'tabsHistorial.action.exempt_channels.remove': 'Removed a channel exempt from the mention limit',
    'tabsHistorial.action.exempt_roles.add': 'Added a role exempt from the mention limit',
    'tabsHistorial.action.exempt_roles.remove': 'Removed a role exempt from the mention limit',
    'tabsHistorial.action.frases.add': 'Added a special phrase',
    'tabsHistorial.action.frases.edit': 'Edited a special phrase',
    'tabsHistorial.action.frases.remove': 'Deleted a special phrase',
    'tabsHistorial.action.frases.set_pack': "Changed a phrase's pack",
    'tabsHistorial.action.frase_channels.add': 'Enabled a channel for special phrases',
    'tabsHistorial.action.frase_channels.remove': 'Disabled a channel for special phrases',
    'tabsHistorial.action.frase_packs.create': 'Created a phrase pack',
    'tabsHistorial.action.frase_packs.delete': 'Deleted a phrase pack',
    'tabsHistorial.action.frase_packs.assign_channel': 'Assigned a phrase pack to a channel',
    'tabsHistorial.action.frase_packs.unassign_channel': 'Removed a phrase pack from a channel',
    'tabsHistorial.action.gifs.add': 'Added a GIF',
    'tabsHistorial.action.gifs.auto_removed': 'Automatically removed a GIF because its host stopped serving it',
    'tabsHistorial.action.gifs.remove': 'Deleted a GIF',
    'tabsHistorial.action.gifs.block': 'Blocked a GIF',
    'tabsHistorial.action.gifs.unblock': 'Unblocked a GIF',
    'tabsHistorial.action.mention_channels.add': 'Added a mention channel',
    'tabsHistorial.action.mention_channels.remove': 'Removed a mention channel',
    'tabsHistorial.action.reactions.add': 'Added a reaction',
    'tabsHistorial.action.reactions.remove': 'Removed a reaction',
    'tabsHistorial.action.spontaneous_channels.add': 'Added a spontaneous participation channel',
    'tabsHistorial.action.spontaneous_channels.remove': 'Removed a spontaneous participation channel',
    'tabsHistorial.action.style.update': "Updated the bot's style",
    'tabsHistorial.action.triggers.create': 'Created a channel trigger',
    'tabsHistorial.action.triggers.delete': 'Deleted a channel trigger',
    'tabsHistorial.action.updates_channel.set': 'Set the updates channel',
    'tabsHistorial.action.youtube.add': 'Added a YouTube subscription',
    'tabsHistorial.action.youtube.remove': 'Removed a YouTube subscription',
    'tabsHistorial.action.youtube.update_mention_role': 'Changed the YouTube mention role',
    'tabsHistorial.emptyState': 'No changes recorded on this server yet.',
    'tabsHistorial.searchPlaceholder': 'Search changes by text, user, or action…',
    'tabsHistorial.searchAria': 'Search changes',
    'tabsHistorial.filterUserAria': 'Filter by user',
    'tabsHistorial.allUsers': 'All users',
    'tabsHistorial.filterActionAria': 'Filter by action',
    'tabsHistorial.allActions': 'All actions',
    'tabsHistorial.groupContent': 'Content',
    'tabsHistorial.optAllContent': 'Everything in Content',
    'tabsHistorial.optFrases': 'Special phrases',
    'tabsHistorial.optFrasePacks': 'Phrase packs',
    'tabsHistorial.optTriggers': 'Channel triggers',
    'tabsHistorial.optReactions': 'Reactions',
    'tabsHistorial.groupChat': 'Chat and settings',
    'tabsHistorial.optAllChat': 'Everything in Chat and channels',
    'tabsHistorial.optChatSettings': 'Chat settings',
    'tabsHistorial.optChannelSettings': 'Channel settings',
    'tabsHistorial.optCorpus': 'Memory and learning',
    'tabsHistorial.optExempt': 'Mention exemptions',
    'tabsHistorial.groupMultimedia': 'Multimedia',
    'tabsHistorial.optGifs': 'GIFs',
    'tabsHistorial.groupEmbeds': 'Embeds',
    'tabsHistorial.optEmbeds': 'Embeds and templates',
    'tabsHistorial.groupIntegrations': 'Integrations',
    'tabsHistorial.optYoutube': 'YouTube',
    'tabsHistorial.groupGeneral': 'General',
    'tabsHistorial.optStyle': "Bot's style",
    'tabsHistorial.dateFromTitle': 'Start date',
    'tabsHistorial.dateToTitle': 'End date',
    'tabsHistorial.dateFromLabel': 'From',
    'tabsHistorial.dateToLabel': 'To',
    'tabsHistorial.filterDateAria': 'Filter by date',
    'tabsHistorial.dateAny': 'Any date',
    'tabsHistorial.dateToday': 'Today',
    'tabsHistorial.dateYesterday': 'Yesterday',
    'tabsHistorial.date7d': 'Last 7 days',
    'tabsHistorial.date30d': 'Last 30 days',
    'tabsHistorial.dateCustom': 'Custom…',
    'tabsHistorial.chipText': 'Text: "{q}"',
    'tabsHistorial.chipUser': 'User: {name}',
    'tabsHistorial.chipAction': 'Action: {label}',
    'tabsHistorial.chipDate': 'Date: {label}',
    'tabsHistorial.clearFilters': 'Clear filters',
    'tabsHistorial.removeFilterAria': 'Remove filter {text}',
    'tabsHistorial.sectionTitle': 'Change history',
    'tabsHistorial.noMore': 'No more actions',
    'tabsHistorial.loadMore': 'Load more',
    'tabsHistorial.loading': 'Loading…',
    'tabsHistorial.noMatchFiltered': 'No changes match these filters.',
  },
});

// Traduce el "action" que graba db.log_audit (ver _log_audit en webapi.py) a
// un texto legible. Lo que no está mapeado se muestra tal cual: mejor un
// action en crudo que un renglón vacío si se agrega uno nuevo acá y se
// olvida sumarlo a este mapa.
const ACTION_LABELS = {
  'chat.settings_update': t('tabsHistorial.action.chat.settings_update'),
  'chat.tunables_update': t('tabsHistorial.action.chat.tunables_update'),
  'channel_settings.update': t('tabsHistorial.action.channel_settings.update'),
  'corpus.add': t('tabsHistorial.action.corpus.add'),
  'corpus.remove': t('tabsHistorial.action.corpus.remove'),
  'corpus.amnesia': t('tabsHistorial.action.corpus.amnesia'),
  'embed_template.create': t('tabsHistorial.action.embed_template.create'),
  'embed_template.update': t('tabsHistorial.action.embed_template.update'),
  'embed_template.delete': t('tabsHistorial.action.embed_template.delete'),
  'embeds.schedule': t('tabsHistorial.action.embeds.schedule'),
  'embeds.send': t('tabsHistorial.action.embeds.send'),
  'excluded_users.add': t('tabsHistorial.action.excluded_users.add'),
  'excluded_users.update': t('tabsHistorial.action.excluded_users.update'),
  'excluded_users.remove': t('tabsHistorial.action.excluded_users.remove'),
  'exempt_channels.add': t('tabsHistorial.action.exempt_channels.add'),
  'exempt_channels.remove': t('tabsHistorial.action.exempt_channels.remove'),
  'exempt_roles.add': t('tabsHistorial.action.exempt_roles.add'),
  'exempt_roles.remove': t('tabsHistorial.action.exempt_roles.remove'),
  'frases.add': t('tabsHistorial.action.frases.add'),
  'frases.edit': t('tabsHistorial.action.frases.edit'),
  'frases.remove': t('tabsHistorial.action.frases.remove'),
  'frases.set_pack': t('tabsHistorial.action.frases.set_pack'),
  'frase_channels.add': t('tabsHistorial.action.frase_channels.add'),
  'frase_channels.remove': t('tabsHistorial.action.frase_channels.remove'),
  'frase_packs.create': t('tabsHistorial.action.frase_packs.create'),
  'frase_packs.delete': t('tabsHistorial.action.frase_packs.delete'),
  'frase_packs.assign_channel': t('tabsHistorial.action.frase_packs.assign_channel'),
  'frase_packs.unassign_channel': t('tabsHistorial.action.frase_packs.unassign_channel'),
  'gifs.add': t('tabsHistorial.action.gifs.add'),
  'gifs.auto_removed': t('tabsHistorial.action.gifs.auto_removed'),
  'gifs.remove': t('tabsHistorial.action.gifs.remove'),
  'gifs.block': t('tabsHistorial.action.gifs.block'),
  'gifs.unblock': t('tabsHistorial.action.gifs.unblock'),
  'mention_channels.add': t('tabsHistorial.action.mention_channels.add'),
  'mention_channels.remove': t('tabsHistorial.action.mention_channels.remove'),
  'reactions.add': t('tabsHistorial.action.reactions.add'),
  'reactions.remove': t('tabsHistorial.action.reactions.remove'),
  'spontaneous_channels.add': t('tabsHistorial.action.spontaneous_channels.add'),
  'spontaneous_channels.remove': t('tabsHistorial.action.spontaneous_channels.remove'),
  'style.update': t('tabsHistorial.action.style.update'),
  'triggers.create': t('tabsHistorial.action.triggers.create'),
  'triggers.delete': t('tabsHistorial.action.triggers.delete'),
  'updates_channel.set': t('tabsHistorial.action.updates_channel.set'),
  'youtube.add': t('tabsHistorial.action.youtube.add'),
  'youtube.remove': t('tabsHistorial.action.youtube.remove'),
  'youtube.update_mention_role': t('tabsHistorial.action.youtube.update_mention_role'),
};

function actionLabel(action) {
  return ACTION_LABELS[action] || action;
}

function getActionIcon(action) {
  if (action.startsWith('gifs.')) return 'film';
  if (action.startsWith('embed')) return 'layout';
  if (action.startsWith('youtube.')) return 'youtube';
  if (action.startsWith('frase') || action.startsWith('triggers.') || action.startsWith('reactions.')) return 'chat';
  if (action.startsWith('style.')) return 'image';
  return 'history';
}

function formatWhen(createdAt) {
  return formatDateTime(new Date(createdAt.replace(' ', 'T') + 'Z'));
}

function entryRow(entry) {
  return el('li', { class: 'audit-item' },
    el('div', { class: 'audit-icon-wrap' }, icon(getActionIcon(entry.action))),
    el('div', { class: 'audit-content', style: 'flex:1' },
      el('div', { class: 'audit-title' },
        el('strong', { class: 'audit-user' }, entry.user_name),
        el('span', { class: 'dim' }, ' — '),
        el('span', { class: 'audit-action' }, actionLabel(entry.action))
      ),
      entry.detail ? el('div', { class: 'audit-detail dim' }, entry.detail) : null
    ),
    el('span', { class: 'audit-date dim' }, formatWhen(entry.created_at))
  );
}

const AUDIT_PATH = (guildId) => `/api/guilds/${guildId}/audit`;

export async function loadHistorial() {
  const box = content();
  box.append(spinner());

  const state = {
    q: '',
    userId: '',
    action: '',
    datePreset: 'all',
    dateFrom: '',
    dateTo: '',
    limit: PAGE_SIZE,
    cursor: null,
    hasMore: false,
    users: [],
  };

  let debounceTimer = null;

  function getDateParams() {
    if (state.datePreset === 'today') {
      const d = new Date().toISOString().slice(0, 10);
      return { date_from: d + ' 00:00:00', date_to: d + ' 23:59:59' };
    }
    if (state.datePreset === 'yesterday') {
      const y = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
      return { date_from: y + ' 00:00:00', date_to: y + ' 23:59:59' };
    }
    if (state.datePreset === '7d') {
      const d = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
      return { date_from: d + ' 00:00:00' };
    }
    if (state.datePreset === '30d') {
      const d = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
      return { date_from: d + ' 00:00:00' };
    }
    if (state.datePreset === 'custom') {
      const res = {};
      if (state.dateFrom) res.date_from = state.dateFrom;
      if (state.dateTo) res.date_to = state.dateTo;
      return res;
    }
    return {};
  }

  function hasActiveFilters() {
    return Boolean(state.q || state.userId || state.action || state.datePreset !== 'all');
  }

  async function fetchAudit(isNextPage = false) {
    const params = new URLSearchParams({ limit: String(state.limit) });
    if (state.q) params.set('q', state.q);
    if (state.userId) params.set('user_id', state.userId);
    if (state.action) params.set('action', state.action);

    const dateParams = getDateParams();
    if (dateParams.date_from) params.set('date_from', dateParams.date_from);
    if (dateParams.date_to) params.set('date_to', dateParams.date_to);

    if (isNextPage && state.cursor) {
      params.set('before_id', String(state.cursor));
    }

    return await apiFetch(`${AUDIT_PATH(GUILD_ID)}?${params.toString()}`);
  }

  try {
    const initialData = await fetchAudit(false);
    box.innerHTML = '';

    if (!initialData.entries.length && !hasActiveFilters()) {
      box.append(emptyState(t('tabsHistorial.emptyState')));
      return;
    }

    if (initialData.users && initialData.users.length) {
      state.users = initialData.users;
    }

    // Contenedor principal de Historial
    const container = el('div', { class: 'audit-container' });

    // 1. Buscador
    const searchInput = el('input', {
      type: 'search',
      class: 'audit-search-input',
      placeholder: t('tabsHistorial.searchPlaceholder'),
      'aria-label': t('tabsHistorial.searchAria'),
      value: state.q,
      oninput: () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          state.q = searchInput.value.trim();
          reloadPage();
        }, 280);
      },
    });

    const searchWrap = el('div', { class: 'audit-search-wrap' },
      el('span', { class: 'audit-search-icon', 'aria-hidden': 'true' }, icon('search')),
      searchInput
    );

    // 2. Selectores de Filtro
    const userSelect = el('select', {
      class: 'audit-select',
      'aria-label': t('tabsHistorial.filterUserAria'),
      onchange: () => {
        state.userId = userSelect.value;
        reloadPage();
      },
    }, el('option', { value: '' }, t('tabsHistorial.allUsers')));

    function updateUserOptions() {
      const currentVal = userSelect.value;
      userSelect.innerHTML = '';
      userSelect.append(el('option', { value: '' }, t('tabsHistorial.allUsers')));
      for (const u of state.users) {
        const opt = el('option', { value: String(u.user_id) }, u.user_name);
        if (String(u.user_id) === currentVal) opt.selected = true;
        userSelect.append(opt);
      }
    }
    updateUserOptions();

    const actionSelect = el('select', {
      class: 'audit-select',
      'aria-label': t('tabsHistorial.filterActionAria'),
      onchange: () => {
        state.action = actionSelect.value;
        reloadPage();
      },
    },
      el('option', { value: '' }, t('tabsHistorial.allActions')),
      el('optgroup', { label: t('tabsHistorial.groupContent') },
        el('option', { value: 'cat:contenido' }, t('tabsHistorial.optAllContent')),
        el('option', { value: 'frases.' }, t('tabsHistorial.optFrases')),
        el('option', { value: 'frase_packs.' }, t('tabsHistorial.optFrasePacks')),
        el('option', { value: 'triggers.' }, t('tabsHistorial.optTriggers')),
        el('option', { value: 'reactions.' }, t('tabsHistorial.optReactions'))
      ),
      el('optgroup', { label: t('tabsHistorial.groupChat') },
        el('option', { value: 'cat:chat' }, t('tabsHistorial.optAllChat')),
        el('option', { value: 'chat.' }, t('tabsHistorial.optChatSettings')),
        el('option', { value: 'channel_settings.' }, t('tabsHistorial.optChannelSettings')),
        el('option', { value: 'corpus.' }, t('tabsHistorial.optCorpus')),
        el('option', { value: 'exempt_' }, t('tabsHistorial.optExempt'))
      ),
      el('optgroup', { label: t('tabsHistorial.groupMultimedia') },
        el('option', { value: 'gifs.' }, t('tabsHistorial.optGifs'))
      ),
      el('optgroup', { label: t('tabsHistorial.groupEmbeds') },
        el('option', { value: 'embed' }, t('tabsHistorial.optEmbeds'))
      ),
      el('optgroup', { label: t('tabsHistorial.groupIntegrations') },
        el('option', { value: 'youtube.' }, t('tabsHistorial.optYoutube'))
      ),
      el('optgroup', { label: t('tabsHistorial.groupGeneral') },
        el('option', { value: 'style.' }, t('tabsHistorial.optStyle'))
      )
    );

    const customDateWrap = el('div', { class: 'audit-custom-dates', style: 'display:none' });
    const fromInput = el('input', {
      type: 'date',
      class: 'audit-date-input',
      title: t('tabsHistorial.dateFromTitle'),
      onchange: () => {
        state.dateFrom = fromInput.value;
        reloadPage();
      },
    });
    const toInput = el('input', {
      type: 'date',
      class: 'audit-date-input',
      title: t('tabsHistorial.dateToTitle'),
      onchange: () => {
        state.dateTo = toInput.value;
        reloadPage();
      },
    });
    customDateWrap.append(el('span', {}, t('tabsHistorial.dateFromLabel')), fromInput, el('span', {}, t('tabsHistorial.dateToLabel')), toInput);

    const dateSelect = el('select', {
      class: 'audit-select',
      'aria-label': t('tabsHistorial.filterDateAria'),
      onchange: () => {
        state.datePreset = dateSelect.value;
        customDateWrap.style.display = state.datePreset === 'custom' ? 'inline-flex' : 'none';
        if (state.datePreset !== 'custom') {
          state.dateFrom = '';
          state.dateTo = '';
          fromInput.value = '';
          toInput.value = '';
          reloadPage();
        }
      },
    },
      el('option', { value: 'all' }, t('tabsHistorial.dateAny')),
      el('option', { value: 'today' }, t('tabsHistorial.dateToday')),
      el('option', { value: 'yesterday' }, t('tabsHistorial.dateYesterday')),
      el('option', { value: '7d' }, t('tabsHistorial.date7d')),
      el('option', { value: '30d' }, t('tabsHistorial.date30d')),
      el('option', { value: 'custom' }, t('tabsHistorial.dateCustom'))
    );

    const filtersRow = el('div', { class: 'audit-filters-row' },
      userSelect,
      actionSelect,
      dateSelect,
      customDateWrap
    );

    const chipsRow = el('div', { class: 'audit-active-chips' });

    function renderActiveChips() {
      chipsRow.innerHTML = '';
      if (!hasActiveFilters()) {
        chipsRow.style.display = 'none';
        return;
      }
      chipsRow.style.display = 'flex';

      if (state.q) {
        chipsRow.append(createChip(t('tabsHistorial.chipText', { q: state.q }), () => {
          state.q = '';
          searchInput.value = '';
          reloadPage();
        }));
      }

      if (state.userId) {
        const u = state.users.find(x => String(x.user_id) === state.userId);
        const name = u ? u.user_name : state.userId;
        // Usuario: ${name}
        chipsRow.append(createChip(t('tabsHistorial.chipUser', { name }), () => {
          state.userId = '';
          userSelect.value = '';
          reloadPage();
        }));
      }

      if (state.action) {
        const opt = actionSelect.querySelector(`option[value="${state.action}"]`);
        const label = opt ? opt.textContent : state.action;
        chipsRow.append(createChip(t('tabsHistorial.chipAction', { label }), () => {
          state.action = '';
          actionSelect.value = '';
          reloadPage();
        }));
      }

      if (state.datePreset !== 'all') {
        const opt = dateSelect.querySelector(`option[value="${state.datePreset}"]`);
        const label = opt ? opt.textContent : state.datePreset;
        chipsRow.append(createChip(t('tabsHistorial.chipDate', { label }), () => {
          state.datePreset = 'all';
          dateSelect.value = 'all';
          state.dateFrom = '';
          state.dateTo = '';
          fromInput.value = '';
          toInput.value = '';
          customDateWrap.style.display = 'none';
          reloadPage();
        }));
      }

      const clearAllBtn = el('button', {
        type: 'button',
        class: 'audit-clear-btn',
        onclick: resetAllFilters,
      }, t('tabsHistorial.clearFilters'));
      chipsRow.append(clearAllBtn);
    }

    function createChip(text, onRemove) {
      return el('span', { class: 'audit-chip' },
        el('span', {}, text),
        el('button', {
          type: 'button',
          class: 'audit-chip-x',
          'aria-label': t('tabsHistorial.removeFilterAria', { text }),
          onclick: onRemove,
        }, icon('x'))
      );
    }

    function resetAllFilters() {
      state.q = '';
      state.userId = '';
      state.action = '';
      state.datePreset = 'all';
      state.dateFrom = '';
      state.dateTo = '';
      searchInput.value = '';
      userSelect.value = '';
      actionSelect.value = '';
      dateSelect.value = 'all';
      fromInput.value = '';
      toInput.value = '';
      customDateWrap.style.display = 'none';
      reloadPage();
    }

    const toolbar = el('div', { class: 'audit-toolbar' },
      searchWrap,
      filtersRow,
      chipsRow
    );

    const listWrap = el('div', { class: 'audit-list-wrap' });
    const list = el('ul', { class: 'item-list' });
    const footer = el('div', { class: 'gif-more-wrap' });

    listWrap.append(list, footer);
    container.append(toolbar, listWrap);
    box.append(formGroup(t('tabsHistorial.sectionTitle'), container));

    function renderEntries(entries, append = false) {
      if (!append) list.innerHTML = '';
      for (const entry of entries) {
        list.append(entryRow(entry));
      }
    }

    function renderFooter() {
      footer.innerHTML = '';
      if (!state.hasMore) {
        footer.append(el('span', { class: 'dim' }, t('tabsHistorial.noMore')));
        return;
      }
      const btn = el('button', {
        class: 'btn btn-secondary',
        onclick: () => loadMore(btn),
      }, t('tabsHistorial.loadMore'));
      footer.append(btn);
    }

    async function loadMore(btn) {
      btn.disabled = true;
      btn.textContent = t('tabsHistorial.loading');
      try {
        const more = await fetchAudit(true);
        renderEntries(more.entries, true);
        if (more.entries.length) {
          state.cursor = more.entries[more.entries.length - 1].id;
        }
        state.hasMore = more.has_more;
        renderFooter();
      } catch (e) {
        toast(e.message, 'err');
        btn.disabled = false;
        btn.textContent = t('tabsHistorial.loadMore');
      }
    }

    async function reloadPage() {
      renderActiveChips();
      list.innerHTML = '';
      footer.innerHTML = '';
      list.append(spinner());

      try {
        state.cursor = null;
        const data = await fetchAudit(false);
        list.innerHTML = '';

        if (data.users && data.users.length && !state.users.length) {
          state.users = data.users;
          updateUserOptions();
        }

        if (!data.entries.length) {
          if (hasActiveFilters()) {
            list.append(
              el('div', { class: 'audit-empty-filtered' },
                el('p', { class: 'dim' }, t('tabsHistorial.noMatchFiltered')),
                el('button', {
                  type: 'button',
                  class: 'btn btn-secondary btn-sm',
                  onclick: resetAllFilters,
                }, t('tabsHistorial.clearFilters'))
              )
            );
          } else {
            list.append(emptyState(t('tabsHistorial.emptyState')));
          }
          return;
        }

        renderEntries(data.entries, false);
        state.cursor = data.entries[data.entries.length - 1].id;
        state.hasMore = data.has_more;
        renderFooter();
      } catch (e) {
        list.innerHTML = '';
        renderError(list, e);
      }
    }

    // Renderizado de la carga inicial
    renderActiveChips();
    renderEntries(initialData.entries, false);
    if (initialData.entries.length) {
      state.cursor = initialData.entries[initialData.entries.length - 1].id;
      state.hasMore = initialData.has_more;
    }
    renderFooter();
  } catch (e) {
    renderError(box, e);
  }
}
