// Página de cuenta (/es/perfil, /es/perfil/servidores, /es/perfil/conexiones, /es/perfil/facturacion):
// header compacto, tabs y contenido por tab. Los tabs son links reales a cuatro
// páginas estáticas distintas — no hay SPA que valga la pena acá.
//
// Los datos del usuario salen de /api/me (la misma llamada que usa el navbar);
// antes venían como data-attributes que inyectaba el servidor, pero estas
// páginas ya no se renderizan por request.

import { apiFetch } from '/js/core/api.js';
import { el, spinner, emptyState, renderError, guildIcon, toast } from '/js/core/dom.js';
import { currentLocale, formatDate } from '/js/core/config.js';

const TABS = [
  { key: 'perfil', label: 'Perfil', path: '' },
  { key: 'servidores', label: 'Servidores', path: '/servidores' },
  { key: 'conexiones', label: 'Conexiones', path: '/conexiones' },
  { key: 'facturacion', label: 'Facturación', path: '/facturacion' },
];

const INVITE = 'https://discord.com/oauth2/authorize?client_id=1471724794411089920';
const SUPPORT = 'https://discord.gg/5U7HKyxnBv';

// Fecha de creación de la cuenta a partir del snowflake de Discord.
function accountCreated(userId) {
  try {
    const ms = Number((BigInt(userId) >> 22n) + 1420070400000n);
    return formatDate(new Date(ms), { year: 'numeric', month: 'long' });
  } catch (e) { return null; }
}

function header(me, tab, locale) {
  const created = accountCreated(me.user_id);
  const metaItems = [
    el('li', {}, 'Usuario de Discord'),
    created ? el('li', {}, `En Discord desde ${created}`) : null,
    me.email ? el('li', {}, me.email) : null,
  ].filter(Boolean);

  return el('section', { class: 'pf-head' },
    el('div', { class: 'pf-hero' },
      me.avatar_url ? el('img', { class: 'pf-avatar-lg', src: me.avatar_url, alt: me.name || '' }) : null,
      el('div', { class: 'pf-hero-info' },
        el('h1', { class: 'pf-hero-name' }, me.name || 'Tu cuenta'),
        el('ul', { class: 'pf-meta dim' }, metaItems))),
    el('nav', { class: 'pf-tabs', 'aria-label': 'Pestañas de cuenta' },
      TABS.map(t => el('a', {
        class: 'pf-tab' + (t.key === tab ? ' active' : ''),
        href: `/${locale}/perfil${t.path}`,
        'aria-current': t.key === tab ? 'page' : null,
      }, t.label))));
}

async function tabPerfil(box, me, locale) {
  const summaryGrid = el('div', { class: 'pf-summary-grid' });
  box.append(
    el('div', { class: 'pf-overview' },
      el('h2', { class: 'pf-section-title' }, 'Resumen de la cuenta'),
      summaryGrid));

  summaryGrid.append(spinner());

  try {
    const guilds = await apiFetch('/api/me/guilds');
    const configuredCount = (guilds.configured || []).length;
    const premiumCount = (guilds.configured || []).filter(g => g.is_premium).length;
    const totalManageable = configuredCount + (guilds.available || []).length;

    summaryGrid.innerHTML = '';
    summaryGrid.append(
      el('div', { class: 'pf-stat-card' },
        el('div', { class: 'pf-stat-header' },
          el('span', { class: 'pf-stat-label' }, 'Servidores administrados'),
          el('a', { class: 'pf-stat-link', href: `/${locale}/perfil/servidores` }, 'Ver servidores →')),
        el('div', { class: 'pf-stat-val' }, String(configuredCount)),
        el('div', { class: 'pf-stat-sub dim' },
          totalManageable > configuredCount
            ? `${configuredCount} con Purgito activo de ${totalManageable} disponibles`
            : `${configuredCount} servidores configurados`)),

      el('div', { class: 'pf-stat-card' },
        el('div', { class: 'pf-stat-header' },
          el('span', { class: 'pf-stat-label' }, 'Suscripciones Premium'),
          el('a', { class: 'pf-stat-link', href: `/${locale}/perfil/facturacion` }, 'Facturación →')),
        el('div', { class: 'pf-stat-val' },
          premiumCount > 0 ? `${premiumCount} ${premiumCount === 1 ? 'activo' : 'activos'}` : 'Sin planes activos'),
        el('div', { class: 'pf-stat-sub dim' },
          premiumCount > 0
            ? 'En tus servidores configurados'
            : el('a', { href: `/${locale}/premium`, class: 'link-accent' }, 'Conoce Purgito Premium'))),

      el('div', { class: 'pf-stat-card pf-stat-card--wide' },
        el('div', { class: 'pf-stat-header' },
          el('span', { class: 'pf-stat-label' }, 'Datos de la cuenta de Discord')),
        el('div', { class: 'pf-account-details' },
          el('div', { class: 'pf-acc-item' },
            el('span', { class: 'pf-acc-label' }, 'ID de Discord'),
            el('span', { class: 'pf-acc-val pf-mono' }, me.user_id || 'No disponible')),
          el('div', { class: 'pf-acc-item' },
            el('span', { class: 'pf-acc-label' }, 'Correo electrónico'),
            el('span', { class: 'pf-acc-val' }, me.email || 'No disponible')),
          accountCreated(me.user_id) ? el('div', { class: 'pf-acc-item' },
            el('span', { class: 'pf-acc-label' }, 'Miembro en Discord'),
            el('span', { class: 'pf-acc-val' }, `Desde ${accountCreated(me.user_id)}`)) : null
        ))
    );
  } catch (e) {
    summaryGrid.innerHTML = '';
    renderError(summaryGrid, e);
  }
}

