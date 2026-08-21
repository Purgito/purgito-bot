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
import { t, addStrings } from './core/i18n.js';

addStrings({
  es: {
    'perfil.tabs.servidores': 'Servidores',
    'perfil.tabs.conexiones': 'Conexiones',
    'perfil.tabs.facturacion': 'Facturación',
    'perfil.tabs.perfil': 'Perfil',
    'perfil.tabsAriaLabel': 'Pestañas de cuenta',
    'perfil.discordUser': 'Usuario de Discord',
    'perfil.onDiscordSince': 'En Discord desde {date}',
    'perfil.defaultName': 'Tu cuenta',
    'perfil.accountSummary': 'Resumen de la cuenta',
    'perfil.managedServers': 'Servidores administrados',
    'perfil.viewServers': 'Ver servidores →',
    'perfil.serversActiveOf': '{configured} con Purgito activo de {total} disponibles',
    'perfil.serversConfigured': '{configured} servidores configurados',
    'perfil.premiumSubs': 'Suscripciones Premium',
    'perfil.billingLink': 'Facturación →',
    'perfil.activeSingular': 'activo',
    'perfil.activePlural': 'activos',
    'perfil.noPlansActive': 'Sin planes activos',
    'perfil.premiumSubsSub': 'En tus servidores configurados',
    'perfil.discoverPremium': 'Conoce Purgito Premium',
    'perfil.discordAccountData': 'Datos de la cuenta de Discord',
    'perfil.discordId': 'ID de Discord',
    'perfil.notAvailable': 'No disponible',
    'perfil.authentication': 'Autenticación',
    'perfil.discordOAuth2': 'Discord OAuth2',
    'perfil.sessionStatus': 'Estado de sesión',
    'perfil.connected': 'Conectado',
    'perfil.reload': 'Recargar',
    'perfil.invitePurgito': 'Invitar a Purgito',
    'perfil.supportServer': 'Servidor de soporte',
    'perfil.memberCount': '{count} miembros',
    'perfil.notHereYet': 'Purgito no está aquí',
    'perfil.chooseServer': 'Elegir este servidor',
    'perfil.dashboard': 'Dashboard',
    'perfil.searchPlaceholder': 'Buscar por nombre o ID…',
    'perfil.noServerMatch': 'Ningún servidor coincide con la búsqueda.',
    'perfil.listUpdated': 'Lista de servidores actualizada',
    'perfil.listUpdateError': 'No se pudo actualizar la lista, intenta de nuevo',
    'perfil.connectionsUnavailable': 'Función aún no disponible..',
    'perfil.upsellTitle': 'Sumate a Premium',
    'perfil.upsellDesc': 'Sube los límites de Purgito y desbloquea los memes automáticos en tus servidores.',
    'perfil.billingStatus.trialing': 'En prueba gratuita',
    'perfil.billingStatus.active': 'Activo',
    'perfil.billingStatus.pastDue': 'Pago pendiente',
    'perfil.billingStatus.canceled': 'Cancelado',
    'perfil.billingStatus.unpaid': 'Pago fallido',
    'perfil.billingStatus.incomplete': 'Pago en proceso',
    'perfil.billingStatus.incompleteExpired': 'Pago no completado',
    'perfil.billingStatusCanceledAtPeriodEnd': 'Cancelado al final del período',
    'perfil.billingStatusUnknown': 'Estado desconocido',
    'perfil.manageSubscription': 'Gestionar suscripción en Polar →',
    'perfil.plan': 'Plan',
    'perfil.defaultPlanName': 'Purgito Premium',
    'perfil.status': 'Estado',
    'perfil.trialEndsLabel': 'Fin de la prueba gratuita',
    'perfil.accessUntil': 'Acceso hasta',
    'perfil.nextCharge': 'Próximo cobro',
    'perfil.serverFallbackName': 'Servidor {id}',
    'perfil.subCanceledNotice': 'Ya cancelaste esta suscripción: el servidor conserva Premium hasta la fecha de arriba.',
    'perfil.permanentPremiumDesc': 'Premium permanente otorgado por Purgito. No requiere suscripción ni renovación.',
    'perfil.yourSubscriptions': 'Tus suscripciones',
    'perfil.permanentPremium': 'Premium permanente',
  },
  en: {
    'perfil.tabs.servidores': 'Servers',
    'perfil.tabs.conexiones': 'Connections',
    'perfil.tabs.facturacion': 'Billing',
    'perfil.tabs.perfil': 'Profile',
    'perfil.tabsAriaLabel': 'Account tabs',
    'perfil.discordUser': 'Discord user',
    'perfil.onDiscordSince': 'On Discord since {date}',
    'perfil.defaultName': 'Your account',
    'perfil.accountSummary': 'Account summary',
    'perfil.managedServers': 'Managed servers',
    'perfil.viewServers': 'View servers →',
    'perfil.serversActiveOf': '{configured} with Purgito active out of {total} available',
    'perfil.serversConfigured': '{configured} servers configured',
    'perfil.premiumSubs': 'Premium subscriptions',
    'perfil.billingLink': 'Billing →',
    'perfil.activeSingular': 'active',
    'perfil.activePlural': 'active',
    'perfil.noPlansActive': 'No active plans',
    'perfil.premiumSubsSub': 'On your configured servers',
    'perfil.discoverPremium': 'Discover Purgito Premium',
    'perfil.discordAccountData': 'Discord account data',
    'perfil.discordId': 'Discord ID',
    'perfil.notAvailable': 'Not available',
    'perfil.authentication': 'Authentication',
    'perfil.discordOAuth2': 'Discord OAuth2',
    'perfil.sessionStatus': 'Session status',
    'perfil.connected': 'Connected',
    'perfil.reload': 'Reload',
    'perfil.invitePurgito': 'Invite Purgito',
    'perfil.supportServer': 'Support server',
    'perfil.memberCount': '{count} members',
    'perfil.notHereYet': 'Purgito isn’t here yet',
    'perfil.chooseServer': 'Choose this server',
    'perfil.dashboard': 'Dashboard',
    'perfil.searchPlaceholder': 'Search by name or ID…',
    'perfil.noServerMatch': 'No server matches your search.',
    'perfil.listUpdated': 'Server list updated',
    'perfil.listUpdateError': 'Could not update the list, try again',
    'perfil.connectionsUnavailable': 'Feature not available yet.',
    'perfil.upsellTitle': 'Join Premium',
    'perfil.upsellDesc': 'Raise Purgito’s limits and unlock automatic memes on your servers.',
    'perfil.billingStatus.trialing': 'On free trial',
    'perfil.billingStatus.active': 'Active',
    'perfil.billingStatus.pastDue': 'Payment past due',
    'perfil.billingStatus.canceled': 'Canceled',
    'perfil.billingStatus.unpaid': 'Payment failed',
    'perfil.billingStatus.incomplete': 'Payment processing',
    'perfil.billingStatus.incompleteExpired': 'Payment not completed',
    'perfil.billingStatusCanceledAtPeriodEnd': 'Canceled at the end of the period',
    'perfil.billingStatusUnknown': 'Unknown status',
    'perfil.manageSubscription': 'Manage subscription on Polar →',
    'perfil.plan': 'Plan',
    'perfil.defaultPlanName': 'Purgito Premium',
    'perfil.status': 'Status',
    'perfil.trialEndsLabel': 'Free trial ends',
    'perfil.accessUntil': 'Access until',
    'perfil.nextCharge': 'Next charge',
    'perfil.serverFallbackName': 'Server {id}',
    'perfil.subCanceledNotice': 'You already canceled this subscription: the server keeps Premium until the date above.',
    'perfil.permanentPremiumDesc': 'Permanent Premium granted by Purgito. No subscription or renewal required.',
    'perfil.yourSubscriptions': 'Your subscriptions',
    'perfil.permanentPremium': 'Permanent Premium',
  },
});

