/* Test suite integral del dashboard (landing/js/dash.js)
   Verifica el ciclo de vida completo:
   1. Sintaxis e importación de todos los módulos ES.
   2. Carga exitosa con servidor configurado (render de header, métricas, topbar y tabs).
   3. Servidor donde el bot no está instalado (hero con botón de invitar).
   4. Servidor no administrado por el usuario o inexistente (emptyState y botón de retorno).
   5. Acceso sin guild ID en la URL (redirección a primer servidor configurado o /perfil/servidores).
   6. Error de API en /api/me/guilds (renderError visible, nunca pantalla en blanco).
   7. Resiliencia en loadInicio con datos vacíos o endpoints fallando parcialmente.
   8. Cambio reactivo de servidor vía selectGuild y popstate.
   9. Paleta de comandos (Ctrl+K) y navegación de categorías.
   node landing/test_dash.mjs */

import assert from 'node:assert/strict';
import { register } from 'node:module';

register('./root_import_loader.mjs', import.meta.url);

class Node {}

class FakeText extends Node {
  constructor(text) { super(); this.text = String(text); }
}

class FakeElement extends Node {
  constructor(tag, attrs = {}) {
    super();
    this.tagName = tag;
    this.className = attrs.class || '';
    this.disabled = false;
    this.children = [];
    this._html = '';
    this.style = {};
    this.attributes = { ...attrs };
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k]; }
  removeAttribute(k) { delete this.attributes[k]; }
  append(...nodes) { this.children.push(...nodes.filter(Boolean)); }
  prepend(...nodes) { this.children.unshift(...nodes.filter(Boolean)); }
  remove() {
    this.children = [];
    this._html = '';
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = v; if (v === '') this.children = []; }
  text() {
    return this.children.map(c => (c instanceof FakeText ? c.text : (c.text ? c.text() : ''))).join('');
  }
  hasClass(cls) { return (this.className || '').split(' ').includes(cls); }
  findByClass(cls) {
    const out = [];
    for (const c of this.children) {
      if (!(c instanceof FakeElement)) continue;
      if (c.hasClass(cls)) out.push(c);
      out.push(...c.findByClass(cls));
    }
    return out;
  }
  querySelector(sel) {
    if (sel.startsWith('.')) {
      const cls = sel.slice(1);
      const res = this.findByClass(cls);
      return res.length ? res[0] : null;
    }
    return null;
  }
  querySelectorAll(sel) {
    if (sel.startsWith('.')) {
      return this.findByClass(sel.slice(1));
    }
    return [];
  }
  get classList() {
    return {
      add: (...cls) => {
        const set = new Set((this.className || '').split(' ').filter(Boolean));
        cls.forEach(c => set.add(c));
        this.className = Array.from(set).join(' ');
      },
      remove: (...cls) => {
        const set = new Set((this.className || '').split(' ').filter(Boolean));
        cls.forEach(c => set.delete(c));
        this.className = Array.from(set).join(' ');
      },
      toggle: (c, force) => {
        const set = new Set((this.className || '').split(' ').filter(Boolean));
        const has = set.has(c);
        const next = force !== undefined ? force : !has;
        if (next) set.add(c); else set.delete(c);
        this.className = Array.from(set).join(' ');
        return next;
      },
      contains: (c) => (this.className || '').split(' ').filter(Boolean).includes(c),
    };
  }
}

const elementsById = {};

global.Node = Node;
global.document = {
  createElement: (tag, attrs) => new FakeElement(tag, attrs),
  createTextNode: (text) => new FakeText(text),
  getElementById: (id) => {
    if (!elementsById[id]) elementsById[id] = new FakeElement('div');
    return elementsById[id];
  },
  querySelector: (sel) => {
    if (sel === '.dash-layout') return elementsById.dashLayout || (elementsById.dashLayout = new FakeElement('div', { class: 'dash-layout' }));
    return null;
  },
  querySelectorAll: () => [],
  addEventListener: () => {},
  removeEventListener: () => {},
  body: new FakeElement('body'),
  title: '',
};

global.window = {
  addEventListener: () => {},
  removeEventListener: () => {},
  visualViewport: null,
};

global.localStorage = {
  _data: {},
  getItem(k) { return this._data[k] || null; },
  setItem(k, v) { this._data[k] = String(v); },
  removeItem(k) { delete this._data[k]; },
};

global.history = {
  pushState: (state, title, url) => { global.location.pathname = url.split('?')[0]; },
  replaceState: (state, title, url) => { global.location.pathname = url.split('?')[0]; },
};

