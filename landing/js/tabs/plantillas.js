// Editor dedicado de una Plantilla (Texto | Embed + Botones), usado desde los
// configuradores de Bienvenidas/Despedidas/Boosts (js/tabs/eventos.js) y
// desde la lista de "Mis plantillas" en js/embeds/shared-ui.js.
//
// Vive separado de shared-ui.js/classic-editor.js a propósito: esos archivos
// comparten estado (session.js/state.js) con el editor multi-embed de
// "Crear / Enviar" y con la programación de anuncios — sumarles texto plano y
// botones ahí arriesgaba ese código ya en producción. Este editor es
// independiente y cubre texto/embed/botones, que es lo que necesitan los 3
// eventos. Layout V2 sigue disponible desde Plantillas (shared-ui.js) para
// quien lo necesite — no se duplica acá.

import { apiFetch } from '/js/core/api.js';
import {
  el, spinner, renderError, toast, autoGrow, icon,
} from '/js/core/dom.js';
import { GUILD_ID } from '/js/core/config.js';
import { getRoles, content } from '/js/panel-shell.js';
import { t, addStrings } from '/js/core/i18n.js';
import { EMBED_LIMITS } from '/js/embeds/state.js';
import { colorField, imageField } from '/js/embeds/shared-ui.js';

addStrings({
  es: {
    'tabsPlantillas.titleNew': 'Nueva plantilla',
    'tabsPlantillas.titleEdit': 'Editar plantilla',
    'tabsPlantillas.nameLabel': 'Nombre de la plantilla',
    'tabsPlantillas.namePlaceholder': 'Ej: Bienvenida clásica',
    'tabsPlantillas.nameRequired': 'La plantilla necesita un nombre',
    'tabsPlantillas.saveBtn': 'Guardar plantilla',
    'tabsPlantillas.saving': 'Guardando…',
    'tabsPlantillas.savedSuccess': 'Plantilla guardada',
    'tabsPlantillas.cancelBtn': 'Cancelar',
    'tabsPlantillas.emptyContentError': 'Escribí un mensaje o configurá un embed antes de guardar',
  },
  en: {
    'tabsPlantillas.titleNew': 'New template',
    'tabsPlantillas.titleEdit': 'Edit template',
    'tabsPlantillas.nameLabel': 'Template name',
    'tabsPlantillas.namePlaceholder': 'E.g: Classic welcome',
    'tabsPlantillas.nameRequired': 'The template needs a name',
    'tabsPlantillas.saveBtn': 'Save template',
    'tabsPlantillas.saving': 'Saving…',
    'tabsPlantillas.savedSuccess': 'Template saved',
    'tabsPlantillas.cancelBtn': 'Cancel',
    'tabsPlantillas.emptyContentError': 'Write a message or set up an embed before saving',
  },
});

function embedPayloadFromState(s) {
  const e = {};
  if (s.title && s.title.trim()) e.title = s.title.trim();
  if (s.description && s.description.trim()) e.description = s.description.trim();
  if (s.color) e.color = s.color;
  if (s.author_name && s.author_name.trim()) {
    e.author = { name: s.author_name.trim() };
    if (s.author_icon_url && s.author_icon_url.trim()) e.author.icon_url = s.author_icon_url.trim();
  }
  if (s.footer_text && s.footer_text.trim()) {
    e.footer = { text: s.footer_text.trim() };
    if (s.footer_icon_url && s.footer_icon_url.trim()) e.footer.icon_url = s.footer_icon_url.trim();
  }
  if (s.thumbnail && s.thumbnail.trim()) e.thumbnail = { url: s.thumbnail.trim() };
  if (s.image && s.image.trim()) e.image = { url: s.image.trim() };
  const fields = (s.fields || [])
    .filter(f => f.name.trim() && f.value.trim())
    .map(f => ({ name: f.name.trim(), value: f.value.trim(), inline: !!f.inline }));
  if (fields.length) e.fields = fields;
  return e;
}

function blankEmbedState() {
  return {
    title: '', description: '', color: '',
    author_name: '', author_icon_url: '',
    footer_text: '', footer_icon_url: '',
    thumbnail: '', image: '',
    fields: [],
  };
}

