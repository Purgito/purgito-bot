import { apiFetch } from '/js/core/api.js';
import { el, spinner, flash, renderError, icon } from '/js/core/dom.js';
import { GUILD_ID, currentLocale } from '/js/core/config.js';
import { content } from '/js/panel-shell.js';

function checkoutBtn(box, plan, label) {
  return el('button', {
    class: 'btn btn-primary',
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
    const premiumRows = [
      ['Memes automáticos programados', 'No disponible', 'Disponible'],
      ['Mensajes guardados en memoria (corpus)', '15.000', '50.000'],
      ['Mensajes de usuario en memoria', '5.000', '20.000'],
      ['GIFs guardados', '1.500', '4.000'],
      ['Imágenes en la colección de memes', '75', '200'],
      ['Plantillas de embeds guardadas', '20', '50'],
    ];
    if (data.premium) {
      box.append(el('div', { class: 'premium-layout' },
        el('div', { class: 'premium-card premium-card-wide' },
          el('h2', {}, icon('star'), el('span', {}, 'Premium activo')),
          el('p', { class: 'dim' },
            'Este servidor tiene acceso a todas las funciones premium.',
            data.note ? ` Plan: ${data.note}.` : ''),
          el('ul', { class: 'premium-receipt' },
            el('li', {}, 'Memes automáticos programados desbloqueados'),
            el('li', {}, 'Límites de corpus ampliados a 50.000 mensajes'),
            el('li', {}, 'Límite de corpus de usuario ampliado a 20.000 mensajes'),
            el('li', {}, 'Límite de GIFs guardados ampliado a 4.000'),
            el('li', {}, 'Colección de memes ampliada a 200 imágenes'),
            el('li', {}, 'Límite de plantillas de embeds ampliado a 50')))));
      return;
    }
    const cardWide = el('div', { class: 'premium-card premium-card-wide' },
      el('h2', {}, icon('star'), el('span', {}, 'Activa premium')),
      el('p', { class: 'dim' },
        'Desbloquea las funciones premium de Purgito en este servidor. El pago se procesa en Polar y el premium se activa automáticamente al completarlo.'),
      el('table', { class: 'premium-comparison' },
        el('thead', {}, el('tr', {},
          el('th', {}, 'Beneficio'),
          el('th', {}, 'Free'),
          el('th', { class: 'premium-column' }, 'Premium'))),
        el('tbody', {}, premiumRows.map(([benefit, free, premium]) =>
          el('tr', {},
            el('th', { scope: 'row' }, benefit),
            el('td', {}, free),
            el('td', { class: 'premium-column' }, premium))))),
      el('div', { class: 'premium-plans' },
        el('article', { class: 'premium-plan-card' },
          el('span', { class: 'premium-plan-badge premium-plan-badge-trial' }, '7 días gratis'),
          el('div', { class: 'premium-plan-copy' },
            el('h3', {}, 'Mensual'),
            el('div', { class: 'premium-plan-price' }, '$4.99', el('span', {}, '/mes')),
            el('p', { class: 'dim' },
              'Empieza gratis, sin compromiso — cancela cuando quieras durante la prueba y no se te cobra nada.'),
            el('p', { class: 'premium-plan-fineprint' },
              'La prueba gratis aplica una vez por cliente (mismo comprador o método de pago), aunque la actives en otro servidor.')),
          checkoutBtn(box, 'monthly', 'Empezar prueba gratis — 7 días')),
        el('article', { class: 'premium-plan-card premium-plan-featured' },
          el('span', { class: 'premium-plan-badge' }, 'Ahorra ~33%'),
          el('span', { class: 'premium-plan-recommended' }, 'Recomendado'),
          el('div', { class: 'premium-plan-copy' },
            el('h3', {}, 'Anual'),
            el('div', { class: 'premium-plan-price' }, '$39.99', el('span', {}, '/año')),
            el('p', { class: 'dim' }, 'La mejor opción: pagas una vez y ahorras ~33% frente a 12 meses sueltos.')),
          checkoutBtn(box, 'annual', 'Suscribirse — Anual $39.99/año'))));

    // Las páginas legales las genera landing/build_docs.py desde docs/*.md y
    // viven en /<locale>/terminos y /<locale>/privacidad — el /terms y /privacy
    // que apuntaban al panel viejo ya no existen.
    // Clase propia (antes reusaba .premium-plan-fineprint, pensada para el
    // gap:18px de una tarjeta individual): sin eso, este párrafo quedaba sin
    // separación del grid de precios — pegado a su borde inferior, en la
    // costura entre ambas tarjetas. Ver diagnóstico en el reporte del fix.
    const loc = currentLocale();
    const legalNote = el('p', { class: 'premium-legal-note' },
      'Al continuar aceptas los ',
      el('a', { href: `/${loc}/terminos`, target: '_blank', rel: 'noopener' }, 'Términos'),
      ' y la ',
      el('a', { href: `/${loc}/privacidad`, target: '_blank', rel: 'noopener' }, 'Política de Privacidad'),
      '.');
    cardWide.append(legalNote);

    // Nota discreta: no compite por atención con las tarjetas de precio de arriba.
    const cancelNote = el('div', { class: 'premium-note' },
      icon('info'),
      el('div', { class: 'premium-note-body' },
        el('h3', {}, '¿Cómo cancelo o gestiono mi suscripción?'),
        el('p', {},
          'El pago se procesa a través de Polar, nuestro proveedor de pagos (Merchant of Record) — la suscripción se gestiona ahí, no en este dashboard.'),
        el('p', {},
          'Al suscribirte, Polar te envía un correo de confirmación (no Purgito) con un link a tu portal de cliente. Desde ahí puedes cancelar la suscripción, cambiar de plan (mensual ↔ anual) o ver tus recibos, cuando quieras. Si no lo encuentras, revisa spam o promociones.'),
        el('p', {},
          'Cancelar no corta el acceso de inmediato: el premium sigue activo hasta el final del período ya pagado, y simplemente no se renueva después.')));

    box.append(el('div', { class: 'premium-layout' }, cardWide, cancelNote));
  } catch (e) { renderError(box, e); }
}
