// Configuradores delgados de Eventos del Servidor: Bienvenidas, Despedidas y
// Boosts. Deciden CUÁNDO y DÓNDE se envía un mensaje y QUÉ plantilla usa —
// no construyen el mensaje. El contenido (texto/embed/botones) vive en
// Plantillas (js/tabs/plantillas.js). Ver
// docs/superpowers/specs/2026-08-21-eventos-plantillas-design.md para el
// porqué de esta separación.

import { apiFetch } from '/js/core/api.js';
import {
  el, spinner, renderError, toast, icon,
} from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, channelSelect, content } from '/js/panel-shell.js';
import { t, addStrings } from '/js/core/i18n.js';
import { loadTemplateEditor } from './plantillas.js';

addStrings({
  es: {
    // Bienvenidas
    'tabsWelcome.title': 'Bienvenidas',
    'tabsWelcome.subtitle': 'Decidí cuándo y dónde Purgito da la bienvenida a los nuevos miembros.',
    'tabsWelcome.toggleLabel': 'Activar bienvenida',
    'tabsWelcome.channelLabel': 'Canal de bienvenida',

    // Despedidas
    'tabsGoodbye.title': 'Despedidas',
    'tabsGoodbye.subtitle': 'Decidí cuándo y dónde Purgito se despide de los miembros que se van.',
    'tabsGoodbye.toggleLabel': 'Activar despedida',
    'tabsGoodbye.channelLabel': 'Canal de despedida',

    // Boosts
    'tabsBoost.title': 'Boosts',
    'tabsBoost.subtitle': 'Decidí cuándo y dónde Purgito agradece los boosts al servidor.',
    'tabsBoost.toggleLabel': 'Activar mensaje de boost',
    'tabsBoost.channelLabel': 'Canal de boosts',

    // Compartido entre los 3 módulos
    'tabsEventos.statusActive': 'Activado',
    'tabsEventos.statusInactive': 'Desactivado',
    'tabsEventos.channelSelectPlaceholder': 'Elige un canal…',
    'tabsEventos.noPermsWarning': '⚠ Purgito no puede enviar mensajes en este canal.',
    'tabsEventos.eventDisabledNotice': 'La bienvenida está desactivada. Actívala arriba para enviar mensajes automáticamente.',
    'tabsEventos.eventDisabledNoticeGoodbye': 'Las despedidas están desactivadas. Actívalas arriba para enviar mensajes automáticamente.',
    'tabsEventos.eventDisabledNoticeBoost': 'Los mensajes de boost están desactivados. Actívalos arriba para enviar mensajes automáticamente.',
    'tabsEventos.templateSectionLabel': 'Plantilla',
    'tabsEventos.templatePlaceholder': 'Elige una plantilla…',
    'tabsEventos.editTemplateBtn': 'Editar plantilla',
    'tabsEventos.createTemplateBtn': '+ Crear plantilla',
    'tabsEventos.noTemplatesHint': 'Todavía no tenés plantillas — creá una para poder asignarla acá.',
    'tabsEventos.legacyInlineNotice': 'Este evento todavía tiene un mensaje guardado directamente, sin usar una plantilla.',
    'tabsEventos.migrateToTemplateBtn': 'Convertir en plantilla',
    'tabsEventos.migratedSuccess': 'Mensaje convertido en una plantilla nueva',
    'tabsEventos.templateMissingNotice': 'La plantilla asignada a este evento ya no existe — elegí otra.',
    'tabsEventos.saveBtn': 'Guardar cambios',
    'tabsEventos.saving': 'Guardando…',
    'tabsEventos.savedSuccess': 'Configuración guardada correctamente',
    'tabsEventos.testBtn': 'Enviar prueba',
    'tabsEventos.testing': 'Enviando prueba…',
    'tabsEventos.testSuccess': 'Mensaje de prueba enviado al canal',
    'tabsEventos.resetBtn': 'Restablecer',
    'tabsEventos.resetConfirm': '¿Seguro que deseas restablecer la configuración de este evento?',
    'tabsEventos.resetSuccess': 'Configuración restablecida',
    'tabsEventos.noChannelSelected': 'Debes seleccionar un canal para activar el evento',
    // Reutilizadas por plantillas.js (evita duplicar el mismo texto en dos archivos)
    'tabsEventos.secMessage': 'Mensaje de texto',
    'tabsEventos.secEmbed': 'Embed de Discord',
    'tabsEventos.plainTextCounter': '{count} / 2000 caracteres',
    'tabsEventos.embedTitleLabel': 'Título del embed',
    'tabsEventos.embedDescLabel': 'Descripción',
    'tabsEventos.embedColorLabel': 'Color de la barra lateral',
    'tabsEventos.embedThumbLabel': 'Miniatura (Thumbnail)',
    'tabsEventos.embedImageLabel': 'Imagen grande',
    'tabsEventos.embedAuthorNameLabel': 'Nombre del autor',
    'tabsEventos.embedAuthorIconLabel': 'Icono del autor',
    'tabsEventos.embedFooterTextLabel': 'Texto del pie de página',
    'tabsEventos.embedFooterIconLabel': 'Icono del pie de página',
    'tabsEventos.addFieldBtn': '+ Agregar campo',
    'tabsEventos.fieldNamePlaceholder': 'Nombre del campo',
    'tabsEventos.fieldValuePlaceholder': 'Valor del campo',
    'tabsEventos.fieldInlineLabel': 'En línea (inline)',
    'tabsEventos.sectionFields': 'Campos adicionales',
    'tabsEventos.embedMoreOptions': 'Más opciones (color, thumbnail, icono de pie)',
    'tabsEventos.varsTitle': 'Variables disponibles',
    'tabsEventos.varsSubtitle': 'Haz clic en una variable para insertarla en el campo activo o copiarla.',
    'tabsEventos.varsSearchPlaceholder': 'Buscar variables…',
    'tabsEventos.varsCopied': 'Variable {var} copiada al portapapeles',
    'tabsEventos.varsInserted': 'Variable {var} insertada',
    'tabsEventos.insertVarBtn': 'Insertar variable',
    'tabsEventos.catAll': 'Todas',
    'tabsEventos.catUser': 'Usuario',
    'tabsEventos.catServer': 'Servidor',
    'tabsEventos.catChannel': 'Canal',
    'tabsEventos.catBoost': 'Boost',
    'tabsEventos.catDate': 'Fecha',
    'tabsEventos.varExample': 'Ejemplo:',
    'tabsEventos.close': 'Cerrar',
    'tabsEventos.buttonsTitle': 'Botones',
    'tabsEventos.buttonsHelp': 'Añade botones de enlace o de rol a este mensaje.',
    'tabsEventos.addButton': '+ Añadir botón',
    'tabsEventos.buttonLabelPlaceholder': 'Etiqueta del botón',
    'tabsEventos.buttonUrlPlaceholder': 'https://ejemplo.com',
    'tabsEventos.buttonTypeLink': 'Enlace (URL)',
    'tabsEventos.buttonTypeRole': 'Rol (Toggle)',
    'tabsEventos.buttonColorPrimary': 'Azul (Primary)',
    'tabsEventos.buttonColorSecondary': 'Gris (Secondary)',
    'tabsEventos.buttonColorSuccess': 'Verde (Success)',
    'tabsEventos.buttonColorDanger': 'Rojo (Danger)',
    'tabsEventos.modePlainText': 'Mensaje normal',
    'tabsEventos.modeClassicEmbed': 'Embed clásico',
    'tabsEventos.contentModeLabel': 'Formato',
  },
  en: {
    // Welcome
    'tabsWelcome.title': 'Welcome',
    'tabsWelcome.subtitle': 'Decide when and where Purgito welcomes new members.',
    'tabsWelcome.toggleLabel': 'Enable welcome',
    'tabsWelcome.channelLabel': 'Welcome channel',

    // Goodbye
    'tabsGoodbye.title': 'Goodbye',
    'tabsGoodbye.subtitle': 'Decide when and where Purgito says goodbye to members who leave.',
    'tabsGoodbye.toggleLabel': 'Enable goodbye',
    'tabsGoodbye.channelLabel': 'Goodbye channel',

    // Boosts
    'tabsBoost.title': 'Boosts',
    'tabsBoost.subtitle': 'Decide when and where Purgito thanks server boosts.',
    'tabsBoost.toggleLabel': 'Enable boost message',
    'tabsBoost.channelLabel': 'Boosts channel',

    // Shared
    'tabsEventos.statusActive': 'Enabled',
    'tabsEventos.statusInactive': 'Disabled',
    'tabsEventos.channelSelectPlaceholder': 'Choose a channel…',
    'tabsEventos.noPermsWarning': '⚠ Purgito cannot send messages in this channel.',
    'tabsEventos.eventDisabledNotice': 'Welcome is disabled. Enable it above to automatically send messages.',
    'tabsEventos.eventDisabledNoticeGoodbye': 'Goodbyes are disabled. Enable it above to automatically send messages.',
    'tabsEventos.eventDisabledNoticeBoost': 'Boost messages are disabled. Enable it above to automatically send messages.',
    'tabsEventos.templateSectionLabel': 'Template',
    'tabsEventos.templatePlaceholder': 'Choose a template…',
    'tabsEventos.editTemplateBtn': 'Edit template',
    'tabsEventos.createTemplateBtn': '+ Create template',
    'tabsEventos.noTemplatesHint': "You don't have templates yet — create one to assign it here.",
    'tabsEventos.legacyInlineNotice': 'This event still has a message saved directly, without using a template.',
    'tabsEventos.migrateToTemplateBtn': 'Convert to template',
    'tabsEventos.migratedSuccess': 'Message converted into a new template',
    'tabsEventos.templateMissingNotice': "The template assigned to this event no longer exists — choose another.",
    'tabsEventos.saveBtn': 'Save changes',
    'tabsEventos.saving': 'Saving…',
    'tabsEventos.savedSuccess': 'Settings saved successfully',
    'tabsEventos.testBtn': 'Send test',
    'tabsEventos.testing': 'Sending test…',
    'tabsEventos.testSuccess': 'Test message sent to channel',
    'tabsEventos.resetBtn': 'Reset',
    'tabsEventos.resetConfirm': 'Are you sure you want to reset settings for this event?',
    'tabsEventos.resetSuccess': 'Settings reset successfully',
    'tabsEventos.noChannelSelected': 'You must select a channel to enable the event',
    'tabsEventos.secMessage': 'Text message',
    'tabsEventos.secEmbed': 'Discord embed',
    'tabsEventos.plainTextCounter': '{count} / 2000 characters',
    'tabsEventos.embedTitleLabel': 'Embed title',
    'tabsEventos.embedDescLabel': 'Description',
    'tabsEventos.embedColorLabel': 'Sidebar color',
    'tabsEventos.embedThumbLabel': 'Thumbnail',
    'tabsEventos.embedImageLabel': 'Large image',
    'tabsEventos.embedAuthorNameLabel': 'Author name',
    'tabsEventos.embedAuthorIconLabel': 'Author icon',
    'tabsEventos.embedFooterTextLabel': 'Footer text',
    'tabsEventos.embedFooterIconLabel': 'Footer icon',
    'tabsEventos.addFieldBtn': '+ Add field',
    'tabsEventos.fieldNamePlaceholder': 'Field name',
    'tabsEventos.fieldValuePlaceholder': 'Field value',
    'tabsEventos.fieldInlineLabel': 'Inline',
    'tabsEventos.sectionFields': 'Additional fields',
    'tabsEventos.embedMoreOptions': 'More options (color, thumbnail, footer icon)',
    'tabsEventos.varsTitle': 'Available variables',
    'tabsEventos.varsSubtitle': 'Click any variable to insert into the active field or copy it.',
    'tabsEventos.varsSearchPlaceholder': 'Search variables…',
    'tabsEventos.varsCopied': 'Variable {var} copied to clipboard',
    'tabsEventos.varsInserted': 'Variable {var} inserted',
    'tabsEventos.insertVarBtn': 'Insert variable',
    'tabsEventos.catAll': 'All',
    'tabsEventos.catUser': 'User',
    'tabsEventos.catServer': 'Server',
    'tabsEventos.catChannel': 'Channel',
    'tabsEventos.catBoost': 'Boost',
    'tabsEventos.catDate': 'Date',
    'tabsEventos.varExample': 'Example:',
    'tabsEventos.close': 'Close',
    'tabsEventos.buttonsTitle': 'Buttons',
    'tabsEventos.buttonsHelp': 'Add link or role buttons to this message.',
    'tabsEventos.addButton': '+ Add button',
    'tabsEventos.buttonLabelPlaceholder': 'Button label',
    'tabsEventos.buttonUrlPlaceholder': 'https://example.com',
    'tabsEventos.buttonTypeLink': 'Link (URL)',
    'tabsEventos.buttonTypeRole': 'Role (Toggle)',
    'tabsEventos.buttonColorPrimary': 'Blurple (Primary)',
    'tabsEventos.buttonColorSecondary': 'Grey (Secondary)',
    'tabsEventos.buttonColorSuccess': 'Green (Success)',
    'tabsEventos.buttonColorDanger': 'Red (Danger)',
    'tabsEventos.modePlainText': 'Normal message',
    'tabsEventos.modeClassicEmbed': 'Classic embed',
    'tabsEventos.contentModeLabel': 'Format',
  },
});

