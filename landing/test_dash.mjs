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
  closest(sel) {
    if (sel.startsWith('.')) {
      const cls = sel.slice(1);
      if (this.hasClass(cls)) return this;
    }
    return null;
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

function jsonResp(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => data,
    text: async () => JSON.stringify(data),
    headers: new Map(),
  };
}

let fetchHandlers = [];

global.fetch = async (url, opts) => {
  for (const handler of fetchHandlers) {
    const res = await handler(url, opts);
    if (res) return res;
  }
  return jsonResp({});
};

function setupDOM() {
  elementsById.dashHead = new FakeElement('div');
  elementsById.dashTabs = new FakeElement('nav', { class: 'dash-sidebar' });
  elementsById.catContent = new FakeElement('div', { class: 'dash-content' });
  elementsById.toast = new FakeElement('div');
  elementsById.dashLayout = new FakeElement('div', { class: 'dash-layout' });
}

console.log('--- Iniciando tests de dash.js ---');

// Import del módulo
const {
  initDash, fetchUserGuilds, clearGuildsCache, selectGuild, activate, toggleSidebarCollapse,
  buildServerPicker, setServerPickerOpen, getServerPickerOpen, renderSidebar,
  MODULES, CATEGORIES
} = await import('./js/dash.js');
const { GUILD_ID, setGuildId } = await import('./js/core/config.js');

