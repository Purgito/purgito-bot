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

// Cacheados por la vida de la página (viven en core/config.js para que
// core/markdown.js pueda leerlos sin importar de acá).
export async function getChannels() {
  if (!channelCache) setChannelCache((await apiFetch(`/api/server/${GUILD_ID}/channels`)).channels);
  return channelCache;
}

export async function getRoles() {
  if (!roleCache) setRoleCache((await apiFetch(`/api/server/${GUILD_ID}/roles`)).roles);
  return roleCache;
}

export function channelSelect(channels, selectedId, noneLabel) {
  const sel = el('select', {});
  if (noneLabel !== undefined) sel.append(el('option', { value: '' }, noneLabel));
  let hasSelected = false;
  for (const ch of channels) {
    if (String(ch.id) === String(selectedId)) hasSelected = true;
    sel.append(el('option', { value: ch.id }, '#' + (ch.name || ch.id)));
  }
  if (selectedId && !hasSelected) {
    sel.append(el('option', { value: selectedId }, `Canal no disponible (ID: ${selectedId})`));
  }
  sel.value = selectedId || '';
  return sel;
}

export function roleSelect(roles, selectedId, noneLabel) {
  const sel = el('select', {});
  sel.append(el('option', { value: '' }, noneLabel));
  for (const r of roles) sel.append(el('option', { value: r.id }, '@' + r.name));
  sel.value = selectedId || '';
  return sel;
}

export function content() {
  const box = document.getElementById('catContent');
  box.innerHTML = '';
  return box;
}
