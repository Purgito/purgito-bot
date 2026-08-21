// Editor Layout V2 (Components V2): lista editable de bloques + su preview.

import { GUILD_ID } from '/js/core/config.js';
import { apiFetch } from '/js/core/api.js';
import { el, autoGrow, previewEmpty, toast, showFormAlert, formGroup, helpIcon, spinner } from '/js/core/dom.js';
import { mdToNodes, previewImg, beginPreviewRender, endPreviewRender } from '/js/core/markdown.js';
import {
  componentCount, newBlock, LAYOUT_MAX_COMPONENTS, blockWarning, blockSummary,
  BLOCK_LABELS, stripBlockIds, colorToHex, blankLayoutDoc, blankSendOpts,
  blockToApi, sendOptsToApi, hasFileBlock, hasEmptyFileBlock, countFileBlocks,
  formatBytes, LAYOUT_MAX_FILES, LAYOUT_MAX_FILE_BYTES,
} from '/js/embeds/state.js';
import { _layoutDoc, setLayoutDoc } from '/js/embeds/session.js';
import { roleSelect, channelSelect } from '/js/panel-shell.js';
import {
  insertWrap, imageField, colorField, sendOptionsPanel, loadEmbeds, uploadLayoutFile,
} from '/js/embeds/shared-ui.js';
import {
  readEmbedDraft, clearEmbedDraft, scheduleHistorySnapshot, scheduleDraftSave,
  openHistoryModal, openJsonModal,
} from '/js/embeds/persistence.js';
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'embedsLayout.noBlocksYet': 'Todavía no hay bloques. Agregá el primero con los botones de abajo.',
    'embedsLayout.addText': '+ Texto',
    'embedsLayout.addSection': '+ Sección',
    'embedsLayout.addGallery': '+ Galería',
    'embedsLayout.addSeparator': '+ Separador',
    'embedsLayout.addButtons': '+ Botones',
    'embedsLayout.addFile': '+ Archivo',
    'embedsLayout.addContainer': '+ Container',
    'embedsLayout.maxFilesTooltip': 'Máximo {limit} archivos por mensaje',
    'embedsLayout.maxComponentsTooltip': 'Límite de {limit} componentes por mensaje alcanzado',
    'embedsLayout.expand': 'Expandir',
    'embedsLayout.collapse': 'Colapsar',
    'embedsLayout.dragToReorder': 'Arrastra para reordenar',
    'embedsLayout.duplicateBlock': 'Duplicar bloque',
    'embedsLayout.linkOption': 'Enlace',
    'embedsLayout.assignRoleOption': 'Asignar rol',
    'embedsLayout.buttonTextPlaceholder': 'Texto del botón',
    'embedsLayout.chooseRolePlaceholder': 'Elegir rol…',
    'embedsLayout.colorGray': 'Gris',
    'embedsLayout.colorBlurple': 'Blurple',
    'embedsLayout.colorGreen': 'Verde',
    'embedsLayout.colorRed': 'Rojo',
    'embedsLayout.assignRoleHelp': '"Asignar rol" alterna: si quien clickea no tiene el rol se lo da, si ya lo tiene se lo quita.',
    'embedsLayout.textMarkdownPlaceholder': 'Texto (markdown de Discord)',
    'embedsLayout.smallSpaceOption': 'Espacio chico',
    'embedsLayout.largeSpaceOption': 'Espacio grande',
    'embedsLayout.visibleLineLabel': 'Línea visible',
    'embedsLayout.descriptionOptionalPlaceholder': 'Descripción (opcional)',
    'embedsLayout.addImage': '+ Imagen',
    'embedsLayout.addButton': '+ Botón',
    'embedsLayout.textPlaceholderN': 'Texto {n}',
    'embedsLayout.addTextItem': '+ Texto',
    'embedsLayout.thumbnailOption': 'Miniatura',
    'embedsLayout.buttonOption': 'Botón',
    'embedsLayout.textsMaxLabel': 'Textos (máx 3)',
    'embedsLayout.accessoryLabel': 'Accesorio',
    'embedsLayout.fileTooLarge': 'El archivo supera el máximo de {size}',
    'embedsLayout.uploadingFile': 'Subiendo archivo…',
    'embedsLayout.uploadFailed': 'No se pudo subir: {error}',
    'embedsLayout.chooseFile': 'Elegir archivo',
    'embedsLayout.markAsSpoiler': 'Marcar como spoiler',
    'embedsLayout.spoilerHelp': 'Se ve pixelado hasta que alguien lo abre a propósito.',
    'embedsLayout.fileHint': 'Máx. {size}. Solo funciona con "Enviar ahora" — no se puede programar ni guardar en una plantilla.',
    'embedsLayout.accentBarLabel': 'Barra de color',
    'embedsLayout.accentBarHelp': 'Pinta un borde de color a la izquierda de todo el container, como el de un embed clásico.',
    'embedsLayout.previewEmptyHint': 'Agrega bloques para ver tu mensaje',
    'embedsLayout.buttonFallbackLabel': 'botón',
    'embedsLayout.roleTag': 'ROL',
    'embedsLayout.noFilePlaceholder': '(sin archivo)',
    'embedsLayout.v2Warning': 'Los layouts V2 no pueden combinar con embeds clásicos en el mismo mensaje — es una limitación de Discord, no del panel.',
    'embedsLayout.draftRecovered': 'Recuperamos tu borrador anterior',
    'embedsLayout.discard': 'Descartar',
    'embedsLayout.schedBlockedByFile': 'No disponible: el layout tiene un bloque de archivo',
    'embedsLayout.channelPlaceholder': 'Canal destino…',
    'embedsLayout.intervalOption': 'Por intervalo',
    'embedsLayout.dailyOption': 'A hora fija',
    'embedsLayout.scheduleLabel': 'Programar',
    'embedsLayout.sendNowLabel': 'Enviar ahora',
    'embedsLayout.needAtLeastOneBlock': 'Agrega al menos un bloque',
    'embedsLayout.chooseChannel': 'Elige un canal destino',
    'embedsLayout.emptyFileBlock': 'Hay un bloque de archivo sin elegir todavía.',
    'embedsLayout.fileBlockCantSchedule': 'Los bloques de archivo no se pueden programar — usa "Enviar ahora".',
    'embedsLayout.layoutScheduled': 'Layout programado',
    'embedsLayout.layoutSent': 'Layout enviado',
    'embedsLayout.fileBlockCantSaveTemplate': 'Los bloques de archivo no se pueden guardar en una plantilla — usa "Enviar ahora".',
    'embedsLayout.templateNamePrompt': 'Nombre de la plantilla:',
    'embedsLayout.templateUpdated': 'Plantilla actualizada',
    'embedsLayout.templateSaved': 'Plantilla guardada',
    'embedsLayout.saveAsTemplate': 'Guardar como plantilla',
    'embedsLayout.clear': 'Limpiar',
    'embedsLayout.history': 'Historial',
    'embedsLayout.viewEditJson': 'Ver/editar JSON',
    'embedsLayout.blocksSection': 'Bloques',
    'embedsLayout.destinationSection': 'Destino y envío',
    'embedsLayout.targetChannelLabel': 'Canal destino',
    'embedsLayout.previewLabel': 'Preview',
  },
  en: {
    'embedsLayout.noBlocksYet': 'No blocks yet. Add the first one with the buttons below.',
    'embedsLayout.addText': '+ Text',
    'embedsLayout.addSection': '+ Section',
    'embedsLayout.addGallery': '+ Gallery',
    'embedsLayout.addSeparator': '+ Separator',
    'embedsLayout.addButtons': '+ Buttons',
    'embedsLayout.addFile': '+ File',
    'embedsLayout.addContainer': '+ Container',
    'embedsLayout.maxFilesTooltip': 'Maximum of {limit} files per message',
    'embedsLayout.maxComponentsTooltip': 'Limit of {limit} components per message reached',
    'embedsLayout.expand': 'Expand',
    'embedsLayout.collapse': 'Collapse',
    'embedsLayout.dragToReorder': 'Drag to reorder',
    'embedsLayout.duplicateBlock': 'Duplicate block',
    'embedsLayout.linkOption': 'Link',
    'embedsLayout.assignRoleOption': 'Assign role',
    'embedsLayout.buttonTextPlaceholder': 'Button text',
    'embedsLayout.chooseRolePlaceholder': 'Choose role…',
    'embedsLayout.colorGray': 'Gray',
    'embedsLayout.colorBlurple': 'Blurple',
    'embedsLayout.colorGreen': 'Green',
    'embedsLayout.colorRed': 'Red',
    'embedsLayout.assignRoleHelp': '"Assign role" toggles it: if the clicker doesn\'t have the role they get it, if they already have it they lose it.',
    'embedsLayout.textMarkdownPlaceholder': 'Text (Discord markdown)',
    'embedsLayout.smallSpaceOption': 'Small spacing',
    'embedsLayout.largeSpaceOption': 'Large spacing',
    'embedsLayout.visibleLineLabel': 'Visible line',
    'embedsLayout.descriptionOptionalPlaceholder': 'Description (optional)',
    'embedsLayout.addImage': '+ Image',
    'embedsLayout.addButton': '+ Button',
    'embedsLayout.textPlaceholderN': 'Text {n}',
    'embedsLayout.addTextItem': '+ Text',
    'embedsLayout.thumbnailOption': 'Thumbnail',
    'embedsLayout.buttonOption': 'Button',
    'embedsLayout.textsMaxLabel': 'Texts (max 3)',
    'embedsLayout.accessoryLabel': 'Accessory',
    'embedsLayout.fileTooLarge': 'The file exceeds the maximum of {size}',
    'embedsLayout.uploadingFile': 'Uploading file…',
    'embedsLayout.uploadFailed': 'Could not upload: {error}',
    'embedsLayout.chooseFile': 'Choose file',
    'embedsLayout.markAsSpoiler': 'Mark as spoiler',
    'embedsLayout.spoilerHelp': 'Shows up pixelated until someone deliberately opens it.',
    'embedsLayout.fileHint': 'Max. {size}. Only works with "Send now" — can\'t be scheduled or saved in a template.',
    'embedsLayout.accentBarLabel': 'Color bar',
    'embedsLayout.accentBarHelp': 'Paints a colored border on the left of the entire container, like a classic embed\'s.',
    'embedsLayout.previewEmptyHint': 'Add blocks to see your message',
    'embedsLayout.buttonFallbackLabel': 'button',
    'embedsLayout.roleTag': 'ROLE',
    'embedsLayout.noFilePlaceholder': '(no file)',
    'embedsLayout.v2Warning': 'V2 layouts can\'t be combined with classic embeds in the same message — that\'s a Discord limitation, not the panel\'s.',
    'embedsLayout.draftRecovered': 'We recovered your previous draft',
    'embedsLayout.discard': 'Discard',
    'embedsLayout.schedBlockedByFile': 'Not available: the layout has a file block',
    'embedsLayout.channelPlaceholder': 'Target channel…',
    'embedsLayout.intervalOption': 'By interval',
    'embedsLayout.dailyOption': 'At a fixed time',
    'embedsLayout.scheduleLabel': 'Schedule',
    'embedsLayout.sendNowLabel': 'Send now',
    'embedsLayout.needAtLeastOneBlock': 'Add at least one block',
    'embedsLayout.chooseChannel': 'Choose a target channel',
    'embedsLayout.emptyFileBlock': 'There\'s a file block with nothing chosen yet.',
    'embedsLayout.fileBlockCantSchedule': 'File blocks can\'t be scheduled — use "Send now".',
    'embedsLayout.layoutScheduled': 'Layout scheduled',
    'embedsLayout.layoutSent': 'Layout sent',
    'embedsLayout.fileBlockCantSaveTemplate': 'File blocks can\'t be saved in a template — use "Send now".',
    'embedsLayout.templateNamePrompt': 'Template name:',
    'embedsLayout.templateUpdated': 'Template updated',
    'embedsLayout.templateSaved': 'Template saved',
    'embedsLayout.saveAsTemplate': 'Save as template',
    'embedsLayout.clear': 'Clear',
    'embedsLayout.history': 'History',
    'embedsLayout.viewEditJson': 'View/edit JSON',
    'embedsLayout.blocksSection': 'Blocks',
    'embedsLayout.destinationSection': 'Destination and sending',
    'embedsLayout.targetChannelLabel': 'Target channel',
    'embedsLayout.previewLabel': 'Preview',
  },
});

