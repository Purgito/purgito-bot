// Markdown estilo Discord + menciones para el Preview de embeds/layouts.
// Puramente visual: el JSON guardado/enviado nunca pasa por acá (docDicts,
// blockToApi, etc. siguen usando el texto crudo). roleCache/channelCache es el
// mismo cache que ya alimenta el picker de menciones (5.1), leído desde
// core/config.js.

import { el, embedImg } from '/js/core/dom.js';
import { roleCache, channelCache } from '/js/core/config.js';

// <@&id> -> @Rol (con su color real si tiene uno asignado), <#id> -> #canal,
// <@id>/<@!id> -> @usuario genérico (no hay endpoint de miembros en el panel).
// Si el rol/canal ya no existe, se muestra un placeholder mudo en vez de romper.
export function resolveMentionNode(kind, id) {
  if (kind === 'role') {
    const r = (roleCache || []).find(x => x.id === id);
    if (!r) return el('span', { class: 'd-embed-mention d-embed-mention-unknown' }, '@rol-eliminado');
    const span = el('span', { class: 'd-embed-mention' }, '@' + r.name);
    if (r.color && r.color !== '#000000') {
      span.style.color = r.color;
      span.style.background = `color-mix(in srgb, ${r.color} 30%, transparent)`;
    }
    return span;
  }
  if (kind === 'channel') {
    const c = (channelCache || []).find(x => x.id === id);
    if (!c) return el('span', { class: 'd-embed-mention d-embed-mention-unknown' }, '#canal-eliminado');
    return el('span', { class: 'd-embed-mention' }, '#' + c.name);
  }
  return el('span', { class: 'd-embed-mention' }, '@usuario');
}

// Emoji custom <:nombre:id> / animado <a:nombre:id>: el ID ya trae todo lo
// necesario para construir la URL del CDN de Discord sin pedirle nada al
// backend. Si la imagen no carga (emoji borrado, CDN caído), se cae a
// :nombre: en vez de dejar un ícono roto.
export function customEmojiNode(name, id, animated) {
  const fallback = ':' + name + ':';
  const img = el('img', {
    src: `https://cdn.discordapp.com/emojis/${id}.${animated ? 'gif' : 'png'}?size=24&quality=lossless`,
    alt: fallback, class: 'd-embed-emoji',
  });
  img.onerror = () => { img.replaceWith(document.createTextNode(fallback)); };
  return img;
}

// Formato de <t:unix:estilo>, compartido con el picker de fecha (5.1) para
// no duplicar la lógica de Intl.DateTimeFormat/RelativeTimeFormat.
export function discordTimestampText(date, style) {
  const s = style || 'f';
  if (s === 'R') {
    const sec = Math.round((date - Date.now()) / 1000);
    const rtf = new Intl.RelativeTimeFormat('es');
    const abs = Math.abs(sec);
    if (abs < 60) return rtf.format(sec, 'second');
    if (abs < 3600) return rtf.format(Math.round(sec / 60), 'minute');
    if (abs < 86400) return rtf.format(Math.round(sec / 3600), 'hour');
    return rtf.format(Math.round(sec / 86400), 'day');
  }
  const opts = {
    t: { timeStyle: 'short' }, T: { timeStyle: 'medium' },
    d: { dateStyle: 'short' }, D: { dateStyle: 'long' },
    f: { dateStyle: 'long', timeStyle: 'short' }, F: { dateStyle: 'full', timeStyle: 'short' },
  }[s] || { dateStyle: 'long', timeStyle: 'short' };
  return new Intl.DateTimeFormat('es', opts).format(date);
}

// Solo esquemas seguros son clickeables; una URL rara (p.ej. "javascript:")
// se muestra igual con el estilo de link pero sin href, para no correr JS
// arbitrario desde una plantilla pegada/importada.
export function mdLinkNode(text, url) {
  const attrs = { class: 'd-embed-link', title: url };
  if (/^(https?:|mailto:)/i.test(url)) {
    attrs.href = url; attrs.target = '_blank'; attrs.rel = 'noopener noreferrer';
  }
  return el('a', attrs, ...parseInline(text));
}