const TABS = [
  { key: 'servidores', label: 'Servidores', path: '/servidores' },
  { key: 'conexiones', label: 'Conexiones', path: '/conexiones' },
  { key: 'facturacion', label: 'Facturación', path: '/facturacion' },
  { key: 'perfil', label: 'Perfil', path: '' },
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
  let meta = null;
  if (tab === 'perfil') {
    const created = accountCreated(me.user_id);
    const metaItems = [
      el('li', {}, t('perfil.discordUser')),
      created ? el('li', {}, t('perfil.onDiscordSince', { date: created })) : null,
      me.email ? el('li', {}, me.email) : null,
    ].filter(Boolean);
    if (metaItems.length) {
      meta = el('ul', { class: 'pf-meta dim' }, metaItems);
    }
  }

  return el('section', { class: 'pf-head' },
    el('div', { class: 'pf-hero' },
      me.avatar_url ? el('img', { class: 'pf-avatar-lg', src: me.avatar_url, alt: me.name || '' }) : null,
      el('div', { class: 'pf-hero-info' },
        el('h1', { class: 'pf-hero-name' }, me.name || t('perfil.defaultName')),
        meta)),
    el('nav', { class: 'pf-tabs', 'aria-label': t('perfil.tabsAriaLabel') },
      TABS.map(tTab => el('a', {
        class: 'pf-tab' + (tTab.key === tab ? ' active' : ''),
        href: `/${locale}/perfil${tTab.path}`,
        'aria-current': tTab.key === tab ? 'page' : null,
      }, t(`perfil.tabs.${tTab.key}`) || tTab.label))));
}