// Lista editable de bloques (recursiva: un container tiene su propia lista).
export function renderBlocks(listEl, blocks, inContainer, onChange, roles) {
  listEl.innerHTML = '';
  // Token propio de esta lista (distinto en cada render): el drag & drop de
  // abajo lo usa para que soltar un bloque solo reordene dentro de la MISMA
  // lista de la que salió — un container tiene su propia lista anidada, y sin
  // esto arrastrar un bloque del nivel raíz hasta adentro de un container (u
  // otro container hermano) mezclaría índices de arrays distintos.
  const listToken = Math.random().toString(36).slice(2);
  // Numeración correlativa POR TIPO (un Separator entre dos Textos no corre
  // la numeración de los Textos).
  const typeCounts = {};
  blocks.forEach((b, i) => {
    typeCounts[b.type] = (typeCounts[b.type] || 0) + 1;
    listEl.append(renderBlockCard(listEl, blocks, i, typeCounts[b.type], inContainer, onChange, roles, listToken));
  });
  // Outline recién iniciado: invitar a agregar el primer bloque en vez de una
  // lista vacía sin indicación.
  if (!blocks.length && !inContainer) {
    listEl.append(el('div', { class: 'outline-empty' },
      t('embedsLayout.noBlocksYet')));
  }
  const adder = el('div', { class: 'add-row layout-adder' });
  const atMax = componentCount(_layoutDoc ? _layoutDoc.blocks : blocks) >= LAYOUT_MAX_COMPONENTS;
  const types = [['text', t('embedsLayout.addText')], ['section', t('embedsLayout.addSection')], ['media_gallery', t('embedsLayout.addGallery')],
                 ['separator', t('embedsLayout.addSeparator')], ['action_row', t('embedsLayout.addButtons')], ['file', t('embedsLayout.addFile')]];
  if (!inContainer) types.push(['container', t('embedsLayout.addContainer')]);
  for (const [blockType, label] of types) {
    // "+ Archivo" además respeta su propio tope (Discord: adjuntos por
    // mensaje), independiente del tope general de componentes.
    const atFileMax = blockType === 'file'
      && countFileBlocks(_layoutDoc ? _layoutDoc.blocks : blocks) >= LAYOUT_MAX_FILES;
    const disabled = atMax || atFileMax;
    adder.append(el('button', {
      class: 'btn btn-secondary btn-sm',
      disabled: disabled || null,
      title: atFileMax
        ? t('embedsLayout.maxFilesTooltip', { limit: LAYOUT_MAX_FILES })
        : atMax ? t('embedsLayout.maxComponentsTooltip', { limit: LAYOUT_MAX_COMPONENTS }) : null,
      onclick: () => { blocks.push(newBlock(blockType)); renderBlocks(listEl, blocks, inContainer, onChange, roles); onChange(); },
    }, label));
  }
  listEl.append(adder);
}

