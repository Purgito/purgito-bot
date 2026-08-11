// Persistencia local del editor de embeds/layouts: historial versionado
// (localStorage, hasta 20 versiones), borrador autosave (1 slot por guild+modo)
// y el modal "Ver/editar JSON".

import { GUILD_ID, formatDateTime } from '/js/core/config.js';
import { el, emptyState } from '/js/core/dom.js';
import { apiFetch } from '/js/core/api.js';
import {
  _embedMode, _embedDoc, _layoutDoc, setEmbedDoc, setLayoutDoc,
} from '/js/embeds/session.js';
import { embedDict, docDicts, blockToApi, apiToBlock, embedToState } from '/js/embeds/state.js';
import { renderEmbedsPreview } from '/js/embeds/classic-editor.js';
import { renderLayoutPreview } from '/js/embeds/layout-editor.js';
import { loadEmbeds, panelModal } from '/js/embeds/shared-ui.js';

// --- Historial local (5.4) ---

const HIST_MAX = 20;
let _histTimer = null;

function histKey() { return `purgito_hist_${GUILD_ID}_${_embedMode}`; }

function readHistory() {
  try { return JSON.parse(localStorage.getItem(histKey()) || '[]'); }
  catch (e) { return []; }
}

export function saveHistorySnapshot() {
  const doc = _embedMode === 'layout' ? _layoutDoc : _embedDoc;
  if (!doc) return;
  const list = readHistory();
  const snap = JSON.stringify(doc);
  if (list.length && JSON.stringify(list[0].doc) === snap) return; // sin cambios
  list.unshift({ ts: Date.now(), doc: JSON.parse(snap) });
  try { localStorage.setItem(histKey(), JSON.stringify(list.slice(0, HIST_MAX))); }
  catch (e) { /* quota llena: el historial es red de seguridad, no crítico */ }
}

export function scheduleHistorySnapshot() {
  clearTimeout(_histTimer);
  _histTimer = setTimeout(saveHistorySnapshot, 3000);
}

function historySummary(doc) {
  if (doc.blocks) return `Layout con ${doc.blocks.length} bloque(s)`;
  const n = doc.embeds.map(embedDict).filter(d => Object.keys(d).length).length;
  return `${n} embed(s)`;
}

export function openHistoryModal() {
  saveHistorySnapshot(); // el estado actual también entra, así restaurar es reversible
  const list = readHistory();
  const body = el('div', { class: 'hist-list' });
  if (!list.length) body.append(emptyState('Todavía no hay versiones guardadas — se van a guardar solas a medida que editás.'));
  list.forEach((entry, i) => {
    const previewBox = el('div', { style: 'display:none' });
    let previewLoaded = false;
    const row = el('div', { class: 'hist-entry' },
      el('div', { class: 'hist-entry-head' },
        el('span', {}, formatDateTime(new Date(entry.ts))),
        el('span', { class: 'dim' }, historySummary(entry.doc)),
        el('button', {
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            if (!previewLoaded) {
              previewLoaded = true;
              previewBox.append(entry.doc.blocks
                ? renderLayoutPreview(entry.doc.blocks.map(blockToApi))
                : renderEmbedsPreview(entry.doc.embeds.map(embedDict)));
            }
            previewBox.style.display = previewBox.style.display === 'none' ? '' : 'none';
          },
        }, 'Ver'),
        el('button', {
          class: 'btn btn-primary btn-sm',
          onclick: () => {
            if (entry.doc.blocks) setLayoutDoc(entry.doc); else setEmbedDoc(entry.doc);
            // Deshacer lineal: restaurar descarta las versiones posteriores.
            try { localStorage.setItem(histKey(), JSON.stringify(list.slice(i))); } catch (e) {}
            document.querySelector('.modal-overlay')?.remove();
            loadEmbeds();
          },
        }, 'Restaurar')),
      previewBox);
    body.append(row);
  });
  panelModal('Historial local', body);
}

