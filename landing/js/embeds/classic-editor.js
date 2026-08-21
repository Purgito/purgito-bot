// Editor de embeds clásicos + su preview HTML/CSS puro (sin llamada al backend).

import { GUILD_ID, formatNumber } from '/js/core/config.js';
import { apiFetch } from '/js/core/api.js';
import {
  el, autoGrow, showFormAlert, accordionGroup, formGroup, previewEmpty, toast, helpIcon,
} from '/js/core/dom.js';
import {
  previewImg, mdToNodes, beginPreviewRender, endPreviewRender, discordTimestampText,
} from '/js/core/markdown.js';
import {
  blankDoc, blankEmbed, blankSendOpts, embedDict, embedChars, EMBED_LIMITS,
  docDicts, validateEmbedsClient, sendOptsToApi, colorToHex, isoToLocalInput, localInputToIso,
} from '/js/embeds/state.js';
import { _embedDoc, setEmbedDoc } from '/js/embeds/session.js';
import { channelSelect } from '/js/panel-shell.js';
import {
  readEmbedDraft, clearEmbedDraft, scheduleHistorySnapshot, scheduleDraftSave,
  openHistoryModal, openJsonModal,
} from '/js/embeds/persistence.js';
import { insertWrap, imageField, colorField, sendOptionsPanel, loadEmbeds } from '/js/embeds/shared-ui.js';
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'embedsClassic.emptyEmbedTooltip': 'Este embed está vacío y no se va a enviar',
    'embedsClassic.draftRecovered': 'Recuperamos tu borrador anterior',
    'embedsClassic.discard': 'Descartar',
    'embedsClassic.nowButton': 'Ahora',
    'embedsClassic.timestampHelp': 'Se muestra en el footer del embed, siempre convertido a la hora local de quien lo ve — no hace falta ajustar por zona horaria.',
    'embedsClassic.addField': '+ Agregar field',
    'embedsClassic.fieldHeader': 'Field {index}',
    'embedsClassic.fieldNamePlaceholder': 'Nombre',
    'embedsClassic.fieldValuePlaceholder': 'Valor',
    'embedsClassic.dragToReorder': 'Arrastra para reordenar',
    'embedsClassic.moveUp': 'Mover arriba',
    'embedsClassic.moveDown': 'Mover abajo',
    'embedsClassic.duplicate': 'Duplicar',
    'embedsClassic.delete': 'Eliminar',
    'embedsClassic.inlineLabel': 'inline',
    'embedsClassic.embedPillLabel': 'Embed {index}',
    'embedsClassic.moveBefore': 'Mover antes',
    'embedsClassic.moveAfter': 'Mover después',
    'embedsClassic.addEmbed': '+ Agregar embed',
    'embedsClassic.galleryTooltip': 'Agrupa varias imágenes en una galería compartiendo el enlace del embed actual',
    'embedsClassic.addImageFirst': 'Agrega primero una imagen a este embed',
    'embedsClassic.addGallery': '+ Galería',
    'embedsClassic.channelPlaceholder': 'Canal destino…',
    'embedsClassic.intervalOption': 'Por intervalo',
    'embedsClassic.dailyOption': 'A hora fija',
    'embedsClassic.scheduleLabel': 'Programar',
    'embedsClassic.sendNowLabel': 'Enviar ahora',
    'embedsClassic.chooseChannel': 'Elige un canal destino',
    'embedsClassic.embedScheduled': 'Embed programado',
    'embedsClassic.embedsSent': '{count} embeds enviados',
    'embedsClassic.embedSentSingular': 'Embed enviado',
    'embedsClassic.templateNamePrompt': 'Nombre de la plantilla:',
    'embedsClassic.templateUpdated': 'Plantilla actualizada',
    'embedsClassic.templateSaved': 'Plantilla guardada',
    'embedsClassic.saveAsTemplate': 'Guardar como plantilla',
    'embedsClassic.shareLinkReady': 'Link listo — cualquiera con el link puede cargar este embed en su servidor',
    'embedsClassic.copyLink': 'Copiar link',
    'embedsClassic.linkCopied': 'Link copiado',
    'embedsClassic.copyLinkPrompt': 'Copia el link:',
    'embedsClassic.share': 'Compartir',
    'embedsClassic.clear': 'Limpiar',
    'embedsClassic.history': 'Historial',
    'embedsClassic.viewEditJson': 'Ver/editar JSON',
    'embedsClassic.bodySection': 'Cuerpo',
    'embedsClassic.titleLabel': 'Título',
    'embedsClassic.descriptionLabel': 'Descripción',
    'embedsClassic.colorLabel': 'Color',
    'embedsClassic.dateOptionalLabel': 'Fecha (opcional)',
    'embedsClassic.authorSection': 'Autor',
    'embedsClassic.nameLabel': 'Nombre',
    'embedsClassic.authorIconLabel': 'Ícono del autor',
    'embedsClassic.imagesSection': 'Imágenes',
    'embedsClassic.thumbnailLabel': 'Thumbnail',
    'embedsClassic.largeImageLabel': 'Imagen grande',
    'embedsClassic.footerSection': 'Footer',
    'embedsClassic.textLabel': 'Texto',
    'embedsClassic.footerIconLabel': 'Ícono del footer',
    'embedsClassic.fieldsSection': 'Fields',
    'embedsClassic.destinationSection': 'Destino y envío',
    'embedsClassic.targetChannelLabel': 'Canal destino',
    'embedsClassic.previewLabel': 'Preview',
  },
  en: {
    'embedsClassic.emptyEmbedTooltip': 'This embed is empty and won\'t be sent',
    'embedsClassic.draftRecovered': 'We recovered your previous draft',
    'embedsClassic.discard': 'Discard',
    'embedsClassic.nowButton': 'Now',
    'embedsClassic.timestampHelp': 'Shown in the embed footer, always converted to the local time of whoever views it — no need to adjust for time zones.',
    'embedsClassic.addField': '+ Add field',
    'embedsClassic.fieldHeader': 'Field {index}',
    'embedsClassic.fieldNamePlaceholder': 'Name',
    'embedsClassic.fieldValuePlaceholder': 'Value',
    'embedsClassic.dragToReorder': 'Drag to reorder',
    'embedsClassic.moveUp': 'Move up',
    'embedsClassic.moveDown': 'Move down',
    'embedsClassic.duplicate': 'Duplicate',
    'embedsClassic.delete': 'Delete',
    'embedsClassic.inlineLabel': 'inline',
    'embedsClassic.embedPillLabel': 'Embed {index}',
    'embedsClassic.moveBefore': 'Move earlier',
    'embedsClassic.moveAfter': 'Move later',
    'embedsClassic.addEmbed': '+ Add embed',
    'embedsClassic.galleryTooltip': 'Groups several images into a gallery by sharing the current embed\'s link',
    'embedsClassic.addImageFirst': 'Add an image to this embed first',
    'embedsClassic.addGallery': '+ Gallery',
    'embedsClassic.channelPlaceholder': 'Target channel…',
    'embedsClassic.intervalOption': 'By interval',
    'embedsClassic.dailyOption': 'At a fixed time',
    'embedsClassic.scheduleLabel': 'Schedule',
    'embedsClassic.sendNowLabel': 'Send now',
    'embedsClassic.chooseChannel': 'Choose a target channel',
    'embedsClassic.embedScheduled': 'Embed scheduled',
    'embedsClassic.embedsSent': '{count} embeds sent',
    'embedsClassic.embedSentSingular': 'Embed sent',
    'embedsClassic.templateNamePrompt': 'Template name:',
    'embedsClassic.templateUpdated': 'Template updated',
    'embedsClassic.templateSaved': 'Template saved',
    'embedsClassic.saveAsTemplate': 'Save as template',
    'embedsClassic.shareLinkReady': 'Link ready — anyone with the link can load this embed into their server',
    'embedsClassic.copyLink': 'Copy link',
    'embedsClassic.linkCopied': 'Link copied',
    'embedsClassic.copyLinkPrompt': 'Copy the link:',
    'embedsClassic.share': 'Share',
    'embedsClassic.clear': 'Clear',
    'embedsClassic.history': 'History',
    'embedsClassic.viewEditJson': 'View/edit JSON',
    'embedsClassic.bodySection': 'Body',
    'embedsClassic.titleLabel': 'Title',
    'embedsClassic.descriptionLabel': 'Description',
    'embedsClassic.colorLabel': 'Color',
    'embedsClassic.dateOptionalLabel': 'Date (optional)',
    'embedsClassic.authorSection': 'Author',
    'embedsClassic.nameLabel': 'Name',
    'embedsClassic.authorIconLabel': 'Author icon',
    'embedsClassic.imagesSection': 'Images',
    'embedsClassic.thumbnailLabel': 'Thumbnail',
    'embedsClassic.largeImageLabel': 'Large image',
    'embedsClassic.footerSection': 'Footer',
    'embedsClassic.textLabel': 'Text',
    'embedsClassic.footerIconLabel': 'Footer icon',
    'embedsClassic.fieldsSection': 'Fields',
    'embedsClassic.destinationSection': 'Destination and sending',
    'embedsClassic.targetChannelLabel': 'Target channel',
    'embedsClassic.previewLabel': 'Preview',
  },
});