// MIME propio (no 'text/plain') para llevar el token de la lista de origen en
// el dataTransfer, junto al índice — ver comentario del token en renderBlocks.
const LV2_DRAG_TYPE = 'application/x-purgito-blocklist';

export function renderBlockCard(listEl, blocks, i, typeNum, inContainer, onChange, roles, listToken) {
  const b = blocks[i];
  function rerender() { renderBlocks(listEl, blocks, inContainer, onChange, roles); onChange(); }
  const warn = blockWarning(b);
  const summary = blockSummary(b);
  const body = el('div', { class: 'layout-block-body' }, renderBlockForm(b, onChange, roles));
  if (b._collapsed) body.style.display = 'none';
  const toggle = el('button', {
    class: 'btn btn-secondary btn-sm',
    title: b._collapsed ? t('embedsLayout.expand') : t('embedsLayout.collapse'),
    onclick: () => {
      // _collapsed vive solo en el estado del editor (blockToApi nunca lo copia).
      b._collapsed = !b._collapsed;
      rerender();
    },
  }, b._collapsed ? '▸' : '▾');
  // Solo el handle es draggable (igual criterio que los fields del embed
  // clásico): arrastrar desde un input/textarea del cuerpo del bloque debe
  // seguir seleccionando texto normalmente, no mover el bloque.
  const handle = el('span', {
    class: 'layout-block-handle', draggable: 'true',
    title: t('embedsLayout.dragToReorder'), 'aria-label': t('embedsLayout.dragToReorder'),
  }, '⠿');
  const head = el('div', { class: 'layout-block-head' },
    el('span', { class: 'layout-block-title' },
      handle, toggle,
      el('span', { class: 'layout-block-type' }, `${BLOCK_LABELS[b.type]} ${typeNum}`),
      warn ? el('span', { class: 'layout-warn', title: warn }, '!') : null,
      summary ? el('span', { class: 'layout-block-summary dim' }, summary) : null),
    el('span', { class: 'layout-block-actions' },
      el('button', {
        class: 'btn btn-secondary btn-sm', title: t('embedsLayout.duplicateBlock'),
        disabled: componentCount(_layoutDoc ? _layoutDoc.blocks : blocks) >= LAYOUT_MAX_COMPONENTS || null,
        onclick: () => {
          const copy = structuredClone(b);
          stripBlockIds(copy);
          blocks.splice(i + 1, 0, copy);
          rerender();
        },
      }, '⧉'),
      // Las flechas quedan como fallback para touch (el drag HTML5 no anda
      // ahí) y como acción rápida sin tener que arrastrar.
      el('button', { class: 'btn btn-secondary btn-sm', disabled: i === 0 || null, onclick: () => { [blocks[i - 1], blocks[i]] = [blocks[i], blocks[i - 1]]; rerender(); } }, '↑'),
      el('button', { class: 'btn btn-secondary btn-sm', disabled: i === blocks.length - 1 || null, onclick: () => { [blocks[i + 1], blocks[i]] = [blocks[i], blocks[i + 1]]; rerender(); } }, '↓'),
      el('button', { class: 'btn btn-danger btn-sm', onclick: () => { blocks.splice(i, 1); rerender(); } }, '✗')));
  const card = el('div', { class: 'layout-block' }, head, body);

  handle.ondragstart = (e) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(i));
    e.dataTransfer.setData(LV2_DRAG_TYPE, listToken);
    card.classList.add('dragging');
  };
  handle.ondragend = () => card.classList.remove('dragging');
  card.ondragover = (e) => {
    // dataTransfer.getData() no es legible en dragover en todos los
    // navegadores (solo .types) — por eso el chequeo de lista propia se hace
    // recién en ondrop; acá solo se anticipa la indicación visual.
    if (!e.dataTransfer.types.includes(LV2_DRAG_TYPE)) return;
    e.preventDefault();
    card.classList.add('drag-over');
  };
  card.ondragleave = () => card.classList.remove('drag-over');
  card.ondrop = (e) => {
    card.classList.remove('drag-over');
    if (e.dataTransfer.getData(LV2_DRAG_TYPE) !== listToken) return; // otra lista (raíz vs. un container u otro)
    e.preventDefault();
    const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (Number.isNaN(from) || from === i) return;
    const [moved] = blocks.splice(from, 1);
    blocks.splice(i, 0, moved);
    rerender();
  };

  return card;
}

