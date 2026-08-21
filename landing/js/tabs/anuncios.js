// Módulo de Gestión de Anuncios Programados de Purgito.
// Centro de administración de publicaciones automáticas por intervalo u hora fija diaria.

import { apiFetch } from '/js/core/api.js';
import {
  el, spinner, renderError, toast, formGroup, accordionGroup, autoGrow, helpIcon, icon, emptyState,
} from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, content } from '/js/panel-shell.js';
import { mdToNodes } from '/js/core/markdown.js';
import { t, addStrings } from '/js/core/i18n.js';
import {
  blankDoc, blankEmbed, embedDict, EMBED_LIMITS,
  blankLayoutDoc, newBlock, apiToBlock,
} from '/js/embeds/state.js';
import { renderEmbedsPreview } from '/js/embeds/classic-editor.js';
import { renderLayoutPreview } from '/js/embeds/layout-editor.js';
import { colorField, imageField } from '/js/embeds/shared-ui.js';

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
    'tabsAnuncios.secWhereWhen': '1. Dónde y Cuándo',
    'tabsAnuncios.channelLabel': 'Canal de destino',
    'tabsAnuncios.channelHelp': 'Canal donde se publicará el anuncio automáticamente.',
    'tabsAnuncios.channelSelectPlaceholder': 'Elige un canal…',
    'tabsAnuncios.cadenceLabel': 'Tipo de programación',
    'tabsAnuncios.modeInterval': 'Cada cierto tiempo',
    'tabsAnuncios.modeDaily': 'A una hora fija',
    'tabsAnuncios.intervalInputLabel': 'Intervalo (minutos)',
    'tabsAnuncios.intervalHint': 'Se enviará cada {minutes} minutos.',
    'tabsAnuncios.timeInputLabel': 'Hora de envío (HH:MM)',
    'tabsAnuncios.timeHint': 'Se enviará todos los días a las {time}.',
    'tabsAnuncios.secContent': '2. Contenido del anuncio',
    'tabsAnuncios.contentModeLabel': 'Modo de contenido',
    'tabsAnuncios.modePlainText': 'Mensaje normal',
    'tabsAnuncios.modeClassicEmbed': 'Embed clásico',
    'tabsAnuncios.modeLayoutV2': 'Layout V2',
    'tabsAnuncios.plainTextLabel': 'Mensaje de texto',
    'tabsAnuncios.plainTextPlaceholder': 'Escribe el mensaje que se publicará automáticamente…',
    'tabsAnuncios.plainTextCounter': '{count} / 2000 caracteres',
    'tabsAnuncios.secAdvanced': '3. Opciones avanzadas',
    'tabsAnuncios.autoDeleteLabel': 'Eliminar automáticamente (Auto-delete)',
    'tabsAnuncios.autoDeleteHelp': 'Borra el mensaje publicado después de transcurrido el tiempo configurado.',
    'tabsAnuncios.autoDeleteSeconds': 'Segundos antes de borrar (1 - 86400)',
    'tabsAnuncios.autoDeleteHint': 'El anuncio se eliminará automáticamente después de {seconds} segundos.',
    'tabsAnuncios.sectionContent': 'Contenido principal',
    'tabsAnuncios.sectionAppearance': 'Apariencia y color',
    'tabsAnuncios.sectionImages': 'Imágenes y miniaturas',
    'tabsAnuncios.sectionAuthor': 'Autor',
    'tabsAnuncios.sectionFooter': 'Pie de página',
    'tabsAnuncios.sectionFields': 'Campos adicionales',
    'tabsAnuncios.sectionIdentity': 'Identidad personalizada (Webhook)',
    'tabsAnuncios.embedTitleLabel': 'Título del embed',
    'tabsAnuncios.embedDescLabel': 'Descripción',
    'tabsAnuncios.embedColorLabel': 'Color de barra lateral',
    'tabsAnuncios.embedThumbLabel': 'Miniatura (Thumbnail)',
    'tabsAnuncios.embedImageLabel': 'Imagen grande',
    'tabsAnuncios.embedAuthorNameLabel': 'Nombre del autor',
    'tabsAnuncios.embedAuthorIconLabel': 'Icono del autor',
    'tabsAnuncios.embedFooterTextLabel': 'Texto de pie de página',
    'tabsAnuncios.embedFooterIconLabel': 'Icono de pie de página',
    'tabsAnuncios.webhookUsernameLabel': 'Nombre de usuario personalizado',
    'tabsAnuncios.webhookAvatarLabel': 'Avatar personalizado (URL)',
    'tabsAnuncios.webhookHelp': 'Envía el anuncio con un nombre y avatar específicos usando webhooks de Discord.',
    'tabsAnuncios.addFieldBtn': '+ Agregar campo',
    'tabsAnuncios.fieldNamePlaceholder': 'Nombre',
    'tabsAnuncios.fieldValuePlaceholder': 'Valor',
    'tabsAnuncios.fieldInlineLabel': 'En línea',
    'tabsAnuncios.previewTitle': 'Vista previa en vivo',
    'tabsAnuncios.previewHeader': 'Purgito',
    'tabsAnuncios.previewBotTag': 'BOT',
    'tabsAnuncios.previewToday': 'HOY',
    'tabsAnuncios.saveBtn': 'Guardar anuncio',
    'tabsAnuncios.saving': 'Guardando…',
    'tabsAnuncios.savedSuccess': 'Anuncio guardado correctamente',
    'tabsAnuncios.cancelBtn': 'Cancelar',
    'tabsAnuncios.noChannelSelected': 'Debes seleccionar un canal para el anuncio',
    'tabsAnuncios.emptyContent': 'El contenido del anuncio no puede estar vacío',
    'tabsAnuncios.templatesBtn': 'Plantillas',
    'tabsAnuncios.loadTemplate': 'Cargar plantilla',
    'tabsAnuncios.saveTemplate': 'Guardar como plantilla',
    'tabsAnuncios.templatePrompt': 'Nombre de la plantilla:',
    'tabsAnuncios.templateSaved': 'Plantilla guardada',
    'tabsAnuncios.templateLoaded': 'Plantilla cargada',
    'tabsAnuncios.noTemplates': 'No hay plantillas guardadas',
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
    'tabsAnuncios.secWhereWhen': '1. Where and When',
    'tabsAnuncios.channelLabel': 'Destination channel',
    'tabsAnuncios.channelHelp': 'Channel where the announcement will be posted automatically.',
    'tabsAnuncios.channelSelectPlaceholder': 'Choose a channel…',
    'tabsAnuncios.cadenceLabel': 'Schedule type',
    'tabsAnuncios.modeInterval': 'Every interval',
    'tabsAnuncios.modeDaily': 'Daily at a fixed time',
    'tabsAnuncios.intervalInputLabel': 'Interval (minutes)',
    'tabsAnuncios.intervalHint': 'Will be sent every {minutes} minutes.',
    'tabsAnuncios.timeInputLabel': 'Send time (HH:MM)',
    'tabsAnuncios.timeHint': 'Will be sent every day at {time}.',
    'tabsAnuncios.secContent': '2. Announcement content',
    'tabsAnuncios.contentModeLabel': 'Content mode',
    'tabsAnuncios.modePlainText': 'Normal message',
    'tabsAnuncios.modeClassicEmbed': 'Classic embed',
    'tabsAnuncios.modeLayoutV2': 'Layout V2',
    'tabsAnuncios.plainTextLabel': 'Text message',
    'tabsAnuncios.plainTextPlaceholder': 'Write the message that will be automatically published…',
    'tabsAnuncios.plainTextCounter': '{count} / 2000 characters',
    'tabsAnuncios.secAdvanced': '3. Advanced options',
    'tabsAnuncios.autoDeleteLabel': 'Auto-delete message',
    'tabsAnuncios.autoDeleteHelp': 'Deletes the published message automatically after the specified time.',
    'tabsAnuncios.autoDeleteSeconds': 'Seconds before delete (1 - 86400)',
    'tabsAnuncios.autoDeleteHint': 'The announcement will be deleted automatically after {seconds} seconds.',
    'tabsAnuncios.sectionContent': 'Main content',
    'tabsAnuncios.sectionAppearance': 'Appearance & color',
    'tabsAnuncios.sectionImages': 'Images & thumbnails',
    'tabsAnuncios.sectionAuthor': 'Author',
    'tabsAnuncios.sectionFooter': 'Footer',
    'tabsAnuncios.sectionFields': 'Additional fields',
    'tabsAnuncios.sectionIdentity': 'Custom identity (Webhook)',
    'tabsAnuncios.embedTitleLabel': 'Embed title',
    'tabsAnuncios.embedDescLabel': 'Description',
    'tabsAnuncios.embedColorLabel': 'Sidebar color',
    'tabsAnuncios.embedThumbLabel': 'Thumbnail',
    'tabsAnuncios.embedImageLabel': 'Large image',
    'tabsAnuncios.embedAuthorNameLabel': 'Author name',
    'tabsAnuncios.embedAuthorIconLabel': 'Author icon',
    'tabsAnuncios.embedFooterTextLabel': 'Footer text',
    'tabsAnuncios.embedFooterIconLabel': 'Footer icon',
    'tabsAnuncios.webhookUsernameLabel': 'Custom username',
    'tabsAnuncios.webhookAvatarLabel': 'Custom avatar (URL)',
    'tabsAnuncios.webhookHelp': 'Send the announcement with a custom name and avatar using Discord webhooks.',
    'tabsAnuncios.addFieldBtn': '+ Add field',
    'tabsAnuncios.fieldNamePlaceholder': 'Name',
    'tabsAnuncios.fieldValuePlaceholder': 'Value',
    'tabsAnuncios.fieldInlineLabel': 'Inline',
    'tabsAnuncios.previewTitle': 'Live preview',
    'tabsAnuncios.previewHeader': 'Purgito',
    'tabsAnuncios.previewBotTag': 'BOT',
    'tabsAnuncios.previewToday': 'TODAY',
    'tabsAnuncios.saveBtn': 'Save announcement',
    'tabsAnuncios.saving': 'Saving…',
    'tabsAnuncios.savedSuccess': 'Announcement saved successfully',
    'tabsAnuncios.cancelBtn': 'Cancel',
    'tabsAnuncios.noChannelSelected': 'You must select a destination channel',
    'tabsAnuncios.emptyContent': 'Announcement content cannot be empty',
    'tabsAnuncios.templatesBtn': 'Templates',
    'tabsAnuncios.loadTemplate': 'Load template',
    'tabsAnuncios.saveTemplate': 'Save as template',
    'tabsAnuncios.templatePrompt': 'Template name:',
    'tabsAnuncios.templateSaved': 'Template saved',
    'tabsAnuncios.templateLoaded': 'Template loaded',
    'tabsAnuncios.noTemplates': 'No templates saved',
  },
});