async function tabPerfil(box, me, locale) {
  const summaryGrid = el('div', { class: 'pf-summary-grid' });
  box.append(
    el('div', { class: 'pf-overview' },
      el('h2', { class: 'pf-section-title' }, t('perfil.accountSummary')),
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
          el('span', { class: 'pf-stat-label' }, t('perfil.managedServers')),
          el('a', { class: 'pf-stat-link', href: `/${locale}/perfil/servidores` }, t('perfil.viewServers'))),
        el('div', { class: 'pf-stat-val' }, String(configuredCount)),
        el('div', { class: 'pf-stat-sub dim' },
          totalManageable > configuredCount
            ? t('perfil.serversActiveOf', { configured: configuredCount, total: totalManageable })
            : t('perfil.serversConfigured', { configured: configuredCount }))),

      el('div', { class: 'pf-stat-card' },
        el('div', { class: 'pf-stat-header' },
          el('span', { class: 'pf-stat-label' }, t('perfil.premiumSubs')),
          el('a', { class: 'pf-stat-link', href: `/${locale}/perfil/facturacion` }, t('perfil.billingLink'))),
        el('div', { class: 'pf-stat-val' },
          premiumCount > 0 ? `${premiumCount} ${premiumCount === 1 ? t('perfil.activeSingular') : t('perfil.activePlural')}` : t('perfil.noPlansActive')),
        el('div', { class: 'pf-stat-sub dim' },
          premiumCount > 0
            ? t('perfil.premiumSubsSub')
            : el('a', { href: `/${locale}/premium`, class: 'link-accent' }, t('perfil.discoverPremium')))),

      el('div', { class: 'pf-stat-card pf-stat-card--wide' },
        el('div', { class: 'pf-stat-header' },
          el('span', { class: 'pf-stat-label' }, t('perfil.discordAccountData'))),
        el('div', { class: 'pf-account-details' },
          el('div', { class: 'pf-acc-item' },
            el('span', { class: 'pf-acc-label' }, t('perfil.discordId')),
            el('span', { class: 'pf-acc-val pf-mono' }, me.user_id || t('perfil.notAvailable'))),
          el('div', { class: 'pf-acc-item' },
            el('span', { class: 'pf-acc-label' }, t('perfil.authentication')),
            el('span', { class: 'pf-acc-val' }, t('perfil.discordOAuth2'))),
          el('div', { class: 'pf-acc-item' },
            el('span', { class: 'pf-acc-label' }, t('perfil.sessionStatus')),
            el('span', { class: 'pf-acc-val' }, t('perfil.connected')))
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
  }, t('perfil.reload'));
  return el('div', { class: 'pf-actions' },
    el('a', { class: 'btn btn-primary', href: INVITE, target: '_blank', rel: 'noopener' }, t('perfil.invitePurgito')),
    el('a', { class: 'btn btn-secondary', href: SUPPORT, target: '_blank', rel: 'noopener' }, t('perfil.supportServer')),
    reload);
}

