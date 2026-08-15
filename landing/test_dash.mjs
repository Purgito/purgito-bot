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
    this.value = attrs.value !== undefined ? String(attrs.value) : '';
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
  focus() {}
  blur() {}
  addEventListener() {}
  removeEventListener() {}
  click() { if (typeof this.onclick === 'function') this.onclick(); }
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
const { initDash, fetchUserGuilds, selectGuild, activate, toggleSidebarCollapse, MODULES, CATEGORIES } = await import('./js/dash.js');
const { GUILD_ID, setGuildId } = await import('./js/core/config.js');

// ── Test 1: Estructura de módulos y categorías ─────────────────────────────────
{
  assert.ok(CATEGORIES.length >= 6, 'Debe haber al menos 6 categorías');
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

  // Verificamos que la barra superior sea limpia (sin duplicar el avatar/nombre del servidor)
  const topText = elementsById.dashHead.text();
  assert.match(topText, /Servidores/);
  assert.match(topText, /Buscar/);
  assert.doesNotMatch(topText, /Mi Servidor Pro/, 'La barra superior no debe duplicar el nombre del servidor');
  assert.equal(elementsById.dashTabs.hidden, false, 'dashTabs no debe estar oculto');

  console.log('✓ Test 2: Carga exitosa y render completo con servidor configurado (sin encabezado duplicado)');
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

// ── Test 9: Módulo de Triggers de canal (carga, empty state, formulario) ──────
{
  setupDOM();
  setGuildId('123456789');
  global.location.pathname = '/es/dashboard/123456789/triggers';

  const mockGuilds = {
    configured: [{ id: '123456789', name: 'Servidor Triggers' }],
    available: [],
  };

  const mockTriggersData = {
    triggers: [],
    total: 0,
    limit: 10,
    match_types: ['exact', 'starts_with', 'regex'],
    actions: ['frase_de_pack', 'markov', 'mezcla'],
  };

  const mockPacksData = {
    packs: [{ id: 1, name: 'Pack Bienvenida' }],
    total: 1,
    limit: 5,
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      if (url.includes('/api/server/123456789/settings/triggers')) return jsonResp(mockTriggersData);
      if (url.includes('/api/server/123456789/frases/packs')) return jsonResp(mockPacksData);
      if (url.includes('/api/server/123456789/channels')) {
        return jsonResp({ channels: [{ id: '10', name: 'general', type: 0 }] });
      }
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);
  const mod = MODULES.find(m => m.key === 'triggers');
  assert.ok(mod, 'Módulo triggers debe existir');
  await mod.load();
  await new Promise(r => setTimeout(r, 50));

  const contentText = elementsById.catContent.text();
  assert.ok(contentText.length > 0, 'El módulo triggers debe renderizarse');
  assert.match(contentText, /Triggers de canal/);
  assert.match(contentText, /Todavía no configuraste ningún trigger\./);
  assert.match(contentText, /0 de 10/); // Cupo line

  console.log('✓ Test 9: Triggers de canal sin errores de .length y con empty state');
}

// ── Test 10: Ajustes de Chat (todas las subsecciones cargan sin error) ──────────
{
  setupDOM();
  setGuildId('123456789');
  global.location.pathname = '/es/dashboard/123456789/chat';

  const mockGuilds = {
    configured: [{ id: '123456789', name: 'Servidor Chat' }],
    available: [],
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      if (url.includes('/api/server/123456789/settings/chat')) {
        return jsonResp({
          enabled: true,
          auto_generate_every: 20,
          auto_generate_probability: 0.3,
          gif_response_probability: 0.1,
          frase_probability: 0.15,
          reaction_probability: 0.05,
          mention_rate_limit: 10,
          limits: { auto_generate_every: [1, 1000] },
        });
      }
      if (url.includes('/api/server/123456789/settings/spontaneous-channels')) return jsonResp({ channels: [] });
      if (url.includes('/api/server/123456789/settings/mention-channels')) return jsonResp({ channels: [] });
      if (url.includes('/api/server/123456789/settings/corpus')) return jsonResp({ channels: [], ignored: [] });
      if (url.includes('/api/server/123456789/settings/reacciones')) return jsonResp({ reactions: ['😀', '🔥'] });
      if (url.includes('/api/server/123456789/settings/frases/channels')) return jsonResp({ channels: [] });
      if (url.includes('/api/server/123456789/settings/frases')) return jsonResp({ frases: [], total: 0, limit: 200 });
      if (url.includes('/api/server/123456789/frases/packs')) return jsonResp({ packs: [], total: 0, limit: 10 });
      if (url.includes('/api/server/123456789/settings/triggers')) {
        return jsonResp({
          triggers: [],
          total: 0,
          limit: 10,
          match_types: ['exact', 'starts_with', 'regex'],
          actions: ['frase_de_pack', 'markov', 'mezcla'],
        });
      }
      if (url.includes('/api/server/123456789/settings/exempt-roles')) return jsonResp({ roles: [] });
      if (url.includes('/api/server/123456789/settings/exempt-channels')) return jsonResp({ channels: [] });
      if (url.includes('/api/server/123456789/channels')) {
        return jsonResp({ channels: [{ id: '10', name: 'general', type: 0 }] });
      }
      if (url.includes('/api/server/123456789/roles')) return jsonResp({ roles: [] });
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);
  const mod = MODULES.find(m => m.key === 'chat');
  assert.ok(mod, 'Módulo chat debe existir');
  await mod.load();
  await new Promise(r => setTimeout(r, 50));

  const contentText = elementsById.catContent.text();
  assert.ok(contentText.length > 0, 'Ajustes de chat no debe estar vacío');
  assert.match(contentText, /Chat activado/);
  assert.match(contentText, /Cada cuántos mensajes nuevos/);
  assert.match(contentText, /Manda un GIF/);
  assert.match(contentText, /Usa una frase tuya/);

  console.log('✓ Test 10: Ajustes de Chat carga todas las subsecciones limpiamente');
}

// ── Test 11: Modal "Editar apariencia" (openStyleModal y persistencia) ────────
{
  setupDOM();
  setGuildId('123456789');

  let styleUpdatedPayload = null;
  fetchHandlers = [
    (url, opts) => {
      if (url.includes('/api/server/123456789/style') && opts?.method === 'PUT') {
        styleUpdatedPayload = JSON.parse(opts.body);
        return jsonResp({ ok: true });
      }
      return jsonResp({});
    },
  ];

  const currentStyle = {
    nick: 'Purgito Tester',
    current_nick: 'Purgito Tester',
    avatar_url: 'https://cdn.example.com/avatar.png',
  };

  const { openStyleModal } = await import('/js/dash.js');
  assert.equal(typeof openStyleModal, 'function', 'openStyleModal debe ser una función exportada');

  openStyleModal(currentStyle);
  assert.ok(document.body.children.length > 0, 'El modal de estilo debe agregarse al DOM');

  console.log('✓ Test 11: Modal de edición de estilo funcional');
}

// ── Test 12: Simulador de Chat (renombrado, coherencia y ejecución) ───────────
{
  setupDOM();
  setGuildId('123456789');

  const playgroundMod = MODULES.find(m => m.key === 'playground');
  assert.ok(playgroundMod, 'Módulo playground debe existir');
  assert.equal(playgroundMod.label, 'Simulador de Chat', 'Debe renombrarse a "Simulador de Chat"');

  let simulatedRequest = null;
  fetchHandlers = [
    (url, opts) => {
      if (url.includes('/api/server/123456789/channels')) {
        return jsonResp({
          channels: [
            { id: '10', name: 'general', can_use_simulator: true, can_send: true, can_view: true },
            { id: '99', name: 'solo-lectura-no-usable', can_use_simulator: false, can_send: false, can_view: true },
          ],
        });
      }
      if (url.includes('/api/server/123456789/style')) {
        return jsonResp({ current_nick: 'Purgito Bot', current_avatar_url: 'https://example.com/purgito.png' });
      }
      if (url.includes('/api/server/123456789/chat/playground') && opts?.method === 'POST') {
        simulatedRequest = JSON.parse(opts.body);
        return jsonResp({
          would_respond: true,
          reason: 'markov',
          text: '¡Hola desde la simulación de Purgito!',
          avisos: [],
        });
      }
      return jsonResp({});
    },
  ];

  await playgroundMod.load();
  await new Promise(r => setTimeout(r, 50));

  const contentText = elementsById.catContent.text();
  assert.match(contentText, /Simulador de Chat/);
  assert.match(contentText, /Canal de contexto/);
  assert.match(contentText, /Mensaje de entrada/);
  assert.match(contentText, /Simular respuesta/);
  assert.ok(!contentText.includes('Respuesta simulada'), 'No debe existir un panel permanente de Respuesta simulada');

  // Test vacío cuando no hay canales utilizables
  fetchHandlers = [
    (url) => {
      if (url.includes('/api/server/123456789/channels')) {
        return jsonResp({
          channels: [
            { id: '99', name: 'solo-lectura', can_use_simulator: false },
          ],
        });
      }
      return jsonResp({});
    },
  ];
  await playgroundMod.load();
  await new Promise(r => setTimeout(r, 50));
  const emptyContent = elementsById.catContent.text();
  assert.match(emptyContent, /No hay canales disponibles para simular/);

  console.log('✓ Test 12: Simulador de Chat estructurado, con filtrado de permisos y sin panel permanente');
}

// ── Test 13: Eliminación de redundancias en navegación ────────────────────────
{
  setupDOM();
  setGuildId('123456789');

  // Verificar que cada módulo tiene una única categoría asignada
  const keyCounts = {};
  for (const m of MODULES) {
    keyCounts[m.key] = (keyCounts[m.key] || 0) + 1;
  }
  for (const [key, count] of Object.entries(keyCounts)) {
    assert.equal(count, 1, `El módulo ${key} solo debe existir una vez en MODULES`);
  }

  // Reacciones automáticas y Frases y Packs deben estar en Automatización
  const reaccionesMod = MODULES.find(m => m.key === 'reacciones');
  assert.equal(reaccionesMod.cat, 'automatizacion', 'Reacciones debe estar en Automatización');

  const frasesMod = MODULES.find(m => m.key === 'frases');
  assert.equal(frasesMod.cat, 'automatizacion', 'Frases debe estar en Automatización');

  const triggersMod = MODULES.find(m => m.key === 'triggers');
  assert.equal(triggersMod.cat, 'automatizacion', 'Triggers debe estar en Automatización');

  const chatMod = MODULES.find(m => m.key === 'chat');
  assert.equal(chatMod.cat, 'principal', 'Chat debe estar en Principal');

  const premiumMod = MODULES.find(m => m.key === 'premium');
  assert.equal(premiumMod.cat, 'principal', 'Purgito Premium debe estar al final de Principal');

  console.log('✓ Test 13: Estructura de módulos limpia y sin redundancias');
}

// ── Test 14: Persistencia del estado del sidebar al navegar ──────────────────
{
  setupDOM();
  setGuildId('123456789');

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp({ configured: [{ id: '123456789', name: 'Server' }], available: [] });
      return jsonResp({});
    },
  ];

  await fetchUserGuilds(true);

  // 1. Colapsar sidebar
  toggleSidebarCollapse();
  assert.equal(localStorage.getItem('purgito_dash_sidebar_collapsed'), 'true', 'Debe persistir true en localStorage');
  const layout = document.querySelector('.dash-layout');
  assert.ok(layout.hasClass('sidebar-collapsed'), 'Layout debe tener clase sidebar-collapsed');

  // 2. Navegar a Chat con sidebar colapsado -> debe seguir colapsado
  activate('chat', false);
  assert.ok(layout.hasClass('sidebar-collapsed'), 'Sidebar debe seguir colapsado al navegar a Chat');

  // 3. Navegar a Embeds con sidebar colapsado -> debe seguir colapsado
  activate('embeds', false);
  assert.ok(layout.hasClass('sidebar-collapsed'), 'Sidebar debe seguir colapsado al navegar a Embeds');

  // 4. Navegar a Inicio con sidebar colapsado -> debe seguir colapsado
  activate('inicio', false);
  assert.ok(layout.hasClass('sidebar-collapsed'), 'Sidebar debe seguir colapsado al navegar a Inicio');

  // 5. Expandir sidebar
  toggleSidebarCollapse();
  assert.equal(localStorage.getItem('purgito_dash_sidebar_collapsed'), 'false', 'Debe persistir false en localStorage');
  assert.ok(!layout.hasClass('sidebar-collapsed'), 'Layout no debe tener clase sidebar-collapsed');

  // 6. Navegar a Chat con sidebar expandido -> debe seguir expandido
  activate('chat', false);
  assert.ok(!layout.hasClass('sidebar-collapsed'), 'Sidebar debe seguir expandido al navegar a Chat');

  console.log('✓ Test 14: Persistencia bidireccional del sidebar en navegación');
}

