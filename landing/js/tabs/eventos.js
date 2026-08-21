// Módulo de Eventos del Servidor (Bienvenida, Despedida, Boost).

import { apiFetch } from '/js/core/api.js';
import {
  el, spinner, renderError, toast, formGroup, autoGrow, helpIcon, icon,
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
import { colorField, imageField, insertWrap, sendOptionsPanel } from '/js/embeds/shared-ui.js';

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
    'tabsEventos.varsTitle': 'Variables disponibles',
    'tabsEventos.varsSubtitle': 'Haz clic en cualquier variable para copiarla.',
    'tabsEventos.varsSearchPlaceholder': 'Buscar variables…',
    'tabsEventos.varsCopied': 'Variable {var} copiada al portapapeles',
    'tabsEventos.catAll': 'Todas',
    'tabsEventos.catUser': 'Usuario',
    'tabsEventos.catServer': 'Servidor',
    'tabsEventos.catChannel': 'Canal',
    'tabsEventos.catBoost': 'Boost',
    'tabsEventos.catDate': 'Fecha',
    'tabsEventos.previewTitle': 'Vista previa',
    'tabsEventos.previewHeader': 'Purgito',
    'tabsEventos.previewBotTag': 'BOT',
    'tabsEventos.previewToday': 'HOY',
    'tabsEventos.saveBtn': 'Guardar configuración',
    'tabsEventos.saving': 'Guardando…',
    'tabsEventos.savedSuccess': 'Configuración de {event} guardada',
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
    'tabsEventos.varsTitle': 'Available variables',
    'tabsEventos.varsSubtitle': 'Click any variable to copy it to your clipboard.',
    'tabsEventos.varsSearchPlaceholder': 'Search variables…',
    'tabsEventos.varsCopied': 'Variable {var} copied to clipboard',
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
  const isEn = (document.documentElement.lang || 'es') === 'en';
  return {
    user: '@Usuario de prueba',
    user_tag: 'usuario_prueba',
    user_name: 'usuario_prueba',
    user_nick: 'Usuario de prueba',
    user_displayname: 'Usuario de prueba',
    user_avatar: 'https://cdn.discordapp.com/embed/avatars/1.png',
    user_id: '987654321012345678',
    user_created_at: isEn ? 'January 15, 2022' : '15 de enero de 2022',
    user_joined_at: isEn ? 'August 21, 2026' : '21 de agosto de 2026',
    user_boost_since: eventType === 'boost' ? (isEn ? 'August 21, 2026' : '21 de agosto de 2026') : 'N/A',
    server_name: 'Mi Servidor',
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
  if (!text || typeof text !== 'string') return text || '';
  return text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, varName) => {
    return ctx[varName] !== undefined ? ctx[varName] : match;
  });
}

function resolveEmbedForPreview(embed, ctx) {
  const e = JSON.parse(JSON.stringify(embed));
  if (e.title) e.title = resolvePlaceholders(e.title, ctx);
  if (e.description) e.description = resolvePlaceholders(e.description, ctx);
  if (e.fields && Array.isArray(e.fields)) {
    for (const f of e.fields) {
      if (f.name) f.name = resolvePlaceholders(f.name, ctx);
      if (f.value) f.value = resolvePlaceholders(f.value, ctx);
    }
  }
  if (e.footer) {
    if (e.footer.text) e.footer.text = resolvePlaceholders(e.footer.text, ctx);
    if (e.footer.icon_url) e.footer.icon_url = resolvePlaceholders(e.footer.icon_url, ctx);
  }
  if (e.author) {
    if (e.author.name) e.author.name = resolvePlaceholders(e.author.name, ctx);
    if (e.author.icon_url) e.author.icon_url = resolvePlaceholders(e.author.icon_url, ctx);
  }
  if (e.thumbnail && e.thumbnail.url) e.thumbnail.url = resolvePlaceholders(e.thumbnail.url, ctx);
  if (e.image && e.image.url) e.image.url = resolvePlaceholders(e.image.url, ctx);
  return e;
}

