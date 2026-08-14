// /es/estado — Monitoreo de estado en vivo de Purgito.
// Script self-contained con DOM nativo, sin dependencias de bundler.

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
    setBadge(globalBadge, 'Interrupción', 'down');
    if (globalTitle) globalTitle.textContent = 'Interrupción del servicio';
    if (globalDesc) globalDesc.textContent = 'No se puede establecer conexión con los servidores de Purgito.';

    setDot(dotBot, 'down');
    setBadge(badgeBot, 'Desconectado', 'down');
    if (botDetail) botDetail.textContent = 'Sin respuesta del servidor';

    setDot(dotWeb, 'down');
    setBadge(badgeWeb, 'Sin respuesta', 'down');
    if (webDetail) webDetail.textContent = 'El servidor web no responde';

    setDot(dotEngine, 'down');
    setBadge(badgeEngine, 'Desconocido', 'down');

    setDot(dotInfraDiscord, 'down');
    setBadge(badgeInfraDiscord, 'Inaccesible', 'down');

    setDot(dotInfraHost, 'down');
    setBadge(badgeInfraHost, 'Inaccesible', 'down');

    setDot(dotInfraDb, 'down');
    setBadge(badgeInfraDb, 'Desconocido', 'down');

    if (incidentCard) {
      incidentCard.classList.remove('is-ok', 'is-warn');
      incidentCard.classList.add('is-down');
    }
    if (incidentTitle) incidentTitle.textContent = 'Incidente activo: API inaccesible';
    if (incidentDesc) incidentDesc.textContent = 'No se ha podido consultar el estado de la API de Purgito. Es posible que el servicio esté experimentando una interrupción.';
    if (incidentTag) setBadge(incidentTag, 'Interrupción', 'down');

    if (lastUpdate) lastUpdate.textContent = 'Error de conexión';
    return;
  }

  // Web responde OK
  const latencyOk = data.latency_ms != null;
  const now = new Date();
  const timeStr = now.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  if (lastUpdate) {
    lastUpdate.textContent = `Actualizado a las ${timeStr}`;
  }

  // 1. Estado Global
  if (latencyOk) {
    setDot(globalDot, 'ok');
    setBadge(globalBadge, 'Operativo', 'ok');
    if (globalTitle) globalTitle.textContent = 'Todos los sistemas operativos';
    if (globalDesc) globalDesc.textContent = 'Purgito y todos sus subsistemas están funcionando con normalidad.';
  } else {
    setDot(globalDot, 'warn');
    setBadge(globalBadge, 'Degradado', 'warn');
    if (globalTitle) globalTitle.textContent = 'Rendimiento degradado';
    if (globalDesc) globalDesc.textContent = 'El bot está activo pero la conexión con el Gateway de Discord presenta problemas.';
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
  setBadge(badgeBot, latencyOk ? 'Conectado' : 'Sin conexión', latencyOk ? 'ok' : 'down');
  if (botDetail) {
    botDetail.textContent = latencyOk
      ? 'Conexión activa con Discord Gateway · Eventos y chat en vivo'
      : 'Sin conexión con el Gateway de Discord';
  }
  const elBotLatency = document.getElementById('estadoBotLatency');
  const elBotGuilds = document.getElementById('estadoBotGuilds');
  const elBotMembers = document.getElementById('estadoBotMembers');
  if (elBotLatency) elBotLatency.textContent = latencyOk ? `${data.latency_ms} ms` : '—';
  if (elBotGuilds) elBotGuilds.textContent = fmtNumber(data.guild_count);
  if (elBotMembers) elBotMembers.textContent = fmtNumber(data.member_count);

  // 3. Fila Panel Web y API
  setDot(dotWeb, 'ok');
  setBadge(badgeWeb, 'Operativo', 'ok');
  if (webDetail) webDetail.textContent = 'Servidor aiohttp activo · purgito.app';
  const elWebLatency = document.getElementById('estadoWebLatency');
  const elWebUptime = document.getElementById('estadoWebUptime');
  if (elWebLatency) elWebLatency.textContent = `${httpLatency} ms`;
  if (elWebUptime) elWebUptime.textContent = fmtUptime(data.uptime_seconds);

  // 4. Fila Proceso y Memoria
  setDot(dotEngine, 'ok');
  setBadge(badgeEngine, 'Normal', 'ok');
  if (engineDetail) engineDetail.textContent = 'Cadenas de Markov, generador de memes y tareas de fondo';
  const elEngineMemory = document.getElementById('estadoEngineMemory');
  const elEngineUptime = document.getElementById('estadoEngineUptime');
  if (elEngineMemory) elEngineMemory.textContent = fmtMemory(data.memory_mb);
  if (elEngineUptime) elEngineUptime.textContent = fmtUptime(data.uptime_seconds);

  // 5. Infraestructura
  setDot(dotInfraDiscord, latencyOk ? 'ok' : 'down');
  setBadge(badgeInfraDiscord, latencyOk ? 'Operativo' : 'Desconectado', latencyOk ? 'ok' : 'down');
  const elInfraDiscordLat = document.getElementById('estadoInfraDiscordLatency');
  if (elInfraDiscordLat) elInfraDiscordLat.textContent = latencyOk ? `${data.latency_ms} ms` : '—';

  setDot(dotInfraHost, 'ok');
  setBadge(badgeInfraHost, 'Operativo', 'ok');
  const elInfraHostMem = document.getElementById('estadoInfraHostMem');
  if (elInfraHostMem) elInfraHostMem.textContent = fmtMemory(data.memory_mb);

  setDot(dotInfraDb, 'ok');
  setBadge(badgeInfraDb, 'Operativo', 'ok');

  // 6. Registro de incidentes
  if (incidentCard) {
    incidentCard.classList.remove('is-ok', 'is-warn', 'is-down');
    if (latencyOk) {
      incidentCard.classList.add('is-ok');
      if (incidentTitle) incidentTitle.textContent = 'Sin incidentes reportados';
      if (incidentDesc) {
        incidentDesc.textContent = `Todos los componentes han operado continuamente desde el último inicio del proceso (${fmtUptime(data.uptime_seconds)} activo).`;
      }
      if (incidentTag) setBadge(incidentTag, 'Operativo', 'ok');
    } else {
      incidentCard.classList.add('is-warn');
      if (incidentTitle) incidentTitle.textContent = 'Incidente: Gateway de Discord no responde';
      if (incidentDesc) {
        incidentDesc.textContent = 'El servidor web está en línea pero se ha perdido el latido WebSocket con Discord.';
      }
      if (incidentTag) setBadge(incidentTag, 'Degradado', 'warn');
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
  box.append(el('p', 'estado-search-status', 'Consultando servidor…'));

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
          el('strong', 'estado-result-empty-title', 'Servidor no encontrado'),
          el('p', 'estado-search-status', 'Purgito no está presente en ese servidor o la ID ingresada no es válida.')
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
        const badge = el('span', 'badge badge-premium', 'Premium');
        nameRow.append(badge);
      }

      const metaRow = el('div', 'estado-result-meta-row');
      metaRow.append(
        el('span', 'estado-result-status-dot', '● En línea'),
        el('span', 'estado-result-divider', '·'),
        el('span', 'estado-result-members', `${fmtNumber(data.member_count)} miembros`)
      );

      copy.append(nameRow, metaRow);
      card.append(icon, copy);
      box.append(card);
    })
    .catch((e) => {
      box.innerHTML = '';
      const msg = e.message === 'rate-limit'
        ? 'Demasiadas consultas seguidas — espera un momento antes de volver a intentar.'
        : 'No se pudo completar la comprobación del servidor.';
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
      errBox.append(el('p', 'estado-search-status is-err', 'Ingresa una ID de servidor válida (solo números, entre 5 y 25 dígitos).'));
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
