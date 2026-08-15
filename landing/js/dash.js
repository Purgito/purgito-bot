// Dashboard por servidor (/es/dashboard/:id): selector de servidor persistente,
// navegación por categorías de Purgito, buscador global (Ctrl + K),
// Inicio como resumen ejecutivo y módulos de configuración.
//
// Reutiliza los loaders de GIFS, EMBEDS, PREMIUM, YOUTUBE e HISTORIAL sin
// tocar su lógica.

import { apiFetch, humanError } from '/js/core/api.js';
import {
  el, icon, spinner, emptyState, renderError, guildIcon, toast, formGroup,
  confirmDelBtn, helpIcon, accordionGroup,
} from '/js/core/dom.js';
import { GUILD_ID, setGuildId, clearGuildCaches, currentLocale } from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, roleSelect, content } from '/js/panel-shell.js';
import { loadGifs } from '/js/tabs/gifs.js';
import { loadPremium } from '/js/tabs/premium.js';
import { loadYoutube } from '/js/tabs/youtube.js';
import { loadHistorial } from '/js/tabs/historial.js';
import {
  loadEmbeds, loadSharedEmbed, panelModal, getEmojis, uploadImageBlob,
} from '/js/embeds/shared-ui.js';

// ---------------- ESTRUCTURA DE MÓDULOS Y CATEGORÍAS ----------------

export const CATEGORIES = [
  { key: 'principal', label: 'Principal', icon: 'home' },
  { key: 'alertas', label: 'Alertas', icon: 'bell' },
  { key: 'anuncios', label: 'Anuncios', icon: 'layout' },
  { key: 'automatizacion', label: 'Automatización', icon: 'zap' },
  { key: 'entretenimiento', label: 'Entretenimiento', icon: 'image' },
  { key: 'utilidades', label: 'Utilidades', icon: 'sliders' },
];

export const MODULES = [
  // Principal
  {
    key: 'inicio',
    cat: 'principal',
    label: 'Inicio',
    icon: 'home',
    desc: 'Resumen del servidor, estado de Purgito y accesos rápidos',
    keywords: ['dashboard', 'resumen', 'estado', 'general', 'servidor', 'inicio'],
    load: loadInicio,
  },
  {
    key: 'chat',
    cat: 'principal',
    label: 'Ajustes de Chat',
    icon: 'chat',
    desc: 'Comportamiento, probabilidades, canales y límites del chat',
    keywords: ['chat', 'ajustes', 'markov', 'probabilidad', 'menciones', 'espontaneo', 'comportamiento'],
    load: loadChatTab,
  },
  {
    key: 'estilo',
    cat: 'principal',
    label: 'Personalización',
    icon: 'palette',
    desc: 'Apariencia de Purgito en este servidor: nick, avatar y banner',
    keywords: ['estilo', 'personalizacion', 'nick', 'apodo', 'avatar', 'banner', 'foto', 'apariencia'],
    load: loadEstiloModule,
  },
  {
    key: 'playground',
    cat: 'principal',
    label: 'Simulador de Chat',
    icon: 'play',
    desc: 'Simula y prueba cómo respondería Purgito en vivo según las reglas y corpus del canal',
    keywords: ['simulador', 'probar', 'simular', 'markov', 'generacion', 'chat', 'playground', 'respuestas'],
    load: loadPlaygroundModule,
  },
  {
    key: 'historial',
    cat: 'principal',
    label: 'Auditoría',
    icon: 'history',
    desc: 'Registro de cambios y auditoría de acciones realizadas',
    keywords: ['auditoria', 'historial', 'logs', 'registro', 'cambios', 'seguridad'],
    load: loadHistorial,
  },
  {
    key: 'premium',
    cat: 'principal',
    label: 'Purgito Premium',
    icon: 'star',
    badge: 'PREMIUM',
    badgeType: 'premium',
    desc: 'Memoria ampliada a 50.000 mensajes, 4.000 GIFs y soporte prioritario',
    keywords: ['premium', 'suscripcion', 'polar', 'planes', 'limites', 'cupo', '50000'],
    load: loadPremium,
  },

  // Alertas
  {
    key: 'youtube',
    cat: 'alertas',
    label: 'YouTube',
    icon: 'youtube',
    desc: 'Avisos automáticos de nuevos videos en canales de YouTube',
    keywords: ['youtube', 'videos', 'notificaciones', 'canales', 'alertas'],
    load: loadYoutube,
  },

  // Anuncios
  {
    key: 'embeds',
    cat: 'anuncios',
    label: 'Diseñador de Mensajes',
    icon: 'layout',
    desc: 'Editor visual de embeds clásicos y bloques interactivos Layout V2',
    keywords: ['embeds', 'anuncios', 'mensajes', 'diseñador', 'plantillas', 'layout', 'botones'],
    load: loadEmbeds,
  },
  {
    key: 'updates',
    cat: 'anuncios',
    label: 'Canal de Novedades',
    icon: 'bell',
    desc: 'Canal donde Purgito publica sus anuncios y actualizaciones',
    keywords: ['novedades', 'actualizaciones', 'anuncios', 'bot', 'canal'],
    load: loadUpdatesModule,
  },

  // Automatización
  {
    key: 'triggers',
    cat: 'automatizacion',
    label: 'Triggers de canal',
    icon: 'zap',
    desc: 'Respuestas automáticas por coincidencia de texto o regex',
    keywords: ['triggers', 'automatizacion', 'regex', 'patrones', 'coincidencias', 'respuestas'],
    load: loadTriggersModule,
  },
  {
    key: 'reacciones',
    cat: 'automatizacion',
    label: 'Reacciones automáticas',
    icon: 'smile',
    desc: 'Reacciona automáticamente con emojis configurados en mensajes',
    keywords: ['reacciones', 'emojis', 'automatizacion', 'reaccionar', 'caritas'],
    load: loadReaccionesModule,
  },
  {
    key: 'frases',
    cat: 'automatizacion',
    label: 'Frases y Packs',
    icon: 'sparkle',
    desc: 'Frases personalizadas y paquetes temáticos organizados por canal',
    keywords: ['frases', 'packs', 'especiales', 'personalizadas', 'mensajes'],
    load: loadFrasesModule,
  },

  // Entretenimiento
  {
    key: 'gifs',
    cat: 'entretenimiento',
    label: 'GIFs',
    icon: 'film',
    desc: 'Galería de GIFs del servidor para respuestas y comandos',
    keywords: ['gifs', 'galeria', 'animaciones', 'tenor', 'giphy', 'entretenimiento'],
    load: loadGifs,
  },
  {
    key: 'memes',
    cat: 'entretenimiento',
    label: 'Memes',
    icon: 'image',
    desc: 'Generación automática de memes y plantillas',
    keywords: ['memes', 'imagenes', 'generador', 'plantillas', 'entretenimiento'],
    load: loadMemes,
  },

  // Utilidades
  {
    key: 'canales',
    cat: 'utilidades',
    label: 'Canales y Permisos',
    icon: 'sliders',
    desc: 'Matriz de lectura/respuesta y canales o roles ignorados',
    keywords: ['canales', 'permisos', 'matriz', 'exentos', 'ignorados', 'silenciados', 'aprender'],
    load: loadCanalesModule,
  },
  {
    key: 'corpus',
    cat: 'utilidades',
    label: 'Importar Mensajes',
    icon: 'corpus',
    desc: 'Sube un archivo .txt para entrenar el estilo de chat de Purgito',
    keywords: ['corpus', 'importar', 'txt', 'mensajes', 'entrenar', 'aprendizaje'],
    load: loadCorpusModule,
  },
  {
    key: 'amnesia',
    cat: 'utilidades',
    label: 'Limpieza',
    icon: 'trash',
    desc: 'Borra mensajes y estilo aprendidos en las últimas 24 horas',
    keywords: ['amnesia', 'limpieza', 'borrar', 'corpus', '24 horas', 'reset'],
    load: loadAmnesiaModule,
  },
];

// Compatibilidad con TABS existentes
export const TABS = [
  { key: 'inicio', label: 'INICIO', icon: 'home', load: loadInicio },
  { key: 'chat', label: 'CHAT', icon: 'chat', load: loadChatTab },
  { key: 'gifs', label: 'GIFS', icon: 'film', load: loadGifs },
  { key: 'memes', label: 'MEMES', icon: 'image', load: loadMemes },
  { key: 'embeds', label: 'EMBEDS', icon: 'layout', load: loadEmbeds },
  { key: 'premium', label: 'PREMIUM', icon: 'star', load: loadPremium },
  { key: 'youtube', label: 'YOUTUBE', icon: 'youtube', load: loadYoutube },
  { key: 'historial', label: 'HISTORIAL', icon: 'history', load: loadHistorial },
];

const SIDEBAR_COLLAPSED_KEY = 'purgito_dash_sidebar_collapsed';

function getStoredSidebarCollapsed() {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true';
  } catch (e) {
    return false;
  }
}

function setStoredSidebarCollapsed(collapsed) {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
  } catch (e) { /* ignore */ }
}

let _sidebarCollapsed = getStoredSidebarCollapsed();
let _loadEpoch = 0;
let _activeGuild = null;
let _serverPickerOpen = false;

function updateSidebarLayoutState() {
  const layout = document.querySelector('.dash-layout');
  const nav = document.getElementById('dashTabs');
  if (layout) layout.classList.toggle('sidebar-collapsed', _sidebarCollapsed);
  if (nav) nav.classList.toggle('collapsed', _sidebarCollapsed);
}

export function toggleSidebarCollapse() {
  _sidebarCollapsed = !_sidebarCollapsed;
  setStoredSidebarCollapsed(_sidebarCollapsed);
  updateSidebarLayoutState();
  renderSidebar(currentTab());
}

function currentTab() {
  const seg = location.pathname.split('/')[4] || 'inicio';
  return MODULES.some(m => m.key === seg) ? seg : 'inicio';
}

// ---------------- PERSISTENCIA DE CATEGORÍAS EN SIDEBAR ----------------

const CAT_STORAGE_KEY = 'purgito_dash_collapsed_cats';