function selectedPremiumPlan() {
  const plan = new URLSearchParams(location.search).get('plan');
  return plan === 'monthly' || plan === 'annual' ? plan : null;
}

function serverCard(g, configured, locale, plan) {
  const dashboardHref = `/${locale}/dashboard/${g.id}${plan ? `/premium?plan=${plan}` : '/inicio'}`;
  return el('div', { class: 'card' },
    guildIcon(g),
    el('div', { class: 'card-info' },
      el('div', { class: 'card-name' }, g.name,
        configured && g.is_premium ? el('span', { class: 'badge badge-premium' }, 'PREMIUM') : null),
      el('div', { class: 'card-sub' },
        configured
          ? (g.member_count != null ? t('perfil.memberCount', { count: g.member_count }) : '')
          : t('perfil.notHereYet'))),
    configured
      ? el('a', { class: 'btn btn-primary', href: dashboardHref }, plan ? t('perfil.chooseServer') : t('perfil.dashboard'))
      : el('a', { class: 'btn btn-secondary', href: g.invite_url, target: '_blank', rel: 'noopener' }, t('perfil.invitePurgito')));
}

async function tabServidores(box, locale) {
  const plan = selectedPremiumPlan();
  const search = el('input', {
    type: 'search', class: 'pf-search', placeholder: t('perfil.searchPlaceholder'),
  });
  const grid = el('div', { class: 'card-grid' });
  let all = [];

  function render() {
    const q = search.value.trim().toLowerCase();
    grid.innerHTML = '';
    const hits = all.filter(([g]) =>
      !q || (g.name || '').toLowerCase().includes(q) || g.id.includes(q));
    if (!hits.length) grid.append(emptyState(t('perfil.noServerMatch')));
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
      if (force) toast(t('perfil.listUpdated'), 'ok');
    } catch (e) {
      grid.innerHTML = '';
      renderError(grid, e);
      if (force) toast(t('perfil.listUpdateError'), 'err');
    }
  }

  search.oninput = render;
  box.append(
    el('div', { class: 'pf-toolbar' }, search, actionButtons(() => load(true))),
    grid);
  await load(false);
}

function tabConexiones(box) {
  box.append(emptyState(t('perfil.connectionsUnavailable')));
}

function premiumUpsellCard(locale) {
  return el('a', { class: 'pf-upsell', href: `/${locale}/premium` },
    el('div', { class: 'pf-upsell-copy' },
      el('h2', {}, t('perfil.upsellTitle')),
      el('p', { class: 'dim' }, t('perfil.upsellDesc'))),
    el('div', { class: 'pf-upsell-brands' },
      ['visa', 'mastercard', 'americanexpress', 'discover'].map(b =>
        el('img', { src: `/assets/${b}.svg`, alt: b, loading: 'lazy' }))));
}

const BILLING_STATUS_KEYS = {
  trialing: 'perfil.billingStatus.trialing',
  active: 'perfil.billingStatus.active',
  past_due: 'perfil.billingStatus.pastDue',
  canceled: 'perfil.billingStatus.canceled',
  unpaid: 'perfil.billingStatus.unpaid',
  incomplete: 'perfil.billingStatus.incomplete',
  incomplete_expired: 'perfil.billingStatus.incompleteExpired',
};

function billingStatusLabel(sub) {
  if (sub.cancel_at_period_end && sub.status === 'active') return t('perfil.billingStatusCanceledAtPeriodEnd');
  const key = BILLING_STATUS_KEYS[sub.status];
  return key ? t(key) : t('perfil.billingStatusUnknown');
}