// Campos de un botón: selector Enlace/Asignar rol + los inputs correspondientes.
export function buttonStyleFields(bt, onChange, roles) {
  const styleSel = el('select', {}, el('option', { value: 'link' }, t('embedsLayout.linkOption')), el('option', { value: 'role' }, t('embedsLayout.assignRoleOption')));
  styleSel.value = bt.style || 'link';
  const label = el('input', { type: 'text', placeholder: t('embedsLayout.buttonTextPlaceholder'), maxlength: '80', value: bt.label });
  label.oninput = () => { bt.label = label.value; onChange(); };
  const urlInput = el('input', { type: 'url', placeholder: 'https://…', value: bt.url || '' });
  urlInput.oninput = () => { bt.url = urlInput.value; onChange(); };
  const roleSel = roleSelect(roles, bt.role_id, t('embedsLayout.chooseRolePlaceholder'));
  roleSel.onchange = () => { bt.role_id = roleSel.value; onChange(); };
  // Color (Fase 4): solo para botones de rol -- uno de link siempre es el
  // mismo gris con ícono en Discord, no se puede recolorear.
  const colorSel = el('select', {},
    el('option', { value: 'secondary' }, t('embedsLayout.colorGray')),
    el('option', { value: 'primary' }, t('embedsLayout.colorBlurple')),
    el('option', { value: 'success' }, t('embedsLayout.colorGreen')),
    el('option', { value: 'danger' }, t('embedsLayout.colorRed')));
  colorSel.value = bt.color || 'secondary';
  colorSel.onchange = () => { bt.color = colorSel.value; onChange(); };
  function sync() {
    const isRole = styleSel.value === 'role';
    urlInput.style.display = isRole ? 'none' : '';
    roleSel.style.display = isRole ? '' : 'none';
    colorSel.style.display = isRole ? '' : 'none';
  }
  styleSel.onchange = () => { bt.style = styleSel.value; sync(); onChange(); };
  sync();
  return el('div', { class: 'add-row layout-btn-fields' }, styleSel, label, urlInput, roleSel, colorSel,
    helpIcon(t('embedsLayout.assignRoleHelp')));
}

