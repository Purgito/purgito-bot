/* Test de la tab HISTORIAL (landing/js/tabs/historial.js) con fetch y un DOM
   mínimo mockeados -- no hay jsdom en el repo, así que se stubea nada más lo
   que core/dom.js (el/emptyState/spinner/toast) y panel-shell.js (content)
   tocan de verdad.
   node landing/test_historial.mjs */
import assert from 'node:assert/strict';
import { register } from 'node:module';

// historial.js importa con paths root-relative ("/js/core/api.js", como los
// sirve nginx en el navegador); este hook los reescribe al árbol real bajo
// landing/ para poder importarlo desde Node. Ver root_import_loader.mjs.
register('./root_import_loader.mjs', import.meta.url);

class Node {}

class FakeText extends Node {
  constructor(text) { super(); this.text = String(text); }
}

class FakeElement extends Node {
  constructor(tag) {
    super();
    this.tagName = tag;
    this.className = '';
    this.disabled = false;
    this.children = [];
    this._html = '';
  }
  setAttribute() {}
  append(...nodes) { this.children.push(...nodes); }
  remove() {}
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = v; if (v === '') this.children = []; }
  text() {
    return this.children.map(c => (c instanceof FakeText ? c.text : c.text())).join('');
  }
  hasClass(cls) { return this.className.split(' ').includes(cls); }
  findByClass(cls) {
    const out = [];
    for (const c of this.children) {
      if (!(c instanceof FakeElement)) continue;
      if (c.hasClass(cls)) out.push(c);
      out.push(...c.findByClass(cls));
    }
    return out;
  }
}

const elementsById = {};

global.Node = Node;
global.document = {
  createElement: (tag) => new FakeElement(tag),
  createTextNode: (text) => new FakeText(text),
  getElementById: (id) => elementsById[id],
};
// GUILD_ID sale de location.pathname al importar core/config.js (ver ese
// archivo): tiene que existir antes del import dinámico de historial.js.
global.location = { pathname: '/es/dashboard/123456789/historial' };

let fetchImpl;
global.fetch = (...args) => fetchImpl(...args);

function jsonResponse(body, status = 200) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

function freshBox() {
  elementsById.catContent = new FakeElement('div');
  elementsById.toast = new FakeElement('div');
  return elementsById.catContent;
}

const { loadHistorial } = await import('./js/tabs/historial.js');

// ── Lista con entradas: traduce el action y muestra usuario + detail ────────
{
  const box = freshBox();
  const urls = [];
  fetchImpl = async (url) => {
    urls.push(url);
    return jsonResponse({
      entries: [
        {
          id: 2, user_id: 1, user_name: 'Ana', action: 'gifs.add',
          detail: 'https://tenor.com/view/x', created_at: '2026-08-05 12:00:00',
        },
        {
          id: 1, user_id: 1, user_name: 'Ana', action: 'youtube.update_mention_role',
          detail: null, created_at: '2026-08-05 11:00:00',
        },
      ],
    });
  };

  await loadHistorial();

  assert.equal(urls.length, 1);
  assert.match(urls[0], /^\/api\/guilds\/123456789\/audit\?limit=50&offset=0$/);
  const text = box.text();
  assert.match(text, /Ana/);
  assert.match(text, /Agregó un GIF/);
  assert.match(text, /https:\/\/tenor\.com\/view\/x/);
  assert.match(text, /Cambió el rol de mención de YouTube/);
  // Sin botón "Cargar más": menos de 50 entradas en la primera página.
  assert.equal(box.findByClass('btn-secondary').length, 0);
}

// ── Action sin traducción conocida: se muestra tal cual, no se rompe ────────
{
  const box = freshBox();
  fetchImpl = async () => jsonResponse({
    entries: [{
      id: 1, user_id: 1, user_name: 'Ana', action: 'algo.nuevo.sin_mapear',
      detail: null, created_at: '2026-08-05 12:00:00',
    }],
  });

  await loadHistorial();

  assert.match(box.text(), /algo\.nuevo\.sin_mapear/);
}

// ── Sin entradas: emptyState con el texto pedido ────────────────────────────
{
  const box = freshBox();
  fetchImpl = async () => jsonResponse({ entries: [] });

  await loadHistorial();

  assert.equal(box.findByClass('empty-state').length, 1);
  assert.match(box.text(), /Todavía no hay cambios registrados en este servidor\./);
}

// ── Página llena (50): aparece "Cargar más" y trae la página siguiente ──────
{
  const box = freshBox();
  const page1 = Array.from({ length: 50 }, (_, i) => ({
    id: 50 - i, user_id: 1, user_name: 'Ana', action: 'corpus.add',
    detail: `channel_id=${i}`, created_at: '2026-08-05 12:00:00',
  }));
  const page2 = [{
    id: 999, user_id: 1, user_name: 'Ana', action: 'corpus.remove',
    detail: 'channel_id=999', created_at: '2026-08-05 13:00:00',
  }];
  const urls = [];
  fetchImpl = async (url) => {
    urls.push(url);
    return jsonResponse({ entries: url.includes('offset=0') ? page1 : page2 });
  };

  await loadHistorial();
  const [moreBtn] = box.findByClass('btn-secondary');
  assert.ok(moreBtn, 'debería mostrar "Cargar más" con una página llena');

  await moreBtn.onclick();

  assert.equal(urls[1], '/api/guilds/123456789/audit?limit=50&offset=50');
  assert.match(box.text(), /channel_id=999/);
}

// ── Error de red: usa renderError, no revienta ──────────────────────────────
{
  const box = freshBox();
  fetchImpl = async () => { throw new TypeError('fetch failed'); };

  await loadHistorial();

  assert.match(box.text(), /No se pudo conectar con el servidor/);
}

console.log('ok');