const EVENT_CONFIGS = {
  welcome: {
    key: 'welcome',
    icon: 'logIn',
    titleKey: 'tabsWelcome.title',
    subtitleKey: 'tabsWelcome.subtitle',
    toggleLabelKey: 'tabsWelcome.toggleLabel',
    channelLabelKey: 'tabsWelcome.channelLabel',
    disabledNoticeKey: 'tabsEventos.eventDisabledNotice',
  },
  goodbye: {
    key: 'goodbye',
    icon: 'logOut',
    titleKey: 'tabsGoodbye.title',
    subtitleKey: 'tabsGoodbye.subtitle',
    toggleLabelKey: 'tabsGoodbye.toggleLabel',
    channelLabelKey: 'tabsGoodbye.channelLabel',
    disabledNoticeKey: 'tabsEventos.eventDisabledNoticeGoodbye',
  },
  boost: {
    key: 'boost',
    icon: 'star',
    titleKey: 'tabsBoost.title',
    subtitleKey: 'tabsBoost.subtitle',
    toggleLabelKey: 'tabsBoost.toggleLabel',
    channelLabelKey: 'tabsBoost.channelLabel',
    disabledNoticeKey: 'tabsEventos.eventDisabledNoticeBoost',
  },
};

export async function loadWelcomeTab() {
  return loadEventPage('welcome');
}