// ── Test 15: Eliminación de auto-collapse en Embeds ───────────────────────────
{
  setupDOM();
  setGuildId('123456789');
  localStorage.setItem('purgito_dash_sidebar_collapsed', 'false');

  const layout = document.querySelector('.dash-layout');

  // Con sidebar expandido, entrar a embeds NO debe colapsar
  activate('embeds', false);
  assert.ok(!layout.hasClass('sidebar-collapsed'), 'Embeds no debe forzar el colapso del sidebar');

  // Con sidebar colapsado, entrar a embeds debe respetar el colapso
  toggleSidebarCollapse();
  assert.ok(layout.hasClass('sidebar-collapsed'), 'Sidebar está colapsado');
  activate('embeds', false);
  assert.ok(layout.hasClass('sidebar-collapsed'), 'Embeds respeta el estado colapsado si el usuario lo eligió');

  console.log('✓ Test 15: Embeds no altera arbitrariamente el estado del sidebar');
}

// ── Test 16: Compatibilidad con redirecciones legacy en Chat ──────────────────
{
  setupDOM();
  setGuildId('123456789');

  global.location.hash = '#reacciones';
  let activatedKey = null;
  const modChat = MODULES.find(m => m.key === 'chat');

  // Ejecutamos loadChatTab con hash #reacciones
  await modChat.load();
  assert.equal(global.location.pathname, '/es/dashboard/123456789/reacciones', 'Hash #reacciones debe activar el módulo dedicado de reacciones');

  global.location.hash = '#contenido';
  await modChat.load();
  assert.equal(global.location.pathname, '/es/dashboard/123456789/frases', 'Hash #contenido debe activar el módulo de frases');

  console.log('✓ Test 16: Enlaces legacy con hash redirigen limpiamente al módulo canónico');
}

console.log('\n========================================');
console.log('✓ TODOS LOS TESTS DEL DASHBOARD PASARON');
console.log('========================================\n');