function getCollapsedCategories() {
  try {
    const raw = localStorage.getItem(CAT_STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch (e) {
    return new Set();
  }
}

function saveCollapsedCategories(set) {
  try {
    localStorage.setItem(CAT_STORAGE_KEY, JSON.stringify(Array.from(set)));
  } catch (e) { /* ignore */ }
}

function toggleCategoryCollapse(catKey) {
  const set = getCollapsedCategories();
  if (set.has(catKey)) set.delete(catKey);
  else set.add(catKey);
  saveCollapsedCategories(set);
  renderSidebar(currentTab());
}

// ---------------- SELECTOR DE SERVIDOR PERSISTENTE ----------------

let _cachedGuilds = null;
let _fetchingGuildsPromise = null;

export async function fetchUserGuilds(force = false) {
  if (force) {
    _cachedGuilds = null;
    _fetchingGuildsPromise = null;
  }
  if (_cachedGuilds) return _cachedGuilds;
  if (_fetchingGuildsPromise) return _fetchingGuildsPromise;

  _fetchingGuildsPromise = (async () => {
    try {
      const data = await apiFetch('/api/me/guilds' + (force ? '?refresh=1' : ''));
      _cachedGuilds = data || { configured: [], available: [] };
      return _cachedGuilds;
    } finally {
      _fetchingGuildsPromise = null;
    }
  })();

  return _fetchingGuildsPromise;
}

function buildServerPicker(activeGuild, guildsData, onSelectGuild) {
  const picker = el('div', { class: 'server-picker' });
  const configured = (guildsData && guildsData.configured) || [];
  const available = (guildsData && guildsData.available) || [];

  const trigger = el('button', {
    type: 'button',
    class: 'server-picker-btn' + (_serverPickerOpen ? ' active' : ''),
    'aria-haspopup': 'true',
    'aria-expanded': String(_serverPickerOpen),
    title: activeGuild ? activeGuild.name : 'Seleccionar servidor',
    onclick: (e) => {
      e.stopPropagation();
      _serverPickerOpen = !_serverPickerOpen;
      renderSidebar(currentTab());
    },
  },
    activeGuild ? guildIcon(activeGuild) : el('div', { class: 'guild-icon guild-initial' }, '?'),
    el('div', { class: 'server-picker-info' },
      el('div', { class: 'server-picker-name' }, activeGuild ? activeGuild.name : 'Servidor'),
      el('div', { class: 'server-picker-sub dim' },
        activeGuild && activeGuild.is_premium ? el('span', { class: 'badge badge-premium badge-xs' }, 'PREMIUM') : null,
        activeGuild && activeGuild.member_count != null ? `${Number(activeGuild.member_count).toLocaleString('es')} miembros` : 'Cambiar servidor'
      )
    ),
    el('span', { class: 'server-picker-caret' }, icon('chevronDown'))
  );

  picker.append(trigger);

  if (_serverPickerOpen) {
    const searchInput = el('input', {
      type: 'search',
      class: 'server-dropdown-search',
      placeholder: 'Buscar servidor…',
      autocomplete: 'off',
    });

    const listContainer = el('div', { class: 'server-dropdown-list' });

    function renderList() {
      const q = searchInput.value.trim().toLowerCase();
      listContainer.innerHTML = '';

      const filteredConfigured = configured.filter(g =>
        !q || (g.name || '').toLowerCase().includes(q) || (g.id || '').includes(q)
      );

      const filteredAvailable = available.filter(g =>
        !q || (g.name || '').toLowerCase().includes(q) || (g.id || '').includes(q)
      );

      if (!filteredConfigured.length && !filteredAvailable.length) {
        listContainer.append(el('div', { class: 'server-dropdown-empty dim' }, 'No se encontraron servidores.'));
        return;
      }

      if (filteredConfigured.length) {
        listContainer.append(el('div', { class: 'server-dropdown-header' }, 'Tus servidores con Purgito'));
        for (const g of filteredConfigured) {
          const isCurrent = g.id === GUILD_ID;
          const row = el('button', {
            type: 'button',
            class: 'server-dropdown-item' + (isCurrent ? ' active' : ''),
            onclick: () => {
              _serverPickerOpen = false;
              if (!isCurrent) onSelectGuild(g.id);
              else renderSidebar(currentTab());
            },
          },
            guildIcon(g),
            el('div', { class: 'server-dropdown-item-info' },
              el('div', { class: 'server-dropdown-item-name' },
                g.name,
                g.is_premium ? el('span', { class: 'badge badge-premium badge-xs' }, 'PREMIUM') : null
              ),
              el('div', { class: 'server-dropdown-item-sub dim' },
                isCurrent ? 'Servidor activo' : (g.member_count != null ? `${Number(g.member_count).toLocaleString('es')} miembros` : '')
              )
            ),
            isCurrent ? el('span', { class: 'server-dropdown-check' }, icon('check')) : null
          );
          listContainer.append(row);
        }
      }

      if (filteredAvailable.length) {
        listContainer.append(el('div', { class: 'server-dropdown-header' }, 'Otros servidores que administras'));
        for (const g of filteredAvailable) {
          const row = el('a', {
            class: 'server-dropdown-item server-dropdown-item--invite',
            href: g.invite_url || `https://discord.com/oauth2/authorize?client_id=1471724794411089920&guild_id=${g.id}&scope=bot%20applications.commands&permissions=8`,
            target: '_blank',
            rel: 'noopener',
          },
            guildIcon(g),
            el('div', { class: 'server-dropdown-item-info' },
              el('div', { class: 'server-dropdown-item-name' }, g.name),
              el('div', { class: 'server-dropdown-item-sub dim' }, 'Invitar a Purgito')
            ),
            el('span', { class: 'server-dropdown-ext' }, icon('externalLink'))
          );
          listContainer.append(row);
        }
      }
    }

    searchInput.oninput = renderList;

    const dropdown = el('div', { class: 'server-dropdown-menu' },
      el('div', { class: 'server-dropdown-search-wrap' },
        icon('search'),
        searchInput
      ),
      listContainer,
      el('div', { class: 'server-dropdown-footer' },
        el('a', { class: 'server-dropdown-manage-link', href: `/${currentLocale()}/perfil/servidores` },
          'Administrar todos los servidores →'
        )
      )
    );

    picker.append(dropdown);
    setTimeout(() => searchInput.focus(), 50);
  }

  return picker;
}

// ---------------- BUSCADOR GLOBAL DE MÓDULOS (Ctrl + K) ----------------

let _commandPaletteOpen = false;

function openCommandPalette() {
  if (_commandPaletteOpen) return;
  _commandPaletteOpen = true;

  let selectedIndex = 0;
  let matches = [];

  const backdrop = el('div', { class: 'cmd-palette-backdrop' });
  const modal = el('div', { class: 'cmd-palette-modal' });

  const input = el('input', {
    type: 'search',
    class: 'cmd-palette-input',
    placeholder: 'Buscar módulo, ajuste o comando…',
    autocomplete: 'off',
  });

  const resultsList = el('div', { class: 'cmd-palette-results' });

  function close() {
    _commandPaletteOpen = false;
    backdrop.remove();
  }

  function getCategoryLabel(catKey) {
    const cat = CATEGORIES.find(c => c.key === catKey);
    return cat ? cat.label : catKey;
  }

  function renderResults() {
    const q = input.value.trim().toLowerCase();
    resultsList.innerHTML = '';

    matches = MODULES.filter(m => {
      if (!q) return true;
      if (m.label.toLowerCase().includes(q)) return true;
      if (m.desc.toLowerCase().includes(q)) return true;
      if (m.cat.toLowerCase().includes(q)) return true;
      if (getCategoryLabel(m.cat).toLowerCase().includes(q)) return true;
      if (m.keywords && m.keywords.some(k => k.toLowerCase().includes(q))) return true;
      return false;
    });

    if (!matches.length) {
      resultsList.append(el('div', { class: 'cmd-palette-empty dim' }, `No se encontraron módulos para "${input.value}".`));
      return;
    }

    if (selectedIndex >= matches.length) selectedIndex = matches.length - 1;
    if (selectedIndex < 0) selectedIndex = 0;

    let currentCat = null;
    matches.forEach((m, idx) => {
      if (!q && m.cat !== currentCat) {
        currentCat = m.cat;
        resultsList.append(el('div', { class: 'cmd-palette-group-title' }, getCategoryLabel(m.cat)));
      }

      const isSelected = idx === selectedIndex;
      const itemNode = el('div', {
        class: 'cmd-palette-item' + (isSelected ? ' active' : ''),
        onclick: () => {
          close();
          activate(m.key, true);
        },
      },
        el('div', { class: 'cmd-palette-item-icon' }, icon(m.icon)),
        el('div', { class: 'cmd-palette-item-info' },
          el('div', { class: 'cmd-palette-item-title' },
            m.label,
            m.badge ? el('span', { class: `badge badge-${m.badgeType || 'soon'} badge-xs` }, m.badge) : null
          ),
          el('div', { class: 'cmd-palette-item-desc dim' }, m.desc)
        ),
        el('span', { class: 'cmd-palette-item-cat' }, getCategoryLabel(m.cat))
      );

      if (isSelected) {
        setTimeout(() => itemNode.scrollIntoView({ block: 'nearest' }), 0);
      }

      resultsList.append(itemNode);
    });
  }

  input.oninput = () => {
    selectedIndex = 0;
    renderResults();
  };

  input.onkeydown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (matches.length) {
        selectedIndex = (selectedIndex + 1) % matches.length;
        renderResults();
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (matches.length) {
        selectedIndex = (selectedIndex - 1 + matches.length) % matches.length;
        renderResults();
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (matches.length && matches[selectedIndex]) {
        const chosen = matches[selectedIndex];
        close();
        activate(chosen.key, true);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  };

  backdrop.onclick = (e) => {
    if (e.target === backdrop) close();
  };

  const header = el('div', { class: 'cmd-palette-header' },
    icon('search'),
    input,
    el('kbd', { class: 'cmd-palette-kbd' }, 'ESC')
  );

  const footer = el('div', { class: 'cmd-palette-footer' },
    el('span', { class: 'cmd-palette-tip' }, el('kbd', {}, '↑↓'), ' para navegar'),
    el('span', { class: 'cmd-palette-tip' }, el('kbd', {}, '↵'), ' para abrir'),
    el('span', { class: 'cmd-palette-tip' }, el('kbd', {}, 'ESC'), ' para cerrar')
  );

  modal.append(header, resultsList, footer);
  backdrop.append(modal);
  document.body.append(backdrop);

  renderResults();
  setTimeout(() => input.focus(), 50);
}

// Atajo global Ctrl + K / Cmd + K
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    openCommandPalette();
  }
});

// Cerrar selector de servidor al hacer click fuera
document.addEventListener('click', (e) => {
  if (_serverPickerOpen && !e.target.closest('.server-picker')) {
    _serverPickerOpen = false;
    renderSidebar(currentTab());
  }
});

// ---------------- RENDERIZADO DE SIDEBAR ----------------

function renderSidebar(activeTab) {
  const nav = document.getElementById('dashTabs');
  if (!nav) return;
  nav.className = 'dash-sidebar' + (_sidebarCollapsed ? ' collapsed' : '');
  nav.innerHTML = '';
  updateSidebarLayoutState();

  const activeModuleObj = MODULES.find(m => m.key === activeTab) || MODULES[0];

  // Botón colapsar / expandir en desktop (rail mode)
  const collapseBtn = el('button', {
    type: 'button',
    class: 'dash-sidebar-collapse-btn',
    title: _sidebarCollapsed ? 'Mostrar navegación' : 'Ocultar navegación',
    'aria-label': _sidebarCollapsed ? 'Mostrar navegación' : 'Ocultar navegación',
    'aria-expanded': String(!_sidebarCollapsed),
    onclick: () => toggleSidebarCollapse(),
  }, icon(_sidebarCollapsed ? 'panelOpen' : 'panelClose'));

  const header = el('div', { class: 'dash-sidebar-header' }, collapseBtn);

  // Selector móvil
  const currentLabelWrap = el('span', { class: 'dash-mobile-nav-current' },
    el('span', { class: 'dash-mobile-tab-name' }, activeModuleObj.label)
  );

  const toggleBtn = el('button', {
    type: 'button',
    class: 'dash-mobile-nav-toggle',
    'aria-expanded': 'false',
    'aria-label': 'Abrir navegación del dashboard',
    onclick: () => {
      const isOpen = nav.classList.toggle('open');
      toggleBtn.setAttribute('aria-expanded', String(isOpen));
    },
  },
    currentLabelWrap,
    el('svg', { class: 'dash-mobile-nav-chev', viewBox: '0 0 24 24', 'aria-hidden': 'true' },
      el('path', { d: 'M6 9l6 6 6-6' }))
  );

  function closeMobileNav() {
    nav.classList.remove('open');
    toggleBtn.setAttribute('aria-expanded', 'false');
  }

  const inner = el('div', { class: 'dash-sidebar-inner' });

  // 1. Selector de servidor persistente
  if (!_sidebarCollapsed) {
    const serverPickerNode = buildServerPicker(_activeGuild, _cachedGuilds, (newGuildId) => {
      closeMobileNav();
      selectGuild(newGuildId);
    });
    inner.append(serverPickerNode);

    // 2. Buscador rápido de módulos (Ctrl + K)
    const cmdSearchBtn = el('button', {
      type: 'button',
      class: 'dash-cmd-search-btn',
      title: 'Buscar módulo (Ctrl + K)',
      onclick: () => {
        closeMobileNav();
        openCommandPalette();
      },
    },
      icon('search'),
      el('span', { class: 'dash-cmd-search-text' }, 'Buscar módulo…'),
      el('kbd', { class: 'dash-cmd-search-badge' }, '⌘K')
    );
    inner.append(cmdSearchBtn);
  }

  // 3. Categorías y módulos
  const collapsedCats = getCollapsedCategories();

  for (const cat of CATEGORIES) {
    const catModules = MODULES.filter(m => m.cat === cat.key);
    if (!catModules.length) continue;

    const hasActiveModule = catModules.some(m => m.key === activeTab);
    const isCollapsed = !_sidebarCollapsed && collapsedCats.has(cat.key) && !hasActiveModule;

    const catGroup = el('div', {
      class: 'dash-sidebar-cat-group' + (isCollapsed ? ' is-collapsed' : ''),
    });

    if (!_sidebarCollapsed) {
      const catHeader = el('button', {
        type: 'button',
        class: 'dash-sidebar-cat-header',
        'aria-expanded': String(!isCollapsed),
        onclick: () => toggleCategoryCollapse(cat.key),
      },
        el('span', { class: 'dash-sidebar-cat-title' }, cat.label),
        el('span', { class: 'dash-sidebar-cat-chev' }, icon('chevronDown'))
      );
      catGroup.append(catHeader);
    }

    const list = el('ul', { class: 'dash-sidebar-list' });

    for (const m of catModules) {
      const isTabActive = m.key === activeTab;
      const item = el('li', {
        class: 'dash-sidebar-item' + (isTabActive ? ' active' : ''),
      });

      const tabLink = el('a', {
        class: 'dash-tab' + (isTabActive ? ' active' : ''),
        'data-key': m.key,
        href: `/${currentLocale()}/dashboard/${GUILD_ID}/${m.key}`,
        'aria-current': isTabActive ? 'page' : null,
        title: m.label,
        onclick: (ev) => {
          ev.preventDefault();
          closeMobileNav();
          activate(m.key, true);
        },
      },
        icon(m.icon),
        el('span', { class: 'dash-tab-label' }, m.label),
        m.badge ? el('span', { class: `badge badge-${m.badgeType || 'soon'} badge-xs` }, m.badge) : null
      );

      item.append(tabLink);
      list.append(item);
    }

    catGroup.append(list);
    inner.append(catGroup);
  }

  nav.append(header, toggleBtn, inner);
}

// ---------------- CABECERA Y TOPBAR ----------------

export function renderTopBar(guild) {
  const head = document.getElementById('dashHead');
  if (!head) return;
  head.innerHTML = '';

  const loc = currentLocale();

  const titleNode = el('div', { class: 'dash-topbar' },
    el('a', { class: 'dash-back-link', href: `/${loc}/perfil/servidores` },
      icon('arrowLeft'),
      el('span', {}, 'Servidores')
    ),
    el('div', { class: 'dash-topbar-actions' },
      el('button', {
        type: 'button',
        class: 'btn btn-secondary btn-sm',
        title: 'Buscar módulo o comando (Ctrl + K)',
        onclick: () => openCommandPalette(),
      },
        icon('search'),
        el('span', { class: 'hide-mobile' }, 'Buscar')
      )
    )
  );

  head.append(titleNode);
}

export async function loadHead() {
  const head = document.getElementById('dashHead');
  if (!head) return;
  try {
    const data = await fetchUserGuilds();
    const configured = (data && data.configured) || [];
    const g = configured.find(x => x.id === GUILD_ID);
    if (g) {
      _activeGuild = g;
      document.title = `${g.name} · Purgito`;
    }
    renderTopBar(_activeGuild);
  } catch (e) {
    renderTopBar(_activeGuild);
  }
}

// ---------------- CAMBIO REACTIVO DE SERVIDOR ----------------

export async function selectGuild(newGuildId) {
  if (!newGuildId || newGuildId === GUILD_ID) return;

  setGuildId(newGuildId);
  clearGuildCaches();
  _loadEpoch++;

  const curTab = currentTab();
  history.pushState({}, '', `/${currentLocale()}/dashboard/${newGuildId}/${curTab}`);

  const data = await fetchUserGuilds();
  const configured = (data && data.configured) || [];
  _activeGuild = configured.find(x => x.id === newGuildId) || null;
  if (_activeGuild) {
    document.title = `${_activeGuild.name} · Purgito`;
  }
  renderTopBar(_activeGuild);

  activate(curTab, false);
  toast('Cambiando al servidor…', 'ok');
}

// ---------------- ACTIVACIÓN DE MÓDULO ----------------

export function activate(key, push) {
  renderSidebar(key);

  if (push) {
    history.pushState({}, '', `/${currentLocale()}/dashboard/${GUILD_ID}/${key}`);
  }

  if (key === 'inicio') {
    loadHead();
  }

  const mod = MODULES.find(m => m.key === key) || MODULES[0];
  mod.load();
}

// ---------------- INICIALIZACIÓN DETERMINISTA Y ROBUSTA ----------------

export async function initDash() {
  const head = document.getElementById('dashHead');
  const tabs = document.getElementById('dashTabs');
  const box = content();

  // 1. Si no hay GUILD_ID en la URL (ej. /es/dashboard o /dashboard)
  if (!GUILD_ID) {
    if (head) head.innerHTML = '';
    if (tabs) tabs.hidden = true;
    if (box) {
      box.innerHTML = '';
      box.append(spinner());
    }

    try {
      const data = await fetchUserGuilds();
      const configured = (data && data.configured) || [];
      if (configured.length > 0) {
        location.replace(`/${currentLocale()}/dashboard/${configured[0].id}/inicio`);
        return;
      }
      location.replace(`/${currentLocale()}/perfil/servidores`);
      return;
    } catch (e) {
      if (box) {
        box.innerHTML = '';
        renderError(box, e);
      }
      return;
    }
  }

  // 2. Con GUILD_ID presente: cargamos primero la lista de servidores del usuario
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }

  try {
    const data = await fetchUserGuilds();
    const configured = (data && data.configured) || [];
    const available = (data && data.available) || [];
    const g = configured.find(x => x.id === GUILD_ID);

    if (!g) {
      const avail = available.find(x => x.id === GUILD_ID);
      const back = el('a', { class: 'dash-back', href: `/${currentLocale()}/perfil/servidores` },
        el('span', { class: 'dash-back-arrow', 'aria-hidden': 'true' }, '←'), 'Volver a servidores');
      if (head) {
        head.innerHTML = '';
        head.append(back);
      }
      if (tabs) tabs.hidden = true;
      if (box) {
        box.innerHTML = '';
        if (avail) {
          box.append(el('div', { class: 'dash-server-hero', style: 'max-width: 640px; margin: 30px auto; flex-direction: column; text-align: center; gap: 16px; padding: 28px;' },
            guildIcon(avail),
            el('div', { class: 'dash-server-hero-info', style: 'align-items: center;' },
              el('h2', { class: 'dash-server-hero-name', style: 'font-size: 20px;' }, avail.name),
              el('p', { class: 'dim', style: 'margin: 6px 0 16px; font-size: 14px;' }, 'Purgito todavía no está instalado en este servidor.'),
              el('div', { style: 'display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;' },
                el('a', { class: 'btn btn-primary', href: avail.invite_url || `https://discord.com/oauth2/authorize?client_id=1471724794411089920&guild_id=${avail.id}&scope=bot%20applications.commands&permissions=8`, target: '_blank', rel: 'noopener' }, 'Invitar a Purgito'),
                el('a', { class: 'btn btn-secondary', href: `/${currentLocale()}/perfil/servidores` }, 'Ver mis servidores')
              )
            )
          ));
        } else {
          box.append(emptyState('No encontramos ese servidor entre los que administras.'));
        }
      }
      return;
    }

    _activeGuild = g;
    document.title = `${g.name} · Purgito`;

    if (tabs) tabs.hidden = false;
    renderTopBar(g);

    const shareId = new URLSearchParams(location.search).get('share');
    if (shareId) {
      loadSharedEmbed(shareId).finally(() => activate('embeds', true));
    } else {
      const tab = currentTab();
      activate(tab, false);
      if (!location.pathname.split('/')[4]) {
        history.replaceState({}, '', `/${currentLocale()}/dashboard/${GUILD_ID}/${tab}`);
      }
    }
  } catch (e) {
    if (box) {
      box.innerHTML = '';
      renderError(box, e);
    }
  }
}

window.onpopstate = async () => {
  const rawGuild = location.pathname.split('/')[3] || '';
  if (rawGuild && rawGuild !== GUILD_ID) {
    setGuildId(rawGuild);
    clearGuildCaches();
    _loadEpoch++;
    const data = await fetchUserGuilds();
    const configured = (data && data.configured) || [];
    _activeGuild = configured.find(x => x.id === GUILD_ID) || null;
    renderTopBar(_activeGuild);
  }
  activate(currentTab(), false);
};

// Cerrar menú móvil con Escape
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    const nav = document.getElementById('dashTabs');
    if (nav && nav.classList.contains('open')) {
      nav.classList.remove('open');
      const toggle = nav.querySelector('.dash-mobile-nav-toggle');
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
    }
  }
});

