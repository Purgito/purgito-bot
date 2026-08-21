// Módulos independientes de Eventos del Servidor: Bienvenidas, Despedidas y Boosts.
// Cada página es una herramienta dedicada con su propio contexto, editor, variables y live preview.

import { apiFetch } from '/js/core/api.js';
import {
  el, spinner, renderError, toast, formGroup, accordionGroup, autoGrow, helpIcon, icon,
} from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, content } from '/js/panel-shell.js';
import { mdToNodes } from '/js/core/markdown.js';
import { t, addStrings } from '/js/core/i18n.js';
import {
  blankDoc, blankEmbed, embedDict, embedChars, EMBED_LIMITS,
  blankLayoutDoc, newBlock, blockWarning, apiToBlock,
} from '/js/embeds/state.js';
import { renderEmbedsPreview } from '/js/embeds/classic-editor.js';
import { renderLayoutPreview } from '/js/embeds/layout-editor.js';
import { colorField, imageField } from '/js/embeds/shared-ui.js';

addStrings({
  es: {
    // Bienvenidas
    'tabsWelcome.title': 'Bienvenidas',
    'tabsWelcome.subtitle': 'Configura el mensaje que Purgito enviará cuando un nuevo miembro entre en tu servidor.',
    'tabsWelcome.toggleLabel': 'Activar bienvenida',
    'tabsWelcome.toggleHelp': 'Purgito enviará este mensaje automáticamente cuando un nuevo miembro entre al servidor.',
    'tabsWelcome.channelLabel': 'Canal de bienvenida',
    'tabsWelcome.channelHelp': 'Canal donde se publicará el mensaje de bienvenida.',

    // Despedidas
    'tabsGoodbye.title': 'Despedidas',
    'tabsGoodbye.subtitle': 'Configura el mensaje que Purgito enviará cuando un miembro abandone tu servidor.',
    'tabsGoodbye.toggleLabel': 'Activar despedida',
    'tabsGoodbye.toggleHelp': 'Purgito enviará este mensaje automáticamente cuando un miembro abandone el servidor.',
    'tabsGoodbye.channelLabel': 'Canal de despedida',
    'tabsGoodbye.channelHelp': 'Canal donde se publicará el mensaje de despedida.',

    // Boosts
    'tabsBoost.title': 'Boosts',
    'tabsBoost.subtitle': 'Configura el mensaje que Purgito enviará cuando alguien apoye tu servidor con un boost.',
    'tabsBoost.toggleLabel': 'Activar mensaje de boost',
    'tabsBoost.toggleHelp': 'Purgito enviará este mensaje automáticamente cuando un miembro mejore el servidor.',
    'tabsBoost.channelLabel': 'Canal de boosts',
    'tabsBoost.channelHelp': 'Canal donde se agradecerán los boosts del servidor.',

    // Secciones y elementos compartidos
    'tabsEventos.secStatus': 'Estado',
    'tabsEventos.statusActive': 'Activado',
    'tabsEventos.statusInactive': 'Desactivado',
    'tabsEventos.secChannel': 'Canal de destino',
    'tabsEventos.channelSelectPlaceholder': 'Elige un canal…',
    'tabsEventos.noPermsWarning': '⚠ Purgito no puede enviar mensajes o embeds en este canal.',
    'tabsEventos.secMessage': 'Mensaje',
    'tabsEventos.contentModeLabel': 'Tipo de contenido',
    'tabsEventos.modePlainText': 'Mensaje normal',
    'tabsEventos.modeClassicEmbed': 'Embed clásico',
    'tabsEventos.modeLayoutV2': 'Layout V2',
    'tabsEventos.plainTextLabel': 'Contenido del mensaje',
    'tabsEventos.plainTextPlaceholder': 'Escribe aquí el mensaje…',
    'tabsEventos.plainTextCounter': '{count} / 2000 caracteres',
    'tabsEventos.sectionContent': 'Contenido principal',
    'tabsEventos.sectionAppearance': 'Apariencia y color',
    'tabsEventos.sectionImages': 'Imágenes y miniaturas',
    'tabsEventos.sectionAuthor': 'Autor',
    'tabsEventos.sectionFooter': 'Pie de página',
    'tabsEventos.sectionFields': 'Campos adicionales (Fields)',
    'tabsEventos.sectionIdentity': 'Identidad personalizada (Webhook)',
    'tabsEventos.embedTitleLabel': 'Título del embed',
    'tabsEventos.embedDescLabel': 'Descripción',
    'tabsEventos.embedColorLabel': 'Color de la barra lateral',
    'tabsEventos.embedThumbLabel': 'Miniatura (Thumbnail)',
    'tabsEventos.embedImageLabel': 'Imagen grande',
    'tabsEventos.embedAuthorNameLabel': 'Nombre del autor',
    'tabsEventos.embedAuthorIconLabel': 'Icono del autor',
    'tabsEventos.embedFooterTextLabel': 'Texto del pie de página',
    'tabsEventos.embedFooterIconLabel': 'Icono del pie de página',
    'tabsEventos.webhookUsernameLabel': 'Nombre de usuario personalizado',
    'tabsEventos.webhookAvatarLabel': 'Avatar personalizado (URL)',
    'tabsEventos.webhookHelp': 'Permite enviar el mensaje con un nombre y avatar específicos usando webhooks de Discord.',
    'tabsEventos.addFieldBtn': '+ Agregar campo',
    'tabsEventos.fieldNamePlaceholder': 'Nombre del campo',
    'tabsEventos.fieldValuePlaceholder': 'Valor del campo',
    'tabsEventos.fieldInlineLabel': 'En línea (inline)',
    'tabsEventos.varsTitle': 'Variables disponibles',
    'tabsEventos.varsSubtitle': 'Haz clic en una variable para insertarla en el campo activo o copiarla.',
    'tabsEventos.varsSearchPlaceholder': 'Buscar variables…',
    'tabsEventos.varsCopied': 'Variable {var} copiada al portapapeles',
    'tabsEventos.varsInserted': 'Variable {var} insertada',
    'tabsEventos.catAll': 'Todas',
    'tabsEventos.catUser': 'Usuario',
    'tabsEventos.catServer': 'Servidor',
    'tabsEventos.catChannel': 'Canal',
    'tabsEventos.catBoost': 'Boost',
    'tabsEventos.catDate': 'Fecha',
    'tabsEventos.previewTitle': 'Vista previa en vivo',
    'tabsEventos.previewHeader': 'Purgito',
    'tabsEventos.previewBotTag': 'BOT',
    'tabsEventos.previewToday': 'HOY',
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
    'tabsEventos.emptyTextWarning': 'El mensaje no puede estar vacío si el evento está activo',
    'tabsEventos.varExample': 'Ejemplo:',
    'tabsEventos.templatesBtn': 'Plantillas',
    'tabsEventos.loadTemplate': 'Cargar plantilla',
    'tabsEventos.saveTemplate': 'Guardar como plantilla',
    'tabsEventos.templatePrompt': 'Nombre de la plantilla:',
    'tabsEventos.templateSaved': 'Plantilla guardada',
    'tabsEventos.templateLoaded': 'Plantilla cargada',
    'tabsEventos.noTemplates': 'No hay plantillas guardadas',
  },
  en: {
    // Welcome
    'tabsWelcome.title': 'Welcome',
    'tabsWelcome.subtitle': 'Configure the message Purgito will send when a new member joins your server.',
    'tabsWelcome.toggleLabel': 'Enable welcome',
    'tabsWelcome.toggleHelp': 'Purgito will send this message automatically when a new member joins the server.',
    'tabsWelcome.channelLabel': 'Welcome channel',
    'tabsWelcome.channelHelp': 'Channel where welcome messages will be posted.',

    // Goodbye
    'tabsGoodbye.title': 'Goodbye',
    'tabsGoodbye.subtitle': 'Configure the message Purgito will send when a member leaves your server.',
    'tabsGoodbye.toggleLabel': 'Enable goodbye',
    'tabsGoodbye.toggleHelp': 'Purgito will send this message automatically when a member leaves the server.',
    'tabsGoodbye.channelLabel': 'Goodbye channel',
    'tabsGoodbye.channelHelp': 'Channel where goodbye messages will be posted.',

    // Boosts
    'tabsBoost.title': 'Boosts',
    'tabsBoost.subtitle': 'Configure the message Purgito will send when someone boosts your server.',
    'tabsBoost.toggleLabel': 'Enable boost message',
    'tabsBoost.toggleHelp': 'Purgito will send this message automatically when a member boosts the server.',
    'tabsBoost.channelLabel': 'Boosts channel',
    'tabsBoost.channelHelp': 'Channel where server boosts will be celebrated.',

    // Sections and shared elements
    'tabsEventos.secStatus': 'Status',
    'tabsEventos.statusActive': 'Enabled',
    'tabsEventos.statusInactive': 'Disabled',
    'tabsEventos.secChannel': 'Destination Channel',
    'tabsEventos.channelSelectPlaceholder': 'Choose a channel…',
    'tabsEventos.noPermsWarning': '⚠ Purgito cannot send messages or embeds in this channel.',
    'tabsEventos.secMessage': 'Message',
    'tabsEventos.contentModeLabel': 'Content type',
    'tabsEventos.modePlainText': 'Normal message',
    'tabsEventos.modeClassicEmbed': 'Classic embed',
    'tabsEventos.modeLayoutV2': 'Layout V2',
    'tabsEventos.plainTextLabel': 'Message content',
    'tabsEventos.plainTextPlaceholder': 'Write the message here…',
    'tabsEventos.plainTextCounter': '{count} / 2000 characters',
    'tabsEventos.sectionContent': 'Main content',
    'tabsEventos.sectionAppearance': 'Appearance & color',
    'tabsEventos.sectionImages': 'Images & thumbnails',
    'tabsEventos.sectionAuthor': 'Author',
    'tabsEventos.sectionFooter': 'Footer',
    'tabsEventos.sectionFields': 'Additional fields',
    'tabsEventos.sectionIdentity': 'Custom identity (Webhook)',
    'tabsEventos.embedTitleLabel': 'Embed title',
    'tabsEventos.embedDescLabel': 'Description',
    'tabsEventos.embedColorLabel': 'Sidebar color',
    'tabsEventos.embedThumbLabel': 'Thumbnail',
    'tabsEventos.embedImageLabel': 'Large image',
    'tabsEventos.embedAuthorNameLabel': 'Author name',
    'tabsEventos.embedAuthorIconLabel': 'Author icon',
    'tabsEventos.embedFooterTextLabel': 'Footer text',
    'tabsEventos.embedFooterIconLabel': 'Footer icon',
    'tabsEventos.webhookUsernameLabel': 'Custom username',
    'tabsEventos.webhookAvatarLabel': 'Custom avatar (URL)',
    'tabsEventos.webhookHelp': 'Allows sending the message with a specific custom name and avatar using Discord webhooks.',
    'tabsEventos.addFieldBtn': '+ Add field',
    'tabsEventos.fieldNamePlaceholder': 'Field name',
    'tabsEventos.fieldValuePlaceholder': 'Field value',
    'tabsEventos.fieldInlineLabel': 'Inline',
    'tabsEventos.varsTitle': 'Available variables',
    'tabsEventos.varsSubtitle': 'Click any variable to insert into active field or copy.',
    'tabsEventos.varsSearchPlaceholder': 'Search variables…',
    'tabsEventos.varsCopied': 'Variable {var} copied to clipboard',
    'tabsEventos.varsInserted': 'Variable {var} inserted',
    'tabsEventos.catAll': 'All',
    'tabsEventos.catUser': 'User',
    'tabsEventos.catServer': 'Server',
    'tabsEventos.catChannel': 'Channel',
    'tabsEventos.catBoost': 'Boost',
    'tabsEventos.catDate': 'Date',
    'tabsEventos.previewTitle': 'Live preview',
    'tabsEventos.previewHeader': 'Purgito',
    'tabsEventos.previewBotTag': 'BOT',
    'tabsEventos.previewToday': 'TODAY',
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
    'tabsEventos.emptyTextWarning': 'Message cannot be empty when the event is enabled',
    'tabsEventos.varExample': 'Example:',
    'tabsEventos.templatesBtn': 'Templates',
    'tabsEventos.loadTemplate': 'Load template',
    'tabsEventos.saveTemplate': 'Save as template',
    'tabsEventos.templatePrompt': 'Template name:',
    'tabsEventos.templateSaved': 'Template saved',
    'tabsEventos.templateLoaded': 'Template loaded',
    'tabsEventos.noTemplates': 'No templates saved',
  },
});

