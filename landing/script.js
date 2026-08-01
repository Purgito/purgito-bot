'use strict';

/* Homepage de purgito.app — vainilla, sin dependencias.
   Cuatro bloques independientes: si uno falla, los otros siguen andando. */

var LANGS = ['es', 'en', 'ru', 'ja', 'de'];

/* Idioma del path (purgito.app/es/…); si la landing se sirve sin prefijo,
   cae al idioma del navegador y por último a español. */
function locale() {
  var seg = location.pathname.split('/')[1];
  if (LANGS.indexOf(seg) !== -1) return seg;
  var nav = (navigator.language || 'es').slice(0, 2).toLowerCase();
  return LANGS.indexOf(nav) !== -1 ? nav : 'es';
}

/* Abre/cierra un popover: click afuera y Escape lo cierran. Lo comparten el
   selector de idioma y el menú de perfil. */
function popover(btn, menu, container) {
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
  }
  btn.addEventListener('click', function () { setOpen(menu.hidden); });
  document.addEventListener('click', function (e) {
    if (!menu.hidden && !container.contains(e.target)) setOpen(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !menu.hidden) { setOpen(false); btn.focus(); }
  });
  return setOpen;
}

/* ── Ticker del hero: frases cortas que parodian a un bot de Markov de primer
   orden entrenado en chat de Discord. Tipeo + glitch corto, vainilla, sin
   librerías. Respeta prefers-reduced-motion (cambio directo, sin animación). */

(function () {
  var PHRASES = [
    'no cacho ni lo que estoy diciendo pero igual',
    'alguien vio el mensaje como de recién que decía',
    'esto claramente no era lo que iba a',
    'ya po pero quién fue el que mandó el',
    'el meme estaba bueno hasta que después nadie',
    'creo que me perdí como en la parte tres del',
    'según lo que leí esto no tiene mucho',
    'espera espera eso lo dije yo o fue el otro',
    'básicamente sí pero también depende de si',
    'el gif que subieron ayer todavía me da un poco de',
    'no me acuerdo de qué hablábamos pero era importante',
    'confirmo que esto es real aunque no estoy tan',
    'la música se cortó justo cuando venía la mejor',
    'leí demasiados mensajes y ahora solo pienso en',
    'posiblemente tengan razón o posiblemente yo esté',
    'wena la idea igual pero cómo se supone que uno',
    'juraría que ese comando existía o quizás lo soñé',
    'al final terminamos hablando de cualquier cosa menos del'
  ];

  var textEl = document.getElementById('ticker-text');
  if (!textEl) return;

  var TYPE_MS = 45;    // ms por caracter tipeado
  var HOLD_MS = 2800;  // pausa con la frase completa en pantalla
  var GLITCH_MS = 240; // duración del glitch al cambiar de frase

  var i = 0;
  function pickNext() {
    var p = PHRASES[i % PHRASES.length];
    i++;
    return p;
  }

  // Sin animación: cambio directo, con un respiro proporcional al largo.
  function runStatic() {
    textEl.textContent = pickNext();
    setTimeout(runStatic, HOLD_MS + 1200);
  }

  function typePhrase(phrase, pos) {
    if (pos > phrase.length) {
      setTimeout(swapOut, HOLD_MS);
      return;
    }
    textEl.textContent = phrase.slice(0, pos);
    setTimeout(function () { typePhrase(phrase, pos + 1); }, TYPE_MS);
  }

  function swapOut() {
    textEl.classList.add('glitch');
    setTimeout(function () {
      textEl.classList.remove('glitch');
      textEl.textContent = '';
      typePhrase(pickNext(), 0);
    }, GLITCH_MS);
  }

  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    runStatic();
  } else {
    typePhrase(pickNext(), 0);
  }
})();

/* ── Selector de idioma (navbar y footer). El código visible sale del idioma
   activo y cada enlace reescribe solo el prefijo del path, conservando el
   resto de la ruta. Los idiomas sin traducción se muestran atenuados y no
   navegan — la lista viene del <head> (window.READY_LANGS). */

(function () {
  var READY = window.READY_LANGS || ['es'];
  var current = locale();
  var seg = location.pathname.split('/')[1];
  // Si el path ya venía con prefijo, el resto es lo que sigue; si no, todo.
  var rest = LANGS.indexOf(seg) !== -1
    ? location.pathname.slice(seg.length + 1)
    : location.pathname;

  document.querySelectorAll('[data-lang-picker]').forEach(function (picker) {
    var btn = picker.querySelector('.lang-btn');
    var menu = picker.querySelector('.lang-menu');
    if (!btn || !menu) return;

    var code = picker.querySelector('[data-lang-code]');
    if (code) code.textContent = current.toUpperCase();

    menu.querySelectorAll('.lang-item').forEach(function (item) {
      var lang = item.dataset.lang;
      if (READY.indexOf(lang) === -1) {
        // Sin href no es clickeable ni enfocable: queda visible pero inerte.
        item.removeAttribute('href');
        item.setAttribute('aria-disabled', 'true');
        item.insertAdjacentHTML('beforeend', '<span class="soon">Próximamente</span>');
        return;
      }
      item.href = '/' + lang + (rest || '/') + location.search + location.hash;
      item.setAttribute('aria-checked', String(lang === current));
    });

    popover(btn, menu, picker);
  });
})();