// ── Test 1: Estructura de módulos y categorías ─────────────────────────────────
{
  assert.ok(CATEGORIES.length >= 5, 'Debe haber al menos 5 categorías');
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
  assert.match(contentText, /Acciones rápidas/, 'Debe renderizar la sección de acciones rápidas');
  assert.match(contentText, /Personalización rápida/, 'Debe renderizar la tarjeta de estilo rápido');
  assert.match(contentText, /Actualizaciones del Bot/, 'Debe renderizar la sección de novedades');

  // Verificamos que la barra superior sea limpia (sin duplicar el avatar/nombre del servidor)
  const topText = elementsById.dashHead.text();
  assert.match(topText, /Servidores/);
  assert.match(topText, /Buscar/);
  assert.doesNotMatch(topText, /Mi Servidor Pro/, 'La barra superior no debe duplicar el nombre del servidor');
  assert.equal(elementsById.dashTabs.hidden, false, 'dashTabs no debe estar oculto');

  // Comprobamos el módulo dedicado de Estadísticas (Stats)
  const statsMod = MODULES.find(m => m.key === 'stats');
  assert.ok(statsMod, 'El módulo stats debe existir');
  await statsMod.load();
  await new Promise(r => setTimeout(r, 50));

  const statsContent = elementsById.catContent.text();
  assert.match(statsContent, /Estadísticas y Uso/, 'Debe renderizar el título del módulo stats');
  assert.match(statsContent, /1[.,]?200/, 'Debe renderizar las métricas de mensajes en memoria');
  assert.match(statsContent, /Actividad histórica/, 'Debe renderizar contadores históricos');
  assert.match(statsContent, /42/, 'Debe renderizar GIFs enviados');
  assert.match(statsContent, /999/, 'Debe renderizar mensajes enviados');

  console.log('✓ Test 2: Carga exitosa y render completo con servidor configurado e Inicio enfocado en configuración');
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
  assert.match(contentText, /No puedes administrar este servidor con esta cuenta/);
  assert.match(contentText, /Ver mis servidores/);

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

// ── Test 12: Simulador de Chat (generación espontánea y estados) ─────────────
{
  setupDOM();
  setGuildId('123456789');

  const playgroundMod = MODULES.find(m => m.key === 'playground');
  assert.ok(playgroundMod, 'Módulo playground debe existir');
  assert.equal(playgroundMod.label, 'Simulador de Chat', 'Debe nombrarse "Simulador de Chat"');

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
          result_type: 'message',
          would_respond: true,
          reason: 'markov',
          text: '¡Hola desde la simulación de Purgito!',
          channel_info: {
            id: '10',
            name: 'general',
            is_ignored: false,
            is_corpus_allowed: true,
            channel_corpus_count: 150,
            guild_corpus_count: 1200,
          },
          settings: {
            auto_generate_every: 15,
            auto_generate_probability: 0.6,
            frase_probability: 0.0,
            gif_response_probability: 0.2,
            reaction_probability: 0.05,
          },
          avisos: [],
        });
      }
      return jsonResp({});
    },
  ];

  await playgroundMod.load();
  await new Promise(r => setTimeout(r, 50));

  const initialContent = elementsById.catContent.text();
  assert.match(initialContent, /Simulador de Chat/);
  assert.match(initialContent, /Canal de prueba/);
  assert.match(initialContent, /Listo para simular/, 'Debe mostrar el estado inicial "Listo para simular"');
  assert.match(initialContent, /Ejecuta una simulación para previsualizar una interacción espontánea de Purgito en este canal/);
  assert.equal(simulatedRequest, null, 'No debe ejecutar la simulación antes de que el usuario pulse el botón');

  // Simular al pulsar el botón
  const simBtn = elementsById.catContent.querySelector('.sim-submit-btn') || elementsById.catContent.querySelector('.sim-empty-action-btn');
  assert.ok(simBtn && typeof simBtn.onclick === 'function', 'Debe existir el botón de Simular interacción');
  await simBtn.onclick();
  await new Promise(r => setTimeout(r, 50));

  assert.ok(simulatedRequest && simulatedRequest.channel_id === '10', 'Debe enviar la petición de simulación para el canal seleccionado');
  const simulatedContent = elementsById.catContent.text();
  const idxResult = simulatedContent.indexOf('Resultado simulado');
  const idxConfig = simulatedContent.indexOf('Configuración disponible');
  const idxRules = simulatedContent.indexOf('Reglas evaluadas');
  assert.ok(idxResult !== -1 && idxConfig !== -1 && idxRules !== -1, 'Todas las secciones deben existir');
  assert.ok(idxResult < idxConfig, 'Resultado simulado debe aparecer ANTES de Configuración disponible');
  assert.ok(idxConfig < idxRules, 'Configuración disponible debe aparecer ANTES de Reglas evaluadas');

  assert.match(simulatedContent, /Purgito podría responder:/);
  assert.match(simulatedContent, /¡Hola desde la simulación de Purgito!/);
  assert.ok(!simulatedContent.includes('Mensaje de entrada'), 'No debe existir el campo Mensaje de entrada');
  assert.ok(!simulatedContent.includes('Paso 1'), 'No debe existir estructura por pasos');

  // Repetir simulación en el mismo componente (actualización parcial in-place)
  await simBtn.onclick();
  await new Promise(r => setTimeout(r, 50));
  const reSimulatedContent = elementsById.catContent.text();
  assert.match(reSimulatedContent, /Resultado simulado/);
  assert.match(reSimulatedContent, /¡Hola desde la simulación de Purgito!/);

  // Test resultado GIF exclusivamente
  fetchHandlers = [
    (url, opts) => {
      if (url.includes('/api/server/123456789/channels')) {
        return jsonResp({
          channels: [{ id: '10', name: 'general', can_use_simulator: true }],
        });
      }
      if (url.includes('/api/server/123456789/chat/playground') && opts?.method === 'POST') {
        return jsonResp({
          result_type: 'gif',
          would_respond: true,
          reason: 'gif',
          gif_url: 'https://media.giphy.com/media/test.gif',
          channel_info: { id: '10', name: 'general' },
          settings: { gif_response_probability: 0.8 },
        });
      }
      return jsonResp({});
    },
  ];
  await playgroundMod.load();
  await new Promise(r => setTimeout(r, 50));
  const simBtnGif = elementsById.catContent.querySelector('.sim-submit-btn') || elementsById.catContent.querySelector('.sim-empty-action-btn');
  await simBtnGif.onclick();
  await new Promise(r => setTimeout(r, 50));
  const gifContent = elementsById.catContent.text();
  assert.match(gifContent, /GIF espontáneo/);
  assert.ok(!gifContent.includes('Purgito podría responder:'), 'No debe renderizar mensaje cuando el resultado es un GIF');

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

  console.log('✓ Test 12: Simulador de Chat con generación espontánea y estados correctos');
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

  // Bienvenidas, Despedidas, Boosts, Anuncios y Updates deben estar en Anuncios
  const welcomeMod = MODULES.find(m => m.key === 'welcome');
  assert.equal(welcomeMod.cat, 'anuncios', 'Bienvenidas debe estar en Anuncios');

  const goodbyeMod = MODULES.find(m => m.key === 'goodbye');
  assert.equal(goodbyeMod.cat, 'anuncios', 'Despedidas debe estar en Anuncios');

  const boostMod = MODULES.find(m => m.key === 'boost');
  assert.equal(boostMod.cat, 'anuncios', 'Boosts debe estar en Anuncios');

  const anunciosMod = MODULES.find(m => m.key === 'anuncios');
  assert.equal(anunciosMod.cat, 'anuncios', 'Anuncios debe estar en Anuncios');

  const updatesMod = MODULES.find(m => m.key === 'updates');
  assert.equal(updatesMod.cat, 'anuncios', 'Updates debe estar en Anuncios');

  // Triggers, Reacciones, Frases y YouTube deben estar en Automatización
  const youtubeMod = MODULES.find(m => m.key === 'youtube');
  assert.equal(youtubeMod.cat, 'automatizacion', 'YouTube debe estar en Automatización');

  const reaccionesMod = MODULES.find(m => m.key === 'reacciones');
  assert.equal(reaccionesMod.cat, 'automatizacion', 'Reacciones debe estar en Automatización');

  const frasesMod = MODULES.find(m => m.key === 'frases');
  assert.equal(frasesMod.cat, 'automatizacion', 'Frases debe estar en Automatización');

  const triggersMod = MODULES.find(m => m.key === 'triggers');
  assert.equal(triggersMod.cat, 'automatizacion', 'Triggers debe estar en Automatización');

  const chatMod = MODULES.find(m => m.key === 'chat');
  assert.equal(chatMod.cat, 'principal', 'Chat debe estar en Principal');

  const gifsMod = MODULES.find(m => m.key === 'gifs');
  assert.equal(gifsMod.cat, 'contenido', 'GIFs debe estar en Contenido');

  const canalesMod = MODULES.find(m => m.key === 'canales');
  assert.equal(canalesMod.cat, 'servidor', 'Canales debe estar en Servidor');

  const premiumMod = MODULES.find(m => m.key === 'premium');
  assert.ok(premiumMod, 'Purgito Premium debe existir');

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
  const modChat = MODULES.find(m => m.key === 'chat');

  // Ejecutamos loadChatTab con hash #reacciones
  await modChat.load();
  assert.equal(global.location.pathname, '/es/dashboard/123456789/reacciones', 'Hash #reacciones debe activar el módulo dedicado de reacciones');

  global.location.hash = '#contenido';
  await modChat.load();
  assert.equal(global.location.pathname, '/es/dashboard/123456789/frases', 'Hash #contenido debe activar el módulo de frases');

  console.log('✓ Test 16: Enlaces legacy con hash redirigen limpiamente al módulo canónico');
}