export function renderBlockForm(b, onChange, roles) {
  if (b.type === 'text') {
    const ta = el('textarea', { class: 'autogrow', placeholder: t('embedsLayout.textMarkdownPlaceholder') });
    ta.value = b.content;
    ta.oninput = () => { b.content = ta.value; autoGrow(ta); onChange(); };
    return insertWrap(ta, ['menciones', 'fecha', 'emoji']);
  }
  if (b.type === 'separator') {
    const vis = el('input', { type: 'checkbox', checked: b.visible });
    vis.onchange = () => { b.visible = vis.checked; onChange(); };
    const sp = el('select', {}, el('option', { value: 'small' }, t('embedsLayout.smallSpaceOption')), el('option', { value: 'large' }, t('embedsLayout.largeSpaceOption')));
    sp.value = b.spacing;
    sp.onchange = () => { b.spacing = sp.value; onChange(); };
    return el('div', { class: 'add-row' }, el('label', { class: 'toggle' }, vis, t('embedsLayout.visibleLineLabel')), sp);
  }
  if (b.type === 'media_gallery') {
    const box = el('div', {});
    function renderItems() {
      box.innerHTML = '';
      b.items.forEach((it, idx) => {
        const desc = el('input', { type: 'text', placeholder: t('embedsLayout.descriptionOptionalPlaceholder'), value: it.description });
        desc.oninput = () => { it.description = desc.value; onChange(); };
        box.append(el('div', { class: 'gallery-item-row' },
          imageField(it, 'url', onChange),
          desc,
          b.items.length > 1 ? el('button', { class: 'btn btn-danger btn-sm', onclick: () => { b.items.splice(idx, 1); renderItems(); onChange(); } }, '✗') : null));
      });
      box.append(el('button', { class: 'btn btn-secondary btn-sm', disabled: b.items.length >= 10 || null, onclick: () => { b.items.push({ url: '', description: '' }); renderItems(); onChange(); } }, t('embedsLayout.addImage')));
    }
    renderItems();
    return box;
  }
  if (b.type === 'action_row') {
    const box = el('div', {});
    function renderBtns() {
      box.innerHTML = '';
      b.buttons.forEach((bt, idx) => {
        box.append(el('div', { class: 'layout-btn-row' },
          buttonStyleFields(bt, onChange, roles),
          el('button', { class: 'btn btn-danger btn-sm', onclick: () => { b.buttons.splice(idx, 1); renderBtns(); onChange(); } }, '✗')));
      });
      box.append(el('button', { class: 'btn btn-secondary btn-sm', disabled: b.buttons.length >= 5 || null, onclick: () => { b.buttons.push({ style: 'link', label: '', url: '', role_id: '', color: 'secondary' }); renderBtns(); onChange(); } }, t('embedsLayout.addButton')));
    }
    renderBtns();
    return box;
  }
  if (b.type === 'section') {
    const box = el('div', {});
    const textsBox = el('div', {});
    function renderTexts() {
      textsBox.innerHTML = '';
      b.texts.forEach((tx, idx) => {
        const inp = el('input', { type: 'text', placeholder: t('embedsLayout.textPlaceholderN', { n: idx + 1 }), value: tx });
        inp.oninput = () => { b.texts[idx] = inp.value; onChange(); };
        textsBox.append(el('div', { class: 'add-row' }, insertWrap(inp, ['menciones', 'fecha', 'emoji']),
          b.texts.length > 1 ? el('button', { class: 'btn btn-danger btn-sm', onclick: () => { b.texts.splice(idx, 1); renderTexts(); onChange(); } }, '✗') : null));
      });
      textsBox.append(el('button', { class: 'btn btn-secondary btn-sm', disabled: b.texts.length >= 3 || null, onclick: () => { b.texts.push(''); renderTexts(); onChange(); } }, t('embedsLayout.addTextItem')));
    }
    renderTexts();
    const accType = el('select', {}, el('option', { value: 'thumbnail' }, t('embedsLayout.thumbnailOption')), el('option', { value: 'button' }, t('embedsLayout.buttonOption')));
    accType.value = b.accessory.type;
    const accBox = el('div', {});
    function renderAcc() {
      accBox.innerHTML = '';
      if (b.accessory.type === 'thumbnail') {
        const desc = el('input', { type: 'text', placeholder: t('embedsLayout.descriptionOptionalPlaceholder'), value: b.accessory.description });
        desc.oninput = () => { b.accessory.description = desc.value; onChange(); };
        accBox.append(el('div', { class: 'add-row' }, imageField(b.accessory, 'url', onChange), desc));
      } else {
        accBox.append(buttonStyleFields(b.accessory, onChange, roles));
      }
    }
    accType.onchange = () => { b.accessory.type = accType.value; renderAcc(); onChange(); };
    renderAcc();
    return el('div', {},
      el('div', { class: 'field' }, el('label', {}, t('embedsLayout.textsMaxLabel')), textsBox),
      el('div', { class: 'field' }, el('label', {}, t('embedsLayout.accessoryLabel')), accType, accBox));
  }
  if (b.type === 'file') {
    const box = el('div', {});
    function render() {
      box.innerHTML = '';
      if (b.upload) {
        box.append(el('div', { class: 'img-chip' },
          el('span', { class: 'img-chip-name' }, b.upload.filename
            + (b.upload.size ? ` (${formatBytes(b.upload.size)})` : '')),
          el('button', { class: 'btn btn-danger btn-sm', onclick: () => { b.upload = null; render(); onChange(); } }, '✗')));
        return;
      }
      const fileInput = el('input', { type: 'file', style: 'display:none' });
      fileInput.onchange = async () => {
        const file = fileInput.files[0];
        if (!file) return;
        if (file.size > LAYOUT_MAX_FILE_BYTES) {
          toast(t('embedsLayout.fileTooLarge', { size: formatBytes(LAYOUT_MAX_FILE_BYTES) }), 'warn');
          return;
        }
        box.innerHTML = '';
        box.append(el('div', { class: 'img-uploading' }, spinner(), el('span', {}, t('embedsLayout.uploadingFile'))));
        try {
          const upload = await uploadLayoutFile(file);
          b.upload = { id: upload.id, filename: upload.filename, size: file.size };
          render();
          onChange();
        } catch (e) {
          render();
          box.prepend(el('div', { class: 'img-error' }, t('embedsLayout.uploadFailed', { error: e.message })));
          toast(e.message, e.status === 429 ? 'warn' : 'err');
        }
      };
      box.append(
        el('button', { type: 'button', class: 'btn btn-primary', onclick: () => fileInput.click() }, t('embedsLayout.chooseFile')),
        fileInput);
    }
    render();
    const spoilerChk = el('input', { type: 'checkbox', checked: b.spoiler });
    spoilerChk.onchange = () => { b.spoiler = spoilerChk.checked; onChange(); };
    return el('div', {}, box,
      el('div', { class: 'add-row' },
        el('label', { class: 'toggle' }, spoilerChk, t('embedsLayout.markAsSpoiler')),
        helpIcon(t('embedsLayout.spoilerHelp'))),
      el('p', { class: 'dim' },
        t('embedsLayout.fileHint', { size: formatBytes(LAYOUT_MAX_FILE_BYTES) })));
  }
  // container
  const box = el('div', {});
  const accentChk = el('input', { type: 'checkbox', checked: b.accent });
  accentChk.onchange = () => { b.accent = accentChk.checked; onChange(); };
  box.append(el('div', { class: 'add-row' },
    el('label', { class: 'toggle' }, accentChk, t('embedsLayout.accentBarLabel')),
    helpIcon(t('embedsLayout.accentBarHelp')),
    colorField(b, 'accent_color', onChange)));
  const nested = el('div', { class: 'layout-nested' });
  renderBlocks(nested, b.children, true, onChange, roles);
  box.append(nested);
  return box;
}