export async function loadGoodbyeTab() {
  return loadEventPage('goodbye');
}

export async function loadBoostTab() {
  return loadEventPage('boost');
}

async function loadEventPage(eventType) {
  const myGuild = GUILD_ID;
  const box = content();
  box.innerHTML = '';
  box.append(spinner());

  try {
    const [eventsData, templatesData, channels] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/events`),
      apiFetch(`/api/server/${GUILD_ID}/embeds/templates`),
      getChannels(),
    ]);

    if (myGuild !== GUILD_ID) return;
    renderEventConfigurator(box, eventType, eventsData, templatesData, channels);
  } catch (err) {
    if (myGuild !== GUILD_ID) return;
    renderError(box, err);
  }
}

function renderEventConfigurator(container, eventType, initialData, templatesData, channels) {
  container.innerHTML = '';

  const cfg = EVENT_CONFIGS[eventType] || EVENT_CONFIGS.welcome;
  const serverEvents = initialData.events || {};
  const templates = templatesData.templates || [];

  const evConfig = serverEvents[eventType] || {
    enabled: false,
    channel_id: '',
    template_id: null,
    content_mode: null,
    message: null,
    embed_json: null,
  };

  let isEnabled = !!evConfig.enabled;
  let selectedChannelId = evConfig.channel_id ? String(evConfig.channel_id) : (channels.length ? String(channels[0].id) : '');
  let selectedTemplateId = evConfig.template_id != null ? String(evConfig.template_id) : '';

  // Legacy real: contenido guardado directo en el evento, sin plantilla.
  const hasLegacyInline = !evConfig.template_id && Boolean(
    (evConfig.message && evConfig.message.trim())
    || (evConfig.embed_json && evConfig.embed_json !== '[]' && evConfig.embed_json !== 'null')
  );

  // ── Activación + canal ──────────────────────────────────────────────
  const toggleChk = el('input', { type: 'checkbox', checked: isEnabled });
  const toggleStatusBadge = el('span', {
    class: 'badge ' + (isEnabled ? 'badge-ok' : 'badge-dim'),
  }, isEnabled ? `● ${t('tabsEventos.statusActive')}` : `○ ${t('tabsEventos.statusInactive')}`);

  const channelSel = channelSelect(channels, selectedChannelId, t('tabsEventos.channelSelectPlaceholder'));
  const channelWarning = el('p', { class: 'form-error-msg', style: 'display: none; margin: 4px 0 0 0;' },
    t('tabsEventos.noPermsWarning'));

  function checkChannelPerms() {
    const ch = channels.find(c => String(c.id) === String(selectedChannelId));
    channelWarning.style.display = (ch && ch.can_send === false) ? 'block' : 'none';
  }
  channelSel.onchange = () => { selectedChannelId = channelSel.value; checkChannelPerms(); };
  checkChannelPerms();

  const disabledNotice = el('div', {
    class: 'cfg-disabled-hint',
    style: isEnabled ? 'display: none;' : 'display: flex;',
  }, icon('info'), el('span', {}, t(cfg.disabledNoticeKey)));

  toggleChk.onchange = () => {
    isEnabled = toggleChk.checked;
    toggleStatusBadge.className = 'badge ' + (isEnabled ? 'badge-ok' : 'badge-dim');
    toggleStatusBadge.textContent = isEnabled ? `● ${t('tabsEventos.statusActive')}` : `○ ${t('tabsEventos.statusInactive')}`;
    disabledNotice.style.display = isEnabled ? 'none' : 'flex';
  };

  const headerBlock = el('div', { class: 'cfg-block' },
    el('div', { class: 'cfg-head-row' },
      el('div', { class: 'cfg-head-title' },
        el('span', { class: 'event-icon' }, icon(cfg.icon)),
        el('h1', {}, t(cfg.titleKey)),
        toggleStatusBadge
      ),
      el('label', { class: 'toggle toggle-lg', title: t(cfg.toggleLabelKey) },
        toggleChk,
        el('span', { class: 'toggle-label' }, t(cfg.toggleLabelKey))
      )
    ),
    el('p', { class: 'dim cfg-desc' }, t(cfg.subtitleKey))
  );

  const activationBlock = el('div', { class: 'cfg-block' },
    el('label', { class: 'cfg-field-label' }, icon('chat'), t(cfg.channelLabelKey)),
    channelSel,
    channelWarning,
    disabledNotice
  );

  // ── Plantilla ────────────────────────────────────────────────────────
  const templateSel = el('select', { class: 'form-control' },
    el('option', { value: '' }, t('tabsEventos.templatePlaceholder')),
    ...templates.map(tpl => el('option', {
      value: String(tpl.id),
      selected: String(tpl.id) === selectedTemplateId,
    }, tpl.name))
  );

  const editTemplateBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary btn-sm',
    onclick: () => {
      if (!selectedTemplateId) return;
      loadTemplateEditor(Number(selectedTemplateId), {
        onSaved: () => loadEventPage(eventType),
        onCancel: () => loadEventPage(eventType),
      });
    },
  }, t('tabsEventos.editTemplateBtn'));

  const createTemplateBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary btn-sm',
    onclick: () => {
      loadTemplateEditor(null, {
        onSaved: async (newTemplateId) => {
          try {
            await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}`, {
              method: 'PUT',
              body: JSON.stringify({
                enabled: isEnabled,
                channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
                template_id: newTemplateId,
              }),
            });
          } catch (err) {
            toast(err.message || 'Error', 'err');
          }
          loadEventPage(eventType);
        },
        onCancel: () => loadEventPage(eventType),
      });
    },
  }, t('tabsEventos.createTemplateBtn'));

  function syncTemplateButtons() {
    editTemplateBtn.style.display = selectedTemplateId ? '' : 'none';
  }
  syncTemplateButtons();
  templateSel.onchange = () => { selectedTemplateId = templateSel.value; syncTemplateButtons(); };

  const templateBlockChildren = [
    el('label', { class: 'cfg-field-label' }, icon('layout'), t('tabsEventos.templateSectionLabel')),
    el('div', { class: 'cfg-row' }, templateSel, editTemplateBtn, createTemplateBtn),
  ];
  if (!templates.length) {
    templateBlockChildren.push(el('p', { class: 'dim text-xs', style: 'margin: 0;' }, t('tabsEventos.noTemplatesHint')));
  }
  if (evConfig.template_id && evConfig.template_missing) {
    templateBlockChildren.push(
      el('div', { class: 'event-legacy-notice' }, icon('info'), el('span', {}, t('tabsEventos.templateMissingNotice')))
    );
  }
  const templateBlock = el('div', { class: 'cfg-block' }, ...templateBlockChildren);

  // ── Aviso legacy: contenido inline sin migrar ───────────────────────
  async function migrateToTemplate() {
    try {
      const payload = { name: `${t(cfg.titleKey)} ${new Date().toLocaleDateString()}` };
      if (evConfig.content_mode === 'layout_v2') {
        payload.content_mode = 'layout_v2';
        payload.layout = evConfig.embed_json ? JSON.parse(evConfig.embed_json) : { blocks: [] };
      } else if (evConfig.content_mode === 'composite') {
        payload.content_mode = 'composite';
        payload.message = evConfig.message || '';
        const parsed = evConfig.embed_json ? JSON.parse(evConfig.embed_json) : {};
        if (parsed.embeds) payload.embeds = parsed.embeds;
        if (parsed.buttons) payload.buttons = parsed.buttons;
        if (parsed.send_options) payload.send_options = parsed.send_options;
      } else if (evConfig.content_mode === 'classic_embed') {
        payload.content_mode = 'classic_embed';
        const parsed = evConfig.embed_json ? JSON.parse(evConfig.embed_json) : [];
        payload.embeds = Array.isArray(parsed) ? parsed : (parsed.embeds || [parsed]);
      } else {
        payload.content_mode = 'plain_text';
        payload.message = evConfig.message || '';
      }
      const res = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}`, {
        method: 'PUT',
        body: JSON.stringify({
          enabled: isEnabled,
          channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
          template_id: res.id,
        }),
      });
      toast(t('tabsEventos.migratedSuccess'), 'ok');
      loadEventPage(eventType);
    } catch (err) {
      toast(err.message || 'Error', 'err');
    }
  }

  const legacyBlock = hasLegacyInline ? el('div', { class: 'cfg-block' },
    el('div', { class: 'event-legacy-notice' },
      icon('info'),
      el('span', {}, t('tabsEventos.legacyInlineNotice')),
      el('button', { type: 'button', class: 'btn btn-secondary btn-xs', onclick: migrateToTemplate }, t('tabsEventos.migrateToTemplateBtn'))
    )
  ) : null;

  // ── Acciones ─────────────────────────────────────────────────────────
  const saveBtn = el('button', {
    type: 'button',
    class: 'btn btn-primary',
    onclick: async () => {
      if (isEnabled && !selectedChannelId) {
        toast(t('tabsEventos.noChannelSelected'), 'err');
        return;
      }
      saveBtn.disabled = true;
      saveBtn.textContent = t('tabsEventos.saving');
      try {
        await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}`, {
          method: 'PUT',
          body: JSON.stringify({
            enabled: isEnabled,
            channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
            template_id: selectedTemplateId ? parseInt(selectedTemplateId, 10) : null,
          }),
        });
        toast(t('tabsEventos.savedSuccess'), 'ok');
      } catch (err) {
        toast(err.message || 'Error al guardar', 'err');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = t('tabsEventos.saveBtn');
      }
    },
  }, t('tabsEventos.saveBtn'));

  const testBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary',
    onclick: async () => {
      testBtn.disabled = true;
      testBtn.textContent = t('tabsEventos.testing');
      try {
        const body = { channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null };
        if (selectedTemplateId) body.template_id = parseInt(selectedTemplateId, 10);
        await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}/test`, {
          method: 'POST',
          body: JSON.stringify(body),
        });
        toast(t('tabsEventos.testSuccess'), 'ok');
      } catch (err) {
        toast(err.message || 'Error al enviar prueba', 'err');
      } finally {
        testBtn.disabled = false;
        testBtn.textContent = t('tabsEventos.testBtn');
      }
    },
  }, icon('play'), t('tabsEventos.testBtn'));

  const resetBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary btn-danger-soft',
    onclick: async () => {
      if (!confirm(t('tabsEventos.resetConfirm'))) return;
      try {
        await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}`, { method: 'DELETE' });
        toast(t('tabsEventos.resetSuccess'), 'ok');
        loadEventPage(eventType);
      } catch (err) {
        toast(err.message || 'Error al restablecer', 'err');
      }
    },
  }, icon('trash'), t('tabsEventos.resetBtn'));

  const actionsBar = el('div', { class: 'event-actions-bar' },
    el('div', { class: 'left-actions' }, saveBtn, testBtn),
    resetBtn
  );

  const cfgCardChildren = [headerBlock, activationBlock, templateBlock];
  if (legacyBlock) cfgCardChildren.push(legacyBlock);
  const cfgCard = el('div', { class: 'card cfg-card' }, ...cfgCardChildren);

  container.append(cfgCard, actionsBar);
}