// Cerrar menú móvil al clickear fuera
document.addEventListener('click', (ev) => {
  const nav = document.getElementById('dashTabs');
  if (nav && nav.classList.contains('open') && !nav.contains(ev.target)) {
    nav.classList.remove('open');
    const toggle = nav.querySelector('.dash-mobile-nav-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
  }
});

initDash();


// ---------------- REDISEÑO DE INICIO (DASHBOARD EJECUTIVO) ----------------

function withCap(used, cap) {
  if (used == null) return null;
  const n = Number(used).toLocaleString('es');
  if (!cap) return n;
  return el('span', { class: 'stat-cap-wrap' },
    el('span', { class: 'stat-num-main' }, n),
    el('span', { class: 'stat-num-cap dim' }, ` / ${Number(cap).toLocaleString('es')}`));
}

function statTile(iconName, value, label, subtext) {
  const valEl = el('div', { class: 'stat-value' });
  if (value instanceof Node) {
    valEl.append(value);
  } else {
    valEl.textContent = value != null ? (typeof value === 'number' ? value.toLocaleString('es') : String(value)) : '—';
  }
  return el('div', { class: 'stat-tile' },
    el('div', { class: 'stat-icon-wrap' }, icon(iconName)),
    el('div', { class: 'stat-content' },
      el('div', { class: 'stat-label dim' }, label),
      valEl,
      subtext ? el('div', { class: 'stat-sub dim' }, subtext) : null
    ));
}

function quickActionCard(iconName, title, desc, onClick) {
  return el('button', {
    type: 'button',
    class: 'quick-action-card',
    onclick: onClick,
  },
    el('div', { class: 'quick-action-icon-wrap' }, icon(iconName)),
    el('div', { class: 'quick-action-info' },
      el('div', { class: 'quick-action-title' }, title),
      el('div', { class: 'quick-action-desc dim' }, desc)
    ),
    el('span', { class: 'quick-action-arrow dim' }, '→')
  );
}

async function loadInicio() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  const epoch = _loadEpoch;

  try {
    const [styleRes, updatesRes, statsRes, channelsRes] = await Promise.allSettled([
      apiFetch(`/api/server/${GUILD_ID}/style`),
      apiFetch(`/api/server/${GUILD_ID}/settings/updates`),
      apiFetch(`/api/server/${GUILD_ID}/stats`),
      getChannels({ force: true }),
    ]);

    if (epoch !== _loadEpoch) return; // Rechaza respuestas desfasadas
    if (!box) return;
    box.innerHTML = '';

    const style = styleRes.status === 'fulfilled' ? (styleRes.value || {}) : {};
    const updates = updatesRes.status === 'fulfilled' ? (updatesRes.value || {}) : {};
    const stats = statsRes.status === 'fulfilled' ? (statsRes.value || {}) : {};
    const channels = channelsRes.status === 'fulfilled' ? (channelsRes.value || []) : [];

    // Si todas las llamadas de datos fallaron por auth o error fatal:
    if (styleRes.status === 'rejected' && statsRes.status === 'rejected' && channelsRes.status === 'rejected') {
      renderError(box, styleRes.reason || statsRes.reason);
      return;
    }

    const g = _activeGuild;

    // 1. Resumen / Hero del Servidor
    const memberText = g && g.member_count != null
      ? `${Number(g.member_count).toLocaleString('es')} miembros`
      : 'Servidor de Discord';

    const serverHero = el('div', { class: 'dash-server-hero' },
      g ? guildIcon(g) : null,
      el('div', { class: 'dash-server-hero-info' },
        el('div', { class: 'dash-server-hero-title-row' },
          el('h1', { class: 'dash-server-hero-name' }, (g && g.name) || 'Servidor'),
          g && g.is_premium ? el('span', { class: 'badge badge-premium' }, 'PREMIUM') : null
        ),
        el('div', { class: 'dash-server-hero-meta dim' },
          el('span', {}, memberText),
          el('span', { class: 'meta-sep' }, '·'),
          el('span', {}, `${stats.text_channels || channels.length || 0} canales`),
          el('span', { class: 'meta-sep' }, '·'),
          el('span', { class: 'server-id-mono' }, `ID: ${GUILD_ID}`)
        )
      )
    );
    box.append(serverHero);

    // 2. Estado y Métricas de Purgito
    const lims = stats.limits || {};
    const tiles = el('div', { class: 'stat-grid' },
      statTile('corpus', withCap(stats.corpus_total, lims.corpus_total), 'Mensajes en memoria', 'Corpus de aprendizaje'),
      statTile('film', withCap(stats.gifs, lims.gifs), 'GIFs en catálogo', 'Para respuestas y comandos'),
      statTile('sparkle', withCap(stats.frases, lims.frases), 'Frases especiales', 'Respuestas configuradas'),
      statTile('chat', `${stats.reading_channels || 0} / ${stats.text_channels || channels.length || 0}`, 'Canales que lee', 'Para armar estilo'),
      statTile('layout', `${stats.reply_channels || 0} / ${stats.text_channels || channels.length || 0}`, 'Canales que responde', 'Menciones y espontáneos'),
      statTile('smile', stats.reactions || 0, 'Emojis de reacción', 'Pool activo')
    );

    const alcanzados = [
      [stats.corpus_total, lims.corpus_total, 'mensajes guardados'],
      [stats.gifs, lims.gifs, 'GIFs'],
      [stats.frases, lims.frases, 'frases especiales'],
    ].filter(([used, cap]) => cap && used >= cap);

    const cerca = [
      [stats.corpus_total, lims.corpus_total, 'mensajes guardados'],
      [stats.gifs, lims.gifs, 'GIFs'],
      [stats.frases, lims.frases, 'frases especiales'],
    ].filter(([used, cap]) => cap && used >= cap * 0.9 && used < cap);

    let quotaNotice = null;
    if (alcanzados.length) {
      quotaNotice = el('div', { class: 'stat-quota-box stat-quota-box--full' },
        el('span', { class: 'stat-quota-icon' }, '⚠️'),
        el('div', { class: 'stat-quota-text' },
          `Has alcanzado el límite de ${alcanzados.map(c => c[2]).join(' y ')}. ` +
          'Purgito descarta automáticamente el contenido más antiguo para dar lugar a nuevo contenido.'
        )
      );
    } else if (cerca.length) {
      quotaNotice = el('div', { class: 'stat-quota-box stat-quota-box--near' },
        el('span', { class: 'stat-quota-icon' }, 'ℹ️'),
        el('div', { class: 'stat-quota-text' },
          `Estás cerca del cupo de ${cerca.map(c => c[2]).join(' y ')}: al alcanzarlo, ` +
          'Purgito empezará a descartar lo más antiguo para hacer lugar a lo nuevo.'
        )
      );
    }

    box.append(formGroup('Estado de Purgito en este servidor', tiles, quotaNotice));

    // 3. Acciones rápidas (Quick Actions)
    const quickActionsGrid = el('div', { class: 'quick-actions-grid' },
      quickActionCard('chat', 'Ajustes de Chat', 'Comportamiento, probabilidades y límites de conversación', () => activate('chat', true)),
      quickActionCard('palette', 'Personalización', 'Personaliza el nombre, avatar y banner de Purgito', () => activate('estilo', true)),
      quickActionCard('layout', 'Diseñador de Mensajes', 'Crea y programa anuncios con embeds o Layout V2', () => activate('embeds', true)),
      quickActionCard('film', 'Galería de GIFs', 'Gestiona y verifica la colección de GIFs del servidor', () => activate('gifs', true)),
      quickActionCard('zap', 'Triggers y Automatización', 'Configura respuestas automáticas y frases clave', () => activate('triggers', true)),
      quickActionCard('history', 'Auditoría', 'Revisa el historial de cambios y acciones realizadas', () => activate('historial', true))
    );

    box.append(formGroup('Acciones rápidas', quickActionsGrid));

    // 4. Configuración Rápida / Estilo y Actualizaciones
    const avatar = style.avatar_url || style.current_avatar_url;
    const nick = style.nick || style.current_nick || 'Purgito';

    const stylePreviewNode = formGroup('Personalización rápida',
      el('div', { class: 'style-card' },
        el('div', { class: 'style-preview' },
          avatar ? el('img', { class: 'style-avatar', src: avatar, alt: '' }) : null,
          el('div', {},
            el('div', { class: 'style-nick' }, nick, el('span', { class: 'dm-badge' }, 'BOT')),
            el('div', { class: 'dim' }, 'Así se ve Purgito en este servidor')
          )
        ),
        el('div', { class: 'style-card-actions' },
          el('button', {
            class: 'btn btn-secondary',
            onclick: () => openStyleModal(style),
          }, 'Editar estilo'),
          el('button', {
            class: 'btn btn-secondary',
            onclick: () => activate('estilo', true),
          }, 'Ver opciones →')
        )
      )
    );

    // Canal de actualizaciones
    const sel = channelSelect(channels, updates.channel_id, 'Sin canal — no publicar');
    sel.onchange = async () => {
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/updates`, {
          method: 'PUT', body: { channel_id: sel.value || null },
        });
        toast(sel.value ? 'Canal de actualizaciones guardado' : 'Canal de actualizaciones quitado', 'ok');
      } catch (e) { toast('No se pudo guardar el canal, intenta de nuevo', 'err'); }
    };

    const updatesRow = formGroup('Actualizaciones del Bot',
      el('div', { class: 'updates-row' },
        el('div', { class: 'updates-info' },
          el('p', { class: 'dim' }, 'Canal donde Purgito publica anuncios y novedades de actualizaciones.')
        ),
        el('div', { class: 'updates-control' }, sel)
      )
    );

    // Actividad histórica acumulada
    const counters = stats.counters || {};
    const activityRow = formGroup('Actividad histórica',
      el('p', { class: 'dim' }, 'Actividad acumulada en este servidor desde que se unió Purgito.'),
      el('div', { class: 'activity-grid' },
        el('div', { class: 'activity-card' },
          el('div', { class: 'activity-icon-wrap' }, icon('film')),
          el('div', { class: 'activity-content' },
            el('div', { class: 'activity-value' }, Number(counters.gifs_enviados || 0).toLocaleString('es')),
            el('div', { class: 'activity-label' }, 'GIFs enviados'),
            el('div', { class: 'activity-sub dim' }, 'Total histórico acumulado')
          )
        ),
        el('div', { class: 'activity-card' },
          el('div', { class: 'activity-icon-wrap' }, icon('chat')),
          el('div', { class: 'activity-content' },
            el('div', { class: 'activity-value' }, Number(counters.mensajes_enviados || 0).toLocaleString('es')),
            el('div', { class: 'activity-label' }, 'Mensajes enviados'),
            el('div', { class: 'activity-sub dim' }, 'Total histórico acumulado')
          )
        )
      )
    );

    box.append(stylePreviewNode, updatesRow, activityRow);
  } catch (e) {
    if (box) renderError(box, e);
  }
}

// ---------------- MÓDULOS ESPECÍFICOS DIRECTOS ----------------

export function openStyleModal(style = {}) {
  const currentNick = style.nick || style.current_nick || '';
  const currentAvatar = style.avatar_url || style.current_avatar_url || '';
  const currentBanner = style.banner_url || '';

  const nickInput = el('input', {
    type: 'text',
    placeholder: 'Purgito',
    maxlength: '32',
    value: currentNick,
    class: 'input-text',
    style: 'width: 100%;',
  });

  const nickCounter = el('span', { class: 'dim style-counter' }, `${currentNick.length}/32`);
  nickInput.oninput = () => {
    nickCounter.textContent = `${nickInput.value.length}/32`;
  };

  let editAvatar = false;
  let avatarUrl = style.avatar_url;
  let editBanner = false;
  let bannerUrl = style.banner_url;

  // Avatar
  const avatarCheck = el('input', { type: 'checkbox' });
  const avatarPreview = el('img', {
    class: 'style-avatar',
    src: currentAvatar || '/assets/icon.png',
    alt: '',
    style: 'width: 48px; height: 48px; border-radius: 50%; object-fit: cover;',
  });
  const avatarFile = el('input', {
    type: 'file', accept: 'image/png,image/jpeg,image/gif,image/webp', style: 'display:none',
  });
  const avatarUploadBtn = el('button', {
    type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => avatarFile.click(),
  }, 'Subir imagen');
  const avatarRemoveBtn = el('button', {
    type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => {
      avatarUrl = null;
      avatarPreview.src = '/assets/icon.png';
      avatarCheck.checked = true;
      editAvatar = true;
    },
  }, 'Quitar');

  const avatarControls = el('div', { class: 'style-img-body' },
    avatarPreview,
    el('div', { style: 'display:flex;flex-direction:column;gap:6px;' },
      el('div', { style: 'display:flex;gap:6px;' }, avatarUploadBtn, avatarRemoveBtn),
      el('span', { class: 'dim', style: 'font-size:12px;' }, 'PNG, JPG, GIF o WEBP. Máx 10 MB.')
    ),
    avatarFile
  );

  avatarFile.onchange = async () => {
    const file = avatarFile.files[0];
    if (!file) return;
    avatarUploadBtn.disabled = true;
    avatarUploadBtn.textContent = 'Subiendo…';
    try {
      const url = await uploadImageBlob(file);
      avatarUrl = url;
      avatarPreview.src = url;
      avatarCheck.checked = true;
      editAvatar = true;
      toast('Avatar subido', 'ok');
    } catch (e) {
      toast(e.message || 'No se pudo subir la imagen', 'err');
    } finally {
      avatarUploadBtn.disabled = false;
      avatarUploadBtn.textContent = 'Subir imagen';
    }
  };

  avatarCheck.onchange = () => { editAvatar = avatarCheck.checked; };

  // Banner
  const bannerCheck = el('input', { type: 'checkbox' });
  const bannerPreview = el('img', {
    class: 'style-banner',
    src: currentBanner || '',
    alt: '',
    style: currentBanner ? 'width: 100%; max-height: 90px; object-fit: cover; border-radius: var(--radius-sm);' : 'display:none;',
  });
  const bannerFile = el('input', {
    type: 'file', accept: 'image/png,image/jpeg,image/gif,image/webp', style: 'display:none',
  });
  const bannerUploadBtn = el('button', {
    type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => bannerFile.click(),
  }, 'Subir imagen');
  const bannerRemoveBtn = el('button', {
    type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => {
      bannerUrl = null;
      bannerPreview.style.display = 'none';
      bannerCheck.checked = true;
      editBanner = true;
    },
  }, 'Quitar');

  const bannerControls = el('div', { style: 'display:flex;flex-direction:column;gap:8px;' },
    bannerPreview,
    el('div', { style: 'display:flex;gap:6px;align-items:center;' }, bannerUploadBtn, bannerRemoveBtn),
    bannerFile
  );

  bannerFile.onchange = async () => {
    const file = bannerFile.files[0];
    if (!file) return;
    bannerUploadBtn.disabled = true;
    bannerUploadBtn.textContent = 'Subiendo…';
    try {
      const url = await uploadImageBlob(file);
      bannerUrl = url;
      bannerPreview.src = url;
      bannerPreview.style.display = 'block';
      bannerCheck.checked = true;
      editBanner = true;
      toast('Banner subido', 'ok');
    } catch (e) {
      toast(e.message || 'No se pudo subir la imagen', 'err');
    } finally {
      bannerUploadBtn.disabled = false;
      bannerUploadBtn.textContent = 'Subir imagen';
    }
  };

  bannerCheck.onchange = () => { editBanner = bannerCheck.checked; };

  let modal = null;
  const saveBtn = el('button', {
    type: 'button',
    class: 'btn btn-primary',
    onclick: async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Guardando…';
      try {
        const body = { nick: nickInput.value.trim() };
        if (editAvatar) body.avatar_url = avatarUrl;
        if (editBanner) body.banner_url = bannerUrl;

        const res = await apiFetch(`/api/server/${GUILD_ID}/style`, {
          method: 'PUT',
          body,
        });
        toast('Apariencia de Purgito actualizada', 'ok');
        if (res && res.warning) toast(res.warning, 'warn');
        if (modal) modal.remove();
        if (currentTab() === 'inicio') loadInicio();
        else if (currentTab() === 'estilo') loadEstiloModule();
      } catch (e) {
        toast(e.message || 'No se pudo guardar la apariencia', 'err');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Guardar';
      }
    },
  }, 'Guardar');

  const cancelBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary',
    onclick: () => { if (modal) modal.remove(); },
  }, 'Cancelar');

  const modalBody = el('div', { class: 'style-modal' },
    formGroup(el('span', {}, 'Apodo en este servidor', nickCounter),
      el('p', { class: 'dim' }, 'Nombre con el que aparece Purgito en este servidor.'),
      nickInput
    ),
    formGroup(el('label', { class: 'toggle' }, avatarCheck, 'Modificar avatar'),
      el('p', { class: 'dim' }, 'Avatar exclusivo para este servidor.'),
      avatarControls
    ),
    formGroup(el('label', { class: 'toggle' }, bannerCheck, 'Modificar banner'),
      el('p', { class: 'dim' }, 'Banner del perfil de Purgito en este servidor.'),
      bannerControls
    ),
    el('div', { class: 'style-modal-actions' }, cancelBtn, saveBtn)
  );

  modal = panelModal('Editar apariencia en este servidor', modalBody);
}

async function loadEstiloModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const style = await apiFetch(`/api/server/${GUILD_ID}/style`);
    if (!box) return;
    box.innerHTML = '';

    const avatar = (style && (style.avatar_url || style.current_avatar_url)) || null;
    const nick = (style && (style.nick || style.current_nick)) || 'Purgito';

    box.append(
      formGroup('Personalización de Purgito',
        el('p', { class: 'dim' }, 'Modifica cómo se presenta Purgito exclusivamente en este servidor (apodo, avatar y banner de perfil).'),
        el('div', { class: 'style-card' },
          el('div', { class: 'style-preview' },
            avatar ? el('img', { class: 'style-avatar', src: avatar, alt: '' }) : null,
            el('div', {},
              el('div', { class: 'style-nick' }, nick, el('span', { class: 'dm-badge' }, 'BOT')),
              el('div', { class: 'dim' }, 'Vista previa del bot en este servidor')
            )
          ),
          el('button', {
            class: 'btn btn-primary',
            onclick: () => openStyleModal(style || {}),
          }, 'Editar apariencia')
        )
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

async function loadPlaygroundModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const [channelsRes, styleRes] = await Promise.allSettled([
      getChannels({ force: true }),
      apiFetch(`/api/server/${GUILD_ID}/style`),
    ]);

    if (!box) return;
    box.innerHTML = '';

    const allChannels = channelsRes.status === 'fulfilled' && Array.isArray(channelsRes.value) ? channelsRes.value : [];
    const style = styleRes.status === 'fulfilled' ? (styleRes.value || {}) : {};

    // Filtrar únicamente canales donde Purgito puede operar en el simulador
    const usableChannels = allChannels.filter(c => c && c.can_use_simulator !== false && c.can_send !== false && c.can_view !== false);

    // Estado vacío si no hay canales con permisos suficientes
    if (!usableChannels.length) {
      box.append(
        formGroup('Simulador de Chat',
          el('p', { class: 'dim' },
            'Prueba la generación de respuestas en tiempo real con las reglas, triggers y corpus del canal seleccionado. Esta simulación es segura: no envía ningún mensaje a Discord ni consume cupos.'
          ),
          el('div', { class: 'sim-empty-state' },
            el('div', { class: 'sim-empty-state-icon' }, icon('lock')),
            el('h3', { class: 'sim-empty-state-title' }, 'No hay canales disponibles para usar el simulador'),
            el('p', { class: 'sim-empty-state-desc' },
              'Purgito necesita permisos de "Ver canal" y "Enviar mensajes" en Discord para poder evaluar el contexto y simular respuestas. Configura los roles del bot en los canales de texto de tu servidor para comenzar.'
            )
          )
        )
      );
      return;
    }

    let selectedChannelId = usableChannels[0].id;
    let isSubmitting = false;

    const container = el('div', { class: 'sim-container' });

    // Step 1: Canal de contexto
    const channelPicker = buildPlaygroundChannelPicker(usableChannels, selectedChannelId, (newId) => {
      selectedChannelId = newId;
    });

    const step1Card = el('div', { class: 'sim-step-card' },
      el('div', { class: 'sim-step-header' },
        el('div', { class: 'sim-step-badge' }, '1'),
        el('div', { class: 'sim-step-title-group' },
          el('h3', { class: 'sim-step-title' }, 'Canal de contexto'),
          el('p', { class: 'sim-step-desc' }, 'Selecciona un canal donde Purgito tenga permisos de lectura y respuesta.')
        )
      ),
      channelPicker
    );

    // Step 2: Mensaje de entrada
    const textarea = el('textarea', {
      class: 'sim-textarea',
      rows: '3',
      placeholder: 'Escribe un mensaje de prueba para Purgito (ej.: Hola bot, ¿qué opinas de este servidor?)',
      maxlength: '4000',
    });

    const step2Card = el('div', { class: 'sim-step-card' },
      el('div', { class: 'sim-step-header' },
        el('div', { class: 'sim-step-badge' }, '2'),
        el('div', { class: 'sim-step-title-group' },
          el('h3', { class: 'sim-step-title' }, 'Mensaje de entrada'),
          el('p', { class: 'sim-step-desc' }, 'Escribe el mensaje que simulará haber enviado un usuario en el canal seleccionado.')
        )
      ),
      textarea
    );

    // Result container
    const resultBox = el('div', { class: 'sim-result-section' });

    // Action button
    const submitBtn = el('button', {
      type: 'button',
      class: 'btn btn-primary sim-submit-btn',
      onclick: async () => {
        if (isSubmitting) return;
        const msg = textarea.value.trim();
        if (!selectedChannelId) {
          toast('Por favor selecciona un canal válido', 'warn');
          return;
        }
        if (!msg) {
          toast('Escribe un mensaje de prueba antes de simular', 'warn');
          textarea.focus();
          return;
        }

        isSubmitting = true;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '';
        submitBtn.append(spinner(), el('span', {}, 'Generando respuesta…'));

        resultBox.innerHTML = '';
        resultBox.append(spinner());

        try {
          const data = await apiFetch(`/api/server/${GUILD_ID}/chat/playground`, {
            method: 'POST',
            body: { channel_id: selectedChannelId, message: msg },
          });
          const targetChan = usableChannels.find(c => String(c.id) === String(selectedChannelId)) || { name: 'canal' };
          renderPlaygroundResult(resultBox, data, targetChan, style);
        } catch (err) {
          resultBox.innerHTML = '';
          let errText = 'No fue posible simular la respuesta.';
          if (err && err.status === 403) {
            errText = 'Purgito ya no tiene acceso a este canal o carece de permisos para ver y enviar mensajes.';
          } else if (err && err.status === 400) {
            errText = (err.data && err.data.error) || 'El canal o mensaje de prueba no son válidos.';
          } else if (err && err.status === 429) {
            errText = 'Has realizado demasiadas simulaciones consecutivas. Espera unos momentos antes de intentar nuevamente.';
          }
          resultBox.append(el('div', { class: 'sim-no-response-box' },
            icon('alertTriangle'),
            el('div', {},
              el('strong', {}, 'Error al simular: '),
              el('span', {}, errText)
            )
          ));
        } finally {
          isSubmitting = false;
          submitBtn.disabled = false;
          submitBtn.innerHTML = '';
          submitBtn.append(icon('play'), el('span', {}, 'Simular respuesta'));
        }
      },
    }, icon('play'), el('span', {}, 'Simular respuesta'));

    const actionRow = el('div', { class: 'sim-action-row' },
      submitBtn,
      el('span', { class: 'sim-hint' }, 'El mensaje se evaluará contra las reglas del canal sin enviarse a Discord.')
    );

    container.append(step1Card, step2Card, actionRow, resultBox);

    box.append(
      formGroup('Simulador de Chat',
        el('p', { class: 'dim' },
          'Prueba la generación de respuestas en tiempo real con las reglas, triggers y corpus del canal seleccionado. Esta simulación es segura: no envía ningún mensaje a Discord ni consume cupos.'
        ),
        container
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

async function loadUpdatesModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const [updates, channels] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/updates`),
      getChannels({ force: true }),
    ]);
    if (!box) return;
    box.innerHTML = '';

    const sel = channelSelect(channels, updates ? updates.channel_id : null, 'Sin canal — no publicar');
    sel.onchange = async () => {
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/updates`, {
          method: 'PUT', body: { channel_id: sel.value || null },
        });
        toast(sel.value ? 'Canal de actualizaciones guardado' : 'Canal de actualizaciones quitado', 'ok');
      } catch (e) { toast('No se pudo guardar el canal, intenta de nuevo', 'err'); }
    };

    box.append(
      formGroup('Canal de Novedades y Actualizaciones',
        el('p', { class: 'dim' }, 'Elige el canal donde Purgito publicará avisos de novedades, notas de versiones y anuncios importantes.'),
        el('div', { class: 'updates-row' },
          el('div', { class: 'updates-info' },
            el('p', { class: 'dim' }, 'Canal configurado actualmente en este servidor:')
          ),
          el('div', { class: 'updates-control' }, sel)
        )
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

async function loadTriggersModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const [triggers, channels, frasePacks] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/triggers`),
      getChannels(),
      apiFetch(`/api/server/${GUILD_ID}/frases/packs`),
    ]);
    if (!box) return;
    box.innerHTML = '';

    const triggersBox = el('div', {});
    const packsList = (frasePacks && frasePacks.packs) || [];
    renderTriggers(triggersBox, triggers, channels || [], packsList);

    box.append(
      formGroup('Triggers de canal',
        el('p', { class: 'dim' },
          'Si un mensaje recibido coincide con el patrón configurado, Purgito responderá automáticamente sin esperar una mención.'
        ),
        triggersBox
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

async function loadReaccionesModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const [chat, reactions] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/chat`),
      apiFetch(`/api/server/${GUILD_ID}/settings/reacciones`),
    ]);
    if (!box) return;
    box.innerHTML = '';

    const reaccionesBox = el('div', {});
    const reactionsList = (reactions && reactions.reactions) || (Array.isArray(reactions) ? reactions : []);
    renderReacciones(reaccionesBox, reactionsList);

    box.append(
      formGroup('Reacciones automáticas',
        el('p', { class: 'dim' }, 'Configura la probabilidad y la colección de emojis con los que Purgito puede reaccionar a los mensajes del chat.'),
        probabilityField('Probabilidad de reaccionar con un emoji', null, {
          key: 'reaction_probability',
          value: chat ? chat.reaction_probability : 0,
        }),
        el('div', { class: 'field' },
          el('label', {}, 'Colección de emojis'),
          reaccionesBox
        )
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

async function loadFrasesModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const [frases, frasePacks, channels, fraseChannels] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/frases`),
      apiFetch(`/api/server/${GUILD_ID}/frases/packs`),
      getChannels(),
      apiFetch(`/api/server/${GUILD_ID}/settings/frases/channels`),
    ]);
    if (!box) return;
    box.innerHTML = '';

    const frasesList = (frases && frases.frases) || (Array.isArray(frases) ? frases : []);
    const packsList = (frasePacks && frasePacks.packs) || [];
    const frasesBox = el('div', {});
    renderFrases(frasesBox, frasesList, packsList, frases ? frases.limit : null);

    const packsBox = el('div', {});
    renderFrasePacks(packsBox, packsList, channels || [], frasesBox, frasePacks ? frasePacks.limit : null);

    const fraseChannelsSelected = new Set(((fraseChannels && fraseChannels.channels) || []).map(c => c.id));
    const TAGS = ['{{user.mention}}', '{{user.name}}', '{{channel.name}}',
      '{{channel.mention}}', '{{guild.name}}', '{{markov.word}}', '{{markov.sentence}}'];

    box.append(
      formGroup('Frases especiales',
        el('p', { class: 'dim' }, 'Frases predefinidas que Purgito puede intercalar en sus respuestas o mediante triggers.'),
        frasesBox,
        accordionGroup('Variables dinámicas disponibles en frases', false,
          el('div', { class: 'tag-list' },
            TAGS.map(t => el('code', { class: 'cmd' }, t))
          )
        )
      ),
      formGroup('Paquetes de frases (Packs)',
        el('p', { class: 'dim' }, 'Agrupa frases temáticas para asignarlas a canales específicos o dispararlas mediante triggers.'),
        packsBox
      ),
      accordionGroup('Canales donde pueden salir frases especiales generales', false,
        channelToggleList({
          channels: channels || [],
          isSelected: id => fraseChannelsSelected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/channels`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            fraseChannelsSelected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/channels/${ch.id}`, {
              method: 'DELETE',
            });
            fraseChannelsSelected.delete(ch.id);
          },
          listBelow: 'Sin canales específicos seleccionados: pueden salir en cualquiera.',
        })
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

