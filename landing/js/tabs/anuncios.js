// Módulo de Gestión de Anuncios Programados de Purgito.
// Programador de mensajes de texto con resolución dinámica de variables.

import { apiFetch } from '/js/core/api.js';
import {
  el, spinner, renderError, toast, autoGrow, icon,
} from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, channelSelect, content } from '/js/panel-shell.js';
import { mdToNodes } from '/js/core/markdown.js';
import { t, addStrings } from '/js/core/i18n.js';

addStrings({
  es: {
    'tabsAnuncios.title': 'Anuncios',
    'tabsAnuncios.subtitle': 'Automatiza mensajes para mantener informado tu servidor.',
    'tabsAnuncios.createBtn': '+ Crear anuncio',
    'tabsAnuncios.createFirstBtn': '+ Crear tu primer anuncio',
    'tabsAnuncios.emptyTitle': 'No hay anuncios configurados',
    'tabsAnuncios.emptyDesc': 'Crea publicaciones automáticas periódicas o diarias para avisar a tus miembros.',
    'tabsAnuncios.quotaUsed': 'anuncios utilizados',
    'tabsAnuncios.quotaLimitReached': 'Has alcanzado el límite de anuncios para este servidor.',
    'tabsAnuncios.upgradePrompt': 'Pasa a Purgito Premium para programar hasta 10 anuncios.',
    'tabsAnuncios.statusActive': 'Activo',
    'tabsAnuncios.statusInactive': 'Inactivo',
    'tabsAnuncios.cadenceInterval': 'Cada {minutes} minutos',
    'tabsAnuncios.cadenceDaily': 'Todos los días · {time}',
    'tabsAnuncios.channelMissing': '⚠ Canal no disponible',
    'tabsAnuncios.noPerms': '⚠ Purgito no puede publicar aquí',
    'tabsAnuncios.noPermsWarning': '⚠ Purgito no tiene permiso para enviar mensajes en ese canal.',
    'tabsAnuncios.autoDeleteBadge': '⏱ Auto-borrado: {seconds}s',
    'tabsAnuncios.lastSent': 'Último envío:',
    'tabsAnuncios.neverSent': 'Aún no enviado',
    'tabsAnuncios.editBtn': 'Editar',
    'tabsAnuncios.deleteBtn': 'Eliminar',
    'tabsAnuncios.deleteConfirm': '¿Seguro que deseas eliminar este anuncio?',
    'tabsAnuncios.deleteSuccess': 'Anuncio eliminado correctamente',
    'tabsAnuncios.backToList': '← Volver a la lista de anuncios',
    'tabsAnuncios.createTitle': 'Nuevo anuncio programado',
    'tabsAnuncios.editTitle': 'Editar anuncio',
    'tabsAnuncios.sectionSchedule': 'Programación',
    'tabsAnuncios.channelLabel': 'Canal de destino',
    'tabsAnuncios.channelSelectPlaceholder': 'Elige un canal…',
    'tabsAnuncios.sendLabel': 'Enviar',
    'tabsAnuncios.cadenceLabel': 'Tipo de programación',
    'tabsAnuncios.modeInterval': 'Cada cierto tiempo',
    'tabsAnuncios.modeDaily': 'A una hora fija',
    'tabsAnuncios.intervalInputLabel': 'Cada',
    'tabsAnuncios.intervalMinutesUnit': 'minutos',
    'tabsAnuncios.intervalHint': 'Se enviará cada {minutes} minutos.',
    'tabsAnuncios.timeInputLabel': 'Todos los días a las',
    'tabsAnuncios.timeHint': 'Se enviará todos los días a las {time}.',
    'tabsAnuncios.sectionMessage': 'Mensaje',
    'tabsAnuncios.messageLabel': 'Mensaje',
    'tabsAnuncios.messagePlaceholder': 'Escribe el mensaje que Purgito publicará automáticamente…',
    'tabsAnuncios.messageCounter': '{count} / 2000',
    'tabsAnuncios.insertVarBtn': 'Insertar variable',
    'tabsAnuncios.varsTitle': 'Variables disponibles',
    'tabsAnuncios.varsSubtitle': 'Haz clic en una variable para insertarla en la posición del cursor.',
    'tabsAnuncios.varsSearchPlaceholder': 'Buscar variables…',
    'tabsAnuncios.varExample': 'Ejemplo:',
    'tabsAnuncios.varsCopied': 'Variable {var} copiada al portapapeles',
    'tabsAnuncios.varsInserted': 'Variable {var} insertada',
    'tabsAnuncios.sectionPreview': 'Vista previa',
    'tabsAnuncios.previewTitle': 'Vista previa',
    'tabsAnuncios.previewHeader': 'Purgito',
    'tabsAnuncios.previewBotTag': 'BOT',
    'tabsAnuncios.previewToday': 'HOY',
    'tabsAnuncios.sectionOptions': 'Opciones',
    'tabsAnuncios.advancedOptions': 'Opciones',
    'tabsAnuncios.autoDeleteLabel': 'Auto-borrar el mensaje',
    'tabsAnuncios.autoDeleteAfter': 'Después de',
    'tabsAnuncios.autoDeleteSecondsUnit': 'segundos',
    'tabsAnuncios.autoDeleteHint': 'El anuncio se eliminará automáticamente después de {seconds} segundos.',
    'tabsAnuncios.saveBtn': 'Guardar anuncio',
    'tabsAnuncios.saving': 'Guardando…',
    'tabsAnuncios.savedSuccess': 'Anuncio guardado correctamente',
    'tabsAnuncios.cancelBtn': 'Cancelar',
    'tabsAnuncios.noChannelSelected': 'Debes seleccionar un canal para el anuncio',
    'tabsAnuncios.emptyMessage': 'El mensaje del anuncio no puede estar vacío',
  },
  en: {
    'tabsAnuncios.title': 'Announcements',
    'tabsAnuncios.subtitle': 'Automate scheduled messages to keep your server informed.',
    'tabsAnuncios.createBtn': '+ Create announcement',
    'tabsAnuncios.createFirstBtn': '+ Create your first announcement',
    'tabsAnuncios.emptyTitle': 'No announcements configured',
    'tabsAnuncios.emptyDesc': 'Create periodic or daily automatic posts to notify your members.',
    'tabsAnuncios.quotaUsed': 'announcements used',
    'tabsAnuncios.quotaLimitReached': 'You have reached the announcement limit for this server.',
    'tabsAnuncios.upgradePrompt': 'Upgrade to Purgito Premium to schedule up to 10 announcements.',
    'tabsAnuncios.statusActive': 'Active',
    'tabsAnuncios.statusInactive': 'Inactive',
    'tabsAnuncios.cadenceInterval': 'Every {minutes} minutes',
    'tabsAnuncios.cadenceDaily': 'Every day · {time}',
    'tabsAnuncios.channelMissing': '⚠ Channel unavailable',
    'tabsAnuncios.noPerms': '⚠ Purgito cannot post here',
    'tabsAnuncios.noPermsWarning': '⚠ Purgito does not have permission to send messages in this channel.',
    'tabsAnuncios.autoDeleteBadge': '⏱ Auto-delete: {seconds}s',
    'tabsAnuncios.lastSent': 'Last sent:',
    'tabsAnuncios.neverSent': 'Never sent yet',
    'tabsAnuncios.editBtn': 'Edit',
    'tabsAnuncios.deleteBtn': 'Delete',
    'tabsAnuncios.deleteConfirm': 'Are you sure you want to delete this announcement?',
    'tabsAnuncios.deleteSuccess': 'Announcement deleted successfully',
    'tabsAnuncios.backToList': '← Back to announcements list',
    'tabsAnuncios.createTitle': 'New scheduled announcement',
    'tabsAnuncios.editTitle': 'Edit announcement',
    'tabsAnuncios.sectionSchedule': 'Schedule',
    'tabsAnuncios.channelLabel': 'Destination channel',
    'tabsAnuncios.channelSelectPlaceholder': 'Choose a channel…',
    'tabsAnuncios.sendLabel': 'Send',
    'tabsAnuncios.cadenceLabel': 'Schedule type',
    'tabsAnuncios.modeInterval': 'Every interval',
    'tabsAnuncios.modeDaily': 'Daily at a fixed time',
    'tabsAnuncios.intervalInputLabel': 'Every',
    'tabsAnuncios.intervalMinutesUnit': 'minutes',
    'tabsAnuncios.intervalHint': 'Will be sent every {minutes} minutes.',
    'tabsAnuncios.timeInputLabel': 'Every day at',
    'tabsAnuncios.timeHint': 'Will be sent every day at {time}.',
    'tabsAnuncios.sectionMessage': 'Message',
    'tabsAnuncios.messageLabel': 'Message',
    'tabsAnuncios.messagePlaceholder': 'Write the message that Purgito will automatically publish…',
    'tabsAnuncios.messageCounter': '{count} / 2000',
    'tabsAnuncios.insertVarBtn': 'Insert variable',
    'tabsAnuncios.varsTitle': 'Available variables',
    'tabsAnuncios.varsSubtitle': 'Click any variable to insert it at cursor position.',
    'tabsAnuncios.varsSearchPlaceholder': 'Search variables…',
    'tabsAnuncios.varExample': 'Example:',
    'tabsAnuncios.varsCopied': 'Variable {var} copied to clipboard',
    'tabsAnuncios.varsInserted': 'Variable {var} inserted',
    'tabsAnuncios.sectionPreview': 'Preview',
    'tabsAnuncios.previewTitle': 'Preview',
    'tabsAnuncios.previewHeader': 'Purgito',
    'tabsAnuncios.previewBotTag': 'BOT',
    'tabsAnuncios.previewToday': 'TODAY',
    'tabsAnuncios.sectionOptions': 'Options',
    'tabsAnuncios.advancedOptions': 'Options',
    'tabsAnuncios.autoDeleteLabel': 'Auto-delete message',
    'tabsAnuncios.autoDeleteAfter': 'After',
    'tabsAnuncios.autoDeleteSecondsUnit': 'seconds',
    'tabsAnuncios.autoDeleteHint': 'The announcement will be deleted automatically after {seconds} seconds.',
    'tabsAnuncios.saveBtn': 'Save announcement',
    'tabsAnuncios.saving': 'Saving…',
    'tabsAnuncios.savedSuccess': 'Announcement saved successfully',
    'tabsAnuncios.cancelBtn': 'Cancel',
    'tabsAnuncios.noChannelSelected': 'You must select a destination channel',
    'tabsAnuncios.emptyMessage': 'Announcement message cannot be empty',
  },
});

