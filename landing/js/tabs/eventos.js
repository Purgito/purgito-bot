// Módulo de Eventos del Servidor (Bienvenida, Despedida, Boost).
// Arquitectura visual: Selector de Eventos -> Configuración Mínima -> Workspace (Editor 2-Col + Live Preview).

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
import { colorField, imageField, insertWrap } from '/js/embeds/shared-ui.js';

addStrings({
  es: {
    'tabsEventos.title': 'Eventos del servidor',
    'tabsEventos.subtitle': 'Configura mensajes automáticos para dar la bienvenida, despedir miembros o agradecer mejoras.',
    'tabsEventos.welcomeTitle': 'Bienvenida',
    'tabsEventos.welcomeDesc': 'Se envía cuando un nuevo miembro entra al servidor.',
    'tabsEventos.goodbyeTitle': 'Despedida',
    'tabsEventos.goodbyeDesc': 'Se envía cuando un miembro abandona el servidor.',
    'tabsEventos.boostTitle': 'Boost',
    'tabsEventos.boostDesc': 'Se envía cuando un miembro mejora el servidor.',
    'tabsEventos.statusActive': 'ACTIVO',
    'tabsEventos.statusInactive': 'INACTIVO',
    'tabsEventos.statusConfigured': 'Configurado',
    'tabsEventos.statusNotConfigured': 'Sin configurar',
    'tabsEventos.statusLabel': 'Estado del evento',
    'tabsEventos.activeState': 'Activado',
    'tabsEventos.inactiveState': 'Desactivado',
    'tabsEventos.toggleLabel': 'Activar evento',
    'tabsEventos.toggleHelp': 'Si está desactivado, Purgito no enviará ningún mensaje cuando ocurra este evento.',
    'tabsEventos.channelLabel': 'Canal de destino',
    'tabsEventos.channelHelp': 'Canal donde se publicará el mensaje automático.',
    'tabsEventos.channelSelectPlaceholder': 'Elige un canal…',
    'tabsEventos.contentModeLabel': 'Modo de contenido',
    'tabsEventos.modePlainText': 'Mensaje normal',
    'tabsEventos.modeClassicEmbed': 'Embed clásico',
    'tabsEventos.modeLayoutV2': 'Layout V2',
    'tabsEventos.plainTextLabel': 'Contenido del mensaje',
    'tabsEventos.plainTextPlaceholder': '¡Bienvenido {user} a {server_name}! Ya somos {server_membercount} miembros.',
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
    'tabsEventos.webhookHelp': 'Permite enviar el mensaje con un nombre y avatar específicos para este evento usando webhooks de Discord.',
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
    'tabsEventos.savedSuccess': 'Configuración de {event} guardada correctamente',
    'tabsEventos.testBtn': 'Enviar prueba',
    'tabsEventos.testing': 'Enviando prueba…',
    'tabsEventos.testSuccess': 'Mensaje de prueba enviado al canal',
    'tabsEventos.resetBtn': 'Restablecer',
    'tabsEventos.resetConfirm': '¿Seguro que deseas restablecer la configuración de {event}?',
    'tabsEventos.resetSuccess': 'Configuración de {event} restablecida',
    'tabsEventos.noChannelSelected': 'Debes seleccionar un canal para activar el evento',
    'tabsEventos.emptyTextWarning': 'El mensaje no puede estar vacío si el evento está activo',
    'tabsEventos.botAvatarAlt': 'Avatar de Purgito',
    'tabsEventos.selectEventPrompt': 'Elige un evento arriba para ver o editar su configuración.',
    'tabsEventos.varExample': 'Ejemplo:',
  },
  en: {
    'tabsEventos.title': 'Server Events',
    'tabsEventos.subtitle': 'Configure automatic messages to welcome new members, say goodbye, or celebrate server boosts.',
    'tabsEventos.welcomeTitle': 'Welcome',
    'tabsEventos.welcomeDesc': 'Sent when a new member joins the server.',
    'tabsEventos.goodbyeTitle': 'Goodbye',
    'tabsEventos.goodbyeDesc': 'Sent when a member leaves the server.',
    'tabsEventos.boostTitle': 'Boost',
    'tabsEventos.boostDesc': 'Sent when a member boosts the server.',
    'tabsEventos.statusActive': 'ACTIVE',
    'tabsEventos.statusInactive': 'INACTIVE',
    'tabsEventos.statusConfigured': 'Configured',
    'tabsEventos.statusNotConfigured': 'Not configured',
    'tabsEventos.statusLabel': 'Event status',
    'tabsEventos.activeState': 'Enabled',
    'tabsEventos.inactiveState': 'Disabled',
    'tabsEventos.toggleLabel': 'Enable event',
    'tabsEventos.toggleHelp': 'If disabled, Purgito will not send any message when this event occurs.',
    'tabsEventos.channelLabel': 'Destination channel',
    'tabsEventos.channelHelp': 'Channel where the automatic message will be posted.',
    'tabsEventos.channelSelectPlaceholder': 'Choose a channel…',
    'tabsEventos.contentModeLabel': 'Content mode',
    'tabsEventos.modePlainText': 'Normal message',
    'tabsEventos.modeClassicEmbed': 'Classic embed',
    'tabsEventos.modeLayoutV2': 'Layout V2',
    'tabsEventos.plainTextLabel': 'Message content',
    'tabsEventos.plainTextPlaceholder': 'Welcome {user} to {server_name}! We are now {server_membercount} members.',
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
    'tabsEventos.webhookHelp': 'Allows sending the message with a specific custom name and avatar for this event using Discord webhooks.',
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
    'tabsEventos.saveBtn': 'Save settings',
    'tabsEventos.saving': 'Saving…',
    'tabsEventos.savedSuccess': '{event} settings saved successfully',
    'tabsEventos.testBtn': 'Send test',
    'tabsEventos.testing': 'Sending test…',
    'tabsEventos.testSuccess': 'Test message sent to the channel',
    'tabsEventos.resetBtn': 'Reset',
    'tabsEventos.resetConfirm': 'Are you sure you want to reset the settings for {event}?',
    'tabsEventos.resetSuccess': '{event} settings reset successfully',
    'tabsEventos.noChannelSelected': 'You must select a channel to enable the event',
    'tabsEventos.emptyTextWarning': 'Message cannot be empty when the event is enabled',
    'tabsEventos.botAvatarAlt': 'Purgito avatar',
    'tabsEventos.selectEventPrompt': 'Choose an event above to view or edit its settings.',
    'tabsEventos.varExample': 'Example:',
  },
});

