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
import {
  GUILD_ID, setGuildId, clearGuildCaches, currentLocale,
  getDashboardUrl, getPerfilUrl, getLoginUrl, parseGuildId,
} from '/js/core/config.js';
import { getChannels, getRoles, channelSelect, roleSelect, content } from '/js/panel-shell.js';
import { loadGifs } from '/js/tabs/gifs.js';
import { loadPremium } from '/js/tabs/premium.js';
import { loadYoutube } from '/js/tabs/youtube.js';
import { loadHistorial } from '/js/tabs/historial.js';
import { loadWelcomeTab, loadGoodbyeTab, loadBoostTab } from '/js/tabs/eventos.js';
import { loadAnunciosTab } from '/js/tabs/anuncios.js';
import {
  loadEmbeds, loadSharedEmbed, panelModal, getEmojis, uploadImageBlob,
} from '/js/embeds/shared-ui.js';
import { t, addStrings } from '/js/core/i18n.js';

addStrings({
  es: {
    'dash.cat.principal': 'Principal',
    'dash.cat.anuncios': 'Anuncios',
    'dash.cat.plantillas': 'Embeds',
    'dash.cat.automatizacion': 'Automatización',
    'dash.cat.contenido': 'Contenido',
    'dash.cat.servidor': 'Servidor',
    'dash.mod.inicio.label': 'Inicio',
    'dash.mod.inicio.desc': 'Resumen del servidor, estado de Purgito y accesos rápidos',
    'dash.mod.stats.label': 'Estadísticas',
    'dash.mod.stats.desc': 'Métricas de uso, memoria del bot, canales y actividad acumulada',
    'dash.mod.chat.label': 'Ajustes de Chat',
    'dash.mod.chat.desc': 'Comportamiento, probabilidades, canales y límites del chat',
    'dash.mod.estilo.label': 'Personalización',
    'dash.mod.estilo.desc': 'Apariencia de Purgito en este servidor: nick, avatar y banner',
    'dash.mod.playground.label': 'Simulador de Chat',
    'dash.mod.playground.desc': 'Simula y prueba cómo respondería Purgito en vivo según las reglas y corpus del canal',
    'dash.mod.historial.label': 'Auditoría',
    'dash.mod.historial.desc': 'Registro de cambios y auditoría de acciones realizadas',
    'dash.mod.premium.desc': 'Memoria ampliada a 50.000 mensajes, 4.000 GIFs y soporte prioritario',
    'dash.mod.welcome.label': 'Bienvenidas',
    'dash.mod.welcome.desc': 'Mensajes automáticos al unirse nuevos miembros al servidor',
    'dash.mod.goodbye.label': 'Despedidas',
    'dash.mod.goodbye.desc': 'Mensajes automáticos cuando un miembro abandona el servidor',
    'dash.mod.boost.label': 'Boosts',
    'dash.mod.boost.desc': 'Mensajes de celebración y agradecimiento por mejoras al servidor',
    'dash.mod.anuncios.label': 'Anuncios',
    'dash.mod.anuncios.desc': 'Publicaciones automáticas programadas por intervalo u hora fija',
    'dash.mod.updates.label': 'Canal de Novedades',
    'dash.mod.updates.desc': 'Canal donde Purgito publica sus novedades y actualizaciones',
    'dash.mod.triggers.label': 'Triggers de canal',
    'dash.mod.triggers.desc': 'Respuestas automáticas por coincidencia de texto o regex',
    'dash.mod.reacciones.label': 'Reacciones automáticas',
    'dash.mod.reacciones.desc': 'Reacciona automáticamente con emojis configurados en mensajes',
    'dash.mod.frases.label': 'Frases y Packs',
    'dash.mod.frases.desc': 'Frases personalizadas y paquetes temáticos organizados por canal',
    'dash.mod.youtube.desc': 'Avisos automáticos de nuevos videos en canales de YouTube',
    'dash.mod.embeds.label': 'Embeds',
    'dash.mod.embeds.desc': 'Crea y edita mensajes reutilizables: texto, embeds y bloques Layout V2. Bienvenidas, Despedidas y Boosts los usan.',
    'dash.mod.gifs.desc': 'Galería de GIFs del servidor para respuestas y comandos',
    'dash.mod.memes.desc': 'Generación automática de memes y plantillas',
    'dash.mod.canales.label': 'Canales y Permisos',
    'dash.mod.canales.desc': 'Matriz de lectura/respuesta y canales o roles ignorados',
    'dash.mod.amnesia.label': 'Limpieza',
    'dash.mod.amnesia.desc': 'Borra mensajes y estilo aprendidos en las últimas 24 horas',
  },
  en: {
    'dash.cat.principal': 'Main',
    'dash.cat.anuncios': 'Announcements',
    'dash.cat.plantillas': 'Embeds',
    'dash.cat.automatizacion': 'Automation',
    'dash.cat.contenido': 'Content',
    'dash.cat.servidor': 'Server',
    'dash.mod.inicio.label': 'Home',
    'dash.mod.inicio.desc': "Server overview, Purgito's status, and quick links",
    'dash.mod.stats.label': 'Stats',
    'dash.mod.stats.desc': 'Usage metrics, bot memory, channels, and accumulated activity',
    'dash.mod.chat.label': 'Chat settings',
    'dash.mod.chat.desc': 'Behavior, probabilities, channels, and chat limits',
    'dash.mod.estilo.label': 'Customization',
    'dash.mod.estilo.desc': "Purgito's appearance on this server: nickname, avatar, and banner",
    'dash.mod.playground.label': 'Chat Simulator',
    'dash.mod.playground.desc': "Simulate and test how Purgito would reply live, based on the channel's rules and corpus",
    'dash.mod.historial.label': 'Audit log',
    'dash.mod.historial.desc': 'Log of changes and audit trail of actions taken',
    'dash.mod.premium.desc': 'Extended memory up to 50,000 messages, 4,000 GIFs, and priority support',
    'dash.mod.welcome.label': 'Welcome',
    'dash.mod.welcome.desc': 'Automatic messages when new members join the server',
    'dash.mod.goodbye.label': 'Goodbye',
    'dash.mod.goodbye.desc': 'Automatic messages when a member leaves the server',
    'dash.mod.boost.label': 'Boosts',
    'dash.mod.boost.desc': 'Celebration messages when a member boosts the server',
    'dash.mod.anuncios.label': 'Announcements',
    'dash.mod.anuncios.desc': 'Automatic scheduled posts by interval or daily fixed time',
    'dash.mod.updates.label': 'Updates Channel',
    'dash.mod.updates.desc': "Channel where Purgito posts its announcements and updates",
    'dash.mod.triggers.label': 'Channel Triggers',
    'dash.mod.triggers.desc': 'Automatic replies matched by text or regex',
    'dash.mod.reacciones.label': 'Automatic Reactions',
    'dash.mod.reacciones.desc': 'Automatically reacts to messages with configured emojis',
    'dash.mod.frases.label': 'Phrases and Packs',
    'dash.mod.frases.desc': 'Custom phrases and themed packs organized by channel',
    'dash.mod.youtube.desc': 'Automatic alerts for new videos on YouTube channels',
    'dash.mod.embeds.label': 'Embeds',
    'dash.mod.embeds.desc': 'Create and edit reusable messages: text, embeds, and Layout V2 blocks. Welcome, Goodbye, and Boosts use them.',
    'dash.mod.gifs.desc': "The server's GIF gallery for replies and commands",
    'dash.mod.memes.desc': 'Automatic meme generation and templates',
    'dash.mod.canales.label': 'Channels and Permissions',
    'dash.mod.canales.desc': 'Read/reply matrix and ignored channels or roles',
    'dash.mod.amnesia.label': 'Cleanup',
    'dash.mod.amnesia.desc': 'Deletes messages and style learned in the last 24 hours',
  },
});

// ---------------- ESTRUCTURA DE MÓDULOS Y CATEGORÍAS ----------------
// Nota sobre `keywords`: alimentan el filtro del buscador (Ctrl+K), no se
// renderizan. Se mantienen en español -- ver informe final sobre búsqueda
// bilingüe como límite conocido.

export const CATEGORIES = [
  { key: 'principal', label: t('dash.cat.principal'), icon: 'home' },
  { key: 'anuncios', label: t('dash.cat.anuncios'), icon: 'megaphone' },
  { key: 'plantillas', label: t('dash.cat.plantillas'), icon: 'layout' },
  { key: 'automatizacion', label: t('dash.cat.automatizacion'), icon: 'zap' },
  { key: 'contenido', label: t('dash.cat.contenido'), icon: 'film' },
  { key: 'servidor', label: t('dash.cat.servidor'), icon: 'sliders' },
];

