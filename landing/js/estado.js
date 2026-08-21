// /es/estado — Monitoreo de estado en vivo de Purgito.
// Script self-contained con DOM nativo, sin dependencias de bundler.

import { t, addStrings } from './core/i18n.js';

addStrings({
  es: {
    'estado.outage': 'Interrupción',
    'estado.serviceOutage': 'Interrupción del servicio',
    'estado.cantConnect': 'No se puede establecer conexión con los servidores de Purgito.',
    'estado.disconnected': 'Desconectado',
    'estado.noServerResponse': 'Sin respuesta del servidor',
    'estado.noResponse': 'Sin respuesta',
    'estado.webNotResponding': 'El servidor web no responde',
    'estado.unknown': 'Desconocido',
    'estado.unreachable': 'Inaccesible',
    'estado.activeIncidentTitle': 'Incidente activo: API inaccesible',
    'estado.activeIncidentDesc': 'No se ha podido consultar el estado de la API de Purgito. Es posible que el servicio esté experimentando una interrupción.',
    'estado.connectionError': 'Error de conexión',
    'estado.updatedAt': 'Actualizado a las {time}',
    'estado.operational': 'Operativo',
    'estado.allSystemsOperational': 'Todos los sistemas operativos',
    'estado.allSubsystemsNormal': 'Purgito y todos sus subsistemas están funcionando con normalidad.',
    'estado.degraded': 'Degradado',
    'estado.degradedPerformance': 'Rendimiento degradado',
    'estado.gatewayIssues': 'El bot está activo pero la conexión con el Gateway de Discord presenta problemas.',
    'estado.connected': 'Conectado',
    'estado.disconnectedShort': 'Sin conexión',
    'estado.gatewayActive': 'Conexión activa con Discord Gateway · Eventos y chat en vivo',
    'estado.gatewayDown': 'Sin conexión con el Gateway de Discord',
    'estado.aiohttpActive': 'Servidor aiohttp activo · purgito.app',
    'estado.normal': 'Normal',
    'estado.engineDetail': 'Cadenas de Markov, generador de memes y tareas de fondo',
    'estado.noIncidents': 'Sin incidentes reportados',
    'estado.allComponentsUptime': 'Todos los componentes han operado continuamente desde el último inicio del proceso ({uptime} activo).',
    'estado.incidentGatewayTitle': 'Incidente: Gateway de Discord no responde',
    'estado.incidentGatewayDesc': 'El servidor web está en línea pero se ha perdido el latido WebSocket con Discord.',
    'estado.checkingServer': 'Consultando servidor…',
    'estado.serverNotFound': 'Servidor no encontrado',
    'estado.serverNotFoundDesc': 'Purgito no está presente en ese servidor o la ID ingresada no es válida.',
    'estado.online': '● En línea',
    'estado.memberCount': '{count} miembros',
    'estado.premium': 'Premium',
    'estado.rateLimited': 'Demasiadas consultas seguidas — espera un momento antes de volver a intentar.',
    'estado.checkFailed': 'No se pudo completar la comprobación del servidor.',
    'estado.invalidGuildId': 'Ingresa una ID de servidor válida (solo números, entre 5 y 25 dígitos).',
  },
  en: {
    'estado.outage': 'Outage',
    'estado.serviceOutage': 'Service outage',
    'estado.cantConnect': 'Unable to connect to Purgito’s servers.',
    'estado.disconnected': 'Disconnected',
    'estado.noServerResponse': 'No response from the server',
    'estado.noResponse': 'No response',
    'estado.webNotResponding': 'The web server is not responding',
    'estado.unknown': 'Unknown',
    'estado.unreachable': 'Unreachable',
    'estado.activeIncidentTitle': 'Active incident: API unreachable',
    'estado.activeIncidentDesc': 'Purgito’s API status could not be checked. The service may be experiencing an outage.',
    'estado.connectionError': 'Connection error',
    'estado.updatedAt': 'Updated at {time}',
    'estado.operational': 'Operational',
    'estado.allSystemsOperational': 'All systems operational',
    'estado.allSubsystemsNormal': 'Purgito and all its subsystems are running normally.',
    'estado.degraded': 'Degraded',
    'estado.degradedPerformance': 'Degraded performance',
    'estado.gatewayIssues': 'The bot is active but the connection to Discord’s Gateway is having issues.',
    'estado.connected': 'Connected',
    'estado.disconnectedShort': 'Disconnected',
    'estado.gatewayActive': 'Active connection to Discord Gateway · Live events and chat',
    'estado.gatewayDown': 'No connection to Discord’s Gateway',
    'estado.aiohttpActive': 'aiohttp server active · purgito.app',
    'estado.normal': 'Normal',
    'estado.engineDetail': 'Markov chains, meme generator, and background tasks',
    'estado.noIncidents': 'No incidents reported',
    'estado.allComponentsUptime': 'All components have been running continuously since the last process start ({uptime} uptime).',
    'estado.incidentGatewayTitle': 'Incident: Discord Gateway not responding',
    'estado.incidentGatewayDesc': 'The web server is online but the WebSocket heartbeat with Discord has been lost.',
    'estado.checkingServer': 'Checking server…',
    'estado.serverNotFound': 'Server not found',
    'estado.serverNotFoundDesc': 'Purgito isn’t in that server, or the ID entered is not valid.',
    'estado.online': '● Online',
    'estado.memberCount': '{count} members',
    'estado.premium': 'Premium',
    'estado.rateLimited': 'Too many requests in a row — wait a moment before trying again.',
    'estado.checkFailed': 'Could not complete the server check.',
    'estado.invalidGuildId': 'Enter a valid server ID (numbers only, between 5 and 25 digits).',
  },
});