const EVENT_DEFS = [
  { key: 'welcome', icon: 'sparkle', titleKey: 'tabsEventos.welcomeTitle', descKey: 'tabsEventos.welcomeDesc' },
  { key: 'goodbye', icon: 'trash', titleKey: 'tabsEventos.goodbyeTitle', descKey: 'tabsEventos.goodbyeDesc' },
  { key: 'boost', icon: 'star', titleKey: 'tabsEventos.boostTitle', descKey: 'tabsEventos.boostDesc' },
];

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

export async function loadEventosTab() {
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
    renderEventosShell(box, eventsData, channels, roles);
  } catch (err) {
    if (myGuild !== GUILD_ID) return;
    renderError(box, err);
  }
}

function renderEventosShell(container, initialData, channels, roles) {
  container.innerHTML = '';

  let activeEventKey = 'welcome';
  const serverEvents = initialData.events || {};
  const allVariables = initialData.variables || [];

  // Track focused input for smart variable insertion
  let lastActiveInput = null;

  // Header
  const header = el('div', { class: 'tab-header' },
    el('h1', {}, el('span', { class: 'nav-icon' }, icon('sparkle')), t('tabsEventos.title')),
    el('p', { class: 'dim' }, t('tabsEventos.subtitle'))
  );

  // Cards selector for the 3 events
  const cardsWrap = el('div', { class: 'event-cards-grid' });
  const detailWrap = el('div', { class: 'event-workspace' });

  function refreshCards() {
    cardsWrap.innerHTML = '';
    for (const def of EVENT_DEFS) {
      const evConfig = serverEvents[def.key];
      const isEnabled = evConfig && evConfig.enabled;
      const channelObj = evConfig && evConfig.channel_id
        ? channels.find(c => String(c.id) === String(evConfig.channel_id))
        : null;

      const card = el('button', {
        type: 'button',
        class: 'event-nav-card' + (def.key === activeEventKey ? ' active' : ''),
        onclick: () => {
          if (activeEventKey === def.key) return;
          activeEventKey = def.key;
          refreshCards();
          renderEventDetail();
        },
      },
        el('div', { class: 'event-nav-card-head' },
          el('div', { class: 'event-nav-card-title' },
            el('span', { class: 'event-icon' }, icon(def.icon)),
            el('strong', {}, t(def.titleKey))
          ),
          el('span', { class: 'badge ' + (isEnabled ? 'badge-ok' : 'badge-dim') },
            isEnabled ? `● ${t('tabsEventos.statusActive')}` : `○ ${t('tabsEventos.statusInactive')}`
          )
        ),
        el('p', { class: 'event-nav-card-desc dim' }, t(def.descKey)),
        el('div', { class: 'event-nav-card-foot dim' },
          channelObj ? '#' + channelObj.name : t('tabsEventos.statusNotConfigured')
        )
      );

      cardsWrap.append(card);
    }
  }

  function renderEventDetail() {
    detailWrap.innerHTML = '';
    lastActiveInput = null;

    const def = EVENT_DEFS.find(d => d.key === activeEventKey);
    const evConfig = serverEvents[activeEventKey] || {
      enabled: false,
      channel_id: '',
      content_mode: 'plain_text',
      message: activeEventKey === 'welcome'
        ? t('tabsEventos.plainTextPlaceholder')
        : (activeEventKey === 'goodbye' ? 'Hasta luego {user} 👋' : '🚀 ¡Muchas gracias {user} por el boost a {server_name}!'),
      embed_json: null,
    };

    let isEnabled = !!evConfig.enabled;
    let selectedChannelId = evConfig.channel_id ? String(evConfig.channel_id) : '';
    let currentMode = evConfig.content_mode || 'plain_text';
    let currentMessage = evConfig.message || '';
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

    // Ensure embed object exists
    if (!localEmbedDoc.embeds.length) {
      localEmbedDoc.embeds.push(blankEmbed());
    }
    const embedState = localEmbedDoc.embeds[0];

    // 1. MINIMAL CONFIG BAR (Horizontal bar: Active Toggle + Channel Selector)
    const toggleChk = el('input', {
      type: 'checkbox',
      checked: isEnabled,
      onchange: () => {
        isEnabled = toggleChk.checked;
        statusText.textContent = isEnabled ? `● ${t('tabsEventos.activeState')}` : `○ ${t('tabsEventos.inactiveState')}`;
        statusText.className = 'status-indicator ' + (isEnabled ? 'active' : 'inactive');
        updatePreview();
      },
    });

    const statusText = el('span', { class: 'status-indicator ' + (isEnabled ? 'active' : 'inactive') },
      isEnabled ? `● ${t('tabsEventos.activeState')}` : `○ ${t('tabsEventos.inactiveState')}`
    );

    const toggleWrap = el('label', { class: 'toggle event-status-toggle' },
      toggleChk,
      el('span', { class: 'toggle-label' }, t('tabsEventos.toggleLabel')),
      statusText
    );

    const channelSel = channelSelect(channels, selectedChannelId, t('tabsEventos.channelSelectPlaceholder'));
    channelSel.onchange = () => {
      selectedChannelId = channelSel.value;
      updatePreview();
    };

    const minimalBar = el('div', { class: 'event-minimal-bar card' },
      el('div', { class: 'minimal-bar-item' },
        el('div', { class: 'minimal-bar-label' }, t('tabsEventos.statusLabel'), helpIcon(t('tabsEventos.toggleHelp'))),
        toggleWrap
      ),
      el('div', { class: 'minimal-bar-divider' }),
      el('div', { class: 'minimal-bar-item minimal-bar-channel' },
        el('div', { class: 'minimal-bar-label' }, t('tabsEventos.channelLabel'), helpIcon(t('tabsEventos.channelHelp'))),
        channelSel
      )
    );

    // 2. WORKSPACE 2-COLUMN GRID (Left: Mode + Editor + Variables + Actions; Right: Sticky Preview)
    const modes = [
      { key: 'plain_text', label: t('tabsEventos.modePlainText'), icon: 'chat' },
      { key: 'classic_embed', label: t('tabsEventos.modeClassicEmbed'), icon: 'layout' },
      { key: 'layout_v2', label: t('tabsEventos.modeLayoutV2'), icon: 'sparkle' },
    ];

    const modePills = el('div', { class: 'event-mode-pills' });
    const editorContainer = el('div', { class: 'event-editor-container' });
    const previewContainer = el('div', { class: 'event-preview-pane' });

    function renderModeSelector() {
      modePills.innerHTML = '';
      for (const m of modes) {
        const pill = el('button', {
          type: 'button',
          class: 'mode-pill' + (currentMode === m.key ? ' active' : ''),
          onclick: () => {
            if (currentMode === m.key) return;
            currentMode = m.key;
            renderModeSelector();
            renderEditorArea();
            updatePreview();
          },
        },
          el('span', { class: 'mode-pill-icon' }, icon(m.icon)),
          m.label
        );
        modePills.append(pill);
      }
    }

    // Live preview updater
    function updatePreview() {
      previewContainer.innerHTML = '';
      const ctx = getMockContext(activeEventKey);

      if (selectedChannelId) {
        const ch = channels.find(c => String(c.id) === String(selectedChannelId));
        if (ch) {
          ctx.channel = '#' + ch.name;
          ctx.channel_name = ch.name;
          ctx.channel_id = String(ch.id);
        }
      }

      // Custom identity in preview
      const previewAuthorName = customUsername ? resolvePlaceholders(customUsername, ctx) : t('tabsEventos.previewHeader');
      const previewAvatarUrl = customAvatarUrl ? resolvePlaceholders(customAvatarUrl, ctx) : '/assets/icon.png';

      const msgHeader = el('div', { class: 'd-msg-header' },
        el('img', { src: previewAvatarUrl, alt: t('tabsEventos.botAvatarAlt'), class: 'd-msg-avatar' }),
        el('div', { class: 'd-msg-meta' },
          el('span', { class: 'd-msg-author' }, previewAuthorName),
          el('span', { class: 'd-msg-bot' }, t('tabsEventos.previewBotTag')),
          el('span', { class: 'd-msg-time' }, t('tabsEventos.previewToday'))
        )
      );

      const msgBody = el('div', { class: 'd-msg-body' });

      if (currentMode === 'plain_text') {
        const resolvedText = resolvePlaceholders(currentMessage, ctx);
        const textContent = el('div', { class: 'd-msg-text' }, ...mdToNodes(resolvedText || ''));
        msgBody.append(textContent);
      } else if (currentMode === 'classic_embed') {
        const rawDicts = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
        const resolvedDicts = rawDicts.map(d => resolveEmbedForPreview(d, ctx));
        msgBody.append(renderEmbedsPreview(resolvedDicts));
      } else if (currentMode === 'layout_v2') {
        const rawBlocks = localLayoutDoc.blocks.map(b => b);
        const resolvedBlocks = rawBlocks.map(b => resolveBlockForPreview(b, ctx));
        msgBody.append(renderLayoutPreview(resolvedBlocks));
      }

      const discordCard = el('div', { class: 'd-message-card' },
        el('div', { class: 'd-message-top' },
          el('div', { class: 'd-message-channel-tag' },
            icon('chat'),
            el('span', {}, ctx.channel || '#bienvenidas')
          ),
          el('span', { class: 'preview-badge dim' }, t('tabsEventos.previewTitle'))
        ),
        el('div', { class: 'd-message' }, msgHeader, msgBody)
      );

      previewContainer.append(discordCard);
    }

    // Render Editor Content
    function renderEditorArea() {
      editorContainer.innerHTML = '';

      if (currentMode === 'plain_text') {
        const txtArea = el('textarea', {
          class: 'form-control autogrow event-text-input',
          rows: 4,
          placeholder: t('tabsEventos.plainTextPlaceholder'),
        });
        txtArea.value = currentMessage;

        const counter = el('div', { class: 'char-counter' },
          t('tabsEventos.plainTextCounter', { count: currentMessage.length })
        );

        const registerActive = () => { lastActiveInput = txtArea; };
        txtArea.onfocus = registerActive;
        txtArea.onclick = registerActive;
        txtArea.oninput = () => {
          registerActive();
          currentMessage = txtArea.value;
          autoGrow(txtArea);
          counter.textContent = t('tabsEventos.plainTextCounter', { count: currentMessage.length });
          counter.className = 'char-counter' + (currentMessage.length > 2000 ? ' over' : '');
          updatePreview();
        };

        const group = el('div', { class: 'form-group' },
          el('label', { class: 'form-label' }, t('tabsEventos.plainTextLabel')),
          txtArea,
          counter
        );

        editorContainer.append(group);
      } else if (currentMode === 'classic_embed') {
        const s = embedState;

        function boundInput(key, placeholder, isArea = false, maxL = null) {
          const input = el(isArea ? 'textarea' : 'input', {
            class: 'form-control' + (isArea ? ' autogrow' : ''),
            placeholder,
            maxlength: maxL ? String(maxL) : null,
          });
          input.value = s[key] || '';
          const registerActive = () => { lastActiveInput = input; };
          input.onfocus = registerActive;
          input.onclick = registerActive;
          input.oninput = () => {
            registerActive();
            s[key] = input.value;
            if (isArea) autoGrow(input);
            updatePreview();
          };
          return input;
        }

        // 1. Contenido principal
        const titleInp = boundInput('title', '¡Bienvenido {user}!', false, EMBED_LIMITS.title);
        const descInp = boundInput('description', 'Nos alegra tenerte en {server_name}', true, EMBED_LIMITS.description);
        const contentSec = accordionGroup(t('tabsEventos.sectionContent'), true,
          formGroup(t('tabsEventos.embedTitleLabel'), titleInp),
          formGroup(t('tabsEventos.embedDescLabel'), descInp)
        );

        // 2. Apariencia
        const colorWrap = colorField(s, 'color', () => updatePreview());
        const appearanceSec = accordionGroup(t('tabsEventos.sectionAppearance'), false,
          formGroup(t('tabsEventos.embedColorLabel'), colorWrap)
        );

        // 3. Imágenes
        const thumbWrap = imageField(s, 'thumbnail', () => updatePreview(), { gif: true });
        const imgWrap = imageField(s, 'image', () => updatePreview(), { gif: true });
        const imagesSec = accordionGroup(t('tabsEventos.sectionImages'), false,
          formGroup(t('tabsEventos.embedThumbLabel'), thumbWrap),
          formGroup(t('tabsEventos.embedImageLabel'), imgWrap)
        );

        // 4. Autor
        const authorName = boundInput('author_name', '{server_name}', false, EMBED_LIMITS.author);
        const authorIcon = imageField(s, 'author_icon_url', () => updatePreview());
        const authorSec = accordionGroup(t('tabsEventos.sectionAuthor'), false,
          formGroup(t('tabsEventos.embedAuthorNameLabel'), authorName),
          formGroup(t('tabsEventos.embedAuthorIconLabel'), authorIcon)
        );

        // 5. Pie de página
        const footerText = boundInput('footer_text', 'Miembro #{server_membercount}', false, EMBED_LIMITS.footer);
        const footerIcon = imageField(s, 'footer_icon_url', () => updatePreview());
        const footerSec = accordionGroup(t('tabsEventos.sectionFooter'), false,
          formGroup(t('tabsEventos.embedFooterTextLabel'), footerText),
          formGroup(t('tabsEventos.embedFooterIconLabel'), footerIcon)
        );

        // 6. Campos adicionales (Fields)
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
            fName.onfocus = () => { lastActiveInput = fName; };
            fName.oninput = () => {
              lastActiveInput = fName;
              f.name = fName.value;
              updatePreview();
            };

            const fVal = el('input', {
              class: 'form-control',
              placeholder: t('tabsEventos.fieldValuePlaceholder'),
              value: f.value || '',
              maxlength: String(EMBED_LIMITS.fieldValue),
            });
            fVal.onfocus = () => { lastActiveInput = fVal; };
            fVal.oninput = () => {
              lastActiveInput = fVal;
              f.value = fVal.value;
              updatePreview();
            };

            const inlineChk = el('input', {
              type: 'checkbox',
              checked: !!f.inline,
              onchange: () => {
                f.inline = inlineChk.checked;
                updatePreview();
              },
            });

            const delBtn = el('button', {
              type: 'button',
              class: 'btn btn-secondary btn-xs',
              title: 'Eliminar campo',
              onclick: () => {
                s.fields.splice(idx, 1);
                renderFields();
                updatePreview();
              },
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
            updatePreview();
          },
        }, t('tabsEventos.addFieldBtn'));

        renderFields();
        const fieldsSec = accordionGroup(t('tabsEventos.sectionFields'), false,
          fieldsListWrap,
          el('div', { style: 'margin-top: 10px;' }, addFieldBtn)
        );

        // 7. Identidad personalizada (Webhook)
        const customUserInp = el('input', {
          class: 'form-control',
          placeholder: 'Bot de {server_name}',
          value: customUsername,
        });
        customUserInp.onfocus = () => { lastActiveInput = customUserInp; };
        customUserInp.oninput = () => {
          lastActiveInput = customUserInp;
          customUsername = customUserInp.value;
          updatePreview();
        };

        const customAvatarInp = el('input', {
          class: 'form-control',
          placeholder: 'https://ejemplo.com/avatar.png o {server_icon}',
          value: customAvatarUrl,
        });
        customAvatarInp.onfocus = () => { lastActiveInput = customAvatarInp; };
        customAvatarInp.oninput = () => {
          lastActiveInput = customAvatarInp;
          customAvatarUrl = customAvatarInp.value;
          updatePreview();
        };

        const identitySec = accordionGroup(t('tabsEventos.sectionIdentity'), false,
          el('p', { class: 'dim form-hint', style: 'margin-top:0' }, t('tabsEventos.webhookHelp')),
          formGroup(t('tabsEventos.webhookUsernameLabel'), customUserInp),
          formGroup(t('tabsEventos.webhookAvatarLabel'), customAvatarInp)
        );

        editorContainer.append(contentSec, appearanceSec, imagesSec, authorSec, footerSec, fieldsSec, identitySec);
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
                    updatePreview();
                  },
                }, '✕')
              )
            );

            if (b.type === 'text') {
              const ta = el('textarea', { class: 'form-control autogrow' });
              ta.value = b.content || '';
              ta.onfocus = () => { lastActiveInput = ta; };
              ta.oninput = () => {
                lastActiveInput = ta;
                b.content = ta.value;
                autoGrow(ta);
                updatePreview();
              };
              blockRow.append(ta);
            } else if (b.type === 'section') {
              const ta = el('textarea', { class: 'form-control autogrow' });
              ta.value = (b.texts && b.texts[0]) || '';
              ta.onfocus = () => { lastActiveInput = ta; };
              ta.oninput = () => {
                lastActiveInput = ta;
                b.texts = [ta.value];
                autoGrow(ta);
                updatePreview();
              };
              blockRow.append(formGroup('Texto', ta));
              if (b.accessory && b.accessory.type === 'button') {
                const lbl = el('input', { class: 'form-control', value: b.accessory.label || '', placeholder: 'Texto del botón' });
                lbl.onfocus = () => { lastActiveInput = lbl; };
                lbl.oninput = () => { lastActiveInput = lbl; b.accessory.label = lbl.value; updatePreview(); };
                const url = el('input', { class: 'form-control', value: b.accessory.url || '', placeholder: 'https://...' });
                url.onfocus = () => { lastActiveInput = url; };
                url.oninput = () => { lastActiveInput = url; b.accessory.url = url.value; updatePreview(); };
                blockRow.append(formGroup('Botón enlace', el('div', { class: 'grid-2' }, lbl, url)));
              }
            } else if (b.type === 'action_row') {
              const btnsWrap = el('div', { class: 'action-row-buttons' });
              (b.buttons || []).forEach((btn) => {
                const lbl = el('input', { class: 'form-control', value: btn.label || '', placeholder: 'Etiqueta' });
                lbl.onfocus = () => { lastActiveInput = lbl; };
                lbl.oninput = () => { lastActiveInput = lbl; btn.label = lbl.value; updatePreview(); };
                const url = el('input', { class: 'form-control', value: btn.url || '', placeholder: 'https://...' });
                url.onfocus = () => { lastActiveInput = url; };
                url.oninput = () => { lastActiveInput = url; btn.url = url.value; updatePreview(); };
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
              sec.accessory = { type: 'button', style: 'link', label: 'Ver reglas', url: 'https://discord.com' };
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
          localLayoutDoc.blocks.push({ type: 'text', content: 'Bienvenido {user} a {server_name}!' });
        }

        refreshLayoutBlocks();

        // Identidad personalizada para Layout V2
        const customUserInp = el('input', {
          class: 'form-control',
          placeholder: 'Bot de {server_name}',
          value: customUsername,
        });
        customUserInp.onfocus = () => { lastActiveInput = customUserInp; };
        customUserInp.oninput = () => {
          lastActiveInput = customUserInp;
          customUsername = customUserInp.value;
          updatePreview();
        };

        const customAvatarInp = el('input', {
          class: 'form-control',
          placeholder: 'https://ejemplo.com/avatar.png o {server_icon}',
          value: customAvatarUrl,
        });
        customAvatarInp.onfocus = () => { lastActiveInput = customAvatarInp; };
        customAvatarInp.oninput = () => {
          lastActiveInput = customAvatarInp;
          customAvatarUrl = customAvatarInp.value;
          updatePreview();
        };

        const identitySec = accordionGroup(t('tabsEventos.sectionIdentity'), false,
          el('p', { class: 'dim form-hint', style: 'margin-top:0' }, t('tabsEventos.webhookHelp')),
          formGroup(t('tabsEventos.webhookUsernameLabel'), customUserInp),
          formGroup(t('tabsEventos.webhookAvatarLabel'), customAvatarInp)
        );

        editorContainer.append(blocksList, addBlockBtns, identitySec);
      }
    }

    // 3. AUXILIARY VARIABLES TOOL (Smart insert + copy + category filters + search)
    const varsCard = el('div', { class: 'event-vars-aux' },
      el('div', { class: 'vars-panel-header' },
        el('div', { class: 'vars-panel-title' },
          el('strong', {}, t('tabsEventos.varsTitle')),
          el('span', { class: 'dim text-xs' }, t('tabsEventos.varsSubtitle'))
        )
      )
    );

    const searchInput = el('input', {
      type: 'search',
      class: 'form-control vars-search',
      placeholder: t('tabsEventos.varsSearchPlaceholder'),
    });

    const categoryTabs = el('div', { class: 'vars-category-tabs' });
    const varsList = el('div', { class: 'vars-grid' });

    let activeVarCategory = 'all';
    let varSearchTerm = '';

    const categories = [
      { key: 'all', label: t('tabsEventos.catAll') },
      { key: 'user', label: t('tabsEventos.catUser') },
      { key: 'server', label: t('tabsEventos.catServer') },
      { key: 'channel', label: t('tabsEventos.catChannel') },
      ...(activeEventKey === 'boost' ? [{ key: 'boost', label: t('tabsEventos.catBoost') }] : []),
      { key: 'date', label: t('tabsEventos.catDate') },
    ];

    function renderCategoryTabs() {
      categoryTabs.innerHTML = '';
      for (const cat of categories) {
        const tabBtn = el('button', {
          type: 'button',
          class: 'category-tab-btn' + (activeVarCategory === cat.key ? ' active' : ''),
          onclick: () => {
            activeVarCategory = cat.key;
            renderCategoryTabs();
            renderVariablesList();
          },
        }, cat.label);
        categoryTabs.append(tabBtn);
      }
    }

    function insertOrCopyVariable(placeholderTag) {
      if (lastActiveInput && document.body.contains(lastActiveInput)) {
        try {
          const start = lastActiveInput.selectionStart ?? lastActiveInput.value.length;
          const end = lastActiveInput.selectionEnd ?? lastActiveInput.value.length;
          const val = lastActiveInput.value || '';
          lastActiveInput.value = val.slice(0, start) + placeholderTag + val.slice(end);
          lastActiveInput.selectionStart = lastActiveInput.selectionEnd = start + placeholderTag.length;
          lastActiveInput.focus();
          lastActiveInput.dispatchEvent(new Event('input', { bubbles: true }));
          toast(t('tabsEventos.varsInserted', { var: placeholderTag }), 'ok');
          return;
        } catch (e) {
          // fallback to clipboard
        }
      }

      navigator.clipboard.writeText(placeholderTag).then(() => {
        toast(t('tabsEventos.varsCopied', { var: placeholderTag }), 'ok');
      }).catch(() => {
        toast(placeholderTag, 'ok');
      });
    }

    function renderVariablesList() {
      varsList.innerHTML = '';
      const filtered = allVariables.filter(v => {
        if (!v.allowed_events.includes(activeEventKey)) return false;
        if (activeVarCategory !== 'all' && v.category !== activeVarCategory) return false;
        if (varSearchTerm) {
          const q = varSearchTerm.toLowerCase();
          const matchName = v.name.toLowerCase().includes(q);
          const matchDesc = (v.description || '').toLowerCase().includes(q);
          if (!matchName && !matchDesc) return false;
        }
        return true;
      });

      for (const v of filtered) {
        const placeholderTag = `{${v.name}}`;
        const item = el('button', {
          type: 'button',
          class: 'var-chip',
          title: `Insertar ${placeholderTag}`,
          onclick: () => insertOrCopyVariable(placeholderTag),
        },
          el('span', { class: 'var-tag' }, placeholderTag),
          el('span', { class: 'var-desc' }, v.description || '')
        );
        varsList.append(item);
      }
    }

    searchInput.oninput = () => {
      varSearchTerm = searchInput.value.trim();
      renderVariablesList();
    };

    renderCategoryTabs();
    renderVariablesList();
    varsCard.append(searchInput, categoryTabs, varsList);

    // 4. ACTIONS TOOLBAR (Sticky/Pinned at bottom)
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

          const res = await apiFetch(`/api/server/${GUILD_ID}/events/${activeEventKey}`, {
            method: 'PUT',
            body: JSON.stringify(payload),
          });

          serverEvents[activeEventKey] = res.event;
          refreshCards();
          toast(t('tabsEventos.savedSuccess', { event: t(def.titleKey) }), 'ok');
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
        if (!selectedChannelId) {
          toast(t('tabsEventos.noChannelSelected'), 'err');
          return;
        }
        testBtn.disabled = true;
        testBtn.textContent = t('tabsEventos.testing');
        try {
          const payload = {
            channel_id: parseInt(selectedChannelId, 10),
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

          await apiFetch(`/api/server/${GUILD_ID}/events/${activeEventKey}/test`, {
            method: 'POST',
            body: JSON.stringify(payload),
          });

          toast(t('tabsEventos.testSuccess'), 'ok');
        } catch (err) {
          toast(err.message || 'Error al enviar prueba', 'err');
        } finally {
          testBtn.disabled = false;
          testBtn.textContent = t('tabsEventos.testBtn');
        }
      },
    }, t('tabsEventos.testBtn'));

    const resetBtn = el('button', {
      type: 'button',
      class: 'btn btn-secondary btn-danger-soft',
      onclick: async () => {
        if (!confirm(t('tabsEventos.resetConfirm', { event: t(def.titleKey) }))) return;
        try {
          await apiFetch(`/api/server/${GUILD_ID}/events/${activeEventKey}`, { method: 'DELETE' });
          delete serverEvents[activeEventKey];
          refreshCards();
          renderEventDetail();
          toast(t('tabsEventos.resetSuccess', { event: t(def.titleKey) }), 'ok');
        } catch (err) {
          toast(err.message || 'Error al restablecer', 'err');
        }
      },
    }, t('tabsEventos.resetBtn'));

    const actionsRow = el('div', { class: 'event-actions-bar' },
      el('div', { class: 'left-actions' }, saveBtn, testBtn),
      resetBtn
    );

    // Initial renders
    renderModeSelector();
    renderEditorArea();
    updatePreview();

    // Assemble 2-column layout
    const workspaceGrid = el('div', { class: 'event-workspace-grid' },
      el('div', { class: 'event-editor-pane' },
        el('div', { class: 'form-group' },
          el('label', { class: 'form-label' }, t('tabsEventos.contentModeLabel')),
          modePills
        ),
        editorContainer,
        varsCard,
        actionsRow
      ),
      el('div', { class: 'event-preview-pane-wrap' },
        previewContainer
      )
    );

    detailWrap.append(minimalBar, workspaceGrid);
  }

  refreshCards();
  renderEventDetail();

  container.append(header, cardsWrap, detailWrap);
}
