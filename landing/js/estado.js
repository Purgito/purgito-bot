// /es/estado — página pública, sin login. A propósito NO importa nada de
// js/core/ (dom.js/api.js): esos helpers están pensados para el dashboard y
// dependen de clases que solo define dash.css (.toast, .guild-icon, etc.),
// que esta página no carga. Self-contained con DOM plano, mismo espíritu que
// script.js (el script de la homepage).

const REFRESH_MS = 30000;

function fmtUptime(seconds) {
  if (seconds == null) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d${h}h${m}m`;
  if (h > 0) return `${h}h${m}m`;
  return `${m}m`;
}

function fmtMemory(mb) {
  if (mb == null) return '—';
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${mb.toFixed(0)}MB`;
}

function fmtNumber(n) {
  return n == null ? '—' : n.toLocaleString('es');
}

function setDot(dot, ok) {
  dot.classList.remove('is-ok', 'is-down');
  if (ok === true) dot.classList.add('is-ok');
  else if (ok === false) dot.classList.add('is-down');
}

async function loadStatus() {
  const dot = document.getElementById('estadoDot');
  const dotBot = document.getElementById('estadoDotBot');
  const dotWeb = document.getElementById('estadoDotWeb');
  const botDetail = document.getElementById('estadoBotDetail');
  const webDetail = document.getElementById('estadoWebDetail');

  let data = null;
  try {
    const resp = await fetch('/api/status');
    if (!resp.ok) throw new Error('http ' + resp.status);
    data = await resp.json();
  } catch (e) {
    setDot(dot, false);
    setDot(dotBot, false);
    setDot(dotWeb, false);
    botDetail.textContent = 'No se pudo consultar el estado';
    webDetail.textContent = 'No responde';
    return;
  }

  setDot(dotWeb, true);
  webDetail.textContent = 'Operativo';

  const latencyOk = data.latency_ms != null;
  setDot(dotBot, latencyOk);
  botDetail.textContent = latencyOk
    ? `Conectado — ${data.latency_ms} ms de latencia`
    : 'Sin conexión con el gateway de Discord';
  setDot(dot, latencyOk);

  document.getElementById('estadoUptime').textContent = fmtUptime(data.uptime_seconds);
  document.getElementById('estadoMemory').textContent = fmtMemory(data.memory_mb);
  document.getElementById('estadoUsers').textContent = fmtNumber(data.member_count);
  document.getElementById('estadoGuilds').textContent = fmtNumber(data.guild_count);
  document.getElementById('estadoLatency').textContent =
    latencyOk ? `${data.latency_ms} ms` : '— ms';
}

function renderSearchResult(box, guildId) {
  box.innerHTML = '';
  box.append(el('p', 'estado-search-status', 'Buscando…'));

  fetch(`/api/status/guild/${encodeURIComponent(guildId)}`)
    .then((resp) => {
      if (resp.status === 429) throw new Error('rate-limit');
      if (!resp.ok) throw new Error('http-' + resp.status);
      return resp.json();
    })
    .then((data) => {
      box.innerHTML = '';
      if (!data.found) {
        box.append(el('p', 'estado-search-status', 'Purgito no está en ese servidor (o el ID no es correcto).'));
        return;
      }
      const icon = data.icon_url
        ? Object.assign(document.createElement('img'), { className: 'estado-result-icon', src: data.icon_url, alt: '' })
        : el('div', 'estado-result-icon estado-result-initial', (data.name || '?').trim().charAt(0).toUpperCase());
      const card = el('div', 'estado-result-card');
      card.append(icon);
      const copy = el('div', 'estado-result-copy');
      const nameRow = el('div', 'estado-result-name-row');
      nameRow.append(el('strong', '', data.name));
      if (data.premium) nameRow.append(el('span', 'badge', 'Premium'));
      copy.append(nameRow, el('span', 'estado-component-detail', `${fmtNumber(data.member_count)} miembros`));
      card.append(copy);
      box.append(card);
    })
    .catch((e) => {
      box.innerHTML = '';
      const msg = e.message === 'rate-limit'
        ? 'Demasiadas búsquedas — espera un momento e intenta de nuevo.'
        : 'No se pudo completar la búsqueda.';
      box.append(el('p', 'estado-search-status', msg));
    });
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function setupMode() {
  const select = document.getElementById('estadoMode');
  const general = document.getElementById('estadoGeneral');
  const search = document.getElementById('estadoSearch');
  if (!select) return;
  select.addEventListener('change', () => {
    const isSearch = select.value === 'buscar';
    general.hidden = isSearch;
    search.hidden = !isSearch;
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
      result.append(el('p', 'estado-search-status', 'Pega un ID de servidor válido (solo números).'));
      return;
    }
    renderSearchResult(result, id);
  }

  btn.addEventListener('click', run);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
}

setupMode();
setupSearch();
loadStatus();
setInterval(loadStatus, REFRESH_MS);