function actionButtons(onReload) {
  const reload = el('button', {
    class: 'btn btn-secondary',
    type: 'button',
    onclick: async () => {
      // Deshabilitado mientras vuela: el refresh salta el cache de 5 min y
      // pega contra Discord, que limita ese endpoint a ~1 req/s por token.
      reload.disabled = true;
      try { await onReload(); } finally { reload.disabled = false; }
    },
  }, 'Recargar');
  return el('div', { class: 'pf-actions' },
    el('a', { class: 'btn btn-primary', href: INVITE, target: '_blank', rel: 'noopener' }, 'Invitar a Purgito'),
    el('a', { class: 'btn btn-secondary', href: SUPPORT, target: '_blank', rel: 'noopener' }, 'Servidor de soporte'),
    reload);
}

function selectedPremiumPlan() {
  const plan = new URLSearchParams(location.search).get('plan');
  return plan === 'monthly' || plan === 'annual' ? plan : null;
}

function serverCard(g, configured, locale, plan) {
  const dashboardHref = `/${locale}/dashboard/${g.id}${plan ? `/premium?plan=${plan}` : ''}`;
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
      ? el('a', { class: 'btn btn-primary', href: dashboardHref }, plan ? 'Elegir este servidor' : 'Dashboard')
      : el('a', { class: 'btn btn-secondary', href: g.invite_url, target: '_blank', rel: 'noopener' }, 'Invitar a Purgito'));
}

async function tabServidores(box, locale) {
  const plan = selectedPremiumPlan();
  const search = el('input', {
    type: 'search', class: 'pf-search', placeholder: 'Buscar por nombre o ID…',
  });
  const grid = el('div', { class: 'card-grid' });
  let all = [];

  function render() {
    const q = search.value.trim().toLowerCase();
    grid.innerHTML = '';
    const hits = all.filter(([g]) =>
      !q || (g.name || '').toLowerCase().includes(q) || g.id.includes(q));
    if (!hits.length) grid.append(emptyState('Ningún servidor coincide con la búsqueda.'));
    for (const [g, conf] of hits) grid.append(serverCard(g, conf, locale, plan));
  }

  /* `force` manda ?refresh=1, que hace que el backend vuelva a preguntarle la
     lista a Discord en vez de servir su cache de 5 min. Sin eso el botón sería
     decorativo justo cuando más se usa: recién invitaste a Purgito a un
     servidor y quieres verlo aparecer. El texto del buscador se conserva. */
  async function load(force) {
    grid.innerHTML = '';
    grid.append(spinner());
    try {
      const guilds = await apiFetch('/api/me/guilds' + (force ? '?refresh=1' : ''));
      all = [
        ...guilds.configured.map(g => [g, true]),
        ...guilds.available.map(g => [g, false]),
      ];
      render();
      if (force) toast('Lista de servidores actualizada', 'ok');
    } catch (e) {
      grid.innerHTML = '';
      renderError(grid, e);
      if (force) toast('No se pudo actualizar la lista, intenta de nuevo', 'err');
    }
  }

  search.oninput = render;
  box.append(
    el('div', { class: 'pf-toolbar' }, search, actionButtons(() => load(true))),
    grid);
  await load(false);
}

function tabConexiones(box) {
  box.append(emptyState('Función aún no disponible..'));
}

function premiumUpsellCard(locale) {
  return el('a', { class: 'pf-upsell', href: `/${locale}/premium` },
    el('div', { class: 'pf-upsell-copy' },
      el('h2', {}, 'Sumate a Premium'),
      el('p', { class: 'dim' }, 'Sube los límites de Purgito y desbloquea los memes automáticos en tus servidores.')),
    el('div', { class: 'pf-upsell-brands' },
      ['visa', 'mastercard', 'americanexpress', 'discover'].map(b =>
        el('img', { src: `/assets/${b}.svg`, alt: b, loading: 'lazy' }))));
}

async function tabFacturacion(box, locale) {
  box.append(spinner());
  let guilds;
  try { guilds = await apiFetch('/api/me/guilds'); }
  catch (e) { return renderError(box, e); }
  box.innerHTML = '';
  const withPremium = guilds.configured.filter(g => g.is_premium);
  if (!withPremium.length) {
    box.append(premiumUpsellCard(locale));
    return;
  }
  box.append(el('div', { class: 'pf-billing' },
    premiumUpsellCard(locale),
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
      'cambiar de plan o descargar recibos.')));
}

export async function initPerfil() {
  const locale = currentLocale();
  const params = new URLSearchParams(location.search);
  // Compatibilidad: si entran a /es/perfil con ?plan=... o ?share=..., redirigir a servidores
  if (!location.pathname.includes('/servidores') && !location.pathname.includes('/conexiones') && !location.pathname.includes('/facturacion') && (params.has('plan') || params.has('share'))) {
    location.replace(`/${locale}/perfil/servidores${location.search}`);
    return;
  }

  const seg = location.pathname.split('/')[3] || 'perfil';
  const tab = TABS.some(t => t.key === seg) ? seg : 'perfil';
  const main = document.getElementById('contenido');

  let me = {};
  try { me = await apiFetch('/api/me'); } catch (e) { /* header degradado, no fatal */ }
  // /api/me responde 200 con logged_in:false en vez de 401 (así el navbar no
  // ensucia la consola), así que el redirect a login se decide acá.
  if (me && me.logged_in === false) {
    location.href = '/auth/login';
    return;
  }
  main.append(header(me, tab, locale));

  const box = el('div', { class: 'pf-content' });
  main.append(box);
  if (tab === 'perfil') await tabPerfil(box, me, locale);
  else if (tab === 'conexiones') tabConexiones(box);
  else if (tab === 'facturacion') await tabFacturacion(box, locale);
  else await tabServidores(box, locale);
}

initPerfil();