// Formato inline completo: escape, código, links enmascarados, spoiler,
// negrita+cursiva, negrita, subrayado, tachado, cursiva (* o _), las tres
// menciones, emoji custom y timestamps. Grupos con nombre en vez de índices
// numéricos: agregar una alternativa no corre el riesgo de desalinear el
// resto. El orden de la alternancia importa (más específico primero: ***
// antes que **, ** antes que *) para que la regex no confunda negrita con
// cursiva.
const MD_INLINE_RE = new RegExp([
  String.raw`\\(?<esc>[\s\S])`,
  String.raw`\x60(?<code>[^\x60\n]+?)\x60`,
  String.raw`\[(?<linktext>[^\[\]]+)\]\((?<linkurl>(?:[^()\s]|\([^()\s]*\))+)\)`,
  String.raw`\|\|(?<spoiler>[\s\S]+?)\|\|`,
  String.raw`\*\*\*(?<bi>[\s\S]+?)\*\*\*`,
  String.raw`\*\*(?<bold>[\s\S]+?)\*\*`,
  String.raw`__(?<under>[\s\S]+?)__`,
  String.raw`~~(?<strike>[\s\S]+?)~~`,
  String.raw`\*(?<italic1>[^*\n]+?)\*`,
  String.raw`_(?<italic2>[^_\n]+?)_`,
  String.raw`<@&(?<role>\d+)>`,
  String.raw`<#(?<channel>\d+)>`,
  String.raw`<@!?(?<user>\d+)>`,
  String.raw`<(?<emojia>a)?:(?<emojiname>[a-zA-Z0-9_]{2,32}):(?<emojiid>\d+)>`,
  String.raw`<t:(?<ts>-?\d+)(?::(?<tstyle>[tTdDfFR]))?>`,
].join('|'), 'g');

export function parseInline(text) {
  const nodes = [];
  const re = new RegExp(MD_INLINE_RE);
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) nodes.push(document.createTextNode(text.slice(last, m.index)));
    const g = m.groups;
    if (g.esc !== undefined) nodes.push(document.createTextNode(g.esc));
    else if (g.code !== undefined) nodes.push(el('code', { class: 'd-embed-code' }, g.code));
    else if (g.linktext !== undefined) nodes.push(mdLinkNode(g.linktext, g.linkurl));
    else if (g.spoiler !== undefined) nodes.push(el('span', { class: 'd-embed-spoiler' }, ...parseInline(g.spoiler)));
    else if (g.bi !== undefined) nodes.push(el('strong', {}, el('em', {}, ...parseInline(g.bi))));
    else if (g.bold !== undefined) nodes.push(el('strong', {}, ...parseInline(g.bold)));
    else if (g.under !== undefined) nodes.push(el('u', {}, ...parseInline(g.under)));
    else if (g.strike !== undefined) nodes.push(el('s', {}, ...parseInline(g.strike)));
    else if (g.italic1 !== undefined) nodes.push(el('em', {}, ...parseInline(g.italic1)));
    else if (g.italic2 !== undefined) nodes.push(el('em', {}, ...parseInline(g.italic2)));
    else if (g.role !== undefined) nodes.push(resolveMentionNode('role', g.role));
    else if (g.channel !== undefined) nodes.push(resolveMentionNode('channel', g.channel));
    else if (g.user !== undefined) nodes.push(resolveMentionNode('user', g.user));
    else if (g.emojiid !== undefined) nodes.push(customEmojiNode(g.emojiname, g.emojiid, !!g.emojia));
    else if (g.ts !== undefined) {
      const date = new Date(parseInt(g.ts, 10) * 1000);
      nodes.push(el('span', { class: 'd-embed-timestamp' }, discordTimestampText(date, g.tstyle)));
    }
    last = re.lastIndex;
    if (re.lastIndex === m.index) re.lastIndex++; // salvaguarda anti bucle infinito
  }
  if (last < text.length) nodes.push(document.createTextNode(text.slice(last)));
  return nodes;
}

// Reconoce si una línea abre un bloque especial (cita, subtexto, encabezado,
// lista) — usado para saber cuándo cortar la acumulación de un párrafo llano.
export function isBlockLine(line) {
  return /^>\s?/.test(line) || /^-#\s?/.test(line) || /^#{1,3}\s+/.test(line) ||
         /^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line);
}

// Lista (no ordenada u ordenada) con sangría visual: Discord no dibuja
// bullets/viñetas distintas por nivel, solo corre la línea entera hacia la
// derecha, así que la sangría se resuelve con margin-left por ítem en vez de
// listas anidadas de verdad.
export function buildList(items, ordered) {
  const attrs = { class: 'd-embed-list' };
  if (ordered) attrs.start = String(items[0].num);
  const list = el(ordered ? 'ol' : 'ul', attrs);
  const base = items[0].indent;
  for (const it of items) {
    const level = Math.max(0, Math.round((it.indent - base) / 2));
    const li = el('li', {}, ...parseInline(it.content));
    if (level > 0) li.style.marginLeft = (level * 18) + 'px';
    list.append(li);
  }
  return list;
}