const EVENT_CONFIGS = {
  welcome: {
    key: 'welcome',
    icon: 'logIn',
    titleKey: 'tabsWelcome.title',
    subtitleKey: 'tabsWelcome.subtitle',
    toggleLabelKey: 'tabsWelcome.toggleLabel',
    toggleHelpKey: 'tabsWelcome.toggleHelp',
    channelLabelKey: 'tabsWelcome.channelLabel',
    channelHelpKey: 'tabsWelcome.channelHelp',
    placeholderDefault: '¡Bienvenido {user} a {server_name}! Ya somos {server_membercount} miembros.',
  },
  goodbye: {
    key: 'goodbye',
    icon: 'logOut',
    titleKey: 'tabsGoodbye.title',
    subtitleKey: 'tabsGoodbye.subtitle',
    toggleLabelKey: 'tabsGoodbye.toggleLabel',
    toggleHelpKey: 'tabsGoodbye.toggleHelp',
    channelLabelKey: 'tabsGoodbye.channelLabel',
    channelHelpKey: 'tabsGoodbye.channelHelp',
    placeholderDefault: 'Hasta luego {user} 👋 Gracias por haber formado parte de {server_name}.',
  },
  boost: {
    key: 'boost',
    icon: 'star',
    titleKey: 'tabsBoost.title',
    subtitleKey: 'tabsBoost.subtitle',
    toggleLabelKey: 'tabsBoost.toggleLabel',
    toggleHelpKey: 'tabsBoost.toggleHelp',
    channelLabelKey: 'tabsBoost.channelLabel',
    channelHelpKey: 'tabsBoost.channelHelp',
    placeholderDefault: '🚀 ¡Muchas gracias {user} por el boost a {server_name}! Ahora tenemos nivel {server_boostlevel} ({server_boostcount} mejoras).',
  },
};