const REFRESH_MS = 30000;

function fmtUptime(seconds) {
  if (seconds == null) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtMemory(mb) {
  if (mb == null) return '—';
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}

function fmtNumber(n) {
  return n == null ? '—' : n.toLocaleString('es');
}

function setStatusClasses(el, status) {
  if (!el) return;
  el.classList.remove('is-ok', 'is-warn', 'is-down');
  if (status) el.classList.add(`is-${status}`);
}

function setBadge(el, text, status) {
  if (!el) return;
  el.textContent = text;
  setStatusClasses(el, status);
}

function setDot(el, status) {
  if (!el) return;
  setStatusClasses(el, status);
}

async function loadStatus() {
  const globalDot = document.getElementById('estadoGlobalDot');
  const globalBadge = document.getElementById('estadoGlobalBadge');
  const globalTitle = document.getElementById('estadoGlobalTitle');
  const globalDesc = document.getElementById('estadoGlobalDesc');
  const lastUpdate = document.getElementById('estadoLastUpdate');

  const dotBot = document.getElementById('estadoDotBot');
  const badgeBot = document.getElementById('estadoBotBadge');
  const botDetail = document.getElementById('estadoBotDetail');

  const dotWeb = document.getElementById('estadoDotWeb');
  const badgeWeb = document.getElementById('estadoWebBadge');
  const webDetail = document.getElementById('estadoWebDetail');

  const dotEngine = document.getElementById('estadoDotEngine');
  const badgeEngine = document.getElementById('estadoEngineBadge');
  const engineDetail = document.getElementById('estadoEngineDetail');

  const dotInfraDiscord = document.getElementById('estadoDotInfraDiscord');
  const badgeInfraDiscord = document.getElementById('estadoBadgeInfraDiscord');

  const dotInfraHost = document.getElementById('estadoDotInfraHost');
  const badgeInfraHost = document.getElementById('estadoBadgeInfraHost');

  const dotInfraDb = document.getElementById('estadoDotInfraDb');
  const badgeInfraDb = document.getElementById('estadoBadgeInfraDb');

  const incidentCard = document.getElementById('estadoIncidentCard');
  const incidentTitle = document.getElementById('estadoIncidentTitle');
  const incidentDesc = document.getElementById('estadoIncidentDesc');
  const incidentTag = document.getElementById('estadoIncidentTag');

  const t0 = performance.now();
  let data = null;
  let httpLatency = 0;

  try {
    const resp = await fetch('/api/status');
    httpLatency = Math.max(1, Math.round(performance.now() - t0));
    if (!resp.ok) throw new Error('http-' + resp.status);
    data = await resp.json();
  } catch (e) {
    // Falla total de conectividad con la API
    setDot(globalDot, 'down');
    setBadge(globalBadge, t('estado.outage'), 'down');
    if (globalTitle) globalTitle.textContent = t('estado.serviceOutage');
    if (globalDesc) globalDesc.textContent = t('estado.cantConnect');

    setDot(dotBot, 'down');
    setBadge(badgeBot, t('estado.disconnected'), 'down');
    if (botDetail) botDetail.textContent = t('estado.noServerResponse');

    setDot(dotWeb, 'down');
    setBadge(badgeWeb, t('estado.noResponse'), 'down');
    if (webDetail) webDetail.textContent = t('estado.webNotResponding');

    setDot(dotEngine, 'down');
    setBadge(badgeEngine, t('estado.unknown'), 'down');

    setDot(dotInfraDiscord, 'down');
    setBadge(badgeInfraDiscord, t('estado.unreachable'), 'down');

    setDot(dotInfraHost, 'down');
    setBadge(badgeInfraHost, t('estado.unreachable'), 'down');

    setDot(dotInfraDb, 'down');
    setBadge(badgeInfraDb, t('estado.unknown'), 'down');

    if (incidentCard) {
      incidentCard.classList.remove('is-ok', 'is-warn');
      incidentCard.classList.add('is-down');
    }
    if (incidentTitle) incidentTitle.textContent = t('estado.activeIncidentTitle');
    if (incidentDesc) incidentDesc.textContent = t('estado.activeIncidentDesc');
    if (incidentTag) setBadge(incidentTag, t('estado.outage'), 'down');

    if (lastUpdate) lastUpdate.textContent = t('estado.connectionError');
    return;
  }

  // Web responde OK
  const latencyOk = data.latency_ms != null;
  const now = new Date();
  const timeStr = now.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  if (lastUpdate) {
    lastUpdate.textContent = t('estado.updatedAt', { time: timeStr });
  }

  // 1. Estado Global
  if (latencyOk) {
    setDot(globalDot, 'ok');
    setBadge(globalBadge, t('estado.operational'), 'ok');
    if (globalTitle) globalTitle.textContent = t('estado.allSystemsOperational');
    if (globalDesc) globalDesc.textContent = t('estado.allSubsystemsNormal');
  } else {
    setDot(globalDot, 'warn');
    setBadge(globalBadge, t('estado.degraded'), 'warn');
    if (globalTitle) globalTitle.textContent = t('estado.degradedPerformance');
    if (globalDesc) globalDesc.textContent = t('estado.gatewayIssues');
  }

  // Métricas de resumen
  const elUptime = document.getElementById('estadoUptime');
  const elGuilds = document.getElementById('estadoGuilds');
  const elUsers = document.getElementById('estadoUsers');
  const elLatency = document.getElementById('estadoLatency');

  if (elUptime) elUptime.textContent = fmtUptime(data.uptime_seconds);
  if (elGuilds) elGuilds.textContent = fmtNumber(data.guild_count);
  if (elUsers) elUsers.textContent = fmtNumber(data.member_count);
  if (elLatency) elLatency.textContent = latencyOk ? `${data.latency_ms} ms` : '—';

  // 2. Fila Bot de Discord
  setDot(dotBot, latencyOk ? 'ok' : 'down');
  setBadge(badgeBot, latencyOk ? t('estado.connected') : t('estado.disconnectedShort'), latencyOk ? 'ok' : 'down');
  if (botDetail) {
    botDetail.textContent = latencyOk
      ? t('estado.gatewayActive')
      : t('estado.gatewayDown');
  }
  const elBotLatency = document.getElementById('estadoBotLatency');
  const elBotGuilds = document.getElementById('estadoBotGuilds');
  const elBotMembers = document.getElementById('estadoBotMembers');
  if (elBotLatency) elBotLatency.textContent = latencyOk ? `${data.latency_ms} ms` : '—';
  if (elBotGuilds) elBotGuilds.textContent = fmtNumber(data.guild_count);
  if (elBotMembers) elBotMembers.textContent = fmtNumber(data.member_count);

  // 3. Fila Panel Web y API
  setDot(dotWeb, 'ok');
  setBadge(badgeWeb, t('estado.operational'), 'ok');
  if (webDetail) webDetail.textContent = t('estado.aiohttpActive');
  const elWebLatency = document.getElementById('estadoWebLatency');
  const elWebUptime = document.getElementById('estadoWebUptime');
  if (elWebLatency) elWebLatency.textContent = `${httpLatency} ms`;
  if (elWebUptime) elWebUptime.textContent = fmtUptime(data.uptime_seconds);

  // 4. Fila Proceso y Memoria
  setDot(dotEngine, 'ok');
  setBadge(badgeEngine, t('estado.normal'), 'ok');
  if (engineDetail) engineDetail.textContent = t('estado.engineDetail');
  const elEngineMemory = document.getElementById('estadoEngineMemory');
  const elEngineUptime = document.getElementById('estadoEngineUptime');
  if (elEngineMemory) elEngineMemory.textContent = fmtMemory(data.memory_mb);
  if (elEngineUptime) elEngineUptime.textContent = fmtUptime(data.uptime_seconds);

  // 5. Infraestructura
  setDot(dotInfraDiscord, latencyOk ? 'ok' : 'down');
  setBadge(badgeInfraDiscord, latencyOk ? t('estado.operational') : t('estado.disconnected'), latencyOk ? 'ok' : 'down');
  const elInfraDiscordLat = document.getElementById('estadoInfraDiscordLatency');
  if (elInfraDiscordLat) elInfraDiscordLat.textContent = latencyOk ? `${data.latency_ms} ms` : '—';

  setDot(dotInfraHost, 'ok');
  setBadge(badgeInfraHost, t('estado.operational'), 'ok');
  const elInfraHostMem = document.getElementById('estadoInfraHostMem');
  if (elInfraHostMem) elInfraHostMem.textContent = fmtMemory(data.memory_mb);

  setDot(dotInfraDb, 'ok');
  setBadge(badgeInfraDb, t('estado.operational'), 'ok');

  // 6. Registro de incidentes
  if (incidentCard) {
    incidentCard.classList.remove('is-ok', 'is-warn', 'is-down');
    if (latencyOk) {
      incidentCard.classList.add('is-ok');
      if (incidentTitle) incidentTitle.textContent = t('estado.noIncidents');
      if (incidentDesc) {
        incidentDesc.textContent = t('estado.allComponentsUptime', { uptime: fmtUptime(data.uptime_seconds) });
      }
      if (incidentTag) setBadge(incidentTag, t('estado.operational'), 'ok');
    } else {
      incidentCard.classList.add('is-warn');
      if (incidentTitle) incidentTitle.textContent = t('estado.incidentGatewayTitle');
      if (incidentDesc) {
        incidentDesc.textContent = t('estado.incidentGatewayDesc');
      }
      if (incidentTag) setBadge(incidentTag, t('estado.degraded'), 'warn');
    }
  }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function renderSearchResult(box, guildId) {
  box.innerHTML = '';
  box.append(el('p', 'estado-search-status', t('estado.checkingServer')));

  fetch(`/api/status/guild/${encodeURIComponent(guildId)}`)
    .then((resp) => {
      if (resp.status === 429) throw new Error('rate-limit');
      if (!resp.ok) throw new Error('http-' + resp.status);
      return resp.json();
    })
    .then((data) => {
      box.innerHTML = '';
      if (!data.found) {
        const emptyBox = el('div', 'estado-result-empty');
        emptyBox.append(
          el('strong', 'estado-result-empty-title', t('estado.serverNotFound')),
          el('p', 'estado-search-status', t('estado.serverNotFoundDesc'))
        );
        box.append(emptyBox);
        return;
      }

      const card = el('div', 'estado-result-card');
      const icon = data.icon_url
        ? Object.assign(document.createElement('img'), { className: 'estado-result-icon', src: data.icon_url, alt: '' })
        : el('div', 'estado-result-icon estado-result-initial', (data.name || '?').trim().charAt(0).toUpperCase());

      const copy = el('div', 'estado-result-copy');
      const nameRow = el('div', 'estado-result-name-row');
      nameRow.append(el('strong', 'estado-result-name', data.name));
      if (data.premium) {
        const badge = el('span', 'badge badge-premium', t('estado.premium'));
        nameRow.append(badge);
      }

      const metaRow = el('div', 'estado-result-meta-row');
      metaRow.append(
        el('span', 'estado-result-status-dot', t('estado.online')),
        el('span', 'estado-result-divider', '·'),
        el('span', 'estado-result-members', t('estado.memberCount', { count: fmtNumber(data.member_count) }))
      );

      copy.append(nameRow, metaRow);
      card.append(icon, copy);
      box.append(card);
    })
    .catch((e) => {
      box.innerHTML = '';
      const msg = e.message === 'rate-limit'
        ? t('estado.rateLimited')
        : t('estado.checkFailed');
      const errBox = el('div', 'estado-result-empty');
      errBox.append(el('p', 'estado-search-status is-err', msg));
      box.append(errBox);
    });
}

function setupSearch() {
  const btn = document.getElementById('estadoSearchBtn');
  const input = document.getElementById('estadoGuildId');
  const result = document.getElementById('estadoSearchResult');
  if (!btn || !input || !result) return;

  function run() {
    const id = input.value.trim();
    if (!/^\d{5,25}$/.test(id)) {
      result.innerHTML = '';
      const errBox = el('div', 'estado-result-empty');
      errBox.append(el('p', 'estado-search-status is-err', t('estado.invalidGuildId')));
      result.append(errBox);
      return;
    }
    renderSearchResult(result, id);
  }

  btn.addEventListener('click', run);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      run();
    }
  });
}

setupSearch();
loadStatus();
setInterval(loadStatus, REFRESH_MS);