// Preview anidado de un layout (bloques ya en formato API).
export function renderLayoutPreview(blocks) {
  if (!blocks.length) return previewEmpty(t('embedsLayout.previewEmptyHint'));
  const wrap = el('div', { class: 'lv2-preview' });
  for (const b of blocks) wrap.append(renderPreviewBlock(b));
  return wrap;
}

// Botón del preview: los de "asignar rol" llevan una etiqueta de texto (sin
// emoji, mismo criterio del resto del panel) para distinguirlos de un link.
export function lv2Button(bt) {
  // Color real de Discord (Fase 4) solo para botones de rol -- uno de link
  // siempre se ve igual (gris + ícono), Discord no lo deja recolorear.
  const colorClass = bt.style === 'role' ? ` lv2-btn-${bt.color || 'secondary'}` : '';
  return el('span', { class: 'lv2-btn' + colorClass },
    bt.label || t('embedsLayout.buttonFallbackLabel'), bt.style === 'role' ? el('span', { class: 'lv2-btn-tag' }, t('embedsLayout.roleTag')) : null);
}

export function renderPreviewBlock(b) {
  if (b.type === 'container') {
    const inner = el('div', { class: 'lv2-container-inner' });
    for (const c of b.children) inner.append(renderPreviewBlock(c));
    const cont = el('div', { class: 'lv2-container' }, inner);
    if (b.accent_color != null) cont.style.borderLeft = '4px solid ' + (colorToHex(b.accent_color) || '#8B6EF5');
    return cont;
  }
  if (b.type === 'text') return el('div', { class: 'lv2-text' }, ...mdToNodes(b.content || ''));
  if (b.type === 'section') {
    const texts = el('div', { class: 'lv2-section-texts' },
      b.texts.map(tx => el('div', { class: 'lv2-text' }, ...mdToNodes(tx))));
    let acc;
    if (b.accessory.type === 'thumbnail') acc = b.accessory.url ? previewImg({ src: b.accessory.url, alt: '', class: 'lv2-thumb' }) : null;
    else acc = lv2Button(b.accessory);
    return el('div', { class: 'lv2-section' }, texts, el('div', { class: 'lv2-accessory' }, acc));
  }
  if (b.type === 'media_gallery') {
    const grid = el('div', { class: 'lv2-gallery' });
    for (const it of b.items) if (it.url) grid.append(previewImg({ src: it.url, alt: it.description || '' }));
    return grid;
  }
  if (b.type === 'separator') return el('div', { class: 'lv2-sep' + (b.visible ? ' visible' : '') });
  if (b.type === 'action_row') return el('div', { class: 'lv2-row' }, b.buttons.map(lv2Button));
  if (b.type === 'file') {
    return el('div', { class: 'lv2-file' + (b.spoiler ? ' lv2-file-spoiler' : '') },
      b.filename || t('embedsLayout.noFilePlaceholder'));
  }
  return el('div', {});
}