async function loadCanalesModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const [spontaneousChans, mentionChans, corpus, exempt, exemptChans, channels, roles] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels`),
      apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels`),
      apiFetch(`/api/server/${GUILD_ID}/settings/corpus`),
      apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles`),
      apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels`),
      getChannels({ force: true }),
      getRoles(),
    ]);
    if (!box) return;
    box.innerHTML = '';

    const spontaneousSelected = new Set(((spontaneousChans && spontaneousChans.channels) || []).map(c => c.id));
    const mentionSelected = new Set(((mentionChans && mentionChans.channels) || []).map(c => c.id));
    const corpusSelected = new Set(((corpus && corpus.channels) || []).map(c => c.id));
    const ignoredSet = new Set((corpus && corpus.ignored) || []);

    const cols = [
      {
        short: 'Habla', onLabel: 'habla por su cuenta acá', offLabel: 'ya no habla solo acá',
        help: 'Purgito puede arrancar una charla por su cuenta en este canal. Sin ningún canal marcado, puede hacerlo en todos.',
        isSelected: id => spontaneousSelected.has(id),
        add: async ch => {
          await apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels`, {
            method: 'POST', body: { channel_id: ch.id },
          });
          spontaneousSelected.add(ch.id);
        },
        remove: async ch => {
          await apiFetch(`/api/server/${GUILD_ID}/settings/spontaneous-channels/${ch.id}`, { method: 'DELETE' });
          spontaneousSelected.delete(ch.id);
        },
      },
      {
        short: 'Responde', onLabel: 'responde menciones acá', offLabel: 'ya no responde menciones acá',
        help: 'Purgito contesta cuando lo mencionan en este canal. Sin ningún canal marcado, responde en todos.',
        isSelected: id => mentionSelected.has(id),
        add: async ch => {
          await apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels`, {
            method: 'POST', body: { channel_id: ch.id },
          });
          mentionSelected.add(ch.id);
        },
        remove: async ch => {
          await apiFetch(`/api/server/${GUILD_ID}/settings/mention-channels/${ch.id}`, { method: 'DELETE' });
          mentionSelected.delete(ch.id);
        },
      },
      {
        short: 'Aprende', onLabel: 'aprende de acá', offLabel: 'ya no aprende de acá',
        help: 'Purgito guarda los mensajes de este canal para armar su estilo. Sin ningún canal marcado, no aprende de nada.',
        isSelected: id => corpusSelected.has(id),
        add: async ch => {
          await apiFetch(`/api/server/${GUILD_ID}/settings/corpus`, {
            method: 'POST', body: { channel_id: ch.id },
          });
          corpusSelected.add(ch.id);
        },
        remove: async ch => {
          await apiFetch(`/api/server/${GUILD_ID}/settings/corpus/${ch.id}`, { method: 'DELETE' });
          corpusSelected.delete(ch.id);
        },
      },
    ];

    async function openOverrides(ch, panel) {
      const data = await apiFetch(`/api/guilds/${GUILD_ID}/channels/${ch.id}/settings`);
      const eff = (data && data.effective) || {}, ov = (data && data.overrides) || {}, lim2 = (data && data.limits) || {};
      const rng = (k, d) => lim2[k] || d;
      panel.innerHTML = '';
      panel.append(
        el('div', { class: 'ovr-grid' },
          channelOverrideRow(ch.id, {
            key: 'auto_generate_every', label: 'Cada cuántos mensajes', kind: 'number',
            effective: eff.auto_generate_every, override: ov.auto_generate_every,
            min: rng('auto_generate_every', [1])[0], max: rng('auto_generate_every', [null, 1000])[1],
            suffix: 'mensajes',
          }),
          channelOverrideRow(ch.id, {
            key: 'auto_generate_probability', label: 'Probabilidad de hablar', kind: 'percent',
            effective: eff.auto_generate_probability, override: ov.auto_generate_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'gif_response_probability', label: 'Responde con GIF', kind: 'percent',
            effective: eff.gif_response_probability, override: ov.gif_response_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'frase_probability', label: 'Usa una frase especial', kind: 'percent',
            effective: eff.frase_probability, override: ov.frase_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'reaction_probability', label: 'Reacciona con emoji', kind: 'percent',
            effective: eff.reaction_probability, override: ov.reaction_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'mention_rate_limit', label: 'Menciones por hora', kind: 'number',
            effective: eff.mention_rate_limit, override: ov.mention_rate_limit,
            min: rng('mention_rate_limit', [0])[0], max: rng('mention_rate_limit', [null, 1000])[1],
            suffix: 'por usuario',
          })
        )
      );
    }

    const matrixNode = channelMatrix({ channels: channels || [], cols, openOverrides });

    const exemptSelected = new Set(((exempt && exempt.roles) || []).map(r => r.id));
    const exemptChannelsSelected = new Set(((exemptChans && exemptChans.channels) || []).map(c => c.id));

    box.append(
      formGroup('Matriz de canales',
        ignoredSet.size
          ? el('p', { class: 'dim' }, ignoredSet.size === 1
            ? 'Hay 1 canal silenciado desde /settings: queda fuera aunque lo marques acá.'
            : `Hay ${ignoredSet.size} canales silenciados desde /settings: quedan fuera aunque los marques acá.`)
          : null,
        matrixNode
      ),
      formGroup('Exenciones de límites',
        el('div', { class: 'field' },
          el('label', {}, 'Roles exentos de límites de menciones'),
          roleToggleList({
            roles,
            selected: exemptSelected,
            add: async role => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles`, {
                method: 'POST', body: { role_id: role.id },
              });
              exemptSelected.add(role.id);
            },
            remove: async role => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles/${role.id}`, {
                method: 'DELETE',
              });
              exemptSelected.delete(role.id);
            },
            listBelow: 'Ningún rol exento: el límite aplica a todos por igual.',
          })
        ),
        el('div', { class: 'field' },
          el('label', {}, 'Canales exentos de límites de menciones'),
          channelToggleList({
            channels,
            isSelected: id => exemptChannelsSelected.has(id),
            add: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels`, {
                method: 'POST', body: { channel_id: ch.id },
              });
              exemptChannelsSelected.add(ch.id);
            },
            remove: async ch => {
              await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels/${ch.id}`, {
                method: 'DELETE',
              });
              exemptChannelsSelected.delete(ch.id);
            },
            listBelow: 'Ningún canal exento: el límite aplica en todos.',
          })
        )
      )
    );
  } catch (e) { renderError(box, e); }
}

