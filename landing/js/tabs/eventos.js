// Módulos independientes de Eventos del Servidor: Bienvenidas, Despedidas y Boosts.
// Arquitectura compacta, clara, componible y de alta densidad visual con Live Preview fiel a Discord.

import { apiFetch } from '/js/core/api.js';
import {
  el, spinner, renderError, toast, autoGrow, helpIcon, icon,
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
    'tabsEventos.secMainConfig': 'Configuración principal',
    'tabsEventos.secContent': 'Contenido',
    'tabsEventos.secAdvanced': 'Opciones avanzadas',
    'tabsEventos.channelSelectPlaceholder': 'Elige un canal…',
    'tabsEventos.noPermsWarning': '⚠ Purgito no puede enviar mensajes o embeds en este canal.',
    'tabsEventos.secMessage': 'Mensaje de texto',
    'tabsEventos.secEmbed': 'Embed de Discord',
    'tabsEventos.secButtons': 'Botones interactivos',
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
    'tabsEventos.insertVarBtn': 'Insertar variable',
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
    'tabsEventos.previewEmpty': 'No hay contenido activo. Activa el mensaje de texto o el embed para ver la vista previa.',
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
    'tabsEventos.buttonsTitle': 'Botones',
    'tabsEventos.buttonsHelp': 'Añade botones de enlace o de rol a tu bienvenida.',
    'tabsEventos.addButton': '+ Añadir botón',
    'tabsEventos.buttonLabelPlaceholder': 'Etiqueta del botón',
    'tabsEventos.buttonUrlPlaceholder': 'https://ejemplo.com',
    'tabsEventos.buttonTypeLink': 'Enlace (URL)',
    'tabsEventos.buttonTypeRole': 'Rol (Toggle)',
    'tabsEventos.buttonColorPrimary': 'Azul (Primary)',
    'tabsEventos.buttonColorSecondary': 'Gris (Secondary)',
    'tabsEventos.buttonColorSuccess': 'Verde (Success)',
    'tabsEventos.buttonColorDanger': 'Rojo (Danger)',
    'tabsEventos.useLayoutV2': 'Usar Layout V2 (Editor avanzado de bloques)',
    'tabsEventos.layoutV2Hint': 'Permite diseñar mensajes con la arquitectura moderna de bloques de Discord.',
    'tabsEventos.close': 'Cerrar',
    'tabsEventos.quickVars': 'Variables rápidas:',
    'tabsEventos.eventDisabledNotice': 'La bienvenida está desactivada. Actívala arriba para enviar mensajes automáticamente.',
    'tabsEventos.eventDisabledNoticeGoodbye': 'Las despedidas están desactivadas. Actívalas arriba para enviar mensajes automáticamente.',
    'tabsEventos.eventDisabledNoticeBoost': 'Los mensajes de boost están desactivados. Actívalos arriba para enviar mensajes automáticamente.',
    'tabsEventos.legacyDualNoticeText': 'Esta configuración también tiene un mensaje de texto guardado.',
    'tabsEventos.legacyDualNoticeEmbed': 'Esta configuración también tiene un embed guardado.',
    'tabsEventos.legacyDualSwitchText': 'Ver mensaje',
    'tabsEventos.legacyDualSwitchEmbed': 'Ver embed',
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
    'tabsEventos.secMainConfig': 'Main Configuration',
    'tabsEventos.secContent': 'Content',
    'tabsEventos.secAdvanced': 'Advanced Options',
    'tabsEventos.channelSelectPlaceholder': 'Choose a channel…',
    'tabsEventos.noPermsWarning': '⚠ Purgito cannot send messages or embeds in this channel.',
    'tabsEventos.secMessage': 'Text Message',
    'tabsEventos.secEmbed': 'Discord Embed',
    'tabsEventos.secButtons': 'Interactive Buttons',
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
    'tabsEventos.insertVarBtn': 'Insert variable',
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
    'tabsEventos.previewEmpty': 'No active content. Enable text message or embed to see live preview.',
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
    'tabsEventos.buttonsTitle': 'Buttons',
    'tabsEventos.buttonsHelp': 'Add optional link or role buttons to your welcome message.',
    'tabsEventos.addButton': '+ Add button',
    'tabsEventos.buttonLabelPlaceholder': 'Button label',
    'tabsEventos.buttonUrlPlaceholder': 'https://example.com',
    'tabsEventos.buttonTypeLink': 'Link (URL)',
    'tabsEventos.buttonTypeRole': 'Role (Toggle)',
    'tabsEventos.buttonColorPrimary': 'Blurple (Primary)',
    'tabsEventos.buttonColorSecondary': 'Grey (Secondary)',
    'tabsEventos.buttonColorSuccess': 'Green (Success)',
    'tabsEventos.buttonColorDanger': 'Red (Danger)',
    'tabsEventos.useLayoutV2': 'Use Layout V2 (Advanced block editor)',
    'tabsEventos.layoutV2Hint': 'Allows designing messages using Discord Components V2 block architecture.',
    'tabsEventos.close': 'Close',
    'tabsEventos.quickVars': 'Quick variables:',
    'tabsEventos.eventDisabledNotice': 'Welcome is disabled. Enable it above to automatically send messages.',
    'tabsEventos.eventDisabledNoticeGoodbye': 'Goodbyes are disabled. Enable it above to automatically send messages.',
    'tabsEventos.eventDisabledNoticeBoost': 'Boost messages are disabled. Enable it above to automatically send messages.',
    'tabsEventos.legacyDualNoticeText': 'This configuration also has a saved text message.',
    'tabsEventos.legacyDualNoticeEmbed': 'This configuration also has a saved embed.',
    'tabsEventos.legacyDualSwitchText': 'View message',
    'tabsEventos.legacyDualSwitchEmbed': 'View embed',
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
    disabledNoticeKey: 'tabsEventos.eventDisabledNotice',
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
    disabledNoticeKey: 'tabsEventos.eventDisabledNoticeGoodbye',
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
    disabledNoticeKey: 'tabsEventos.eventDisabledNoticeBoost',
    placeholderDefault: '🚀 ¡Muchas gracias {user} por el boost a {server_name}! Ahora tenemos nivel {server_boostlevel} ({server_boostcount} mejoras).',
  },
};

