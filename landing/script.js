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

/* Íconos outline de 24×24 — mismo trazo que el resto del sitio. El color y el
   grosor salen del CSS (.menu-i), acá solo viven los paths. */
var ICONS = {
  help:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>' +
        '<path d="m5.6 5.6 3.2 3.2m6.4 6.4 3.2 3.2m0-12.8-3.2 3.2m-6.4 6.4-3.2 3.2"/>',
  book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a2.5 2.5 0 0 1 0-5H20"/>',
  star: '<path d="M12 3 14.3 8.8 20.6 9.2 15.7 13.2 17.3 19.3 12 15.9 6.7 19.3 8.3 13.2 3.4 9.2 9.7 8.8Z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>'
};

function svgIcon(paths) {
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'menu-i');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = paths;
  return svg;
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

/* ── Estado de sesión en el nav: consulta la sesión de la propia app y
   renderiza login o avatar+dropdown. El slot arranca vacío y aparece ya
   resuelto (sin parpadeo). Cualquier fallo del fetch degrada en silencio al
   botón de login — nunca un error visible ni romper el resto de la página. */

(function () {
  // Mismo origen que la landing: nginx enruta /auth y /api a la app.
  var PANEL = '';
  var LOC = locale();

  // Entrada al panel: la lista de servidores del perfil, no el selector viejo.
  var DASHBOARD = PANEL + '/' + LOC + '/perfil';

  document.querySelectorAll('.dash-link').forEach(function (a) {
    a.href = DASHBOARD;
  });

  // El locale viaja para volver a purgito.app/es tras el callback, no a la raíz.
  var LOGIN = PANEL + '/auth/login?from=landing&locale=' + LOC;

  /* "Subscribirse" de /es/premium: sin sesión manda a login, con sesión al
     selector de servidores. Conserva el plan elegido hasta el panel, donde el
     checkout sí conoce el guild y envía el producto correspondiente a Polar. */
  function selectedPlan() {
    var toggle = document.getElementById('plan-toggle');
    return toggle && toggle.dataset.plan === 'annual' ? 'annual' : 'monthly';
  }

  function setSubscribe(href) {
    document.querySelectorAll('.js-subscribe').forEach(function (a) {
      var url = new URL(href, location.origin);
      url.searchParams.set('plan', selectedPlan());
      a.href = url.pathname + url.search + url.hash;
    });
  }

  var subscribeHref = LOGIN;
  document.addEventListener('premiumplanchange', function () {
    setSubscribe(subscribeHref);
  });

  var slot = document.getElementById('auth-slot');
  if (!slot) return;

  function renderLogin() {
    subscribeHref = LOGIN;
    setSubscribe(subscribeHref);
    var a = document.createElement('a');
    a.className = 'nav-link btn-login';
    a.href = LOGIN;

    a.innerHTML = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.3 5.3A16.9 16.9 0 0 0 15.1 4l-.2.4a12.6 12.6 0 0 1 3.7 1.9 15.9 15.9 0 0 0-13.3 0A12.6 12.6 0 0 1 9 4.4L8.8 4A16.9 16.9 0 0 0 4.6 5.3C2 9.2 1.3 13 1.7 16.7a17 17 0 0 0 5.1 2.6l1-1.7a11 11 0 0 1-1.8-.8l.4-.3a12.2 12.2 0 0 0 10.4 0l.4.3a11 11 0 0 1-1.8.8l1 1.7a17 17 0 0 0 5.1-2.6c.5-4.3-.6-8.1-2.2-11.4ZM8.5 14.5c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm7 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>';
    a.appendChild(document.createTextNode('Iniciar sesión con Discord'));
    slot.appendChild(a);
  }

  function renderUser(data) {
    subscribeHref = DASHBOARD;
    setSubscribe(subscribeHref);
    var wrap = document.createElement('div');
    wrap.className = 'auth-wrap';

    /* El bloque avatar+nombre es un LINK directo al perfil, y el chevron de al
       lado es el único que abre el menú. Antes había además un botón
       "Dashboard" suelto en el nav y otro repetido dentro del menú: tres
       caminos a la misma pantalla. Queda uno solo, el más directo. */
    var profile = document.createElement('a');
    profile.className = 'auth-btn';
    profile.href = DASHBOARD;

    if (data.avatar_url) {
      var img = document.createElement('img');
      img.className = 'auth-avatar';
      img.src = data.avatar_url;
      img.alt = '';
      profile.appendChild(img);
    }
    var name = document.createElement('span');
    name.className = 'auth-name';
    name.textContent = data.name || 'Usuario';
    profile.appendChild(name);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'auth-chev';
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-label', 'Abrir menú de cuenta');

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

    /* null = separador entre grupos, tal cual el boceto. Sin "Dashboard": a esa
       pantalla se llega clickeando el bloque avatar+nombre de arriba. */
    [
      { href: 'https://discord.gg/5U7HKyxnBv', label: 'Soporte', icon: ICONS.help },
      { href: '/' + LOC + '/documentacion', label: 'Documentación', icon: ICONS.book },
      null,
      { href: '/' + LOC + '/premium', label: 'Premium', icon: ICONS.star },
      {
        href: PANEL + '/auth/logout',
        label: 'Cerrar sesión',
        icon: ICONS.logout,
        danger: true,
        logout: true
      }
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
      if (item.logout) {
        // POST, no navegación GET directa: logout muta estado server-side
        // (revoke_session) y SameSite=Lax deja pasar la cookie en un GET de
        // navegación top-level venga de donde venga -- ver el comentario en
        // start_web_server (webapi.py) junto a app.router.add_post("/auth/logout").
        a.addEventListener('click', function (e) {
          e.preventDefault();
          fetch(item.href, { method: 'POST', credentials: 'include' })
            .catch(function () {})
            .then(function () { location.href = '/' + LOC; });
        });
      }
      a.appendChild(svgIcon(item.icon));
      a.appendChild(document.createTextNode(item.label));
      menu.appendChild(a);
    });

    wrap.appendChild(profile);
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

/* ── Toggle Mensual/Anual de /es/premium. Mantiene sincronizados el precio,
   los avisos de prueba y los CTA. El plan también viaja al panel, que es el
   único lugar donde se puede iniciar el checkout por servidor. */

(function () {
  var toggle = document.getElementById('plan-toggle');
  if (!toggle) return;

  var PLANS = {
    mensual: {
      key: 'monthly', amount: '$4.99', per: '/mensual', trial: true,
      cta: 'Comenzar prueba gratis', heroCta: 'Comenzar 7 días gratis',
      notes: 'La prueba gratis de 7 días está disponible para suscripciones mensuales. La suscripción se factura de forma segura mediante Polar y se vincula al servidor de Discord que selecciones en tu panel. Puedes cancelar en cualquier momento antes de que termine el periodo de prueba sin ningún cargo.'
    },
    anual: {
      key: 'annual', amount: '$39.99', per: '/anual', trial: false,
      cta: 'Suscribirse al plan anual', heroCta: 'Elegir plan anual',
      notes: 'La suscripción anual se factura de forma segura mediante Polar y se vincula al servidor de Discord que selecciones en tu panel. El primer cobro se realiza al suscribirte.'
    }
  };

  var amount = document.getElementById('plan-amount');
  var per = document.getElementById('plan-per');
  var trial = document.getElementById('plan-trial');
  var trustTrial = document.getElementById('plan-trust-trial');
  var cta = document.getElementById('plan-cta');
  var heroCta = document.querySelector('.prem-cta-main.js-subscribe');
  var notes = document.getElementById('plan-sub-notes');
  var opts = toggle.querySelectorAll('.toggle-opt');

  function selectPlan(name) {
    var plan = PLANS[name];
    if (!plan) return;

    toggle.dataset.plan = plan.key;
    opts.forEach(function (b) {
      var on = b.dataset.plan === name;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', String(on));
    });
    amount.textContent = plan.amount;
    per.textContent = plan.per;
    trial.hidden = !plan.trial;
    trustTrial.hidden = !plan.trial;
    cta.textContent = plan.cta;
    heroCta.textContent = plan.heroCta;
    notes.textContent = plan.notes;
    document.dispatchEvent(new CustomEvent('premiumplanchange', { detail: { plan: plan.key } }));
  }

  toggle.addEventListener('click', function (e) {
    var btn = e.target.closest('.toggle-opt');
    if (!btn) return;
    selectPlan(btn.dataset.plan);
  });
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

/* ── Dropdowns de navegación (desktop): Recursos, Comunidad, etc.
   Inspirado en el comportamiento fluido de la referencia: hover bridge sin
   desaparecer en la transición, soporte para click, cambio inmediato entre
   dropdowns sin parpadeo, accesibilidad (aria-expanded), Escape y click fuera. */

(function () {
  var items = Array.prototype.slice.call(document.querySelectorAll('[data-nav-dropdown]'));
  if (!items.length) return;

  var currentOpen = null;
  var closeTimer = null;

  function openDropdown(item) {
    if (closeTimer) {
      clearTimeout(closeTimer);
      closeTimer = null;
    }
    if (currentOpen && currentOpen !== item) {
      closeDropdown(currentOpen);
    }
    var btn = item.querySelector('.nav-dropdown-btn');
    var menu = item.querySelector('.nav-dropdown');
    if (!btn || !menu) return;

    item.classList.add('is-open');
    btn.setAttribute('aria-expanded', 'true');
    menu.hidden = false;
    currentOpen = item;
  }

  function closeDropdown(item) {
    if (!item) return;
    var btn = item.querySelector('.nav-dropdown-btn');
    var menu = item.querySelector('.nav-dropdown');
    item.classList.remove('is-open');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    if (menu) menu.hidden = true;
    if (currentOpen === item) currentOpen = null;
  }

  function scheduleClose(item) {
    if (closeTimer) clearTimeout(closeTimer);
    closeTimer = setTimeout(function () {
      closeDropdown(item);
      closeTimer = null;
    }, 140);
  }

  items.forEach(function (item) {
    var btn = item.querySelector('.nav-dropdown-btn');
    var menu = item.querySelector('.nav-dropdown');
    if (!btn || !menu) return;

    // Pointer/Hover (solo para mouse/puntero fino)
    item.addEventListener('mouseenter', function () {
      openDropdown(item);
    });
    item.addEventListener('mouseleave', function () {
      scheduleClose(item);
    });

    // Click en el botón
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (item.classList.contains('is-open')) {
        closeDropdown(item);
      } else {
        openDropdown(item);
      }
    });

    // Teclado: flechas y atajos accesibles
    btn.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openDropdown(item);
        var firstLink = menu.querySelector('a');
        if (firstLink) firstLink.focus();
      }
    });

    menu.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeDropdown(item);
        btn.focus();
      }
    });

    // Al clickear un enlace dentro, cerrar el menú
    menu.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () {
        closeDropdown(item);
      });
    });
  });

  // Click fuera cierra cualquier dropdown abierto
  document.addEventListener('click', function (e) {
    if (currentOpen && !currentOpen.contains(e.target)) {
      closeDropdown(currentOpen);
    }
  });

  // Escape global
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && currentOpen) {
      var btn = currentOpen.querySelector('.nav-dropdown-btn');
      closeDropdown(currentOpen);
      if (btn) btn.focus();
    }
  });
})();

