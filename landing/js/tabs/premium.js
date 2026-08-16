import { apiFetch } from '/js/core/api.js';
import { el, spinner, flash, renderError, icon } from '/js/core/dom.js';
import { GUILD_ID, currentLocale } from '/js/core/config.js';
import { content } from '/js/panel-shell.js';

function checkoutBtn(box, plan, label, extraClass = '') {
  return el('button', {
    class: `btn btn-primary ${extraClass}`.trim(),
    onclick: async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      try {
        const data = await apiFetch(`/api/server/${GUILD_ID}/premium/checkout`, {
          method: 'POST', body: { plan },
        });
        window.location.href = data.checkout_url;
      } catch (e) {
        btn.disabled = false;
        flash(box, false, e.message);
      }
    },
  }, label);
}

export async function loadPremium() {
  const box = content();
  box.append(spinner());
  try {
    const data = await apiFetch(`/api/server/${GUILD_ID}/premium`);
    box.innerHTML = '';
    const loc = currentLocale();

    const premiumRows = [
      ['Memes automáticos programados', 'No disponible', 'Disponible'],
      ['Mensajes guardados en memoria (corpus)', '15.000', '50.000'],
      ['Mensajes de usuario en memoria', '2.000', '8.000'],
      ['GIFs guardados', '1.500', '4.000'],
      ['Imágenes en la colección de memes', '75', '200'],
      ['Plantillas de embeds guardadas', '20', '50'],
    ];

    if (data.premium) {
      // Estado: Servidor con Premium activo (vista limpia de beneficios y límites activos)
      const activeHero = el('div', { class: 'premium-active-hero' },
        el('div', { class: 'premium-active-header' },
          el('div', { class: 'premium-active-title-group' },
            el('span', { class: 'badge badge-premium' }, icon('star'), 'ACTIVO'),
            el('h2', {}, 'Purgito Premium activo')),
          el('span', { class: 'badge badge-success' }, 'Beneficios habilitados')),
        el('p', { class: 'premium-active-desc' },
          'Este servidor tiene acceso a todas las funciones premium y límites ampliados de Purgito.'),
        el('div', { class: 'premium-benefits-grid premium-receipt' },
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('corpus')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, '50.000 mensajes'),
              el('div', { class: 'benefit-label' }, 'Memoria del servidor (corpus) ampliada'))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('members')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, '8.000 mensajes'),
              el('div', { class: 'benefit-label' }, 'Memoria personalizada por usuario'))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('film')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, '4.000 GIFs'),
              el('div', { class: 'benefit-label' }, 'Límite de GIFs guardados ampliado'))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('image')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, '200 imágenes'),
              el('div', { class: 'benefit-label' }, 'Colección de memes ampliada'))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('layout')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, '50 plantillas'),
              el('div', { class: 'benefit-label' }, 'Límite de plantillas de embeds ampliado'))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('clock')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, 'Desbloqueado'),
              el('div', { class: 'benefit-label' }, 'Memes automáticos programados')))));

      const manageBox = el('div', { class: 'premium-manage-callout' },
        el('div', { class: 'premium-manage-info' },
          icon('info'),
          el('div', {},
            el('h4', {}, 'Gestión de la suscripción y facturación'),
            el('p', {}, 'La administración de la suscripción personal, facturas, método de pago y cancelación se realiza exclusivamente desde el perfil de la cuenta del comprador.'))),
        el('a', { class: 'btn btn-secondary btn-sm', href: `/${loc}/perfil/facturacion` }, 'Facturación en Mi Perfil →'));

      box.append(el('div', { class: 'premium-layout' }, activeHero, manageBox));
      return;
    }

    // Estado: Servidor sin Premium (presentación moderna del catálogo y planes)
    const header = el('div', { class: 'premium-hero' },
      el('span', { class: 'badge badge-premium' }, icon('star'), 'PREMIUM'),
      el('h1', {}, 'Purgito Premium'),
      el('p', {}, 'Desbloquea todo el potencial de Purgito para tu servidor con memoria ampliada, mayor capacidad multimedia y automatizaciones exclusivas.'));

    const comparisonCard = el('div', { class: 'premium-comparison-card' },
      el('div', { class: 'premium-card-header' },
        el('h3', {}, 'Comparativa de capacidades'),
        el('p', { class: 'dim' }, 'Todo lo que cambia al activar Premium en tu servidor.')),
      el('div', { class: 'premium-table-wrap' },
        el('table', { class: 'premium-comparison-table' },
          el('thead', {},
            el('tr', {},
              el('th', {}, 'Beneficio'),
              el('th', {}, 'Plan Free'),
              el('th', { class: 'premium-col-head' }, 'Con Premium'))),
          el('tbody', {}, premiumRows.map(([benefit, free, premium]) =>
            el('tr', {},
              el('th', { scope: 'row', class: 'feature-name' }, benefit),
              el('td', { class: 'free-val' }, free),
              el('td', { class: 'prem-val' },
                el('span', { class: 'prem-chip' }, premium))))))));

    const plansGrid = el('div', { class: 'premium-plans-grid' },
      // Tarjeta Mensual
      el('article', { class: 'premium-plan-card' },
        el('div', { class: 'premium-plan-top' },
          el('div', { class: 'premium-plan-header' },
            el('h3', {}, 'Plan Mensual'),
            el('span', { class: 'plan-badge plan-badge-trial' }, '7 DÍAS GRATIS')),
          el('div', { class: 'premium-plan-price-wrap' },
            el('span', { class: 'premium-plan-amount' }, '$4.99'),
            el('span', { class: 'premium-plan-cycle' }, '/ mes')),
          el('p', { class: 'premium-plan-desc' },
            'Empieza gratis sin compromiso. Cancela cuando quieras durante los 7 días de prueba y no se te cobrará nada.')),
        el('div', { class: 'premium-plan-bottom' },
          checkoutBtn(box, 'monthly', 'Empezar prueba gratis — 7 días'),
          el('p', { class: 'premium-plan-footnote' },
            'La prueba gratis aplica una vez por cliente (mismo comprador o método de pago).'))),
      // Tarjeta Anual (Destacada)
      el('article', { class: 'premium-plan-card premium-plan-featured' },
        el('div', { class: 'premium-plan-top' },
          el('div', { class: 'premium-plan-header' },
            el('h3', {}, 'Plan Anual'),
            el('div', { class: 'plan-badges-group' },
              el('span', { class: 'plan-badge plan-badge-savings' }, 'AHORRA ~33%'),
              el('span', { class: 'plan-badge plan-badge-recom' }, 'RECOMENDADO'))),
          el('div', { class: 'premium-plan-price-wrap' },
            el('span', { class: 'premium-plan-amount' }, '$39.99'),
            el('span', { class: 'premium-plan-cycle' }, '/ año'),
            el('span', { class: 'premium-plan-sub-cycle' }, '≈ $3.33/mes')),
          el('p', { class: 'premium-plan-desc' },
            'La mejor opción: un solo pago al año y ahorras un tercio del costo frente a 12 meses del plan mensual.')),
        el('div', { class: 'premium-plan-bottom' },
          checkoutBtn(box, 'annual', 'Suscribirse — Anual $39.99/año', 'btn-premium-action'),
          el('p', { class: 'premium-plan-footnote' },
            'Facturación anual de $39.99/año con renovación automática. Cancela en cualquier momento.'))));

    const legalNote = el('p', { class: 'premium-legal-note' },
      'Al suscribirte aceptas los ',
      el('a', { href: `/${loc}/terminos`, target: '_blank', rel: 'noopener' }, 'Términos de Servicio'),
      ' y la ',
      el('a', { href: `/${loc}/privacidad`, target: '_blank', rel: 'noopener' }, 'Política de Privacidad'),
      '.');

    const infoNote = el('div', { class: 'premium-note' },
      icon('info'),
      el('div', { class: 'premium-note-body' },
        el('h3', {}, '¿Cómo funciona la activación y gestión?'),
        el('p', {},
          'El pago se procesa de forma segura a través de Polar (nuestro proveedor y Merchant of Record). Al completarse, Premium se activa automáticamente en tu servidor en segundos.'),
        el('p', {},
          'Recibirás un correo de confirmación con un enlace directo a tu portal de cliente de Polar para cambiar de plan, actualizar tu método de pago o cancelar la renovación en cualquier momento.'),
        el('p', {},
          'Cancelar la suscripción no corta los beneficios de inmediato: el servidor conserva todas las funciones premium hasta que finalice el período ya abonado.')));

    box.append(el('div', { class: 'premium-layout' },
      header,
      comparisonCard,
      plansGrid,
      legalNote,
      infoNote));
  } catch (e) { renderError(box, e); }
}
