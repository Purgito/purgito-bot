// Cascarón compartido del rediseño (/es/perfil*, /es/dashboard/:id*): navbar
// con dropdowns de perfil e idioma, footer de tres columnas y helpers de
// locale. Los datos de sesión/links llegan como data-attributes del <script>
// de entrada (ver pages/dash.py).

import { el } from './core/dom.js';

export const LANGS = [
  { code: 'es', label: 'Español' },
  { code: 'en', label: 'English' },
  { code: 'ru', label: 'Русский' },
  { code: 'ja', label: '日本語' },
  { code: 'de', label: 'Deutsch' },
];

export function shellData() {
  const s = document.querySelector('script[data-landing]');
  return s ? { ...s.dataset } : {};
}

export function currentLocale() {
  const seg = location.pathname.split('/')[1];
  return LANGS.some(l => l.code === seg) ? seg : 'es';
}

function localePath(code) {
  const parts = location.pathname.split('/');
  parts[1] = code;
  return parts.join('/') || `/${code}/perfil`;
}

// SVG del wordmark, el mismo de la landing (gradiente violeta→magenta).
function logoSvg() {
  const s = el('span', { class: 'nb-logo', 'aria-hidden': 'true' });
  s.innerHTML = '<svg width="26" height="26" viewBox="0 0 26 26">'
    + '<rect x="1" y="1" width="24" height="24" rx="7" fill="url(#nbg)"></rect>'
    + '<path d="M7 9.5 L11 13 L7 16.5" fill="none" stroke="#0B0C10" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></path>'
    + '<line x1="13" y1="17" x2="19" y2="17" stroke="#0B0C10" stroke-width="2.2" stroke-linecap="round"></line>'
    + '<defs><linearGradient id="nbg" x1="0" y1="0" x2="26" y2="26" gradientUnits="userSpaceOnUse">'
    + '<stop stop-color="#8B6EF5"></stop><stop offset="1" stop-color="#FF3D7F"></stop>'
    + '</linearGradient></defs></svg>';
  return s;
}

// Dropdown genérico: click en el trigger abre/cierra, click afuera cierra.
function dropdown(cls, trigger, panel) {
  const wrap = el('div', { class: 'dd ' + cls }, trigger, panel);
  trigger.onclick = (e) => {
    e.stopPropagation();
    const open = wrap.classList.contains('open');
    document.querySelectorAll('.dd.open').forEach(d => d.classList.remove('open'));
    if (!open) wrap.classList.add('open');
  };
  return wrap;
}
document.addEventListener('click', () =>
  document.querySelectorAll('.dd.open').forEach(d => d.classList.remove('open')));

export function langDropdown() {
  const locale = currentLocale();
  const current = LANGS.find(l => l.code === locale) || LANGS[0];
  const panel = el('div', { class: 'dd-panel' },
    LANGS.map(l => el('a', {
      class: 'dd-item' + (l.code === locale ? ' active' : ''),
      href: localePath(l.code),
    }, l.label)));
  const btn = el('button', { class: 'dd-trigger', 'aria-haspopup': 'true' },
    current.code.toUpperCase(), el('span', { class: 'dd-caret' }, '▾'));
  return dropdown('dd-lang', btn, panel);
}

function userDropdown(data) {
  const locale = currentLocale();
  const links = [
    ['Dashboard', `/${locale}/perfil`],
    ['Soporte', data.support],
    ['Documentación', data.docs],
    ['Premium', `${data.landing}/${locale}/premium`],
  ];
  const panel = el('div', { class: 'dd-panel dd-user-panel' },
    el('div', { class: 'dd-user-head' },
      el('img', { src: data.avatar, alt: '' }),
      el('div', {},
        el('div', { class: 'dd-user-name' }, data.username),
        data.email ? el('div', { class: 'dd-user-email' }, data.email) : null)),
    links.map(([label, href]) => el('a', { class: 'dd-item', href }, label)),
    el('a', { class: 'dd-item dd-item-danger', href: '/auth/logout' }, 'Cerrar sesión'));
  const btn = el('button', { class: 'dd-trigger nb-user', 'aria-haspopup': 'true' },
    el('img', { src: data.avatar, alt: '' }),
    el('span', {}, data.username),
    el('span', { class: 'dd-caret' }, '▾'));
  return dropdown('dd-user', btn, panel);
}

export function renderNavbar(data) {
  const locale = currentLocale();
  const nav = document.getElementById('navbar');
  nav.innerHTML = '';
  nav.append(el('div', { class: 'nb-inner' },
    el('a', { class: 'nb-brand', href: data.landing }, logoSvg(), el('span', {}, 'Purgito')),
    el('nav', { class: 'nb-links' },
      el('a', { href: data.docs }, 'Documentación'),
      el('a', { href: `${data.landing}/${locale}/premium` }, 'Premium')),
    el('div', { class: 'nb-right' },
      langDropdown(),
      el('a', { class: 'btn btn-secondary btn-sm', href: `/${locale}/perfil` }, 'Dashboard'),
      userDropdown(data))));
}

export function renderFooter(data) {
  const foot = document.getElementById('footer');
  const col = (title, links) => el('div', { class: 'ft-col' },
    el('div', { class: 'ft-title' }, title),
    links.map(([label, href]) => el('a', { href }, label)));
  foot.innerHTML = '';
  foot.append(el('div', { class: 'ft-inner' },
    el('div', { class: 'ft-cols' },
      col('Recursos', [
        ['Documentación', data.docs], ['Estado', '/health'], ['Guía', data.docs]]),
      col('Purgito', [
        ['Código', data.repo], ['Soporte', data.support], ['Reembolsos', '/terms']]),
      col('Legal', [
        ['Términos', '/terms'], ['Privacidad', '/privacy'], ['Reembolsos', '/terms']])),
    el('div', { class: 'ft-bottom' },
      el('span', { class: 'ft-note' },
        'Hecho por ', el('a', { href: data.repo }, 'punkyyy01'),
        ` · © Purgito ${new Date().getFullYear()} · No afiliado con Discord Inc.`),
      el('div', { class: 'ft-actions' },
        langDropdown(),
        el('button', {
          class: 'btn btn-secondary btn-sm',
          onclick: () => window.scrollTo({ top: 0, behavior: 'smooth' }),
        }, '↑ Volver arriba')))));
}

export function initShell() {
  const data = shellData();
  renderNavbar(data);
  renderFooter(data);
  return data;
}