function resolveBlockForPreview(block, ctx) {
  const b = JSON.parse(JSON.stringify(block));
  if (b.type === 'container' && Array.isArray(b.children)) {
    b.children = b.children.map(c => resolveBlockForPreview(c, ctx));
  } else if (b.type === 'text' && b.content) {
    b.content = resolvePlaceholders(b.content, ctx);
  } else if (b.type === 'section') {
    if (Array.isArray(b.texts)) b.texts = b.texts.map(tx => resolvePlaceholders(tx, ctx));
    if (b.accessory) {
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
      if (it.url) it.url = resolvePlaceholders(it.url, ctx);
      if (it.description) it.description = resolvePlaceholders(it.description, ctx);
    }
  } else if (b.type === 'action_row' && Array.isArray(b.buttons)) {
    for (const btn of b.buttons) {
      if (btn.label) btn.label = resolvePlaceholders(btn.label, ctx);
      if (btn.url) btn.url = resolvePlaceholders(btn.url, ctx);
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

  // Header
  const header = el('div', { class: 'tab-header' },
    el('h1', {}, el('span', { class: 'nav-icon' }, icon('sparkle')), t('tabsEventos.title')),
    el('p', { class: 'dim' }, t('tabsEventos.subtitle'))
  );

  // Cards selector for the 3 events
  const cardsWrap = el('div', { class: 'event-cards-grid' });
  const detailWrap = el('div', { class: 'event-detail-card card' });

  function refreshCards() {
    cardsWrap.innerHTML = '';
    for (const def of EVENT_DEFS) {
      const evConfig = serverEvents[def.key];
      const isEnabled = evConfig && evConfig.enabled;
      const channelObj = evConfig && evConfig.channel_id
        ? channels.find(c => String(c.id) === String(evConfig.channel_id))
        : null;

      const card = el('div', {
        class: 'event-nav-card' + (def.key === activeEventKey ? ' active' : ''),
        onclick: () => {
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
            isEnabled ? t('tabsEventos.statusActive') : t('tabsEventos.statusInactive')
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

    // Embed/Layout state representation
    let localEmbedDoc = null;
    let localLayoutDoc = null;

    if (currentMode === 'classic_embed' && evConfig.embed_json) {
      try {
        const parsed = JSON.parse(evConfig.embed_json);
        const list = Array.isArray(parsed) ? parsed : (parsed.embeds || []);
        localEmbedDoc = blankDoc();
        localEmbedDoc.embeds = list.map(e => ({ ...e }));
      } catch (e) {
        localEmbedDoc = blankDoc();
      }
    } else {
      localEmbedDoc = blankDoc();
    }

    if (currentMode === 'layout_v2' && evConfig.embed_json) {
      try {
        const parsed = JSON.parse(evConfig.embed_json);
        localLayoutDoc = blankLayoutDoc();
        localLayoutDoc.blocks = (parsed.blocks || []).map(apiToBlock);
      } catch (e) {
        localLayoutDoc = blankLayoutDoc();
      }
    } else {
      localLayoutDoc = blankLayoutDoc();
    }

    // Detail Header
    const detailHead = el('div', { class: 'event-detail-header' },
      el('div', { class: 'event-detail-title-group' },
        el('h2', {}, t(def.titleKey)),
        el('p', { class: 'dim' }, t(def.descKey))
      )
    );

    // Toggle switch
    const toggleChk = el('input', {
      type: 'checkbox',
      checked: isEnabled,
      onchange: () => {
        isEnabled = toggleChk.checked;
        updatePreview();
      },
    });

    const toggleRow = el('div', { class: 'form-group' },
      el('label', { class: 'toggle' },
        toggleChk,
        el('span', { class: 'toggle-label' }, t('tabsEventos.toggleLabel'))
      ),
      helpIcon(t('tabsEventos.toggleHelp'))
    );

    // Channel Selector
    const channelSel = channelSelect(channels, selectedChannelId, t('tabsEventos.channelSelectPlaceholder'));
    channelSel.onchange = () => {
      selectedChannelId = channelSel.value;
      updatePreview();
    };

    const channelRow = formGroup(t('tabsEventos.channelLabel'), channelSel, t('tabsEventos.channelHelp'));

    // Mode Selector (Pills)
    const modes = [
      { key: 'plain_text', label: t('tabsEventos.modePlainText'), icon: 'chat' },
      { key: 'classic_embed', label: t('tabsEventos.modeClassicEmbed'), icon: 'layout' },
      { key: 'layout_v2', label: t('tabsEventos.modeLayoutV2'), icon: 'sparkle' },
    ];

    const modePills = el('div', { class: 'event-mode-pills' });
    const editorContainer = el('div', { class: 'event-editor-container' });
    const previewContainer = el('div', { class: 'event-preview-container' });

    function renderModeSelector() {
      modePills.innerHTML = '';
      for (const m of modes) {
        const pill = el('button', {
          type: 'button',
          class: 'mode-pill' + (currentMode === m.key ? ' active' : ''),
          onclick: () => {
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

    // Live preview update function
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

      // Discord message wrapper
      const msgHeader = el('div', { class: 'd-msg-header' },
        el('img', { src: '/assets/icon.png', alt: t('tabsEventos.botAvatarAlt'), class: 'd-msg-avatar' }),
        el('div', { class: 'd-msg-meta' },
          el('span', { class: 'd-msg-author' }, t('tabsEventos.previewHeader')),
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

      const discordMessage = el('div', { class: 'd-message' }, msgHeader, msgBody);
      previewContainer.append(
        el('div', { class: 'preview-title-bar' },
          el('strong', {}, t('tabsEventos.previewTitle'))
        ),
        discordMessage
      );
    }

    // Editor Area Render
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

        txtArea.oninput = () => {
          currentMessage = txtArea.value;
          autoGrow(txtArea);
          counter.textContent = t('tabsEventos.plainTextCounter', { count: currentMessage.length });
          counter.className = 'char-counter' + (currentMessage.length > 2000 ? ' over' : '');
          updatePreview();
        };

        const group = el('div', { class: 'form-group' },
          el('label', {}, t('tabsEventos.plainTextLabel')),
          txtArea,
          counter
        );

        editorContainer.append(group);
      } else if (currentMode === 'classic_embed') {
        // Embed editor fields
        const s = localEmbedDoc.embeds[0] || blankEmbed();
        localEmbedDoc.embeds[0] = s;

        function boundInput(key, placeholder, isArea = false) {
          const input = el(isArea ? 'textarea' : 'input', {
            class: 'form-control' + (isArea ? ' autogrow' : ''),
            placeholder,
          });
          input.value = s[key] || '';
          input.oninput = () => {
            s[key] = input.value;
            if (isArea) autoGrow(input);
            updatePreview();
          };
          return input;
        }

        const titleInput = boundInput('title', '¡Bienvenido {user}!');
        const descInput = boundInput('description', 'Nos alegra tenerte en {server_name}', true);

        const thumbWrap = imageField(s, 'thumbnail', () => updatePreview());
        const imgWrap = imageField(s, 'image', () => updatePreview());
        const colorWrap = colorField(s, 'color', () => updatePreview());

        const authorName = boundInput('author_name', '{server_name}');
        const authorIcon = imageField(s, 'author_icon_url', () => updatePreview());

        const footerText = boundInput('footer_text', 'Miembro #{server_membercount}');
        const footerIcon = imageField(s, 'footer_icon_url', () => updatePreview());

        const embedBox = el('div', { class: 'event-embed-editor' },
          formGroup('Título del embed', titleInput),
          formGroup('Descripción del embed', descInput),
          formGroup('Color de la barra lateral', colorWrap),
          formGroup('Miniatura (Thumbnail)', thumbWrap),
          formGroup('Imagen grande', imgWrap),
          formGroup('Autor (Nombre)', authorName),
          formGroup('Autor (Icono)', authorIcon),
          formGroup('Pie de página (Texto)', footerText),
          formGroup('Pie de página (Icono)', footerIcon)
        );

        editorContainer.append(embedBox);
      } else if (currentMode === 'layout_v2') {
        // Layout V2 Simple Block Builder
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
              ta.oninput = () => {
                b.content = ta.value;
                autoGrow(ta);
                updatePreview();
              };
              blockRow.append(ta);
            } else if (b.type === 'section') {
              const ta = el('textarea', { class: 'form-control autogrow' });
              ta.value = (b.texts && b.texts[0]) || '';
              ta.oninput = () => {
                b.texts = [ta.value];
                autoGrow(ta);
                updatePreview();
              };
              blockRow.append(formGroup('Texto', ta));
              if (b.accessory && b.accessory.type === 'button') {
                const lbl = el('input', { class: 'form-control', value: b.accessory.label || '', placeholder: 'Texto del botón' });
                lbl.oninput = () => { b.accessory.label = lbl.value; updatePreview(); };
                const url = el('input', { class: 'form-control', value: b.accessory.url || '', placeholder: 'https://...' });
                url.oninput = () => { b.accessory.url = url.value; updatePreview(); };
                blockRow.append(formGroup('Botón enlace', el('div', { class: 'grid-2' }, lbl, url)));
              }
            } else if (b.type === 'action_row') {
              const btnsWrap = el('div', { class: 'action-row-buttons' });
              (b.buttons || []).forEach((btn, bIdx) => {
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
        editorContainer.append(blocksList, addBlockBtns);
      }
    }

    // Variables Panel
    const varsCard = el('div', { class: 'event-variables-panel' },
      el('div', { class: 'vars-panel-header' },
        el('strong', {}, t('tabsEventos.varsTitle')),
        el('p', { class: 'dim' }, t('tabsEventos.varsSubtitle'))
      )
    );

    const searchInput = el('input', {
      type: 'text',
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
        const item = el('div', {
          class: 'var-card',
          onclick: () => {
            navigator.clipboard.writeText(placeholderTag).then(() => {
              toast(t('tabsEventos.varsCopied', { var: placeholderTag }), 'ok');
            });
          },
        },
          el('div', { class: 'var-card-head' },
            el('code', { class: 'var-tag' }, placeholderTag),
            el('span', { class: 'var-copy-icon' }, icon('sparkle'))
          ),
          el('p', { class: 'var-desc' }, v.description),
          el('p', { class: 'var-example dim' }, `${t('tabsEventos.varExample')} ${v.example}`)
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

    // Action Buttons
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
          if (currentMode === 'plain_text') {
            payload.message = currentMessage;
          } else if (currentMode === 'classic_embed') {
            payload.embeds = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
          } else if (currentMode === 'layout_v2') {
            payload.layout = { blocks: localLayoutDoc.blocks };
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
          if (currentMode === 'plain_text') {
            payload.message = currentMessage;
          } else if (currentMode === 'classic_embed') {
            payload.embeds = localEmbedDoc.embeds.map(embedDict).filter(d => Object.keys(d).length);
          } else if (currentMode === 'layout_v2') {
            payload.layout = { blocks: localLayoutDoc.blocks };
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
      class: 'btn btn-danger',
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

    const actionsRow = el('div', { class: 'event-actions-row' },
      el('div', { class: 'left-actions' }, saveBtn, testBtn),
      resetBtn
    );

    // Initial renders
    renderModeSelector();
    renderEditorArea();
    updatePreview();

    // Assemble detail view
    const mainCols = el('div', { class: 'event-editor-layout' },
      el('div', { class: 'editor-col' },
        toggleRow,
        channelRow,
        formGroup(t('tabsEventos.contentModeLabel'), modePills),
        editorContainer,
        varsCard
      ),
      el('div', { class: 'preview-col' },
        previewContainer
      )
    );

    detailWrap.append(detailHead, mainCols, actionsRow);
  }

  refreshCards();
  renderEventDetail();

  container.append(header, cardsWrap, detailWrap);
}