function embedStateFromPayload(e) {
  const s = blankEmbedState();
  if (!e || typeof e !== 'object') return s;
  s.title = e.title || '';
  s.description = e.description || '';
  s.color = typeof e.color === 'string' ? e.color : '';
  if (e.author) { s.author_name = e.author.name || ''; s.author_icon_url = e.author.icon_url || ''; }
  if (e.footer) { s.footer_text = e.footer.text || ''; s.footer_icon_url = e.footer.icon_url || ''; }
  if (e.thumbnail) s.thumbnail = e.thumbnail.url || '';
  if (e.image) s.image = e.image.url || '';
  s.fields = Array.isArray(e.fields) ? e.fields.map(f => ({ name: f.name || '', value: f.value || '', inline: !!f.inline })) : [];
  return s;
}

/**
 * Abre el editor de una plantilla existente (templateId numérico) o de una
 * nueva (templateId null) directamente en content(). opts.onSaved(id) y
 * opts.onCancel() controlan a dónde volver — por defecto, a la lista de
 * Plantillas (Mis plantillas).
 */
export async function loadTemplateEditor(templateId, opts = {}) {
  const myGuild = GUILD_ID;
  const box = content();
  box.innerHTML = '';
  box.append(spinner());

  try {
    const [templatesData, rolesData, eventsData] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/embeds/templates`),
      getRoles(),
      apiFetch(`/api/server/${GUILD_ID}/events`),
    ]);
    if (myGuild !== GUILD_ID) return;

    const existing = templateId != null
      ? (templatesData.templates || []).find(tpl => tpl.id === templateId)
      : null;
    if (templateId != null && !existing) {
      renderError(box, new Error('Plantilla no encontrada'));
      return;
    }

    renderTemplateEditor(box, existing, rolesData, eventsData.variables || [], opts);
  } catch (err) {
    if (myGuild !== GUILD_ID) return;
    renderError(box, err);
  }
}

function defaultDone() {
  import('/js/dash.js').then(({ activate }) => activate('embeds', true));
}

function renderTemplateEditor(container, existing, roles, allVariables, opts) {
  container.innerHTML = '';

  let name = existing ? existing.name : '';
  let format = existing && existing.content_mode === 'plain_text' ? 'text' : 'embed';
  if (existing && existing.content_mode === 'composite') {
    format = (existing.embeds && existing.embeds.length) ? 'embed' : 'text';
  }
  let currentMessage = existing ? (existing.message || '') : '';
  const embedState = embedStateFromPayload(existing && existing.embeds ? existing.embeds[0] : null);
  let buttons = existing && Array.isArray(existing.buttons) ? existing.buttons.map(b => ({ ...b })) : [];
  let isLayoutTemplate = existing ? existing.content_mode === 'layout_v2' : false;

  let lastActiveInput = null;
  function registerInputFocus(node) {
    node.addEventListener('focus', () => { lastActiveInput = node; });
    node.addEventListener('click', () => { lastActiveInput = node; });
  }

  // ── Variables: popover simple, sin categorías por evento (una plantilla
  // puede terminar usándose en cualquiera) ──────────────────────────────
  function openVariablesModal(targetInput) {
    const existingModal = document.getElementById('purg-variables-modal-backdrop');
    if (existingModal) existingModal.remove();
    const target = targetInput || lastActiveInput;

    const searchInput = el('input', {
      type: 'search', class: 'form-control form-control-sm var-modal-search',
      placeholder: t('tabsEventos.varsSearchPlaceholder'), autofocus: true,
    });
    const chipsGrid = el('div', { class: 'var-modal-grid' });

    function renderChips() {
      chipsGrid.innerHTML = '';
      const q = searchInput.value.toLowerCase().trim();
      const filtered = allVariables.filter(v => !q || v.name.toLowerCase().includes(q) || (v.description || '').toLowerCase().includes(q));
      for (const v of filtered) {
        const varTag = `{${v.name}}`;
        chipsGrid.append(el('button', {
          type: 'button', class: 'var-chip-compact',
          title: `${v.description || ''} (${t('tabsEventos.varExample')} ${v.example || ''})`,
          onclick: () => {
            if (target && typeof target.value === 'string') {
              const start = target.selectionStart ?? target.value.length;
              const end = target.selectionEnd ?? target.value.length;
              target.value = target.value.slice(0, start) + varTag + target.value.slice(end);
              target.selectionStart = target.selectionEnd = start + varTag.length;
              target.dispatchEvent(new Event('input', { bubbles: true }));
              target.focus();
              toast(t('tabsEventos.varsInserted', { var: varTag }), 'ok');
            } else if (navigator.clipboard) {
              navigator.clipboard.writeText(varTag);
              toast(t('tabsEventos.varsCopied', { var: varTag }), 'ok');
            }
            closeModal();
          },
        }, el('code', { class: 'var-tag' }, varTag), el('span', { class: 'var-desc' }, v.description || '')));
      }
    }
    searchInput.oninput = renderChips;
    renderChips();

    function closeModal() { document.removeEventListener('keydown', onKey); backdrop.remove(); }
    function onKey(e) { if (e.key === 'Escape') closeModal(); }
    document.addEventListener('keydown', onKey);

    const modalBox = el('div', { class: 'purg-variables-modal' },
      el('div', { class: 'var-modal-header' },
        el('div', { class: 'var-modal-title' }, icon('sparkle'), el('strong', {}, t('tabsEventos.varsTitle'))),
        el('button', { type: 'button', class: 'modal-close-btn', onclick: closeModal }, '✕')
      ),
      el('p', { class: 'dim text-xs', style: 'margin:0 0 10px 0;' }, t('tabsEventos.varsSubtitle')),
      searchInput, chipsGrid
    );
    const backdrop = el('div', {
      id: 'purg-variables-modal-backdrop', class: 'purg-modal-backdrop',
      onclick: (e) => { if (e.target === backdrop) closeModal(); },
    }, modalBox);
    document.body.append(backdrop);
    setTimeout(() => searchInput.focus(), 30);
  }

  // ── Nombre ───────────────────────────────────────────────────────────
  const nameInput = el('input', {
    class: 'form-control', placeholder: t('tabsPlantillas.namePlaceholder'), value: name, maxlength: '100',
  });
  nameInput.oninput = () => { name = nameInput.value; };

  const nameBlock = el('div', { class: 'cfg-block' },
    el('label', { class: 'cfg-field-label' }, t('tabsPlantillas.nameLabel')),
    nameInput
  );

  // ── Selector Texto | Embed + Botones + Layout V2 (contenedor dinámico) ─
  const contentCard = el('div', { class: 'card cfg-card' }, nameBlock);

  function buildMessageEditor() {
    const msgTxt = el('textarea', { class: 'form-control autogrow event-message-textarea', rows: 4 });
    msgTxt.value = currentMessage;
    registerInputFocus(msgTxt);
    const charCounter = el('span', { class: 'char-counter' }, t('tabsEventos.plainTextCounter', { count: currentMessage.length }));
    msgTxt.oninput = () => {
      currentMessage = msgTxt.value;
      autoGrow(msgTxt);
      charCounter.textContent = t('tabsEventos.plainTextCounter', { count: currentMessage.length });
      charCounter.className = 'char-counter' + (currentMessage.length > 2000 ? ' over' : '');
    };
    const moreVarsBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-xs btn-more-vars', onclick: () => openVariablesModal(msgTxt),
    }, icon('sparkle'), t('tabsEventos.insertVarBtn'));
    const bar = el('div', { class: 'event-textarea-bar' },
      el('div', { class: 'event-textarea-bar-left' }, moreVarsBtn),
      charCounter
    );
    return el('div', { class: 'cfg-format-body' }, msgTxt, bar);
  }

  function buildEmbedEditor() {
    const s = embedState;
    function boundInput(key, placeholder, isArea = false, maxL = null) {
      const inp = el(isArea ? 'textarea' : 'input', { class: 'form-control' + (isArea ? ' autogrow' : ''), placeholder, maxlength: maxL ? String(maxL) : null });
      inp.value = s[key] || '';
      registerInputFocus(inp);
      inp.oninput = () => { s[key] = inp.value; if (isArea) autoGrow(inp); };
      return inp;
    }

    const titleInput = boundInput('title', 'Título del embed…', false, EMBED_LIMITS.title);
    const descInput = boundInput('description', 'Descripción (soporta markdown y variables)…', true, EMBED_LIMITS.description);

    const authorRow = el('div', { class: 'grid-2' },
      el('div', { class: 'form-group-compact' }, el('label', {}, t('tabsEventos.embedAuthorNameLabel')), boundInput('author_name', 'Nombre del autor', false, EMBED_LIMITS.author)),
      el('div', { class: 'form-group-compact' }, el('label', {}, t('tabsEventos.embedAuthorIconLabel')), imageField(s, 'author_icon_url', () => {}))
    );
    const embedTitleRow = el('div', { class: 'form-group-compact' },
      el('div', { class: 'field-label-row' }, el('label', {}, t('tabsEventos.embedTitleLabel')), el('button', { type: 'button', class: 'btn-inline-var', onclick: () => openVariablesModal(titleInput) }, icon('sparkle'), '{ }')),
      titleInput
    );
    const embedDescRow = el('div', { class: 'form-group-compact' },
      el('div', { class: 'field-label-row' }, el('label', {}, t('tabsEventos.embedDescLabel')), el('button', { type: 'button', class: 'btn-inline-var', onclick: () => openVariablesModal(descInput) }, icon('sparkle'), '{ }')),
      descInput
    );

    const fieldsListWrap = el('div', { class: 'embed-fields-container' });
    s.fields = s.fields || [];
    function renderFields() {
      fieldsListWrap.innerHTML = '';
      s.fields.forEach((f, idx) => {
        const fName = el('input', { class: 'form-control form-control-sm', placeholder: t('tabsEventos.fieldNamePlaceholder'), value: f.name || '', maxlength: String(EMBED_LIMITS.fieldName) });
        registerInputFocus(fName);
        fName.oninput = () => { f.name = fName.value; };
        const fVal = el('input', { class: 'form-control form-control-sm', placeholder: t('tabsEventos.fieldValuePlaceholder'), value: f.value || '', maxlength: String(EMBED_LIMITS.fieldValue) });
        registerInputFocus(fVal);
        fVal.oninput = () => { f.value = fVal.value; };
        const inlineChk = el('input', { type: 'checkbox', checked: !!f.inline, onchange: () => { f.inline = inlineChk.checked; } });
        const delBtn = el('button', { type: 'button', class: 'btn btn-secondary btn-xs btn-field-del', onclick: () => { s.fields.splice(idx, 1); renderFields(); } }, '✕');
        fieldsListWrap.append(el('div', { class: 'embed-field-item-compact' },
          el('div', { class: 'field-inputs-compact' }, fName, fVal),
          el('label', { class: 'toggle toggle-xs' }, inlineChk, t('tabsEventos.fieldInlineLabel')),
          delBtn
        ));
      });
    }
    const addFieldBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-xs',
      onclick: () => {
        if (s.fields.length >= EMBED_LIMITS.fields) { toast(`Máximo ${EMBED_LIMITS.fields} campos`, 'warn'); return; }
        s.fields.push({ name: '', value: '', inline: false });
        renderFields();
      },
    }, t('tabsEventos.addFieldBtn'));
    renderFields();

    const imageRow = el('div', { class: 'form-group-compact' }, el('label', {}, t('tabsEventos.embedImageLabel')), imageField(s, 'image', () => {}, { gif: true }));
    const footerTextRow = el('div', { class: 'form-group-compact' }, el('label', {}, t('tabsEventos.embedFooterTextLabel')), boundInput('footer_text', 'Pie de página', false, EMBED_LIMITS.footer));

    const moreOptionsDetails = el('details', { class: 'event-advanced-accordion' },
      el('summary', { class: 'event-advanced-summary' }, el('div', { class: 'event-advanced-summary-title' }, t('tabsEventos.embedMoreOptions'))),
      el('div', { class: 'event-advanced-body' },
        el('div', { class: 'form-group-compact' }, el('label', {}, t('tabsEventos.embedColorLabel')), colorField(s, 'color', () => {})),
        el('div', { class: 'grid-2', style: 'margin-top: 10px;' },
          el('div', { class: 'form-group-compact' }, el('label', {}, t('tabsEventos.embedThumbLabel')), imageField(s, 'thumbnail', () => {}, { gif: true })),
          el('div', { class: 'form-group-compact' }, el('label', {}, t('tabsEventos.embedFooterIconLabel')), imageField(s, 'footer_icon_url', () => {}))
        )
      )
    );

    return el('div', { class: 'cfg-format-body' },
      authorRow, embedTitleRow, embedDescRow,
      el('div', { class: 'form-group-compact' }, el('div', { class: 'field-label-row' }, el('label', {}, t('tabsEventos.sectionFields')), addFieldBtn), fieldsListWrap),
      imageRow, footerTextRow, moreOptionsDetails
    );
  }

  const formatBodyWrap = el('div', { class: 'cfg-format-body' });
  const pillsWrap = el('div', { class: 'event-mode-pills' });

  function renderPills() {
    pillsWrap.innerHTML = '';
    for (const m of [
      { key: 'text', label: t('tabsEventos.modePlainText'), i: 'chat' },
      { key: 'embed', label: t('tabsEventos.modeClassicEmbed'), i: 'layout' },
    ]) {
      pillsWrap.append(el('button', {
        type: 'button', class: 'mode-pill' + (format === m.key ? ' active' : ''),
        onclick: () => { if (format === m.key) return; format = m.key; renderPills(); renderFormatBody(); },
      }, el('span', { class: 'mode-pill-icon' }, icon(m.i)), m.label));
    }
  }
  function renderFormatBody() {
    formatBodyWrap.innerHTML = '';
    formatBodyWrap.append(format === 'embed' ? buildEmbedEditor() : buildMessageEditor());
  }

  const formatSelectorRow = el('div', { class: 'event-format-selector' },
    el('label', { class: 'cfg-field-label' }, t('tabsEventos.contentModeLabel')), pillsWrap
  );

  // ── Botones ──────────────────────────────────────────────────────────
  const buttonsListWrap = el('div', { class: 'event-buttons-list' });
  function renderButtonsEditor() {
    buttonsListWrap.innerHTML = '';
    if (!buttons.length) {
      buttonsListWrap.append(el('p', { class: 'dim text-xs', style: 'margin:0; padding:4px 0;' }, t('tabsEventos.buttonsHelp')));
    }
    buttons.forEach((btn, idx) => {
      const lblInp = el('input', { class: 'form-control form-control-sm', placeholder: t('tabsEventos.buttonLabelPlaceholder'), value: btn.label || '', maxlength: '80' });
      registerInputFocus(lblInp);
      lblInp.oninput = () => { btn.label = lblInp.value; };

      const typeSel = el('select', { class: 'form-control form-control-sm' },
        el('option', { value: 'link', selected: btn.style !== 'role' }, t('tabsEventos.buttonTypeLink')),
        el('option', { value: 'role', selected: btn.style === 'role' }, t('tabsEventos.buttonTypeRole'))
      );
      const urlInp = el('input', { class: 'form-control form-control-sm', placeholder: t('tabsEventos.buttonUrlPlaceholder'), value: btn.url || '', style: btn.style === 'role' ? 'display:none;' : 'display:block;' });
      registerInputFocus(urlInp);
      urlInp.oninput = () => { btn.url = urlInp.value; };

      const roleSel = el('select', { class: 'form-control form-control-sm', style: btn.style === 'role' ? 'display:block;' : 'display:none;' },
        el('option', { value: '' }, 'Selecciona un rol…'),
        ...roles.map(r => el('option', { value: String(r.id), selected: String(btn.role_id) === String(r.id) }, r.name))
      );
      roleSel.onchange = () => { btn.role_id = roleSel.value ? parseInt(roleSel.value, 10) : null; };

      const colorSel = el('select', { class: 'form-control form-control-sm', style: btn.style === 'role' ? 'display:block;' : 'display:none;' },
        el('option', { value: 'secondary', selected: btn.color === 'secondary' }, t('tabsEventos.buttonColorSecondary')),
        el('option', { value: 'primary', selected: btn.color === 'primary' }, t('tabsEventos.buttonColorPrimary')),
        el('option', { value: 'success', selected: btn.color === 'success' }, t('tabsEventos.buttonColorSuccess')),
        el('option', { value: 'danger', selected: btn.color === 'danger' }, t('tabsEventos.buttonColorDanger'))
      );
      colorSel.onchange = () => { btn.color = colorSel.value; };

      typeSel.onchange = () => {
        btn.style = typeSel.value;
        urlInp.style.display = btn.style === 'role' ? 'none' : 'block';
        roleSel.style.display = btn.style === 'role' ? 'block' : 'none';
        colorSel.style.display = btn.style === 'role' ? 'block' : 'none';
      };

      const delBtn = el('button', { type: 'button', class: 'btn btn-secondary btn-xs btn-field-del', onclick: () => { buttons.splice(idx, 1); renderButtonsEditor(); } }, '✕');

      buttonsListWrap.append(el('div', { class: 'event-button-item' }, el('div', { class: 'event-button-grid' }, lblInp, typeSel, urlInp, roleSel, colorSel, delBtn)));
    });
  }
  const addBtnAction = el('button', {
    type: 'button', class: 'btn btn-secondary btn-xs',
    onclick: () => {
      if (buttons.length >= 5) { toast('Máximo 5 botones por fila', 'warn'); return; }
      buttons.push({ label: 'Enlace', style: 'link', url: 'https://discord.com' });
      renderButtonsEditor();
    },
  }, t('tabsEventos.addButton'));
  renderButtonsEditor();

  const buttonsBlock = el('div', { class: 'cfg-block' },
    el('div', { class: 'cfg-row' }, el('div', { class: 'cfg-block-label' }, t('tabsEventos.buttonsTitle')), addBtnAction),
    buttonsListWrap
  );

  renderPills();
  renderFormatBody();

  const contentBlock = el('div', { class: 'cfg-block' }, formatSelectorRow, formatBodyWrap);

  if (!isLayoutTemplate) {
    contentCard.append(contentBlock, buttonsBlock);
  } else {
    contentCard.append(el('div', { class: 'cfg-block' },
      el('p', { class: 'dim text-sm' }, 'Esta plantilla usa Layout V2 (bloques avanzados). Para editarla, abrí Plantillas → Crear / Enviar → Mis plantillas → Cargar en editor.')
    ));
  }

  // ── Acciones ─────────────────────────────────────────────────────────
  const saveBtn = el('button', {
    type: 'button', class: 'btn btn-primary',
    onclick: async () => {
      const trimmedName = name.trim();
      if (!trimmedName) { toast(t('tabsPlantillas.nameRequired'), 'err'); return; }
      const hasText = format === 'text' && currentMessage.trim();
      const embedPayload = embedPayloadFromState(embedState);
      const hasEmbed = format === 'embed' && Object.keys(embedPayload).length > 0;
      const hasButtons = buttons.length > 0;
      if (!hasText && !hasEmbed && !hasButtons) { toast(t('tabsPlantillas.emptyContentError'), 'err'); return; }

      let payload;
      if (hasButtons || (hasText && hasEmbed)) {
        payload = { name: trimmedName, content_mode: 'composite', message: hasText ? currentMessage : '' };
        if (hasEmbed) payload.embeds = [embedPayload];
        if (hasButtons) payload.buttons = buttons;
      } else if (hasEmbed) {
        payload = { name: trimmedName, content_mode: 'classic_embed', embeds: [embedPayload] };
      } else {
        payload = { name: trimmedName, content_mode: 'plain_text', message: currentMessage };
      }

      saveBtn.disabled = true;
      saveBtn.textContent = t('tabsPlantillas.saving');
      try {
        let id = existing ? existing.id : null;
        if (existing) {
          await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${existing.id}`, { method: 'PUT', body: JSON.stringify(payload) });
        } else {
          const res = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`, { method: 'POST', body: JSON.stringify(payload) });
          id = res.id;
        }
        toast(t('tabsPlantillas.savedSuccess'), 'ok');
        if (opts.onSaved) opts.onSaved(id);
        else defaultDone();
      } catch (err) {
        toast(err.message || 'Error', 'err');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = t('tabsPlantillas.saveBtn');
      }
    },
  }, t('tabsPlantillas.saveBtn'));

  const cancelBtn = el('button', {
    type: 'button', class: 'btn btn-secondary',
    onclick: () => { if (opts.onCancel) opts.onCancel(); else defaultDone(); },
  }, t('tabsPlantillas.cancelBtn'));

  const actionsBar = el('div', { class: 'event-actions-bar' }, el('div', { class: 'left-actions' }, saveBtn, cancelBtn));

  const headBlock = el('div', { class: 'cfg-block' },
    el('div', { class: 'cfg-head-row' }, el('div', { class: 'cfg-head-title' }, el('h1', {}, existing ? t('tabsPlantillas.titleEdit') : t('tabsPlantillas.titleNew'))))
  );

  container.append(el('div', { class: 'card cfg-card' }, headBlock), contentCard, actionsBar);
}