function billingDate(iso) {
  if (!iso) return null;
  return formatDate(new Date(iso), { year: 'numeric', month: 'long', day: 'numeric' });
}

function manageSubscriptionBtn(sub) {
  return el('button', {
    class: 'btn btn-secondary btn-sm',
    type: 'button',
    onclick: async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      try {
        const data = await apiFetch('/api/me/billing/portal', {
          method: 'POST', body: { guild_id: sub.guild_id },
        });
        window.location.href = data.portal_url;
      } catch (e) {
        btn.disabled = false;
        toast(e.message, 'err');
      }
    },
  }, t('perfil.manageSubscription'));
}

function subscriptionCard(sub) {
  const periodEnd = billingDate(sub.current_period_end);
  const trialEnd = billingDate(sub.trial_end);
  const rows = [
    [t('perfil.plan'), sub.plan || t('perfil.defaultPlanName')],
    [t('perfil.status'), billingStatusLabel(sub)],
  ];
  if (sub.is_trialing && trialEnd) rows.push([t('perfil.trialEndsLabel'), trialEnd]);
  if (periodEnd) {
    rows.push([sub.cancel_at_period_end ? t('perfil.accessUntil') : t('perfil.nextCharge'), periodEnd]);
  }
  return el('div', { class: 'card pf-stat-card pf-stat-card--wide' },
    el('div', { class: 'card-name' }, sub.guild_name || t('perfil.serverFallbackName', { id: sub.guild_id }),
      el('span', { class: 'badge badge-premium' }, 'PREMIUM')),
    el('div', { class: 'pf-account-details' },
      rows.map(([k, v]) => el('div', { class: 'pf-acc-item' },
        el('span', { class: 'pf-acc-label' }, k), el('span', { class: 'pf-acc-val' }, v)))),
    sub.cancel_at_period_end
      ? el('p', { class: 'dim' }, t('perfil.subCanceledNotice'))
      : null,
    sub.can_manage ? manageSubscriptionBtn(sub) : null);
}

function permanentPremiumCard(g) {
  return el('div', { class: 'card pf-stat-card pf-stat-card--wide' },
    el('div', { class: 'card-name' }, g.name,
      el('span', { class: 'badge badge-premium' }, 'PREMIUM')),
    el('p', { class: 'dim' }, t('perfil.permanentPremiumDesc')));
}

async function tabFacturacion(box, locale) {
  box.append(spinner());
  let guilds, billing;
  try {
    [guilds, billing] = await Promise.all([
      apiFetch('/api/me/guilds'),
      apiFetch('/api/me/billing'),
    ]);
  } catch (e) { box.innerHTML = ''; return renderError(box, e); }
  box.innerHTML = '';

  const subscriptions = billing.subscriptions || [];
  const permanentes = guilds.configured.filter(g => g.is_premium && g.is_permanent);

  if (!subscriptions.length && !permanentes.length) {
    box.append(premiumUpsellCard(locale));
    return;
  }

  const sections = [premiumUpsellCard(locale)];
  if (subscriptions.length) {
    sections.push(
      el('h2', {}, t('perfil.yourSubscriptions')),
      subscriptions.map(subscriptionCard));
  }
  if (permanentes.length) {
    sections.push(
      el('h2', {}, t('perfil.permanentPremium')),
      permanentes.map(permanentPremiumCard));
  }
  box.append(el('div', { class: 'pf-billing' }, ...sections));
}

export async function initPerfil() {
  const locale = currentLocale();
  const params = new URLSearchParams(location.search);
  // Compatibilidad: si entran a /es/perfil con ?plan=... o ?share=..., redirigir a servidores
  if (!location.pathname.includes('/servidores') && !location.pathname.includes('/conexiones') && !location.pathname.includes('/facturacion') && (params.has('plan') || params.has('share'))) {
    location.replace(`/${locale}/perfil/servidores${location.search}`);
    return;
  }

  const m = location.pathname.match(/\/perfil(?:\/([^\/?#]+))?/);
  const seg = (m && m[1]) ? m[1] : 'perfil';
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
