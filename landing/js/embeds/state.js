// Lógica pura del editor de embeds/layouts: sin DOM, sin fetch, sin GUILD_ID.
// Todo acá son transformaciones de datos (estado del formulario <-> dict estilo
// API de Discord) y validaciones espejo del backend. Al no depender de
// document/window, es el módulo candidato natural a tests unitarios con el
// runner nativo de Node más adelante.

// Espejo de los límites de validate_embed_payload (webapi.py) para dar
// feedback inmediato sin esperar el 400 del server.
export const EMBED_LIMITS = {
  title: 256, description: 4096, fields: 25, fieldName: 256,
  fieldValue: 1024, footer: 2048, author: 256, total: 6000, count: 10,
};

export const BLOCK_LABELS = {
  text: 'Texto', section: 'Sección', media_gallery: 'Galería',
  separator: 'Separador', action_row: 'Botones', container: 'Container',
};

export const LAYOUT_MAX_COMPONENTS = 40;

// Forma del objeto de contexto que en el futuro va a permitir un editor sin
// guild (envío por webhook, sin plantillas, etc.). Por ahora nada lo consume
// más que con estos defaults: guildId real y todas las caps en true (ver
// nota en la tarea de refactor). No cambia ningún comportamiento todavía.
export function blankEmbedCtx(guildId = null) {
  return {
    guildId,
    caps: {
      channels: true, roles: true, templates: true,
      share: true, sendToChannel: true, sendWebhook: true,
    },
  };
}

export function blankDoc() {
  return { embeds: [blankEmbed()], active: 0, templateId: null, templateName: '',
           channelId: '', sendMode: 'now', schedType: 'interval', interval: '60', time: '09:00',
           sendOpts: blankSendOpts() };
}

export function blankEmbed() {
  return {
    title: '', description: '', color: '#8B6EF5',
    authorName: '', authorIcon: '', footerText: '', footerIcon: '',
    // `url` no tiene campo visible: lo gestiona el atajo de galería, que agrupa
    // embeds consecutivos que comparten el mismo `url` (así los muestra Discord).
    thumbnail: '', image: '', url: '', fields: [],
  };
}

// Estado del formulario -> dict de embed estilo API de Discord (solo lo no vacío).
export function embedDict(s) {
  const e = {};
  if (s.title.trim()) e.title = s.title.trim();
  if (s.description.trim()) e.description = s.description.trim();
  if (s.color) e.color = s.color; // hex "#RRGGBB"; el backend lo convierte a int
  if (s.url && s.url.trim()) e.url = s.url.trim();
  if (s.authorName.trim()) {
    e.author = { name: s.authorName.trim() };
    if (s.authorIcon.trim()) e.author.icon_url = s.authorIcon.trim();
  }
  if (s.footerText.trim()) {
    e.footer = { text: s.footerText.trim() };
    if (s.footerIcon.trim()) e.footer.icon_url = s.footerIcon.trim();
  }
  if (s.thumbnail.trim()) e.thumbnail = { url: s.thumbnail.trim() };
  if (s.image.trim()) e.image = { url: s.image.trim() };
  const fields = s.fields
    .filter(f => f.name.trim() && f.value.trim())
    .map(f => ({ name: f.name.trim(), value: f.value.trim(), inline: !!f.inline }));
  if (fields.length) e.fields = fields;
  return e;
}

// Inverso: dict de embed guardado -> estado del formulario.
export function embedToState(e) {
  const s = blankEmbed();
  s.title = e.title || '';
  s.description = e.description || '';
  if (typeof e.color === 'number') s.color = '#' + e.color.toString(16).padStart(6, '0');
  else if (typeof e.color === 'string') s.color = e.color;
  s.url = e.url || '';
  s.authorName = (e.author && e.author.name) || '';
  s.authorIcon = (e.author && e.author.icon_url) || '';
  s.footerText = (e.footer && e.footer.text) || '';
  s.footerIcon = (e.footer && e.footer.icon_url) || '';
  s.thumbnail = (e.thumbnail && e.thumbnail.url) || '';
  s.image = (e.image && e.image.url) || '';
  s.fields = (e.fields || []).map(f => ({ name: f.name || '', value: f.value || '', inline: !!f.inline }));
  return s;
}