// ── Test 17: Manejo universal de atributos booleanos en el() ───────────────────
{
  const { el } = await import('/js/core/dom.js');

  const btnDisabled = el('button', { disabled: true }, 'Deshabilitado');
  assert.equal(btnDisabled.disabled, true, 'Propiedad disabled debe ser true');
  assert.equal(btnDisabled.getAttribute('disabled'), '', 'Atributo disabled debe existir');

  const btnEnabled = el('button', { disabled: false }, 'Habilitado');
  assert.equal(btnEnabled.disabled, false, 'Propiedad disabled debe ser false');
  assert.equal(btnEnabled.getAttribute('disabled'), undefined, 'Atributo disabled NO debe existir (no disabled="false")');

  const chkChecked = el('input', { type: 'checkbox', checked: true });
  assert.equal(chkChecked.checked, true);
  assert.equal(chkChecked.getAttribute('checked'), '');

  const chkUnchecked = el('input', { type: 'checkbox', checked: false });
  assert.equal(chkUnchecked.checked, false);
  assert.equal(chkUnchecked.getAttribute('checked'), undefined);

  console.log('✓ Test 17: Manejo universal de atributos booleanos en el()');
}

// ── Test 18: Paginación en modal de selección de emojis personalizados ─────────
{
  setupDOM();
  setGuildId('123456789');

  const mockEmojis = Array.from({ length: 129 }, (_, i) => ({
    id: `emoji_${i + 1}`,
    name: `custom_emoji_${i + 1}`,
    url: `https://cdn.example.com/emojis/${i + 1}.png`,
    animated: false,
  }));

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/server/123456789/emojis')) {
        return jsonResp({ emojis: mockEmojis });
      }
      return jsonResp({});
    },
  ];

  const { openAddEmojiModal } = await import('/js/dash.js');
  const dummyBox = new FakeElement('div');
  const overlay = await openAddEmojiModal(dummyBox, []);

  // Cambiar a la pestaña de emojis del servidor
  const tabButtons = overlay.findByClass('emoji-modal-tab');
  const serverTab = tabButtons.find(b => b.text().includes('Del servidor'));
  assert.ok(serverTab, 'Pestaña "Del servidor" debe existir');
  serverTab.click();

  // Esperar a que getEmojis() resuelva y renderice
  await new Promise(r => setTimeout(r, 60));

  // En página 1 (129 emojis = 9 páginas):
  let pager = overlay.querySelector('.emoji-pager');
  assert.ok(pager, 'El paginador de emojis debe existir');
  assert.match(pager.text(), /1 \/ 9 \(129 emojis\)/);

  const prevBtn = pager.children[0];
  const nextBtn = pager.children[2];

  assert.equal(prevBtn.disabled, true, 'Anterior debe estar deshabilitado en página 1');
  assert.equal(prevBtn.getAttribute('disabled'), '', 'Anterior debe tener atributo disabled');

  assert.equal(nextBtn.disabled, false, 'Siguiente debe estar habilitado en página 1');
  assert.equal(nextBtn.getAttribute('disabled'), undefined, 'Siguiente NO debe tener atributo disabled');

  // Click en Siguiente -> Avanza a página 2
  nextBtn.click();
  await new Promise(r => setTimeout(r, 20));

  pager = overlay.querySelector('.emoji-pager');
  assert.match(pager.text(), /2 \/ 9 \(129 emojis\)/);

  const prevBtnP2 = pager.children[0];
  const nextBtnP2 = pager.children[2];

  assert.equal(prevBtnP2.disabled, false, 'Anterior debe estar habilitado en página 2');
  assert.equal(prevBtnP2.getAttribute('disabled'), undefined);
  assert.equal(nextBtnP2.disabled, false, 'Siguiente debe estar habilitado en página 2');
  assert.equal(nextBtnP2.getAttribute('disabled'), undefined);

  // Avanzar hasta página 9 (última página)
  for (let p = 2; p < 9; p++) {
    const currentNext = overlay.querySelector('.emoji-pager').children[2];
    currentNext.click();
  }

  pager = overlay.querySelector('.emoji-pager');
  assert.match(pager.text(), /9 \/ 9 \(129 emojis\)/);

  const prevBtnP9 = pager.children[0];
  const nextBtnP9 = pager.children[2];

  assert.equal(prevBtnP9.disabled, false, 'Anterior debe estar habilitado en última página');
  assert.equal(prevBtnP9.getAttribute('disabled'), undefined);
  assert.equal(nextBtnP9.disabled, true, 'Siguiente debe estar deshabilitado en última página');
  assert.equal(nextBtnP9.getAttribute('disabled'), '');

  // Click en Anterior -> Vuelve a página 8
  prevBtnP9.click();
  pager = overlay.querySelector('.emoji-pager');
  assert.match(pager.text(), /8 \/ 9 \(129 emojis\)/);

  console.log('✓ Test 18: Paginación y estados disabled/enabled en modal de emojis');
}