function getMockContext(eventType) {
  const isEn = (typeof document !== 'undefined' && document.documentElement && document.documentElement.lang === 'en') || false;
  return {
    user: isEn ? '@Test User' : '@Usuario de prueba',
    user_tag: 'usuario_prueba',
    user_name: 'usuario_prueba',
    user_nick: isEn ? 'Test User' : 'Usuario de prueba',
    user_displayname: isEn ? 'Test User' : 'Usuario de prueba',
    user_avatar: 'https://cdn.discordapp.com/embed/avatars/1.png',
    user_id: '987654321012345678',
    user_created_at: isEn ? 'January 15, 2022' : '15 de enero de 2022',
    user_joined_at: isEn ? 'August 21, 2026' : '21 de agosto de 2026',
    user_boost_since: eventType === 'boost' ? (isEn ? 'August 21, 2026' : '21 de agosto de 2026') : 'N/A',
    server_name: isEn ? 'Test Server' : 'Mi Servidor',
    server_id: String(GUILD_ID || '123456789012345678'),
    server_membercount: isEn ? '1,284' : '1.284',
    server_membercount_ordinal: isEn ? '#1,284' : '#1.284',
    server_icon: 'https://cdn.discordapp.com/embed/avatars/0.png',
    server_owner: 'Owner',
    server_owner_id: '111222333444555666',
    server_created_at: isEn ? 'March 10, 2020' : '10 de marzo de 2020',
    server_rolecount: '25',
    server_channelcount: '18',
    server_boostlevel: '2',
    server_boostcount: '9',
    channel: '#general',
    channel_name: 'general',
    channel_id: '555666777888999000',
    server_nextboostlevel: '3',
    server_nextboostlevel_required: '14',
    server_nextboostlevel_until_required: '5',
    date: isEn ? 'August 21, 2026' : '21 de agosto de 2026',
  };
}

function resolvePlaceholders(text, ctx) {
  if (!text || typeof text !== 'string') return text;
  return text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, varName) => {
    return ctx[varName] !== undefined ? ctx[varName] : match;
  });
}

function resolveEmbedForPreview(embed, ctx) {
  if (!embed || typeof embed !== 'object') return {};
  const e = JSON.parse(JSON.stringify(embed));
  if (e.title) e.title = resolvePlaceholders(e.title, ctx);
  if (e.description) e.description = resolvePlaceholders(e.description, ctx);
  if (e.fields && Array.isArray(e.fields)) {
    for (const f of e.fields) {
      if (f && typeof f === 'object') {
        if (f.name) f.name = resolvePlaceholders(f.name, ctx);
        if (f.value) f.value = resolvePlaceholders(f.value, ctx);
      }
    }
  }
  if (e.footer && typeof e.footer === 'object') {
    if (e.footer.text) e.footer.text = resolvePlaceholders(e.footer.text, ctx);
    if (e.footer.icon_url) e.footer.icon_url = resolvePlaceholders(e.footer.icon_url, ctx);
  }
  if (e.author && typeof e.author === 'object') {
    if (e.author.name) e.author.name = resolvePlaceholders(e.author.name, ctx);
    if (e.author.icon_url) e.author.icon_url = resolvePlaceholders(e.author.icon_url, ctx);
  }
  if (e.thumbnail && typeof e.thumbnail === 'object' && e.thumbnail.url) {
    e.thumbnail.url = resolvePlaceholders(e.thumbnail.url, ctx);
  }
  if (e.image && typeof e.image === 'object' && e.image.url) {
    e.image.url = resolvePlaceholders(e.image.url, ctx);
  }
  return e;
}