export const MODULES = [
  // Principal
  {
    key: 'inicio',
    cat: 'principal',
    label: t('dash.mod.inicio.label'),
    icon: 'home',
    desc: t('dash.mod.inicio.desc'),
    keywords: ['dashboard', 'resumen', 'estado', 'general', 'servidor', 'inicio'],
    load: loadInicio,
  },
  {
    key: 'stats',
    cat: 'principal',
    label: t('dash.mod.stats.label'),
    icon: 'activity',
    desc: t('dash.mod.stats.desc'),
    keywords: ['estadisticas', 'stats', 'metricas', 'mensajes', 'gifs', 'actividad', 'memoria', 'uso', 'contadores'],
    load: loadStatsModule,
  },
  {
    key: 'chat',
    cat: 'principal',
    label: t('dash.mod.chat.label'),
    icon: 'chat',
    desc: t('dash.mod.chat.desc'),
    keywords: ['chat', 'ajustes', 'markov', 'probabilidad', 'menciones', 'espontaneo', 'comportamiento'],
    load: loadChatTab,
  },
  {
    key: 'estilo',
    cat: 'principal',
    label: t('dash.mod.estilo.label'),
    icon: 'palette',
    desc: t('dash.mod.estilo.desc'),
    keywords: ['estilo', 'personalizacion', 'nick', 'apodo', 'avatar', 'banner', 'foto', 'apariencia'],
    load: loadEstiloModule,
  },
  {
    key: 'playground',
    cat: 'principal',
    label: t('dash.mod.playground.label'),
    icon: 'play',
    desc: t('dash.mod.playground.desc'),
    keywords: ['simulador', 'probar', 'simular', 'markov', 'generacion', 'chat', 'playground', 'respuestas'],
    load: loadPlaygroundModule,
  },
  {
    key: 'historial',
    cat: 'principal',
    label: t('dash.mod.historial.label'),
    icon: 'history',
    desc: t('dash.mod.historial.desc'),
    keywords: ['auditoria', 'historial', 'logs', 'registro', 'cambios', 'seguridad'],
    load: loadHistorial,
  },

  // Anuncios
  {
    key: 'welcome',
    cat: 'anuncios',
    label: t('dash.mod.welcome.label'),
    icon: 'logIn',
    desc: t('dash.mod.welcome.desc'),
    keywords: ['bienvenidas', 'welcome', 'bienvenida', 'saludo', 'nuevo', 'miembro', 'entradas'],
    load: loadWelcomeTab,
  },
  {
    key: 'goodbye',
    cat: 'anuncios',
    label: t('dash.mod.goodbye.label'),
    icon: 'logOut',
    desc: t('dash.mod.goodbye.desc'),
    keywords: ['despedidas', 'goodbye', 'despedida', 'salidas', 'abandono'],
    load: loadGoodbyeTab,
  },
  {
    key: 'boost',
    cat: 'anuncios',
    label: t('dash.mod.boost.label'),
    icon: 'star',
    desc: t('dash.mod.boost.desc'),
    keywords: ['boosts', 'boost', 'mejora', 'agradecimiento', 'servidor', 'nitro'],
    load: loadBoostTab,
  },
  {
    key: 'anuncios',
    cat: 'anuncios',
    label: t('dash.mod.anuncios.label'),
    icon: 'megaphone',
    desc: t('dash.mod.anuncios.desc'),
    keywords: ['anuncios', 'programados', 'intervalo', 'diario', 'cadencia', 'mensajes', 'publicaciones', 'automatico', 'auto-delete'],
    load: loadAnunciosTab,
  },
  {
    key: 'updates',
    cat: 'anuncios',
    label: t('dash.mod.updates.label'),
    icon: 'bell',
    desc: t('dash.mod.updates.desc'),
    keywords: ['novedades', 'actualizaciones', 'anuncios', 'bot', 'canal', 'updates'],
    load: loadUpdatesModule,
  },

  // Plantillas
  {
    key: 'embeds',
    cat: 'plantillas',
    label: t('dash.mod.embeds.label'),
    icon: 'layout',
    desc: t('dash.mod.embeds.desc'),
    keywords: ['plantillas', 'embeds', 'templates', 'mensajes', 'editor', 'disenador', 'botones'],
    load: loadEmbeds,
  },

  // Automatización
  {
    key: 'triggers',
    cat: 'automatizacion',
    label: t('dash.mod.triggers.label'),
    icon: 'zap',
    desc: t('dash.mod.triggers.desc'),
    keywords: ['triggers', 'automatizacion', 'regex', 'patrones', 'coincidencias', 'respuestas'],
    load: loadTriggersModule,
  },
  {
    key: 'reacciones',
    cat: 'automatizacion',
    label: t('dash.mod.reacciones.label'),
    icon: 'smile',
    desc: t('dash.mod.reacciones.desc'),
    keywords: ['reacciones', 'emojis', 'automatizacion', 'reaccionar', 'caritas'],
    load: loadReaccionesModule,
  },
  {
    key: 'frases',
    cat: 'automatizacion',
    label: t('dash.mod.frases.label'),
    icon: 'sparkle',
    desc: t('dash.mod.frases.desc'),
    keywords: ['frases', 'packs', 'especiales', 'personalizadas', 'mensajes'],
    load: loadFrasesModule,
  },
  {
    key: 'youtube',
    cat: 'automatizacion',
    label: 'YouTube',
    icon: 'youtube',
    desc: t('dash.mod.youtube.desc'),
    keywords: ['youtube', 'videos', 'notificaciones', 'canales', 'alertas'],
    load: loadYoutube,
  },

  // Contenido
  {
    key: 'gifs',
    cat: 'contenido',
    label: 'GIFs',
    icon: 'film',
    desc: t('dash.mod.gifs.desc'),
    keywords: ['gifs', 'galeria', 'animaciones', 'tenor', 'giphy', 'entretenimiento'],
    load: loadGifs,
  },
  {
    key: 'memes',
    cat: 'contenido',
    label: 'Memes',
    icon: 'image',
    desc: t('dash.mod.memes.desc'),
    keywords: ['memes', 'imagenes', 'generador', 'plantillas', 'entretenimiento'],
    load: loadMemes,
  },

  // Servidor
  {
    key: 'canales',
    cat: 'servidor',
    label: t('dash.mod.canales.label'),
    icon: 'sliders',
    desc: t('dash.mod.canales.desc'),
    keywords: ['canales', 'permisos', 'matriz', 'exentos', 'ignorados', 'silenciados', 'aprender'],
    load: loadCanalesModule,
  },
  {
    key: 'amnesia',
    cat: 'servidor',
    label: t('dash.mod.amnesia.label'),
    icon: 'trash',
    desc: t('dash.mod.amnesia.desc'),
    keywords: ['amnesia', 'limpieza', 'borrar', 'corpus', '24 horas', 'reset'],
    load: loadAmnesiaModule,
  },

  // Purgito Premium (Módulo especial)
  {
    key: 'premium',
    cat: 'premium',
    label: 'Purgito Premium',
    icon: 'star',
    badge: 'PREMIUM',
    badgeType: 'premium',
    desc: t('dash.mod.premium.desc'),
    keywords: ['premium', 'suscripcion', 'polar', 'planes', 'limites', 'cupo', '50000'],
    load: loadPremium,
  },
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
export let _serverPickerOpen = false;

export function setServerPickerOpen(isOpen) {
  _serverPickerOpen = Boolean(isOpen);
}

export function getServerPickerOpen() {
  return _serverPickerOpen;
}

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
  const m = location.pathname.match(/\/dashboard\/\d{1,25}\/([a-zA-Z0-9_-]+)/);
  const seg = m ? m[1] : (location.pathname.split('/')[4] || 'inicio');
  return MODULES.some(mod => mod.key === seg) ? seg : 'inicio';
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

addStrings({
  es: {
    'dash.serverPicker.select': 'Seleccionar servidor',
    'dash.serverPicker.change': 'Cambiar servidor',
    'dash.serverPicker.members': '{count} miembros',
    'dash.serverPicker.searchPlaceholder': 'Buscar servidor…',
    'dash.serverPicker.noResults': 'No se encontraron servidores.',
    'dash.serverPicker.configuredHeader': 'Tus servidores con Purgito',
    'dash.serverPicker.activeServer': 'Servidor activo',
    'dash.serverPicker.availableHeader': 'Otros servidores que administras',
    'dash.serverPicker.invite': 'Invitar a Purgito',
    'dash.serverPicker.loadError': 'No se pudieron cargar los servidores.',
    'dash.serverPicker.manageAll': 'Administrar todos los servidores →',
  },
  en: {
    'dash.serverPicker.select': 'Select server',
    'dash.serverPicker.change': 'Change server',
    'dash.serverPicker.members': '{count} members',
    'dash.serverPicker.searchPlaceholder': 'Search server…',
    'dash.serverPicker.noResults': 'No servers found.',
    'dash.serverPicker.configuredHeader': 'Your servers with Purgito',
    'dash.serverPicker.activeServer': 'Active server',
    'dash.serverPicker.availableHeader': 'Other servers you manage',
    'dash.serverPicker.invite': 'Invite Purgito',
    'dash.serverPicker.loadError': 'Could not load servers.',
    'dash.serverPicker.manageAll': 'Manage all servers →',
  },
});

let _cachedGuilds = null;
let _fetchingGuildsPromise = null;

export function clearGuildsCache() {
  _cachedGuilds = null;
  _fetchingGuildsPromise = null;
}

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

export function buildServerPicker(activeGuild, guildsData, onSelectGuild) {
  const picker = el('div', { class: 'server-picker' });
  const currentGuildsData = guildsData || _cachedGuilds;
  let configured = (currentGuildsData && currentGuildsData.configured) || [];
  let available = (currentGuildsData && currentGuildsData.available) || [];

  const active = activeGuild || (configured.find(g => g.id === GUILD_ID)) || null;

  const trigger = el('button', {
    type: 'button',
    class: 'server-picker-btn' + (_serverPickerOpen ? ' active' : ''),
    'aria-haspopup': 'true',
    'aria-expanded': String(_serverPickerOpen),
    title: active ? active.name : t('dash.serverPicker.select'),
    onclick: (e) => {
      e.stopPropagation();
      _serverPickerOpen = !_serverPickerOpen;
      renderSidebar(currentTab());
    },
  },
    active ? guildIcon(active) : el('div', { class: 'guild-icon guild-initial' }, '?'),
    el('div', { class: 'server-picker-info' },
      el('div', { class: 'server-picker-name' }, active ? active.name : 'Servidor'),
      el('div', { class: 'server-picker-sub dim' },
        active && active.is_premium ? el('span', { class: 'badge badge-premium badge-xs' }, 'PREMIUM') : null,
        active && active.member_count != null ? t('dash.serverPicker.members', { count: Number(active.member_count).toLocaleString('es') }) : t('dash.serverPicker.change')
      )
    ),
    el('span', { class: 'server-picker-caret' }, icon('chevronDown'))
  );

  picker.append(trigger);

  if (_serverPickerOpen) {
    const searchInput = el('input', {
      type: 'search',
      class: 'server-dropdown-search',
      placeholder: t('dash.serverPicker.searchPlaceholder'),
      autocomplete: 'off',
    });

    searchInput.onkeydown = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        _serverPickerOpen = false;
        renderSidebar(currentTab());
      }
    };

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
        listContainer.append(el('div', { class: 'server-dropdown-empty dim' }, t('dash.serverPicker.noResults')));
        return;
      }

      if (filteredConfigured.length) {
        listContainer.append(el('div', { class: 'server-dropdown-header' }, t('dash.serverPicker.configuredHeader')));
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
                isCurrent ? t('dash.serverPicker.activeServer') : (g.member_count != null ? t('dash.serverPicker.members', { count: Number(g.member_count).toLocaleString('es') }) : '')
              )
            ),
            isCurrent ? el('span', { class: 'server-dropdown-check' }, icon('check')) : null
          );
          listContainer.append(row);
        }
      }

      if (filteredAvailable.length) {
        listContainer.append(el('div', { class: 'server-dropdown-header' }, t('dash.serverPicker.availableHeader')));
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
              el('div', { class: 'server-dropdown-item-sub dim' }, t('dash.serverPicker.invite'))
            ),
            el('span', { class: 'server-dropdown-ext' }, icon('externalLink'))
          );
          listContainer.append(row);
        }
      }
    }

    searchInput.oninput = renderList;

    if (!currentGuildsData) {
      listContainer.append(spinner());
      fetchUserGuilds().then(data => {
        if (!_serverPickerOpen) return;
        configured = (data && data.configured) || [];
        available = (data && data.available) || [];
        renderList();
      }).catch(() => {
        if (!_serverPickerOpen) return;
        listContainer.innerHTML = '';
        listContainer.append(el('div', { class: 'server-dropdown-empty dim text-danger' }, t('dash.serverPicker.loadError')));
      });
    } else {
      renderList();
    }

    const dropdown = el('div', { class: 'server-dropdown-menu' },
      el('div', { class: 'server-dropdown-search-wrap' },
        icon('search'),
        searchInput
      ),
      listContainer,
      el('div', { class: 'server-dropdown-footer' },
        el('a', { class: 'server-dropdown-manage-link', href: getPerfilUrl('servidores') },
          t('dash.serverPicker.manageAll')
        )
      )
    );

    picker.append(dropdown);
    setTimeout(() => searchInput.focus(), 50);
  }

  return picker;
}

// ---------------- BUSCADOR GLOBAL DE MÓDULOS (Ctrl + K) ----------------

addStrings({
  es: {
    'dash.palette.searchPlaceholder': 'Buscar módulo, ajuste o comando…',
    'dash.palette.noResults': 'No se encontraron módulos para "{query}".',
    'dash.palette.navigate': 'para navegar',
    'dash.palette.open': 'para abrir',
    'dash.palette.close': 'para cerrar',
  },
  en: {
    'dash.palette.searchPlaceholder': 'Search module, setting, or command…',
    'dash.palette.noResults': 'No modules found for "{query}".',
    'dash.palette.navigate': 'to navigate',
    'dash.palette.open': 'to open',
    'dash.palette.close': 'to close',
  },
});

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
    placeholder: t('dash.palette.searchPlaceholder'),
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
      resultsList.append(el('div', { class: 'cmd-palette-empty dim' }, t('dash.palette.noResults', { query: input.value })));
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
    el('span', { class: 'cmd-palette-tip' }, el('kbd', {}, '↑↓'), ' ' + t('dash.palette.navigate')),
    el('span', { class: 'cmd-palette-tip' }, el('kbd', {}, '↵'), ' ' + t('dash.palette.open')),
    el('span', { class: 'cmd-palette-tip' }, el('kbd', {}, 'ESC'), ' ' + t('dash.palette.close'))
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

addStrings({
  es: {
    'dash.sidebar.showNav': 'Mostrar navegación',
    'dash.sidebar.hideNav': 'Ocultar navegación',
    'dash.sidebar.openMobileNav': 'Abrir navegación del dashboard',
    'dash.sidebar.searchModule': 'Buscar módulo (Ctrl + K)',
    'dash.sidebar.searchModuleShort': 'Buscar módulo…',
  },
  en: {
    'dash.sidebar.showNav': 'Show navigation',
    'dash.sidebar.hideNav': 'Hide navigation',
    'dash.sidebar.openMobileNav': 'Open dashboard navigation',
    'dash.sidebar.searchModule': 'Search module (Ctrl + K)',
    'dash.sidebar.searchModuleShort': 'Search module…',
  },
});

export function renderSidebar(activeTab) {
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
    title: _sidebarCollapsed ? t('dash.sidebar.showNav') : t('dash.sidebar.hideNav'),
    'aria-label': _sidebarCollapsed ? t('dash.sidebar.showNav') : t('dash.sidebar.hideNav'),
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
    'aria-label': t('dash.sidebar.openMobileNav'),
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
      title: t('dash.sidebar.searchModule'),
      onclick: () => {
        closeMobileNav();
        openCommandPalette();
      },
    },
      icon('search'),
      el('span', { class: 'dash-cmd-search-text' }, t('dash.sidebar.searchModuleShort')),
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
        href: getDashboardUrl(GUILD_ID, m.key),
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

  // 4. Sección dedicada para Purgito Premium
  const premiumMod = MODULES.find(m => m.key === 'premium');
  if (premiumMod) {
    const isPremiumActive = activeTab === 'premium';
    const premiumGroup = el('div', { class: 'dash-sidebar-premium-section' },
      el('div', { class: 'dash-sidebar-divider' }),
      el('a', {
        class: 'dash-tab dash-tab--premium' + (isPremiumActive ? ' active' : ''),
        'data-key': 'premium',
        href: getDashboardUrl(GUILD_ID, 'premium'),
        'aria-current': isPremiumActive ? 'page' : null,
        title: premiumMod.label,
        onclick: (ev) => {
          ev.preventDefault();
          closeMobileNav();
          activate('premium', true);
        },
      },
        icon('star'),
        el('span', { class: 'dash-tab-label' }, premiumMod.label),
        el('span', { class: 'badge badge-premium badge-xs' }, 'PREMIUM')
      )
    );
    inner.append(premiumGroup);
  }

  nav.append(header, toggleBtn, inner);
}

// ---------------- CABECERA Y TOPBAR ----------------

addStrings({
  es: {
    'dash.topbar.servers': 'Servidores',
    'dash.topbar.searchModuleOrCommand': 'Buscar módulo o comando (Ctrl + K)',
    'dash.topbar.search': 'Buscar',
  },
  en: {
    'dash.topbar.servers': 'Servers',
    'dash.topbar.searchModuleOrCommand': 'Search module or command (Ctrl + K)',
    'dash.topbar.search': 'Search',
  },
});