async function loadCorpusModule() {
  const box = content();
  box.append(spinner());
  try {
    const channels = await getChannels();
    box.innerHTML = '';

    box.append(
      formGroup('Importar corpus desde un archivo',
        el('p', { class: 'dim' },
          'Sube un archivo .txt con mensajes de texto plano. Cada línea no vacía entra al corpus del canal elegido como si fuera un mensaje real.'
        ),
        corpusImportForm(channels)
      )
    );
  } catch (e) { renderError(box, e); }
}

async function loadAmnesiaModule() {
  const box = content();
  box.innerHTML = '';
  box.append(
    formGroup('Limpieza de memoria reciente',
      el('p', { class: 'dim' },
        'Borra el corpus (mensajes aprendidos y estilo por usuario) de las últimas 24 horas de todo el servidor. Esta acción es irreversible.'
      ),
      amnesiaButton()
    )
  );
}

// ---------------- CONFIGURACIÓN DEL CHAT (SUBTABS) ----------------

function channelToggleList({ channels, selected, isSelected, add, remove, listBelow }) {
  const wrap = el('div', { class: 'chan-picker' });
  const panel = el('div', { class: 'dd-panel chan-panel' });
  const btn = el('button', { class: 'dd-trigger' },
    'Seleccionar canales…', el('span', { class: 'dd-caret' }, '▾'));
  const dd = el('div', { class: 'dd' }, btn, panel);
  btn.onclick = (e) => { e.stopPropagation(); dd.classList.toggle('open'); };
  const list = el('div', { class: 'chan-chips' });

  let busy = false;
  async function toggle(ch) {
    if (busy) return;
    busy = true;
    try {
      if (isSelected(ch.id)) {
        await remove(ch);
        toast('Se ha quitado el canal', 'ok');
      } else {
        await add(ch);
        toast('Se ha agregado el canal', 'ok');
      }
    } catch (e) {
      toast(isSelected(ch.id)
        ? 'No se pudo quitar el canal, intenta de nuevo'
        : 'No se pudo agregar el canal, intenta de nuevo', 'err');
    }
    busy = false;
    render();
  }

  function chanLabel(ch) {
    return el('span', { class: 'chan-name' + (ch.can_send === false ? ' chan-noperm' : '') },
      '#' + (ch.name || ch.id),
      ch.can_send === false
        ? el('span', { class: 'chan-warn', title: 'El bot no puede leer o escribir en este canal' }, '⚠')
        : null);
  }

  function render() {
    panel.innerHTML = '';
    for (const ch of channels) {
      panel.append(el('button', {
        class: 'dd-item chan-option' + (isSelected(ch.id) ? ' active' : ''),
        onclick: (e) => { e.stopPropagation(); toggle(ch); },
      }, chanLabel(ch), isSelected(ch.id) ? el('span', { class: 'chan-check' }, '✓') : null));
    }
    list.innerHTML = '';
    const sel = channels.filter(c => isSelected(c.id));
    if (!sel.length) {
      list.append(el('span', { class: 'dim' }, listBelow));
    }
    for (const ch of sel) {
      list.append(el('span', { class: 'chan-chip' },
        chanLabel(ch),
        el('button', {
          class: 'chan-chip-x', 'aria-label': `Quitar #${ch.name || ch.id}`, onclick: () => toggle(ch),
        }, '✕')));
    }
  }
  render();
  wrap.append(dd, list);
  return wrap;
}

function corpusImportForm(channels) {
  const chanSel = channelSelect(channels, null, 'Elige un canal…');
  const fileInput = el('input', { type: 'file', accept: '.txt,text/plain' });
  const resultBox = el('div', {});
  const btn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      const file = fileInput.files[0];
      if (!chanSel.value || !file) {
        toast('Elige un canal y un archivo .txt', 'warn');
        return;
      }
      resultBox.innerHTML = '';
      resultBox.append(spinner());
      let r, data;
      try {
        r = await fetch(`/api/server/${GUILD_ID}/settings/corpus/import/${chanSel.value}`, {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/octet-stream' },
          body: file,
        });
        data = await r.json().catch(() => ({}));
      } catch (e) {
        resultBox.innerHTML = '';
        toast('No se pudo conectar con el servidor', 'err');
        return;
      }
      resultBox.innerHTML = '';
      if (!r.ok) {
        toast(data.error || humanError(r.status), r.status === 429 ? 'warn' : 'err');
        return;
      }
      toast(`${data.imported} mensajes importados`, 'ok');
      fileInput.value = '';
    },
  }, 'Importar');

  return el('div', {},
    el('div', { class: 'add-row' }, chanSel, fileInput, btn),
    resultBox);
}

function amnesiaButton() {
  const wrap = el('div', {});

  function showButton() {
    wrap.innerHTML = '';
    wrap.append(el('button', {
      class: 'btn btn-danger', onclick: showConfirm,
    }, 'Borrar corpus de las últimas 24h'));
  }

  function showConfirm() {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'gif-confirm' },
      'Esto borra mensajes y estilo por usuario de las últimas 24 horas y no se puede deshacer. ¿Seguro?',
      el('button', { class: 'btn btn-danger btn-sm', onclick: doAmnesia }, '✓ Sí, borrar'),
      el('button', { class: 'btn btn-secondary btn-sm', onclick: showButton }, '✗ Cancelar')));
  }

  async function doAmnesia() {
    try {
      const data = await apiFetch(`/api/server/${GUILD_ID}/settings/corpus/amnesia`, {
        method: 'POST',
      });
      toast(
        `Borrados ${data.deleted.corpus_messages} mensajes y ${data.deleted.user_corpus} de estilo por usuario`,
        'ok',
      );
    } catch (e) {
      toast('No se pudo borrar el corpus reciente, intenta de nuevo', 'err');
    }
    showButton();
  }

  showButton();
  return wrap;
}

function debounce(fn, delayMs) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

const TUNABLE_SAVE_DEBOUNCE_MS = 500;

async function saveTunable(key, value, label, onSaved) {
  try {
    const r = await apiFetch(`/api/server/${GUILD_ID}/settings/chat/tunables`, {
      method: 'PUT', body: { [key]: value },
    });
    if (onSaved && r.saved && r.saved[key] !== undefined) onSaved(r.saved[key]);
    toast(`${label} actualizado`, 'ok');
  } catch (e) {
    toast(`No se pudo guardar ${label.toLowerCase()}, intenta de nuevo`, 'err');
  }
}

function numberField(label, help, { key, value, min, max, step, suffix, save = saveTunable }) {
  const input = el('input', {
    type: 'number', value: String(value), min: String(min),
    max: String(max), step: String(step || 1), class: 'num-input',
  });
  input.onchange = debounce(() => {
    save(key, Number(input.value), label, (saved) => {
      input.value = String(saved);
    });
  }, TUNABLE_SAVE_DEBOUNCE_MS);
  return el('div', { class: 'field' },
    el('label', {}, label),
    el('div', { class: 'num-row' }, input, suffix ? el('span', { class: 'dim' }, suffix) : null),
    help ? el('p', { class: 'dim' }, help) : null);
}

function probabilityField(label, help, { key, value, save = saveTunable }) {
  const pct = Math.round(value * 100);
  const input = el('input', {
    type: 'number', min: '0', max: '100', step: '1', value: String(pct), class: 'num-input',
  });
  const bar = el('progress', { class: 'prob-bar', value: String(pct), max: '100' });
  input.onchange = debounce(() => {
    const clamped = Math.max(0, Math.min(100, Number(input.value) || 0));
    save(key, clamped / 100, label, (saved) => {
      const back = Math.round(saved * 100);
      input.value = String(back);
      bar.value = back;
    });
  }, TUNABLE_SAVE_DEBOUNCE_MS);
  return el('div', { class: 'field' },
    el('label', {}, label),
    el('div', { class: 'prob-row' }, input, el('span', { class: 'dim' }, '%')),
    bar,
    help ? el('p', { class: 'dim' }, help) : null);
}

function channelOverrideRow(channelId, spec) {
  const { key, label, help, kind, effective, min, max, suffix } = spec;
  let override = spec.override;

  const toInput = v => (kind === 'percent' ? Math.round(v * 100) : v);
  const toApi = v => (kind === 'percent' ? v / 100 : v);

  const input = el('input', {
    type: 'number', class: 'num-input',
    min: String(kind === 'percent' ? 0 : min), max: String(kind === 'percent' ? 100 : max),
    step: '1',
  });
  const reset = el('button', {
    class: 'ovr-reset', title: 'Volver al valor del servidor', 'aria-label': 'Volver al valor del servidor',
    onclick: () => save(null),
  }, '↺');
  const caption = el('span', { class: 'dim ovr-caption' });
  const row = el('div', { class: 'ovr-row' },
    el('label', {}, label, help ? helpIcon(help) : null),
    el('div', { class: 'ovr-control' },
      input,
      suffix ? el('span', { class: 'dim ovr-suffix' }, suffix) : null,
      reset),
    caption);

  const fmt = v => {
    const n = toInput(v);
    if (!suffix) return String(n);
    return kind === 'percent' ? `${n}${suffix}` : `${n} ${suffix}`;
  };

  function paint() {
    const inherited = override === null || override === undefined;
    input.value = String(toInput(inherited ? effective : override));
    row.classList.toggle('is-override', !inherited);
    reset.hidden = inherited;
    caption.textContent = inherited
      ? `${fmt(effective)} · valor del servidor`
      : 'valor propio de este canal';
  }

  async function save(raw) {
    const prev = override;
    try {
      const r = await apiFetch(`/api/guilds/${GUILD_ID}/channels/${channelId}/settings`, {
        method: 'PUT', body: { [key]: raw === null ? null : toApi(raw) },
      });
      override = raw === null ? null : r.saved[key];
      paint();
      toast(raw === null ? `${label}: vuelve al valor del servidor` : `${label} actualizado en este canal`, 'ok');
    } catch (e) {
      override = prev;
      paint();
      toast(`No se pudo guardar ${label.toLowerCase()}, intenta de nuevo`, 'err');
    }
  }

  input.onchange = debounce(() => {
    const lo = kind === 'percent' ? 0 : min;
    const hi = kind === 'percent' ? 100 : max;
    save(Math.max(lo, Math.min(hi, Number(input.value) || 0)));
  }, TUNABLE_SAVE_DEBOUNCE_MS);

  paint();
  return row;
}

function roleToggleList({ roles, selected, add, remove, listBelow }) {
  const panel = el('div', { class: 'dd-panel chan-panel' });
  const btn = el('button', { class: 'dd-trigger' },
    'Seleccionar roles…', el('span', { class: 'dd-caret' }, '▾'));
  const dd = el('div', { class: 'dd' }, btn, panel);
  btn.onclick = (e) => { e.stopPropagation(); dd.classList.toggle('open'); };
  const list = el('div', { class: 'chan-chips' });

  let busy = false;
  async function toggle(role) {
    if (busy) return;
    busy = true;
    const had = selected.has(role.id);
    try {
      if (had) { await remove(role); toast('Rol quitado', 'ok'); }
      else { await add(role); toast('Rol agregado', 'ok'); }
    } catch (e) {
      toast(had ? 'No se pudo quitar el rol' : 'No se pudo agregar el rol', 'err');
    }
    busy = false;
    render();
  }

  function roleLabel(role) {
    return el('span', { class: 'role-name' },
      el('span', {
        class: 'role-dot',
        style: `background:${role.color && role.color !== '#000000' ? role.color : 'currentColor'}`,
      }),
      '@' + role.name);
  }

  function render() {
    panel.innerHTML = '';
    for (const role of roles) {
      panel.append(el('button', {
        class: 'dd-item chan-option' + (selected.has(role.id) ? ' active' : ''),
        onclick: (e) => { e.stopPropagation(); toggle(role); },
      }, roleLabel(role), selected.has(role.id) ? el('span', { class: 'chan-check' }, '✓') : null));
    }
    list.innerHTML = '';
    const sel = roles.filter(r => selected.has(r.id));
    if (!sel.length) list.append(el('span', { class: 'dim' }, listBelow));
    for (const role of sel) {
      list.append(el('span', { class: 'chan-chip' },
        roleLabel(role),
        el('button', {
          class: 'chan-chip-x', 'aria-label': `Quitar @${role.name}`, onclick: () => toggle(role),
        }, '✕')));
    }
  }
  render();
  return el('div', { class: 'chan-picker' }, dd, list);
}

function channelMatrix({ channels, cols, openOverrides }) {
  const wrap = el('div', { class: 'chan-matrix' });
  const filter = el('input', {
    type: 'search', placeholder: 'Filtrar canales…', class: 'chan-filter', autocomplete: 'off',
  });
  const body = el('div', { class: 'chan-matrix-body' });

  const head = el('div', { class: 'chan-matrix-head' },
    el('span', {}, 'Canal'),
    ...cols.map(c => el('span', { class: 'chan-matrix-col' }, c.short, helpIcon(c.help))),
    el('span', { class: 'chan-matrix-col' }, 'Ajustes'));

  function rowFor(ch) {
    const row = el('div', { class: 'chan-matrix-row' });
    const panel = el('div', { class: 'chan-matrix-panel' });
    panel.hidden = true;
    let loaded = false;

    const gear = el('button', {
      class: 'chan-gear', title: `Ajustes de #${ch.name}`, 'aria-label': `Ajustes de #${ch.name}`,
      onclick: async () => {
        panel.hidden = !panel.hidden;
        row.classList.toggle('open', !panel.hidden);
        if (panel.hidden || loaded) return;
        loaded = true;
        panel.append(spinner());
        try { await openOverrides(ch, panel); } catch (e) { renderError(panel, e); }
      },
    }, '⚙');

    row.append(
      el('span', { class: 'chan-name' + (ch.can_send === false ? ' chan-noperm' : '') },
        '#' + (ch.name || ch.id),
        ch.can_send === false
          ? el('span', { class: 'chan-warn', title: 'El bot no puede leer o escribir en este canal' }, '⚠')
          : null),
      ...cols.map((c) => {
        const box = el('input', { type: 'checkbox', checked: c.isSelected(ch.id) });
        box.onchange = async () => {
          const on = box.checked;
          try {
            if (on) await c.add(ch); else await c.remove(ch);
            toast(`#${ch.name}: ${on ? c.onLabel : c.offLabel}`, 'ok');
          } catch (e) {
            box.checked = !on;
            toast('No se pudo guardar, intenta de nuevo', 'err');
          }
        };
        return el('label', { class: 'chan-matrix-cell', title: c.short }, box);
      }),
      el('span', { class: 'chan-matrix-cell' }, gear));
    return el('div', { class: 'chan-matrix-item' }, row, panel);
  }

  const items = channels.map(ch => ({ ch, node: rowFor(ch) }));
  for (const it of items) body.append(it.node);
  filter.oninput = () => {
    const q = filter.value.trim().toLowerCase();
    for (const it of items) it.node.hidden = q && !(it.ch.name || '').toLowerCase().includes(q);
  };

  wrap.append(filter, head, body);
  return wrap;
}

