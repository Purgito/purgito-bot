// Página de perfil (/es/perfil, /es/perfil/conexiones, /es/perfil/facturacion):
// header de usuario, tabs y contenido por tab. Los tabs son links reales (la
// página es liviana, no hace falta SPA).

import { apiFetch } from './core/api.js';
import { el, spinner, emptyState, renderError, guildIcon } from './core/dom.js';
import { initShell, currentLocale } from './shell.js';

const TABS = [
  { key: 'servidores', label: 'Servidores', path: '' },
  { key: 'conexiones', label: 'Conexiones', path: '/conexiones' },
  { key: 'facturacion', label: 'Facturación', path: '/facturacion' },
];

// Fecha de creación de la cuenta a partir del snowflake de Discord.
function accountCreated(userId) {
  try {
    const ms = Number((BigInt(userId) >> 22n) + 1420070400000n);
    return new Date(ms).toLocaleDateString('es', { year: 'numeric', month: 'long' });
  } catch (e) { return null; }
}

function header(data, tab, locale) {
  const created = accountCreated(data.userId);
  return el('section', { class: 'pf-head' },
    el('div', { class: 'pf-id' },
      el('img', { class: 'pf-avatar', src: data.avatar, alt: '' }),
      el('div', {},
        el('h1', {}, data.username),
        el('div', { class: 'pf-meta dim' },
          created ? `En Discord desde ${created}` : '',
          data.email ? ` · ${data.email}` : ''))),
    el('nav', { class: 'pf-tabs' },
      TABS.map(t => el('a', {
        class: 'pf-tab' + (t.key === tab ? ' active' : ''),
        href: `/${locale}/perfil${t.path}`,
      }, t.label))));
}

function actionButtons(data) {
  return el('div', { class: 'pf-actions' },
    el('a', { class: 'btn btn-primary', href: data.invite, target: '_blank', rel: 'noopener' }, 'Invitar a Purgito'),
    el('a', { class: 'btn btn-secondary', href: data.support, target: '_blank', rel: 'noopener' }, 'Servidor de soporte'),
    // ponytail: Reportar abre el servidor de soporte, no un formulario propio.
    el('a', { class: 'btn btn-secondary', href: data.support, target: '_blank', rel: 'noopener' }, 'Reportar'));
}

function serverCard(g, configured, locale) {
  return el('div', { class: 'card' },
    guildIcon(g),
    el('div', { class: 'card-info' },
      el('div', { class: 'card-name' }, g.name,
        configured && g.is_premium ? el('span', { class: 'badge badge-premium' }, 'PREMIUM') : null),
      el('div', { class: 'card-sub' },
        configured
          ? (g.member_count != null ? g.member_count + ' miembros' : '')
          : 'Purgito no está aquí')),
    configured
      ? el('a', { class: 'btn btn-primary', href: `/${locale}/dashboard/${g.id}` }, 'Dashboard')
      : el('a', { class: 'btn btn-secondary', href: g.invite_url, target: '_blank', rel: 'noopener' }, 'Invitar a Purgito'));
}

async function tabServidores(box, data, locale) {
  box.append(spinner());
  let guilds;
  try { guilds = await apiFetch('/api/me/guilds'); }
  catch (e) { return renderError(box, e); }
  box.innerHTML = '';
  const search = el('input', {
    type: 'search', class: 'pf-search', placeholder: 'Buscar por nombre o ID…',
  });
  const grid = el('div', { class: 'card-grid' });
  const all = [
    ...guilds.configured.map(g => [g, true]),
    ...guilds.available.map(g => [g, false]),
  ];
  function render() {
    const q = search.value.trim().toLowerCase();
    grid.innerHTML = '';
    const hits = all.filter(([g]) =>
      !q || (g.name || '').toLowerCase().includes(q) || g.id.includes(q));
    if (!hits.length) grid.append(emptyState('Ningún servidor coincide con la búsqueda.'));
    for (const [g, conf] of hits) grid.append(serverCard(g, conf, locale));
  }
  search.oninput = render;
  render();
  box.append(el('div', { class: 'pf-toolbar' }, search, actionButtons(data)), grid);
}

function tabConexiones(box) {
  box.append(emptyState('Función aún no disponible..'));
}

function premiumUpsellCard(data, locale) {
  return el('a', {
    class: 'pf-upsell',
    href: `${data.landing}/${locale}/premium`,
  },
    el('div', { class: 'pf-upsell-copy' },
      el('h2', {}, 'Sumate a Premium'),
      el('p', { class: 'dim' }, 'Sube los límites de Purgito y desbloquea los memes automáticos en tus servidores.')),
    el('div', { class: 'pf-upsell-brands' },
      ['visa', 'mastercard', 'americanexpress', 'discover'].map(b =>
        el('img', { src: `/static/img/${b}.svg`, alt: b, loading: 'lazy' }))));
}

async function tabFacturacion(box, data, locale) {
  box.append(spinner());
  let guilds;
  try { guilds = await apiFetch('/api/me/guilds'); }
  catch (e) { return renderError(box, e); }
  box.innerHTML = '';
  const withPremium = guilds.configured.filter(g => g.is_premium);
  if (!withPremium.length) {
    box.append(premiumUpsellCard(data, locale));
    return;
  }
  const list = el('div', { class: 'pf-billing' },
    el('h2', {}, 'Tus servidores con Premium'),
    withPremium.map(g => el('div', { class: 'card' },
      guildIcon(g),
      el('div', { class: 'card-info' },
        el('div', { class: 'card-name' }, g.name,
          el('span', { class: 'badge badge-premium' }, 'PREMIUM')),
        el('div', { class: 'card-sub' }, g.premium_note ? `Plan: ${g.premium_note}` : 'Premium activo')),
      el('a', { class: 'btn btn-secondary', href: `/${locale}/dashboard/${g.id}/premium` }, 'Ver detalle'))),
    el('p', { class: 'dim pf-billing-note' },
      'La suscripción se gestiona en Polar (nuestro procesador de pagos): en el correo de ',
      'confirmación que te envió Polar hay un link a tu portal de cliente para cancelar, ',
      'cambiar de plan o descargar recibos.'));
  box.append(list);
}

export async function initPerfil() {
  const data = initShell();
  data.userId = data.userId || '';
  const locale = currentLocale();
  const seg = location.pathname.split('/')[3] || 'servidores';
  const tab = TABS.some(t => t.key === seg) ? seg : 'servidores';
  const main = document.getElementById('perfilMain');
  main.append(header(data, tab, locale));
  const box = el('div', { class: 'pf-content' });
  main.append(box);
  if (tab === 'conexiones') tabConexiones(box);
  else if (tab === 'facturacion') await tabFacturacion(box, data, locale);
  else await tabServidores(box, data, locale);
}