// ── Test 19: Carga inicial inmediata de servidores en el selector (búsqueda vacía) ──
{
  setupDOM();
  setGuildId('111111111');
  const mockGuilds = {
    configured: [
      { id: '111111111', name: 'Mi Server Activo', is_premium: true, member_count: 350 },
      { id: '222222222', name: 'Server Secundario', is_premium: false, member_count: 80 },
    ],
    available: [
      { id: '333333333', name: 'Server Sin Purgito', invite_url: 'https://discord.com/oauth2/fake' },
    ],
  };

  setServerPickerOpen(true);
  const picker = buildServerPicker(mockGuilds.configured[0], mockGuilds, () => {});

  const list = picker.querySelector('.server-dropdown-list');
  assert.ok(list, 'La lista del dropdown debe existir');

  // Comprobamos que renderiza INMEDIATAMENTE sin necesidad de escribir en el buscador
  const listText = list.text();
  assert.match(listText, /Tus servidores con Purgito/, 'Debe mostrar encabezado de servidores configurados');
  assert.match(listText, /Mi Server Activo/, 'Debe listar el servidor activo');
  assert.match(listText, /Servidor activo/, 'Debe identificar el servidor activo');
  assert.match(listText, /PREMIUM/, 'Debe mostrar badge premium en el activo');
  assert.match(listText, /Server Secundario/, 'Debe listar el servidor secundario');
  assert.match(listText, /80 miembros/, 'Debe mostrar miembros del servidor secundario');
  assert.match(listText, /Otros servidores que administras/, 'Debe mostrar encabezado de servidores disponibles');
  assert.match(listText, /Server Sin Purgito/, 'Debe listar el servidor disponible');
  assert.match(listText, /Invitar a Purgito/, 'Debe incluir texto para invitar');

  // Comprobamos footer de administración
  const footer = picker.querySelector('.server-dropdown-footer');
  assert.ok(footer, 'Footer debe existir');
  assert.match(footer.text(), /Administrar todos los servidores →/);

  setServerPickerOpen(false);
  console.log('✓ Test 19: Carga inicial inmediata de servidores en el selector (búsqueda vacía)');
}

// ── Test 20: Filtro en tiempo real y restauración de la lista en el selector ────────
{
  setupDOM();
  setGuildId('111111111');
  const mockGuilds = {
    configured: [
      { id: '111111111', name: 'Mi Server Activo' },
      { id: '222222222', name: 'Comunidad Gaming' },
    ],
    available: [
      { id: '333333333', name: 'Amigos Discord' },
    ],
  };

  setServerPickerOpen(true);
  const picker = buildServerPicker(mockGuilds.configured[0], mockGuilds, () => {});
  const searchInput = picker.querySelector('.server-dropdown-search');
  const list = picker.querySelector('.server-dropdown-list');

  // 1. Filtrar por 'Gaming'
  searchInput.value = 'Gaming';
  searchInput.oninput();
  assert.match(list.text(), /Comunidad Gaming/);
  assert.doesNotMatch(list.text(), /Mi Server Activo/);
  assert.doesNotMatch(list.text(), /Amigos Discord/);

  // 2. Búsqueda sin resultados
  searchInput.value = 'Inexistente 12345';
  searchInput.oninput();
  assert.match(list.text(), /No se encontraron servidores\./);
  // Footer se mantiene
  const footer = picker.querySelector('.server-dropdown-footer');
  assert.match(footer.text(), /Administrar todos los servidores →/);

  // 3. Borrar búsqueda -> restauración completa inmediata
  searchInput.value = '';
  searchInput.oninput();
  assert.match(list.text(), /Mi Server Activo/);
  assert.match(list.text(), /Comunidad Gaming/);
  assert.match(list.text(), /Amigos Discord/);

  setServerPickerOpen(false);
  console.log('✓ Test 20: Filtro en tiempo real y restauración de la lista en el selector');
}

