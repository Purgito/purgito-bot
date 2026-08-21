// Piezas compartidas por los módulos del dashboard: el guild activo, los
// caches de canales/roles y los selectores que arman esas listas.
//
// Conserva el nombre del módulo que existía en el panel viejo porque
// embeds/*.js y tabs/*.js lo importan tal cual — cambiarlo obligaría a tocar
// ~90 KB de editor que acá se reutiliza sin modificar. Lo que sí desapareció
// es todo lo demás que vivía en ese archivo (navegación por categorías,
// sidebar, header del servidor): el navbar y el footer ahora son HTML de la
// landing y las tabs las maneja dash.js.

import { apiFetch } from '/js/core/api.js';
import { el } from '/js/core/dom.js';
import {
  GUILD_ID, channelCache, setChannelCache, roleCache, setRoleCache,
} from '/js/core/config.js';
import { t, addStrings } from '/js/core/i18n.js';

addStrings({
  es: { 'panelShell.channelUnavailable': 'Canal no disponible (ID: {id})' },
  en: { 'panelShell.channelUnavailable': 'Channel not available (ID: {id})' },
});

// Cacheados por la vida de la página (viven en core/config.js para que
// core/markdown.js pueda leerlos sin importar de acá). Acepta { force: true }
// o booleano directo para invalidar y re-consultar al entrar a INICIO o CHAT.
export async function getChannels(opts = {}) {
  const force = typeof opts === 'boolean' ? opts : Boolean(opts && opts.force);
  if (!channelCache || force) {
    try {
      const data = await apiFetch(`/api/server/${GUILD_ID}/channels`);
      setChannelCache((data && Array.isArray(data.channels)) ? data.channels : []);
    } catch (e) {
      if (!channelCache) setChannelCache([]);
      throw e;
    }
  }
  return channelCache || [];
}

export async function getRoles() {
  if (!roleCache) {
    try {
      const data = await apiFetch(`/api/server/${GUILD_ID}/roles`);
      setRoleCache((data && Array.isArray(data.roles)) ? data.roles : []);
    } catch (e) {
      if (!roleCache) setRoleCache([]);
      throw e;
    }
  }
  return roleCache || [];
}

export function channelSelect(channels, selectedId, noneLabel) {
  const sel = el('select', {});
  if (noneLabel !== undefined) sel.append(el('option', { value: '' }, noneLabel));
  let hasSelected = false;
  const list = Array.isArray(channels) ? channels : [];
  for (const ch of list) {
    if (!ch) continue;
    if (String(ch.id) === String(selectedId)) hasSelected = true;
    sel.append(el('option', { value: ch.id }, '#' + (ch.name || ch.id)));
  }
  if (selectedId && !hasSelected) {
    sel.append(el('option', { value: selectedId }, t('panelShell.channelUnavailable', { id: selectedId })));
  }
  sel.value = selectedId || '';
  return sel;
}

export function roleSelect(roles, selectedId, noneLabel) {
  const sel = el('select', {});
  if (noneLabel !== undefined) sel.append(el('option', { value: '' }, noneLabel));
  const list = Array.isArray(roles) ? roles : [];
  for (const r of list) {
    if (!r) continue;
    sel.append(el('option', { value: r.id }, '@' + (r.name || r.id)));
  }
  sel.value = selectedId || '';
  return sel;
}

export function content() {
  const box = document.getElementById('catContent');
  if (box) box.innerHTML = '';
  return box;
}