// Doc a partir de un array de embeds guardados (plantilla).
export function docFromEmbeds(embeds, templateId, templateName, sendOptions) {
  const doc = blankDoc();
  doc.embeds = (embeds && embeds.length ? embeds : [{}]).map(embedToState);
  doc.active = 0;
  doc.templateId = templateId || null;
  doc.templateName = templateName || '';
  doc.sendOpts = sendOptsFromApi(sendOptions);
  return doc;
}

// Caracteres que Discord cuenta contra el límite de 6000 por mensaje.
// Espejo de embed_char_count() en webapi.py — mantener en sync.
export function embedChars(e) {
  let total = (e.title || '').length + (e.description || '').length
    + ((e.footer && e.footer.text) || '').length + ((e.author && e.author.name) || '').length;
  for (const f of e.fields || []) total += f.name.length + f.value.length;
  return total;
}

export function validateEmbedClient(e) {
  if ((e.title || '').length > EMBED_LIMITS.title) return `El título supera los ${EMBED_LIMITS.title} caracteres.`;
  if ((e.description || '').length > EMBED_LIMITS.description) return `La descripción supera los ${EMBED_LIMITS.description} caracteres.`;
  const fields = e.fields || [];
  if (fields.length > EMBED_LIMITS.fields) return `Máximo ${EMBED_LIMITS.fields} fields.`;
  for (const f of fields) {
    if (f.name.length > EMBED_LIMITS.fieldName) return `Un field tiene el nombre demasiado largo (máx ${EMBED_LIMITS.fieldName}).`;
    if (f.value.length > EMBED_LIMITS.fieldValue) return `Un field tiene el valor demasiado largo (máx ${EMBED_LIMITS.fieldValue}).`;
  }
  if (((e.footer && e.footer.text) || '').length > EMBED_LIMITS.footer) return `El footer supera los ${EMBED_LIMITS.footer} caracteres.`;
  if (((e.author && e.author.name) || '').length > EMBED_LIMITS.author) return `El autor supera los ${EMBED_LIMITS.author} caracteres.`;
  if (!e.title && !e.description && !fields.length && !e.image && !e.thumbnail && !e.author && !e.footer) {
    return 'El embed está vacío: completa al menos un campo.';
  }
  return null;
}

// Valida el array completo (espejo de validate_embeds_payload en el backend).
// El tope de 6000 aplica a la SUMA de todos los embeds del mensaje (regla real
// de Discord), no por embed.
export function validateEmbedsClient(dicts) {
  if (!dicts.length) return 'Agrega al menos un embed con contenido.';
  if (dicts.length > EMBED_LIMITS.count) return `Máximo ${EMBED_LIMITS.count} embeds por mensaje.`;
  for (let i = 0; i < dicts.length; i++) {
    const err = validateEmbedClient(dicts[i]);
    if (err) return `Embed ${i + 1}: ${err}`;
  }
  const total = dicts.reduce((n, d) => n + embedChars(d), 0);
  if (total > EMBED_LIMITS.total) {
    return `El mensaje supera los ${EMBED_LIMITS.total} caracteres sumando todos los embeds (${total}).`;
  }
  return null;
}

// dicts no vacíos del doc (los tabs sin contenido no se envían ni guardan).
export function docDicts(doc) {
  return doc.embeds.map(embedDict).filter(d => Object.keys(d).length);
}

// Detecta URLs de Tenor/Giphy y devuelve { note, url, warn } o null. Para
// Giphy normaliza a la URL del archivo directo (Discord no embebe la página);
// para una página de Tenor no se puede derivar el archivo de forma fiable en
// el cliente, así que solo se avisa.
export function detectGif(raw) {
  const url = (raw || '').trim();
  let host;
  try { host = new URL(url).hostname.toLowerCase(); } catch (e) { return null; }
  if (host.endsWith('giphy.com')) {
    const m = url.match(/giphy\.com\/(?:gifs|media)\/(?:.*-)?(\w+)/);
    if (m && !host.startsWith('media')) {
      return { note: 'GIF de Giphy detectado — usaremos el archivo optimizado.', url: `https://media.giphy.com/media/${m[1]}/giphy.gif` };
    }
    return null;
  }
  if (host.endsWith('tenor.com')) {
    if (host.startsWith('media') || host.startsWith('c.')) return null; // ya es archivo directo
    return { warn: true, url, note: 'Página de Tenor detectada — para que se vea en el embed pegá el enlace directo del GIF (media.tenor.com/…), no el de la página.' };
  }
  return null;
}

// --- Opciones de envío finas (5.6) ---