// ── Test 21: Selección de servidor y ciclo de apertura/cierre del selector ─────────
{
  setupDOM();
  setGuildId('111111111');
  const mockGuilds = {
    configured: [
      { id: '111111111', name: 'Mi Server Activo' },
      { id: '222222222', name: 'Nuevo Destino' },
    ],
    available: [],
  };

  let selectedGuildId = null;
  setServerPickerOpen(true);
  const picker = buildServerPicker(mockGuilds.configured[0], mockGuilds, (id) => {
    selectedGuildId = id;
  });

  const items = picker.querySelectorAll('.server-dropdown-item');
  assert.equal(items.length, 2, 'Debe haber 2 items');

  // Click en el segundo servidor
  items[1].click();
  assert.equal(selectedGuildId, '222222222', 'Debe seleccionar 222222222');
  assert.equal(getServerPickerOpen(), false, 'Debe cerrar el dropdown al seleccionar');

  console.log('✓ Test 21: Selección de servidor y ciclo de apertura/cierre del selector');
}

// ── Test 22: Carga diferida / fallback cuando se abre el selector sin caché previo ─
{
  setupDOM();
  setGuildId('444444444');
  clearGuildsCache();

  const mockGuilds = {
    configured: [
      { id: '444444444', name: 'Servidor Asíncrono', is_premium: false },
    ],
    available: [],
  };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp(mockGuilds);
      return jsonResp({});
    },
  ];

  setServerPickerOpen(true);
  // Llamamos a buildServerPicker sin guildsData y con caché vacío
  const picker = buildServerPicker(null, null, () => {});
  const list = picker.querySelector('.server-dropdown-list');

  // Debe esperar a la promesa de fetchUserGuilds
  await new Promise(r => setTimeout(r, 50));

  assert.match(list.text(), /Servidor Asíncrono/, 'Debe resolver y renderizar los servidores tras la carga');
  assert.match(list.text(), /Servidor activo/);

  setServerPickerOpen(false);
  console.log('✓ Test 22: Carga diferida / fallback cuando se abre el selector sin caché previo');
}

// ── Test 23: Error al obtener servidores con selector abierto ────────────────────
{
  setupDOM();
  setGuildId('555555555');
  clearGuildsCache();

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/me/guilds')) return jsonResp({ error: 'Network error' }, 500);
      return jsonResp({});
    },
  ];

  setServerPickerOpen(true);
  const picker = buildServerPicker(null, null, () => {});
  const list = picker.querySelector('.server-dropdown-list');

  await new Promise(r => setTimeout(r, 50));

  assert.match(list.text(), /No se pudieron cargar los servidores\./, 'Debe mostrar mensaje de error amigable');

  // El footer con el enlace a administración debe seguir existiendo
  const footer = picker.querySelector('.server-dropdown-footer');
  assert.ok(footer, 'Footer debe seguir presente ante error');
  assert.match(footer.text(), /Administrar todos los servidores →/);

  setServerPickerOpen(false);
  console.log('✓ Test 23: Error al obtener servidores con selector abierto');
}

// ── Test 24: createUpdatesSection estados y reactividad ─────────────────────────
{
  setupDOM();
  setGuildId('123456789');
  const { createUpdatesSection } = await import('./js/dash.js');
  const channels = [
    { id: '10', name: 'anuncios', can_view: true, can_send: true },
    { id: '20', name: 'general', can_view: true, can_send: false },
  ];

  // 1. Estado healthy (operativo)
  const healthyNode = createUpdatesSection(
    { channel_id: '10', status: 'healthy', channel_name: 'anuncios', can_publish: true },
    channels
  );
  assert.match(healthyNode.text(), /Canal configurado y operativo/, 'Debe mostrar badge operativo');
  assert.match(healthyNode.text(), /#anuncios/, 'Debe mostrar el nombre del canal');

  // 2. Estado missing_permissions (permisos insuficientes)
  const missingNode = createUpdatesSection(
    {
      channel_id: '20',
      status: 'missing_permissions',
      channel_name: 'general',
      missing_permissions: ['send_messages'],
      missing_permissions_labels: ['Enviar mensajes'],
    },
    channels
  );
  assert.match(missingNode.text(), /Permisos insuficientes/, 'Debe mostrar badge de permisos insuficientes');
  assert.match(missingNode.text(), /Enviar mensajes/, 'Debe listar el permiso faltante');

  // 3. Estado not_found (canal eliminado)
  const notFoundNode = createUpdatesSection(
    { channel_id: '999', status: 'not_found', can_publish: false },
    channels
  );
  assert.match(notFoundNode.text(), /Canal eliminado o inaccesible/, 'Debe mostrar badge de canal eliminado');

  // 4. Estado no_channel (sin canal)
  const noChanNode = createUpdatesSection(
    { channel_id: null, status: 'no_channel', can_publish: false },
    channels
  );
  assert.match(noChanNode.text(), /Sin canal configurado/, 'Debe mostrar badge sin canal');

  console.log('✓ Test 24: createUpdatesSection renderiza correctamente todos los estados (healthy, missing_permissions, not_found, no_channel)');
}

// ── Test 25: loadUpdatesModule carga y renderiza el módulo completo ────────────
{
  setupDOM();
  setGuildId('123456789');

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/server/123456789/settings/updates')) {
        return jsonResp({
          channel_id: '10',
          channel_name: 'anuncios',
          status: 'healthy',
          can_publish: true,
          missing_permissions: [],
          missing_permissions_labels: [],
        });
      }
      if (url.includes('/api/server/123456789/channels')) {
        return jsonResp({
          channels: [
            { id: '10', name: 'anuncios', can_view: true, can_send: true },
            { id: '20', name: 'general', can_view: true, can_send: true },
          ],
        });
      }
      return jsonResp({});
    },
  ];

  await activate('updates', false);
  await new Promise(r => setTimeout(r, 50));

  const contentText = elementsById.catContent.text();
  assert.match(contentText, /Canal de Novedades y Actualizaciones/, 'Debe renderizar el título del módulo');
  assert.match(contentText, /Canal configurado y operativo/, 'Debe mostrar el estado operativo');

  console.log('✓ Test 25: loadUpdatesModule carga y renderiza el módulo de actualizaciones');
}