function getMockContext(eventType) {
  const isEn = (typeof document !== 'undefined' && document.documentElement && document.documentElement.lang === 'en') || false;
  return {
    user: isEn ? '@TestUser' : '@Usuario',
    user_tag: 'usuario_prueba',
    user_name: 'usuario_prueba',
    user_nick: isEn ? 'Test User' : 'Usuario',
    user_displayname: isEn ? 'Test User' : 'Usuario',
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

  // Filter variables applicable to current event
  const eventVariables = allVariables.filter(v => {
    if (!v.allowed_events || !Array.isArray(v.allowed_events)) return true;
    return v.allowed_events.includes(eventType);
  });

  // Track focused input for smart variable insertion
  let lastActiveInput = null;

  function registerInputFocus(inputNode) {
    inputNode.addEventListener('focus', () => { lastActiveInput = inputNode; });
    inputNode.addEventListener('click', () => { lastActiveInput = inputNode; });
  }

  // Load existing event configuration
  const evConfig = serverEvents[eventType] || {
    enabled: false,
    channel_id: '',
    content_mode: 'plain_text',
    message: cfg.placeholderDefault,
    embed_json: null,
  };

  let isEnabled = !!evConfig.enabled;
  let selectedChannelId = evConfig.channel_id ? String(evConfig.channel_id) : (channels.length ? String(channels[0].id) : '');
  const savedMode = evConfig.content_mode || 'plain_text';

  let currentMessage = evConfig.message !== undefined && evConfig.message !== null ? evConfig.message : cfg.placeholderDefault;
  let customUsername = '';
  let customAvatarUrl = '';
  let buttons = [];

  // State: Component enablement
  // format reemplaza a los antiguos isMessageEnabled/isEmbedEnabled independientes:
  // Texto y Embed pasan a ser mutuamente excluyentes para configuraciones nuevas.
  let format = 'text';
  let isLayoutV2 = savedMode === 'layout_v2';
  let isButtonsEnabled = false;
  // true solo si una configuración legacy 'composite' tiene AMBOS mensaje y embed
  // con contenido real: el que no se ve activo no se pierde hasta que se guarde.
  let hasLegacyDual = false;

  let localEmbedDoc = blankDoc();
  let localLayoutDoc = blankLayoutDoc();

  // Parse embed_json from server
  if (evConfig.embed_json) {
    try {
      const parsed = JSON.parse(evConfig.embed_json);
      if (savedMode === 'layout_v2') {
        if (parsed && parsed.send_options) {
          customUsername = parsed.send_options.username || '';
          customAvatarUrl = parsed.send_options.avatar_url || '';
        }
        localLayoutDoc.blocks = (parsed.blocks || []).map(apiToBlock);
      } else {
        // Classic or Composite mode
        const list = Array.isArray(parsed) ? parsed : (parsed.embeds || []);
        if (parsed && !Array.isArray(parsed)) {
          if (parsed.send_options) {
            customUsername = parsed.send_options.username || '';
            customAvatarUrl = parsed.send_options.avatar_url || '';
          }
          if (Array.isArray(parsed.buttons)) {
            buttons = parsed.buttons.map(b => ({ ...b }));
          }
        }
        if (list.length > 0) {
          localEmbedDoc.embeds = list.map(e => ({ ...e }));
        }
      }
    } catch (e) {
      localEmbedDoc = blankDoc();
    }
  }

  // Setup initial format based on saved data
  const hasRealText = Boolean(evConfig.message && evConfig.message.trim());
  const hasRealEmbed = Boolean(localEmbedDoc.embeds.some(e => e.title || e.description || e.image || e.thumbnail || (e.fields && e.fields.length)));

  if (savedMode === 'classic_embed') {
    format = 'embed';
  } else if (savedMode === 'composite') {
    if (hasRealText && hasRealEmbed) {
      // Legacy real: ambos formatos tienen contenido. Se muestra Embed por
      // defecto y se avisa que el mensaje de texto sigue ahí, sin tocarlo.
      format = 'embed';
      hasLegacyDual = true;
    } else if (hasRealEmbed) {
      format = 'embed';
    } else {
      format = 'text';
    }
  } else if (savedMode === 'layout_v2') {
    isLayoutV2 = true;
  } else {
    // plain_text
    format = 'text';
  }

  isButtonsEnabled = buttons.length > 0;

  if (!localEmbedDoc.embeds.length) {
    localEmbedDoc.embeds.push(blankEmbed());
  }
  const embedState = localEmbedDoc.embeds[0];

  // Root panes
  const rootWrapper = el('div', { class: 'purg-event-wrapper' });
  const editorPane = el('div', { class: 'event-editor-pane' });
  const previewPane = el('div', { class: 'event-preview-pane' });

  // ─────────────────────────────────────────────────────────────
  // 1. SMART VARIABLES MODAL / FLOATING POPOVER
  // ─────────────────────────────────────────────────────────────
  function openVariablesModal(targetInput) {
    const existingModal = document.getElementById('purg-variables-modal-backdrop');
    if (existingModal) existingModal.remove();

    const target = targetInput || lastActiveInput;

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

    let activeCat = 'all';
    let searchQuery = '';

    const searchInput = el('input', {
      type: 'search',
      class: 'form-control form-control-sm var-modal-search',
      placeholder: t('tabsEventos.varsSearchPlaceholder'),
      autofocus: true,
    });

    const categoryTabsWrap = el('div', { class: 'var-category-tabs' });
    const chipsGrid = el('div', { class: 'var-modal-grid' });

    function renderModalChips() {
      chipsGrid.innerHTML = '';
      const q = searchQuery.toLowerCase().trim();

      const filtered = eventVariables.filter(v => {
        const matchCat = activeCat === 'all' || v.category === activeCat;
        if (!matchCat) return false;
        if (!q) return true;
        return v.name.toLowerCase().includes(q) || (v.description && v.description.toLowerCase().includes(q));
      });

      if (!filtered.length) {
        chipsGrid.append(el('p', { class: 'dim text-sm', style: 'padding: 12px; text-align: center;' }, 'No se encontraron variables'));
        return;
      }

      for (const v of filtered) {
        const varTag = `{${v.name}}`;
        const chip = el('button', {
          type: 'button',
          class: 'var-chip-compact',
          title: `${v.description || ''} (${t('tabsEventos.varExample')} ${v.example || ''})`,
          onclick: () => {
            if (target && typeof target.value === 'string') {
              const start = target.selectionStart !== undefined ? target.selectionStart : target.value.length;
              const end = target.selectionEnd !== undefined ? target.selectionEnd : target.value.length;
              const val = target.value;
              target.value = val.substring(0, start) + varTag + val.substring(end);
              target.selectionStart = target.selectionEnd = start + varTag.length;
              target.dispatchEvent(new Event('input', { bubbles: true }));
              target.focus();
              toast(t('tabsEventos.varsInserted', { var: varTag }), 'ok');
            } else {
              if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(varTag);
                toast(t('tabsEventos.varsCopied', { var: varTag }), 'ok');
              }
            }
            closeModal();
          },
        },
          el('code', { class: 'var-tag' }, varTag),
          el('span', { class: 'var-desc' }, v.description || '')
        );
        chipsGrid.append(chip);
      }
    }

    function renderModalCatTabs() {
      categoryTabsWrap.innerHTML = '';
      for (const cat of varCategories) {
        const btn = el('button', {
          type: 'button',
          class: 'category-tab-btn' + (activeCat === cat.key ? ' active' : ''),
          onclick: () => {
            activeCat = cat.key;
            renderModalCatTabs();
            renderModalChips();
          },
        }, cat.label);
        categoryTabsWrap.append(btn);
      }
    }

    searchInput.oninput = () => {
      searchQuery = searchInput.value;
      renderModalChips();
    };

    renderModalCatTabs();
    renderModalChips();

    function closeModal() {
      document.removeEventListener('keydown', handleKeyDown);
      backdrop.remove();
    }

    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        closeModal();
      }
    }
    document.addEventListener('keydown', handleKeyDown);

    const closeBtn = el('button', {
      type: 'button',
      class: 'modal-close-btn',
      onclick: closeModal,
      title: t('tabsEventos.close'),
    }, '✕');

    const modalBox = el('div', { class: 'purg-variables-modal' },
      el('div', { class: 'var-modal-header' },
        el('div', { class: 'var-modal-title' },
          icon('sparkle'),
          el('strong', {}, t('tabsEventos.varsTitle'))
        ),
        closeBtn
      ),
      el('p', { class: 'dim text-xs', style: 'margin: 0 0 10px 0;' }, t('tabsEventos.varsSubtitle')),
      searchInput,
      categoryTabsWrap,
      chipsGrid
    );

    const backdrop = el('div', {
      id: 'purg-variables-modal-backdrop',
      class: 'purg-modal-backdrop',
      onclick: (e) => {
        if (e.target === backdrop) closeModal();
      },
    }, modalBox);

    document.body.append(backdrop);
    setTimeout(() => { searchInput.focus(); }, 30);
  }

  // ─────────────────────────────────────────────────────────────
  // 2. HEADER & CONFIGURACIÓN PRINCIPAL (Ultra Compacta)
  // ─────────────────────────────────────────────────────────────
  const toggleChk = el('input', {
    type: 'checkbox',
    checked: isEnabled,
  });

  const toggleStatusBadge = el('span', {
    class: 'badge ' + (isEnabled ? 'badge-ok' : 'badge-dim'),
  }, isEnabled ? `● ${t('tabsEventos.statusActive')}` : `○ ${t('tabsEventos.statusInactive')}`);

  const channelSel = channelSelect(channels, selectedChannelId, t('tabsEventos.channelSelectPlaceholder'));
  const channelWarning = el('p', { class: 'form-error-msg', style: 'display: none; margin: 4px 0 0 0;' },
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

  const disabledNotice = el('div', {
    class: 'event-disabled-banner',
    style: isEnabled ? 'display: none;' : 'display: flex;',
  },
    icon('info'),
    el('span', {}, t(cfg.disabledNoticeKey || 'tabsEventos.eventDisabledNotice'))
  );

  toggleChk.onchange = () => {
    isEnabled = toggleChk.checked;
    toggleStatusBadge.className = 'badge ' + (isEnabled ? 'badge-ok' : 'badge-dim');
    toggleStatusBadge.textContent = isEnabled ? `● ${t('tabsEventos.statusActive')}` : `○ ${t('tabsEventos.statusInactive')}`;
    disabledNotice.style.display = isEnabled ? 'none' : 'flex';
    syncBodyVisibility();
    updateLivePreview();
  };

  const masterConfigCard = el('div', { class: 'card event-master-card' },
    el('div', { class: 'event-master-head' },
      el('div', { class: 'event-master-meta' },
        el('div', { class: 'event-master-title' },
          el('span', { class: 'event-icon' }, icon(cfg.icon)),
          el('h1', { class: 'section-title' }, t(cfg.titleKey)),
          toggleStatusBadge
        ),
        el('p', { class: 'dim event-master-desc' }, t(cfg.subtitleKey))
      ),
      el('label', { class: 'toggle toggle-lg event-master-switch', title: t(cfg.toggleLabelKey) },
        toggleChk,
        el('span', { class: 'toggle-label' }, t(cfg.toggleLabelKey))
      )
    ),
    el('div', { class: 'event-master-row' },
      el('div', { class: 'event-channel-field' },
        el('label', { class: 'event-field-label' },
          icon('chat'),
          t(cfg.channelLabelKey)
        ),
        channelSel,
        channelWarning
      )
    ),
    disabledNotice
  );

  // ─────────────────────────────────────────────────────────────
  // 3. CONSTRUCTOR DE CONTENIDO UNIFICADO (Componible)
  // ─────────────────────────────────────────────────────────────
  const contentCard = el('div', { class: 'card event-content-card' });

  function syncBodyVisibility() {
    if (isEnabled) {
      contentCard.classList.remove('is-disabled');
    } else {
      contentCard.classList.add('is-disabled');
    }
  }

  function buildMessageEditor() {
    const msgTxt = el('textarea', {
      class: 'form-control autogrow event-message-textarea',
      rows: 3,
      placeholder: cfg.placeholderDefault,
    });
    msgTxt.value = currentMessage;
    registerInputFocus(msgTxt);

    const charCounter = el('span', { class: 'char-counter' },
      t('tabsEventos.plainTextCounter', { count: currentMessage.length })
    );

    msgTxt.oninput = () => {
      currentMessage = msgTxt.value;
      autoGrow(msgTxt);
      charCounter.textContent = t('tabsEventos.plainTextCounter', { count: currentMessage.length });
      charCounter.className = 'char-counter' + (currentMessage.length > 2000 ? ' over' : '');
      updateLivePreview();
    };

    // Quick insertion tags bar
    const quickVarsWrap = el('div', { class: 'event-quick-vars' });
    const quickVars = ['user', 'server_name', 'server_membercount', 'channel'];
    if (eventType === 'boost') quickVars.push('server_boostlevel');

    quickVars.forEach(vName => {
      const tag = `{${vName}}`;
      const btn = el('button', {
        type: 'button',
        class: 'quick-var-btn',
        title: `Insertar ${tag}`,
        onclick: () => {
          const start = msgTxt.selectionStart || msgTxt.value.length;
          const end = msgTxt.selectionEnd || msgTxt.value.length;
          msgTxt.value = msgTxt.value.substring(0, start) + tag + msgTxt.value.substring(end);
          msgTxt.selectionStart = msgTxt.selectionEnd = start + tag.length;
          msgTxt.dispatchEvent(new Event('input', { bubbles: true }));
          msgTxt.focus();
          toast(t('tabsEventos.varsInserted', { var: tag }), 'ok');
        },
      }, tag);
      quickVarsWrap.append(btn);
    });

    const moreVarsBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-xs btn-more-vars',
      onclick: () => openVariablesModal(msgTxt),
    }, icon('sparkle'), t('tabsEventos.insertVarBtn'));

    const msgFooterBar = el('div', { class: 'event-textarea-bar' },
      el('div', { class: 'event-textarea-bar-left' },
        el('span', { class: 'quick-vars-label dim text-xs' }, `${t('tabsEventos.varsTitle')}:`),
        quickVarsWrap,
        moreVarsBtn
      ),
      charCounter
    );

    return el('div', { class: 'event-builder-section is-active' },
      el('div', { class: 'event-builder-section-head' },
        el('div', { class: 'event-builder-section-title' },
          icon('chat'),
          el('strong', {}, t('tabsEventos.secMessage'))
        )
      ),
      el('div', { class: 'event-builder-section-body' }, msgTxt, msgFooterBar)
    );
  }

  function buildEmbedEditor() {
    const s = embedState;

    function boundInput(key, placeholder, isArea = false, maxL = null) {
      const inp = el(isArea ? 'textarea' : 'input', {
        class: 'form-control' + (isArea ? ' autogrow' : ''),
        placeholder,
        maxlength: maxL ? String(maxL) : null,
      });
      inp.value = s[key] || '';
      registerInputFocus(inp);
      inp.oninput = () => {
        s[key] = inp.value;
        if (isArea) autoGrow(inp);
        updateLivePreview();
      };
      return inp;
    }

    // Embed Content (Title & Description)
    const titleInput = boundInput('title', 'Título del embed…', false, EMBED_LIMITS.title);
    const descInput = boundInput('description', 'Descripción del embed (soporta markdown y variables)…', true, EMBED_LIMITS.description);

    const embedTitleRow = el('div', { class: 'form-group-compact' },
      el('div', { class: 'field-label-row' },
        el('label', {}, t('tabsEventos.embedTitleLabel')),
        el('button', {
          type: 'button',
          class: 'btn-inline-var',
          onclick: () => openVariablesModal(titleInput),
        }, icon('sparkle'), '{ }')
      ),
      titleInput
    );

    const embedDescRow = el('div', { class: 'form-group-compact' },
      el('div', { class: 'field-label-row' },
        el('label', {}, t('tabsEventos.embedDescLabel')),
        el('button', {
          type: 'button',
          class: 'btn-inline-var',
          onclick: () => openVariablesModal(descInput),
        }, icon('sparkle'), '{ }')
      ),
      descInput
    );

    // Embed Appearance & Images
    const colorRow = el('div', { class: 'form-group-compact' },
      el('label', {}, t('tabsEventos.embedColorLabel')),
      colorField(s, 'color', () => updateLivePreview())
    );

    const imagesRow = el('div', { class: 'grid-2' },
      el('div', { class: 'form-group-compact' },
        el('label', {}, t('tabsEventos.embedThumbLabel')),
        imageField(s, 'thumbnail', () => updateLivePreview(), { gif: true })
      ),
      el('div', { class: 'form-group-compact' },
        el('label', {}, t('tabsEventos.embedImageLabel')),
        imageField(s, 'image', () => updateLivePreview(), { gif: true })
      )
    );

    // Embed Author & Footer
    const authorRow = el('div', { class: 'grid-2' },
      el('div', { class: 'form-group-compact' },
        el('label', {}, t('tabsEventos.embedAuthorNameLabel')),
        boundInput('author_name', 'Nombre del autor', false, EMBED_LIMITS.author)
      ),
      el('div', { class: 'form-group-compact' },
        el('label', {}, t('tabsEventos.embedAuthorIconLabel')),
        imageField(s, 'author_icon_url', () => updateLivePreview())
      )
    );

    const footerRow = el('div', { class: 'grid-2' },
      el('div', { class: 'form-group-compact' },
        el('label', {}, t('tabsEventos.embedFooterTextLabel')),
        boundInput('footer_text', 'Pie de página', false, EMBED_LIMITS.footer)
      ),
      el('div', { class: 'form-group-compact' },
        el('label', {}, t('tabsEventos.embedFooterIconLabel')),
        imageField(s, 'footer_icon_url', () => updateLivePreview())
      )
    );

    // Embed Fields
    const fieldsListWrap = el('div', { class: 'embed-fields-container' });
    s.fields = s.fields || [];

    function renderFields() {
      fieldsListWrap.innerHTML = '';
      s.fields.forEach((f, idx) => {
        const fName = el('input', {
          class: 'form-control form-control-sm',
          placeholder: t('tabsEventos.fieldNamePlaceholder'),
          value: f.name || '',
          maxlength: String(EMBED_LIMITS.fieldName),
        });
        registerInputFocus(fName);
        fName.oninput = () => { f.name = fName.value; updateLivePreview(); };

        const fVal = el('input', {
          class: 'form-control form-control-sm',
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
          class: 'btn btn-secondary btn-xs btn-field-del',
          onclick: () => { s.fields.splice(idx, 1); renderFields(); updateLivePreview(); },
          title: 'Eliminar campo',
        }, '✕');

        const row = el('div', { class: 'embed-field-item-compact' },
          el('div', { class: 'field-inputs-compact' }, fName, fVal),
          el('label', { class: 'toggle toggle-xs' }, inlineChk, t('tabsEventos.fieldInlineLabel')),
          delBtn
        );
        fieldsListWrap.append(row);
      });
    }

    const addFieldBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-xs',
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

    // Template actions
    const templateActions = el('div', { class: 'embed-templates-bar' },
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
                renderContentBuilder();
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

    return el('div', { class: 'event-builder-section is-active' },
      el('div', { class: 'event-builder-section-head' },
        el('div', { class: 'event-builder-section-title' },
          icon('layout'),
          el('strong', {}, t('tabsEventos.secEmbed'))
        )
      ),
      el('div', { class: 'event-builder-section-body event-embed-body' },
        embedTitleRow,
        embedDescRow,
        colorRow,
        imagesRow,
        authorRow,
        footerRow,
        el('div', { class: 'form-group-compact' },
          el('div', { class: 'field-label-row' },
            el('label', {}, t('tabsEventos.sectionFields')),
            addFieldBtn
          ),
          fieldsListWrap
        ),
        templateActions
      )
    );
  }

  function renderContentBuilder() {
    contentCard.innerHTML = '';

    if (isLayoutV2) {
      renderLayoutV2Section();
      return;
    }

    // SELECTOR DE FORMATO: Texto | Embed (mutuamente excluyente)
    const formatModes = [
      { key: 'text', label: t('tabsEventos.modePlainText'), icon: 'chat' },
      { key: 'embed', label: t('tabsEventos.modeClassicEmbed'), icon: 'layout' },
    ];

    const pillsWrap = el('div', { class: 'event-mode-pills' });
    const formatBodyWrap = el('div', { class: 'event-format-body' });
    const legacyNoticeWrap = el('div', { class: 'event-legacy-notice-wrap' });

    function renderLegacyNotice() {
      legacyNoticeWrap.innerHTML = '';
      if (!hasLegacyDual) return;
      const otherIsText = format === 'embed';
      legacyNoticeWrap.append(
        el('div', { class: 'event-legacy-notice' },
          icon('info'),
          el('span', {}, otherIsText ? t('tabsEventos.legacyDualNoticeText') : t('tabsEventos.legacyDualNoticeEmbed')),
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-xs',
            onclick: () => {
              format = otherIsText ? 'text' : 'embed';
              renderPills();
              renderFormatBody();
              renderLegacyNotice();
              updateLivePreview();
            },
          }, otherIsText ? t('tabsEventos.legacyDualSwitchText') : t('tabsEventos.legacyDualSwitchEmbed'))
        )
      );
    }

    function renderPills() {
      pillsWrap.innerHTML = '';
      for (const m of formatModes) {
        pillsWrap.append(el('button', {
          type: 'button',
          class: 'mode-pill' + (format === m.key ? ' active' : ''),
          onclick: () => {
            if (format === m.key) return;
            format = m.key;
            renderPills();
            renderFormatBody();
            renderLegacyNotice();
            updateLivePreview();
          },
        },
          el('span', { class: 'mode-pill-icon' }, icon(m.icon)),
          m.label
        ));
      }
    }

    function renderFormatBody() {
      formatBodyWrap.innerHTML = '';
      formatBodyWrap.append(format === 'embed' ? buildEmbedEditor() : buildMessageEditor());
    }

    renderPills();
    renderFormatBody();
    renderLegacyNotice();

    const formatSelectorRow = el('div', { class: 'event-format-selector' },
      el('label', { class: 'event-field-label' }, t('tabsEventos.contentModeLabel')),
      pillsWrap
    );

    // SECTION C: BOTONES INTERACTIVOS
    const buttonsListWrap = el('div', { class: 'event-buttons-list' });

    function renderButtonsEditor() {
      buttonsListWrap.innerHTML = '';
      if (!buttons.length) {
        buttonsListWrap.append(
          el('p', { class: 'dim text-xs', style: 'margin: 0; padding: 4px 0;' }, t('tabsEventos.buttonsHelp'))
        );
      }

      buttons.forEach((btn, bIdx) => {
        const lblInp = el('input', {
          class: 'form-control form-control-sm',
          placeholder: t('tabsEventos.buttonLabelPlaceholder'),
          value: btn.label || '',
          maxlength: '80',
        });
        registerInputFocus(lblInp);
        lblInp.oninput = () => { btn.label = lblInp.value; updateLivePreview(); };

        const typeSel = el('select', { class: 'form-control form-control-sm' },
          el('option', { value: 'link', selected: btn.style !== 'role' }, t('tabsEventos.buttonTypeLink')),
          el('option', { value: 'role', selected: btn.style === 'role' }, t('tabsEventos.buttonTypeRole'))
        );

        const urlInp = el('input', {
          class: 'form-control form-control-sm',
          placeholder: t('tabsEventos.buttonUrlPlaceholder'),
          value: btn.url || '',
          style: btn.style === 'role' ? 'display: none;' : 'display: block;',
        });
        registerInputFocus(urlInp);
        urlInp.oninput = () => { btn.url = urlInp.value; updateLivePreview(); };

        // Role selector and color if role style
        const roleSel = el('select', {
          class: 'form-control form-control-sm',
          style: btn.style === 'role' ? 'display: block;' : 'display: none;',
        },
          el('option', { value: '' }, 'Selecciona un rol…'),
          ...roles.map(r => el('option', { value: String(r.id), selected: String(btn.role_id) === String(r.id) }, r.name))
        );
        roleSel.onchange = () => { btn.role_id = roleSel.value ? parseInt(roleSel.value, 10) : null; updateLivePreview(); };

        const colorSel = el('select', {
          class: 'form-control form-control-sm',
          style: btn.style === 'role' ? 'display: block;' : 'display: none;',
        },
          el('option', { value: 'secondary', selected: btn.color === 'secondary' }, t('tabsEventos.buttonColorSecondary')),
          el('option', { value: 'primary', selected: btn.color === 'primary' }, t('tabsEventos.buttonColorPrimary')),
          el('option', { value: 'success', selected: btn.color === 'success' }, t('tabsEventos.buttonColorSuccess')),
          el('option', { value: 'danger', selected: btn.color === 'danger' }, t('tabsEventos.buttonColorDanger'))
        );
        colorSel.onchange = () => { btn.color = colorSel.value; updateLivePreview(); };

        typeSel.onchange = () => {
          btn.style = typeSel.value;
          urlInp.style.display = btn.style === 'role' ? 'none' : 'block';
          roleSel.style.display = btn.style === 'role' ? 'block' : 'none';
          colorSel.style.display = btn.style === 'role' ? 'block' : 'none';
          updateLivePreview();
        };

        const delBtn = el('button', {
          type: 'button',
          class: 'btn btn-secondary btn-xs btn-field-del',
          onclick: () => {
            buttons.splice(bIdx, 1);
            isButtonsEnabled = buttons.length > 0;
            renderButtonsEditor();
            updateLivePreview();
          },
        }, '✕');

        const btnRow = el('div', { class: 'event-button-item' },
          el('div', { class: 'event-button-grid' },
            lblInp,
            typeSel,
            urlInp,
            roleSel,
            colorSel,
            delBtn
          )
        );
        buttonsListWrap.append(btnRow);
      });
    }

    const addBtnAction = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-xs',
      onclick: () => {
        if (buttons.length >= 5) {
          toast('Máximo 5 botones por fila', 'warn');
          return;
        }
        buttons.push({ label: 'Enlace', style: 'link', url: 'https://discord.com' });
        isButtonsEnabled = true;
        renderButtonsEditor();
        updateLivePreview();
      },
    }, t('tabsEventos.addButton'));

    renderButtonsEditor();

    const buttonsSection = el('div', { class: 'event-builder-section is-active' },
      el('div', { class: 'event-builder-section-head' },
        el('div', { class: 'event-builder-section-title' },
          icon('link'),
          el('strong', {}, t('tabsEventos.buttonsTitle')),
          el('span', { class: 'dim text-xs' }, t('tabsEventos.buttonsHelp'))
        ),
        addBtnAction
      ),
      el('div', { class: 'event-builder-section-body' },
        buttonsListWrap
      )
    );

    // SECTION D: OPCIONES AVANZADAS (Webhook identity & Layout V2)
    const customUserInp = el('input', {
      class: 'form-control form-control-sm',
      placeholder: 'Nombre personalizado',
      value: customUsername,
    });
    registerInputFocus(customUserInp);
    customUserInp.oninput = () => { customUsername = customUserInp.value; updateLivePreview(); };

    const customAvatarInp = el('input', {
      class: 'form-control form-control-sm',
      placeholder: 'https://ejemplo.com/avatar.png',
      value: customAvatarUrl,
    });
    registerInputFocus(customAvatarInp);
    customAvatarInp.oninput = () => { customAvatarUrl = customAvatarInp.value; updateLivePreview(); };

    const layoutV2ToggleChk = el('input', {
      type: 'checkbox',
      checked: isLayoutV2,
      onchange: () => {
        isLayoutV2 = layoutV2ToggleChk.checked;
        renderContentBuilder();
        updateLivePreview();
      },
    });

    const advancedSection = el('details', { class: 'event-advanced-accordion' },
      el('summary', { class: 'event-advanced-summary' },
        el('div', { class: 'event-advanced-summary-title' },
          icon('settings'),
          el('strong', {}, t('tabsEventos.secAdvanced'))
        ),
        el('span', { class: 'dim text-xs' }, 'Webhook e identidad')
      ),
      el('div', { class: 'event-advanced-body' },
        el('div', { class: 'form-group-compact' },
          el('label', { class: 'toggle toggle-sm' },
            layoutV2ToggleChk,
            el('span', { class: 'toggle-label' }, t('tabsEventos.useLayoutV2'))
          ),
          el('p', { class: 'dim form-hint', style: 'margin: 2px 0 0 28px;' }, t('tabsEventos.layoutV2Hint'))
        ),
        el('div', { class: 'grid-2', style: 'margin-top: 10px;' },
          el('div', { class: 'form-group-compact' },
            el('label', {}, t('tabsEventos.webhookUsernameLabel')),
            customUserInp
          ),
          el('div', { class: 'form-group-compact' },
            el('label', {}, t('tabsEventos.webhookAvatarLabel')),
            customAvatarInp
          )
        )
      )
    );

    contentCard.append(formatSelectorRow, legacyNoticeWrap, formatBodyWrap, buttonsSection, advancedSection);
    syncBodyVisibility();
  }

  function renderLayoutV2Section() {
    contentCard.innerHTML = '';

    const backToSimpleBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-xs',
      onclick: () => {
        isLayoutV2 = false;
        renderContentBuilder();
        updateLivePreview();
      },
    }, '← Volver al modo estándar');

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
          blockRow.append(ta);
          if (b.accessory && b.accessory.type === 'button') {
            const lbl = el('input', { class: 'form-control', value: b.accessory.label || '', placeholder: 'Etiqueta del botón' });
            registerInputFocus(lbl);
            lbl.oninput = () => { b.accessory.label = lbl.value; updateLivePreview(); };
            const url = el('input', { class: 'form-control', value: b.accessory.url || '', placeholder: 'https://...' });
            registerInputFocus(url);
            url.oninput = () => { b.accessory.url = url.value; updateLivePreview(); };
            blockRow.append(el('div', { class: 'grid-2', style: 'margin-top: 6px;' }, lbl, url));
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

    const lv2Head = el('div', { class: 'event-builder-section-head' },
      el('div', { class: 'event-builder-section-title' },
        icon('sparkle'),
        el('strong', {}, 'Layout V2 (Modo Avanzado)')
      ),
      backToSimpleBtn
    );

    contentCard.append(lv2Head, blocksList, addBlockBtns);
    syncBodyVisibility();
  }

  renderContentBuilder();

  // ─────────────────────────────────────────────────────────────
  // 4. BARRA DE ACCIONES (Guardar, Probar, Restablecer)
  // ─────────────────────────────────────────────────────────────
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
        const sendOpts = (customUsername.trim() || customAvatarUrl.trim())
          ? { username: customUsername.trim(), avatar_url: customAvatarUrl.trim() }
          : null;

        let payload = {};

        if (isLayoutV2) {
          payload = {
            enabled: isEnabled,
            channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
            content_mode: 'layout_v2',
            layout: { blocks: localLayoutDoc.blocks },
          };
          if (sendOpts) payload.send_options = sendOpts;
        } else {
          const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
          const hasText = format === 'text' && Boolean(currentMessage.trim());
          const hasEmbed = format === 'embed' && rawDicts.length > 0;
          const hasBtns = isButtonsEnabled && buttons.length > 0;

          if (hasText && !hasEmbed && !hasBtns && !sendOpts) {
            payload = {
              enabled: isEnabled,
              channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
              content_mode: 'plain_text',
              message: currentMessage,
            };
          } else if (!hasText && hasEmbed && !hasBtns && !sendOpts) {
            payload = {
              enabled: isEnabled,
              channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
              content_mode: 'classic_embed',
              embeds: rawDicts,
            };
          } else {
            payload = {
              enabled: isEnabled,
              channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
              content_mode: 'composite',
              message: format === 'text' ? currentMessage : '',
              embeds: format === 'embed' ? rawDicts : [],
              buttons: isButtonsEnabled ? buttons : [],
            };
            if (sendOpts) payload.send_options = sendOpts;
          }
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
        const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
        const sendOpts = (customUsername.trim() || customAvatarUrl.trim())
          ? { username: customUsername.trim(), avatar_url: customAvatarUrl.trim() }
          : null;

        let testBody = {};
        if (isLayoutV2) {
          testBody = {
            channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
            content_mode: 'layout_v2',
            layout: { blocks: localLayoutDoc.blocks },
          };
          if (sendOpts) testBody.send_options = sendOpts;
        } else {
          testBody = {
            channel_id: selectedChannelId ? parseInt(selectedChannelId, 10) : null,
            content_mode: 'composite',
            message: format === 'text' ? currentMessage : '',
            embeds: format === 'embed' ? rawDicts : [],
            buttons: isButtonsEnabled ? buttons : [],
          };
          if (sendOpts) testBody.send_options = sendOpts;
        }

        await apiFetch(`/api/server/${GUILD_ID}/events/${eventType}/test`, {
          method: 'POST',
          body: JSON.stringify(testBody),
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

  editorPane.append(masterConfigCard, contentCard, actionsBar);

  // ─────────────────────────────────────────────────────────────
  // 5. LIVE PREVIEW (Fiel a Discord y Reactivo)
  // ─────────────────────────────────────────────────────────────
  function updateLivePreview() {
    previewPane.innerHTML = '';
    const ctx = getMockContext(eventType);

    const ch = channels.find(c => String(c.id) === String(selectedChannelId));
    if (ch) {
      ctx.channel = '#' + ch.name;
      ctx.channel_name = ch.name;
      ctx.channel_id = String(ch.id);
    }

    const previewAuthorName = customUsername.trim() || t('tabsEventos.previewHeader');
    const previewAvatarUrl = customAvatarUrl.trim() || '/assets/icon.png';

    const msgHeader = el('div', { class: 'd-msg-header' },
      el('img', { src: previewAvatarUrl, alt: 'Purgito', class: 'd-msg-avatar' }),
      el('div', { class: 'd-msg-meta' },
        el('span', { class: 'd-msg-author' }, previewAuthorName),
        el('span', { class: 'd-msg-bot' }, t('tabsEventos.previewBotTag')),
        el('span', { class: 'd-msg-time' }, t('tabsEventos.previewToday'))
      )
    );

    const msgBody = el('div', { class: 'd-msg-body' });
    let hasPreviewContent = false;

    if (isLayoutV2) {
      const resolvedBlocks = localLayoutDoc.blocks.map(b => resolveBlockForPreview(b, ctx));
      msgBody.append(renderLayoutPreview(resolvedBlocks));
      hasPreviewContent = true;
    } else {
      // 1. Text message
      if (format === 'text' && currentMessage.trim()) {
        const resolved = resolvePlaceholders(currentMessage, ctx);
        msgBody.append(el('div', { class: 'd-msg-text' }, ...mdToNodes(resolved)));
        hasPreviewContent = true;
      }

      // 2. Embed
      if (format === 'embed') {
        const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
        if (rawDicts.length > 0) {
          const resolvedEmbeds = rawDicts.map(e => resolveEmbedForPreview(e, ctx));
          msgBody.append(renderEmbedsPreview(resolvedEmbeds));
          hasPreviewContent = true;
        }
      }

      // 3. Buttons
      if (isButtonsEnabled && buttons.length > 0) {
        const buttonsRow = el('div', { class: 'lv2-row' });
        buttons.forEach(b => {
          const bLabel = resolvePlaceholders(b.label || 'Enlace', ctx);
          const colorClass = b.style === 'role' ? ` lv2-btn-${b.color || 'secondary'}` : '';
          const btnSpan = el('span', { class: 'lv2-btn' + colorClass },
            bLabel,
            b.style === 'role' ? el('span', { class: 'lv2-btn-tag' }, 'ROL') : null
          );
          buttonsRow.append(btnSpan);
        });
        msgBody.append(buttonsRow);
        hasPreviewContent = true;
      }
    }

    if (!hasPreviewContent) {
      msgBody.append(
        el('p', { class: 'dim text-sm', style: 'margin: 6px 0; font-style: italic;' }, t('tabsEventos.previewEmpty'))
      );
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

  rootWrapper.append(workspaceGrid);
  container.append(rootWrapper);
}