export function renderTopBar(guild) {
  const head = document.getElementById('dashHead');
  if (!head) return;
  head.innerHTML = '';

  const titleNode = el('div', { class: 'dash-topbar' },
    el('a', { class: 'dash-back-link', href: getPerfilUrl('servidores') },
      icon('arrowLeft'),
      el('span', {}, t('dash.topbar.servers'))
    ),
    el('div', { class: 'dash-topbar-actions' },
      el('button', {
        type: 'button',
        class: 'btn btn-secondary btn-sm',
        title: t('dash.topbar.searchModuleOrCommand'),
        onclick: () => openCommandPalette(),
      },
        icon('search'),
        el('span', { class: 'hide-mobile' }, t('dash.topbar.search'))
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

addStrings({
  es: {
    'dash.init.switchingServer': 'Cambiando al servidor…',
    'dash.init.backToServers': 'Volver a servidores',
    'dash.init.notInstalled': 'Purgito todavía no está instalado en este servidor.',
    'dash.init.invite': 'Invitar a Purgito',
    'dash.init.viewMyServers': 'Ver mis servidores',
    'dash.init.notFound': 'No puedes administrar este servidor con esta cuenta o no fue encontrado.',
  },
  en: {
    'dash.init.switchingServer': 'Switching servers…',
    'dash.init.backToServers': 'Back to servers',
    'dash.init.notInstalled': "Purgito isn't installed on this server yet.",
    'dash.init.invite': 'Invite Purgito',
    'dash.init.viewMyServers': 'View my servers',
    'dash.init.notFound': 'You cannot manage this server with this account or it was not found.',
  },
});

export async function selectGuild(newGuildId) {
  if (!newGuildId || newGuildId === GUILD_ID) return;

  setGuildId(newGuildId);
  clearGuildCaches();
  _loadEpoch++;

  const curTab = currentTab();
  history.pushState({}, '', getDashboardUrl(newGuildId, curTab));

  const data = await fetchUserGuilds();
  const configured = (data && data.configured) || [];
  _activeGuild = configured.find(x => x.id === newGuildId) || null;
  if (_activeGuild) {
    document.title = `${_activeGuild.name} · Purgito`;
  }
  renderTopBar(_activeGuild);

  activate(curTab, false);
  toast(t('dash.init.switchingServer'), 'ok');
}

// ---------------- ACTIVACIÓN DE MÓDULO ----------------

export function activate(key, push) {
  renderSidebar(key);

  if (push) {
    history.pushState({}, '', getDashboardUrl(GUILD_ID, key));
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
        location.replace(getDashboardUrl(configured[0].id, 'inicio'));
        return;
      }
      location.replace(getPerfilUrl('servidores'));
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
      const back = el('a', { class: 'dash-back', href: getPerfilUrl('servidores') },
        el('span', { class: 'dash-back-arrow', 'aria-hidden': 'true' }, '←'), t('dash.init.backToServers'));
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
              el('p', { class: 'dim', style: 'margin: 6px 0 16px; font-size: 14px;' }, t('dash.init.notInstalled')),
              el('div', { style: 'display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;' },
                el('a', { class: 'btn btn-primary', href: avail.invite_url || `https://discord.com/oauth2/authorize?client_id=1471724794411089920&guild_id=${avail.id}&scope=bot%20applications.commands&permissions=8`, target: '_blank', rel: 'noopener' }, t('dash.init.invite')),
                el('a', { class: 'btn btn-secondary', href: getPerfilUrl('servidores') }, t('dash.init.viewMyServers'))
              )
            )
          ));
        } else {
          box.append(el('div', { class: 'empty-state', style: 'max-width: 540px; margin: 40px auto; text-align: center;' },
            el('p', { style: 'font-size: 16px; margin-bottom: 16px;' }, t('dash.init.notFound')),
            el('a', { class: 'btn btn-secondary', href: getPerfilUrl('servidores') }, t('dash.init.viewMyServers'))
          ));
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
      const m = location.pathname.match(/\/dashboard\/\d{1,25}\/([a-zA-Z0-9_-]+)/);
      if (!m) {
        history.replaceState({}, '', getDashboardUrl(GUILD_ID, tab));
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
  const rawGuild = parseGuildId();
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

addStrings({
  es: {
    'dash.common.save': 'Guardar',
    'dash.common.saving': 'Guardando…',
    'dash.common.cancel': 'Cancelar',
    'dash.common.edit': 'Editar',
    'dash.common.add': 'Agregar',
    'dash.common.remove': 'Quitar',
    'dash.common.uploadImage': 'Subir imagen',
    'dash.common.uploading': 'Subiendo…',
  },
  en: {
    'dash.common.save': 'Save',
    'dash.common.saving': 'Saving…',
    'dash.common.cancel': 'Cancel',
    'dash.common.edit': 'Edit',
    'dash.common.add': 'Add',
    'dash.common.remove': 'Remove',
    'dash.common.uploadImage': 'Upload image',
    'dash.common.uploading': 'Uploading…',
  },
});

addStrings({
  es: {
    'dash.inicio.members': '{count} miembros',
    'dash.inicio.discordServer': 'Servidor de Discord',
    'dash.inicio.serverFallback': 'Servidor',
    'dash.inicio.channelsCount': '{count} canales',
    'dash.inicio.statMessages': 'Mensajes en memoria',
    'dash.inicio.statMessagesSub': 'Corpus de aprendizaje',
    'dash.inicio.statGifs': 'GIFs en catálogo',
    'dash.inicio.statGifsSub': 'Para respuestas y comandos',
    'dash.inicio.statFrases': 'Frases especiales',
    'dash.inicio.statFrasesSub': 'Respuestas configuradas',
    'dash.inicio.statReading': 'Canales que lee',
    'dash.inicio.statReadingSub': 'Para armar estilo',
    'dash.inicio.statReply': 'Canales que responde',
    'dash.inicio.statReplySub': 'Menciones y espontáneos',
    'dash.inicio.statReactions': 'Emojis de reacción',
    'dash.inicio.statReactionsSub': 'Pool activo',
    'dash.inicio.quotaSavedMessages': 'mensajes guardados',
    'dash.inicio.quotaGifs': 'GIFs',
    'dash.inicio.quotaFrases': 'frases especiales',
    'dash.inicio.quotaFullText': 'Has alcanzado el límite de {items}. Purgito descarta automáticamente el contenido más antiguo para dar lugar a nuevo contenido.',
    'dash.inicio.quotaNearText': 'Estás cerca del cupo de {items}: al alcanzarlo, Purgito empezará a descartar lo más antiguo para hacer lugar a lo nuevo.',
    'dash.inicio.statusTitle': 'Estado de Purgito en este servidor',
    'dash.inicio.quickActionsTitle': 'Acciones rápidas',
    'dash.inicio.qaChatTitle': 'Ajustes de Chat',
    'dash.inicio.qaChatDesc': 'Comportamiento, probabilidades y límites de conversación',
    'dash.inicio.qaStyleTitle': 'Personalización',
    'dash.inicio.qaStyleDesc': 'Personaliza el nombre, avatar y banner de Purgito',
    'dash.inicio.qaEmbedsTitle': 'Diseñador de Mensajes',
    'dash.inicio.qaEmbedsDesc': 'Crea y programa anuncios con embeds o Layout V2',
    'dash.inicio.qaGifsTitle': 'Galería de GIFs',
    'dash.inicio.qaGifsDesc': 'Gestiona y verifica la colección de GIFs del servidor',
    'dash.inicio.qaTriggersTitle': 'Triggers y Automatización',
    'dash.inicio.qaTriggersDesc': 'Configura respuestas automáticas y frases clave',
    'dash.inicio.qaStatsTitle': 'Estadísticas y Uso',
    'dash.inicio.qaStatsDesc': 'Consulta métricas de memoria, canales activos y actividad',
    'dash.inicio.qaHistorialTitle': 'Auditoría',
    'dash.inicio.qaHistorialDesc': 'Revisa el historial de cambios y acciones realizadas',
    'dash.inicio.quickStyleTitle': 'Personalización rápida',
    'dash.inicio.previewText': 'Así se ve Purgito en este servidor',
    'dash.inicio.editStyle': 'Editar estilo',
    'dash.inicio.viewOptions': 'Ver opciones →',
    'dash.inicio.activityTitle': 'Actividad histórica',
    'dash.inicio.activityDesc': 'Actividad acumulada en este servidor desde que se unió Purgito.',
    'dash.inicio.gifsSent': 'GIFs enviados',
    'dash.inicio.totalAccumulated': 'Total histórico acumulado',
    'dash.inicio.messagesSent': 'Mensajes enviados',
    'dash.stats.title': 'Estadísticas y Uso',
    'dash.stats.desc': 'Métricas detalladas de memoria, contenido almacenado y actividad acumulada de Purgito en este servidor.',
    'dash.stats.statusTitle': 'Capacidad y memoria en uso',
    'dash.stats.activityTitle': 'Actividad histórica',
    'dash.stats.activityDesc': 'Resumen de actividad acumulada en este servidor desde la llegada de Purgito.',
  },
  en: {
    'dash.inicio.members': '{count} members',
    'dash.inicio.discordServer': 'Discord server',
    'dash.inicio.serverFallback': 'Server',
    'dash.inicio.channelsCount': '{count} channels',
    'dash.inicio.statMessages': 'Messages in memory',
    'dash.inicio.statMessagesSub': 'Learning corpus',
    'dash.inicio.statGifs': 'GIFs in catalog',
    'dash.inicio.statGifsSub': 'For replies and commands',
    'dash.inicio.statFrases': 'Special phrases',
    'dash.inicio.statFrasesSub': 'Configured replies',
    'dash.inicio.statReading': 'Channels it reads',
    'dash.inicio.statReadingSub': 'To build its style',
    'dash.inicio.statReply': 'Channels it replies in',
    'dash.inicio.statReplySub': 'Mentions and spontaneous',
    'dash.inicio.statReactions': 'Reaction emojis',
    'dash.inicio.statReactionsSub': 'Active pool',
    'dash.inicio.quotaSavedMessages': 'saved messages',
    'dash.inicio.quotaGifs': 'GIFs',
    'dash.inicio.quotaFrases': 'special phrases',
    'dash.inicio.quotaFullText': "You've reached the limit for {items}. Purgito automatically discards the oldest content to make room for new content.",
    'dash.inicio.quotaNearText': "You're close to the quota for {items}: once reached, Purgito will start discarding the oldest content to make room for new content.",
    'dash.inicio.statusTitle': "Purgito's status on this server",
    'dash.inicio.quickActionsTitle': 'Quick actions',
    'dash.inicio.qaChatTitle': 'Chat settings',
    'dash.inicio.qaChatDesc': 'Behavior, probabilities, and conversation limits',
    'dash.inicio.qaStyleTitle': 'Customization',
    'dash.inicio.qaStyleDesc': "Customize Purgito's name, avatar, and banner",
    'dash.inicio.qaEmbedsTitle': 'Message Designer',
    'dash.inicio.qaEmbedsDesc': 'Create and schedule announcements with embeds or Layout V2',
    'dash.inicio.qaGifsTitle': 'GIF gallery',
    'dash.inicio.qaGifsDesc': "Manage and review the server's GIF collection",
    'dash.inicio.qaTriggersTitle': 'Triggers and automation',
    'dash.inicio.qaTriggersDesc': 'Set up automatic replies and key phrases',
    'dash.inicio.qaStatsTitle': 'Stats & Usage',
    'dash.inicio.qaStatsDesc': 'View memory metrics, active channels, and activity',
    'dash.inicio.qaHistorialTitle': 'Audit log',
    'dash.inicio.qaHistorialDesc': 'Review the change and action history',
    'dash.inicio.quickStyleTitle': 'Quick customization',
    'dash.inicio.previewText': "This is how Purgito looks on this server",
    'dash.inicio.editStyle': 'Edit style',
    'dash.inicio.viewOptions': 'View options →',
    'dash.inicio.activityTitle': 'Historical activity',
    'dash.inicio.activityDesc': "Activity accumulated on this server since Purgito joined.",
    'dash.inicio.gifsSent': 'GIFs sent',
    'dash.inicio.totalAccumulated': 'Historical total',
    'dash.inicio.messagesSent': 'Messages sent',
    'dash.stats.title': 'Stats and Usage',
    'dash.stats.desc': 'Detailed metrics on memory, stored content, and accumulated activity of Purgito on this server.',
    'dash.stats.statusTitle': 'Capacity and memory in use',
    'dash.stats.activityTitle': 'Historical activity',
    'dash.stats.activityDesc': 'Summary of accumulated activity on this server since Purgito joined.',
  },
});

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
      ? t('dash.inicio.members', { count: Number(g.member_count).toLocaleString('es') })
      : t('dash.inicio.discordServer');

    const serverHero = el('div', { class: 'dash-server-hero' },
      g ? guildIcon(g) : null,
      el('div', { class: 'dash-server-hero-info' },
        el('div', { class: 'dash-server-hero-title-row' },
          el('h1', { class: 'dash-server-hero-name' }, (g && g.name) || t('dash.inicio.serverFallback')),
          g && g.is_premium ? el('span', { class: 'badge badge-premium' }, 'PREMIUM') : null
        ),
        el('div', { class: 'dash-server-hero-meta dim' },
          el('span', {}, memberText),
          el('span', { class: 'meta-sep' }, '·'),
          el('span', {}, t('dash.inicio.channelsCount', { count: stats.text_channels || channels.length || 0 })),
          el('span', { class: 'meta-sep' }, '·'),
          el('span', { class: 'server-id-mono' }, `ID: ${GUILD_ID}`)
        )
      )
    );
    box.append(serverHero);

    // 2. Avisos accionables de cuota (cuando requieren atención del administrador)
    const lims = stats.limits || {};
    const alcanzados = [
      [stats.corpus_total, lims.corpus_total, t('dash.inicio.quotaSavedMessages')],
      [stats.gifs, lims.gifs, t('dash.inicio.quotaGifs')],
      [stats.frases, lims.frases, t('dash.inicio.quotaFrases')],
    ].filter(([used, cap]) => cap && used >= cap);

    const cerca = [
      [stats.corpus_total, lims.corpus_total, t('dash.inicio.quotaSavedMessages')],
      [stats.gifs, lims.gifs, t('dash.inicio.quotaGifs')],
      [stats.frases, lims.frases, t('dash.inicio.quotaFrases')],
    ].filter(([used, cap]) => cap && used >= cap * 0.9 && used < cap);

    if (alcanzados.length) {
      box.append(el('div', { class: 'stat-quota-box stat-quota-box--full' },
        el('span', { class: 'stat-quota-icon' }, '⚠️'),
        el('div', { class: 'stat-quota-text' },
          t('dash.inicio.quotaFullText', { items: alcanzados.map(c => c[2]).join(' y ') })
        )
      ));
    } else if (cerca.length) {
      box.append(el('div', { class: 'stat-quota-box stat-quota-box--near' },
        el('span', { class: 'stat-quota-icon' }, 'ℹ️'),
        el('div', { class: 'stat-quota-text' },
          t('dash.inicio.quotaNearText', { items: cerca.map(c => c[2]).join(' y ') })
        )
      ));
    }

    // 3. Acciones rápidas (Quick Actions)
    const quickActionsGrid = el('div', { class: 'quick-actions-grid' },
      quickActionCard('chat', t('dash.inicio.qaChatTitle'), t('dash.inicio.qaChatDesc'), () => activate('chat', true)),
      quickActionCard('palette', t('dash.inicio.qaStyleTitle'), t('dash.inicio.qaStyleDesc'), () => activate('estilo', true)),
      quickActionCard('layout', t('dash.inicio.qaEmbedsTitle'), t('dash.inicio.qaEmbedsDesc'), () => activate('embeds', true)),
      quickActionCard('film', t('dash.inicio.qaGifsTitle'), t('dash.inicio.qaGifsDesc'), () => activate('gifs', true)),
      quickActionCard('zap', t('dash.inicio.qaTriggersTitle'), t('dash.inicio.qaTriggersDesc'), () => activate('triggers', true)),
      quickActionCard('activity', t('dash.inicio.qaStatsTitle'), t('dash.inicio.qaStatsDesc'), () => activate('stats', true)),
      quickActionCard('history', t('dash.inicio.qaHistorialTitle'), t('dash.inicio.qaHistorialDesc'), () => activate('historial', true))
    );

    box.append(formGroup(t('dash.inicio.quickActionsTitle'), quickActionsGrid));

    // 4. Configuración Rápida / Estilo y Actualizaciones
    const avatar = style.avatar_url || style.current_avatar_url;
    const nick = style.nick || style.current_nick || 'Purgito';

    const stylePreviewNode = formGroup(t('dash.inicio.quickStyleTitle'),
      el('div', { class: 'style-card' },
        el('div', { class: 'style-preview' },
          avatar ? el('img', { class: 'style-avatar', src: avatar, alt: '' }) : null,
          el('div', {},
            el('div', { class: 'style-nick' }, nick, el('span', { class: 'dm-badge' }, 'BOT')),
            el('div', { class: 'dim' }, t('dash.inicio.previewText'))
          )
        ),
        el('div', { class: 'style-card-actions' },
          el('button', {
            class: 'btn btn-secondary',
            onclick: () => openStyleModal(style),
          }, t('dash.inicio.editStyle')),
          el('button', {
            class: 'btn btn-secondary',
            onclick: () => activate('estilo', true),
          }, t('dash.inicio.viewOptions'))
        )
      )
    );

    // Canal de actualizaciones
    const updatesRow = createUpdatesSection(updates, channels);

    box.append(stylePreviewNode, updatesRow);
  } catch (e) {
    if (box) renderError(box, e);
  }
}

export async function loadStatsModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  const epoch = _loadEpoch;

  try {
    const [statsRes, channelsRes] = await Promise.allSettled([
      apiFetch(`/api/server/${GUILD_ID}/stats`),
      getChannels({ force: true }),
    ]);

    if (epoch !== _loadEpoch) return;
    if (!box) return;
    box.innerHTML = '';

    if (statsRes.status === 'rejected') {
      renderError(box, statsRes.reason);
      return;
    }

    const stats = statsRes.value || {};
    const channels = channelsRes.status === 'fulfilled' ? (channelsRes.value || []) : [];
    const lims = stats.limits || {};

    const header = formGroup(t('dash.stats.title'),
      el('p', { class: 'dim' }, t('dash.stats.desc'))
    );

    // 1. Métricas de uso y capacidad
    const tiles = el('div', { class: 'stat-grid' },
      statTile('corpus', withCap(stats.corpus_total, lims.corpus_total), t('dash.inicio.statMessages'), t('dash.inicio.statMessagesSub')),
      statTile('film', withCap(stats.gifs, lims.gifs), t('dash.inicio.statGifs'), t('dash.inicio.statGifsSub')),
      statTile('sparkle', withCap(stats.frases, lims.frases), t('dash.inicio.statFrases'), t('dash.inicio.statFrasesSub')),
      statTile('chat', `${stats.reading_channels || 0} / ${stats.text_channels || channels.length || 0}`, t('dash.inicio.statReading'), t('dash.inicio.statReadingSub')),
      statTile('layout', `${stats.reply_channels || 0} / ${stats.text_channels || channels.length || 0}`, t('dash.inicio.statReply'), t('dash.inicio.statReplySub')),
      statTile('smile', stats.reactions || 0, t('dash.inicio.statReactions'), t('dash.inicio.statReactionsSub'))
    );

    const alcanzados = [
      [stats.corpus_total, lims.corpus_total, t('dash.inicio.quotaSavedMessages')],
      [stats.gifs, lims.gifs, t('dash.inicio.quotaGifs')],
      [stats.frases, lims.frases, t('dash.inicio.quotaFrases')],
    ].filter(([used, cap]) => cap && used >= cap);

    const cerca = [
      [stats.corpus_total, lims.corpus_total, t('dash.inicio.quotaSavedMessages')],
      [stats.gifs, lims.gifs, t('dash.inicio.quotaGifs')],
      [stats.frases, lims.frases, t('dash.inicio.quotaFrases')],
    ].filter(([used, cap]) => cap && used >= cap * 0.9 && used < cap);

    let quotaNotice = null;
    if (alcanzados.length) {
      quotaNotice = el('div', { class: 'stat-quota-box stat-quota-box--full' },
        el('span', { class: 'stat-quota-icon' }, '⚠️'),
        el('div', { class: 'stat-quota-text' },
          t('dash.inicio.quotaFullText', { items: alcanzados.map(c => c[2]).join(' y ') })
        )
      );
    } else if (cerca.length) {
      quotaNotice = el('div', { class: 'stat-quota-box stat-quota-box--near' },
        el('span', { class: 'stat-quota-icon' }, 'ℹ️'),
        el('div', { class: 'stat-quota-text' },
          t('dash.inicio.quotaNearText', { items: cerca.map(c => c[2]).join(' y ') })
        )
      );
    }

    const usageGroup = formGroup(t('dash.stats.statusTitle'), tiles, quotaNotice);

    // 2. Actividad histórica acumulada
    const counters = stats.counters || {};
    const activityRow = formGroup(t('dash.stats.activityTitle'),
      el('p', { class: 'dim' }, t('dash.stats.activityDesc')),
      el('div', { class: 'activity-grid' },
        el('div', { class: 'activity-card' },
          el('div', { class: 'activity-icon-wrap' }, icon('film')),
          el('div', { class: 'activity-content' },
            el('div', { class: 'activity-value' }, Number(counters.gifs_enviados || 0).toLocaleString('es')),
            el('div', { class: 'activity-label' }, t('dash.inicio.gifsSent')),
            el('div', { class: 'activity-sub dim' }, t('dash.inicio.totalAccumulated'))
          )
        ),
        el('div', { class: 'activity-card' },
          el('div', { class: 'activity-icon-wrap' }, icon('chat')),
          el('div', { class: 'activity-content' },
            el('div', { class: 'activity-value' }, Number(counters.mensajes_enviados || 0).toLocaleString('es')),
            el('div', { class: 'activity-label' }, t('dash.inicio.messagesSent')),
            el('div', { class: 'activity-sub dim' }, t('dash.inicio.totalAccumulated'))
          )
        )
      )
    );

    box.append(header, usageGroup, activityRow);
  } catch (e) {
    if (box) renderError(box, e);
  }
}