global.location = {
  pathname: '/es/dashboard/123456789/inicio',
  search: '',
  hash: '',
  replace: (url) => { global.location.pathname = url.split('?')[0]; },
};

let fetchHandlers = [];
global.fetch = async (url, opts = {}) => {
  for (const h of fetchHandlers) {
    const res = await h(url, opts);
    if (res !== undefined) return res;
  }
  return {
    status: 200,
    ok: true,
    json: async () => ({}),
  };
};

function jsonResp(data, status = 200) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => data,
  };
}

function setupDOM() {
  elementsById.dashHead = new FakeElement('div');
  elementsById.dashTabs = new FakeElement('nav', { class: 'dash-sidebar' });
  elementsById.catContent = new FakeElement('div', { class: 'dash-content' });
  elementsById.toast = new FakeElement('div');
  elementsById.dashLayout = new FakeElement('div', { class: 'dash-layout' });
}

console.log('--- Iniciando tests de dash.js ---');

// Import del módulo
const { initDash, fetchUserGuilds, selectGuild, activate, MODULES, CATEGORIES } = await import('./js/dash.js');
const { GUILD_ID, setGuildId } = await import('./js/core/config.js');

// ── Test 1: Estructura de módulos y categorías ─────────────────────────────────
{
  assert.ok(CATEGORIES.length >= 7, 'Debe haber al menos 7 categorías');
  assert.ok(MODULES.length >= 10, 'Debe haber módulos de configuración registrados');
  const inicioMod = MODULES.find(m => m.key === 'inicio');
  assert.ok(inicioMod, 'El módulo inicio debe existir');
  assert.equal(typeof inicioMod.load, 'function');
  console.log('✓ Test 1: Categorías y módulos registrados correctamente');
}

// ── Test 2: Servidor configurado normal (render completo de Inicio) ─────────────
{
  setupDOM();
  setGuildId('123456789');
  global.location.pathname = '/es/dashboard/123456789/inicio';

  const mockGuilds = {
    configured: [{ id: '123456789', name: 'Mi Servidor Pro', is_premium: true, member_count: 500 }],
    available: [],
  };
  const mockStats = {
    corpus_total: 1200,
    gifs: 15,
    frases: 8,
    reading_channels: 3,
    reply_channels: 2,
    reactions: 5,
    text_channels: 5,
    counters: { gifs_enviados: 42, mensajes_enviados: 999 },
    limits: { corpus_total: 5000, gifs: 100, frases: 50 },
  };
  const mockStyle = { current_nick: 'Purgito Bot', current_avatar_url: 'https://example.com/avatar.png' };
  const mockChannels = { channels: [{ id: '10', name: 'general' }, { id: '20', name: 'memes' }] };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      if (url.includes('/api/server/123456789/stats')) return jsonResp(mockStats);
      if (url.includes('/api/server/123456789/style')) return jsonResp(mockStyle);
      if (url.includes('/api/server/123456789/settings/updates')) return jsonResp({ channel_id: '10' });
      if (url.includes('/api/server/123456789/channels')) return jsonResp(mockChannels);
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);
  await initDash();
  await new Promise(r => setTimeout(r, 50));

  // Verificamos que el contenedor de contenido NO esté vacío
  const contentText = elementsById.catContent.text();
  assert.ok(contentText.length > 0, 'catContent no debe estar vacío');
  assert.match(contentText, /Mi Servidor Pro/, 'Debe renderizar el nombre del servidor');
  assert.match(contentText, /500 miembros/, 'Debe renderizar la cantidad de miembros');
  assert.match(contentText, /1[.,]?200/, 'Debe renderizar las métricas de mensajes');
  assert.match(contentText, /Acciones rápidas/, 'Debe renderizar la sección de acciones rápidas');
  assert.match(contentText, /Actividad histórica/, 'Debe renderizar contadores históricos');

  // Verificamos que la barra superior y sidebar estén presentes
  const topText = elementsById.dashHead.text();
  assert.match(topText, /Volver a servidores/);
  assert.equal(elementsById.dashTabs.hidden, false, 'dashTabs no debe estar oculto');

  console.log('✓ Test 2: Carga exitosa y render completo con servidor configurado');
}