// Preview puro HTML/CSS de un embed de Discord; sin llamada al backend.
export function renderEmbedPreview(e) {
  if (!Object.keys(e).length) return previewEmpty();
  const main = el('div', { class: 'd-embed-main' });
  if (e.author) {
    main.append(el('div', { class: 'd-embed-author' },
      e.author.icon_url ? previewImg({ src: e.author.icon_url, alt: '' }) : null,
      e.author.name));
  }
  // Título, descripción y fields soportan markdown/menciones como en Discord
  // real; autor y footer (más abajo) son texto plano — Discord no los formatea.
  if (e.title) main.append(el('div', { class: 'd-embed-title' }, ...mdToNodes(e.title)));
  if (e.description) main.append(el('div', { class: 'd-embed-desc' }, ...mdToNodes(e.description)));
  if (e.fields) {
    const grid = el('div', { class: 'd-embed-fields' });
    for (const f of e.fields) {
      grid.append(el('div', { class: 'd-embed-field' + (f.inline ? ' inline' : '') },
        el('div', { class: 'd-embed-field-name' }, ...mdToNodes(f.name)),
        el('div', { class: 'd-embed-field-value' }, ...mdToNodes(f.value))));
    }
    main.append(grid);
  }
  const body = el('div', { class: 'd-embed-body' }, main);
  if (e.thumbnail) body.append(el('div', { class: 'd-embed-thumb' }, previewImg({ src: e.thumbnail.url, alt: '' })));
  if (e.image) body.append(el('div', { class: 'd-embed-image' }, previewImg({ src: e.image.url, alt: '' })));
  if (e.footer || e.timestamp) {
    const bits = [e.footer && e.footer.text, e.timestamp && discordTimestampText(new Date(e.timestamp), 'f')]
      .filter(Boolean);
    body.append(el('div', { class: 'd-embed-footer' },
      e.footer && e.footer.icon_url ? previewImg({ src: e.footer.icon_url, alt: '' }) : null,
      bits.join(' • ')));
  }
  const color = colorToHex(e.color) || '#8B6EF5';
  return el('div', { class: 'd-embed' },
    el('div', { class: 'd-embed-bar', style: 'background:' + color }), body);
}