async function loadChatTab() {
  // Manejo de compatibilidad con hashes antiguos (#reacciones, #contenido, etc.)
  const hash = location.hash.slice(1);
  if (hash === 'reacciones') { activate('reacciones', true); return; }
  if (hash === 'contenido' || hash === 'frases') { activate('frases', true); return; }
  if (hash === 'triggers') { activate('triggers', true); return; }
  if (hash === 'canales') { activate('canales', true); return; }
  if (hash === 'datos' || hash === 'corpus') { activate('corpus', true); return; }
  if (hash === 'amnesia') { activate('amnesia', true); return; }
  if (hash === 'playground') { activate('playground', true); return; }

  const box = content();
  box.append(spinner());
  const epoch = _loadEpoch;

  try {
    const [chat, exempt, exemptChans, channels, roles] =
      await Promise.all([
        apiFetch(`/api/server/${GUILD_ID}/settings/chat`),
        apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles`),
        apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels`),
        getChannels({ force: true }),
        getRoles(),
      ]);

    if (epoch !== _loadEpoch) return;
    box.innerHTML = '';
    const lim = chat.limits || {};

    const check = el('input', { type: 'checkbox', checked: chat.enabled });
    check.onchange = async () => {
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/chat`, {
          method: 'PUT', body: { enabled: check.checked },
        });
        toast(check.checked ? 'Chat activado' : 'Chat desactivado', 'ok');
      } catch (e) {
        check.checked = !check.checked;
        toast('No se pudo guardar, intenta de nuevo', 'err');
      }
    };
    box.append(el('div', { class: 'chat-master' },
      el('label', { class: 'toggle' }, check, 'Chat activado'),
      helpIcon('Apaga las respuestas a menciones. Los mensajes espontáneos, las reacciones y los triggers no dependen de este switch.')));

    // Cadena de comportamiento
    const comportamientoSection = formGroup('Comportamiento y probabilidades',
      el('p', { class: 'dim' }, 'Define cómo y cuándo participa Purgito en las conversaciones de este servidor.'),
      el('div', { class: 'chain' },
        el('div', { class: 'chain-step' },
          el('div', { class: 'chain-step-head' },
            el('span', { class: 'chain-num' }, '1'),
            el('h3', {}, '¿Arranca una charla solo?'),
            helpIcon('Solo para cuando habla por su cuenta (con un piso de silencio de 45 s en el canal para no spamear). Si lo mencionan responde directo, sin pasar por este paso.')),
          el('div', { class: 'chain-fields' },
            numberField('Cada cuántos mensajes nuevos', null, {
              key: 'auto_generate_every',
              value: chat ? chat.auto_generate_every : 20,
              min: (lim.auto_generate_every || [1])[0],
              max: (lim.auto_generate_every || [null, 1000])[1],
              suffix: 'mensajes',
            }),
            probabilityField('Y ahí, cuántas veces habla', null, {
              key: 'auto_generate_probability',
              value: chat ? chat.auto_generate_probability : 30,
            }))),
        el('div', { class: 'chain-step' },
          el('div', { class: 'chain-step-head' },
            el('span', { class: 'chain-num' }, '2'),
            el('h3', {}, '¿Manda un GIF o escribe?'),
            helpIcon('Los GIFs salen de la galería del tab GIFs.')),
          el('div', { class: 'chain-fields' },
            probabilityField('Manda un GIF', null, {
              key: 'gif_response_probability',
              value: chat ? chat.gif_response_probability : 0,
            }))),
        el('div', { class: 'chain-step' },
          el('div', { class: 'chain-step-head' },
            el('span', { class: 'chain-num' }, '3'),
            el('h3', {}, 'Si escribe, ¿frase tuya o inventada?'),
            helpIcon('Las frases se configuran en Frases y Packs. El resto de las veces arma el mensaje solo, con lo que aprendió del servidor.')),
          el('div', { class: 'chain-fields' },
            probabilityField('Usa una frase tuya', null, {
              key: 'frase_probability',
              value: chat ? chat.frase_probability : 0,
            }))),
        el('div', { class: 'chain-step' },
          el('div', { class: 'chain-step-head' },
            el('span', { class: 'chain-num' }, '4'),
            el('h3', {}, '¿Reacciona con un emoji?'),
            helpIcon('Se evalúa en cada mensaje que lee.')),
          el('div', { class: 'chain-fields' },
            probabilityField('Reacciona con un emoji', null, {
              key: 'reaction_probability',
              value: chat ? chat.reaction_probability : 0,
            })))));

    // Límites de actividad
    const exemptSelected = new Set(((exempt && exempt.roles) || []).map(r => r.id));
    const exemptChannelsSelected = new Set(((exemptChans && exemptChans.channels) || []).map(c => c.id));
    const limitesSection = formGroup(el('span', {}, 'Límite de actividad', helpIcon('0 = sin límite.')),
      numberField('Menciones por hora', null, {
        key: 'mention_rate_limit',
        value: chat ? chat.mention_rate_limit : 0,
        min: (lim.mention_rate_limit || [0])[0],
        max: (lim.mention_rate_limit || [null, 1000])[1],
        suffix: 'por usuario',
      }),
      el('div', { class: 'field' },
        el('label', {}, 'Roles exentos del límite'),
        roleToggleList({
          roles: roles || [],
          selected: exemptSelected,
          add: async role => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles`, {
              method: 'POST', body: { role_id: role.id },
            });
            exemptSelected.add(role.id);
          },
          remove: async role => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles/${role.id}`, {
              method: 'DELETE',
            });
            exemptSelected.delete(role.id);
          },
          listBelow: 'Ningún rol exento — el límite aplica a todos por igual.',
        })),
      el('div', { class: 'field' },
        el('label', {}, 'Canales exentos del límite'),
        channelToggleList({
          channels: channels || [],
          isSelected: id => exemptChannelsSelected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            exemptChannelsSelected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels/${ch.id}`, {
              method: 'DELETE',
            });
            exemptChannelsSelected.delete(ch.id);
          },
          listBelow: 'Ningún canal exento — el límite aplica en todos.',
        })));

    // Accesos directos a módulos relacionados
    const toolsSection = formGroup('Herramientas y automatizaciones del chat',
      el('p', { class: 'dim' }, 'Configura las reglas de automatización y los canales de aprendizaje de Purgito.'),
      el('div', { class: 'quick-actions-grid' },
        quickActionCard('zap', 'Triggers de canal', 'Respuestas automáticas ante palabras o regex', () => activate('triggers', true)),
        quickActionCard('smile', 'Reacciones automáticas', 'Colección de emojis para reaccionar', () => activate('reacciones', true)),
        quickActionCard('sparkle', 'Frases y Packs', 'Frases personalizadas agrupadas por canal', () => activate('frases', true)),
        quickActionCard('sliders', 'Canales y Permisos', 'Matriz de lectura, respuesta y overrides', () => activate('canales', true)),
        quickActionCard('play', 'Simulador de Chat', 'Prueba y simula respuestas en vivo', () => activate('playground', true))
      )
    );

    box.append(comportamientoSection, limitesSection, toolsSection);
  } catch (e) { renderError(box, e); }
}

const RECENT_EMOJIS_KEY = 'purgito_recent_emojis';