// ---------------- MÓDULOS ESPECÍFICOS DIRECTOS ----------------

addStrings({
  es: {
    'dash.styleModal.imageHelp': 'PNG, JPG, GIF o WEBP. Máx 10 MB.',
    'dash.styleModal.avatarUploaded': 'Avatar subido',
    'dash.styleModal.uploadError': 'No se pudo subir la imagen',
    'dash.styleModal.bannerUploaded': 'Banner subido',
    'dash.styleModal.appearanceUpdated': 'Apariencia de Purgito actualizada',
    'dash.styleModal.saveError': 'No se pudo guardar la apariencia',
    'dash.styleModal.nickLabel': 'Apodo en este servidor',
    'dash.styleModal.nickDesc': 'Nombre con el que aparece Purgito en este servidor.',
    'dash.styleModal.avatarToggle': 'Modificar avatar',
    'dash.styleModal.avatarDesc': 'Avatar exclusivo para este servidor.',
    'dash.styleModal.bannerToggle': 'Modificar banner',
    'dash.styleModal.bannerDesc': 'Banner del perfil de Purgito en este servidor.',
    'dash.styleModal.title': 'Editar apariencia en este servidor',
    'dash.styleModal.moduleTitle': 'Personalización de Purgito',
    'dash.styleModal.moduleDesc': 'Modifica cómo se presenta Purgito exclusivamente en este servidor (apodo, avatar y banner de perfil).',
    'dash.styleModal.modulePreview': 'Vista previa del bot en este servidor',
    'dash.styleModal.editAppearance': 'Editar apariencia',
  },
  en: {
    'dash.styleModal.imageHelp': 'PNG, JPG, GIF, or WEBP. Max 10 MB.',
    'dash.styleModal.avatarUploaded': 'Avatar uploaded',
    'dash.styleModal.uploadError': 'Could not upload the image',
    'dash.styleModal.bannerUploaded': 'Banner uploaded',
    'dash.styleModal.appearanceUpdated': "Purgito's appearance updated",
    'dash.styleModal.saveError': 'Could not save the appearance',
    'dash.styleModal.nickLabel': 'Nickname on this server',
    'dash.styleModal.nickDesc': 'The name Purgito appears with on this server.',
    'dash.styleModal.avatarToggle': 'Change avatar',
    'dash.styleModal.avatarDesc': 'Exclusive avatar for this server.',
    'dash.styleModal.bannerToggle': 'Change banner',
    'dash.styleModal.bannerDesc': "Purgito's profile banner on this server.",
    'dash.styleModal.title': 'Edit appearance on this server',
    'dash.styleModal.moduleTitle': 'Customize Purgito',
    'dash.styleModal.moduleDesc': "Change how Purgito presents itself exclusively on this server (nickname, avatar, and profile banner).",
    'dash.styleModal.modulePreview': "Preview of the bot on this server",
    'dash.styleModal.editAppearance': 'Edit appearance',
  },
});

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
  }, t('dash.common.uploadImage'));
  const avatarRemoveBtn = el('button', {
    type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => {
      avatarUrl = null;
      avatarPreview.src = '/assets/icon.png';
      avatarCheck.checked = true;
      editAvatar = true;
    },
  }, t('dash.common.remove'));

  const avatarControls = el('div', { class: 'style-img-body' },
    avatarPreview,
    el('div', { style: 'display:flex;flex-direction:column;gap:6px;' },
      el('div', { style: 'display:flex;gap:6px;' }, avatarUploadBtn, avatarRemoveBtn),
      el('span', { class: 'dim', style: 'font-size:12px;' }, t('dash.styleModal.imageHelp'))
    ),
    avatarFile
  );

  avatarFile.onchange = async () => {
    const file = avatarFile.files[0];
    if (!file) return;
    avatarUploadBtn.disabled = true;
    avatarUploadBtn.textContent = t('dash.common.uploading');
    try {
      const url = await uploadImageBlob(file);
      avatarUrl = url;
      avatarPreview.src = url;
      avatarCheck.checked = true;
      editAvatar = true;
      toast(t('dash.styleModal.avatarUploaded'), 'ok');
    } catch (e) {
      toast(e.message || t('dash.styleModal.uploadError'), 'err');
    } finally {
      avatarUploadBtn.disabled = false;
      avatarUploadBtn.textContent = t('dash.common.uploadImage');
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
  }, t('dash.common.uploadImage'));
  const bannerRemoveBtn = el('button', {
    type: 'button', class: 'btn btn-secondary btn-sm', onclick: () => {
      bannerUrl = null;
      bannerPreview.style.display = 'none';
      bannerCheck.checked = true;
      editBanner = true;
    },
  }, t('dash.common.remove'));

  const bannerControls = el('div', { style: 'display:flex;flex-direction:column;gap:8px;' },
    bannerPreview,
    el('div', { style: 'display:flex;gap:6px;align-items:center;' }, bannerUploadBtn, bannerRemoveBtn),
    bannerFile
  );

  bannerFile.onchange = async () => {
    const file = bannerFile.files[0];
    if (!file) return;
    bannerUploadBtn.disabled = true;
    bannerUploadBtn.textContent = t('dash.common.uploading');
    try {
      const url = await uploadImageBlob(file);
      bannerUrl = url;
      bannerPreview.src = url;
      bannerPreview.style.display = 'block';
      bannerCheck.checked = true;
      editBanner = true;
      toast(t('dash.styleModal.bannerUploaded'), 'ok');
    } catch (e) {
      toast(e.message || t('dash.styleModal.uploadError'), 'err');
    } finally {
      bannerUploadBtn.disabled = false;
      bannerUploadBtn.textContent = t('dash.common.uploadImage');
    }
  };

  bannerCheck.onchange = () => { editBanner = bannerCheck.checked; };

  let modal = null;
  const saveBtn = el('button', {
    type: 'button',
    class: 'btn btn-primary',
    onclick: async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = t('dash.common.saving');
      try {
        const body = { nick: nickInput.value.trim() };
        if (editAvatar) body.avatar_url = avatarUrl;
        if (editBanner) body.banner_url = bannerUrl;

        const res = await apiFetch(`/api/server/${GUILD_ID}/style`, {
          method: 'PUT',
          body,
        });
        toast(t('dash.styleModal.appearanceUpdated'), 'ok');
        if (res && res.warning) toast(res.warning, 'warn');
        if (modal) modal.remove();
        if (currentTab() === 'inicio') loadInicio();
        else if (currentTab() === 'estilo') loadEstiloModule();
      } catch (e) {
        toast(e.message || t('dash.styleModal.saveError'), 'err');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = t('dash.common.save');
      }
    },
  }, t('dash.common.save'));

  const cancelBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary',
    onclick: () => { if (modal) modal.remove(); },
  }, t('dash.common.cancel'));

  const modalBody = el('div', { class: 'style-modal' },
    formGroup(el('span', {}, t('dash.styleModal.nickLabel'), nickCounter),
      el('p', { class: 'dim' }, t('dash.styleModal.nickDesc')),
      nickInput
    ),
    formGroup(el('label', { class: 'toggle' }, avatarCheck, t('dash.styleModal.avatarToggle')),
      el('p', { class: 'dim' }, t('dash.styleModal.avatarDesc')),
      avatarControls
    ),
    formGroup(el('label', { class: 'toggle' }, bannerCheck, t('dash.styleModal.bannerToggle')),
      el('p', { class: 'dim' }, t('dash.styleModal.bannerDesc')),
      bannerControls
    ),
    el('div', { class: 'style-modal-actions' }, cancelBtn, saveBtn)
  );

  modal = panelModal(t('dash.styleModal.title'), modalBody);
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
      formGroup(t('dash.styleModal.moduleTitle'),
        el('p', { class: 'dim' }, t('dash.styleModal.moduleDesc')),
        el('div', { class: 'style-card' },
          el('div', { class: 'style-preview' },
            avatar ? el('img', { class: 'style-avatar', src: avatar, alt: '' }) : null,
            el('div', {},
              el('div', { class: 'style-nick' }, nick, el('span', { class: 'dm-badge' }, 'BOT')),
              el('div', { class: 'dim' }, t('dash.styleModal.modulePreview'))
            )
          ),
          el('button', {
            class: 'btn btn-primary',
            onclick: () => openStyleModal(style || {}),
          }, t('dash.styleModal.editAppearance'))
        )
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

addStrings({
  es: {
    'dash.playground.title': 'Simulador de Chat',
    'dash.playground.moduleDesc': 'Previsualiza cómo respondería Purgito en cualquier canal según las configuraciones reales activas. Esta simulación es segura: no envía ningún mensaje a Discord ni consume cupos.',
    'dash.playground.noChannels': 'No hay canales disponibles para simular.',
    'dash.playground.noChannelsDesc': 'Purgito necesita permisos suficientes para acceder y responder en un canal.',
    'dash.playground.sandboxBadge': 'Sandbox seguro — Sin envíos a Discord',
    'dash.playground.sandboxDesc': 'Simula una interacción espontánea en este canal usando la configuración real de Purgito. Nada se enviará a Discord.',
    'dash.playground.simulate': 'Simular interacción',
    'dash.playground.testChannelTitle': 'Canal de prueba',
    'dash.playground.testChannelDesc': 'Selecciona un canal para previsualizar cómo respondería Purgito usando su generación espontánea.',
    'dash.playground.readyTitle': 'Listo para simular',
    'dash.playground.readyDesc': 'Ejecuta una simulación para previsualizar una interacción espontánea de Purgito en este canal.',
    'dash.playground.invalidChannel': 'Selecciona un canal válido',
    'dash.playground.simulating': 'Simulando…',
    'dash.playground.simulatingSpontaneous': 'Simulando interacción espontánea…',
    'dash.playground.errDefault': 'No fue posible simular la respuesta.',
    'dash.playground.err403': 'Purgito ya no tiene acceso a este canal o carece de permisos para ver y enviar mensajes.',
    'dash.playground.err400': 'El canal seleccionado no es válido.',
    'dash.playground.err429': 'Has realizado demasiadas simulaciones consecutivas. Espera unos momentos antes de intentar nuevamente.',
    'dash.playground.errTitle': 'Error al ejecutar la simulación',
  },
  en: {
    'dash.playground.title': 'Chat Simulator',
    'dash.playground.moduleDesc': "Preview how Purgito would reply in any channel based on the settings currently active. This simulation is safe: it doesn't send any message to Discord or use up quotas.",
    'dash.playground.noChannels': 'No channels available to simulate.',
    'dash.playground.noChannelsDesc': 'Purgito needs sufficient permissions to access and reply in a channel.',
    'dash.playground.sandboxBadge': 'Safe sandbox — Nothing sent to Discord',
    'dash.playground.sandboxDesc': "Simulate a spontaneous interaction in this channel using Purgito's real configuration. Nothing will be sent to Discord.",
    'dash.playground.simulate': 'Simulate interaction',
    'dash.playground.testChannelTitle': 'Test channel',
    'dash.playground.testChannelDesc': "Select a channel to preview how Purgito would reply using its spontaneous generation.",
    'dash.playground.readyTitle': 'Ready to simulate',
    'dash.playground.readyDesc': "Run a simulation to preview a spontaneous interaction from Purgito in this channel.",
    'dash.playground.invalidChannel': 'Select a valid channel',
    'dash.playground.simulating': 'Simulating…',
    'dash.playground.simulatingSpontaneous': 'Simulating spontaneous interaction…',
    'dash.playground.errDefault': 'Could not simulate the reply.',
    'dash.playground.err403': "Purgito no longer has access to this channel or lacks permission to view and send messages.",
    'dash.playground.err400': 'The selected channel is not valid.',
    'dash.playground.err429': 'You have run too many simulations in a row. Wait a moment before trying again.',
    'dash.playground.errTitle': 'Error running the simulation',
  },
});

async function loadPlaygroundModule() {
  const box = content();
  if (box) {
    box.innerHTML = '';
    box.append(spinner());
  }
  try {
    const [channelsRes, styleRes] = await Promise.all([
      getChannels({ force: true }),
      apiFetch(`/api/server/${GUILD_ID}/style`).catch(() => ({})),
    ]);
    if (!box) return;
    box.innerHTML = '';

    const allChannels = Array.isArray(channelsRes) ? channelsRes : [];

    // Filtrar únicamente canales donde Purgito puede operar en el simulador
    const usableChannels = allChannels.filter(c => c && c.can_use_simulator);

    // Estado vacío si no hay canales utilizables
    if (!usableChannels.length) {
      box.append(
        formGroup(t('dash.playground.title'),
          el('p', { class: 'dim' },
            t('dash.playground.moduleDesc')
          ),
          el('div', { class: 'sim-empty-state' },
            el('div', { class: 'sim-empty-state-icon' }, icon('lock')),
            el('h3', { class: 'sim-empty-state-title' }, t('dash.playground.noChannels')),
            el('p', { class: 'sim-empty-state-desc' },
              t('dash.playground.noChannelsDesc')
            )
          )
        )
      );
      return;
    }

    let selectedChannelId = usableChannels[0].id;
    let isSubmitting = false;

    const container = el('div', { class: 'sim-container' });

    // Sandbox header / notice
    const headerBanner = el('div', { class: 'sim-header-banner' },
      el('div', { class: 'sim-header-info' },
        el('div', { class: 'sim-badge sim-badge-sandbox' },
          icon('check'),
          el('span', {}, t('dash.playground.sandboxBadge'))
        ),
        el('p', { class: 'sim-header-desc' },
          t('dash.playground.sandboxDesc')
        )
      )
    );

    // Channel selection and action card
    const refreshBtn = el('button', {
      type: 'button',
      class: 'btn btn-primary sim-submit-btn',
      onclick: () => runSimulation(),
    }, icon('play'), el('span', {}, t('dash.playground.simulate')));

    const channelPicker = buildPlaygroundChannelPicker(usableChannels, selectedChannelId, (newId) => {
      selectedChannelId = newId;
      renderInitialEmptyState();
    });

    const channelCard = el('div', { class: 'sim-card sim-channel-card' },
      el('div', { class: 'sim-card-header' },
        el('h3', { class: 'sim-card-title' }, t('dash.playground.testChannelTitle')),
        el('p', { class: 'sim-card-desc' },
          t('dash.playground.testChannelDesc')
        )
      ),
      el('div', { class: 'sim-channel-action-row' },
        channelPicker,
        refreshBtn
      )
    );

    // Dedicated Slots for Partial In-Place Updates:
    // Layout hierarchy:
    // 1. Sandbox banner
    // 2. Canal de prueba + botón Simular interacción
    // 3. Resultado simulado (Hero card)
    // 4. Configuración disponible (5 cards)
    // 5. Reglas evaluadas
    const resultSlot = el('div', { class: 'sim-result-slot' });
    const configSlot = el('div', { class: 'sim-config-slot' });
    const rulesSlot = el('div', { class: 'sim-rules-slot' });

    function renderInitialEmptyState() {
      resultSlot.innerHTML = '';
      resultSlot.append(
        el('div', { class: 'sim-card sim-empty-ready-card' },
          el('div', { class: 'sim-empty-ready-icon' }, icon('play')),
          el('h3', { class: 'sim-empty-ready-title' }, t('dash.playground.readyTitle')),
          el('p', { class: 'sim-empty-ready-desc' },
            t('dash.playground.readyDesc')
          ),
          el('button', {
            type: 'button',
            class: 'btn btn-primary sim-empty-action-btn',
            onclick: () => runSimulation(),
          }, icon('play'), el('span', {}, t('dash.playground.simulate')))
        )
      );
    }

    async function runSimulation() {
      if (isSubmitting) return;
      if (!selectedChannelId) {
        toast(t('dash.playground.invalidChannel'), 'warn');
        return;
      }

      isSubmitting = true;
      refreshBtn.disabled = true;
      refreshBtn.innerHTML = '';
      refreshBtn.append(spinner(), el('span', {}, t('dash.playground.simulating')));

      // Solo cambia el resultado: loading localizado sin provocar scroll jumps ni recrear la página
      resultSlot.innerHTML = '';
      resultSlot.append(
        el('div', { class: 'sim-card sim-result-loading-card' },
          spinner(),
          el('div', { class: 'sim-result-loading-text' }, t('dash.playground.simulatingSpontaneous'))
        )
      );

      try {
        const data = await apiFetch(`/api/server/${GUILD_ID}/chat/playground`, {
          method: 'POST',
          body: { channel_id: selectedChannelId },
        });

        // Actualizar únicamente el slot del resultado
        resultSlot.innerHTML = '';
        resultSlot.append(buildSimulationResultCard(data, styleRes));

        // Actualizar slots de configuración y reglas de forma limpia
        configSlot.innerHTML = '';
        configSlot.append(buildConfigSection(data));

        rulesSlot.innerHTML = '';
        rulesSlot.append(buildRulesSection(data));
      } catch (err) {
        resultSlot.innerHTML = '';
        let errText = t('dash.playground.errDefault');
        if (err && err.status === 403) {
          errText = (err.data && err.data.error) || t('dash.playground.err403');
        } else if (err && err.status === 400) {
          errText = (err.data && err.data.error) || t('dash.playground.err400');
        } else if (err && err.status === 429) {
          errText = t('dash.playground.err429');
        }
        toast(errText, 'err');
        resultSlot.append(
          el('div', { class: 'sim-error-card' },
            el('div', { class: 'sim-error-icon' }, icon('x')),
            el('div', { class: 'sim-error-content' },
              el('h4', {}, t('dash.playground.errTitle')),
              el('p', {}, errText)
            )
          )
        );
      } finally {
        isSubmitting = false;
        refreshBtn.disabled = false;
        refreshBtn.innerHTML = '';
        refreshBtn.append(icon('play'), el('span', {}, t('dash.playground.simulate')));
      }
    }

    container.append(headerBanner, channelCard, resultSlot, configSlot, rulesSlot);

    box.append(
      formGroup(t('dash.playground.title'),
        container
      )
    );

    // Estado inicial: mostrar estado vacío "Listo para simular"
    renderInitialEmptyState();
  } catch (e) { if (box) renderError(box, e); }
}

addStrings({
  es: {
    'dash.playground.mightSendGif': 'Purgito podría enviar un GIF:',
    'dash.playground.gifAlt': 'GIF espontáneo',
    'dash.playground.packTag': 'Pack: {pack}',
    'dash.playground.frasePecial': 'Frase especial',
    'dash.playground.mightReply': 'Purgito podría responder:',
    'dash.playground.today': 'Hoy',
    'dash.playground.textCopied': 'Texto copiado al portapapeles',
    'dash.playground.copy': 'Copiar',
    'dash.playground.noContentTitle': 'No se pudo generar contenido',
    'dash.playground.noContentDesc': 'El servidor no cuenta con mensajes suficientes en el corpus para generar texto con Markov ni tiene frases disponibles.',
    'dash.playground.resultTitle': 'Resultado simulado',
    'dash.playground.gifSpontaneous': 'GIF espontáneo',
    'dash.playground.messageSpontaneous': 'Mensaje espontáneo',
    'dash.playground.generatedFor': 'Interacción generada para #{channel}:',
    'dash.playground.thisChannel': 'este canal',
    'dash.playground.configTitle': 'Configuración disponible',
    'dash.playground.configDesc': 'Parámetros y recursos configurados en este servidor:',
    'dash.playground.markovGeneration': 'Generación Markov',
    'dash.playground.corpusActive': 'Corpus activo',
    'dash.playground.corpusInactive': 'Corpus inactivo',
    'dash.playground.messagesLearned': 'Mensajes aprendidos:',
    'dash.playground.channelVsTotal': '{channel} en canal / {total} total',
    'dash.playground.spontaneousCadence': 'Cadencia espontánea:',
    'dash.playground.everyNMsgs': 'Cada {n} msgs ({pct}%)',
    'dash.playground.messagePacks': 'Packs de mensajes',
    'dash.playground.defaultPool': 'Pool por defecto',
    'dash.playground.disabled': 'Desactivado',
    'dash.playground.fraseProbability': 'Probabilidad de frases:',
    'dash.playground.packsInServer': 'Packs en el servidor:',
    'dash.playground.configuredCount': '{count} configurados',
    'dash.playground.enabled': 'Habilitados',
    'dash.playground.disabledPlural': 'Desactivados',
    'dash.playground.gifsInCatalog': 'GIFs en catálogo:',
    'dash.playground.savedCount': '{count} guardados',
    'dash.playground.gifProbability': 'Probabilidad de GIF:',
    'dash.playground.inThisChannel': '{count} en este canal',
    'dash.playground.actionLabel': 'Acción: {action}',
    'dash.playground.noTriggersHere': 'Sin triggers en este canal',
    'dash.playground.autoReactions': 'Reacciones automáticas',
    'dash.playground.enabledFem': 'Habilitadas',
    'dash.playground.disabledFem': 'Desactivadas',
    'dash.playground.emojiPool': 'Emojis en pool:',
    'dash.playground.emojiPoolValue': '{count} emojis ({pct}%)',
    'dash.playground.appliesToMembers': 'Aplican a mensajes de miembros',
    'dash.playground.rulesEvaluated': 'Reglas evaluadas',
    'dash.playground.rulesDesc': 'Condiciones y políticas verificadas para la generación espontánea:',
  },
  en: {
    'dash.playground.mightSendGif': 'Purgito might send a GIF:',
    'dash.playground.gifAlt': 'Spontaneous GIF',
    'dash.playground.packTag': 'Pack: {pack}',
    'dash.playground.frasePecial': 'Special phrase',
    'dash.playground.mightReply': 'Purgito might reply:',
    'dash.playground.today': 'Today',
    'dash.playground.textCopied': 'Text copied to clipboard',
    'dash.playground.copy': 'Copy',
    'dash.playground.noContentTitle': 'Could not generate content',
    'dash.playground.noContentDesc': "The server doesn't have enough messages in its corpus to generate Markov text, and no phrases are available either.",
    'dash.playground.resultTitle': 'Simulated result',
    'dash.playground.gifSpontaneous': 'Spontaneous GIF',
    'dash.playground.messageSpontaneous': 'Spontaneous message',
    'dash.playground.generatedFor': 'Interaction generated for #{channel}:',
    'dash.playground.thisChannel': 'this channel',
    'dash.playground.configTitle': 'Available configuration',
    'dash.playground.configDesc': 'Parameters and resources configured on this server:',
    'dash.playground.markovGeneration': 'Markov generation',
    'dash.playground.corpusActive': 'Corpus active',
    'dash.playground.corpusInactive': 'Corpus inactive',
    'dash.playground.messagesLearned': 'Messages learned:',
    'dash.playground.channelVsTotal': '{channel} in channel / {total} total',
    'dash.playground.spontaneousCadence': 'Spontaneous cadence:',
    'dash.playground.everyNMsgs': 'Every {n} msgs ({pct}%)',
    'dash.playground.messagePacks': 'Message packs',
    'dash.playground.defaultPool': 'Default pool',
    'dash.playground.disabled': 'Disabled',
    'dash.playground.fraseProbability': 'Phrase probability:',
    'dash.playground.packsInServer': 'Packs on the server:',
    'dash.playground.configuredCount': '{count} configured',
    'dash.playground.enabled': 'Enabled',
    'dash.playground.disabledPlural': 'Disabled',
    'dash.playground.gifsInCatalog': 'GIFs in catalog:',
    'dash.playground.savedCount': '{count} saved',
    'dash.playground.gifProbability': 'GIF probability:',
    'dash.playground.inThisChannel': '{count} in this channel',
    'dash.playground.actionLabel': 'Action: {action}',
    'dash.playground.noTriggersHere': 'No triggers in this channel',
    'dash.playground.autoReactions': 'Automatic reactions',
    'dash.playground.enabledFem': 'Enabled',
    'dash.playground.disabledFem': 'Disabled',
    'dash.playground.emojiPool': 'Emojis in pool:',
    'dash.playground.emojiPoolValue': '{count} emojis ({pct}%)',
    'dash.playground.appliesToMembers': "Applies to members' messages",
    'dash.playground.rulesEvaluated': 'Rules evaluated',
    'dash.playground.rulesDesc': 'Conditions and policies checked for spontaneous generation:',
  },
});

function buildSimulationResultCard(data, styleRes) {
  const botNick = (styleRes && styleRes.current_nick) || 'Purgito';
  const botAvatar = (styleRes && styleRes.current_avatar_url) || '/img/logo.png';
  const channelInfo = data.channel_info || {};
  const isGif = data.result_type === 'gif' || (data.reason === 'gif' && Boolean(data.gif_url));

  let resultSectionBody;
  if (isGif) {
    resultSectionBody = el('div', { class: 'sim-single-result' },
      el('div', { class: 'sim-result-lead-label' }, t('dash.playground.mightSendGif')),
      el('div', { class: 'sim-gif-hero-container' },
        el('img', { class: 'sim-gif-hero-image', src: data.gif_url, alt: t('dash.playground.gifAlt') })
      )
    );
  } else if (data.text) {
    let reasonTag = 'Markov';
    if (data.reason === 'frase_especial') {
      const packName = channelInfo.effective_pack_name;
      reasonTag = packName ? t('dash.playground.packTag', { pack: packName }) : t('dash.playground.frasePecial');
    } else if (data.reason === 'trigger') {
      reasonTag = 'Trigger';
    }

    resultSectionBody = el('div', { class: 'sim-single-result' },
      el('div', { class: 'sim-result-lead-label' }, t('dash.playground.mightReply')),
      el('div', { class: 'sim-discord-message' },
        el('img', { class: 'sim-discord-avatar', src: botAvatar, alt: botNick, onerror: (e) => { e.target.style.display = 'none'; } }),
        el('div', { class: 'sim-discord-content' },
          el('div', { class: 'sim-discord-author-row' },
            el('span', { class: 'sim-discord-author' }, botNick),
            el('span', { class: 'sim-discord-bot-badge' }, 'BOT'),
            el('span', { class: 'sim-discord-timestamp' }, t('dash.playground.today')),
            el('span', { class: 'sim-origin-badge' }, reasonTag)
          ),
          el('div', { class: 'sim-discord-text' }, data.text),
          el('div', { class: 'sim-discord-actions' },
            el('button', {
              type: 'button',
              class: 'btn btn-secondary btn-sm',
              onclick: () => {
                navigator.clipboard?.writeText(data.text || '');
                toast(t('dash.playground.textCopied'), 'ok');
              },
            }, icon('clipboard'), t('dash.playground.copy'))
          )
        )
      )
    );
  } else {
    resultSectionBody = el('div', { class: 'sim-single-result' },
      el('div', { class: 'sim-error-card' },
        el('div', { class: 'sim-error-icon' }, icon('x')),
        el('div', { class: 'sim-error-content' },
          el('h4', {}, t('dash.playground.noContentTitle')),
          el('p', {}, t('dash.playground.noContentDesc'))
        )
      )
    );
  }

  return el('div', { class: 'sim-card sim-preview-card sim-hero-result-card' },
    el('div', { class: 'sim-card-header' },
      el('div', { class: 'sim-result-header-row' },
        el('h3', { class: 'sim-card-title' }, t('dash.playground.resultTitle')),
        el('span', { class: 'sim-pill-badge sim-pill-badge-cyan' },
          isGif ? t('dash.playground.gifSpontaneous') : t('dash.playground.messageSpontaneous')
        )
      ),
      el('p', { class: 'sim-card-desc' },
        t('dash.playground.generatedFor', { channel: channelInfo.name || t('dash.playground.thisChannel') })
      )
    ),
    resultSectionBody
  );
}

function buildConfigSection(data) {
  const settings = data.settings || {};
  const channelInfo = data.channel_info || {};
  const corpusAllowed = channelInfo.is_corpus_allowed !== false;
  const channelMsgs = channelInfo.channel_corpus_count || 0;
  const guildMsgs = channelInfo.guild_corpus_count || 0;
  const effectivePack = channelInfo.effective_pack_name || null;
  const fraseProb = Math.round((settings.frase_probability || 0) * 100);
  const gifTotal = data.gifs ? data.gifs.total_count : 0;
  const gifProb = Math.round((data.gifs ? data.gifs.probability : (settings.gif_response_probability || 0)) * 100);
  const reactionTotal = data.reactions ? data.reactions.total_count : 0;
  const reactionProb = Math.round((data.reactions ? data.reactions.probability : (settings.reaction_probability || 0)) * 100);
  const triggersList = data.triggers || [];

  return el('div', { class: 'sim-section sim-config-section' },
    el('div', { class: 'sim-section-header' },
      el('h4', { class: 'sim-section-title' }, t('dash.playground.configTitle')),
      el('p', { class: 'sim-section-desc' }, t('dash.playground.configDesc'))
    ),
    el('div', { class: 'sim-config-grid' },
      // Markov
      el('div', { class: 'sim-config-card' },
        el('div', { class: 'sim-config-header' },
          el('div', { class: 'sim-config-title-group' },
            icon('corpus'),
            el('span', { class: 'sim-config-title' }, t('dash.playground.markovGeneration'))
          ),
          el('span', { class: `sim-pill-badge ${corpusAllowed ? 'ok' : 'off'}` },
            corpusAllowed ? t('dash.playground.corpusActive') : t('dash.playground.corpusInactive')
          )
        ),
        el('div', { class: 'sim-config-body' },
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label' }, t('dash.playground.messagesLearned')),
            el('span', { class: 'sim-stat-value' }, t('dash.playground.channelVsTotal', { channel: channelMsgs.toLocaleString(), total: guildMsgs.toLocaleString() }))
          ),
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label' }, t('dash.playground.spontaneousCadence')),
            el('span', { class: 'sim-stat-value' }, t('dash.playground.everyNMsgs', { n: settings.auto_generate_every || 15, pct: Math.round((settings.auto_generate_probability || 0) * 100) }))
          )
        )
      ),

      // Packs de mensajes
      el('div', { class: 'sim-config-card' },
        el('div', { class: 'sim-config-header' },
          el('div', { class: 'sim-config-title-group' },
            icon('layout'),
            el('span', { class: 'sim-config-title' }, t('dash.playground.messagePacks'))
          ),
          el('span', { class: `sim-pill-badge ${fraseProb > 0 ? 'ok' : 'off'}` },
            fraseProb > 0 ? (effectivePack ? t('dash.playground.packTag', { pack: effectivePack }) : t('dash.playground.defaultPool')) : t('dash.playground.disabled')
          )
        ),
        el('div', { class: 'sim-config-body' },
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label' }, t('dash.playground.fraseProbability')),
            el('span', { class: 'sim-stat-value' }, `${fraseProb}%`)
          ),
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label' }, t('dash.playground.packsInServer')),
            el('span', { class: 'sim-stat-value' }, t('dash.playground.configuredCount', { count: (data.packs || []).length }))
          )
        )
      ),

      // GIFs
      el('div', { class: 'sim-config-card' },
        el('div', { class: 'sim-config-header' },
          el('div', { class: 'sim-config-title-group' },
            icon('film'),
            el('span', { class: 'sim-config-title' }, 'GIFs')
          ),
          el('span', { class: `sim-pill-badge ${(gifTotal > 0 && gifProb > 0) ? 'ok' : 'off'}` },
            (gifTotal > 0 && gifProb > 0) ? t('dash.playground.enabled') : t('dash.playground.disabledPlural')
          )
        ),
        el('div', { class: 'sim-config-body' },
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label' }, t('dash.playground.gifsInCatalog')),
            el('span', { class: 'sim-stat-value' }, t('dash.playground.savedCount', { count: gifTotal.toLocaleString() }))
          ),
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label' }, t('dash.playground.gifProbability')),
            el('span', { class: 'sim-stat-value' }, `${gifProb}%`)
          )
        )
      ),

      // Triggers
      el('div', { class: 'sim-config-card' },
        el('div', { class: 'sim-config-header' },
          el('div', { class: 'sim-config-title-group' },
            icon('zap'),
            el('span', { class: 'sim-config-title' }, 'Triggers')
          ),
          el('span', { class: `sim-pill-badge ${triggersList.length > 0 ? 'ok' : 'off'}` },
            t('dash.playground.inThisChannel', { count: triggersList.length })
          )
        ),
        el('div', { class: 'sim-config-body' },
          triggersList.length > 0
            ? el('div', { class: 'sim-trigger-chips' },
                triggersList.slice(0, 3).map(trig => el('span', { class: 'sim-trigger-chip', title: t('dash.playground.actionLabel', { action: trig.action }) }, `"${trig.pattern}"`)),
                triggersList.length > 3 ? el('span', { class: 'sim-trigger-chip-more' }, `+${triggersList.length - 3}`) : null
              )
            : el('div', { class: 'sim-config-stat' },
                el('span', { class: 'sim-stat-label dim' }, t('dash.playground.noTriggersHere'))
              )
        )
      ),

      // Reacciones automáticas
      el('div', { class: 'sim-config-card' },
        el('div', { class: 'sim-config-header' },
          el('div', { class: 'sim-config-title-group' },
            icon('smile'),
            el('span', { class: 'sim-config-title' }, t('dash.playground.autoReactions'))
          ),
          el('span', { class: `sim-pill-badge ${(reactionTotal > 0 && reactionProb > 0) ? 'ok' : 'off'}` },
            (reactionTotal > 0 && reactionProb > 0) ? t('dash.playground.enabledFem') : t('dash.playground.disabledFem')
          )
        ),
        el('div', { class: 'sim-config-body' },
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label' }, t('dash.playground.emojiPool')),
            el('span', { class: 'sim-stat-value' }, t('dash.playground.emojiPoolValue', { count: reactionTotal, pct: reactionProb }))
          ),
          el('div', { class: 'sim-config-stat' },
            el('span', { class: 'sim-stat-label dim', style: 'font-size: 11px;' }, t('dash.playground.appliesToMembers'))
          )
        )
      )
    )
  );
}