// Bloques: cita de una o más líneas ("> "), cita de bloque completo hasta el
// final del tramo (">>> "), subtexto ("-# "), encabezados (#/##/###) y
// listas (-/* , 1.) con su sangría; el resto pasa por el formato inline. Los
// saltos de línea sobrantes los resuelve el white-space:pre-wrap ya usado en
// .d-embed-desc/.lv2-text.
export function mdBlocksFromText(chunk) {
  if (!chunk) return [];
  const lines = chunk.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // ">>> " citas todo lo que sigue hasta el final del tramo, no solo esa línea.
    const tripleM = /^>>>\s?/.exec(line);
    if (tripleM) {
      const rest = [line.slice(tripleM[0].length), ...lines.slice(i + 1)].join('\n');
      out.push(el('div', { class: 'd-embed-quote' }, ...parseInline(rest)));
      i = lines.length;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote = el('div', { class: 'd-embed-quote' });
      let first = true;
      while (i < lines.length && /^>\s?/.test(lines[i]) && !/^>>>\s?/.test(lines[i])) {
        if (!first) quote.append(document.createTextNode('\n'));
        quote.append(...parseInline(lines[i].replace(/^>\s?/, '')));
        first = false;
        i++;
      }
      out.push(quote);
      continue;
    }

    if (/^-#\s?/.test(line)) {
      const sub = el('div', { class: 'd-embed-subtext' });
      let first = true;
      while (i < lines.length && /^-#\s?/.test(lines[i])) {
        if (!first) sub.append(document.createTextNode('\n'));
        sub.append(...parseInline(lines[i].replace(/^-#\s?/, '')));
        first = false;
        i++;
      }
      out.push(sub);
      continue;
    }

    const headM = /^(#{1,3})\s+(.*)$/.exec(line);
    if (headM) {
      out.push(el('div', { class: 'd-embed-h d-embed-h' + headM[1].length }, ...parseInline(headM[2])));
      i++;
      continue;
    }

    const ulFirst = /^(\s*)[-*]\s+(.*)$/.exec(line);
    if (ulFirst) {
      const items = [];
      while (i < lines.length) {
        const mm = /^(\s*)[-*]\s+(.*)$/.exec(lines[i]);
        if (!mm) break;
        items.push({ indent: mm[1].length, content: mm[2] });
        i++;
      }
      out.push(buildList(items, false));
      continue;
    }

    const olFirst = /^(\s*)(\d+)\.\s+(.*)$/.exec(line);
    if (olFirst) {
      const items = [];
      while (i < lines.length) {
        const mm = /^(\s*)(\d+)\.\s+(.*)$/.exec(lines[i]);
        if (!mm) break;
        items.push({ indent: mm[1].length, num: parseInt(mm[2], 10), content: mm[3] });
        i++;
      }
      out.push(buildList(items, true));
      continue;
    }

    const plain = [];
    while (i < lines.length && !isBlockLine(lines[i])) { plain.push(lines[i]); i++; }
    out.push(...parseInline(plain.join('\n')));
  }
  return out;
}

// Bloques de código ``` ``` primero (protegidos del resto del parseo), y
// dentro de cada tramo restante, citas + formato inline.
export function mdToNodes(raw) {
  const text = raw || '';
  const fenceRe = /```(?:[a-zA-Z0-9_+-]*\n)?([\s\S]*?)```/g;
  const nodes = [];
  let last = 0, m;
  while ((m = fenceRe.exec(text))) {
    if (m.index > last) nodes.push(...mdBlocksFromText(text.slice(last, m.index)));
    let code = m[1];
    if (code.endsWith('\n')) code = code.slice(0, -1);
    nodes.push(el('div', { class: 'd-embed-codeblock' }, code));
    last = fenceRe.lastIndex;
  }
  if (last < text.length) nodes.push(...mdBlocksFromText(text.slice(last)));
  return nodes;
}

// Preview en vivo: reusar el mismo <img> entre re-renders evita que la imagen
// se vuelva a decodificar (y parpadee) en cada tecla. El Set de "reclamados"
// se reinicia por render, así dos embeds con la misma URL igual reciben nodos
// distintos (no se roban el nodo cacheado).
const _previewImgCache = new Map();
let _previewImgClaimed = null;
export function beginPreviewRender() { _previewImgClaimed = new Set(); }
export function endPreviewRender() { _previewImgClaimed = null; }
export function previewImg(attrs) {
  const src = attrs.src || '';
  if (_previewImgClaimed && src && !_previewImgClaimed.has(src) && _previewImgCache.has(src)) {
    const img = _previewImgCache.get(src);
    _previewImgClaimed.add(src);
    if (attrs.class) img.className = attrs.class;
    img.style.display = '';
    return img;
  }
  const img = embedImg(attrs);
  if (_previewImgClaimed && src) { _previewImgClaimed.add(src); _previewImgCache.set(src, img); }
  return img;
}