function getRecentEmojis() {
  try {
    const raw = localStorage.getItem(RECENT_EMOJIS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveRecentEmoji(char) {
  try {
    let list = getRecentEmojis().filter(x => x !== char);
    list.unshift(char);
    if (list.length > 12) list = list.slice(0, 12);
    localStorage.setItem(RECENT_EMOJIS_KEY, JSON.stringify(list));
  } catch (e) { /* sin localStorage no pasa nada */ }
}

function parseEmojiText(text) {
  const match = /^<(a)?:([a-zA-Z0-9_~]+):([0-9]+)>$/.exec(text);
  if (match) {
    const animated = Boolean(match[1]);
    const name = match[2];
    const id = match[3];
    const ext = animated ? 'gif' : 'webp';
    const url = `https://cdn.discordapp.com/emojis/${id}.${ext}?size=48&quality=lossless`;
    return { isCustom: true, name, id, animated, url, raw: text };
  }
  return { isCustom: false, name: text, url: null, raw: text };
}

const COMMON_EMOJIS = [
  '😂', '😭', '💀', '❤️', '🔥', '👀', '🤡', '🙏', '😡', '✨',
  '👍', '🎉', '🤔', '😎', '🥳', '🥺', '💯', '💔', '🤣', '😍',
  '😴', '🤯', '👏', '🙌', '🤮', '🤤', '🤫', '💩',
];

async function renderReacciones(box, pool) {
  box.innerHTML = '';
  const poolList = (pool && Array.isArray(pool.reactions))
    ? pool.reactions
    : (Array.isArray(pool) ? pool : []);
  const poolWrap = el('div', { class: 'emoji-pool-wrap' });
  const poolContainer = el('div', { class: 'emoji-pool' });

  if (!poolList.length) {
    poolContainer.append(el('span', { class: 'dim emoji-pool-empty' }, 'Todavía no hay emojis en la colección.'));
  } else {
    for (const r of poolList) {
      const parsed = parseEmojiText(r.emoji_text);
      if (parsed.isCustom) {
        poolContainer.append(el('span', { class: 'emoji-pool-chip', title: `:${parsed.name}:` },
          el('img', { src: parsed.url, alt: parsed.name, class: 'emoji-chip-img', loading: 'lazy' }),
          el('span', { class: 'emoji-chip-name' }, parsed.name),
          el('button', {
            type: 'button',
            class: 'emoji-chip-x',
            'aria-label': `Quitar :${parsed.name}:`,
            onclick: () => removeReaction(box, r.id),
          }, '✕')
        ));
      } else {
        poolContainer.append(el('span', { class: 'emoji-pool-chip emoji-pool-chip--unicode' },
          el('span', { class: 'emoji-chip-char' }, r.emoji_text),
          el('button', {
            type: 'button',
            class: 'emoji-chip-x',
            'aria-label': `Quitar ${r.emoji_text}`,
            onclick: () => removeReaction(box, r.id),
          }, '✕')
        ));
      }
    }
  }

  const addBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary',
    onclick: () => openAddEmojiModal(box, poolList),
  }, '+ Añadir emoji');

  poolWrap.append(poolContainer, el('div', {}, addBtn));
  box.append(poolWrap);
}

async function addEmojiToPool(box, emojiText, modalOverlay = null) {
  try {
    await apiFetch(`/api/server/${GUILD_ID}/settings/reacciones`, {
      method: 'POST', body: { emoji: emojiText },
    });
    const parsed = parseEmojiText(emojiText);
    if (!parsed.isCustom) {
      saveRecentEmoji(emojiText);
    }
    toast('Emoji agregado', 'ok');
    if (modalOverlay) modalOverlay.remove();
    reloadReacciones(box);
  } catch (e) {
    toast(e.message || 'No se pudo agregar el emoji, intenta de nuevo', 'err');
  }
}

async function removeReaction(box, id, modalOverlay = null) {
  try {
    await apiFetch(`/api/server/${GUILD_ID}/settings/reacciones/${id}`, { method: 'DELETE' });
    toast('Emoji quitado', 'ok');
    if (modalOverlay) modalOverlay.remove();
    reloadReacciones(box);
  } catch (e) {
    toast('No se pudo quitar el emoji, intenta de nuevo', 'err');
  }
}

async function reloadReacciones(box) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/reacciones`);
    renderReacciones(box, data.reactions);
  } catch (e) { /* ignore */ }
}

async function openAddEmojiModal(box, pool) {
  const poolList = (pool && Array.isArray(pool.reactions))
    ? pool.reactions
    : (Array.isArray(pool) ? pool : []);
  const inPool = new Map(poolList.map(r => [r.emoji_text, r.id]));
  const modalBody = el('div', { class: 'emoji-modal-box' });

  let activeTab = 'unicode';
  let customSearchQuery = '';
  let customPage = 1;
  const CUSTOM_PAGE_SIZE = 16;
  let cachedServerEmojis = null;

  const tabBtnUnicode = el('button', {
    type: 'button',
    class: 'emoji-modal-tab active',
    onclick: () => switchTab('unicode'),
  }, 'Unicode');

  const tabBtnServer = el('button', {
    type: 'button',
    class: 'emoji-modal-tab',
    onclick: () => switchTab('server'),
  }, 'Del servidor');

  const tabsHeader = el('div', { class: 'emoji-modal-tabs' }, tabBtnUnicode, tabBtnServer);
  const tabContent = el('div', { class: 'emoji-modal-body' });

  modalBody.append(tabsHeader, tabContent);
  const overlay = panelModal('Añadir emoji', modalBody);

  function switchTab(tab) {
    activeTab = tab;
    tabBtnUnicode.classList.toggle('active', tab === 'unicode');
    tabBtnServer.classList.toggle('active', tab === 'server');
    renderTabContent();
  }

  async function renderTabContent() {
    tabContent.innerHTML = '';

    if (activeTab === 'unicode') {
      const input = el('input', {
        type: 'text',
        placeholder: 'Escribe o pega un emoji (ej. 😭)',
        maxlength: '64',
        autocomplete: 'off',
        class: 'emoji-direct-input',
        onkeydown: (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            const val = input.value.trim();
            if (val) addEmojiToPool(box, val, overlay);
          }
        },
      });

      const addRow = el('div', { class: 'add-row' },
        input,
        el('button', {
          type: 'button',
          class: 'btn btn-primary',
          onclick: () => {
            const val = input.value.trim();
            if (val) addEmojiToPool(box, val, overlay);
          },
        }, 'Agregar')
      );

      const recents = getRecentEmojis();
      let recentsSection = null;
      if (recents.length > 0) {
        const recentGrid = el('div', { class: 'emoji-frequent-grid' });
        for (const ch of recents) {
          recentGrid.append(el('button', {
            type: 'button',
            class: 'emoji-frequent-btn',
            title: ch,
            'aria-label': ch,
            onclick: () => addEmojiToPool(box, ch, overlay),
          }, ch));
        }
        recentsSection = el('div', {},
          el('label', { class: 'dim', style: 'display:block;margin-bottom:6px;font-size:12px;font-weight:600;' }, 'Recientes'),
          recentGrid
        );
      }

      const freqGrid = el('div', { class: 'emoji-frequent-grid' });
      for (const ch of COMMON_EMOJIS) {
        freqGrid.append(el('button', {
          type: 'button',
          class: 'emoji-frequent-btn',
          title: ch,
          'aria-label': ch,
          onclick: () => addEmojiToPool(box, ch, overlay),
        }, ch));
      }

      const freqSection = el('div', {},
        el('label', { class: 'dim', style: 'display:block;margin-bottom:6px;font-size:12px;font-weight:600;' }, 'Frecuentes'),
        freqGrid
      );

      tabContent.append(addRow);
      if (recentsSection) tabContent.append(recentsSection);
      tabContent.append(freqSection);

      setTimeout(() => input.focus(), 50);
    } else {
      const searchInput = el('input', {
        type: 'search',
        placeholder: 'Buscar emoji personalizado…',
        value: customSearchQuery,
        class: 'emoji-search-input',
        oninput: () => {
          customSearchQuery = searchInput.value.trim().toLowerCase();
          customPage = 1;
          renderServerEmojiResults();
        },
      });

      const resultsContainer = el('div', { class: 'emoji-server-results' });
      tabContent.append(searchInput, resultsContainer);

      setTimeout(() => searchInput.focus(), 50);

      if (!cachedServerEmojis) {
        resultsContainer.append(spinner());
        try {
          cachedServerEmojis = await getEmojis();
        } catch (e) {
          cachedServerEmojis = [];
        }
        resultsContainer.innerHTML = '';
      }

      function renderServerEmojiResults() {
        resultsContainer.innerHTML = '';
        if (!cachedServerEmojis || !cachedServerEmojis.length) {
          resultsContainer.append(el('p', { class: 'dim', style: 'font-size:13px;padding:12px 0;' }, 'Este servidor no tiene emojis personalizados.'));
          return;
        }

        const filtered = customSearchQuery
          ? cachedServerEmojis.filter(e => e.name.toLowerCase().includes(customSearchQuery))
          : cachedServerEmojis;

        if (!filtered.length) {
          resultsContainer.append(el('p', { class: 'dim', style: 'font-size:13px;padding:12px 0;' }, `No se encontraron emojis que coincidan con "${customSearchQuery}".`));
          return;
        }

        const totalPages = Math.ceil(filtered.length / CUSTOM_PAGE_SIZE);
        if (customPage > totalPages) customPage = totalPages;
        if (customPage < 1) customPage = 1;

        const startIndex = (customPage - 1) * CUSTOM_PAGE_SIZE;
        const pageItems = filtered.slice(startIndex, startIndex + CUSTOM_PAGE_SIZE);

        const grid = el('div', { class: 'emoji-server-grid' });
        for (const e of pageItems) {
          const text = `<${e.animated ? 'a' : ''}:${e.name}:${e.id}>`;
          const selected = inPool.has(text);

          const itemBtn = el('button', {
            type: 'button',
            class: 'emoji-server-item' + (selected ? ' active' : ''),
            title: `:${e.name}:` + (selected ? ' (en el pool - click para quitar)' : ''),
            'aria-label': `:${e.name}:` + (selected ? ' (en el pool)' : ''),
            onclick: () => {
              if (selected) {
                const reactionId = inPool.get(text);
                if (reactionId) removeReaction(box, reactionId, overlay);
              } else {
                addEmojiToPool(box, text, overlay);
              }
            },
          },
            el('img', { src: e.url, alt: e.name, class: 'emoji-server-img', loading: 'lazy' }),
            el('span', { class: 'emoji-server-name' }, e.name)
          );

          grid.append(itemBtn);
        }

        resultsContainer.append(grid);

        if (totalPages > 1) {
          const prevBtn = el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            disabled: customPage <= 1,
            onclick: () => {
              if (customPage > 1) {
                customPage--;
                renderServerEmojiResults();
              }
            },
          }, '← Anterior');

          const nextBtn = el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            disabled: customPage >= totalPages,
            onclick: () => {
              if (customPage < totalPages) {
                customPage++;
                renderServerEmojiResults();
              }
            },
          }, 'Siguiente →');

          const pager = el('div', { class: 'emoji-pager' },
            prevBtn,
            el('span', {}, `${customPage} / ${totalPages} (${filtered.length} emojis)`),
            nextBtn
          );

          resultsContainer.append(pager);
        }
      }

      renderServerEmojiResults();
    }
  }

  renderTabContent();
}

function cupoLine(used, limit, singular, plural, lleno_msg) {
  if (!limit) return null;
  const lleno = used >= limit;
  return el('p', { class: lleno ? '' : 'dim' },
    `${used} de ${limit} ${used === 1 ? singular : plural}`,
    lleno ? ` — llegaste al tope: ${lleno_msg}` : '');
}

function renderFrases(box, frases, packs, limit) {
  const state = box._frasesState || {
    search: '',
    page: 1,
    editingId: null,
    editingText: '',
    isSaving: false,
  };
  box._frasesState = state;
  state.frases = frases || [];
  state.packs = packs || [];
  state.limit = limit || 200;

  box.innerHTML = '';
  const container = el('div', { class: 'frases-container' });
  const cupoWrapper = el('div', { class: 'frases-cupo' });
  const searchWrapper = el('div', { class: 'frases-toolbar' });
  const listWrapper = el('div', { class: 'frases-list-wrapper' });
  const paginationWrapper = el('div', { class: 'frases-pagination-wrapper' });

  function updateCupo() {
    cupoWrapper.innerHTML = '';
    const cupo = cupoLine(
      state.frases.length,
      state.limit,
      'frase usada',
      'frases usadas',
      'elimina una para agregar otra.'
    );
    if (cupo) cupoWrapper.append(cupo);
  }

  const searchInput = el('input', {
    type: 'search',
    class: 'frases-search-input',
    placeholder: 'Buscar una frase…',
    value: state.search,
    autocomplete: 'off',
    'aria-label': 'Buscar una frase',
  });

  searchInput.oninput = () => {
    state.search = searchInput.value;
    state.page = 1;
    renderListAndPagination();
  };

  searchWrapper.append(searchInput);

  const PAGE_SIZE = 20;

  function renderListAndPagination() {
    listWrapper.innerHTML = '';
    paginationWrapper.innerHTML = '';

    if (!state.frases.length) {
      searchWrapper.style.display = 'none';
      listWrapper.append(
        el('ul', { class: 'item-list frases-list' },
          el('li', { class: 'dim' }, 'Todavía no has agregado ninguna frase.'))
      );
      return;
    }

    searchWrapper.style.display = '';

    const q = (state.search || '').trim().toLowerCase();
    const filtered = q
      ? state.frases.filter(f => (f.frase || '').toLowerCase().includes(q))
      : state.frases;

    if (!filtered.length) {
      listWrapper.append(
        el('div', { class: 'frases-empty-search' },
          el('p', { class: 'dim' }, 'No hay frases que coincidan con tu búsqueda.'),
          el('button', {
            class: 'btn btn-secondary btn-sm',
            onclick: () => {
              state.search = '';
              searchInput.value = '';
              state.page = 1;
              renderListAndPagination();
              searchInput.focus();
            },
          }, 'Limpiar búsqueda'))
      );
      return;
    }

    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (state.page > totalPages) state.page = totalPages;
    if (state.page < 1) state.page = 1;

    const startIdx = (state.page - 1) * PAGE_SIZE;
    const pageItems = filtered.slice(startIdx, startIdx + PAGE_SIZE);

    const list = el('ul', { class: 'item-list frases-list' });

    for (const f of pageItems) {
      if (state.editingId === f.id) {
        const editInput = el('input', {
          type: 'text',
          class: 'frase-edit-input',
          maxlength: '300',
          value: state.editingText !== undefined ? state.editingText : f.frase,
          disabled: state.isSaving,
          'aria-label': 'Editar frase',
        });

        async function saveCurrentEdit() {
          const newText = editInput.value.trim();
          if (!newText) {
            toast('La frase no puede estar vacía', 'warn');
            return;
          }
          if (newText.length > 300) {
            toast('La frase no puede superar los 300 caracteres', 'warn');
            return;
          }
          if (newText === f.frase) {
            state.editingId = null;
            state.editingText = '';
            renderListAndPagination();
            return;
          }
          state.isSaving = true;
          renderListAndPagination();
          try {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, {
              method: 'PATCH',
              body: { frase: newText },
            });
            f.frase = newText;
            state.editingId = null;
            state.editingText = '';
            state.isSaving = false;
            toast('Frase actualizada', 'ok');
            renderListAndPagination();
          } catch (e) {
            state.isSaving = false;
            toast(e.message || 'No se pudo actualizar la frase, intenta de nuevo', 'err');
            renderListAndPagination();
          }
        }

        editInput.oninput = () => {
          state.editingText = editInput.value;
        };

        editInput.onkeydown = (ev) => {
          if (ev.key === 'Enter') {
            ev.preventDefault();
            saveCurrentEdit();
          } else if (ev.key === 'Escape') {
            state.editingId = null;
            state.editingText = '';
            renderListAndPagination();
          }
        };

        const saveBtn = el('button', {
          class: 'btn btn-primary btn-sm',
          disabled: state.isSaving,
          onclick: saveCurrentEdit,
        }, state.isSaving ? 'Guardando…' : 'Guardar');

        const cancelBtn = el('button', {
          class: 'btn btn-secondary btn-sm',
          disabled: state.isSaving,
          onclick: () => {
            state.editingId = null;
            state.editingText = '';
            renderListAndPagination();
          },
        }, 'Cancelar');

        list.append(
          el('li', { class: 'frase-item frase-item-editing' },
            editInput,
            el('div', { class: 'frase-actions' }, saveBtn, cancelBtn))
        );
        setTimeout(() => editInput.focus(), 0);
      } else {
        let packSelect = null;
        if (state.packs.length) {
          packSelect = el('select', { class: 'frase-pack-select', 'aria-label': 'Pack de la frase' });
          packSelect.append(el('option', { value: '' }, 'Sin pack (default)'));
          for (const p of state.packs) {
            packSelect.append(el('option', { value: String(p.id) }, p.name));
          }
          packSelect.value = f.pack_id != null ? String(f.pack_id) : '';
          packSelect.onchange = async () => {
            const chosen = packSelect.value ? Number(packSelect.value) : null;
            try {
              await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, {
                method: 'PATCH',
                body: { pack_id: chosen },
              });
              f.pack_id = chosen;
              toast('Pack de la frase actualizado', 'ok');
            } catch (e) {
              toast('No se pudo actualizar el pack, intenta de nuevo', 'err');
              packSelect.value = f.pack_id != null ? String(f.pack_id) : '';
            }
          };
        }

        const editBtn = el('button', {
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            state.editingId = f.id;
            state.editingText = f.frase;
            renderListAndPagination();
          },
        }, 'Editar');

        const delBtn = confirmDelBtn('¿Eliminar esta frase? No se puede recuperar.', async () => {
          try {
            await apiFetch(`/api/server/${GUILD_ID}/settings/frases/${f.id}`, { method: 'DELETE' });
            toast('Frase quitada', 'ok');
            state.frases = state.frases.filter(item => item.id !== f.id);
            if (state.editingId === f.id) {
              state.editingId = null;
              state.editingText = '';
            }
            updateCupo();
            renderListAndPagination();
          } catch (e) {
            toast('No se pudo quitar la frase, intenta de nuevo', 'err');
          }
        });

        list.append(
          el('li', { class: 'frase-item' },
            el('span', { class: 'frase-text' }, f.frase),
            packSelect,
            el('div', { class: 'frase-actions' }, editBtn, delBtn)
          )
        );
      }
    }

    listWrapper.append(list);

    if (totalPages > 1) {
      const prevBtn = el('button', {
        class: 'btn btn-secondary btn-sm',
        disabled: state.page <= 1,
        onclick: () => {
          if (state.page > 1) {
            state.page--;
            renderListAndPagination();
          }
        },
      }, '← Anterior');

      const endIdx = Math.min(startIdx + PAGE_SIZE, filtered.length);
      const infoText = `Página ${state.page} de ${totalPages} · Mostrando ${startIdx + 1}–${endIdx} de ${filtered.length}`;

      const nextBtn = el('button', {
        class: 'btn btn-secondary btn-sm',
        disabled: state.page >= totalPages,
        onclick: () => {
          if (state.page < totalPages) {
            state.page++;
            renderListAndPagination();
          }
        },
      }, 'Siguiente →');

      paginationWrapper.append(
        el('div', { class: 'frases-pagination' },
          prevBtn,
          el('span', { class: 'frases-pagination-info' }, infoText),
          nextBtn
        )
      );
    }
  }

  const addInput = el('input', { type: 'text', placeholder: 'Nueva frase…', maxlength: '300' });
  async function addFrase() {
    const frase = addInput.value.trim();
    if (!frase) return;
    try {
      await apiFetch(`/api/server/${GUILD_ID}/settings/frases`, {
        method: 'POST', body: { frase },
      });
      toast('Frase agregada', 'ok');
      addInput.value = '';
      reloadFrases(box, state.packs);
    } catch (e) {
      toast(e.status === 409 ? e.message : 'No se pudo agregar la frase, intenta de nuevo', e.status === 409 ? 'warn' : 'err');
    }
  }
  addInput.onkeydown = (ev) => { if (ev.key === 'Enter') addFrase(); };
  const addRow = el('div', { class: 'add-row' },
    addInput,
    el('button', { class: 'btn btn-primary', onclick: addFrase }, 'Agregar')
  );

  updateCupo();
  renderListAndPagination();

  container.append(cupoWrapper, searchWrapper, listWrapper, paginationWrapper, addRow);
  box.append(container);
}

async function reloadFrases(box, packs) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/frases`);
    renderFrases(box, data.frases, packs, data.limit);
  } catch (e) { /* ignore */ }
}

