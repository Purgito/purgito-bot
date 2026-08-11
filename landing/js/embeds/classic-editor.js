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
      toast('Recuperamos tu borrador anterior', 'ok', {
        label: 'Descartar', onclick: () => { clearEmbedDraft('classic'); setEmbedDoc(blankDoc()); loadEmbeds(); },
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
      pill.title = empty ? 'Este embed está vacío y no se va a enviar' : '';
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
    }, 'Ahora');
    const clearBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm',
      onclick: () => { s.timestamp = ''; dt.value = ''; updatePreview(); },
    }, '✗');
    return el('div', { class: 'add-row' }, dt, nowBtn, clearBtn,
      helpIcon('Se muestra en el footer del embed, siempre convertido a la hora local de quien lo ve — no hace falta ajustar por zona horaria.'));
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
  }, '+ Agregar field');

  function renderFields() {
    fieldsBox.innerHTML = '';
    s.fields.forEach((f, i) => {
      // Header: "Field N" o "Field N — {nombre|valor}" (patrón fieldNText de
      // Discohook), actualizado en vivo mientras se escribe.
      const headText = () => {
        const t = (f.name || '').trim() || (f.value || '').trim();
        return `Field ${i + 1}` + (t ? ` — ${t.length > 40 ? t.slice(0, 40) + '…' : t}` : '');
      };
      const label = el('span', { class: 'embed-field-label' }, headText());

      const name = el('input', { type: 'text', placeholder: 'Nombre', maxlength: String(EMBED_LIMITS.fieldName), value: f.name });
      name.oninput = () => { f.name = name.value; label.textContent = headText(); updatePreview(); };
      const value = el('textarea', { placeholder: 'Valor', maxlength: String(EMBED_LIMITS.fieldValue), rows: '2' });
      value.value = f.value;
      value.oninput = () => { f.value = value.value; label.textContent = headText(); updatePreview(); };
      const inline = el('input', { type: 'checkbox', checked: f.inline });
      inline.onchange = () => { f.inline = inline.checked; updatePreview(); };

      // Solo el handle es draggable: arrastrar desde los inputs seguiría
      // seleccionando texto normalmente. DnD nativo (mismo enfoque que
      // Discohook) — no funciona en touch; ahí el fallback son los ▲/▼.
      const handle = el('span', {
        class: 'field-drag-handle', draggable: 'true',
        title: 'Arrastra para reordenar', 'aria-label': 'Arrastra para reordenar',
      }, '⠿');

      // Acciones del header. preventDefault evita que el click pliegue el
      // <details> (default de summary); el re-render repone visibilidad ▲/▼.
      const action = (icon, title, hidden, fn) => hidden ? null : el('button', {
        class: 'field-action' + (icon === '✗' ? ' danger' : ''), title, 'aria-label': title,
        onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); fn(); renderFields(); updatePreview(); },
      }, icon);
      const moveTo = (to) => { s.fields.splice(i, 1); s.fields.splice(to, 0, f); };
      const actions = el('span', { class: 'embed-field-actions' },
        action('▲', 'Mover arriba', i === 0, () => moveTo(i - 1)),
        action('▼', 'Mover abajo', i === s.fields.length - 1, () => moveTo(i + 1)),
        action('⧉', 'Duplicar', s.fields.length >= EMBED_LIMITS.fields, () => {
          const dup = { name: f.name, value: f.value, inline: f.inline };
          s.fields.splice(i + 1, 0, dup);
          openFields.add(dup);
        }),
        action('✗', 'Eliminar', false, () => { s.fields.splice(i, 1); openFields.delete(f); }));

      const det = el('details', { class: 'embed-field', open: openFields.has(f) ? '' : null },
        el('summary', { class: 'embed-field-head' }, handle, label, actions),
        el('div', { class: 'embed-field-body' },
          el('div', { class: 'embed-field-name-row' },
            name, el('label', { class: 'toggle' }, inline, 'inline')),
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
        title: 'Mover antes',
        onclick: (ev) => { ev.stopPropagation(); if (i > 0) moveEmbed(i, i - 1); },
      }, '◂'),
      el('span', {
        class: 'embed-pill-move' + (i === doc.embeds.length - 1 ? ' disabled' : ''),
        title: 'Mover después',
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
    }, 'Embed ' + (i + 1), pillActions);
    embedPills.push(pill);
    embedBar.append(pill);
  });
  embedBar.append(el('button', {
    class: 'btn btn-secondary btn-sm', disabled: atMax || null,
    onclick: () => { doc.embeds.push(blankEmbed()); doc.active = doc.embeds.length - 1; loadEmbeds(); },
  }, '+ Agregar embed'));
  embedBar.append(el('button', {
    class: 'btn btn-secondary btn-sm', disabled: atMax || null,
    title: 'Agrupa varias imágenes en una galería compartiendo el enlace del embed actual',
    onclick: () => {
      if (!s.image.trim()) { toast('Agrega primero una imagen a este embed', 'warn'); return; }
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
  }, '+ Galería'));

  // --- destino y modo de envío (persistidos en el doc) ---
  const chSel = channelSelect(channels, doc.channelId, 'Canal destino…');
  chSel.onchange = () => { doc.channelId = chSel.value; };
  const modeNow = el('input', { type: 'radio', name: 'embedMode', checked: doc.sendMode === 'now' });
  const modeSched = el('input', { type: 'radio', name: 'embedMode', checked: doc.sendMode === 'sched' });
  const schedType = el('select', {},
    el('option', { value: 'interval' }, 'Por intervalo'),
    el('option', { value: 'daily' }, 'A hora fija'));
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
    sendBtn.textContent = modeSched.checked ? 'Programar' : 'Enviar ahora';
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
      if (!chSel.value) { showFormAlert(alertBox, 'Elige un canal destino'); return; }
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
          toast('Embed programado', 'ok');
        } else {
          await apiFetch(`/api/server/${GUILD_ID}/embeds/send`, { method: 'POST', body: { channel_id: chSel.value, embeds: dicts, send_options: sendOpts } });
          toast(dicts.length > 1 ? `${dicts.length} embeds enviados` : 'Embed enviado', 'ok');
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
  }, 'Enviar ahora');

  const saveBtn = el('button', {
    class: 'btn btn-secondary',
    onclick: async () => {
      const dicts = docDicts(doc);
      const err = validateEmbedsClient(dicts);
      if (err) { showFormAlert(alertBox, err); return; }
      showFormAlert(alertBox, '');
      const name = (prompt('Nombre de la plantilla:', doc.templateName || '') || '').trim();
      if (!name) return;
      try {
        const body = { name, embeds: dicts, send_options: sendOptsToApi(doc.sendOpts) };
        if (doc.templateId) {
          await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${doc.templateId}`, { method: 'PUT', body });
          toast('Plantilla actualizada', 'ok');
        } else {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`, { method: 'POST', body });
          doc.templateId = resp.id;
          toast('Plantilla guardada', 'ok');
        }
        doc.templateName = name;
      } catch (err2) { toast(err2.message, err2.status === 409 ? 'warn' : 'err'); }
    },
  }, 'Guardar como plantilla');

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
        toast('Link listo — cualquiera con el link puede cargar este embed en su servidor', 'ok', {
          label: 'Copiar link',
          onclick: async () => {
            try { await navigator.clipboard.writeText(resp.url); toast('Link copiado', 'ok'); }
            catch (e2) { prompt('Copia el link:', resp.url); }
          },
        });
      } catch (err2) { toast(err2.message, err2.status === 429 ? 'warn' : 'err'); }
    },
  }, 'Compartir');

  const clearBtn = el('button', {
    class: 'btn btn-secondary',
    onclick: () => { clearEmbedDraft('classic'); sessionStorage.removeItem('purgito_share_id'); setEmbedDoc(blankDoc()); loadEmbeds(); },
  }, 'Limpiar');

  const histBtn = el('button', { class: 'btn btn-secondary', onclick: openHistoryModal }, 'Historial');
  const jsonBtn = el('button', { class: 'btn btn-secondary', onclick: openJsonModal }, 'Ver/editar JSON');

  const form = el('div', { class: 'embed-form' },
    embedBar,
    accordionGroup('Cuerpo', true,
      fieldBlock('Título', bound('input', 'title', { type: 'text', maxlength: String(EMBED_LIMITS.title) })),
      fieldBlock('Descripción', insertWrap(
        bound('textarea', 'description', { maxlength: String(EMBED_LIMITS.description) }),
        ['menciones', 'fecha', 'emoji'])),
      fieldBlock('Color', colorField(s, 'color', updatePreview)),
      fieldBlock('Fecha (opcional)', timestampField())),
    accordionGroup('Autor', !!(s.authorName || s.authorIcon),
      el('div', { class: 'embed-two' },
        fieldBlock('Nombre', insertWrap(
          bound('input', 'authorName', { type: 'text', maxlength: String(EMBED_LIMITS.author) }), ['emoji'])),
        fieldBlock('Ícono del autor', imageField(s, 'authorIcon', updatePreview)))),
    accordionGroup('Imágenes', !!(s.thumbnail || s.image),
      el('div', { class: 'embed-two' },
        fieldBlock('Thumbnail', imageField(s, 'thumbnail', updatePreview, { gif: true })),
        fieldBlock('Imagen grande', imageField(s, 'image', updatePreview, { gif: true })))),
    accordionGroup('Footer', !!(s.footerText || s.footerIcon),
      el('div', { class: 'embed-two' },
        fieldBlock('Texto', insertWrap(
          bound('input', 'footerText', { type: 'text', maxlength: String(EMBED_LIMITS.footer) }), ['emoji'])),
        fieldBlock('Ícono del footer', imageField(s, 'footerIcon', updatePreview)))),
    accordionGroup('Fields', s.fields.length > 0,
      el('div', { class: 'field' }, fieldsBox, addFieldBtn)),
    formGroup('Destino y envío',
      el('div', { class: 'field' }, el('label', {}, 'Canal destino'), chSel),
      el('div', { class: 'field' },
        el('label', { class: 'toggle' }, modeNow, 'Enviar ahora'),
        el('label', { class: 'toggle' }, modeSched, 'Programar'),
        schedControls),
      sendOptionsPanel(doc.sendOpts, roles)),
    alertBox,
    el('div', { class: 'embed-actions' },
      sendBtn, saveBtn, shareBtn, clearBtn,
      el('span', { class: 'embed-actions-spacer' }),
      histBtn, jsonBtn));

  box.append(el('div', { class: 'embed-layout' },
    form,
    el('div', { class: 'd-embed-wrap' },
      el('p', { class: 'dim preview-header', style: 'margin-top:0' }, 'Preview', charCounter),
      previewBox)));
  box.querySelectorAll('.autogrow').forEach(autoGrow);
  updatePreview();
  syncSched();
}