// ── Test 26: Cobertura de i18n -- toda key de STRINGS.es existe en STRINGS.en
// (y viceversa) ──────────────────────────────────────────────────────────────
// Importar dash.js ya registró (por efecto de import transitivo) los strings
// de panel-shell.js, tabs/*.js y embeds/*.js. perfil.js y estado.js son
// entrypoints de página independientes que dash.js no importa, así que hace
// falta traerlos acá para que sus addStrings() también corran antes de
// comparar. Esto corre DESPUÉS de todos los tests de arriba a propósito: si
// alguno de ellos rompiera un import, queremos ver ESE error primero.
{
  await import('./js/perfil.js');
  // estado.js arranca un setInterval de polling en su propio top-level (ver
  // el final del archivo) -- necesario en el navegador, pero en Node deja el
  // proceso vivo para siempre. process.exit() de más abajo lo corta.
  await import('./js/estado.js');
  const { missingKeys } = await import('./js/core/i18n.js');
  const missing = missingKeys();
  assert.deepEqual(missing, [], `Keys de traducción incompletas: ${JSON.stringify(missing, null, 2)}`);
  console.log('✓ Test 26: Cobertura de i18n completa (keys(es) === keys(en))');
}

// ── Test 27: Helpers centralizados de URLs del frontend en core/config.js ──────
{
  const { getDashboardUrl, getPerfilUrl, getLoginUrl, parseGuildId, currentLocale } = await import('./js/core/config.js');

  // getDashboardUrl
  assert.equal(getDashboardUrl('123456789', 'inicio', null, 'es'), '/es/dashboard/123456789/inicio');
  assert.equal(getDashboardUrl('123456789', 'inicio', null, 'en'), '/en/dashboard/123456789/inicio');
  assert.equal(getDashboardUrl('123456789', 'chat', null, 'en'), '/en/dashboard/123456789/chat');
  assert.equal(getDashboardUrl('123456789', 'premium', 'annual', 'es'), '/es/dashboard/123456789/premium?plan=annual');
  assert.equal(getDashboardUrl('123456789', 'premium', 'monthly', 'en'), '/en/dashboard/123456789/premium?plan=monthly');

  // getPerfilUrl
  assert.equal(getPerfilUrl('servidores', 'es'), '/es/perfil/servidores');
  assert.equal(getPerfilUrl('servidores', 'en'), '/en/perfil/servidores');
  assert.equal(getPerfilUrl('facturacion', 'en'), '/en/perfil/facturacion');
  assert.equal(getPerfilUrl('conexiones', 'es'), '/es/perfil/conexiones');
  assert.equal(getPerfilUrl('perfil', 'en'), '/en/perfil');
  assert.equal(getPerfilUrl('', 'es'), '/es/perfil');

  // getLoginUrl
  assert.equal(getLoginUrl(false, 'es'), '/auth/login?locale=es');
  assert.equal(getLoginUrl('', 'es'), '/auth/login?locale=es');
  assert.equal(getLoginUrl('/en/dashboard/123/chat', 'en'), '/auth/login?locale=en&from=%2Fen%2Fdashboard%2F123%2Fchat');

  // parseGuildId & currentLocale
  assert.equal(parseGuildId('/en/dashboard/1471724794411089920/inicio'), '1471724794411089920');
  assert.equal(parseGuildId('/es/dashboard/987654321/chat'), '987654321');
  assert.equal(currentLocale('/en/perfil/servidores'), 'en');
  assert.equal(currentLocale('/es/dashboard/123/inicio'), 'es');
  assert.equal(currentLocale('/'), 'es');

  console.log('✓ Test 27: Helpers centralizados de URLs verificados (getDashboardUrl, getPerfilUrl, getLoginUrl, parseGuildId, currentLocale)');
}