const DEFAULT_ANNOUNCEMENT_VARIABLES = [
  { name: 'server_name', category: 'server', description: 'Nombre del servidor de Discord.', example: 'Mi Servidor' },
  { name: 'server_id', category: 'server', description: 'ID numérico de Discord del servidor.', example: '123456789012345678' },
  { name: 'server_membercount', category: 'server', description: 'Cantidad total de miembros del servidor.', example: '1.284' },
  { name: 'server_membercount_ordinal', category: 'server', description: 'Número de miembro ordinal (ej. #1.284).', example: '#1.284' },
  { name: 'server_icon', category: 'server', description: 'URL del icono del servidor.', example: 'https://cdn.discordapp.com/icons/icon.png' },
  { name: 'server_owner', category: 'server', description: 'Nombre del dueño del servidor.', example: 'Owner' },
  { name: 'server_owner_id', category: 'server', description: 'ID numérico del dueño del servidor.', example: '111222333444555666' },
  { name: 'server_created_at', category: 'server', description: 'Fecha de creación del servidor.', example: '10 de marzo de 2020' },
  { name: 'server_rolecount', category: 'server', description: 'Cantidad de roles creados en el servidor.', example: '42' },
  { name: 'server_channelcount', category: 'server', description: 'Cantidad total de canales del servidor.', example: '28' },
  { name: 'server_boostlevel', category: 'server', description: 'Nivel de boost del servidor (0, 1, 2 o 3).', example: '2' },
  { name: 'server_boostcount', category: 'server', description: 'Cantidad total de mejoras (boosts) del servidor.', example: '9' },
  { name: 'channel', category: 'channel', description: 'Mención del canal donde se envía el mensaje.', example: '#general' },
  { name: 'channel_name', category: 'channel', description: 'Nombre del canal donde se envía el mensaje.', example: 'general' },
  { name: 'channel_id', category: 'channel', description: 'ID numérico del canal.', example: '555666777888999000' },
  { name: 'date', category: 'date', description: 'Fecha actual del evento.', example: '21 de agosto de 2026' },
];