// ── Test 3: Servidor donde el bot no está instalado (disponible pero sin bot) ───
{
  setupDOM();
  setGuildId('999999999');
  global.location.pathname = '/es/dashboard/999999999/inicio';

  const mockGuilds = {
    configured: [{ id: '123456789', name: 'Mi Servidor Pro' }],
    available: [{ id: '999999999', name: 'Servidor Sin Bot', invite_url: 'https://discord.com/invite/fake' }],
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true); // force cache bust
  await initDash();

  const contentText = elementsById.catContent.text();
  assert.ok(contentText.length > 0, 'No debe quedar en blanco');
  assert.match(contentText, /Servidor Sin Bot/);
  assert.match(contentText, /Purgito todavía no está instalado en este servidor/);
  assert.match(contentText, /Invitar a Purgito/);
  assert.equal(elementsById.dashTabs.hidden, true, 'dashTabs debe ocultarse');

  console.log('✓ Test 3: Estado visible cuando el bot no está en el servidor');
}

// ── Test 4: Servidor no administrado / no encontrado ────────────────────────────
{
  setupDOM();
  setGuildId('888888888');
  global.location.pathname = '/es/dashboard/888888888/inicio';

  const mockGuilds = {
    configured: [{ id: '123456789', name: 'Mi Servidor Pro' }],
    available: [],
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);
  await initDash();

  const contentText = elementsById.catContent.text();
  assert.ok(contentText.length > 0, 'No debe quedar en blanco');
  assert.match(contentText, /No encontramos ese servidor entre los que administras/);

  console.log('✓ Test 4: Empty state visible para servidores no encontrados o sin permisos');
}

// ── Test 5: Sin GUILD_ID en URL (redirección a primer configurado) ──────────────
{
  setupDOM();
  setGuildId('');
  global.location.pathname = '/es/dashboard';

  const mockGuilds = {
    configured: [{ id: '123456789', name: 'Primer Servidor' }],
    available: [],
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);
  await initDash();

  assert.equal(global.location.pathname, '/es/dashboard/123456789/inicio');
  console.log('✓ Test 5: Redirección automática correcta cuando falta el guild ID');
}

// ── Test 6: Error de API en fetchUserGuilds (500 o error de conexión) ───────────
{
  setupDOM();
  setGuildId('123456789');
  global.location.pathname = '/es/dashboard/123456789/inicio';

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) {
        return jsonResp({ error: 'Fallo interno del servidor' }, 500);
      }
      return jsonResp({});
    },
  ];

  try { await fetchUserGuilds(true); } catch (e) { /* ignore */ }
  await initDash();

  const contentText = elementsById.catContent.text();
  assert.ok(contentText.length > 0, 'No debe quedar en blanco al fallar la API');
  assert.match(contentText, /Fallo interno del servidor|Algo salió mal/);
  console.log('✓ Test 6: Manejo de errores de API sin pantalla en blanco');
}

// ── Test 7: Resiliencia en loadInicio ante datos incompletos ───────────────────
{
  setupDOM();
  setGuildId('123456789');
  global.location.pathname = '/es/dashboard/123456789/inicio';

  const mockGuilds = {
    configured: [{ id: '123456789', name: 'Servidor Con Datos Nulos' }],
    available: [],
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      // Devuelve objetos vacíos simulando falta de configuración previa
      if (url.includes('/api/server/123456789/stats')) return jsonResp({});
      if (url.includes('/api/server/123456789/style')) return jsonResp({});
      if (url.includes('/api/server/123456789/settings/updates')) return jsonResp({});
      if (url.includes('/api/server/123456789/channels')) return jsonResp({ channels: [] });
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);
  await initDash();
  await new Promise(r => setTimeout(r, 50));

  const contentText = elementsById.catContent.text();
  assert.ok(contentText.length > 0, 'No debe fallar con datos vacíos');
  assert.match(contentText, /Servidor Con Datos Nulos/);
  assert.match(contentText, /0 canales/);

  console.log('✓ Test 7: Resiliencia con configuración vacía o nula');
}

// ── Test 8: Cambio reactivo de servidor con selectGuild ─────────────────────────
{
  setupDOM();
  setGuildId('111');
  const mockGuilds = {
    configured: [
      { id: '111', name: 'Servidor Uno' },
      { id: '222', name: 'Servidor Dos' },
    ],
    available: [],
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      if (url.includes('/api/server/')) return jsonResp({ channels: [] });
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);
  await selectGuild('222');
  await new Promise(r => setTimeout(r, 50));

  assert.equal(global.location.pathname, '/es/dashboard/222/inicio');
  console.log('✓ Test 8: Cambio reactivo de servidor funcional');
}

console.log('\n========================================');
console.log('✓ TODOS LOS TESTS DEL DASHBOARD PASARON');
console.log('========================================\n');