function resolveBlockForPreview(block, ctx) {
  if (!block || typeof block !== 'object') return {};
  const b = JSON.parse(JSON.stringify(block));
  if (b.type === 'container' && Array.isArray(b.children)) {
    b.children = b.children.map(c => resolveBlockForPreview(c, ctx));
  } else if (b.type === 'text' && b.content) {
    b.content = resolvePlaceholders(b.content, ctx);
  } else if (b.type === 'section') {
    if (Array.isArray(b.texts)) b.texts = b.texts.map(tx => resolvePlaceholders(tx, ctx));
    if (b.accessory && typeof b.accessory === 'object') {
      if (b.accessory.type === 'thumbnail') {
        if (b.accessory.url) b.accessory.url = resolvePlaceholders(b.accessory.url, ctx);
        if (b.accessory.description) b.accessory.description = resolvePlaceholders(b.accessory.description, ctx);
      } else if (b.accessory.type === 'button') {
        if (b.accessory.label) b.accessory.label = resolvePlaceholders(b.accessory.label, ctx);
        if (b.accessory.url) b.accessory.url = resolvePlaceholders(b.accessory.url, ctx);
      }
    }
  } else if (b.type === 'media_gallery' && Array.isArray(b.items)) {
    for (const it of b.items) {
      if (it && typeof it === 'object') {
        if (it.url) it.url = resolvePlaceholders(it.url, ctx);
        if (it.description) it.description = resolvePlaceholders(it.description, ctx);
      }
    }
  } else if (b.type === 'action_row' && Array.isArray(b.buttons)) {
    for (const btn of b.buttons) {
      if (btn && typeof btn === 'object') {
        if (btn.label) btn.label = resolvePlaceholders(btn.label, ctx);
        if (btn.url) btn.url = resolvePlaceholders(btn.url, ctx);
      }
    }
  }
  return b;
}

export async function loadWelcomeTab() {
  return loadEventPage('welcome');
}

export async function loadGoodbyeTab() {
  return loadEventPage('goodbye');
}

export async function loadBoostTab() {
  return loadEventPage('boost');
}

export async function loadEventosTab(eventType = 'welcome') {
  return loadEventPage(eventType);
}