function resolvePreviewText(text, channelName) {
  if (!text) return '';
  const now = new Date();
  const dateStr = now.toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' });
  const map = {
    server_name: 'Mi Servidor',
    server_id: '123456789012345678',
    server_membercount: '1.284',
    server_membercount_ordinal: '#1.284',
    server_icon: 'https://cdn.discordapp.com/embed/avatars/0.png',
    server_owner: 'Owner',
    server_owner_id: '111222333444555666',
    server_created_at: '10 de marzo de 2020',
    server_rolecount: '25',
    server_channelcount: '18',
    server_boostlevel: '1',
    server_boostcount: '4',
    channel: channelName ? (channelName.startsWith('#') ? channelName : '#' + channelName) : '#general',
    channel_name: channelName ? channelName.replace(/^#/, '') : 'general',
    channel_id: '555666777888999000',
    date: dateStr,
  };
  return text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key) => {
    return map[key] !== undefined ? map[key] : match;
  });
}

export async function loadAnunciosTab() {
  const myGuild = GUILD_ID;
  const box = content();
  box.innerHTML = '';
  box.append(spinner());

  try {
    const [anunciosData, channelsData] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/anuncios`),
      getChannels(),
    ]);

    if (myGuild !== GUILD_ID) return;
    const channels = Array.isArray(channelsData) ? channelsData : (channelsData.channels || []);
    renderAnunciosManager(box, anunciosData, channels);
  } catch (err) {
    if (myGuild !== GUILD_ID) return;
    renderError(box, err);
  }
}

function renderAnunciosManager(container, initialData, channels) {
  container.innerHTML = '';

  let currentView = 'list'; // 'list' | 'editor'
  let editingAnnouncement = null;
  let announcementsList = initialData.announcements || [];
  let quotaCount = initialData.count !== undefined ? initialData.count : announcementsList.length;
  let quotaMax = initialData.max || 3;
  let isPremium = !!initialData.is_premium;
  const availableVariables = initialData.variables && initialData.variables.length
    ? initialData.variables
    : DEFAULT_ANNOUNCEMENT_VARIABLES;

  const shellWrap = el('div', { class: 'anuncios-manager-shell' });
  container.append(shellWrap);

  function refresh() {
    shellWrap.innerHTML = '';
    if (currentView === 'list') {
      renderList();
    } else {
      renderEditor();
    }
  }

  // ----------------------------------------------------
  // LIST VIEW
  // ----------------------------------------------------
  function renderList() {
    const limitReached = quotaCount >= quotaMax;

    const quotaBadge = el('span', {
      class: 'badge ' + (limitReached ? 'badge-warn' : 'badge-dim'),
    }, `${quotaCount} / ${quotaMax} ${t('tabsAnuncios.quotaUsed')}`);

    const header = el('div', { class: 'tab-header tab-header-with-actions' },
      el('div', { class: 'tab-header-text' },
        el('h1', {}, el('span', { class: 'nav-icon' }, icon('layout')), t('tabsAnuncios.title')),
        el('p', { class: 'dim' }, t('tabsAnuncios.subtitle'))
      ),
      el('div', { class: 'tab-header-actions' },
        quotaBadge,
        el('button', {
          type: 'button',
          class: 'btn btn-primary',
          disabled: limitReached,
          title: limitReached ? t('tabsAnuncios.quotaLimitReached') : t('tabsAnuncios.createBtn'),
          onclick: () => {
            editingAnnouncement = null;
            currentView = 'editor';
            refresh();
          },
        }, t('tabsAnuncios.createBtn'))
      )
    );

    shellWrap.append(header);

    if (limitReached && !isPremium) {
      const upgradeNotice = el('div', { class: 'card quota-upgrade-card' },
        el('div', { class: 'upgrade-card-content' },
          el('span', { class: 'upgrade-icon' }, icon('star')),
          el('div', {},
            el('strong', {}, t('tabsAnuncios.quotaLimitReached')),
            el('p', { class: 'dim text-sm' }, t('tabsAnuncios.upgradePrompt'))
          )
        )
      );
      shellWrap.append(upgradeNotice);
    }

    if (!announcementsList.length) {
      const emptyBox = el('div', { class: 'card empty-state-card' },
        el('div', { class: 'empty-icon-wrap' }, icon('layout')),
        el('h3', {}, t('tabsAnuncios.emptyTitle')),
        el('p', { class: 'dim' }, t('tabsAnuncios.emptyDesc')),
        el('button', {
          type: 'button',
          class: 'btn btn-primary',
          disabled: limitReached,
          onclick: () => {
            editingAnnouncement = null;
            currentView = 'editor';
            refresh();
          },
        }, t('tabsAnuncios.createFirstBtn'))
      );
      shellWrap.append(emptyBox);
      return;
    }

    // Grid of cards
    const listGrid = el('div', { class: 'anuncios-cards-grid' });

    for (const ann of announcementsList) {
      const ch = channels.find(c => String(c.id) === String(ann.channel_id));
      const channelLabel = ch ? '#' + ch.name : t('tabsAnuncios.channelMissing');
      const isChannelError = !ch;

      // Cadence description
      let cadenceText = '';
      if (ann.mode === 'interval') {
        cadenceText = t('tabsAnuncios.cadenceInterval', { minutes: ann.interval_minutes || 30 });
      } else {
        const hh = String(ann.hour || 0).padStart(2, '0');
        const mm = String(ann.minute || 0).padStart(2, '0');
        cadenceText = t('tabsAnuncios.cadenceDaily', { time: `${hh}:${mm}` });
      }

      // Title or snippet - 1 line preview
      let titleSnippet = ann.message || '';
      if (!titleSnippet && ann.embed_json) {
        try {
          const parsed = JSON.parse(ann.embed_json);
          if (Array.isArray(parsed) && parsed[0] && (parsed[0].title || parsed[0].description)) {
            titleSnippet = parsed[0].title || parsed[0].description;
          } else if (parsed && parsed.embeds && parsed.embeds[0] && (parsed.embeds[0].title || parsed.embeds[0].description)) {
            titleSnippet = parsed.embeds[0].title || parsed.embeds[0].description;
          } else if (parsed && Array.isArray(parsed.blocks) && parsed.blocks[0]) {
            const b = parsed.blocks[0];
            titleSnippet = b.title || b.content || b.text || '';
          }
        } catch (e) {
          // ignore
        }
      }
      if (!titleSnippet) titleSnippet = `Anuncio #${ann.id}`;
      titleSnippet = titleSnippet.replace(/\s+/g, ' ').trim();

      const card = el('div', { class: 'anuncio-manage-card card' },
        el('div', { class: 'anuncio-card-header' },
          el('div', { class: 'anuncio-card-title', title: titleSnippet },
            el('span', { class: 'anuncio-type-icon' }, icon('chat')),
            el('strong', { class: 'anuncio-title-text' }, titleSnippet)
          ),
          el('div', { class: 'anuncio-card-badges' },
            el('span', { class: 'badge badge-ok' }, `● ${t('tabsAnuncios.statusActive')}`)
          )
        ),
        el('div', { class: 'anuncio-card-body' },
          el('div', { class: 'anuncio-meta-row' },
            el('span', { class: 'meta-item ' + (isChannelError ? 'meta-error' : '') },
              icon('chat'),
              el('span', {}, channelLabel)
            ),
            el('span', { class: 'meta-item' },
              icon('history'),
              el('span', {}, cadenceText)
            ),
            ann.delete_after_seconds ? el('span', { class: 'meta-item' },
              icon('trash'),
              el('span', {}, t('tabsAnuncios.autoDeleteBadge', { seconds: ann.delete_after_seconds }))
            ) : null
          ),
          ann.last_sent_at ? el('div', { class: 'anuncio-last-sent dim text-xs' },
            `${t('tabsAnuncios.lastSent')} ${ann.last_sent_at}`
          ) : null
        ),
        el('div', { class: 'anuncio-card-actions' },
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            onclick: () => {
              editingAnnouncement = ann;
              currentView = 'editor';
              refresh();
            },
          }, icon('sliders'), t('tabsAnuncios.editBtn')),
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-danger-soft btn-sm',
            onclick: async () => {
              if (!confirm(t('tabsAnuncios.deleteConfirm'))) return;
              try {
                await apiFetch(`/api/server/${GUILD_ID}/anuncios/${ann.id}`, { method: 'DELETE' });
                announcementsList = announcementsList.filter(a => a.id !== ann.id);
                quotaCount = Math.max(0, quotaCount - 1);
                toast(t('tabsAnuncios.deleteSuccess'), 'ok');
                refresh();
              } catch (err) {
                toast(err.message || 'Error al eliminar', 'err');
              }
            },
          }, icon('trash'), t('tabsAnuncios.deleteBtn'))
        )
      );

      listGrid.append(card);
    }

    shellWrap.append(listGrid);
  }

  // ----------------------------------------------------
  // EDITOR VIEW
  // ----------------------------------------------------
  function renderEditor() {
    const isEditing = !!editingAnnouncement;
    const ann = editingAnnouncement || {
      channel_id: channels.length ? channels[0].id : '',
      mode: 'interval',
      interval_minutes: 30,
      hour: 8,
      minute: 0,
      message: '',
      delete_after_seconds: null,
    };

    let selectedChannelId = ann.channel_id ? String(ann.channel_id) : (channels.length ? String(channels[0].id) : '');
    let scheduleMode = ann.mode || 'interval';
    let intervalMinutes = ann.interval_minutes || 30;
    let dailyHour = ann.hour !== undefined && ann.hour !== null ? ann.hour : 8;
    let dailyMinute = ann.minute !== undefined && ann.minute !== null ? ann.minute : 0;
    let textMessage = ann.message || '';
    if (!textMessage && ann.embed_json) {
      try {
        const parsed = JSON.parse(ann.embed_json);
        if (Array.isArray(parsed) && parsed[0]) {
          textMessage = parsed[0].description || parsed[0].title || '';
        } else if (parsed && parsed.embeds && parsed.embeds[0]) {
          textMessage = parsed.embeds[0].description || parsed.embeds[0].title || '';
        } else if (parsed && Array.isArray(parsed.blocks) && parsed.blocks[0]) {
          textMessage = parsed.blocks[0].content || parsed.blocks[0].text || '';
        }
      } catch (e) {
        // ignore
      }
    }
    let enableAutoDelete = !!ann.delete_after_seconds;
    let autoDeleteSeconds = ann.delete_after_seconds || 60;

    // Navigation Header
    const backBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-sm',
      onclick: () => {
        currentView = 'list';
        refresh();
      },
    }, t('tabsAnuncios.backToList'));

    const header = el('div', { class: 'tab-header tab-header-editor' },
      backBtn,
      el('h1', { style: 'margin-top: 10px;' },
        el('span', { class: 'nav-icon' }, icon('layout')),
        isEditing ? `${t('tabsAnuncios.editTitle')} #${ann.id}` : t('tabsAnuncios.createTitle')
      )
    );

    // ── 1. Sección: Programación (Canal + Cuándo agrupados sin divisores) ──
    const channelSel = channelSelect(channels, selectedChannelId, t('tabsAnuncios.channelSelectPlaceholder'));
    const channelWarning = el('p', {
      class: 'form-error-msg',
      style: 'display: none; margin: 4px 0 0 0;',
    }, t('tabsAnuncios.noPermsWarning'));

    function checkChannelPerms() {
      const ch = channels.find(c => String(c.id) === String(selectedChannelId));
      channelWarning.style.display = (ch && ch.can_send === false) ? 'block' : 'none';
    }
    channelSel.onchange = () => {
      selectedChannelId = channelSel.value;
      checkChannelPerms();
      updatePreview();
    };
    checkChannelPerms();

    const channelGroup = el('div', { class: 'anuncio-field-group' },
      el('label', { class: 'anuncio-field-label' }, t('tabsAnuncios.channelLabel')),
      channelSel,
      channelWarning
    );

    const intervalPill = el('button', {
      type: 'button',
      class: 'mode-pill' + (scheduleMode === 'interval' ? ' active' : ''),
      onclick: () => {
        scheduleMode = 'interval';
        refreshScheduleControls();
      },
    }, t('tabsAnuncios.modeInterval'));

    const dailyPill = el('button', {
      type: 'button',
      class: 'mode-pill' + (scheduleMode === 'daily' ? ' active' : ''),
      onclick: () => {
        scheduleMode = 'daily';
        refreshScheduleControls();
      },
    }, t('tabsAnuncios.modeDaily'));

    const scheduleControlsWrap = el('div', { class: 'anuncio-schedule-controls' });

    function refreshScheduleControls() {
      intervalPill.className = 'mode-pill' + (scheduleMode === 'interval' ? ' active' : '');
      dailyPill.className = 'mode-pill' + (scheduleMode === 'daily' ? ' active' : '');
      scheduleControlsWrap.innerHTML = '';

      if (scheduleMode === 'interval') {
        const intervalInp = el('input', {
          type: 'number',
          min: '5',
          max: '1440',
          class: 'form-control anuncio-interval-input',
          value: String(intervalMinutes),
        });
        const hint = el('p', { class: 'dim text-sm anuncio-field-hint' },
          t('tabsAnuncios.intervalHint', { minutes: intervalMinutes })
        );

        const presets = [15, 30, 60, 120, 360, 720, 1440];
        const presetChips = el('div', { class: 'preset-chips' });

        function updateChipsActive() {
          presetChips.querySelectorAll('button').forEach((btn, idx) => {
            btn.classList.toggle('active', presets[idx] === intervalMinutes);
          });
        }

        presets.forEach(m => {
          presetChips.append(el('button', {
            type: 'button',
            class: 'category-tab-btn' + (intervalMinutes === m ? ' active' : ''),
            onclick: () => {
              intervalMinutes = m;
              intervalInp.value = String(m);
              hint.textContent = t('tabsAnuncios.intervalHint', { minutes: m });
              updateChipsActive();
            },
          }, m >= 60 ? `${m / 60}h` : `${m}m`));
        });

        intervalInp.oninput = () => {
          const val = parseInt(intervalInp.value, 10);
          if (!isNaN(val)) intervalMinutes = val;
          hint.textContent = t('tabsAnuncios.intervalHint', { minutes: intervalMinutes });
          updateChipsActive();
        };

        const inputRow = el('div', { class: 'anuncio-input-row' },
          el('span', { class: 'anuncio-input-prefix' }, t('tabsAnuncios.intervalInputLabel')),
          intervalInp,
          el('span', { class: 'anuncio-input-suffix' }, t('tabsAnuncios.intervalMinutesUnit'))
        );

        scheduleControlsWrap.append(inputRow, presetChips, hint);
      } else {
        const hh = String(dailyHour).padStart(2, '0');
        const mm = String(dailyMinute).padStart(2, '0');
        const timeInp = el('input', {
          type: 'time',
          class: 'form-control anuncio-time-input',
          value: `${hh}:${mm}`,
        });
        const hint = el('p', { class: 'dim text-sm anuncio-field-hint' },
          t('tabsAnuncios.timeHint', { time: `${hh}:${mm}` })
        );

        timeInp.oninput = () => {
          const parts = timeInp.value.split(':');
          if (parts.length === 2) {
            dailyHour = parseInt(parts[0], 10);
            dailyMinute = parseInt(parts[1], 10);
            hint.textContent = t('tabsAnuncios.timeHint', { time: timeInp.value });
          }
        };

        const inputRow = el('div', { class: 'anuncio-input-row' },
          el('span', { class: 'anuncio-input-prefix' }, t('tabsAnuncios.timeInputLabel')),
          timeInp
        );

        scheduleControlsWrap.append(inputRow, hint);
      }
    }

    refreshScheduleControls();

    const sendGroup = el('div', { class: 'anuncio-field-group' },
      el('label', { class: 'anuncio-field-label' }, t('tabsAnuncios.sendLabel')),
      el('div', { class: 'event-mode-pills' }, intervalPill, dailyPill),
      scheduleControlsWrap
    );

    const scheduleSection = el('div', { class: 'anuncio-section' },
      el('div', { class: 'anuncio-section-header' },
        el('span', { class: 'anuncio-section-title' }, icon('clock'), t('tabsAnuncios.sectionSchedule'))
      ),
      el('div', { class: 'anuncio-section-fields' },
        channelGroup,
        sendGroup
      )
    );

    // ── 2. Sección: Mensaje (Elemento dominante, amplio y cómodo) ─────
    const msgTxt = el('textarea', {
      class: 'form-control autogrow anuncio-textarea',
      placeholder: t('tabsAnuncios.messagePlaceholder'),
      spellcheck: 'false',
    });
    msgTxt.value = textMessage;

    const charCounter = el('span', { class: 'char-counter' },
      t('tabsAnuncios.messageCounter', { count: textMessage.length })
    );

    function updateCounter() {
      charCounter.textContent = t('tabsAnuncios.messageCounter', { count: textMessage.length });
      charCounter.className = 'char-counter' + (textMessage.length > 2000 ? ' over' : '');
    }

    msgTxt.oninput = () => {
      textMessage = msgTxt.value;
      autoGrow(msgTxt);
      updateCounter();
      updatePreview();
    };

    // Modal de variables
    function openVariablesModal(targetInput) {
      const existingModal = document.getElementById('purg-variables-modal-backdrop');
      if (existingModal) existingModal.remove();
      const target = targetInput || msgTxt;

      const searchInput = el('input', {
        type: 'search',
        class: 'form-control form-control-sm var-modal-search',
        placeholder: t('tabsAnuncios.varsSearchPlaceholder'),
        autofocus: true,
      });
      const chipsGrid = el('div', { class: 'var-modal-grid' });

      function renderChips() {
        chipsGrid.innerHTML = '';
        const q = searchInput.value.toLowerCase().trim();
        const filtered = availableVariables.filter(v =>
          !q || v.name.toLowerCase().includes(q) || (v.description || '').toLowerCase().includes(q)
        );
        for (const v of filtered) {
          const varTag = `{${v.name}}`;
          chipsGrid.append(el('button', {
            type: 'button',
            class: 'var-chip-compact',
            title: `${v.description || ''} (${t('tabsAnuncios.varExample')} ${v.example || ''})`,
            onclick: () => {
              if (target && typeof target.value === 'string') {
                const start = target.selectionStart ?? target.value.length;
                const end = target.selectionEnd ?? target.value.length;
                target.value = target.value.slice(0, start) + varTag + target.value.slice(end);
                target.selectionStart = target.selectionEnd = start + varTag.length;
                if (typeof target.dispatchEvent === 'function' && typeof Event !== 'undefined') {
                  try { target.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                }
                if (typeof target.oninput === 'function') {
                  target.oninput();
                }
                target.focus();
                toast(t('tabsAnuncios.varsInserted', { var: varTag }), 'ok');
              } else if (navigator.clipboard) {
                navigator.clipboard.writeText(varTag);
                toast(t('tabsAnuncios.varsCopied', { var: varTag }), 'ok');
              }
              closeModal();
            },
          }, el('code', { class: 'var-tag' }, varTag), el('span', { class: 'var-desc' }, v.description || '')));
        }
      }
      searchInput.oninput = renderChips;
      renderChips();

      function closeModal() {
        document.removeEventListener('keydown', onKey);
        backdrop.remove();
      }
      function onKey(e) {
        if (e.key === 'Escape') closeModal();
      }
      document.addEventListener('keydown', onKey);

      const modalBox = el('div', { class: 'purg-variables-modal' },
        el('div', { class: 'var-modal-header' },
          el('div', { class: 'var-modal-title' }, icon('sparkle'), el('strong', {}, t('tabsAnuncios.varsTitle'))),
          el('button', { type: 'button', class: 'modal-close-btn', onclick: closeModal }, '✕')
        ),
        el('p', { class: 'dim text-xs', style: 'margin:0 0 10px 0;' }, t('tabsAnuncios.varsSubtitle')),
        searchInput, chipsGrid
      );
      const backdrop = el('div', {
        id: 'purg-variables-modal-backdrop',
        class: 'purg-modal-backdrop',
        onclick: (e) => { if (e.target === backdrop) closeModal(); },
      }, modalBox);
      document.body.append(backdrop);
      setTimeout(() => searchInput.focus(), 30);
    }

    const insertVarBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-xs btn-more-vars',
      onclick: () => openVariablesModal(msgTxt),
    }, icon('sparkle'), t('tabsAnuncios.insertVarBtn'));

    const textareaBar = el('div', { class: 'anuncio-textarea-bottom-bar' },
      insertVarBtn,
      charCounter
    );

    const messageSection = el('div', { class: 'anuncio-section' },
      el('div', { class: 'anuncio-section-header' },
        el('span', { class: 'anuncio-section-title' }, icon('chat'), t('tabsAnuncios.sectionMessage'))
      ),
      el('div', { class: 'anuncio-textarea-wrap' },
        msgTxt,
        textareaBar
      )
    );

    // ── 3. Sección: Opciones (Switch deslizante visible directamente) ──
    const autoDeleteToggleInput = el('input', {
      type: 'checkbox',
      checked: enableAutoDelete,
      onchange: () => {
        enableAutoDelete = autoDeleteToggleInput.checked;
        updateAutoDeleteVisibility();
      },
    });

    const autoDeleteSwitch = el('label', {
      class: 'switch-toggle',
      'aria-label': t('tabsAnuncios.autoDeleteLabel'),
    },
      autoDeleteToggleInput,
      el('span', { class: 'switch-slider' })
    );

    const autoDeleteSecsInp = el('input', {
      type: 'number',
      min: '1',
      max: '86400',
      class: 'form-control anuncio-autodelete-input',
      value: String(autoDeleteSeconds),
    });

    const autoDeleteHint = el('p', { class: 'dim text-sm anuncio-field-hint' },
      t('tabsAnuncios.autoDeleteHint', { seconds: autoDeleteSeconds })
    );

    const autoDeletePresets = [30, 60, 300, 600, 3600, 86400];
    const autoDeleteChips = el('div', { class: 'preset-chips' });

    function updateAutoDeleteChips() {
      autoDeleteChips.querySelectorAll('button').forEach((btn, idx) => {
        btn.classList.toggle('active', autoDeletePresets[idx] === autoDeleteSeconds);
      });
    }

    autoDeletePresets.forEach(s => {
      autoDeleteChips.append(el('button', {
        type: 'button',
        class: 'category-tab-btn' + (autoDeleteSeconds === s ? ' active' : ''),
        onclick: () => {
          autoDeleteSeconds = s;
          autoDeleteSecsInp.value = String(s);
          autoDeleteHint.textContent = t('tabsAnuncios.autoDeleteHint', { seconds: s });
          updateAutoDeleteChips();
        },
      }, s >= 3600 ? `${s / 3600}h` : (s >= 60 ? `${s / 60}m` : `${s}s`)));
    });

    autoDeleteSecsInp.oninput = () => {
      const val = parseInt(autoDeleteSecsInp.value, 10);
      if (!isNaN(val)) autoDeleteSeconds = val;
      autoDeleteHint.textContent = t('tabsAnuncios.autoDeleteHint', { seconds: autoDeleteSeconds });
      updateAutoDeleteChips();
    };

    const autoDeleteExpand = el('div', {
      class: 'anuncio-autodelete-expand' + (enableAutoDelete ? ' is-visible' : ''),
    },
      el('div', { class: 'anuncio-input-row' },
        el('span', { class: 'anuncio-input-prefix' }, t('tabsAnuncios.autoDeleteAfter')),
        autoDeleteSecsInp,
        el('span', { class: 'anuncio-input-suffix' }, t('tabsAnuncios.autoDeleteSecondsUnit'))
      ),
      autoDeleteChips,
      autoDeleteHint
    );

    function updateAutoDeleteVisibility() {
      if (enableAutoDelete) {
        autoDeleteExpand.classList.add('is-visible');
      } else {
        autoDeleteExpand.classList.remove('is-visible');
      }
    }

    const optionsSection = el('div', { class: 'anuncio-section' },
      el('div', { class: 'anuncio-section-header' },
        el('span', { class: 'anuncio-section-title' }, icon('sliders'), t('tabsAnuncios.sectionOptions'))
      ),
      el('div', { class: 'anuncio-options-content' },
        el('div', { class: 'anuncio-switch-row' },
          el('span', { class: 'anuncio-switch-label' }, t('tabsAnuncios.autoDeleteLabel')),
          autoDeleteSwitch
        ),
        autoDeleteExpand
      )
    );

    // ── 4. Acciones (Guardar / Cancelar) ─────────────────────────────
    const saveBtn = el('button', {
      type: 'button',
      class: 'btn btn-primary',
      onclick: async () => {
        if (!selectedChannelId) {
          toast(t('tabsAnuncios.noChannelSelected'), 'err');
          return;
        }

        const cleanMsg = textMessage.trim();
        if (!cleanMsg) {
          toast(t('tabsAnuncios.emptyMessage'), 'err');
          return;
        }

        saveBtn.disabled = true;
        saveBtn.textContent = t('tabsAnuncios.saving');

        try {
          const payload = {
            channel_id: selectedChannelId,
            mode: scheduleMode,
            message: cleanMsg,
            delete_after_seconds: enableAutoDelete ? autoDeleteSeconds : null,
          };

          if (scheduleMode === 'interval') {
            payload.interval_minutes = intervalMinutes;
          } else {
            payload.hour = dailyHour;
            payload.minute = dailyMinute;
          }

          if (isEditing) {
            const res = await apiFetch(`/api/server/${GUILD_ID}/anuncios/${ann.id}`, {
              method: 'PUT',
              body: JSON.stringify(payload),
            });
            const idx = announcementsList.findIndex(a => a.id === ann.id);
            if (idx >= 0 && res.announcement) {
              announcementsList[idx] = res.announcement;
            }
          } else {
            const res = await apiFetch(`/api/server/${GUILD_ID}/anuncios`, {
              method: 'POST',
              body: JSON.stringify(payload),
            });
            if (res.announcement) {
              announcementsList.push(res.announcement);
              quotaCount++;
            }
          }

          toast(t('tabsAnuncios.savedSuccess'), 'ok');
          currentView = 'list';
          refresh();
        } catch (err) {
          toast(err.message || 'Error al guardar anuncio', 'err');
          saveBtn.disabled = false;
          saveBtn.textContent = t('tabsAnuncios.saveBtn');
        }
      },
    }, t('tabsAnuncios.saveBtn'));

    const cancelBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary',
      onclick: () => {
        currentView = 'list';
        refresh();
      },
    }, t('tabsAnuncios.cancelBtn'));

    const actionsBar = el('div', { class: 'anuncio-actions-bar' },
      saveBtn,
      cancelBtn
    );

    // ── 5. Vista Previa (Columna derecha sticky en desktop) ──────────
    const previewContainer = el('div', { class: 'anuncio-preview-box' });

    function updatePreview() {
      previewContainer.innerHTML = '';

      const ch = channels.find(c => String(c.id) === String(selectedChannelId));
      const channelName = ch ? '#' + ch.name : '#general';
      const resolvedText = resolvePreviewText(textMessage || '', channelName);

      const msgHeader = el('div', { class: 'd-msg-header' },
        el('img', { src: '/assets/icon.png', alt: 'Purgito', class: 'd-msg-avatar' }),
        el('div', { class: 'd-msg-meta' },
          el('span', { class: 'd-msg-author' }, t('tabsAnuncios.previewHeader')),
          el('span', { class: 'd-msg-bot' }, t('tabsAnuncios.previewBotTag')),
          el('span', { class: 'd-msg-time' }, t('tabsAnuncios.previewToday'))
        )
      );

      const msgBodyNodes = resolvedText
        ? mdToNodes(resolvedText)
        : [el('span', { class: 'd-msg-placeholder' }, t('tabsAnuncios.messagePlaceholder'))];

      const msgBody = el('div', { class: 'd-msg-body' },
        el('div', { class: 'd-msg-text' }, ...msgBodyNodes)
      );

      const discordCard = el('div', { class: 'd-message-card anuncio-discord-card' },
        el('div', { class: 'd-message-top' },
          el('div', { class: 'd-message-channel-tag' },
            icon('chat'),
            el('span', {}, channelName)
          ),
          el('span', { class: 'preview-badge dim' }, t('tabsAnuncios.previewTitle'))
        ),
        el('div', { class: 'd-message' }, msgHeader, msgBody)
      );

      previewContainer.append(discordCard);
    }

    const previewCol = el('div', { class: 'anuncio-preview-col' },
      el('div', { class: 'anuncio-preview-sticky' },
        el('div', { class: 'anuncio-section-header' },
          el('span', { class: 'anuncio-section-title' }, icon('layout'), t('tabsAnuncios.sectionPreview'))
        ),
        previewContainer
      )
    );

    // ── 6. Montaje del layout de 2 columnas ──────────────────────────
    const formCol = el('div', { class: 'anuncio-form-col card' },
      scheduleSection,
      messageSection,
      optionsSection,
      actionsBar
    );

    const editorLayout = el('div', { class: 'anuncio-editor-layout' },
      formCol,
      previewCol
    );

    updatePreview();
    updateCounter();

    shellWrap.append(header, editorLayout);
    setTimeout(() => {
      autoGrow(msgTxt);
    }, 0);
  }

  refresh();
}