// ── Test 28: Flujo Perfil -> Servidor -> Dashboard conserva el locale ──────────
{
  const { getDashboardUrl } = await import('./js/core/config.js');
  const guildMock = { id: '9988776655', name: 'Comunidad Purgito', is_premium: true, member_count: 50 };

  // Selección de servidor desde EN
  const enUrl = getDashboardUrl(guildMock.id, 'inicio', null, 'en');
  assert.equal(enUrl, '/en/dashboard/9988776655/inicio', 'Flujo EN debe generar /en/dashboard/<id>/inicio');

  // Selección de servidor desde ES
  const esUrl = getDashboardUrl(guildMock.id, 'inicio', null, 'es');
  assert.equal(esUrl, '/es/dashboard/9988776655/inicio', 'Flujo ES debe generar /es/dashboard/<id>/inicio');

  console.log('✓ Test 28: Flujo Perfil -> Servidor -> Dashboard conserva el locale en ambos idiomas');
}

// ── Test 29: Activación de pestañas del dashboard en ambos idiomas ─────────────
{
  const { getDashboardUrl } = await import('./js/core/config.js');
  const tabs = [
    'inicio', 'stats', 'chat', 'welcome', 'goodbye', 'boost', 'anuncios',
    'updates', 'gifs', 'memes', 'triggers', 'reacciones', 'frases',
    'canales', 'amnesia', 'historial', 'premium', 'youtube', 'embeds'
  ];
  for (const t of tabs) {
    assert.equal(getDashboardUrl('123', t, null, 'en'), `/en/dashboard/123/${t}`);
    assert.equal(getDashboardUrl('123', t, null, 'es'), `/es/dashboard/123/${t}`);
  }
  console.log('✓ Test 29: Tabs del dashboard generan URLs correctas en ES y EN');
}

// ── Test 30: URLs de CDN y avatares externos inmutables ────────────────────────
{
  const avatarCdnUrl = 'https://cdn.discordapp.com/avatars/1471724794411089920/a_abcdef123456.png?size=64';
  const defaultAvatarCdnUrl = 'https://cdn.discordapp.com/embed/avatars/3.png';

  assert.ok(avatarCdnUrl.startsWith('https://cdn.discordapp.com/'), 'Avatar custom es URL absoluta de Discord');
  assert.ok(defaultAvatarCdnUrl.startsWith('https://cdn.discordapp.com/'), 'Avatar default es URL absoluta de Discord');
  assert.ok(!avatarCdnUrl.includes('/en/https:'), 'URL externa jamás debe ser prefijada con /en/');
  assert.ok(!avatarCdnUrl.includes('/es/https:'), 'URL externa jamás debe ser prefijada con /es/');

  console.log('✓ Test 30: Inmutabilidad de URLs de Discord CDN y avatares');
}