function buildRulesSection(data) {
  const rulesList = Array.isArray(data.rules_evaluated) ? data.rules_evaluated : [];
  return el('div', { class: 'sim-card sim-rules-card' },
    el('div', { class: 'sim-card-header' },
      el('h3', { class: 'sim-card-title' }, t('dash.playground.rulesEvaluated')),
      el('p', { class: 'sim-card-desc' },
        t('dash.playground.rulesDesc')
      )
    ),
    el('div', { class: 'sim-rules-list' },
      rulesList.map(rule => el('div', { class: `sim-rule-item ${rule.passed ? 'passed' : 'failed'}` },
        el('div', { class: 'sim-rule-icon' }, icon(rule.passed ? 'check' : 'x')),
        el('div', { class: 'sim-rule-content' },
          el('div', { class: 'sim-rule-label' }, rule.label),
          el('div', { class: 'sim-rule-detail' }, rule.detail)
        )
      ))
    ),
    data.avisos && data.avisos.length ? playgroundAvisos(data.avisos) : null
  );
}

addStrings({
  es: {
    'dash.updates.defaultTitle': 'Actualizaciones del Bot',
    'dash.updates.defaultSubtitle': 'Canal donde Purgito publica anuncios y novedades de actualizaciones.',
    'dash.updates.noChannelOption': 'Sin canal — no publicar',
    'dash.updates.noChannelPill': '⚪ Sin canal configurado',
    'dash.updates.noChannelDesc': 'Las novedades y anuncios oficiales del bot no se publicarán en este servidor.',
    'dash.updates.healthyPill': '🟢 Canal configurado y operativo',
    'dash.updates.healthyDesc': 'Purgito tiene permisos suficientes para publicar novedades en #{channel}.',
    'dash.updates.missingPermsPill': '🟠 Permisos insuficientes',
    'dash.updates.missingPermsDesc': 'Purgito no puede publicar en #{channel} porque faltan permisos en Discord:',
    'dash.updates.permViewChannel': 'Ver canal',
    'dash.updates.permSendMessages': 'Enviar mensajes',
    'dash.updates.grantPermsHelp': 'Concede estos permisos en los ajustes de canal o rol de Purgito en Discord para activar las actualizaciones.',
    'dash.updates.notFoundPill': '🔴 Canal eliminado o inaccesible',
    'dash.updates.notFoundDesc': 'El canal configurado (ID: {channelId}) ya no existe en el servidor o fue eliminado. Selecciona un canal válido.',
    'dash.updates.invalidTypePill': '🔴 Tipo de canal no compatible',
    'dash.updates.invalidTypeDesc': 'El canal seleccionado no admite mensajes de texto.',
    'dash.updates.channelSaved': 'Canal de actualizaciones guardado',
    'dash.updates.channelRemoved': 'Canal de actualizaciones quitado',
    'dash.updates.saveError': 'No se pudo guardar el canal, intenta de nuevo',
    'dash.updates.viewSendPerms': 'Ver canal / Enviar mensajes',
  },
  en: {
    'dash.updates.defaultTitle': 'Bot Updates',
    'dash.updates.defaultSubtitle': "Channel where Purgito posts announcements and update news.",
    'dash.updates.noChannelOption': 'No channel — do not post',
    'dash.updates.noChannelPill': '⚪ No channel configured',
    'dash.updates.noChannelDesc': "The bot's official updates and announcements won't be posted on this server.",
    'dash.updates.healthyPill': '🟢 Channel configured and working',
    'dash.updates.healthyDesc': 'Purgito has sufficient permissions to post updates in #{channel}.',
    'dash.updates.missingPermsPill': '🟠 Insufficient permissions',
    'dash.updates.missingPermsDesc': "Purgito can't post in #{channel} because it's missing permissions in Discord:",
    'dash.updates.permViewChannel': 'View channel',
    'dash.updates.permSendMessages': 'Send messages',
    'dash.updates.grantPermsHelp': "Grant these permissions in Purgito's channel or role settings in Discord to enable updates.",
    'dash.updates.notFoundPill': '🔴 Channel deleted or inaccessible',
    'dash.updates.notFoundDesc': 'The configured channel (ID: {channelId}) no longer exists on the server, or was deleted. Select a valid channel.',
    'dash.updates.invalidTypePill': '🔴 Unsupported channel type',
    'dash.updates.invalidTypeDesc': "The selected channel doesn't support text messages.",
    'dash.updates.channelSaved': 'Updates channel saved',
    'dash.updates.channelRemoved': 'Updates channel removed',
    'dash.updates.saveError': 'Could not save the channel, try again',
    'dash.updates.viewSendPerms': 'View channel / Send messages',
  },
});

