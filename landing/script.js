'use strict';

/* Ticker del hero: frases cortas que parodian a un bot de Markov de primer
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

/* Estado de sesión en el nav: consulta la sesión compartida con el panel y
   renderiza login o avatar+dropdown. El slot arranca vacío y aparece ya
   resuelto (sin parpadeo). Cualquier fallo del fetch degrada en silencio al
   botón de login — nunca un error visible ni romper el resto de la página. */

(function () {
  var PANEL = 'https://panel.purgito.app';
  var slot = document.getElementById('auth-slot');
  if (!slot) return;

  function renderLogin() {
    var a = document.createElement('a');
    a.className = 'btn btn-login';
    a.href = PANEL + '/auth/login?from=landing';
    a.textContent = 'Iniciar sesión con Discord';
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
    name.textContent = data.username || 'Usuario';
    btn.appendChild(name);

    var chev = document.createElement('span');
    chev.className = 'auth-chevron';
    chev.setAttribute('aria-hidden', 'true');
    chev.textContent = '▾';
    btn.appendChild(chev);

    var menu = document.createElement('div');
    menu.className = 'auth-menu';
    menu.hidden = true;

    var head = document.createElement('p');
    head.className = 'auth-menu-name';
    head.textContent = data.username || 'Usuario';
    menu.appendChild(head);

    var sep = document.createElement('hr');
    sep.className = 'auth-menu-sep';
    menu.appendChild(sep);

    [
      { href: PANEL + '/servers', label: 'Panel de administración' },
      { href: PANEL + '/auth/logout', label: 'Cerrar sesión' }
    ].forEach(function (item) {
      var a = document.createElement('a');
      a.className = 'auth-menu-item';
      a.href = item.href;
      a.textContent = item.label;
      menu.appendChild(a);
    });

    function setOpen(open) {
      menu.hidden = !open;
      btn.setAttribute('aria-expanded', String(open));
    }
    btn.addEventListener('click', function () {
      setOpen(menu.hidden);
    });
    document.addEventListener('click', function (e) {
      if (!menu.hidden && !wrap.contains(e.target)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !menu.hidden) {
        setOpen(false);
        btn.focus();
      }
    });

    wrap.appendChild(btn);
    wrap.appendChild(menu);
    slot.appendChild(wrap);
  }

  fetch(PANEL + '/api/public/me', { credentials: 'include' })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (data && data.logged_in) renderUser(data);
      else renderLogin();
    })
    .catch(renderLogin);
})();

/* Fade + slide-in de las filas del showcase al entrar en viewport.
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