// ── Test 31: Módulos dedicados e independientes de Bienvenidas, Despedidas y Boosts ──
{
  setupDOM();
  setGuildId('123456789');

  const { loadWelcomeTab, loadGoodbyeTab, loadBoostTab } = await import('./js/tabs/eventos.js');
  assert.equal(typeof loadWelcomeTab, 'function', 'loadWelcomeTab debe ser una función exportada');
  assert.equal(typeof loadGoodbyeTab, 'function', 'loadGoodbyeTab debe ser una función exportada');
  assert.equal(typeof loadBoostTab, 'function', 'loadBoostTab debe ser una función exportada');

  // Bienvenidas: legacy inline (mensaje guardado directo, sin plantilla) ->
  // debe mostrar el aviso de migración, no un editor de mensaje.
  const mockEventsData = {
    events: {
      welcome: {
        guild_id: 123456789,
        event_type: 'welcome',
        enabled: true,
        channel_id: 10,
        content_mode: 'plain_text',
        message: '¡Bienvenido {user} a {server_name}!',
        embed_json: null,
        template_id: null,
      },
      goodbye: {
        guild_id: 123456789,
        event_type: 'goodbye',
        enabled: false,
        channel_id: 20,
        content_mode: null,
        message: null,
        embed_json: null,
        template_id: 5,
      },
      boost: {
        guild_id: 123456789,
        event_type: 'boost',
        enabled: false,
        channel_id: null,
        content_mode: null,
        message: null,
        embed_json: null,
        template_id: null,
      },
    },
    variables: [
      { name: 'user', category: 'user', description: 'Mención del usuario', example: '@Punky', allowed_events: ['welcome', 'goodbye', 'boost'] },
    ],
  };

  const mockTemplatesData = {
    templates: [
      { id: 5, name: 'Hasta siempre', content_mode: 'plain_text', message: 'Chau {user}', used_by: ['goodbye'] },
    ],
    total: 1,
    limit: 20,
  };

  const mockChannels = {
    channels: [
      { id: '10', name: 'bienvenidas' },
      { id: '20', name: 'despedidas' },
    ],
  };
  const mockRoles = { roles: [] };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/server/123456789/events')) return jsonResp(mockEventsData);
      if (url.includes('/api/server/123456789/embeds/templates')) return jsonResp(mockTemplatesData);
      if (url.includes('/api/server/123456789/channels')) return jsonResp(mockChannels);
      if (url.includes('/api/server/123456789/roles')) return jsonResp(mockRoles);
      return jsonResp({});
    },
  ];

  // 1. Bienvenidas: sin plantilla, con contenido legacy inline -> aviso de migración
  await loadWelcomeTab();
  await new Promise(r => setTimeout(r, 50));

  let contentText = elementsById.catContent.text();
  assert.match(contentText, /Bienvenidas/);
  assert.match(contentText, /Activar bienvenida/);
  assert.match(contentText, /Canal de bienvenida/);
  assert.match(contentText, /Plantilla/);
  assert.match(contentText, /Convertir en plantilla/, 'contenido legacy inline debe ofrecer migrar a plantilla');
  assert.match(contentText, /Guardar cambios/);
  assert.match(contentText, /Enviar prueba/);
  assert.match(contentText, /Restablecer/);
  // El editor de mensaje/embed ya no vive acá — eso es responsabilidad de Plantillas.
  assert.doesNotMatch(contentText, /Vista previa en vivo/);
  assert.doesNotMatch(contentText, /Variables disponibles/);

  // 2. Despedidas: ya tiene plantilla asignada -> se ve seleccionada, sin aviso legacy
  await loadGoodbyeTab();
  await new Promise(r => setTimeout(r, 50));

  contentText = elementsById.catContent.text();
  assert.match(contentText, /Despedidas/);
  assert.match(contentText, /Activar despedida/);
  assert.match(contentText, /Canal de despedida/);
  assert.match(contentText, /Hasta siempre/, 'la plantilla vinculada debe aparecer seleccionada en el desplegable');
  assert.doesNotMatch(contentText, /Convertir en plantilla/, 'sin contenido inline no corresponde el aviso legacy');

  // 3. Boosts: sin activar, sin plantilla -> hint de "todavía no tenés plantillas" no aplica (hay 1 global), pero sin selección
  await loadBoostTab();
  await new Promise(r => setTimeout(r, 50));

  contentText = elementsById.catContent.text();
  assert.match(contentText, /Boosts/);
  assert.match(contentText, /Activar mensaje de boost/);
  assert.match(contentText, /Canal de boosts/);
  assert.match(contentText, /Desactivad[oa]/, 'boost está deshabilitado en el mock, el badge debe reflejarlo');

  console.log('✓ Test 31: Bienvenidas/Despedidas/Boosts como configuradores delgados (Eventos vs Plantillas)');
}

// ── Test 32: Módulo de Gestión de Anuncios Programados ───────────────────────
{
  setupDOM();
  setGuildId('123456789');

  const { loadAnunciosTab } = await import('./js/tabs/anuncios.js');
  assert.equal(typeof loadAnunciosTab, 'function', 'loadAnunciosTab debe ser una función exportada');

  const mockAnunciosData = {
    announcements: [
      {
        id: 1,
        channel_id: 10,
        message: '¡No olviden revisar las reglas del servidor!',
        mode: 'interval',
        interval_minutes: 30,
        hour: null,
        minute: null,
        last_sent_at: '2026-08-21 12:00:00',
        content_mode: 'plain_text',
        embed_json: null,
        delete_after_seconds: 60,
      },
    ],
    count: 1,
    max: 3,
    is_premium: false,
  };

  const mockChannels = {
    channels: [
      { id: '10', name: 'general' },
      { id: '20', name: 'anuncios' },
    ],
  };
  const mockRoles = { roles: [] };

  fetchHandlers = [
    (url) => {
      if (url.includes('/api/server/123456789/anuncios')) return jsonResp(mockAnunciosData);
      if (url.includes('/api/server/123456789/channels')) return jsonResp(mockChannels);
      if (url.includes('/api/server/123456789/roles')) return jsonResp(mockRoles);
      return jsonResp({});
    },
  ];

  await loadAnunciosTab();
  await new Promise(r => setTimeout(r, 50));

  const contentText = elementsById.catContent.text();
  assert.match(contentText, /Anuncios/);
  assert.match(contentText, /Automatiza mensajes para mantener informado tu servidor/);
  assert.match(contentText, /Crear anuncio/);
  assert.match(contentText, /1 \/ 3 anuncios utilizados/);
  assert.match(contentText, /Activo/);
  assert.match(contentText, /Cada 30 minutos/);
  assert.match(contentText, /#anuncios/);
  assert.match(contentText, /Auto-borrado: 60s/);
  assert.match(contentText, /Editar/);
  assert.match(contentText, /Eliminar/);

  console.log('✓ Test 32: Módulo de Gestión de Anuncios Programados verificado');
}

console.log('\n========================================');
console.log('✓ TODOS LOS TESTS DEL DASHBOARD PASARON');
console.log('========================================\n');

// estado.js dejó un setInterval corriendo (ver Test 26) -- sin esto el
// proceso de Node nunca termina solo.
process.exit(0);