export async function loadAnunciosTab() {
  const myGuild = GUILD_ID;
  const box = content();
  box.innerHTML = '';
  box.append(spinner());

  try {
    const [anunciosData, channels, roles] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/anuncios`),
      getChannels(),
      getRoles(),
    ]);

    if (myGuild !== GUILD_ID) return;
    renderAnunciosManager(box, anunciosData, channels, roles);
  } catch (err) {
    if (myGuild !== GUILD_ID) return;
    renderError(box, err);
  }
}

function renderAnunciosManager(container, initialData, channels, roles) {
  container.innerHTML = '';

  let currentView = 'list'; // 'list' | 'editor'
  let editingAnnouncement = null;
  let announcementsList = initialData.announcements || [];
  let quotaCount = initialData.count || announcementsList.length;
  let quotaMax = initialData.max || 3;
  let isPremium = !!initialData.is_premium;

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
    // Header
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

      // Mode label
      let modeLabel = t('tabsAnuncios.modePlainText');
      if (ann.content_mode === 'classic_embed') modeLabel = t('tabsAnuncios.modeClassicEmbed');
      else if (ann.content_mode === 'layout_v2') modeLabel = t('tabsAnuncios.modeLayoutV2');

      // Title or snippet
      let titleSnippet = ann.message || '';
      if (ann.embed_json) {
        try {
          const parsed = JSON.parse(ann.embed_json);
          if (Array.isArray(parsed) && parsed[0] && parsed[0].title) {
            titleSnippet = parsed[0].title;
          } else if (parsed && parsed.embeds && parsed.embeds[0] && parsed.embeds[0].title) {
            titleSnippet = parsed.embeds[0].title;
          }
        } catch (e) {
          // ignore
        }
      }
      if (!titleSnippet) titleSnippet = `Anuncio #${ann.id}`;

      const card = el('div', { class: 'anuncio-manage-card card' },
        el('div', { class: 'anuncio-card-header' },
          el('div', { class: 'anuncio-card-title' },
            el('span', { class: 'anuncio-type-icon' }, icon('layout')),
            el('strong', { class: 'anuncio-title-text' }, titleSnippet)
          ),
          el('div', { class: 'anuncio-card-badges' },
            el('span', { class: 'badge badge-ok' }, `● ${t('tabsAnuncios.statusActive')}`),
            el('span', { class: 'badge badge-dim' }, modeLabel)
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
      hour: 9,
      minute: 0,
      content_mode: 'plain_text',
      message: '',
      embed_json: null,
      delete_after_seconds: null,
    };

    let selectedChannelId = ann.channel_id ? String(ann.channel_id) : (channels.length ? String(channels[0].id) : '');
    let scheduleMode = ann.mode || 'interval';
    let intervalMinutes = ann.interval_minutes || 30;
    let dailyHour = ann.hour !== undefined && ann.hour !== null ? ann.hour : 9;
    let dailyMinute = ann.minute !== undefined && ann.minute !== null ? ann.minute : 0;
    let contentMode = ann.content_mode || 'plain_text';
    let textMessage = ann.message || '';
    let enableAutoDelete = !!ann.delete_after_seconds;
    let autoDeleteSeconds = ann.delete_after_seconds || 60;
    let customUsername = '';
    let customAvatarUrl = '';

    // Docs for Embed / Layout
    let localEmbedDoc = blankDoc();
    let localLayoutDoc = blankLayoutDoc();

    if (contentMode === 'classic_embed' && ann.embed_json) {
      try {
        const parsed = JSON.parse(ann.embed_json);
        const list = Array.isArray(parsed) ? parsed : (parsed.embeds || []);
        if (parsed && !Array.isArray(parsed) && parsed.send_options) {
          customUsername = parsed.send_options.username || '';
          customAvatarUrl = parsed.send_options.avatar_url || '';
        }
        localEmbedDoc.embeds = list.map(e => ({ ...e }));
      } catch (e) {
        localEmbedDoc = blankDoc();
      }
    }

    if (contentMode === 'layout_v2' && ann.embed_json) {
      try {
        const parsed = JSON.parse(ann.embed_json);
        if (parsed && parsed.send_options) {
          customUsername = parsed.send_options.username || '';
          customAvatarUrl = parsed.send_options.avatar_url || '';
        }
        localLayoutDoc.blocks = (parsed.blocks || []).map(apiToBlock);
      } catch (e) {
        localLayoutDoc = blankLayoutDoc();
      }
    }

    if (!localEmbedDoc.embeds.length) localEmbedDoc.embeds.push(blankEmbed());
    const embedState = localEmbedDoc.embeds[0];

    // Navigation Header
    const backBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-sm',
      onclick: () => {
        currentView = 'list';
        refresh();
      },
    }, t('tabsAnuncios.backToList'));

    const header = el('div', { class: 'tab-header' },
      backBtn,
      el('h1', { style: 'margin-top: 10px;' },
        el('span', { class: 'nav-icon' }, icon('layout')),
        isEditing ? `${t('tabsAnuncios.editTitle')} #${ann.id}` : t('tabsAnuncios.createTitle')
      )
    );

    // Form Panes
    const editorPane = el('div', { class: 'anuncio-editor-pane' });
    const previewPane = el('div', { class: 'anuncio-preview-pane' });

    // Live preview function
    function updatePreview() {
      previewPane.innerHTML = '';

      const ch = channels.find(c => String(c.id) === String(selectedChannelId));
      const channelName = ch ? '#' + ch.name : '#general';

      const previewAuthorName = customUsername || t('tabsAnuncios.previewHeader');
      const previewAvatarUrl = customAvatarUrl || '/assets/icon.png';

      const msgHeader = el('div', { class: 'd-msg-header' },
        el('img', { src: previewAvatarUrl, alt: 'Purgito', class: 'd-msg-avatar' }),
        el('div', { class: 'd-msg-meta' },
          el('span', { class: 'd-msg-author' }, previewAuthorName),
          el('span', { class: 'd-msg-bot' }, t('tabsAnuncios.previewBotTag')),
          el('span', { class: 'd-msg-time' }, t('tabsAnuncios.previewToday'))
        )
      );

      const msgBody = el('div', { class: 'd-msg-body' });

      if (contentMode === 'plain_text') {
        msgBody.append(el('div', { class: 'd-msg-text' }, ...mdToNodes(textMessage || '')));
      } else if (contentMode === 'classic_embed') {
        const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
        msgBody.append(renderEmbedsPreview(rawDicts));
      } else if (contentMode === 'layout_v2') {
        msgBody.append(renderLayoutPreview(localLayoutDoc.blocks));
      }

      const discordCard = el('div', { class: 'd-message-card' },
        el('div', { class: 'd-message-top' },
          el('div', { class: 'd-message-channel-tag' },
            icon('chat'),
            el('span', {}, channelName)
          ),
          el('span', { class: 'preview-badge dim' }, t('tabsAnuncios.previewTitle'))
        ),
        el('div', { class: 'd-message' }, msgHeader, msgBody)
      );

      previewPane.append(discordCard);
    }

    // 1. DÓNDE Y CUÁNDO (Programación)
    const channelSel = channelSelect(channels, selectedChannelId, t('tabsAnuncios.channelSelectPlaceholder'));
    channelSel.onchange = () => {
      selectedChannelId = channelSel.value;
      updatePreview();
    };

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

    const scheduleControlsWrap = el('div', { class: 'schedule-controls-wrap' });

    function refreshScheduleControls() {
      intervalPill.className = 'mode-pill' + (scheduleMode === 'interval' ? ' active' : '');
      dailyPill.className = 'mode-pill' + (scheduleMode === 'daily' ? ' active' : '');
      scheduleControlsWrap.innerHTML = '';

      if (scheduleMode === 'interval') {
        const intervalInp = el('input', {
          type: 'number',
          min: '5',
          max: '1440',
          class: 'form-control',
          value: String(intervalMinutes),
        });
        const hint = el('p', { class: 'dim text-sm' },
          t('tabsAnuncios.intervalHint', { minutes: intervalMinutes })
        );

        intervalInp.oninput = () => {
          const val = parseInt(intervalInp.value, 10);
          if (!isNaN(val)) intervalMinutes = val;
          hint.textContent = t('tabsAnuncios.intervalHint', { minutes: intervalMinutes });
        };

        const presets = [15, 30, 60, 120, 360, 720, 1440];
        const presetChips = el('div', { class: 'preset-chips' },
          ...presets.map(m => el('button', {
            type: 'button',
            class: 'category-tab-btn',
            onclick: () => {
              intervalMinutes = m;
              intervalInp.value = String(m);
              hint.textContent = t('tabsAnuncios.intervalHint', { minutes: m });
            },
          }, m >= 60 ? `${m / 60}h` : `${m}m`))
        );

        scheduleControlsWrap.append(
          formGroup(t('tabsAnuncios.intervalInputLabel'), intervalInp, presetChips, hint)
        );
      } else {
        const hh = String(dailyHour).padStart(2, '0');
        const mm = String(dailyMinute).padStart(2, '0');
        const timeInp = el('input', {
          type: 'time',
          class: 'form-control',
          value: `${hh}:${mm}`,
        });
        const hint = el('p', { class: 'dim text-sm' },
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

        scheduleControlsWrap.append(
          formGroup(t('tabsAnuncios.timeInputLabel'), timeInp, hint)
        );
      }
    }

    refreshScheduleControls();

    const whereWhenSec = el('div', { class: 'card anuncio-section-card' },
      el('h3', { class: 'section-title' }, t('tabsAnuncios.secWhereWhen')),
      formGroup(t('tabsAnuncios.channelLabel'), channelSel),
      formGroup(t('tabsAnuncios.cadenceLabel'),
        el('div', { class: 'event-mode-pills' }, intervalPill, dailyPill),
        scheduleControlsWrap
      )
    );

    // 2. CONTENIDO
    const contentModes = [
      { key: 'plain_text', label: t('tabsAnuncios.modePlainText'), icon: 'chat' },
      { key: 'classic_embed', label: t('tabsAnuncios.modeClassicEmbed'), icon: 'layout' },
      { key: 'layout_v2', label: t('tabsAnuncios.modeLayoutV2'), icon: 'sparkle' },
    ];

    const contentModePills = el('div', { class: 'event-mode-pills' });
    const contentEditorWrap = el('div', { class: 'anuncio-content-editor-wrap' });

    function renderContentModeSelector() {
      contentModePills.innerHTML = '';
      for (const m of contentModes) {
        const pill = el('button', {
          type: 'button',
          class: 'mode-pill' + (contentMode === m.key ? ' active' : ''),
          onclick: () => {
            if (contentMode === m.key) return;
            contentMode = m.key;
            renderContentModeSelector();
            renderContentEditor();
            updatePreview();
          },
        },
          el('span', { class: 'mode-pill-icon' }, icon(m.icon)),
          m.label
        );
        contentModePills.append(pill);
      }
    }

    function renderContentEditor() {
      contentEditorWrap.innerHTML = '';

      if (contentMode === 'plain_text') {
        const txtArea = el('textarea', {
          class: 'form-control autogrow',
          rows: 4,
          placeholder: t('tabsAnuncios.plainTextPlaceholder'),
        });
        txtArea.value = textMessage;

        const counter = el('div', { class: 'char-counter' },
          t('tabsAnuncios.plainTextCounter', { count: textMessage.length })
        );

        txtArea.oninput = () => {
          textMessage = txtArea.value;
          autoGrow(txtArea);
          counter.textContent = t('tabsAnuncios.plainTextCounter', { count: textMessage.length });
          counter.className = 'char-counter' + (textMessage.length > 2000 ? ' over' : '');
          updatePreview();
        };

        contentEditorWrap.append(
          formGroup(t('tabsAnuncios.plainTextLabel'), txtArea, counter)
        );
      } else if (contentMode === 'classic_embed') {
        const s = embedState;

        function boundInput(key, placeholder, isArea = false, maxL = null) {
          const input = el(isArea ? 'textarea' : 'input', {
            class: 'form-control' + (isArea ? ' autogrow' : ''),
            placeholder,
            maxlength: maxL ? String(maxL) : null,
          });
          input.value = s[key] || '';
          input.oninput = () => {
            s[key] = input.value;
            if (isArea) autoGrow(input);
            updatePreview();
          };
          return input;
        }

        // Templates bar
        const templateBar = el('div', { class: 'template-action-bar' },
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-xs',
            onclick: async () => {
              try {
                const res = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`);
                const templates = res.templates || [];
                if (!templates.length) {
                  toast(t('tabsAnuncios.noTemplates'), 'info');
                  return;
                }
                const chosen = prompt(
                  `Elige una plantilla:\n` + templates.map((t, idx) => `${idx + 1}. ${t.name}`).join('\n')
                );
                const idx = parseInt(chosen, 10) - 1;
                if (!isNaN(idx) && templates[idx]) {
                  const tmpl = templates[idx];
                  const parsed = JSON.parse(tmpl.embed_json);
                  const embeds = Array.isArray(parsed) ? parsed : (parsed.embeds || []);
                  if (embeds.length) {
                    Object.assign(s, embeds[0]);
                    renderContentEditor();
                    updatePreview();
                    toast(t('tabsAnuncios.templateLoaded'), 'ok');
                  }
                }
              } catch (e) {
                toast(e.message || 'Error', 'err');
              }
            },
          }, icon('layout'), t('tabsAnuncios.loadTemplate')),
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-xs',
            onclick: async () => {
              const name = (prompt(t('tabsAnuncios.templatePrompt')) || '').trim();
              if (!name) return;
              try {
                const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
                await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`, {
                  method: 'POST',
                  body: JSON.stringify({ name, embeds: rawDicts }),
                });
                toast(t('tabsAnuncios.templateSaved'), 'ok');
              } catch (e) {
                toast(e.message || 'Error', 'err');
              }
            },
          }, icon('star'), t('tabsAnuncios.saveTemplate'))
        );

        // Sections
        const contentSec = accordionGroup(t('tabsAnuncios.sectionContent'), true,
          formGroup(t('tabsAnuncios.embedTitleLabel'), boundInput('title', 'Título del anuncio', false, EMBED_LIMITS.title)),
          formGroup(t('tabsAnuncios.embedDescLabel'), boundInput('description', 'Descripción del anuncio…', true, EMBED_LIMITS.description))
        );

        const appearanceSec = accordionGroup(t('tabsAnuncios.sectionAppearance'), false,
          formGroup(t('tabsAnuncios.embedColorLabel'), colorField(s, 'color', () => updatePreview()))
        );

        const imagesSec = accordionGroup(t('tabsAnuncios.sectionImages'), false,
          formGroup(t('tabsAnuncios.embedThumbLabel'), imageField(s, 'thumbnail', () => updatePreview(), { gif: true })),
          formGroup(t('tabsAnuncios.embedImageLabel'), imageField(s, 'image', () => updatePreview(), { gif: true }))
        );

        const authorSec = accordionGroup(t('tabsAnuncios.sectionAuthor'), false,
          formGroup(t('tabsAnuncios.embedAuthorNameLabel'), boundInput('author_name', 'Autor del anuncio', false, EMBED_LIMITS.author)),
          formGroup(t('tabsAnuncios.embedAuthorIconLabel'), imageField(s, 'author_icon_url', () => updatePreview()))
        );

        const footerSec = accordionGroup(t('tabsAnuncios.sectionFooter'), false,
          formGroup(t('tabsAnuncios.embedFooterTextLabel'), boundInput('footer_text', 'Pie de página del anuncio', false, EMBED_LIMITS.footer)),
          formGroup(t('tabsAnuncios.embedFooterIconLabel'), imageField(s, 'footer_icon_url', () => updatePreview()))
        );

        // Fields
        const fieldsListWrap = el('div', { class: 'embed-fields-container' });
        s.fields = s.fields || [];

        function renderFields() {
          fieldsListWrap.innerHTML = '';
          s.fields.forEach((f, idx) => {
            const fName = el('input', {
              class: 'form-control',
              placeholder: t('tabsAnuncios.fieldNamePlaceholder'),
              value: f.name || '',
              maxlength: String(EMBED_LIMITS.fieldName),
            });
            fName.oninput = () => { f.name = fName.value; updatePreview(); };

            const fVal = el('input', {
              class: 'form-control',
              placeholder: t('tabsAnuncios.fieldValuePlaceholder'),
              value: f.value || '',
              maxlength: String(EMBED_LIMITS.fieldValue),
            });
            fVal.oninput = () => { f.value = fVal.value; updatePreview(); };

            const inlineChk = el('input', {
              type: 'checkbox',
              checked: !!f.inline,
              onchange: () => { f.inline = inlineChk.checked; updatePreview(); },
            });

            const delBtn = el('button', {
              type: 'button',
              class: 'btn btn-secondary btn-xs',
              onclick: () => { s.fields.splice(idx, 1); renderFields(); updatePreview(); },
            }, '✕');

            const row = el('div', { class: 'embed-field-item' },
              el('div', { class: 'field-inputs' }, fName, fVal),
              el('div', { class: 'field-controls' },
                el('label', { class: 'toggle toggle-xs' }, inlineChk, t('tabsAnuncios.fieldInlineLabel')),
                delBtn
              )
            );
            fieldsListWrap.append(row);
          });
        }

        const addFieldBtn = el('button', {
          type: 'button',
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            if (s.fields.length >= EMBED_LIMITS.maxFields) {
              toast(`Máximo ${EMBED_LIMITS.maxFields} campos`, 'warn');
              return;
            }
            s.fields.push({ name: '', value: '', inline: false });
            renderFields();
            updatePreview();
          },
        }, t('tabsAnuncios.addFieldBtn'));

        renderFields();
        const fieldsSec = accordionGroup(t('tabsAnuncios.sectionFields'), false,
          fieldsListWrap,
          el('div', { style: 'margin-top: 10px;' }, addFieldBtn)
        );

        // Webhook Identity
        const customUserInp = el('input', {
          class: 'form-control',
          placeholder: 'Nombre personalizado',
          value: customUsername,
        });
        customUserInp.oninput = () => { customUsername = customUserInp.value; updatePreview(); };

        const customAvatarInp = el('input', {
          class: 'form-control',
          placeholder: 'https://ejemplo.com/avatar.png',
          value: customAvatarUrl,
        });
        customAvatarInp.oninput = () => { customAvatarUrl = customAvatarInp.value; updatePreview(); };

        const identitySec = accordionGroup(t('tabsAnuncios.sectionIdentity'), false,
          el('p', { class: 'dim form-hint', style: 'margin-top:0' }, t('tabsAnuncios.webhookHelp')),
          formGroup(t('tabsAnuncios.webhookUsernameLabel'), customUserInp),
          formGroup(t('tabsAnuncios.webhookAvatarLabel'), customAvatarInp)
        );

        contentEditorWrap.append(templateBar, contentSec, appearanceSec, imagesSec, authorSec, footerSec, fieldsSec, identitySec);
      } else if (contentMode === 'layout_v2') {
        const blocksList = el('div', { class: 'layout-blocks-list' });

        function refreshLayoutBlocks() {
          blocksList.innerHTML = '';
          localLayoutDoc.blocks.forEach((b, idx) => {
            const blockRow = el('div', { class: 'layout-block-card' },
              el('div', { class: 'layout-block-head' },
                el('strong', {}, `${b.type.toUpperCase()}`),
                el('button', {
                  type: 'button',
                  class: 'btn btn-danger btn-xs',
                  onclick: () => {
                    localLayoutDoc.blocks.splice(idx, 1);
                    refreshLayoutBlocks();
                    updatePreview();
                  },
                }, '✕')
              )
            );

            if (b.type === 'text') {
              const ta = el('textarea', { class: 'form-control autogrow' });
              ta.value = b.content || '';
              ta.oninput = () => { b.content = ta.value; autoGrow(ta); updatePreview(); };
              blockRow.append(ta);
            } else if (b.type === 'section') {
              const ta = el('textarea', { class: 'form-control autogrow' });
              ta.value = (b.texts && b.texts[0]) || '';
              ta.oninput = () => { b.texts = [ta.value]; autoGrow(ta); updatePreview(); };
              blockRow.append(formGroup('Texto', ta));
              if (b.accessory && b.accessory.type === 'button') {
                const lbl = el('input', { class: 'form-control', value: b.accessory.label || '', placeholder: 'Etiqueta del botón' });
                lbl.oninput = () => { b.accessory.label = lbl.value; updatePreview(); };
                const url = el('input', { class: 'form-control', value: b.accessory.url || '', placeholder: 'https://...' });
                url.oninput = () => { b.accessory.url = url.value; updatePreview(); };
                blockRow.append(formGroup('Botón de enlace', el('div', { class: 'grid-2' }, lbl, url)));
              }
            } else if (b.type === 'action_row') {
              const btnsWrap = el('div', { class: 'action-row-buttons' });
              (b.buttons || []).forEach((btn) => {
                const lbl = el('input', { class: 'form-control', value: btn.label || '', placeholder: 'Etiqueta' });
                lbl.oninput = () => { btn.label = lbl.value; updatePreview(); };
                const url = el('input', { class: 'form-control', value: btn.url || '', placeholder: 'https://...' });
                url.oninput = () => { btn.url = url.value; updatePreview(); };
                btnsWrap.append(el('div', { class: 'btn-row-item' }, lbl, url));
              });
              blockRow.append(btnsWrap);
            }
            blocksList.append(blockRow);
          });
        }

        const addBlockBtns = el('div', { class: 'layout-add-btns' },
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            onclick: () => { localLayoutDoc.blocks.push(newBlock('text')); refreshLayoutBlocks(); updatePreview(); },
          }, '+ Texto'),
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            onclick: () => {
              const sec = newBlock('section');
              sec.accessory = { type: 'button', style: 'link', label: 'Enlace', url: 'https://discord.com' };
              localLayoutDoc.blocks.push(sec);
              refreshLayoutBlocks();
              updatePreview();
            },
          }, '+ Sección con Botón'),
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            onclick: () => {
              const row = newBlock('action_row');
              localLayoutDoc.blocks.push(row);
              refreshLayoutBlocks();
              updatePreview();
            },
          }, '+ Fila de Botones')
        );

        if (!localLayoutDoc.blocks.length) {
          localLayoutDoc.blocks.push({ type: 'text', content: 'Anuncio importante en el servidor' });
        }

        refreshLayoutBlocks();

        const customUserInp = el('input', {
          class: 'form-control',
          placeholder: 'Nombre personalizado',
          value: customUsername,
        });
        customUserInp.oninput = () => { customUsername = customUserInp.value; updatePreview(); };

        const customAvatarInp = el('input', {
          class: 'form-control',
          placeholder: 'https://ejemplo.com/avatar.png',
          value: customAvatarUrl,
        });
        customAvatarInp.oninput = () => { customAvatarUrl = customAvatarInp.value; updatePreview(); };

        const identitySec = accordionGroup(t('tabsAnuncios.sectionIdentity'), false,
          el('p', { class: 'dim form-hint', style: 'margin-top:0' }, t('tabsAnuncios.webhookHelp')),
          formGroup(t('tabsAnuncios.webhookUsernameLabel'), customUserInp),
          formGroup(t('tabsAnuncios.webhookAvatarLabel'), customAvatarInp)
        );

        contentEditorWrap.append(blocksList, addBlockBtns, identitySec);
      }
    }

    renderContentModeSelector();
    renderContentEditor();

    const contentSecCard = el('div', { class: 'card anuncio-section-card' },
      el('h3', { class: 'section-title' }, t('tabsAnuncios.secContent')),
      formGroup(t('tabsAnuncios.contentModeLabel'), contentModePills),
      contentEditorWrap
    );

    // 3. OPCIONES AVANZADAS (Auto-delete)
    const autoDeleteChk = el('input', {
      type: 'checkbox',
      checked: enableAutoDelete,
      onchange: () => {
        enableAutoDelete = autoDeleteChk.checked;
        autoDeleteInputWrap.style.display = enableAutoDelete ? 'block' : 'none';
      },
    });

    const autoDeleteSecsInp = el('input', {
      type: 'number',
      min: '1',
      max: '86400',
      class: 'form-control',
      value: String(autoDeleteSeconds),
    });

    const autoDeleteHint = el('p', { class: 'dim text-sm' },
      t('tabsAnuncios.autoDeleteHint', { seconds: autoDeleteSeconds })
    );

    autoDeleteSecsInp.oninput = () => {
      const val = parseInt(autoDeleteSecsInp.value, 10);
      if (!isNaN(val)) autoDeleteSeconds = val;
      autoDeleteHint.textContent = t('tabsAnuncios.autoDeleteHint', { seconds: autoDeleteSeconds });
    };

    const autoDeletePresets = [30, 60, 300, 600, 3600, 86400];
    const autoDeleteChips = el('div', { class: 'preset-chips' },
      ...autoDeletePresets.map(s => el('button', {
        type: 'button',
        class: 'category-tab-btn',
        onclick: () => {
          autoDeleteSeconds = s;
          autoDeleteSecsInp.value = String(s);
          autoDeleteHint.textContent = t('tabsAnuncios.autoDeleteHint', { seconds: s });
        },
      }, s >= 3600 ? `${s / 3600}h` : (s >= 60 ? `${s / 60}m` : `${s}s`)))
    );

    const autoDeleteInputWrap = el('div', {
      style: enableAutoDelete ? 'display:block; margin-top:10px;' : 'display:none; margin-top:10px;',
    },
      formGroup(t('tabsAnuncios.autoDeleteSeconds'), autoDeleteSecsInp, autoDeleteChips, autoDeleteHint)
    );

    const advancedSecCard = el('div', { class: 'card anuncio-section-card' },
      el('h3', { class: 'section-title' }, t('tabsAnuncios.secAdvanced')),
      el('label', { class: 'toggle' },
        autoDeleteChk,
        el('span', { class: 'toggle-label' }, t('tabsAnuncios.autoDeleteLabel')),
        helpIcon(t('tabsAnuncios.autoDeleteHelp'))
      ),
      autoDeleteInputWrap
    );

    // Actions Toolbar
    const saveBtn = el('button', {
      type: 'button',
      class: 'btn btn-primary',
      onclick: async () => {
        if (!selectedChannelId) {
          toast(t('tabsAnuncios.noChannelSelected'), 'err');
          return;
        }

        saveBtn.disabled = true;
        saveBtn.textContent = t('tabsAnuncios.saving');

        try {
          const payload = {
            channel_id: selectedChannelId,
            mode: scheduleMode,
            content_mode: contentMode,
            delete_after_seconds: enableAutoDelete ? autoDeleteSeconds : null,
          };

          if (scheduleMode === 'interval') {
            payload.interval_minutes = intervalMinutes;
          } else {
            payload.hour = dailyHour;
            payload.minute = dailyMinute;
          }

          const sendOpts = (customUsername.trim() || customAvatarUrl.trim())
            ? { username: customUsername.trim(), avatar_url: customAvatarUrl.trim() }
            : null;

          if (contentMode === 'plain_text') {
            if (!textMessage.trim()) {
              toast(t('tabsAnuncios.emptyContent'), 'err');
              saveBtn.disabled = false;
              saveBtn.textContent = t('tabsAnuncios.saveBtn');
              return;
            }
            payload.message = textMessage.trim();
          } else if (contentMode === 'classic_embed') {
            payload.embeds = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
            if (sendOpts) payload.send_options = sendOpts;
          } else if (contentMode === 'layout_v2') {
            payload.layout = { blocks: localLayoutDoc.blocks };
            if (sendOpts) payload.send_options = sendOpts;
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

    const actionsRow = el('div', { class: 'event-actions-bar' },
      el('div', { class: 'left-actions' }, saveBtn, cancelBtn)
    );

    editorPane.append(whereWhenSec, contentSecCard, advancedSecCard, actionsRow);

    updatePreview();

    const workspaceGrid = el('div', { class: 'anuncio-workspace-grid' },
      editorPane,
      el('div', { class: 'anuncio-preview-pane-wrap' }, previewPane)
    );

    shellWrap.append(header, workspaceGrid);
  }

  refresh();
}