export function blankSendOpts() { return { silent: false, restrict: false, roleIds: [] }; }

export function sendOptsToApi(o) {
  if (!o || (!o.silent && !o.restrict)) return undefined; // defaults: no mandar nada
  return { silent: o.silent, restrict_mentions: o.restrict, allowed_role_ids: o.roleIds };
}

export function sendOptsFromApi(so) {
  const o = blankSendOpts();
  if (so) {
    o.silent = !!so.silent;
    o.restrict = !!so.restrict_mentions;
    o.roleIds = (so.allowed_role_ids || []).map(String);
  }
  return o;
}

// --- Layout V2 (Components V2) ---

export function blankLayoutDoc() {
  return { blocks: [], channelId: '', sendMode: 'now', schedType: 'interval',
           interval: '60', time: '09:00', templateId: null, templateName: '',
           sendOpts: blankSendOpts() };
}

export function newBlock(type) {
  if (type === 'text') return { type: 'text', content: '' };
  if (type === 'section') return { type: 'section', texts: [''], accessory: { type: 'thumbnail', url: '', description: '', label: '', style: 'link', role_id: '' } };
  if (type === 'media_gallery') return { type: 'media_gallery', items: [{ url: '', description: '' }] };
  if (type === 'separator') return { type: 'separator', visible: true, spacing: 'small' };
  if (type === 'action_row') return { type: 'action_row', buttons: [{ style: 'link', label: '', url: '', role_id: '' }] };
  return { type: 'container', accent: true, accent_color: '#8B6EF5', children: [] };
}

export function colorToHex(c) {
  if (typeof c === 'number') return '#' + c.toString(16).padStart(6, '0');
  return typeof c === 'string' ? c : null;
}

// Estado de un botón del editor -> dict API. Botones "role" nunca llevan
// custom_id desde el frontend — lo asigna el backend recién al enviar/programar.
export function buttonToApi(bt) {
  if (bt.style === 'role') {
    return { style: 'role', label: bt.label, role_id: bt.role_id ? parseInt(bt.role_id, 10) : null };
  }
  return { style: 'link', label: bt.label, url: bt.url };
}

export function buttonFromApi(bt) {
  return { style: bt.style === 'role' ? 'role' : 'link', label: bt.label || '', url: bt.url || '', role_id: bt.role_id != null ? String(bt.role_id) : '' };
}

// Estado del editor -> dict de bloque estilo API (lo que valida/construye el backend).
export function blockToApi(b) {
  if (b.type === 'container') {
    return { type: 'container', accent_color: b.accent ? b.accent_color : null, children: b.children.map(blockToApi) };
  }
  if (b.type === 'text') return { type: 'text', content: b.content };
  if (b.type === 'section') {
    const acc = b.accessory.type === 'thumbnail'
      ? { type: 'thumbnail', url: b.accessory.url, description: b.accessory.description }
      : { type: 'button', ...buttonToApi(b.accessory) };
    return { type: 'section', texts: b.texts.slice(), accessory: acc };
  }
  if (b.type === 'media_gallery') return { type: 'media_gallery', items: b.items.map(it => ({ url: it.url, description: it.description })) };
  if (b.type === 'separator') return { type: 'separator', visible: b.visible, spacing: b.spacing };
  return { type: 'action_row', buttons: b.buttons.map(buttonToApi) };
}

// Inverso: dict de bloque guardado -> estado del editor.
export function apiToBlock(b) {
  if (b.type === 'container') return { type: 'container', accent: b.accent_color != null, accent_color: colorToHex(b.accent_color) || '#8B6EF5', children: (b.children || []).map(apiToBlock) };
  if (b.type === 'section') {
    const a = b.accessory || {};
    return { type: 'section', texts: (b.texts || ['']).slice(), accessory: { type: a.type === 'button' ? 'button' : 'thumbnail', url: a.url || '', description: a.description || '', ...buttonFromApi(a) } };
  }
  if (b.type === 'media_gallery') return { type: 'media_gallery', items: (b.items || []).map(it => ({ url: it.url || '', description: it.description || '' })) };
  if (b.type === 'separator') return { type: 'separator', visible: b.visible !== false, spacing: b.spacing || 'small' };
  if (b.type === 'action_row') return { type: 'action_row', buttons: (b.buttons || []).map(buttonFromApi) };
  return { type: 'text', content: b.content || '' };
}