function renderFrasePacks(box, packs, channels, frasesBox, limit) {
  box.innerHTML = '';
  const packsList = (packs && Array.isArray(packs.packs))
    ? packs.packs
    : (Array.isArray(packs) ? packs : []);
  const cupo = cupoLine(packsList.length, limit, 'pack usado', 'packs usados',
    'elimina uno para agregar otro.');
  if (cupo) box.append(cupo);
  if (!packsList.length) {
    box.append(el('p', { class: 'dim' },
      'Sin packs todavía — todas las frases están en el pool default del servidor.'));
  }
  for (const pack of packsList) {
    const channelsBox = el('div', {}, el('p', { class: 'dim' }, 'Abre para ver los canales asignados…'));
    let loaded = false;
    const details = el('details', { class: 'embed-group' },
      el('summary', { class: 'embed-group-title' }, pack.name),
      el('div', { class: 'embed-group-body' },
        channelsBox,
        confirmDelBtn(
          '¿Eliminar este pack? Sus frases no se borran: vuelven al pool default del servidor.',
          async () => {
            try {
              await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}`, { method: 'DELETE' });
              toast('Pack eliminado', 'ok');
            } catch (e) { toast('No se pudo eliminar el pack, intenta de nuevo', 'err'); }
            refreshFrasesAndPacks(frasesBox, box, channels);
          },
          { label: 'Eliminar pack' })));
    details.addEventListener('toggle', async () => {
      if (!details.open || loaded) return;
      loaded = true;
      channelsBox.innerHTML = '';
      channelsBox.append(spinner());
      try {
        const data = await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}/channels`);
        const selected = new Set(data.channels.map(c => c.id));
        channelsBox.innerHTML = '';
        channelsBox.append(channelToggleList({
          channels,
          isSelected: id => selected.has(id),
          add: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}/channels`, {
              method: 'POST', body: { channel_id: ch.id },
            });
            selected.add(ch.id);
          },
          remove: async ch => {
            await apiFetch(`/api/server/${GUILD_ID}/frases/packs/${pack.id}/channels/${ch.id}`, {
              method: 'DELETE',
            });
            selected.delete(ch.id);
          },
          listBelow: 'Sin canales asignados a este pack.',
        }));
      } catch (e) { renderError(channelsBox, e); }
    });
    box.append(details);
  }
  const nameInput = el('input', { type: 'text', placeholder: 'Nombre del pack…', maxlength: '80' });
  async function addPack() {
    const name = nameInput.value.trim();
    if (!name) return;
    try {
      await apiFetch(`/api/server/${GUILD_ID}/frases/packs`, { method: 'POST', body: { name } });
      toast('Pack creado', 'ok');
      nameInput.value = '';
      refreshFrasesAndPacks(frasesBox, box, channels);
    } catch (e) {
      toast(e.status === 409 ? e.message : 'No se pudo crear el pack, intenta de nuevo', e.status === 409 ? 'warn' : 'err');
    }
  }
  nameInput.onkeydown = (ev) => { if (ev.key === 'Enter') addPack(); };
  box.append(el('div', { class: 'add-row' }, nameInput,
    el('button', { class: 'btn btn-primary', onclick: addPack }, 'Crear pack')));
}

async function refreshFrasesAndPacks(frasesBox, packsBox, channels) {
  try {
    const [frasesData, packsData] = await Promise.all([
      apiFetch(`/api/server/${GUILD_ID}/settings/frases`),
      apiFetch(`/api/server/${GUILD_ID}/frases/packs`),
    ]);
    renderFrases(frasesBox, frasesData.frases, packsData.packs, frasesData.limit);
    renderFrasePacks(packsBox, packsData.packs, channels, frasesBox, packsData.limit);
  } catch (e) { /* ignore */ }
}

const TRIGGER_MATCH_TYPE_LABELS = {
  exact: 'Texto exacto', starts_with: 'Empieza con', regex: 'Regex',
};
const TRIGGER_MATCH_PHRASES = {
  exact: p => `es exactamente "${p}"`,
  starts_with: p => `empieza con "${p}"`,
  regex: p => `matchea la regex "${p}"`,
};
const TRIGGER_ACTION_LABELS = {
  frase_de_pack: 'Frase de un pack', markov: 'Markov (generado)', mezcla: 'Mezcla (frase o Markov)',
};

function describeTrigger(trig, channels, packs) {
  const chan = channels.find(c => c.id === trig.channel_id);
  const pack = trig.pack_id != null && trig.pack_id !== ''
    ? packs.find(p => String(p.id) === String(trig.pack_id)) : null;
  return {
    channelLabel: '#' + (chan ? chan.name : trig.channel_id),
    matchLabel: TRIGGER_MATCH_TYPE_LABELS[trig.match_type] || trig.match_type,
    pattern: trig.pattern,
    actionLabel: TRIGGER_ACTION_LABELS[trig.action] || trig.action,
    packName: pack ? pack.name : null,
  };
}

function renderTriggers(box, data, channels, packs) {
  box.innerHTML = '';
  const triggersList = (data && Array.isArray(data.triggers))
    ? data.triggers
    : (Array.isArray(data) ? data : []);
  const limit = (data && data.limit) || null;
  const matchTypes = (data && Array.isArray(data.match_types) && data.match_types.length)
    ? data.match_types
    : Object.keys(TRIGGER_MATCH_TYPE_LABELS);
  const actions = (data && Array.isArray(data.actions) && data.actions.length)
    ? data.actions
    : Object.keys(TRIGGER_ACTION_LABELS);
  const safeData = { triggers: triggersList, limit, match_types: matchTypes, actions };
  const safePacks = (packs && Array.isArray(packs.packs)) ? packs.packs : (Array.isArray(packs) ? packs : []);

  const list = el('ul', { class: 'item-list' });
  const cupo = cupoLine(triggersList.length, limit, 'trigger usado', 'triggers usados',
    'elimina uno para agregar otro.');
  if (cupo) box.append(cupo);
  if (!triggersList.length) list.append(el('li', { class: 'dim' }, 'Todavía no configuraste ningún trigger.'));
  for (const trig of triggersList) {
    const d = describeTrigger(trig, channels, safePacks);
    list.append(el('li', { class: 'trigger-card' },
      el('div', { class: 'trigger-card-main' },
        el('span', { class: 'badge trigger-chan-badge' }, d.channelLabel),
        el('span', {}, d.matchLabel, ' ', el('code', { class: 'cmd' }, `"${d.pattern}"`)),
        el('span', { class: 'trigger-arrow' }, '→'),
        el('span', { class: 'trigger-action' }, d.actionLabel, d.packName ? ` (${d.packName})` : '')),
      confirmDelBtn('¿Eliminar este trigger? Hay que volver a escribirlo desde cero.', async () => {
        try {
          await apiFetch(`/api/server/${GUILD_ID}/settings/triggers/${trig.id}`, { method: 'DELETE' });
          toast('Trigger eliminado', 'ok');
        } catch (e) { toast('No se pudo eliminar el trigger, intenta de nuevo', 'err'); }
        reloadTriggers(box, channels, safePacks);
      })));
  }
  box.append(list, triggerForm(box, channels, safePacks, safeData));
}

function triggerForm(box, channels, packs, data) {
  const safePacks = Array.isArray(packs) ? packs : ((packs && packs.packs) || []);
  const chanSel = channelSelect(channels);
  const matchSel = el('select', {});
  const matchTypes = (data && Array.isArray(data.match_types) && data.match_types.length)
    ? data.match_types
    : Object.keys(TRIGGER_MATCH_TYPE_LABELS);
  for (const mt of matchTypes) matchSel.append(el('option', { value: mt }, TRIGGER_MATCH_TYPE_LABELS[mt] || mt));
  const patternInput = el('input', { type: 'text', placeholder: 'gg, !ban, ^hola.*' });
  const actionSel = el('select', {});
  const actions = (data && Array.isArray(data.actions) && data.actions.length)
    ? data.actions
    : Object.keys(TRIGGER_ACTION_LABELS);
  for (const ac of actions) actionSel.append(el('option', { value: ac }, TRIGGER_ACTION_LABELS[ac] || ac));
  const packSel = el('select', {});
  packSel.append(el('option', { value: '' }, 'Sin pack (default)'));
  for (const p of safePacks) packSel.append(el('option', { value: String(p.id) }, p.name));

  const packField = el('div', { class: 'field' }, el('label', {}, 'Pack'), packSel);
  const previewLine = el('p', { class: 'dim trigger-preview' });

  function syncPackVisibility() { packField.style.display = actionSel.value === 'markov' ? 'none' : ''; }

  function updatePreview() {
    const pattern = (patternInput.value || '').trim();
    if (!chanSel.value || !pattern) {
      previewLine.textContent = 'Elige un canal y escribe un patrón para ver la vista previa.';
      return;
    }
    const d = describeTrigger({
      channel_id: chanSel.value, match_type: matchSel.value, pattern,
      action: actionSel.value, pack_id: actionSel.value !== 'markov' ? packSel.value : null,
    }, channels, safePacks);
    const phrase = (TRIGGER_MATCH_PHRASES[matchSel.value] || (p => `matchea "${p}"`))(d.pattern);
    previewLine.textContent =
      `Vista previa: en ${d.channelLabel}, si el mensaje ${phrase}, responde con `
      + `${d.actionLabel.toLowerCase()}${d.packName ? ` (${d.packName})` : ''}.`;
  }

  chanSel.onchange = updatePreview;
  matchSel.onchange = updatePreview;
  patternInput.oninput = updatePreview;
  actionSel.onchange = () => { syncPackVisibility(); updatePreview(); };
  packSel.onchange = updatePreview;
  syncPackVisibility();
  updatePreview();

  const addBtn = el('button', {
    class: 'btn btn-primary',
    onclick: async () => {
      const pattern = (patternInput.value || '').trim();
      if (!chanSel.value || !pattern) {
        toast('Elige un canal y completa el patrón', 'warn');
        return;
      }
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/triggers`, {
          method: 'POST',
          body: {
            channel_id: chanSel.value, match_type: matchSel.value, pattern,
            action: actionSel.value,
            pack_id: actionSel.value !== 'markov' && packSel.value ? packSel.value : null,
          },
        });
        toast('Trigger agregado', 'ok');
        patternInput.value = '';
        reloadTriggers(box, channels, safePacks);
      } catch (e) {
        toast(e.status === 409 ? e.message : 'No se pudo agregar el trigger, intenta de nuevo', e.status === 409 ? 'warn' : 'err');
      }
    },
  }, 'Agregar');

  return el('div', {},
    el('div', { class: 'add-row trigger-form' },
      el('div', { class: 'field' }, el('label', {}, 'Canal'), chanSel),
      el('div', { class: 'field' }, el('label', {}, 'Tipo de match'), matchSel),
      el('div', { class: 'field', style: 'flex:1;min-width:180px' }, el('label', {}, 'Patrón'), patternInput),
      el('div', { class: 'field' }, el('label', {}, 'Acción'), actionSel),
      safePacks.length ? packField : null,
      addBtn),
    previewLine);
}

async function reloadTriggers(box, channels, packs) {
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/settings/triggers`);
    renderTriggers(box, data, channels, packs);
  } catch (e) { /* ignore */ }
}

const PLAYGROUND_NO_RESPONSE_LABELS = {
  canal_ignorado: 'El canal está silenciado (ignorado) — Purgito no respondería ahí.',
  sin_corpus_suficiente: 'Todavía no hay corpus suficiente para generar una respuesta.',
  trigger_sin_contenido: 'Matcheó un trigger, pero el pool de frases de ese trigger está vacío.',
};
const PLAYGROUND_REASON_LABELS = {
  trigger: 'Disparado por un trigger',
  frase_especial: 'Frase especial',
  markov: 'Texto generado (Markov)',
};

const PLAYGROUND_AVISO_LABELS = {
  chat_desactivado:
    'El chat está desactivado: no responde a menciones. Los mensajes espontáneos, las reacciones y los triggers no dependen de este switch y siguen saliendo.',
  canal_sin_menciones:
    'Este canal no está en la lista de canales donde responde a menciones: si lo mencionan acá, avisa que solo contesta en los canales elegidos.',
  canal_sin_espontaneo:
    'Este canal no está en la lista de canales donde habla por su cuenta: acá nunca va a arrancar una charla solo.',
  cupo_horario_agotado:
    'Ya agotaste tu cupo de menciones de esta hora: a vos no te contestaría ahora mismo (a otro miembro sí, cada uno tiene el suyo).',
  cooldown_espontaneo:
    'Acabó de hablar solo en este canal: por el piso de silencio entre mensajes espontáneos no volvería a hacerlo todavía. No afecta a las menciones.',
};

function playgroundAvisos(avisos) {
  if (!avisos || !avisos.length) return null;
  return el('div', { class: 'playground-avisos' },
    el('p', { class: 'dim' }, avisos.length === 1
      ? 'Hay un freno activo fuera del motor de generación:'
      : `Hay ${avisos.length} frenos activos fuera del motor de generación:`),
    el('ul', { class: 'item-list' }, avisos.map(code =>
      el('li', {}, el('span', {}, PLAYGROUND_AVISO_LABELS[code] || code)))));
}

function buildPlaygroundChannelPicker(channels, selectedId, onSelect) {
  const wrap = el('div', { class: 'sim-channel-picker' });
  let currentId = selectedId || (channels[0] ? channels[0].id : '');

  const getChannel = (id) => channels.find(c => String(c.id) === String(id));

  const trigger = el('button', {
    type: 'button',
    class: 'sim-channel-trigger',
    'aria-haspopup': 'listbox',
    'aria-expanded': 'false',
  });

  function updateTriggerText() {
    trigger.innerHTML = '';
    const ch = getChannel(currentId);
    const left = el('div', { class: 'sim-channel-trigger-left' },
      el('span', { class: 'sim-chan-hash' }, '#'),
      el('span', { class: 'sim-chan-name' }, ch ? ch.name : 'Elige un canal…'),
      ch && ch.category ? el('span', { class: 'sim-chan-cat' }, ch.category) : null
    );
    const caret = el('span', { class: 'dd-caret' }, '▾');
    trigger.append(left, caret);
  }
  updateTriggerText();

  const dropdown = el('div', { class: 'sim-channel-dropdown', style: 'display: none;' });

  const searchInput = el('input', {
    type: 'text',
    class: 'sim-channel-search-input',
    placeholder: 'Buscar canal…',
    autocomplete: 'off',
  });
  const searchWrap = el('div', { class: 'sim-channel-search-wrap' },
    icon('search'),
    searchInput
  );

  const listWrap = el('div', { class: 'sim-channel-list', role: 'listbox' });

  function renderList(filter = '') {
    listWrap.innerHTML = '';
    const q = filter.trim().toLowerCase();
    const filtered = channels.filter(c => {
      const matchName = c.name && c.name.toLowerCase().includes(q);
      const matchCat = c.category && c.category.toLowerCase().includes(q);
      return matchName || matchCat;
    });

    if (!filtered.length) {
      listWrap.append(el('div', { style: 'padding: 12px 14px; color: var(--text-dim); font-size: 13px; text-align: center;' }, 'No se encontraron canales'));
      return;
    }

    const categoriesMap = new Map();
    for (const c of filtered) {
      const catKey = c.category || 'Canales de texto';
      if (!categoriesMap.has(catKey)) categoriesMap.set(catKey, []);
      categoriesMap.get(catKey).push(c);
    }

    for (const [catName, catChannels] of categoriesMap.entries()) {
      listWrap.append(el('div', { class: 'sim-channel-cat-header' }, catName));
      for (const ch of catChannels) {
        const isSelected = String(ch.id) === String(currentId);
        const item = el('div', {
          class: `sim-channel-item${isSelected ? ' selected' : ''}`,
          role: 'option',
          'aria-selected': isSelected ? 'true' : 'false',
          onclick: (e) => {
            e.stopPropagation();
            currentId = ch.id;
            updateTriggerText();
            closeDropdown();
            onSelect(ch.id);
          },
        },
          el('div', { style: 'display: flex; align-items: center; gap: 8px; min-width: 0;' },
            el('span', { class: 'sim-chan-hash' }, '#'),
            el('span', { class: 'sim-chan-name' }, ch.name)
          ),
          isSelected ? icon('check') : null
        );
        listWrap.append(item);
      }
    }
  }

  renderList();

  searchInput.oninput = () => {
    renderList(searchInput.value);
  };

  function openDropdown() {
    dropdown.style.display = 'flex';
    trigger.setAttribute('aria-expanded', 'true');
    searchInput.value = '';
    renderList();
    setTimeout(() => searchInput.focus(), 30);
  }

  function closeDropdown() {
    dropdown.style.display = 'none';
    trigger.setAttribute('aria-expanded', 'false');
  }

  trigger.onclick = (e) => {
    e.stopPropagation();
    if (dropdown.style.display === 'none') {
      openDropdown();
    } else {
      closeDropdown();
    }
  };

  document.addEventListener('click', (e) => {
    if (!wrap.contains(e.target)) {
      closeDropdown();
    }
  });

  dropdown.append(searchWrap, listWrap);
  wrap.append(trigger, dropdown);
  return wrap;
}

function renderPlaygroundResult(box, data, channel, style) {
  box.innerHTML = '';
  if (!data) return;

  const card = el('div', { class: 'sim-result-card' });

  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  const chanName = channel ? channel.name : 'canal';

  const resultHeader = el('div', { class: 'sim-result-header' },
    el('div', { class: 'sim-result-title-group' },
      icon('sparkle'),
      el('h4', { class: 'sim-result-title' }, 'Respuesta simulada'),
      el('span', { class: 'badge badge-sm' }, 'Simulación en vivo')
    ),
    el('span', { class: 'sim-meta-tag' },
      icon('chat'),
      `#${chanName}`
    )
  );
  card.append(resultHeader);

  if (!data.would_respond) {
    const reasonText = PLAYGROUND_NO_RESPONSE_LABELS[data.reason] || 'El bot no respondería a este mensaje según las reglas configuradas.';
    card.append(
      el('div', { class: 'sim-no-response-box' },
        icon('alertTriangle'),
        el('div', {},
          el('strong', {}, 'Sin respuesta: '),
          el('span', {}, reasonText)
        )
      )
    );
  } else {
    const botNick = (style && style.current_nick) || 'Purgito';
    const botAvatar = (style && (style.avatar_url || style.current_avatar_url)) || '/img/icon.webp';

    const discordPreview = el('div', { class: 'sim-discord-preview' },
      el('img', { class: 'sim-bot-avatar', src: botAvatar, alt: botNick, onerror: (e) => { e.target.src = '/img/icon.webp'; } }),
      el('div', { class: 'sim-message-content' },
        el('div', { class: 'sim-message-author-row' },
          el('span', { class: 'sim-bot-name' }, botNick),
          el('span', { class: 'sim-bot-tag' }, 'BOT'),
          el('span', { class: 'sim-message-timestamp' }, `Hoy a las ${timeStr} (Simulación)`)
        ),
        el('div', { class: 'sim-message-text' }, data.text || '')
      )
    );
    card.append(discordPreview);

    const metaRow = el('div', { class: 'sim-meta-row' });
    if (data.reason === 'trigger') {
      metaRow.append(
        el('span', { class: 'sim-meta-tag sim-meta-tag--trigger' },
          icon('zap'),
          `Disparado por Trigger ${data.trigger_id ? `(#${data.trigger_id})` : ''}`
        )
      );
    } else if (data.reason === 'frase_especial') {
      metaRow.append(
        el('span', { class: 'sim-meta-tag sim-meta-tag--frase' },
          icon('sparkle'),
          'Frase especial de canal'
        )
      );
    } else if (data.reason === 'markov') {
      metaRow.append(
        el('span', { class: 'sim-meta-tag sim-meta-tag--markov' },
          icon('play'),
          'Generado con Modelo Markov'
        )
      );
    }
    card.append(metaRow);
  }

  const avisosNode = playgroundAvisos(data.avisos);
  if (avisosNode) {
    card.append(avisosNode);
  }

  box.append(card);
}

// ---------------- MEMES ----------------

function loadMemes() {
  const box = content();
  box.append(emptyState('Generación de memes en proceso.'));
}