// Preview de todos los embeds del doc, apilados como los muestra Discord.
export function renderEmbedsPreview(dicts) {
  const nonEmpty = dicts.filter(d => Object.keys(d).length);
  if (!nonEmpty.length) return previewEmpty();
  const stack = el('div', { class: 'd-embed-stack' });
  for (const d of nonEmpty) stack.append(renderEmbedPreview(d));
  return stack;
}

export function renderClassicEditor(box, channels, roles) {
  if (!_embedDoc) {
    const draft = readEmbedDraft('classic');
    if (draft) {
      setEmbedDoc(draft);
      toast(t('embedsClassic.draftRecovered'), 'ok', {
        label: t('embedsClassic.discard'), onclick: () => { clearEmbedDraft('classic'); setEmbedDoc(blankDoc()); loadEmbeds(); },
      });
    } else {
      setEmbedDoc(blankDoc());
    }
  }
  const doc = _embedDoc;
  // Docs restaurados de un historial/borrador anterior a la Fase 5 no traen sendOpts.
  if (!doc.sendOpts) doc.sendOpts = blankSendOpts();
  const s = doc.embeds[doc.active];  // embed activo

  const previewBox = el('div', {});
  // Contador en vivo contra el límite de 6000 (suma de todos los embeds del
  // mensaje — mismo cálculo que validateEmbedsClient) + marca de tabs vacíos.
  const charCounter = el('span', { class: 'char-counter' });
  const embedPills = [];  // se llena al armar embedBar, más abajo
  function refreshEmbedMeta(dicts) {
    const total = dicts.reduce((n, d) => n + embedChars(d), 0);
    charCounter.textContent = `${formatNumber(total)} / ${formatNumber(EMBED_LIMITS.total)}`;
    charCounter.className = 'char-counter'
      + (total > EMBED_LIMITS.total ? ' over' : total >= EMBED_LIMITS.total * 0.9 ? ' near' : '');
    embedPills.forEach((pill, i) => {
      const empty = !Object.keys(dicts[i] || {}).length;
      pill.classList.toggle('empty', empty);
      pill.title = empty ? t('embedsClassic.emptyEmbedTooltip') : '';
    });
  }
  function updatePreview() {
    const dicts = doc.embeds.map(embedDict);
    previewBox.innerHTML = '';
    beginPreviewRender();
    previewBox.append(renderEmbedsPreview(dicts));
    endPreviewRender();
    refreshEmbedMeta(dicts);
    scheduleHistorySnapshot();
    scheduleDraftSave();
  }

  function bound(tag, key, attrs) {
    const node = el(tag, { ...attrs, value: s[key] });
    if (tag === 'textarea') { node.value = s[key]; node.classList.add('autogrow'); }
    node.oninput = () => {
      s[key] = node.value;
      if (tag === 'textarea') autoGrow(node);
      updatePreview();
    };
    return node;
  }

  function fieldBlock(label, node) {
    return el('div', { class: 'field' }, el('label', {}, label), node);
  }

  // Timestamp del embed: datetime-local (hora del navegador) <-> ISO que
  // espera Discord. Se guarda vacío por default — Discord no lo muestra si
  // falta, no hace falta un toggle aparte para "sin timestamp".
  function timestampField() {
    const dt = el('input', { type: 'datetime-local', value: isoToLocalInput(s.timestamp) });
    dt.oninput = () => { s.timestamp = localInputToIso(dt.value); updatePreview(); };
    const nowBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm',
      onclick: () => { s.timestamp = new Date().toISOString(); dt.value = isoToLocalInput(s.timestamp); updatePreview(); },
    }, t('embedsClassic.nowButton'));
    const clearBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm',
      onclick: () => { s.timestamp = ''; dt.value = ''; updatePreview(); },
    }, '✗');
    return el('div', { class: 'add-row' }, dt, nowBtn, clearBtn,
      helpIcon(t('embedsClassic.timestampHelp')));
  }

  // --- fields dinámicos ---
  const fieldsBox = el('div', {});
  // Estado abierto/cerrado de cada field entre re-renders (reorden, duplicar,
  // borrar). Set de referencias a los objetos de s.fields — los splices mueven
  // las mismas refs, así que sobrevive. Regla inicial: ≤3 fields todos
  // abiertos, con más solo el primero (mismo criterio que accordionGroup).
  const openFields = new Set(s.fields.length <= 3 ? s.fields : s.fields.slice(0, 1));
  const addFieldBtn = el('button', {
    class: 'btn btn-secondary btn-sm',
    onclick: () => {
      const f = { name: '', value: '', inline: false };
      s.fields.push(f);
      openFields.add(f);  // recién agregado nace abierto para escribir ya
      renderFields();
      updatePreview();
    },
  }, t('embedsClassic.addField'));

  function renderFields() {
    fieldsBox.innerHTML = '';
    s.fields.forEach((f, i) => {
      // Header: "Field N" o "Field N — {nombre|valor}" (patrón fieldNText de
      // Discohook), actualizado en vivo mientras se escribe.
      const headText = () => {
        const txt = (f.name || '').trim() || (f.value || '').trim();
        return t('embedsClassic.fieldHeader', { index: i + 1 }) + (txt ? ` — ${txt.length > 40 ? txt.slice(0, 40) + '…' : txt}` : '');
      };
      const label = el('span', { class: 'embed-field-label' }, headText());

      const name = el('input', { type: 'text', placeholder: t('embedsClassic.fieldNamePlaceholder'), maxlength: String(EMBED_LIMITS.fieldName), value: f.name });
      name.oninput = () => { f.name = name.value; label.textContent = headText(); updatePreview(); };
      const value = el('textarea', { placeholder: t('embedsClassic.fieldValuePlaceholder'), maxlength: String(EMBED_LIMITS.fieldValue), rows: '2' });
      value.value = f.value;
      value.oninput = () => { f.value = value.value; label.textContent = headText(); updatePreview(); };
      const inline = el('input', { type: 'checkbox', checked: f.inline });
      inline.onchange = () => { f.inline = inline.checked; updatePreview(); };

      // Solo el handle es draggable: arrastrar desde los inputs seguiría
      // seleccionando texto normalmente. DnD nativo (mismo enfoque que
      // Discohook) — no funciona en touch; ahí el fallback son los ▲/▼.
      const handle = el('span', {
        class: 'field-drag-handle', draggable: 'true',
        title: t('embedsClassic.dragToReorder'), 'aria-label': t('embedsClassic.dragToReorder'),
      }, '⠿');

      // Acciones del header. preventDefault evita que el click pliegue el
      // <details> (default de summary); el re-render repone visibilidad ▲/▼.
      const action = (icon, title, hidden, fn) => hidden ? null : el('button', {
        class: 'field-action' + (icon === '✗' ? ' danger' : ''), title, 'aria-label': title,
        onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); fn(); renderFields(); updatePreview(); },
      }, icon);
      const moveTo = (to) => { s.fields.splice(i, 1); s.fields.splice(to, 0, f); };
      const actions = el('span', { class: 'embed-field-actions' },
        action('▲', t('embedsClassic.moveUp'), i === 0, () => moveTo(i - 1)),
        action('▼', t('embedsClassic.moveDown'), i === s.fields.length - 1, () => moveTo(i + 1)),
        action('⧉', t('embedsClassic.duplicate'), s.fields.length >= EMBED_LIMITS.fields, () => {
          const dup = { name: f.name, value: f.value, inline: f.inline };
          s.fields.splice(i + 1, 0, dup);
          openFields.add(dup);
        }),
        action('✗', t('embedsClassic.delete'), false, () => { s.fields.splice(i, 1); openFields.delete(f); }));

      const det = el('details', { class: 'embed-field', open: openFields.has(f) ? '' : null },
        el('summary', { class: 'embed-field-head' }, handle, label, actions),
        el('div', { class: 'embed-field-body' },
          el('div', { class: 'embed-field-name-row' },
            name, el('label', { class: 'toggle' }, inline, t('embedsClassic.inlineLabel'))),
          value));
      det.ontoggle = () => { if (det.open) openFields.add(f); else openFields.delete(f); };

      handle.ondragstart = (e) => {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(i));
        det.classList.add('dragging');
      };
      handle.ondragend = () => det.classList.remove('dragging');
      det.ondragover = (e) => { e.preventDefault(); det.classList.add('drag-over'); };
      det.ondragleave = () => det.classList.remove('drag-over');
      det.ondrop = (e) => {
        e.preventDefault();
        det.classList.remove('drag-over');
        const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        if (Number.isNaN(from) || from === i) return;
        const [moved] = s.fields.splice(from, 1);
        s.fields.splice(i, 0, moved);
        renderFields();
        updatePreview();
      };
      fieldsBox.append(det);
    });
    addFieldBtn.disabled = s.fields.length >= EMBED_LIMITS.fields;
  }
  renderFields();

  // --- barra de embeds (tabs Embed 1..N + agregar + galería) ---
  const atMax = doc.embeds.length >= EMBED_LIMITS.count;
  const embedBar = el('div', { class: 'embed-bar-tabs' });
  // Reordenar mueve el contenido, no el tab activo: si movés el embed que
  // estás editando, la selección lo sigue a su nueva posición.
  function moveEmbed(i, to) {
    [doc.embeds[i], doc.embeds[to]] = [doc.embeds[to], doc.embeds[i]];
    if (doc.active === i) doc.active = to;
    else if (doc.active === to) doc.active = i;
    loadEmbeds();
  }
  doc.embeds.forEach((_, i) => {
    const pillActions = doc.embeds.length > 1 ? el('span', { class: 'embed-pill-actions' },
      el('span', {
        class: 'embed-pill-move' + (i === 0 ? ' disabled' : ''),
        title: t('embedsClassic.moveBefore'),
        onclick: (ev) => { ev.stopPropagation(); if (i > 0) moveEmbed(i, i - 1); },
      }, '◂'),
      el('span', {
        class: 'embed-pill-move' + (i === doc.embeds.length - 1 ? ' disabled' : ''),
        title: t('embedsClassic.moveAfter'),
        onclick: (ev) => { ev.stopPropagation(); if (i < doc.embeds.length - 1) moveEmbed(i, i + 1); },
      }, '▸'),
      el('span', {
        class: 'embed-pill-x',
        onclick: (ev) => {
          ev.stopPropagation();
          doc.embeds.splice(i, 1);
          if (doc.active >= doc.embeds.length) doc.active = doc.embeds.length - 1;
          loadEmbeds();
        },
      }, '✗')) : null;
    const pill = el('div', {
      class: 'embed-pill' + (i === doc.active ? ' active' : ''),
      onclick: () => { doc.active = i; loadEmbeds(); },
    }, t('embedsClassic.embedPillLabel', { index: i + 1 }), pillActions);
    embedPills.push(pill);
    embedBar.append(pill);
  });
  embedBar.append(el('button', {
    class: 'btn btn-secondary btn-sm', disabled: atMax || null,
    onclick: () => { doc.embeds.push(blankEmbed()); doc.active = doc.embeds.length - 1; loadEmbeds(); },
  }, t('embedsClassic.addEmbed')));
  embedBar.append(el('button', {
    class: 'btn btn-secondary btn-sm', disabled: atMax || null,
    title: t('embedsClassic.galleryTooltip'),
    onclick: () => {
      if (!s.image.trim()) { toast(t('embedsClassic.addImageFirst'), 'warn'); return; }
      // Discord agrupa en galería los embeds que comparten el mismo `url`;
      // usamos la imagen del embed activo como enlace compartido.
      const shared = s.url.trim() || s.image.trim();
      s.url = shared;
      const extra = blankEmbed();
      extra.url = shared;
      doc.embeds.push(extra);
      doc.active = doc.embeds.length - 1;
      loadEmbeds();
    },
  }, t('embedsClassic.addGallery')));

  // --- destino y modo de envío (persistidos en el doc) ---
  const chSel = channelSelect(channels, doc.channelId, t('embedsClassic.channelPlaceholder'));
  chSel.onchange = () => { doc.channelId = chSel.value; };
  const modeNow = el('input', { type: 'radio', name: 'embedMode', checked: doc.sendMode === 'now' });
  const modeSched = el('input', { type: 'radio', name: 'embedMode', checked: doc.sendMode === 'sched' });
  const schedType = el('select', {},
    el('option', { value: 'interval' }, t('embedsClassic.intervalOption')),
    el('option', { value: 'daily' }, t('embedsClassic.dailyOption')));
  schedType.value = doc.schedType;
  const intervalInput = el('input', { type: 'number', min: '5', max: '1440', value: doc.interval, style: 'width:110px' });
  const timeInput = el('input', { type: 'time', value: doc.time });
  const schedControls = el('div', { class: 'add-row', style: 'margin-top:8px' },
    schedType, intervalInput, timeInput);

  function syncSched() {
    doc.sendMode = modeSched.checked ? 'sched' : 'now';
    doc.schedType = schedType.value;
    schedControls.style.display = modeSched.checked ? '' : 'none';
    const daily = schedType.value === 'daily';
    intervalInput.style.display = daily ? 'none' : '';
    timeInput.style.display = daily ? '' : 'none';
    sendBtn.textContent = modeSched.checked ? t('embedsClassic.scheduleLabel') : t('embedsClassic.sendNowLabel');
  }
  modeNow.onchange = modeSched.onchange = schedType.onchange = syncSched;
  intervalInput.oninput = () => { doc.interval = intervalInput.value; };
  timeInput.oninput = () => { doc.time = timeInput.value; };

  // Error de validación persistente sobre la barra de acciones (el toast se
  // reserva para el resultado async de enviar/programar).
  const alertBox = el('div', {});

  const sendBtn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      const dicts = docDicts(doc);
      const err = validateEmbedsClient(dicts);
      if (err) { showFormAlert(alertBox, err); return; }
      if (!chSel.value) { showFormAlert(alertBox, t('embedsClassic.chooseChannel')); return; }
      showFormAlert(alertBox, '');
      try {
        const sendOpts = sendOptsToApi(doc.sendOpts);
        if (modeSched.checked) {
          const body = { channel_id: chSel.value, embeds: dicts, mode: schedType.value, send_options: sendOpts };
          if (schedType.value === 'interval') {
            body.interval_minutes = parseInt(intervalInput.value, 10);
          } else {
            const [h, m] = timeInput.value.split(':');
            body.hour = parseInt(h, 10); body.minute = parseInt(m, 10);
          }
          await apiFetch(`/api/server/${GUILD_ID}/embeds/schedule`, { method: 'POST', body });
          toast(t('embedsClassic.embedScheduled'), 'ok');
        } else {
          await apiFetch(`/api/server/${GUILD_ID}/embeds/send`, { method: 'POST', body: { channel_id: chSel.value, embeds: dicts, send_options: sendOpts } });
          toast(dicts.length > 1 ? t('embedsClassic.embedsSent', { count: dicts.length }) : t('embedsClassic.embedSentSingular'), 'ok');
          // Envío inmediato ya salió: el borrador de "lo que tengo a medio
          // escribir" dejó de tener sentido (a diferencia de programar, donde
          // seguís editando variantes). Ver criterio en el reporte.
          clearEmbedDraft('classic');
          // Mismo criterio para un share cargado: ya se usó, no re-cargarlo
          // al volver al selector.
          sessionStorage.removeItem('purgito_share_id');
        }
      } catch (err2) { toast(err2.message, err2.status === 429 ? 'warn' : 'err'); }
    },
  }, t('embedsClassic.sendNowLabel'));

  const saveBtn = el('button', {
    class: 'btn btn-secondary',
    onclick: async () => {
      const dicts = docDicts(doc);
      const err = validateEmbedsClient(dicts);
      if (err) { showFormAlert(alertBox, err); return; }
      showFormAlert(alertBox, '');
      const name = (prompt(t('embedsClassic.templateNamePrompt'), doc.templateName || '') || '').trim();
      if (!name) return;
      try {
        const body = { name, embeds: dicts, send_options: sendOptsToApi(doc.sendOpts) };
        if (doc.templateId) {
          await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${doc.templateId}`, { method: 'PUT', body });
          toast(t('embedsClassic.templateUpdated'), 'ok');
        } else {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`, { method: 'POST', body });
          doc.templateId = resp.id;
          toast(t('embedsClassic.templateSaved'), 'ok');
        }
        doc.templateName = name;
      } catch (err2) { toast(err2.message, err2.status === 409 ? 'warn' : 'err'); }
    },
  }, t('embedsClassic.saveAsTemplate'));

  const shareBtn = el('button', {
    class: 'btn btn-secondary',
    onclick: async () => {
      const dicts = docDicts(doc);
      const err = validateEmbedsClient(dicts);
      if (err) { showFormAlert(alertBox, err); return; }
      showFormAlert(alertBox, '');
      try {
        const resp = await apiFetch(`/api/server/${GUILD_ID}/embeds/share`, {
          method: 'POST', body: { embeds: dicts, send_options: sendOptsToApi(doc.sendOpts) },
        });
        toast(t('embedsClassic.shareLinkReady'), 'ok', {
          label: t('embedsClassic.copyLink'),
          onclick: async () => {
            try { await navigator.clipboard.writeText(resp.url); toast(t('embedsClassic.linkCopied'), 'ok'); }
            catch (e2) { prompt(t('embedsClassic.copyLinkPrompt'), resp.url); }
          },
        });
      } catch (err2) { toast(err2.message, err2.status === 429 ? 'warn' : 'err'); }
    },
  }, t('embedsClassic.share'));

  const clearBtn = el('button', {
    class: 'btn btn-secondary',
    onclick: () => { clearEmbedDraft('classic'); sessionStorage.removeItem('purgito_share_id'); setEmbedDoc(blankDoc()); loadEmbeds(); },
  }, t('embedsClassic.clear'));

  const histBtn = el('button', { class: 'btn btn-secondary', onclick: openHistoryModal }, t('embedsClassic.history'));
  const jsonBtn = el('button', { class: 'btn btn-secondary', onclick: openJsonModal }, t('embedsClassic.viewEditJson'));

  const form = el('div', { class: 'embed-form' },
    embedBar,
    accordionGroup(t('embedsClassic.bodySection'), true,
      fieldBlock(t('embedsClassic.titleLabel'), bound('input', 'title', { type: 'text', maxlength: String(EMBED_LIMITS.title) })),
      fieldBlock(t('embedsClassic.descriptionLabel'), insertWrap(
        bound('textarea', 'description', { maxlength: String(EMBED_LIMITS.description) }),
        ['menciones', 'fecha', 'emoji'])),
      fieldBlock(t('embedsClassic.colorLabel'), colorField(s, 'color', updatePreview)),
      fieldBlock(t('embedsClassic.dateOptionalLabel'), timestampField())),
    accordionGroup(t('embedsClassic.authorSection'), false,
      el('div', { class: 'embed-two' },
        fieldBlock(t('embedsClassic.nameLabel'), insertWrap(
          bound('input', 'authorName', { type: 'text', maxlength: String(EMBED_LIMITS.author) }), ['emoji'])),
        fieldBlock(t('embedsClassic.authorIconLabel'), imageField(s, 'authorIcon', updatePreview)))),
    accordionGroup(t('embedsClassic.imagesSection'), false,
      el('div', { class: 'embed-two' },
        fieldBlock(t('embedsClassic.thumbnailLabel'), imageField(s, 'thumbnail', updatePreview, { gif: true })),
        fieldBlock(t('embedsClassic.largeImageLabel'), imageField(s, 'image', updatePreview, { gif: true })))),
    accordionGroup(t('embedsClassic.footerSection'), false,
      el('div', { class: 'embed-two' },
        fieldBlock(t('embedsClassic.textLabel'), insertWrap(
          bound('input', 'footerText', { type: 'text', maxlength: String(EMBED_LIMITS.footer) }), ['emoji'])),
        fieldBlock(t('embedsClassic.footerIconLabel'), imageField(s, 'footerIcon', updatePreview)))),
    accordionGroup(t('embedsClassic.fieldsSection'), false,
      el('div', { class: 'field' }, fieldsBox, addFieldBtn)),
    formGroup(t('embedsClassic.destinationSection'),
      el('div', { class: 'field' }, el('label', {}, t('embedsClassic.targetChannelLabel')), chSel),
      el('div', { class: 'field' },
        el('label', { class: 'toggle' }, modeNow, t('embedsClassic.sendNowLabel')),
        el('label', { class: 'toggle' }, modeSched, t('embedsClassic.scheduleLabel')),
        schedControls),
      sendOptionsPanel(doc.sendOpts, roles, channels, chSel)),
    alertBox,
    el('div', { class: 'embed-actions' },
      sendBtn, saveBtn, shareBtn, clearBtn,
      el('span', { class: 'embed-actions-spacer' }),
      histBtn, jsonBtn));

  box.append(el('div', { class: 'embed-layout' },
    form,
    el('div', { class: 'd-embed-wrap' },
      el('p', { class: 'dim preview-header', style: 'margin-top:0' }, t('embedsClassic.previewLabel'), charCounter),
      previewBox)));
  box.querySelectorAll('.autogrow').forEach(autoGrow);
  updatePreview();
  syncSched();
}