// --- Borrador automático (autosave del estado en progreso) ---
// Distinto del historial de arriba: acá hay UN solo slot por guild+modo que
// se restaura solo al entrar, sin tope de versiones ni expiración por
// tiempo (localStorage no expira nada por sí solo, así que no hace falta
// lógica de TTL para lograr "indefinido" — solo evitar borrarlo por error).
// Vive hasta que el usuario lo descarta, limpia el editor, o lo consume un
// envío/guardado exitoso (ver saveEmbedDraft/clearEmbedDraft más abajo).
let _draftTimer = null;

function draftKey(mode) { return `purgito_draft_${GUILD_ID}_${mode}`; }

export function saveEmbedDraft() {
  const doc = _embedMode === 'layout' ? _layoutDoc : _embedDoc;
  if (!doc) return;
  try { localStorage.setItem(draftKey(_embedMode), JSON.stringify(doc)); }
  catch (e) { /* quota llena: el borrador es una comodidad, no crítico */ }
}

export function scheduleDraftSave() {
  clearTimeout(_draftTimer);
  _draftTimer = setTimeout(saveEmbedDraft, 3000);
}

export function readEmbedDraft(mode) {
  try {
    const raw = localStorage.getItem(draftKey(mode));
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}

export function clearEmbedDraft(mode) {
  clearTimeout(_draftTimer);
  try { localStorage.removeItem(draftKey(mode)); } catch (e) {}
}

// --- Modo JSON (5.5) ---

export function openJsonModal() {
  const isLayout = _embedMode === 'layout';
  const doc = isLayout ? _layoutDoc : _embedDoc;
  const payload = isLayout
    ? { blocks: doc.blocks.map(blockToApi) }
    : { embeds: docDicts(doc) };
  const ta = el('textarea', { class: 'json-editor', spellcheck: 'false' });
  ta.value = JSON.stringify(payload, null, 2);
  ta.wrap = 'off';
  const errBox = el('p', { class: 'error', style: 'min-height:1.2em;margin:6px 0' }, '');
  const applyBtn = el('button', { class: 'btn btn-primary', disabled: true }, 'Aplicar');
  let parsed = payload;
  let validateTimer = null;

  async function validate() {
    try { parsed = JSON.parse(ta.value); }
    catch (e) { errBox.textContent = 'JSON inválido: ' + e.message; applyBtn.disabled = true; return; }
    const body = isLayout
      ? { content_mode: 'layout_v2', layout: parsed }
      : { content_mode: 'classic_embed', embeds: parsed.embeds };
    try {
      const resp = await apiFetch(`/api/server/${GUILD_ID}/embeds/validate`, { method: 'POST', body });
      errBox.textContent = resp.ok ? '' : resp.error;
      applyBtn.disabled = !resp.ok;
    } catch (e) { errBox.textContent = e.message; applyBtn.disabled = true; }
  }
  ta.oninput = () => { clearTimeout(validateTimer); validateTimer = setTimeout(validate, 400); };

  const wrapChk = el('input', { type: 'checkbox' });
  wrapChk.onchange = () => { ta.wrap = wrapChk.checked ? 'soft' : 'off'; };

  applyBtn.onclick = () => {
    if (isLayout) doc.blocks = (parsed.blocks || []).map(apiToBlock);
    else { doc.embeds = (parsed.embeds && parsed.embeds.length ? parsed.embeds : [{}]).map(embedToState); doc.active = 0; }
    document.querySelector('.modal-overlay')?.remove();
    loadEmbeds();
  };

  // Descarga el contenido ACTUAL del textarea (no el payload original): si
  // el usuario ya lo editó a mano, baja lo que está viendo, no lo de antes.
  const downloadBtn = el('button', {
    class: 'btn btn-secondary',
    onclick: () => {
      const blob = new Blob([ta.value], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = el('a', { href: url, download: `purgito-${isLayout ? 'layout' : 'embed'}.json` });
      document.body.append(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
  }, 'Descargar .json');

  panelModal('Editar como JSON', el('div', {},
    ta, errBox,
    el('div', { class: 'add-row' },
      applyBtn,
      el('button', { class: 'btn btn-secondary', onclick: () => document.querySelector('.modal-overlay')?.remove() }, 'Cancelar'),
      downloadBtn,
      el('label', { class: 'toggle' }, wrapChk, 'Ajuste de línea'))));
  validate();
}