export function createUpdatesSection(initialUpdates, channels, {
  title = t('dash.updates.defaultTitle'),
  subtitle = t('dash.updates.defaultSubtitle'),
} = {}) {
  let currentUpdates = initialUpdates || {};
  let currentChannelId = currentUpdates.channel_id || '';

  const sel = channelSelect(channels, currentChannelId, t('dash.updates.noChannelOption'));
  const statusWrap = el('div', { class: 'updates-status-card' });

  function renderStatus(info) {
    statusWrap.innerHTML = '';
    const status = info.status || (info.channel_id ? 'healthy' : 'no_channel');
    const chName = info.channel_name || ((Array.isArray(channels) ? channels : []).find(c => c && String(c.id) === String(info.channel_id)) || {}).name || info.channel_id;

    let pillClass = 'updates-status-pill--neutral';
    let pillText = t('dash.updates.noChannelPill');
    let descText = t('dash.updates.noChannelDesc');
    const extraNodes = [];

    if (status === 'healthy') {
      pillClass = 'updates-status-pill--healthy';
      pillText = t('dash.updates.healthyPill');
      descText = t('dash.updates.healthyDesc', { channel: chName || t('dash.playground.thisChannel') });
      if (Array.isArray(info.warnings) && info.warnings.length) {
        extraNodes.push(
          el('div', { class: 'updates-warnings-wrap dim' },
            ...info.warnings.map(w => el('div', { class: 'updates-warning-item' }, `ℹ️ ${w}`))
          )
        );
      }
    } else if (status === 'missing_permissions') {
      pillClass = 'updates-status-pill--warning';
      pillText = t('dash.updates.missingPermsPill');
      descText = t('dash.updates.missingPermsDesc', { channel: chName || t('dash.playground.thisChannel') });
      const missingLabels = Array.isArray(info.missing_permissions_labels) && info.missing_permissions_labels.length
        ? info.missing_permissions_labels
        : [t('dash.updates.permViewChannel'), t('dash.updates.permSendMessages')];
      extraNodes.push(
        el('div', { class: 'updates-perms-list' },
          ...missingLabels.map(lbl => el('span', { class: 'updates-perm-tag' }, lbl))
        ),
        el('p', { class: 'updates-help-text dim' },
          t('dash.updates.grantPermsHelp')
        )
      );
    } else if (status === 'not_found') {
      pillClass = 'updates-status-pill--error';
      pillText = t('dash.updates.notFoundPill');
      descText = t('dash.updates.notFoundDesc', { channelId: info.channel_id || currentChannelId });
    } else if (status === 'invalid_type') {
      pillClass = 'updates-status-pill--error';
      pillText = t('dash.updates.invalidTypePill');
      descText = info.details || t('dash.updates.invalidTypeDesc');
    }

    const pill = el('span', { class: `updates-status-pill ${pillClass}` }, pillText);
    const desc = el('p', { class: 'updates-status-desc' }, descText);

    statusWrap.append(
      el('div', { class: 'updates-status-header' }, pill),
      desc,
      ...extraNodes
    );
  }

  renderStatus(currentUpdates);

  sel.onchange = async () => {
    const selectedId = sel.value || null;
    try {
      const res = await apiFetch(`/api/server/${GUILD_ID}/settings/updates`, {
        method: 'PUT',
        body: { channel_id: selectedId },
      });
      currentChannelId = selectedId || '';
      currentUpdates = {
        ...currentUpdates,
        channel_id: selectedId,
        channel_name: res.channel_name,
        status: res.status || (selectedId ? 'healthy' : 'no_channel'),
        missing_permissions: res.missing_permissions || [],
        missing_permissions_labels: res.missing_permissions_labels || [],
        warnings: res.warnings || [],
        details: res.details,
      };
      renderStatus(currentUpdates);
      toast(selectedId ? t('dash.updates.channelSaved') : t('dash.updates.channelRemoved'), 'ok');
    } catch (e) {
      toast(e.message || t('dash.updates.saveError'), 'err');
      sel.value = currentChannelId || '';
      if (e.status === 400 && e.message) {
        renderStatus({
          channel_id: selectedId,
          status: 'missing_permissions',
          missing_permissions_labels: [t('dash.updates.viewSendPerms')],
          details: e.message,
        });
      }
    }
  };

  const row = el('div', { class: 'updates-row' },
    el('div', { class: 'updates-info' },
      el('p', { class: 'dim' }, subtitle)
    ),
    el('div', { class: 'updates-control' }, sel)
  );

  return formGroup(title, row, statusWrap);
}

