import { apiFetch } from '/js/core/api.js';
import { el, spinner, flash, renderError, icon } from '/js/core/dom.js';
import { GUILD_ID, currentLocale } from '/js/core/config.js';
import { content } from '/js/panel-shell.js';
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'tabsPremium.rowAutoMemes.benefit': 'Memes automáticos programados',
    'tabsPremium.rowAutoMemes.free': 'No disponible',
    'tabsPremium.rowAutoMemes.premium': 'Disponible',
    'tabsPremium.rowCorpus.benefit': 'Mensajes guardados en memoria (corpus)',
    'tabsPremium.rowCorpus.free': '15.000',
    'tabsPremium.rowCorpus.premium': '50.000',
    'tabsPremium.rowUserCorpus.benefit': 'Mensajes de usuario en memoria',
    'tabsPremium.rowUserCorpus.free': '2.000',
    'tabsPremium.rowUserCorpus.premium': '8.000',
    'tabsPremium.rowGifs.benefit': 'GIFs guardados',
    'tabsPremium.rowGifs.free': '1.500',
    'tabsPremium.rowGifs.premium': '4.000',
    'tabsPremium.rowImages.benefit': 'Imágenes en la colección de memes',
    'tabsPremium.rowImages.free': '75',
    'tabsPremium.rowImages.premium': '200',
    'tabsPremium.rowEmbeds.benefit': 'Plantillas de embeds guardadas',
    'tabsPremium.rowEmbeds.free': '20',
    'tabsPremium.rowEmbeds.premium': '50',
    'tabsPremium.activeBadge': 'ACTIVO',
    'tabsPremium.activeTitle': 'Purgito Premium activo',
    'tabsPremium.benefitsEnabled': 'Beneficios habilitados',
    'tabsPremium.activeDesc': 'Este servidor tiene acceso a todas las funciones premium y límites ampliados de Purgito.',
    'tabsPremium.benefitCorpus.metric': '50.000 mensajes',
    'tabsPremium.benefitCorpus.label': 'Memoria del servidor (corpus) ampliada',
    'tabsPremium.benefitUserCorpus.metric': '8.000 mensajes',
    'tabsPremium.benefitUserCorpus.label': 'Memoria personalizada por usuario',
    'tabsPremium.benefitGifs.metric': '4.000 GIFs',
    'tabsPremium.benefitGifs.label': 'Límite de GIFs guardados ampliado',
    'tabsPremium.benefitImages.metric': '200 imágenes',
    'tabsPremium.benefitImages.label': 'Colección de memes ampliada',
    'tabsPremium.benefitEmbeds.metric': '50 plantillas',
    'tabsPremium.benefitEmbeds.label': 'Límite de plantillas de embeds ampliado',
    'tabsPremium.benefitAutoMemes.metric': 'Desbloqueado',
    'tabsPremium.benefitAutoMemes.label': 'Memes automáticos programados',
    'tabsPremium.manageTitle': 'Gestión de la suscripción y facturación',
    'tabsPremium.manageDesc': 'La administración de la suscripción personal, facturas, método de pago y cancelación se realiza exclusivamente desde el perfil de la cuenta del comprador.',
    'tabsPremium.manageLink': 'Facturación en Mi Perfil →',
    'tabsPremium.badge': 'PREMIUM',
    'tabsPremium.heroTitle': 'Purgito Premium',
    'tabsPremium.heroDesc': 'Desbloquea todo el potencial de Purgito para tu servidor con memoria ampliada, mayor capacidad multimedia y automatizaciones exclusivas.',
    'tabsPremium.comparisonTitle': 'Comparativa de capacidades',
    'tabsPremium.comparisonDesc': 'Todo lo que cambia al activar Premium en tu servidor.',
    'tabsPremium.colBenefit': 'Beneficio',
    'tabsPremium.colFree': 'Plan Free',
    'tabsPremium.colPremium': 'Con Premium',
    'tabsPremium.monthlyTitle': 'Plan Mensual',
    'tabsPremium.monthlyTrialBadge': '7 DÍAS GRATIS',
    'tabsPremium.monthlyCycle': '/ mes',
    'tabsPremium.monthlyDesc': 'Empieza gratis sin compromiso. Cancela cuando quieras durante los 7 días de prueba y no se te cobrará nada.',
    'tabsPremium.monthlyCta': 'Empezar prueba gratis — 7 días',
    'tabsPremium.monthlyFootnote': 'La prueba gratis aplica una vez por cliente (mismo comprador o método de pago).',
    'tabsPremium.annualTitle': 'Plan Anual',
    'tabsPremium.annualSavingsBadge': 'AHORRA ~33%',
    'tabsPremium.annualRecomBadge': 'RECOMENDADO',
    'tabsPremium.annualCycle': '/ año',
    'tabsPremium.annualSubCycle': '≈ $3.33/mes',
    'tabsPremium.annualDesc': 'La mejor opción: un solo pago al año y ahorras un tercio del costo frente a 12 meses del plan mensual.',
    'tabsPremium.annualCta': 'Suscribirse — Anual $39.99/año',
    'tabsPremium.annualFootnote': 'Facturación anual de $39.99/año con renovación automática. Cancela en cualquier momento.',
    'tabsPremium.legalPrefix': 'Al suscribirte aceptas los ',
    'tabsPremium.legalTerms': 'Términos de Servicio',
    'tabsPremium.legalMiddle': ' y la ',
    'tabsPremium.legalPrivacy': 'Política de Privacidad',
    'tabsPremium.legalSuffix': '.',
    'tabsPremium.infoTitle': '¿Cómo funciona la activación y gestión?',
    'tabsPremium.infoP1': 'El pago se procesa de forma segura a través de Polar (nuestro proveedor y Merchant of Record). Al completarse, Premium se activa automáticamente en tu servidor en segundos.',
    'tabsPremium.infoP2': 'Recibirás un correo de confirmación con un enlace directo a tu portal de cliente de Polar para cambiar de plan, actualizar tu método de pago o cancelar la renovación en cualquier momento.',
    'tabsPremium.infoP3': 'Cancelar la suscripción no corta los beneficios de inmediato: el servidor conserva todas las funciones premium hasta que finalice el período ya abonado.',
  },
  en: {
    'tabsPremium.rowAutoMemes.benefit': 'Scheduled automatic memes',
    'tabsPremium.rowAutoMemes.free': 'Not available',
    'tabsPremium.rowAutoMemes.premium': 'Available',
    'tabsPremium.rowCorpus.benefit': 'Messages stored in memory (corpus)',
    'tabsPremium.rowCorpus.free': '15,000',
    'tabsPremium.rowCorpus.premium': '50,000',
    'tabsPremium.rowUserCorpus.benefit': 'Per-user messages in memory',
    'tabsPremium.rowUserCorpus.free': '2,000',
    'tabsPremium.rowUserCorpus.premium': '8,000',
    'tabsPremium.rowGifs.benefit': 'Saved GIFs',
    'tabsPremium.rowGifs.free': '1,500',
    'tabsPremium.rowGifs.premium': '4,000',
    'tabsPremium.rowImages.benefit': 'Images in the meme collection',
    'tabsPremium.rowImages.free': '75',
    'tabsPremium.rowImages.premium': '200',
    'tabsPremium.rowEmbeds.benefit': 'Saved embed templates',
    'tabsPremium.rowEmbeds.free': '20',
    'tabsPremium.rowEmbeds.premium': '50',
    'tabsPremium.activeBadge': 'ACTIVE',
    'tabsPremium.activeTitle': 'Purgito Premium active',
    'tabsPremium.benefitsEnabled': 'Benefits enabled',
    'tabsPremium.activeDesc': 'This server has access to all of Purgito\'s premium features and expanded limits.',
    'tabsPremium.benefitCorpus.metric': '50,000 messages',
    'tabsPremium.benefitCorpus.label': 'Expanded server memory (corpus)',
    'tabsPremium.benefitUserCorpus.metric': '8,000 messages',
    'tabsPremium.benefitUserCorpus.label': 'Custom per-user memory',
    'tabsPremium.benefitGifs.metric': '4,000 GIFs',
    'tabsPremium.benefitGifs.label': 'Expanded saved GIF limit',
    'tabsPremium.benefitImages.metric': '200 images',
    'tabsPremium.benefitImages.label': 'Expanded meme collection',
    'tabsPremium.benefitEmbeds.metric': '50 templates',
    'tabsPremium.benefitEmbeds.label': 'Expanded embed template limit',
    'tabsPremium.benefitAutoMemes.metric': 'Unlocked',
    'tabsPremium.benefitAutoMemes.label': 'Scheduled automatic memes',
    'tabsPremium.manageTitle': 'Subscription and billing management',
    'tabsPremium.manageDesc': 'Managing your personal subscription, invoices, payment method, and cancellation is done exclusively from the buyer\'s account profile.',
    'tabsPremium.manageLink': 'Billing in My Profile →',
    'tabsPremium.badge': 'PREMIUM',
    'tabsPremium.heroTitle': 'Purgito Premium',
    'tabsPremium.heroDesc': 'Unlock Purgito\'s full potential for your server with expanded memory, more media capacity, and exclusive automations.',
    'tabsPremium.comparisonTitle': 'Feature comparison',
    'tabsPremium.comparisonDesc': 'Everything that changes when you activate Premium on your server.',
    'tabsPremium.colBenefit': 'Feature',
    'tabsPremium.colFree': 'Free plan',
    'tabsPremium.colPremium': 'With Premium',
    'tabsPremium.monthlyTitle': 'Monthly plan',
    'tabsPremium.monthlyTrialBadge': '7-DAY FREE TRIAL',
    'tabsPremium.monthlyCycle': '/ month',
    'tabsPremium.monthlyDesc': 'Start free, no commitment. Cancel anytime during the 7-day trial and you won\'t be charged.',
    'tabsPremium.monthlyCta': 'Start free trial — 7 days',
    'tabsPremium.monthlyFootnote': 'The free trial applies once per customer (same buyer or payment method).',
    'tabsPremium.annualTitle': 'Annual plan',
    'tabsPremium.annualSavingsBadge': 'SAVE ~33%',
    'tabsPremium.annualRecomBadge': 'RECOMMENDED',
    'tabsPremium.annualCycle': '/ year',
    'tabsPremium.annualSubCycle': '≈ $3.33/mo',
    'tabsPremium.annualDesc': 'The best option: one payment a year and you save a third of the cost compared to 12 months of the monthly plan.',
    'tabsPremium.annualCta': 'Subscribe — Annual $39.99/year',
    'tabsPremium.annualFootnote': 'Annual billing of $39.99/year with automatic renewal. Cancel anytime.',
    'tabsPremium.legalPrefix': 'By subscribing you agree to the ',
    'tabsPremium.legalTerms': 'Terms of Service',
    'tabsPremium.legalMiddle': ' and the ',
    'tabsPremium.legalPrivacy': 'Privacy Policy',
    'tabsPremium.legalSuffix': '.',
    'tabsPremium.infoTitle': 'How does activation and management work?',
    'tabsPremium.infoP1': 'Payment is processed securely through Polar (our provider and Merchant of Record). Once completed, Premium activates automatically on your server within seconds.',
    'tabsPremium.infoP2': 'You\'ll get a confirmation email with a direct link to your Polar customer portal to change plans, update your payment method, or cancel the renewal at any time.',
    'tabsPremium.infoP3': 'Canceling the subscription doesn\'t cut off benefits immediately: the server keeps all premium features until the already-paid period ends.',
  },
});

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
      ['Plantillas de embeds guardadas', '20', '50']
    ];

    const displayRows = loc === 'en' ? [
      [t('tabsPremium.rowAutoMemes.benefit'), t('tabsPremium.rowAutoMemes.free'), t('tabsPremium.rowAutoMemes.premium')],
      [t('tabsPremium.rowCorpus.benefit'), t('tabsPremium.rowCorpus.free'), t('tabsPremium.rowCorpus.premium')],
      [t('tabsPremium.rowUserCorpus.benefit'), t('tabsPremium.rowUserCorpus.free'), t('tabsPremium.rowUserCorpus.premium')],
      [t('tabsPremium.rowGifs.benefit'), t('tabsPremium.rowGifs.free'), t('tabsPremium.rowGifs.premium')],
      [t('tabsPremium.rowImages.benefit'), t('tabsPremium.rowImages.free'), t('tabsPremium.rowImages.premium')],
      [t('tabsPremium.rowEmbeds.benefit'), t('tabsPremium.rowEmbeds.free'), t('tabsPremium.rowEmbeds.premium')],
    ] : premiumRows;

    if (data.premium) {
      // Estado: Servidor con Premium activo (vista limpia de beneficios y límites activos)
      const activeHero = el('div', { class: 'premium-active-hero' },
        el('div', { class: 'premium-active-header' },
          el('div', { class: 'premium-active-title-group' },
            el('span', { class: 'badge badge-premium' }, icon('star'), t('tabsPremium.activeBadge')),
            el('h2', {}, t('tabsPremium.activeTitle'))),
          el('span', { class: 'badge badge-success' }, t('tabsPremium.benefitsEnabled'))),
        el('p', { class: 'premium-active-desc' },
          t('tabsPremium.activeDesc')),
        el('div', { class: 'premium-benefits-grid premium-receipt' },
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('corpus')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, t('tabsPremium.benefitCorpus.metric') /* 50.000 */),
              el('div', { class: 'benefit-label' }, t('tabsPremium.benefitCorpus.label')))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('members')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, t('tabsPremium.benefitUserCorpus.metric') /* 8.000 */),
              el('div', { class: 'benefit-label' }, t('tabsPremium.benefitUserCorpus.label')))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('film')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, t('tabsPremium.benefitGifs.metric') /* 4.000 */),
              el('div', { class: 'benefit-label' }, t('tabsPremium.benefitGifs.label')))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('image')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, t('tabsPremium.benefitImages.metric') /* 200 */),
              el('div', { class: 'benefit-label' }, t('tabsPremium.benefitImages.label')))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('layout')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, t('tabsPremium.benefitEmbeds.metric') /* 50 */),
              el('div', { class: 'benefit-label' }, t('tabsPremium.benefitEmbeds.label')))),
          el('div', { class: 'premium-benefit-card' },
            el('div', { class: 'benefit-icon' }, icon('clock')),
            el('div', { class: 'benefit-content' },
              el('div', { class: 'benefit-metric' }, t('tabsPremium.benefitAutoMemes.metric')),
              el('div', { class: 'benefit-label' }, t('tabsPremium.benefitAutoMemes.label'))))));

      const manageBox = el('div', { class: 'premium-manage-callout' },
        el('div', { class: 'premium-manage-info' },
          icon('info'),
          el('div', {},
            el('h4', {}, t('tabsPremium.manageTitle')),
            el('p', {}, t('tabsPremium.manageDesc')))),
        el('a', { class: 'btn btn-secondary btn-sm', href: `/${loc}/perfil/facturacion` }, t('tabsPremium.manageLink')));

      box.append(el('div', { class: 'premium-layout' }, activeHero, manageBox));
      return;
    }

    // Estado: Servidor sin Premium (presentación moderna del catálogo y planes)
    const header = el('div', { class: 'premium-hero' },
      el('span', { class: 'badge badge-premium' }, icon('star'), t('tabsPremium.badge')),
      el('h1', {}, t('tabsPremium.heroTitle')),
      el('p', {}, t('tabsPremium.heroDesc')));

    const comparisonCard = el('div', { class: 'premium-comparison-card' },
      el('div', { class: 'premium-card-header' },
        el('h3', {}, t('tabsPremium.comparisonTitle')),
        el('p', { class: 'dim' }, t('tabsPremium.comparisonDesc'))),
      el('div', { class: 'premium-table-wrap' },
        el('table', { class: 'premium-comparison-table' },
          el('thead', {},
            el('tr', {},
              el('th', {}, t('tabsPremium.colBenefit')),
              el('th', {}, t('tabsPremium.colFree')),
              el('th', { class: 'premium-col-head' }, t('tabsPremium.colPremium')))),
          el('tbody', {}, displayRows.map(([benefit, free, premium]) =>
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
            el('h3', {}, t('tabsPremium.monthlyTitle')),
            el('span', { class: 'plan-badge plan-badge-trial' }, t('tabsPremium.monthlyTrialBadge'))),
          el('div', { class: 'premium-plan-price-wrap' },
            el('span', { class: 'premium-plan-amount' }, '$4.99'),
            el('span', { class: 'premium-plan-cycle' }, t('tabsPremium.monthlyCycle'))),
          el('p', { class: 'premium-plan-desc' },
            t('tabsPremium.monthlyDesc'))),
        el('div', { class: 'premium-plan-bottom' },
          checkoutBtn(box, 'monthly', t('tabsPremium.monthlyCta')),
          el('p', { class: 'premium-plan-footnote' },
            t('tabsPremium.monthlyFootnote')))),
      // Tarjeta Anual (Destacada)
      el('article', { class: 'premium-plan-card premium-plan-featured' },
        el('div', { class: 'premium-plan-top' },
          el('div', { class: 'premium-plan-header' },
            el('h3', {}, t('tabsPremium.annualTitle')),
            el('div', { class: 'plan-badges-group' },
              el('span', { class: 'plan-badge plan-badge-savings' }, t('tabsPremium.annualSavingsBadge')),
              el('span', { class: 'plan-badge plan-badge-recom' }, t('tabsPremium.annualRecomBadge')))),
          el('div', { class: 'premium-plan-price-wrap' },
            el('span', { class: 'premium-plan-amount' }, '$39.99'),
            el('span', { class: 'premium-plan-cycle' }, t('tabsPremium.annualCycle')),
            el('span', { class: 'premium-plan-sub-cycle' }, t('tabsPremium.annualSubCycle'))),
          el('p', { class: 'premium-plan-desc' },
            t('tabsPremium.annualDesc'))),
        el('div', { class: 'premium-plan-bottom' },
          checkoutBtn(box, 'annual', t('tabsPremium.annualCta'), 'btn-premium-action'),
          el('p', { class: 'premium-plan-footnote' },
            t('tabsPremium.annualFootnote')))));

    const legalNote = el('p', { class: 'premium-legal-note' },
      t('tabsPremium.legalPrefix'),
      el('a', { href: `/${loc}/terminos`, target: '_blank', rel: 'noopener' }, t('tabsPremium.legalTerms')),
      t('tabsPremium.legalMiddle'),
      el('a', { href: `/${loc}/privacidad`, target: '_blank', rel: 'noopener' }, t('tabsPremium.legalPrivacy')),
      t('tabsPremium.legalSuffix'));

    const infoNote = el('div', { class: 'premium-note' },
      icon('info'),
      el('div', { class: 'premium-note-body' },
        el('h3', {}, t('tabsPremium.infoTitle')),
        el('p', {},
          t('tabsPremium.infoP1')),
        el('p', {},
          t('tabsPremium.infoP2')),
        el('p', {},
          t('tabsPremium.infoP3'))));

    box.append(el('div', { class: 'premium-layout' },
      header,
      comparisonCard,
      plansGrid,
      legalNote,
      infoNote));
  } catch (e) { renderError(box, e); }
}