export function renderLayoutEditor(box, channels, roles) {
  if (!_layoutDoc) {
    const draft = readEmbedDraft('layout');
    if (draft) {
      setLayoutDoc(draft);
      toast(t('embedsLayout.draftRecovered'), 'ok', {
        label: t('embedsLayout.discard'), onclick: () => { clearEmbedDraft('layout'); setLayoutDoc(blankLayoutDoc()); loadEmbeds(); },
      });
    } else {
      setLayoutDoc(blankLayoutDoc());
    }
  }
  const doc = _layoutDoc;
  if (!doc.sendOpts) doc.sendOpts = blankSendOpts();

  box.append(el('div', { class: 'embed-warn' },
    t('embedsLayout.v2Warning')));

  const previewBox = el('div', {});
  function updatePreview() {
    previewBox.innerHTML = '';
    beginPreviewRender();
    previewBox.append(renderLayoutPreview(doc.blocks.map(blockToApi)));
    endPreviewRender();
    // Los bloques de archivo no persisten (ver auditoría) -- "Programar" no
    // es una opción real mientras haya uno. Si ya estaba en "Programar"
    // cuando aparece el primer bloque de archivo, se vuelve a "Enviar
    // ahora" solo: dejar el radio inhabilitado pero marcado (el navegador lo
    // permite) sería un estado confuso del que no se puede salir clickeando.
    const blockedBySched = hasFileBlock(doc.blocks);
    modeSched.disabled = blockedBySched;
    modeSched.title = blockedBySched ? t('embedsLayout.schedBlockedByFile') : '';
    if (blockedBySched && modeSched.checked) { modeNow.checked = true; syncSched(); }
    scheduleHistorySnapshot();
    scheduleDraftSave();
  }

  const blocksList = el('div', { class: 'layout-list' });
  renderBlocks(blocksList, doc.blocks, false, updatePreview, roles);

  // destino + modo de envío (persistidos en el doc), misma UX que el clásico.
  const chSel = channelSelect(channels, doc.channelId, t('embedsLayout.channelPlaceholder'));
  chSel.onchange = () => { doc.channelId = chSel.value; };
  const modeNow = el('input', { type: 'radio', name: 'lvMode', checked: doc.sendMode === 'now' });
  const modeSched = el('input', { type: 'radio', name: 'lvMode', checked: doc.sendMode === 'sched' });
  const schedType = el('select', {}, el('option', { value: 'interval' }, t('embedsLayout.intervalOption')), el('option', { value: 'daily' }, t('embedsLayout.dailyOption')));
  schedType.value = doc.schedType;
  const intervalInput = el('input', { type: 'number', min: '5', max: '1440', value: doc.interval, style: 'width:110px' });
  const timeInput = el('input', { type: 'time', value: doc.time });
  const schedControls = el('div', { class: 'add-row', style: 'margin-top:8px' }, schedType, intervalInput, timeInput);

  function syncSched() {
    doc.sendMode = modeSched.checked ? 'sched' : 'now';
    doc.schedType = schedType.value;
    schedControls.style.display = modeSched.checked ? '' : 'none';
    const daily = schedType.value === 'daily';
    intervalInput.style.display = daily ? 'none' : '';
    timeInput.style.display = daily ? '' : 'none';
    sendBtn.textContent = modeSched.checked ? t('embedsLayout.scheduleLabel') : t('embedsLayout.sendNowLabel');
  }
  modeNow.onchange = modeSched.onchange = schedType.onchange = syncSched;
  intervalInput.oninput = () => { doc.interval = intervalInput.value; };
  timeInput.oninput = () => { doc.time = timeInput.value; };

  const alertBox = el('div', {});

  const sendBtn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      if (!doc.blocks.length) { showFormAlert(alertBox, t('embedsLayout.needAtLeastOneBlock')); return; }
      if (!chSel.value) { showFormAlert(alertBox, t('embedsLayout.chooseChannel')); return; }
      if (hasEmptyFileBlock(doc.blocks)) { showFormAlert(alertBox, t('embedsLayout.emptyFileBlock')); return; }
      if (modeSched.checked && hasFileBlock(doc.blocks)) { showFormAlert(alertBox, t('embedsLayout.fileBlockCantSchedule')); return; }
      showFormAlert(alertBox, '');
      const layout = { blocks: doc.blocks.map(blockToApi) };
      try {
        const sendOpts = sendOptsToApi(doc.sendOpts);
        if (modeSched.checked) {
          const body = { channel_id: chSel.value, content_mode: 'layout_v2', layout, mode: schedType.value, send_options: sendOpts };
          if (schedType.value === 'interval') body.interval_minutes = parseInt(intervalInput.value, 10);
          else { const [h, m] = timeInput.value.split(':'); body.hour = parseInt(h, 10); body.minute = parseInt(m, 10); }
          await apiFetch(`/api/server/${GUILD_ID}/embeds/schedule`, { method: 'POST', body });
          toast(t('embedsLayout.layoutScheduled'), 'ok');
        } else {
          await apiFetch(`/api/server/${GUILD_ID}/embeds/send`, { method: 'POST', body: { channel_id: chSel.value, content_mode: 'layout_v2', layout, send_options: sendOpts } });
          toast(t('embedsLayout.layoutSent'), 'ok');
          clearEmbedDraft('layout'); // ver criterio (envío inmediato) en el reporte
        }
      } catch (e) { toast(e.message, e.status === 429 ? 'warn' : 'err'); }
    },
  }, t('embedsLayout.sendNowLabel'));

  const saveBtn = el('button', {
    class: 'btn btn-secondary',
    onclick: async () => {
      if (!doc.blocks.length) { showFormAlert(alertBox, t('embedsLayout.needAtLeastOneBlock')); return; }
      if (hasFileBlock(doc.blocks)) { showFormAlert(alertBox, t('embedsLayout.fileBlockCantSaveTemplate')); return; }
      showFormAlert(alertBox, '');
      const layout = { blocks: doc.blocks.map(blockToApi) };
      const name = (prompt(t('embedsLayout.templateNamePrompt'), doc.templateName || '') || '').trim();
      if (!name) return;
      try {
        const body = { name, content_mode: 'layout_v2', layout, send_options: sendOptsToApi(doc.sendOpts) };
        if (doc.templateId) {
          await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${doc.templateId}`, { method: 'PUT', body });
          toast(t('embedsLayout.templateUpdated'), 'ok');
        } else {
          const resp = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`, { method: 'POST', body });
          doc.templateId = resp.id;
          toast(t('embedsLayout.templateSaved'), 'ok');
        }
        doc.templateName = name;
      } catch (e) { toast(e.message, e.status === 409 ? 'warn' : 'err'); }
    },
  }, t('embedsLayout.saveAsTemplate'));

  const clearBtn = el('button', { class: 'btn btn-secondary', onclick: () => { clearEmbedDraft('layout'); setLayoutDoc(blankLayoutDoc()); loadEmbeds(); } }, t('embedsLayout.clear'));
  const histBtn = el('button', { class: 'btn btn-secondary', onclick: openHistoryModal }, t('embedsLayout.history'));
  const jsonBtn = el('button', { class: 'btn btn-secondary', onclick: openJsonModal }, t('embedsLayout.viewEditJson'));

  const form = el('div', { class: 'embed-form' },
    formGroup(t('embedsLayout.blocksSection'),
      el('div', { class: 'field' }, blocksList)),
    formGroup(t('embedsLayout.destinationSection'),
      el('div', { class: 'field' }, el('label', {}, t('embedsLayout.targetChannelLabel')), chSel),
      el('div', { class: 'field' },
        el('label', { class: 'toggle' }, modeNow, t('embedsLayout.sendNowLabel')),
        el('label', { class: 'toggle' }, modeSched, t('embedsLayout.scheduleLabel')),
        schedControls),
      sendOptionsPanel(doc.sendOpts, roles, channels, chSel)),
    alertBox,
    el('div', { class: 'embed-actions' },
      sendBtn, saveBtn, clearBtn,
      el('span', { class: 'embed-actions-spacer' }),
      histBtn, jsonBtn));

  box.append(el('div', { class: 'embed-layout' },
    form,
    el('div', { class: 'd-embed-wrap' }, el('p', { class: 'dim', style: 'margin-top:0' }, t('embedsLayout.previewLabel')), previewBox)));
  box.querySelectorAll('.autogrow').forEach(autoGrow);
  updatePreview();
  syncSched();
}