async function loadEventPage(eventType) {
  const myGuild = GUILD_ID;
  const box = content();
  box.innerHTML = '';
  box.append(spinner());

  try {
    const [eventsData, channels, roles] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/events`),
      getChannels(),
      getRoles(),
    ]);

    if (myGuild !== GUILD_ID) return;
    renderDedicatedEventView(box, eventType, eventsData, channels, roles);
  } catch (err) {
    if (myGuild !== GUILD_ID) return;
    renderError(box, err);
  }
}

function renderDedicatedEventView(container, eventType, initialData, channels, roles) {
  container.innerHTML = '';

  const cfg = EVENT_CONFIGS[eventType] || EVENT_CONFIGS.welcome;
  const serverEvents = initialData.events || {};
  const allVariables = initialData.variables || [];

  // Track focused input for smart variable insertion
  let lastActiveInput = null;

  // Header dedicado
  const header = el('div', { class: 'tab-header' },
    el('h1', {}, el('span', { class: 'nav-icon' }, icon(cfg.icon)), t(cfg.titleKey)),
    el('p', { class: 'dim' }, t(cfg.subtitleKey))
  );
  container.append(header);

  // Configuration state
  const evConfig = serverEvents[eventType] || {
    enabled: false,
    channel_id: '',
    content_mode: 'plain_text',
    message: cfg.placeholderDefault,
    embed_json: null,
  };

  let isEnabled = !!evConfig.enabled;
  let selectedChannelId = evConfig.channel_id ? String(evConfig.channel_id) : (channels.length ? String(channels[0].id) : '');
  let currentMode = evConfig.content_mode || 'plain_text';
  let currentMessage = evConfig.message !== undefined && evConfig.message !== null ? evConfig.message : cfg.placeholderDefault;
  let customUsername = '';
  let customAvatarUrl = '';

  // Embed and Layout state
  let localEmbedDoc = blankDoc();
  let localLayoutDoc = blankLayoutDoc();

  if (currentMode === 'classic_embed' && evConfig.embed_json) {
    try {
      const parsed = JSON.parse(evConfig.embed_json);
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

  if (currentMode === 'layout_v2' && evConfig.embed_json) {
    try {
      const parsed = JSON.parse(evConfig.embed_json);
      if (parsed && parsed.send_options) {
        customUsername = parsed.send_options.username || '';
        customAvatarUrl = parsed.send_options.avatar_url || '';
      }
      localLayoutDoc.blocks = (parsed.blocks || []).map(apiToBlock);
    } catch (e) {
      localLayoutDoc = blankLayoutDoc();
    }
  }

  if (!localEmbedDoc.embeds.length) {
    localEmbedDoc.embeds.push(blankEmbed());
  }
  const embedState = localEmbedDoc.embeds[0];

  // Panes
  const editorPane = el('div', { class: 'event-editor-pane' });
  const previewPane = el('div', { class: 'event-preview-pane' });

  // Helper for tracking focused input
  function registerInputFocus(inputNode) {
    inputNode.addEventListener('focus', () => { lastActiveInput = inputNode; });
    inputNode.addEventListener('click', () => { lastActiveInput = inputNode; });
  }

  // 1. SECCIÓN: ESTADO
  const toggleChk = el('input', {
    type: 'checkbox',
    checked: isEnabled,
  });

  const toggleStatusBadge = el('span', {
    class: 'badge ' + (isEnabled ? 'badge-ok' : 'badge-dim'),
  }, isEnabled ? `● ${t('tabsEventos.statusActive')}` : `○ ${t('tabsEventos.statusInactive')}`);

  toggleChk.onchange = () => {
    isEnabled = toggleChk.checked;
    toggleStatusBadge.className = 'badge ' + (isEnabled ? 'badge-ok' : 'badge-dim');
    toggleStatusBadge.textContent = isEnabled ? `● ${t('tabsEventos.statusActive')}` : `○ ${t('tabsEventos.statusInactive')}`;
  };

  const statusCard = el('div', { class: 'card event-section-card' },
    el('div', { class: 'event-section-header' },
      el('h3', { class: 'section-title' }, t('tabsEventos.secStatus')),
      toggleStatusBadge
    ),
    el('label', { class: 'toggle' },
      toggleChk,
      el('span', { class: 'toggle-label' }, t(cfg.toggleLabelKey)),
      helpIcon(t(cfg.toggleHelpKey))
    ),
    el('p', { class: 'dim text-sm', style: 'margin: 4px 0 0 0;' }, t(cfg.toggleHelpKey))
  );

  // 2. SECCIÓN: CANAL
  const channelSel = channelSelect(channels, selectedChannelId, t('tabsEventos.channelSelectPlaceholder'));
  const channelWarning = el('p', { class: 'form-error-msg', style: 'display: none; margin-top: 6px;' },
    t('tabsEventos.noPermsWarning')
  );

  function checkChannelPerms() {
    const ch = channels.find(c => String(c.id) === String(selectedChannelId));
    if (ch && ch.can_send === false) {
      channelWarning.style.display = 'block';
    } else {
      channelWarning.style.display = 'none';
    }
  }

  channelSel.onchange = () => {
    selectedChannelId = channelSel.value;
    checkChannelPerms();
    updateLivePreview();
  };
  checkChannelPerms();

  const channelCard = el('div', { class: 'card event-section-card' },
    el('h3', { class: 'section-title' }, t('tabsEventos.secChannel')),
    formGroup(t(cfg.channelLabelKey), channelSel, channelWarning),
    el('p', { class: 'dim text-sm', style: 'margin: 0;' }, t(cfg.channelHelpKey))
  );

  // 3. SECCIÓN: MENSAJE (Contenido Principal)
  const modePillsWrap = el('div', { class: 'event-mode-pills' });
  const modeModes = [
    { key: 'plain_text', label: t('tabsEventos.modePlainText'), icon: 'chat' },
    { key: 'classic_embed', label: t('tabsEventos.modeClassicEmbed'), icon: 'layout' },
    { key: 'layout_v2', label: t('tabsEventos.modeLayoutV2'), icon: 'sparkle' },
  ];

  const contentEditorBody = el('div', { class: 'event-content-editor-wrap' });

  function renderModeSelector() {
    modePillsWrap.innerHTML = '';
    for (const m of modeModes) {
      const pill = el('button', {
        type: 'button',
        class: 'mode-pill' + (currentMode === m.key ? ' active' : ''),
        onclick: () => {
          if (currentMode === m.key) return;
          currentMode = m.key;
          renderModeSelector();
          renderContentEditor();
          updateLivePreview();
        },
      },
        el('span', { class: 'mode-pill-icon' }, icon(m.icon)),
        m.label
      );
      modePillsWrap.append(pill);
    }
  }

  function renderContentEditor() {
    contentEditorBody.innerHTML = '';

    if (currentMode === 'plain_text') {
      const txtArea = el('textarea', {
        class: 'form-control autogrow',
        rows: 4,
        placeholder: cfg.placeholderDefault,
      });
      txtArea.value = currentMessage;
      registerInputFocus(txtArea);

      const counter = el('div', { class: 'char-counter' },
        t('tabsEventos.plainTextCounter', { count: currentMessage.length })
      );

      txtArea.oninput = () => {
        currentMessage = txtArea.value;
        autoGrow(txtArea);
        counter.textContent = t('tabsEventos.plainTextCounter', { count: currentMessage.length });
        counter.className = 'char-counter' + (currentMessage.length > 2000 ? ' over' : '');
        updateLivePreview();
      };

      contentEditorBody.append(
        formGroup(t('tabsEventos.plainTextLabel'), txtArea, counter)
      );
    } else if (currentMode === 'classic_embed') {
      const s = embedState;

      function boundInput(key, placeholder, isArea = false, maxL = null) {
        const input = el(isArea ? 'textarea' : 'input', {
          class: 'form-control' + (isArea ? ' autogrow' : ''),
          placeholder,
          maxlength: maxL ? String(maxL) : null,
        });
        input.value = s[key] || '';
        registerInputFocus(input);
        input.oninput = () => {
          s[key] = input.value;
          if (isArea) autoGrow(input);
          updateLivePreview();
        };
        return input;
      }

      // Templates Action Bar
      const templateBar = el('div', { class: 'template-action-bar' },
        el('button', {
          type: 'button',
          class: 'btn btn-secondary btn-xs',
          onclick: async () => {
            try {
              const res = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`);
              const templates = res.templates || [];
              if (!templates.length) {
                toast(t('tabsEventos.noTemplates'), 'info');
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
                  updateLivePreview();
                  toast(t('tabsEventos.templateLoaded'), 'ok');
                }
              }
            } catch (e) {
              toast(e.message || 'Error', 'err');
            }
          },
        }, icon('layout'), t('tabsEventos.loadTemplate')),
        el('button', {
          type: 'button',
          class: 'btn btn-secondary btn-xs',
          onclick: async () => {
            const name = (prompt(t('tabsEventos.templatePrompt')) || '').trim();
            if (!name) return;
            try {
              const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
              await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`, {
                method: 'POST',
                body: JSON.stringify({ name, embeds: rawDicts }),
              });
              toast(t('tabsEventos.templateSaved'), 'ok');
            } catch (e) {
              toast(e.message || 'Error', 'err');
            }
          },
        }, icon('star'), t('tabsEventos.saveTemplate'))
      );

      // Accordion Groups
      const contentSec = accordionGroup(t('tabsEventos.sectionContent'), true,
        formGroup(t('tabsEventos.embedTitleLabel'), boundInput('title', 'Título del mensaje', false, EMBED_LIMITS.title)),
        formGroup(t('tabsEventos.embedDescLabel'), boundInput('description', 'Descripción del mensaje…', true, EMBED_LIMITS.description))
      );

      const appearanceSec = accordionGroup(t('tabsEventos.sectionAppearance'), false,
        formGroup(t('tabsEventos.embedColorLabel'), colorField(s, 'color', () => updateLivePreview()))
      );

      const imagesSec = accordionGroup(t('tabsEventos.sectionImages'), false,
        formGroup(t('tabsEventos.embedThumbLabel'), imageField(s, 'thumbnail', () => updateLivePreview(), { gif: true })),
        formGroup(t('tabsEventos.embedImageLabel'), imageField(s, 'image', () => updateLivePreview(), { gif: true }))
      );

      const authorSec = accordionGroup(t('tabsEventos.sectionAuthor'), false,
        formGroup(t('tabsEventos.embedAuthorNameLabel'), boundInput('author_name', 'Nombre del autor', false, EMBED_LIMITS.author)),
        formGroup(t('tabsEventos.embedAuthorIconLabel'), imageField(s, 'author_icon_url', () => updateLivePreview()))
      );

      const footerSec = accordionGroup(t('tabsEventos.sectionFooter'), false,
        formGroup(t('tabsEventos.embedFooterTextLabel'), boundInput('footer_text', 'Pie de página', false, EMBED_LIMITS.footer)),
        formGroup(t('tabsEventos.embedFooterIconLabel'), imageField(s, 'footer_icon_url', () => updateLivePreview()))
      );

      // Fields
      const fieldsListWrap = el('div', { class: 'embed-fields-container' });
      s.fields = s.fields || [];

      function renderFields() {
        fieldsListWrap.innerHTML = '';
        s.fields.forEach((f, idx) => {
          const fName = el('input', {
            class: 'form-control',
            placeholder: t('tabsEventos.fieldNamePlaceholder'),
            value: f.name || '',
            maxlength: String(EMBED_LIMITS.fieldName),
          });
          registerInputFocus(fName);
          fName.oninput = () => { f.name = fName.value; updateLivePreview(); };

          const fVal = el('input', {
            class: 'form-control',
            placeholder: t('tabsEventos.fieldValuePlaceholder'),
            value: f.value || '',
            maxlength: String(EMBED_LIMITS.fieldValue),
          });
          registerInputFocus(fVal);
          fVal.oninput = () => { f.value = fVal.value; updateLivePreview(); };

          const inlineChk = el('input', {
            type: 'checkbox',
            checked: !!f.inline,
            onchange: () => { f.inline = inlineChk.checked; updateLivePreview(); },
          });

          const delBtn = el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-xs',
            onclick: () => { s.fields.splice(idx, 1); renderFields(); updateLivePreview(); },
          }, '✕');

          const row = el('div', { class: 'embed-field-item' },
            el('div', { class: 'field-inputs' }, fName, fVal),
            el('div', { class: 'field-controls' },
              el('label', { class: 'toggle toggle-xs' }, inlineChk, t('tabsEventos.fieldInlineLabel')),
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
          updateLivePreview();
        },
      }, t('tabsEventos.addFieldBtn'));

      renderFields();
      const fieldsSec = accordionGroup(t('tabsEventos.sectionFields'), false,
        fieldsListWrap,
        el('div', { style: 'margin-top: 10px;' }, addFieldBtn)
      );

      // Webhook Identity
      const customUserInp = el('input', {
        class: 'form-control',
        placeholder: 'Nombre personalizado',
        value: customUsername,
      });
      registerInputFocus(customUserInp);
      customUserInp.oninput = () => { customUsername = customUserInp.value; updateLivePreview(); };

      const customAvatarInp = el('input', {
        class: 'form-control',
        placeholder: 'https://ejemplo.com/avatar.png',
        value: customAvatarUrl,
      });
      registerInputFocus(customAvatarInp);
      customAvatarInp.oninput = () => { customAvatarUrl = customAvatarInp.value; updateLivePreview(); };

      const identitySec = accordionGroup(t('tabsEventos.sectionIdentity'), false,
        el('p', { class: 'dim form-hint', style: 'margin-top:0' }, t('tabsEventos.webhookHelp')),
        formGroup(t('tabsEventos.webhookUsernameLabel'), customUserInp),
        formGroup(t('tabsEventos.webhookAvatarLabel'), customAvatarInp)
      );

      contentEditorBody.append(templateBar, contentSec, appearanceSec, imagesSec, authorSec, footerSec, fieldsSec, identitySec);
    } else if (currentMode === 'layout_v2') {
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
                  updateLivePreview();
                },
              }, '✕')
            )
          );

          if (b.type === 'text') {
            const ta = el('textarea', { class: 'form-control autogrow' });
            ta.value = b.content || '';
            registerInputFocus(ta);
            ta.oninput = () => { b.content = ta.value; autoGrow(ta); updateLivePreview(); };
            blockRow.append(ta);
          } else if (b.type === 'section') {
            const ta = el('textarea', { class: 'form-control autogrow' });
            ta.value = (b.texts && b.texts[0]) || '';
            registerInputFocus(ta);
            ta.oninput = () => { b.texts = [ta.value]; autoGrow(ta); updateLivePreview(); };
            blockRow.append(formGroup('Texto', ta));
            if (b.accessory && b.accessory.type === 'button') {
              const lbl = el('input', { class: 'form-control', value: b.accessory.label || '', placeholder: 'Etiqueta del botón' });
              registerInputFocus(lbl);
              lbl.oninput = () => { b.accessory.label = lbl.value; updateLivePreview(); };
              const url = el('input', { class: 'form-control', value: b.accessory.url || '', placeholder: 'https://...' });
              registerInputFocus(url);
              url.oninput = () => { b.accessory.url = url.value; updateLivePreview(); };
              blockRow.append(formGroup('Botón de enlace', el('div', { class: 'grid-2' }, lbl, url)));
            }
          } else if (b.type === 'action_row') {
            const btnsWrap = el('div', { class: 'action-row-buttons' });
            (b.buttons || []).forEach((btn) => {
              const lbl = el('input', { class: 'form-control', value: btn.label || '', placeholder: 'Etiqueta' });
              registerInputFocus(lbl);
              lbl.oninput = () => { btn.label = lbl.value; updateLivePreview(); };
              const url = el('input', { class: 'form-control', value: btn.url || '', placeholder: 'https://...' });
              registerInputFocus(url);
              url.oninput = () => { btn.url = url.value; updateLivePreview(); };
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
          onclick: () => { localLayoutDoc.blocks.push(newBlock('text')); refreshLayoutBlocks(); updateLivePreview(); },
        }, '+ Texto'),
        el('button', {
          type: 'button',
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            const sec = newBlock('section');
            sec.accessory = { type: 'button', style: 'link', label: 'Enlace', url: 'https://discord.com' };
            localLayoutDoc.blocks.push(sec);
            refreshLayoutBlocks();
            updateLivePreview();
          },
        }, '+ Sección con Botón'),
        el('button', {
          type: 'button',
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            const row = newBlock('action_row');
            localLayoutDoc.blocks.push(row);
            refreshLayoutBlocks();
            updateLivePreview();
          },
        }, '+ Fila de Botones')
      );

      if (!localLayoutDoc.blocks.length) {
        localLayoutDoc.blocks.push({ type: 'text', content: cfg.placeholderDefault });
      }

      refreshLayoutBlocks();

      const customUserInp = el('input', {
        class: 'form-control',
        placeholder: 'Nombre personalizado',
        value: customUsername,
      });
      registerInputFocus(customUserInp);
      customUserInp.oninput = () => { customUsername = customUserInp.value; updateLivePreview(); };

      const customAvatarInp = el('input', {
        class: 'form-control',
        placeholder: 'https://ejemplo.com/avatar.png',
        value: customAvatarUrl,
      });
      registerInputFocus(customAvatarInp);
      customAvatarInp.oninput = () => { customAvatarUrl = customAvatarInp.value; updateLivePreview(); };

      const identitySec = accordionGroup(t('tabsEventos.sectionIdentity'), false,
        el('p', { class: 'dim form-hint', style: 'margin-top:0' }, t('tabsEventos.webhookHelp')),
        formGroup(t('tabsEventos.webhookUsernameLabel'), customUserInp),
        formGroup(t('tabsEventos.webhookAvatarLabel'), customAvatarInp)
      );

      contentEditorBody.append(blocksList, addBlockBtns, identitySec);
    }
  }

  renderModeSelector();
  renderContentEditor();

  const messageCard = el('div', { class: 'card event-section-card' },
    el('h3', { class: 'section-title' }, t('tabsEventos.secMessage')),
    formGroup(t('tabsEventos.contentModeLabel'), modePillsWrap),
    contentEditorBody
  );

  // 4. SECCIÓN: VARIABLES DISPONIBLES (Compacta y contextual)
  // Filtrar variables aplicables al evento actual
  const eventVariables = allVariables.filter(v => {
    if (!v.allowed_events || !Array.isArray(v.allowed_events)) return true;
    return v.allowed_events.includes(eventType);
  });

  const varCategories = [
    { key: 'all', label: t('tabsEventos.catAll') },
    { key: 'user', label: t('tabsEventos.catUser') },
    { key: 'server', label: t('tabsEventos.catServer') },
    { key: 'channel', label: t('tabsEventos.catChannel') },
  ];
  if (eventType === 'boost') {
    varCategories.push({ key: 'boost', label: t('tabsEventos.catBoost') });
  }
  varCategories.push({ key: 'date', label: t('tabsEventos.catDate') });

  let activeVarCategory = 'all';
  let varSearchQuery = '';

  const varSearchInp = el('input', {
    type: 'search',
    class: 'form-control form-control-sm',
    placeholder: t('tabsEventos.varsSearchPlaceholder'),
  });

  const varTabsWrap = el('div', { class: 'var-category-tabs' });
  const varListGrid = el('div', { class: 'var-chips-grid-compact' });

  function renderVarChips() {
    varListGrid.innerHTML = '';
    const q = varSearchQuery.toLowerCase().trim();

    const filtered = eventVariables.filter(v => {
      const matchCat = activeVarCategory === 'all' || v.category === activeVarCategory;
      if (!matchCat) return false;
      if (!q) return true;
      return v.name.toLowerCase().includes(q) || (v.description && v.description.toLowerCase().includes(q));
    });

    for (const v of filtered) {
      const varTag = `{${v.name}}`;
      const chip = el('button', {
        type: 'button',
        class: 'var-chip-compact',
        title: `${v.description || ''} (${t('tabsEventos.varExample')} ${v.example || ''})`,
        onclick: () => {
          if (lastActiveInput && typeof lastActiveInput.value === 'string') {
            const start = lastActiveInput.selectionStart || lastActiveInput.value.length;
            const end = lastActiveInput.selectionEnd || lastActiveInput.value.length;
            const val = lastActiveInput.value;
            lastActiveInput.value = val.substring(0, start) + varTag + val.substring(end);
            lastActiveInput.selectionStart = lastActiveInput.selectionEnd = start + varTag.length;
            lastActiveInput.dispatchEvent(new Event('input', { bubbles: true }));
            lastActiveInput.focus();
            toast(t('tabsEventos.varsInserted', { var: varTag }), 'ok');
          } else {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(varTag);
              toast(t('tabsEventos.varsCopied', { var: varTag }), 'ok');
            }
          }
        },
      },
        el('code', { class: 'var-tag' }, varTag),
        el('span', { class: 'var-desc' }, v.description || '')
      );
      varListGrid.append(chip);
    }
  }

  function renderVarCategoryTabs() {
    varTabsWrap.innerHTML = '';
    for (const cat of varCategories) {
      const btn = el('button', {
        type: 'button',
        class: 'category-tab-btn' + (activeVarCategory === cat.key ? ' active' : ''),
        onclick: () => {
          activeVarCategory = cat.key;
          renderVarCategoryTabs();
          renderVarChips();
        },
      }, cat.label);
      varTabsWrap.append(btn);
    }
  }

  varSearchInp.oninput = () => {
    varSearchQuery = varSearchInp.value;
    renderVarChips();
  };

  renderVarCategoryTabs();
  renderVarChips();

  const variablesCard = el('div', { class: 'card event-section-card event-variables-card' },
    el('div', { class: 'event-section-header' },
      el('h3', { class: 'section-title' }, t('tabsEventos.varsTitle')),
      el('span', { class: 'dim text-xs' }, t('tabsEventos.varsSubtitle'))
    ),
    el('div', { class: 'var-controls-row' }, varSearchInp, varTabsWrap),
    varListGrid
  );

  // 5. SECCIÓN: ACCIONES TOOLBAR
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
        const payload = {
          enabled: isEnabled,
          channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
          content_mode: currentMode,
        };

        const sendOpts = (customUsername.trim() || customAvatarUrl.trim())
          ? { username: customUsername.trim(), avatar_url: customAvatarUrl.trim() }
          : null;

        if (currentMode === 'plain_text') {
          payload.message = currentMessage;
        } else if (currentMode === 'classic_embed') {
          payload.embeds = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
          if (sendOpts) payload.send_options = sendOpts;
        } else if (currentMode === 'layout_v2') {
          payload.layout = { blocks: localLayoutDoc.blocks };
          if (sendOpts) payload.send_options = sendOpts;
        }

        const res = await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });

        serverEvents[eventType] = res.event;
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
        await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}/test`, { method: 'POST' });
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
        serverEvents[eventType] = {
          enabled: false,
          channel_id: '',
          content_mode: 'plain_text',
          message: cfg.placeholderDefault,
          embed_json: null,
        };
        toast(t('tabsEventos.resetSuccess'), 'ok');
        renderDedicatedEventView(container, eventType, initialData, channels, roles);
      } catch (err) {
        toast(err.message || 'Error al restablecer', 'err');
      }
    },
  }, icon('trash'), t('tabsEventos.resetBtn'));

  const actionsBar = el('div', { class: 'event-actions-bar' },
    el('div', { class: 'left-actions' }, saveBtn, testBtn),
    resetBtn
  );

  editorPane.append(statusCard, channelCard, messageCard, variablesCard, actionsBar);

  // LIVE PREVIEW
  function updateLivePreview() {
    previewPane.innerHTML = '';
    const ctx = getMockContext(eventType);

    const ch = channels.find(c => String(c.id) === String(selectedChannelId));
    if (ch) {
      ctx.channel = '#' + ch.name;
      ctx.channel_name = ch.name;
      ctx.channel_id = String(ch.id);
    }

    const previewAuthorName = customUsername || t('tabsEventos.previewHeader');
    const previewAvatarUrl = customAvatarUrl || '/assets/icon.png';

    const msgHeader = el('div', { class: 'd-msg-header' },
      el('img', { src: previewAvatarUrl, alt: 'Purgito', class: 'd-msg-avatar' }),
      el('div', { class: 'd-msg-meta' },
        el('span', { class: 'd-msg-author' }, previewAuthorName),
        el('span', { class: 'd-msg-bot' }, t('tabsEventos.previewBotTag')),
        el('span', { class: 'd-msg-time' }, t('tabsEventos.previewToday'))
      )
    );

    const msgBody = el('div', { class: 'd-msg-body' });

    if (currentMode === 'plain_text') {
      const resolved = resolvePlaceholders(currentMessage, ctx);
      msgBody.append(el('div', { class: 'd-msg-text' }, ...mdToNodes(resolved)));
    } else if (currentMode === 'classic_embed') {
      const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
      const resolvedEmbeds = rawDicts.map(e => resolveEmbedForPreview(e, ctx));
      msgBody.append(renderEmbedsPreview(resolvedEmbeds));
    } else if (currentMode === 'layout_v2') {
      const resolvedBlocks = localLayoutDoc.blocks.map(b => resolveBlockForPreview(b, ctx));
      msgBody.append(renderLayoutPreview(resolvedBlocks));
    }

    const discordCard = el('div', { class: 'd-message-card' },
      el('div', { class: 'd-message-top' },
        el('div', { class: 'd-message-channel-tag' },
          icon('chat'),
          el('span', {}, ch ? '#' + ch.name : '#general')
        ),
        el('span', { class: 'preview-badge dim' }, t('tabsEventos.previewTitle'))
      ),
      el('div', { class: 'd-message' }, msgHeader, msgBody)
    );

    previewPane.append(discordCard);
  }

  updateLivePreview();

  const workspaceGrid = el('div', { class: 'event-workspace-grid' },
    editorPane,
    el('div', { class: 'event-preview-pane-wrap' }, previewPane)
  );

  container.append(workspaceGrid);
}