addStrings({
  es: {
    'dash.updates.moduleTitle': 'Canal de Novedades y Actualizaciones',
    'dash.updates.moduleSubtitle': 'Elige el canal donde Purgito publicará avisos de novedades, notas de versiones y anuncios importantes.',
    'dash.triggers.moduleTitle': 'Triggers de canal',
    'dash.triggers.moduleDesc': 'Si un mensaje recibido coincide con el patrón configurado, Purgito responderá automáticamente sin esperar una mención.',
    'dash.reacciones.moduleTitle': 'Reacciones automáticas',
    'dash.reacciones.moduleDesc': 'Configura la probabilidad y la colección de emojis con los que Purgito puede reaccionar a los mensajes del chat.',
    'dash.reacciones.probLabel': 'Probabilidad de reaccionar con un emoji',
    'dash.reacciones.emojiCollectionLabel': 'Colección de emojis',
  },
  en: {
    'dash.updates.moduleTitle': 'Updates Channel',
    'dash.updates.moduleSubtitle': 'Choose the channel where Purgito will post update notices, release notes, and important announcements.',
    'dash.triggers.moduleTitle': 'Channel Triggers',
    'dash.triggers.moduleDesc': "If an incoming message matches the configured pattern, Purgito will reply automatically without waiting for a mention.",
    'dash.reacciones.moduleTitle': 'Automatic Reactions',
    'dash.reacciones.moduleDesc': "Set the probability and the collection of emojis Purgito can use to react to chat messages.",
    'dash.reacciones.probLabel': 'Probability of reacting with an emoji',
    'dash.reacciones.emojiCollectionLabel': 'Emoji collection',
  },
});

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

    box.append(
      createUpdatesSection(updates, channels, {
        title: t('dash.updates.moduleTitle'),
        subtitle: t('dash.updates.moduleSubtitle'),
      })
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
      formGroup(t('dash.triggers.moduleTitle'),
        el('p', { class: 'dim' },
          t('dash.triggers.moduleDesc')
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
      formGroup(t('dash.reacciones.moduleTitle'),
        el('p', { class: 'dim' }, t('dash.reacciones.moduleDesc')),
        probabilityField(t('dash.reacciones.probLabel'), null, {
          key: 'reaction_probability',
          value: chat ? chat.reaction_probability : 0,
        }),
        el('div', { class: 'field' },
          el('label', {}, t('dash.reacciones.emojiCollectionLabel')),
          reaccionesBox
        )
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

addStrings({
  es: {
    'dash.frasesModule.title': 'Frases especiales',
    'dash.frasesModule.desc': 'Frases predefinidas que Purgito puede intercalar en sus respuestas o mediante triggers.',
    'dash.frasesModule.dynamicVars': 'Variables dinámicas disponibles en frases',
    'dash.frasesModule.packsTitle': 'Paquetes de frases (Packs)',
    'dash.frasesModule.packsDesc': 'Agrupa frases temáticas para asignarlas a canales específicos o dispararlas mediante triggers.',
    'dash.frasesModule.channelsAccordion': 'Canales donde pueden salir frases especiales generales',
    'dash.frasesModule.noChannelsSelected': 'Sin canales específicos seleccionados: pueden salir en cualquiera.',
  },
  en: {
    'dash.frasesModule.title': 'Special phrases',
    'dash.frasesModule.desc': 'Predefined phrases Purgito can mix into its replies or trigger through triggers.',
    'dash.frasesModule.dynamicVars': 'Dynamic variables available in phrases',
    'dash.frasesModule.packsTitle': 'Phrase packs',
    'dash.frasesModule.packsDesc': 'Group themed phrases to assign them to specific channels or trigger them through triggers.',
    'dash.frasesModule.channelsAccordion': 'Channels where general special phrases can appear',
    'dash.frasesModule.noChannelsSelected': 'No specific channels selected: they can appear in any channel.',
  },
});

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
      formGroup(t('dash.frasesModule.title'),
        el('p', { class: 'dim' }, t('dash.frasesModule.desc')),
        frasesBox,
        accordionGroup(t('dash.frasesModule.dynamicVars'), false,
          el('div', { class: 'tag-list' },
            TAGS.map(tag => el('code', { class: 'cmd' }, tag))
          )
        )
      ),
      formGroup(t('dash.frasesModule.packsTitle'),
        el('p', { class: 'dim' }, t('dash.frasesModule.packsDesc')),
        packsBox
      ),
      accordionGroup(t('dash.frasesModule.channelsAccordion'), false,
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
          listBelow: t('dash.frasesModule.noChannelsSelected'),
        })
      )
    );
  } catch (e) { if (box) renderError(box, e); }
}

addStrings({
  es: {
    'dash.canalesModule.colSpeakShort': 'Habla',
    'dash.canalesModule.colSpeakOn': 'habla por su cuenta acá',
    'dash.canalesModule.colSpeakOff': 'ya no habla solo acá',
    'dash.canalesModule.colSpeakHelp': 'Purgito puede arrancar una charla por su cuenta en este canal. Sin ningún canal marcado, puede hacerlo en todos.',
    'dash.canalesModule.colReplyShort': 'Responde',
    'dash.canalesModule.colReplyOn': 'responde menciones acá',
    'dash.canalesModule.colReplyOff': 'ya no responde menciones acá',
    'dash.canalesModule.colReplyHelp': 'Purgito contesta cuando lo mencionan en este canal. Sin ningún canal marcado, responde en todos.',
    'dash.canalesModule.colLearnShort': 'Aprende',
    'dash.canalesModule.colLearnOn': 'aprende de acá',
    'dash.canalesModule.colLearnOff': 'ya no aprende de acá',
    'dash.canalesModule.colLearnHelp': 'Purgito guarda los mensajes de este canal para armar su estilo. Sin ningún canal marcado, no aprende de nada.',
    'dash.canalesModule.ovrEvery': 'Cada cuántos mensajes',
    'dash.canalesModule.ovrEverySuffix': 'mensajes',
    'dash.canalesModule.ovrTalkProb': 'Probabilidad de hablar',
    'dash.canalesModule.ovrGifProb': 'Responde con GIF',
    'dash.canalesModule.ovrFraseProb': 'Usa una frase especial',
    'dash.canalesModule.ovrReactionProb': 'Reacciona con emoji',
    'dash.canalesModule.ovrMentionLimit': 'Menciones por hora',
    'dash.canalesModule.ovrMentionLimitSuffix': 'por usuario',
    'dash.canalesModule.matrixTitle': 'Matriz de canales',
    'dash.canalesModule.silencedOne': 'Hay 1 canal silenciado desde /settings: queda fuera aunque lo marques acá.',
    'dash.canalesModule.silencedMany': 'Hay {count} canales silenciados desde /settings: quedan fuera aunque los marques acá.',
    'dash.canalesModule.exemptionsTitle': 'Exenciones de límites',
    'dash.canalesModule.exemptRolesLabel': 'Roles exentos de límites de menciones',
    'dash.canalesModule.noExemptRoles': 'Ningún rol exento: el límite aplica a todos por igual.',
    'dash.canalesModule.exemptChannelsLabel': 'Canales exentos de límites de menciones',
    'dash.canalesModule.noExemptChannels': 'Ningún canal exento: el límite aplica en todos.',
  },
  en: {
    'dash.canalesModule.colSpeakShort': 'Speaks',
    'dash.canalesModule.colSpeakOn': 'speaks on its own here',
    'dash.canalesModule.colSpeakOff': 'no longer speaks on its own here',
    'dash.canalesModule.colSpeakHelp': "Purgito can start a conversation on its own in this channel. With no channel checked, it can do so in all of them.",
    'dash.canalesModule.colReplyShort': 'Replies',
    'dash.canalesModule.colReplyOn': 'replies to mentions here',
    'dash.canalesModule.colReplyOff': 'no longer replies to mentions here',
    'dash.canalesModule.colReplyHelp': "Purgito replies when mentioned in this channel. With no channel checked, it replies in all of them.",
    'dash.canalesModule.colLearnShort': 'Learns',
    'dash.canalesModule.colLearnOn': 'learns from here',
    'dash.canalesModule.colLearnOff': 'no longer learns from here',
    'dash.canalesModule.colLearnHelp': "Purgito saves messages from this channel to build its style. With no channel checked, it doesn't learn from any.",
    'dash.canalesModule.ovrEvery': 'Every how many messages',
    'dash.canalesModule.ovrEverySuffix': 'messages',
    'dash.canalesModule.ovrTalkProb': 'Probability of speaking',
    'dash.canalesModule.ovrGifProb': 'Replies with GIF',
    'dash.canalesModule.ovrFraseProb': 'Uses a special phrase',
    'dash.canalesModule.ovrReactionProb': 'Reacts with emoji',
    'dash.canalesModule.ovrMentionLimit': 'Mentions per hour',
    'dash.canalesModule.ovrMentionLimitSuffix': 'per user',
    'dash.canalesModule.matrixTitle': 'Channel matrix',
    'dash.canalesModule.silencedOne': "There's 1 channel muted via /settings: it stays excluded even if you check it here.",
    'dash.canalesModule.silencedMany': 'There are {count} channels muted via /settings: they stay excluded even if you check them here.',
    'dash.canalesModule.exemptionsTitle': 'Limit exemptions',
    'dash.canalesModule.exemptRolesLabel': 'Roles exempt from mention limits',
    'dash.canalesModule.noExemptRoles': 'No role exempt: the limit applies equally to everyone.',
    'dash.canalesModule.exemptChannelsLabel': 'Channels exempt from mention limits',
    'dash.canalesModule.noExemptChannels': 'No channel exempt: the limit applies to all of them.',
  },
});

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
        short: t('dash.canalesModule.colSpeakShort'), onLabel: t('dash.canalesModule.colSpeakOn'), offLabel: t('dash.canalesModule.colSpeakOff'),
        help: t('dash.canalesModule.colSpeakHelp'),
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
        short: t('dash.canalesModule.colReplyShort'), onLabel: t('dash.canalesModule.colReplyOn'), offLabel: t('dash.canalesModule.colReplyOff'),
        help: t('dash.canalesModule.colReplyHelp'),
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
        short: t('dash.canalesModule.colLearnShort'), onLabel: t('dash.canalesModule.colLearnOn'), offLabel: t('dash.canalesModule.colLearnOff'),
        help: t('dash.canalesModule.colLearnHelp'),
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
            key: 'auto_generate_every', label: t('dash.canalesModule.ovrEvery'), kind: 'number',
            effective: eff.auto_generate_every, override: ov.auto_generate_every,
            min: rng('auto_generate_every', [1])[0], max: rng('auto_generate_every', [null, 1000])[1],
            suffix: t('dash.canalesModule.ovrEverySuffix'),
          }),
          channelOverrideRow(ch.id, {
            key: 'auto_generate_probability', label: t('dash.canalesModule.ovrTalkProb'), kind: 'percent',
            effective: eff.auto_generate_probability, override: ov.auto_generate_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'gif_response_probability', label: t('dash.canalesModule.ovrGifProb'), kind: 'percent',
            effective: eff.gif_response_probability, override: ov.gif_response_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'frase_probability', label: t('dash.canalesModule.ovrFraseProb'), kind: 'percent',
            effective: eff.frase_probability, override: ov.frase_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'reaction_probability', label: t('dash.canalesModule.ovrReactionProb'), kind: 'percent',
            effective: eff.reaction_probability, override: ov.reaction_probability, suffix: '%',
          }),
          channelOverrideRow(ch.id, {
            key: 'mention_rate_limit', label: t('dash.canalesModule.ovrMentionLimit'), kind: 'number',
            effective: eff.mention_rate_limit, override: ov.mention_rate_limit,
            min: rng('mention_rate_limit', [0])[0], max: rng('mention_rate_limit', [null, 1000])[1],
            suffix: t('dash.canalesModule.ovrMentionLimitSuffix'),
          })
        )
      );
    }

    const matrixNode = channelMatrix({ channels: channels || [], cols, openOverrides });

    const exemptSelected = new Set(((exempt && exempt.roles) || []).map(r => r.id));
    const exemptChannelsSelected = new Set(((exemptChans && exemptChans.channels) || []).map(c => c.id));

    box.append(
      formGroup(t('dash.canalesModule.matrixTitle'),
        ignoredSet.size
          ? el('p', { class: 'dim' }, ignoredSet.size === 1
            ? t('dash.canalesModule.silencedOne')
            : t('dash.canalesModule.silencedMany', { count: ignoredSet.size }))
          : null,
        matrixNode
      ),
      formGroup(t('dash.canalesModule.exemptionsTitle'),
        el('div', { class: 'field' },
          el('label', {}, t('dash.canalesModule.exemptRolesLabel')),
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
            listBelow: t('dash.canalesModule.noExemptRoles'),
          })
        ),
        el('div', { class: 'field' },
          el('label', {}, t('dash.canalesModule.exemptChannelsLabel')),
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
            listBelow: t('dash.canalesModule.noExemptChannels'),
          })
        )
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