export function docFromLayout(layout, templateId, templateName, sendOptions) {
  const doc = blankLayoutDoc();
  doc.blocks = (layout.blocks || []).map(apiToBlock);
  doc.templateId = templateId || null;
  doc.templateName = templateName || '';
  doc.sendOpts = sendOptsFromApi(sendOptions || layout.send_options);
  return doc;
}

// --- Outline de bloques (5.3): resumen, advertencias y conteo de componentes ---

export function firstWords(text, max = 40) {
  const t = (text || '').trim().replace(/\s+/g, ' ');
  return t.length > max ? t.slice(0, max) + '…' : t;
}

// Adelanto corto del contenido de un bloque para su fila colapsada.
export function blockSummary(b) {
  if (b.type === 'text') return firstWords(b.content);
  if (b.type === 'section') return firstWords((b.texts || []).find(t => t.trim()) || '');
  if (b.type === 'media_gallery') {
    const n = b.items.filter(it => it.url.trim()).length;
    return n ? `${n} imagen(es)` : '';
  }
  if (b.type === 'action_row') return b.buttons.map(bt => bt.label.trim()).filter(Boolean).join(', ');
  if (b.type === 'separator') return b.visible ? 'línea visible' : 'solo espacio';
  if (b.type === 'container') return `${b.children.length} bloque(s)`;
  return '';
}

export function btnWarn(bt) {
  if (!bt.label.trim()) return 'Botón sin texto';
  if (bt.style === 'link' && !/^https?:\/\//.test((bt.url || '').trim())) return 'Botón sin URL válida';
  if (bt.style === 'role' && !bt.role_id) return 'Botón sin rol elegido';
  return null;
}

// Problema de validación visible en la fila colapsada, sin expandir el bloque.
export function blockWarning(b) {
  if (b.type === 'text' && !b.content.trim()) return 'Texto vacío';
  if (b.type === 'section') {
    if (!(b.texts || []).some(t => t.trim())) return 'Sección sin texto';
    if (b.accessory.type === 'thumbnail' && !b.accessory.url.trim()) return 'Miniatura sin imagen';
    if (b.accessory.type === 'button') return btnWarn(b.accessory);
  }
  if (b.type === 'media_gallery' && !b.items.some(it => it.url.trim())) return 'Galería sin imágenes';
  if (b.type === 'action_row') {
    if (!b.buttons.length) return 'Fila sin botones';
    for (const bt of b.buttons) { const w = btnWarn(bt); if (w) return w; }
  }
  if (b.type === 'container') {
    if (!b.children.length) return 'Container vacío';
    for (const c of b.children) { const w = blockWarning(c); if (w) return w; }
  }
  return null;
}

// Espejo del conteo de validate_layout_v2_payload (máx 40 componentes).
export function componentCount(blocks) {
  let n = 0;
  for (const b of blocks) {
    n++;
    if (b.type === 'container') n += componentCount(b.children);
    else if (b.type === 'section') n += b.texts.length + 1; // textos + accesorio
    else if (b.type === 'action_row') n += b.buttons.length;
  }
  return n;
}

// Al duplicar, limpiar cualquier identificador único (custom_id de botones)
// para que la copia no colisione con el original. El estado del editor no
// suele llevarlos (se mintean en el backend), pero un doc restaurado de
// historial o pegado por JSON podría traerlos.
export function stripBlockIds(b) {
  delete b.custom_id;
  (b.buttons || []).forEach(bt => delete bt.custom_id);
  if (b.accessory) delete b.accessory.custom_id;
  (b.children || []).forEach(stripBlockIds);
}

// Snippet de texto legible del primer embed no vacío de una plantilla.
export function templateSnippet(embeds) {
  const e = embeds.find(x => x && Object.keys(x).length) || {};
  return e.title || e.description || (e.fields && e.fields[0] && e.fields[0].name) || '(sin texto)';
}

// Snippet del primer bloque con texto de un layout V2 (para "Mis plantillas").
export function layoutSnippet(layout) {
  function text(b) {
    if (b.type === 'text') return (b.content || '').trim();
    if (b.type === 'section') return (b.texts || []).find(t => t && t.trim()) || '';
    if (b.type === 'container') { for (const c of b.children || []) { const s = text(c); if (s) return s; } }
    return '';
  }
  for (const b of (layout && layout.blocks) || []) { const s = text(b); if (s) return s; }
  return '(layout sin texto)';
}