/* ── Menú móvil y acordeones para pantallas pequeñas (< 900px).
   Sin dependencia de hover, navegación táctil y accesible. */

(function () {
  var toggle = document.getElementById('nav-mobile-toggle');
  var panel = document.getElementById('nav-mobile-panel');
  var nav = document.querySelector('.nav');
  if (!toggle || !panel) return;

  function setMobileOpen(open) {
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('no-scroll', open);
    if (nav) nav.classList.toggle('is-mobile-open', open);
  }

  toggle.addEventListener('click', function (e) {
    e.stopPropagation();
    setMobileOpen(panel.hidden);
  });

  // Acordeones internos de Recursos y Comunidad
  panel.querySelectorAll('.nav-mobile-accordion-btn').forEach(function (btn) {
    var sub = btn.nextElementSibling;
    if (!sub) return;
    btn.addEventListener('click', function () {
      var isClosed = sub.hidden;
      sub.hidden = !isClosed;
      btn.setAttribute('aria-expanded', String(isClosed));
    });
  });

  // Click en cualquier enlace dentro del panel cierra el menú
  panel.querySelectorAll('a').forEach(function (a) {
    a.addEventListener('click', function () {
      setMobileOpen(false);
    });
  });

  // Escape cierra el menú móvil
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden) {
      setMobileOpen(false);
      toggle.focus();
    }
  });

  // Si se redimensiona la ventana a escritorio, cerrar automáticamente
  window.addEventListener('resize', function () {
    if (window.innerWidth > 900 && !panel.hidden) {
      setMobileOpen(false);
    }
  });
})();

/* ── Fondo dinámico de la navbar según scroll:
   Transparente en la parte superior (scrollY = 0) para integrarse naturalmente
   con la página, y con fondo translúcido + blur al desplazarse (> 16px). */

(function () {
  var nav = document.querySelector('.nav');
  if (!nav) return;

  var SCROLL_THRESHOLD = 16;
  var ticking = false;

  function updateNavScroll() {
    var scrolled = window.scrollY > SCROLL_THRESHOLD;
    nav.classList.toggle('is-scrolled', scrolled);
    ticking = false;
  }

  window.addEventListener('scroll', function () {
    if (!ticking) {
      window.requestAnimationFrame(updateNavScroll);
      ticking = true;
    }
  }, { passive: true });

  // Evaluar estado al cargar o refrescar la página
  updateNavScroll();
})();