function renderExcludedUsersList(container, users, onRefresh) {
  container.innerHTML = '';
  const list = el('div', { class: 'excluded-users-list' });

  if (!users || !users.length) {
    list.append(el('p', { class: 'dim empty-muted' }, 'Ningún usuario excluido en este servidor.'));
  } else {
    for (const u of users) {
      let badgeText = '';
      if (u.exclude_interaction && u.exclude_learning) {
        badgeText = 'No responde ni aprende';
      } else if (u.exclude_interaction) {
        badgeText = 'No responde';
      } else if (u.exclude_learning) {
        badgeText = 'No aprende';
      }

      const row = el('div', { class: 'excluded-user-row' },
        el('div', { class: 'excluded-user-info' },
          u.avatar_url
            ? el('img', { src: u.avatar_url, alt: u.user_name, class: 'excluded-user-avatar', loading: 'lazy' })
            : el('span', { class: 'excluded-user-avatar excluded-user-avatar--fallback' }, icon('user')),
          el('div', { class: 'excluded-user-names' },
            el('strong', { class: 'excluded-user-name' }, u.user_name),
            el('span', { class: 'dim excluded-user-id' }, u.user_id)
          )
        ),
        el('div', { class: 'excluded-user-badge-wrap' },
          el('span', { class: 'badge badge-dim' }, badgeText)
        ),
        el('div', { class: 'excluded-user-actions' },
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            onclick: () => openEditExcludedUserModal(u, onRefresh),
          }, 'Editar'),
          confirmDelBtn('¿Quitar la exclusión de este usuario?', async () => {
            try {
              await apiFetch(`/api/server/${GUILD_ID}/settings/excluded-users/${u.user_id}`, {
                method: 'DELETE',
              });
              toast('Exclusión eliminada', 'ok');
              await onRefresh();
            } catch (err) {
              toast(humanError(err) || 'No se pudo quitar la exclusión', 'err');
            }
          })
        )
      );
      list.append(row);
    }
  }

  const addBtn = el('button', {
    type: 'button',
    class: 'btn btn-secondary',
    onclick: () => openAddExcludedUserModal(onRefresh),
  }, '+ Añadir usuario');

  container.append(list, el('div', { class: 'excluded-users-add-wrap' }, addBtn));
}

function openAddExcludedUserModal(onRefresh) {
  let selectedUser = null;
  let searchTimeout = null;

  const searchInput = el('input', {
    type: 'text',
    class: 'input',
    placeholder: 'Escribe un ID de Discord o busca por nombre…',
    autocomplete: 'off',
  });

  const resultsBox = el('div', { class: 'user-search-results' });
  const selectedBox = el('div', { class: 'user-selected-preview' });

  function setSelected(u) {
    selectedUser = u;
    resultsBox.innerHTML = '';
    selectedBox.innerHTML = '';
    if (u) {
      selectedBox.append(
        el('div', { class: 'user-selected-card' },
          u.avatar_url
            ? el('img', { src: u.avatar_url, alt: u.name || u.user_name, class: 'excluded-user-avatar', loading: 'lazy' })
            : el('span', { class: 'excluded-user-avatar excluded-user-avatar--fallback' }, icon('user')),
          el('div', { class: 'user-selected-text' },
            el('strong', {}, u.name || u.user_name),
            el('span', { class: 'dim' }, `ID: ${u.id || u.user_id}`)
          ),
          el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            onclick: () => setSelected(null),
          }, 'Cambiar')
        )
      );
      searchInput.value = '';
      searchInput.style.display = 'none';
    } else {
      searchInput.style.display = '';
      searchInput.focus();
    }
  }

  searchInput.oninput = () => {
    const q = searchInput.value.trim();
    if (searchTimeout) clearTimeout(searchTimeout);
    if (!q) {
      resultsBox.innerHTML = '';
      return;
    }
    searchTimeout = setTimeout(async () => {
      try {
        const searchPath = `/api/server/${GUILD_ID}/members/search`;
        const res = await apiFetch(searchPath + `?q=${encodeURIComponent(q)}`);
        resultsBox.innerHTML = '';
        if (res.members && res.members.length) {
          for (const m of res.members) {
            const item = el('div', {
              class: 'user-search-item',
              onclick: () => setSelected(m),
            },
              m.avatar_url
                ? el('img', { src: m.avatar_url, alt: m.name, class: 'excluded-user-avatar-sm', loading: 'lazy' })
                : el('span', { class: 'excluded-user-avatar-sm' }, icon('user')),
              el('span', { class: 'user-search-name' }, m.name),
              el('span', { class: 'dim user-search-id' }, m.id)
            );
            resultsBox.append(item);
          }
        } else if (/^\d{17,20}$/.test(q)) {
          const item = el('div', {
            class: 'user-search-item',
            onclick: () => setSelected({ id: q, name: `Usuario (${q})`, avatar_url: null }),
          },
            el('span', {}, icon('user')),
            el('span', { class: 'user-search-name' }, `Usar ID: ${q}`)
          );
          resultsBox.append(item);
        } else {
          resultsBox.append(el('p', { class: 'dim user-search-empty' }, 'No se encontraron usuarios con ese nombre o ID.'));
        }
      } catch (err) {
        resultsBox.innerHTML = '';
      }
    }, 250);
  };

  const modeRadios = [
    {
      id: 'exc_both',
      value: 'both',
      title: 'Bloquear ambas (No responder ni aprender)',
      desc: 'Purgito no interactuará con este usuario ni aprenderá de sus mensajes.',
      checked: true,
    },
    {
      id: 'exc_inter',
      value: 'interaction',
      title: 'No responder a este usuario',
      desc: 'El bot no responderá a sus menciones, no reaccionará ni activará triggers.',
      checked: false,
    },
    {
      id: 'exc_learn',
      value: 'learning',
      title: 'No aprender de este usuario',
      desc: 'Sus mensajes nuevos no entrarán en el aprendizaje del servidor ni se usarán en Markov.',
      checked: false,
    },
  ];

  const radioGroup = el('div', { class: 'excluded-options-group' });
  const radioInputs = {};

  for (const opt of modeRadios) {
    const radio = el('input', {
      type: 'radio',
      name: 'exclusion_type',
      id: opt.id,
      value: opt.value,
      checked: opt.checked,
    });
    radioInputs[opt.value] = radio;
    const label = el('label', { for: opt.id, class: 'excluded-option-card' },
      radio,
      el('div', { class: 'excluded-option-text' },
        el('strong', {}, opt.title),
        el('p', { class: 'dim' }, opt.desc)
      )
    );
    radioGroup.append(label);
  }

  let modal = null;

  const saveBtn = el('button', {
    type: 'button',
    class: 'btn btn-primary',
    onclick: async () => {
      let uid = selectedUser ? (selectedUser.id || selectedUser.user_id) : searchInput.value.trim();
      if (!uid) {
        toast('Debes seleccionar o ingresar un ID de usuario', 'err');
        return;
      }
      const mode = Object.keys(radioInputs).find(k => radioInputs[k].checked) || 'both';
      const excludeInteraction = mode === 'both' || mode === 'interaction';
      const excludeLearning = mode === 'both' || mode === 'learning';

      saveBtn.disabled = true;
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/excluded-users`, {
          method: 'POST',
          body: {
            user_id: uid,
            exclude_interaction: excludeInteraction,
            exclude_learning: excludeLearning,
          },
        });
        toast('Usuario excluido correctamente', 'ok');
        if (modal) modal.remove();
        await onRefresh();
      } catch (err) {
        saveBtn.disabled = false;
        toast(humanError(err) || 'No se pudo guardar la exclusión', 'err');
      }
    },
  }, 'Guardar exclusión');

  const modalBody = el('div', { class: 'excluded-user-modal-body' },
    el('div', { class: 'field' },
      el('label', {}, 'Usuario del servidor'),
      searchInput,
      resultsBox,
      selectedBox
    ),
    el('div', { class: 'field' },
      el('label', {}, 'Tipo de exclusión'),
      radioGroup
    ),
    el('p', { class: 'dim note' }, 'ⓘ Esta configuración afecta únicamente a este servidor.'),
    el('div', { class: 'modal-actions' },
      saveBtn,
      el('button', {
        type: 'button',
        class: 'btn btn-secondary',
        onclick: () => { if (modal) modal.remove(); },
      }, 'Cancelar')
    )
  );

  modal = panelModal('Añadir exclusión de usuario', modalBody);
}

function openEditExcludedUserModal(user, onRefresh) {
  let initialMode = 'both';
  if (user.exclude_interaction && !user.exclude_learning) initialMode = 'interaction';
  else if (!user.exclude_interaction && user.exclude_learning) initialMode = 'learning';

  const modeRadios = [
    {
      id: 'edit_exc_both',
      value: 'both',
      title: 'Bloquear ambas (No responder ni aprender)',
      desc: 'Purgito no interactuará con este usuario ni aprenderá de sus mensajes.',
      checked: initialMode === 'both',
    },
    {
      id: 'edit_exc_inter',
      value: 'interaction',
      title: 'No responder a este usuario',
      desc: 'El bot no responderá a sus menciones, no reaccionará ni activará triggers.',
      checked: initialMode === 'interaction',
    },
    {
      id: 'edit_exc_learn',
      value: 'learning',
      title: 'No aprender de este usuario',
      desc: 'Sus mensajes nuevos no entrarán en el aprendizaje del servidor ni se usarán en Markov.',
      checked: initialMode === 'learning',
    },
  ];

  const radioGroup = el('div', { class: 'excluded-options-group' });
  const radioInputs = {};

  for (const opt of modeRadios) {
    const radio = el('input', {
      type: 'radio',
      name: 'edit_exclusion_type',
      id: opt.id,
      value: opt.value,
      checked: opt.checked,
    });
    radioInputs[opt.value] = radio;
    const label = el('label', { for: opt.id, class: 'excluded-option-card' },
      radio,
      el('div', { class: 'excluded-option-text' },
        el('strong', {}, opt.title),
        el('p', { class: 'dim' }, opt.desc)
      )
    );
    radioGroup.append(label);
  }

  let modal = null;

  const saveBtn = el('button', {
    type: 'button',
    class: 'btn btn-primary',
    onclick: async () => {
      const mode = Object.keys(radioInputs).find(k => radioInputs[k].checked) || 'both';
      const excludeInteraction = mode === 'both' || mode === 'interaction';
      const excludeLearning = mode === 'both' || mode === 'learning';

      saveBtn.disabled = true;
      try {
        await apiFetch(`/api/server/${GUILD_ID}/settings/excluded-users/${user.user_id}`, {
          method: 'PUT',
          body: {
            exclude_interaction: excludeInteraction,
            exclude_learning: excludeLearning,
          },
        });
        toast('Exclusión actualizada', 'ok');
        if (modal) modal.remove();
        await onRefresh();
      } catch (err) {
        saveBtn.disabled = false;
        toast(humanError(err) || 'No se pudo actualizar la exclusión', 'err');
      }
    },
  }, 'Guardar cambios');

  const modalBody = el('div', { class: 'excluded-user-modal-body' },
    el('div', { class: 'user-selected-card' },
      user.avatar_url
        ? el('img', { src: user.avatar_url, alt: user.user_name, class: 'excluded-user-avatar', loading: 'lazy' })
        : el('span', { class: 'excluded-user-avatar excluded-user-avatar--fallback' }, icon('user')),
      el('div', { class: 'user-selected-text' },
        el('strong', {}, user.user_name),
        el('span', { class: 'dim' }, `ID: ${user.user_id}`)
      )
    ),
    el('div', { class: 'field' },
      el('label', {}, 'Tipo de exclusión'),
      radioGroup
    ),
    el('p', { class: 'dim note' }, 'ⓘ Esta configuración afecta únicamente a este servidor.'),
    el('div', { class: 'modal-actions' },
      saveBtn,
      el('button', {
        type: 'button',
        class: 'btn btn-secondary',
        onclick: () => { if (modal) modal.remove(); },
      }, 'Cancelar')
    )
  );

  modal = panelModal(`Editar exclusión: ${user.user_name}`, modalBody);
}

async function loadChatTab() {
  // Manejo de compatibilidad con hashes antiguos (#reacciones, #contenido, etc.)
  const hash = location.hash.slice(1);
  if (hash === 'reacciones') { activate('reacciones', true); return; }
  if (hash === 'contenido' || hash === 'frases') { activate('frases', true); return; }
  if (hash === 'triggers') { activate('triggers', true); return; }
  if (hash === 'canales') { activate('canales', true); return; }
  if (hash === 'datos' || hash === 'corpus') { activate('canales', true); return; }
  if (hash === 'amnesia') { activate('amnesia', true); return; }
  if (hash === 'playground') { activate('playground', true); return; }

  const box = content();
  box.append(spinner());
  const epoch = _loadEpoch;

  try {
    const [chat, exempt, exemptChans, excludedData, channels, roles] =
      await Promise.all([
        apiFetch(`/api/server/${GUILD_ID}/settings/chat`),
        apiFetch(`/api/server/${GUILD_ID}/settings/exempt-roles`),
        apiFetch(`/api/server/${GUILD_ID}/settings/exempt-channels`),
        apiFetch(`/api/server/${GUILD_ID}/settings/excluded-users`),
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

    // Exclusión de usuarios
    const excludedUsersContainer = el('div', { class: 'excluded-users-container' });
    const refreshExcluded = async () => {
      try {
        const res = await apiFetch(`/api/server/${GUILD_ID}/settings/excluded-users`);
        renderExcludedUsersList(excludedUsersContainer, res.users || [], refreshExcluded);
      } catch (err) {
        toast('Error al recargar exclusiones', 'err');
      }
    };
    renderExcludedUsersList(excludedUsersContainer, (excludedData && excludedData.users) || [], refreshExcluded);

    const excludedSection = formGroup('Exclusión de usuarios',
      el('p', { class: 'dim' }, 'Excluye a miembros concretos de las respuestas de Purgito, de su aprendizaje o de ambos. Esta configuración afecta únicamente a este servidor.'),
      excludedUsersContainer
    );

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

    box.append(comportamientoSection, limitesSection, excludedSection, toolsSection);
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

export async function openAddEmojiModal(box, pool) {
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
  return overlay;
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
        type: 'button',
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
        type: 'button',
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



// ---------------- MEMES ----------------

function loadMemes() {
  const box = content();
  box.append(emptyState('Generación de memes en proceso.'));
}