/* ── Estado de sesión en el nav: consulta la sesión compartida con el panel y
   renderiza login o avatar+dropdown. El slot arranca vacío y aparece ya
   resuelto (sin parpadeo). Cualquier fallo del fetch degrada en silencio al
   botón de login — nunca un error visible ni romper el resto de la página. */

(function () {
  var PANEL = 'https://panel.purgito.app';
  var LOC = locale();

  // Entrada al panel: la lista de servidores del perfil, no el selector viejo.
  var DASHBOARD = PANEL + '/' + LOC + '/perfil';

  document.querySelectorAll('#nav-dash, .dash-link').forEach(function (a) {
    a.href = DASHBOARD;
  });

  var slot = document.getElementById('auth-slot');
  if (!slot) return;

  function renderLogin() {
    var a = document.createElement('a');
    a.className = 'nav-link btn-login';
    // El locale viaja para volver a purgito.app/es tras el callback, no a la raíz.
    a.href = PANEL + '/auth/login?from=landing&locale=' + LOC;

    a.innerHTML = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.3 5.3A16.9 16.9 0 0 0 15.1 4l-.2.4a12.6 12.6 0 0 1 3.7 1.9 15.9 15.9 0 0 0-13.3 0A12.6 12.6 0 0 1 9 4.4L8.8 4A16.9 16.9 0 0 0 4.6 5.3C2 9.2 1.3 13 1.7 16.7a17 17 0 0 0 5.1 2.6l1-1.7a11 11 0 0 1-1.8-.8l.4-.3a12.2 12.2 0 0 0 10.4 0l.4.3a11 11 0 0 1-1.8.8l1 1.7a17 17 0 0 0 5.1-2.6c.5-4.3-.6-8.1-2.2-11.4ZM8.5 14.5c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm7 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>';
    a.appendChild(document.createTextNode('Iniciar sesión con Discord'));
    slot.appendChild(a);
  }

  function renderUser(data) {
    var wrap = document.createElement('div');
    wrap.className = 'auth-wrap';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'auth-btn';
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');

    if (data.avatar_url) {
      var img = document.createElement('img');
      img.className = 'auth-avatar';
      img.src = data.avatar_url;
      img.alt = '';
      btn.appendChild(img);
    }
    var name = document.createElement('span');
    name.className = 'auth-name';
    name.textContent = data.name || 'Usuario';
    btn.appendChild(name);

    var chev = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chev.setAttribute('class', 'chev');
    chev.setAttribute('viewBox', '0 0 24 24');
    chev.setAttribute('aria-hidden', 'true');
    chev.innerHTML = '<path d="M6 9l6 6 6-6"/>';
    btn.appendChild(chev);

    var menu = document.createElement('div');
    menu.className = 'auth-menu';
    menu.hidden = true;

    // Cabecera: foto, nick y email del usuario logueado.
    var head = document.createElement('div');
    head.className = 'auth-menu-head';
    if (data.avatar_url) {
      var big = document.createElement('img');
      big.src = data.avatar_url;
      big.alt = '';
      head.appendChild(big);
    }
    var ident = document.createElement('div');
    var nick = document.createElement('p');
    nick.className = 'auth-menu-name';
    nick.textContent = data.name || 'Usuario';
    ident.appendChild(nick);
    if (data.email) {
      var mail = document.createElement('p');
      mail.className = 'auth-menu-mail';
      mail.textContent = data.email;
      ident.appendChild(mail);
    }
    head.appendChild(ident);
    menu.appendChild(head);

    // null = separador entre grupos, tal cual el boceto.
    [
      { href: DASHBOARD, label: 'Dashboard' },
      null,
      { href: 'https://discord.gg/5U7HKyxnBv', label: 'Soporte' },
      { href: '/' + LOC + '/docs', label: 'Documentación' },
      null,
      { href: '/' + LOC + '/premium', label: 'Premium' },
      { href: PANEL + '/auth/logout', label: 'Cerrar sesión', danger: true }
    ].forEach(function (item) {
      if (!item) {
        var hr = document.createElement('hr');
        hr.className = 'auth-menu-sep';
        menu.appendChild(hr);
        return;
      }
      var a = document.createElement('a');
      a.className = 'auth-menu-item' + (item.danger ? ' danger' : '');
      a.href = item.href;
      var dot = document.createElement('span');
      dot.className = 'dot';
      dot.setAttribute('aria-hidden', 'true');
      a.appendChild(dot);
      a.appendChild(document.createTextNode(item.label));
      menu.appendChild(a);
    });

    wrap.appendChild(btn);
    wrap.appendChild(menu);
    slot.appendChild(wrap);

    popover(btn, menu, wrap);
  }

  fetch(PANEL + '/api/me', { credentials: 'include' })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (data && data.logged_in) renderUser(data);
      else renderLogin();
    })
    .catch(renderLogin);
})();

/* ── Fade + slide-in de las secciones al entrar en viewport.
   Solo se activa (clase js-reveal en <html>) si hay IntersectionObserver y
   sin prefers-reduced-motion; en cualquier otro caso el contenido queda
   visible desde el inicio. */

(function () {
  var rows = document.querySelectorAll('.reveal');
  if (!rows.length || !('IntersectionObserver' in window)) return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  document.documentElement.classList.add('js-reveal');

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('in');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });

  rows.forEach(function (row) { io.observe(row); });
})();
