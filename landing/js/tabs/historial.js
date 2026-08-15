import { apiFetch } from '/js/core/api.js';
import { el, icon, spinner, emptyState, renderError, formGroup, toast } from '/js/core/dom.js';
import { GUILD_ID, formatDateTime } from '/js/core/config.js';
import { content } from '/js/panel-shell.js';

const PAGE_SIZE = 5;

// Traduce el "action" que graba db.log_audit (ver _log_audit en webapi.py) a
// un texto legible. Lo que no está mapeado se muestra tal cual: mejor un
// action en crudo que un renglón vacío si se agrega uno nuevo acá y se
// olvida sumarlo a este mapa.
const ACTION_LABELS = {
  'chat.settings_update': 'Actualizó la configuración del chat',
  'chat.tunables_update': 'Ajustó los parámetros del chat',
  'channel_settings.update': 'Cambió los ajustes de un canal puntual',
  'corpus.add': 'Agregó un canal de aprendizaje',
  'corpus.remove': 'Quitó un canal de aprendizaje',
  'corpus.amnesia': 'Borró el corpus de las últimas 24 horas (amnesia)',
  'corpus.import': 'Importó corpus desde un archivo',
  'embed_template.create': 'Creó una plantilla de embed',
  'embed_template.update': 'Editó una plantilla de embed',
  'embed_template.delete': 'Eliminó una plantilla de embed',
  'embeds.schedule': 'Programó un anuncio con embed',
  'embeds.send': 'Envió un embed',
  'exempt_channels.add': 'Agregó un canal exento del límite de menciones',
  'exempt_channels.remove': 'Quitó un canal exento del límite de menciones',
  'exempt_roles.add': 'Agregó un rol exento del límite de menciones',
  'exempt_roles.remove': 'Quitó un rol exento del límite de menciones',
  'frases.add': 'Agregó una frase especial',
  'frases.edit': 'Editó una frase especial',
  'frases.remove': 'Eliminó una frase especial',
  'frases.set_pack': 'Cambió el pack de una frase',
  'frase_channels.add': 'Habilitó un canal para frases especiales',
  'frase_channels.remove': 'Deshabilitó un canal para frases especiales',
  'frase_packs.create': 'Creó un pack de frases',
  'frase_packs.delete': 'Eliminó un pack de frases',
  'frase_packs.assign_channel': 'Asignó un pack de frases a un canal',
  'frase_packs.unassign_channel': 'Quitó un pack de frases de un canal',
  'gifs.add': 'Agregó un GIF',
  'gifs.auto_removed': 'Quitó solo un GIF porque su host dejó de servirlo',
  'gifs.remove': 'Eliminó un GIF',
  'gifs.block': 'Bloqueó un GIF',
  'gifs.unblock': 'Desbloqueó un GIF',
  'mention_channels.add': 'Agregó un canal de menciones',
  'mention_channels.remove': 'Quitó un canal de menciones',
  'reactions.add': 'Agregó una reacción',
  'reactions.remove': 'Quitó una reacción',
  'spontaneous_channels.add': 'Agregó un canal de participación espontánea',
  'spontaneous_channels.remove': 'Quitó un canal de participación espontánea',
  'style.update': 'Actualizó el estilo del bot',
  'triggers.create': 'Creó un trigger de canal',
  'triggers.delete': 'Eliminó un trigger de canal',
  'updates_channel.set': 'Configuró el canal de novedades',
  'youtube.add': 'Agregó una suscripción de YouTube',
  'youtube.remove': 'Eliminó una suscripción de YouTube',
  'youtube.update_mention_role': 'Cambió el rol de mención de YouTube',
};

function actionLabel(action) {
  return ACTION_LABELS[action] || action;
}

function getActionIcon(action) {
  if (action.startsWith('gifs.')) return 'film';
  if (action.startsWith('embed')) return 'layout';
  if (action.startsWith('youtube.')) return 'youtube';
  if (action.startsWith('frase') || action.startsWith('triggers.') || action.startsWith('reactions.')) return 'chat';
  if (action.startsWith('style.')) return 'image';
  return 'history';
}

function formatWhen(createdAt) {
  return formatDateTime(new Date(createdAt.replace(' ', 'T') + 'Z'));
}

function entryRow(entry) {
  return el('li', { class: 'audit-item' },
    el('div', { class: 'audit-icon-wrap' }, icon(getActionIcon(entry.action))),
    el('div', { class: 'audit-content', style: 'flex:1' },
      el('div', { class: 'audit-title' },
        el('strong', { class: 'audit-user' }, entry.user_name),
        el('span', { class: 'dim' }, ' — '),
        el('span', { class: 'audit-action' }, actionLabel(entry.action))
      ),
      entry.detail ? el('div', { class: 'audit-detail dim' }, entry.detail) : null
    ),
    el('span', { class: 'audit-date dim' }, formatWhen(entry.created_at))
  );
}

const AUDIT_PATH = (guildId) => `/api/guilds/${guildId}/audit`;

export async function loadHistorial() {
  const box = content();
  box.append(spinner());

  const state = {
    q: '',
    userId: '',
    action: '',
    datePreset: 'all',
    dateFrom: '',
    dateTo: '',
    limit: PAGE_SIZE,
    cursor: null,
    hasMore: false,
    users: [],
  };

  let debounceTimer = null;

  function getDateParams() {
    if (state.datePreset === 'today') {
      const d = new Date().toISOString().slice(0, 10);
      return { date_from: d + ' 00:00:00', date_to: d + ' 23:59:59' };
    }
    if (state.datePreset === 'yesterday') {
      const y = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
      return { date_from: y + ' 00:00:00', date_to: y + ' 23:59:59' };
    }
    if (state.datePreset === '7d') {
      const d = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
      return { date_from: d + ' 00:00:00' };
    }
    if (state.datePreset === '30d') {
      const d = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
      return { date_from: d + ' 00:00:00' };
    }
    if (state.datePreset === 'custom') {
      const res = {};
      if (state.dateFrom) res.date_from = state.dateFrom;
      if (state.dateTo) res.date_to = state.dateTo;
      return res;
    }
    return {};
  }

  function hasActiveFilters() {
    return Boolean(state.q || state.userId || state.action || state.datePreset !== 'all');
  }

  async function fetchAudit(isNextPage = false) {
    const params = new URLSearchParams({ limit: String(state.limit) });
    if (state.q) params.set('q', state.q);
    if (state.userId) params.set('user_id', state.userId);
    if (state.action) params.set('action', state.action);

    const dateParams = getDateParams();
    if (dateParams.date_from) params.set('date_from', dateParams.date_from);
    if (dateParams.date_to) params.set('date_to', dateParams.date_to);

    if (isNextPage && state.cursor) {
      params.set('before_id', String(state.cursor));
    }

    return await apiFetch(`${AUDIT_PATH(GUILD_ID)}?${params.toString()}`);
  }

  try {
    const initialData = await fetchAudit(false);
    box.innerHTML = '';

    if (!initialData.entries.length && !hasActiveFilters()) {
      box.append(emptyState('Todavía no hay cambios registrados en este servidor.'));
      return;
    }

    if (initialData.users && initialData.users.length) {
      state.users = initialData.users;
    }

    // Contenedor principal de Historial
    const container = el('div', { class: 'audit-container' });

    // 1. Buscador
    const searchInput = el('input', {
      type: 'search',
      class: 'audit-search-input',
      placeholder: 'Buscar cambios por texto, usuario o acción…',
      'aria-label': 'Buscar cambios',
      value: state.q,
      oninput: () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          state.q = searchInput.value.trim();
          reloadPage();
        }, 280);
      },
    });

    const searchWrap = el('div', { class: 'audit-search-wrap' },
      el('span', { class: 'audit-search-icon', 'aria-hidden': 'true' }, icon('search')),
      searchInput
    );

    // 2. Selectores de Filtro
    const userSelect = el('select', {
      class: 'audit-select',
      'aria-label': 'Filtrar por usuario',
      onchange: () => {
        state.userId = userSelect.value;
        reloadPage();
      },
    }, el('option', { value: '' }, 'Todos los usuarios'));

    function updateUserOptions() {
      const currentVal = userSelect.value;
      userSelect.innerHTML = '';
      userSelect.append(el('option', { value: '' }, 'Todos los usuarios'));
      for (const u of state.users) {
        const opt = el('option', { value: String(u.user_id) }, u.user_name);
        if (String(u.user_id) === currentVal) opt.selected = true;
        userSelect.append(opt);
      }
    }
    updateUserOptions();

    const actionSelect = el('select', {
      class: 'audit-select',
      'aria-label': 'Filtrar por acción',
      onchange: () => {
        state.action = actionSelect.value;
        reloadPage();
      },
    },
      el('option', { value: '' }, 'Todas las acciones'),
      el('optgroup', { label: 'Contenido' },
        el('option', { value: 'cat:contenido' }, 'Todo en Contenido'),
        el('option', { value: 'frases.' }, 'Frases especiales'),
        el('option', { value: 'frase_packs.' }, 'Packs de frases'),
        el('option', { value: 'triggers.' }, 'Triggers de canal'),
        el('option', { value: 'reactions.' }, 'Reacciones')
      ),
      el('optgroup', { label: 'Chat y configuración' },
        el('option', { value: 'cat:chat' }, 'Todo en Chat y canales'),
        el('option', { value: 'chat.' }, 'Configuración del chat'),
        el('option', { value: 'channel_settings.' }, 'Ajustes de canales'),
        el('option', { value: 'corpus.' }, 'Memoria y aprendizaje'),
        el('option', { value: 'exempt_' }, 'Exenciones de menciones')
      ),
      el('optgroup', { label: 'Multimedia' },
        el('option', { value: 'gifs.' }, 'GIFs')
      ),
      el('optgroup', { label: 'Embeds' },
        el('option', { value: 'embed' }, 'Embeds y plantillas')
      ),
      el('optgroup', { label: 'Integraciones' },
        el('option', { value: 'youtube.' }, 'YouTube')
      ),
      el('optgroup', { label: 'General' },
        el('option', { value: 'style.' }, 'Estilo del bot')
      )
    );

    const customDateWrap = el('div', { class: 'audit-custom-dates', style: 'display:none' });
    const fromInput = el('input', {
      type: 'date',
      class: 'audit-date-input',
      title: 'Fecha inicial',
      onchange: () => {
        state.dateFrom = fromInput.value;
        reloadPage();
      },
    });
    const toInput = el('input', {
      type: 'date',
      class: 'audit-date-input',
      title: 'Fecha final',
      onchange: () => {
        state.dateTo = toInput.value;
        reloadPage();
      },
    });
    customDateWrap.append(el('span', {}, 'Desde'), fromInput, el('span', {}, 'Hasta'), toInput);

    const dateSelect = el('select', {
      class: 'audit-select',
      'aria-label': 'Filtrar por fecha',
      onchange: () => {
        state.datePreset = dateSelect.value;
        customDateWrap.style.display = state.datePreset === 'custom' ? 'inline-flex' : 'none';
        if (state.datePreset !== 'custom') {
          state.dateFrom = '';
          state.dateTo = '';
          fromInput.value = '';
          toInput.value = '';
          reloadPage();
        }
      },
    },
      el('option', { value: 'all' }, 'Cualquier fecha'),
      el('option', { value: 'today' }, 'Hoy'),
      el('option', { value: 'yesterday' }, 'Ayer'),
      el('option', { value: '7d' }, 'Últimos 7 días'),
      el('option', { value: '30d' }, 'Últimos 30 días'),
      el('option', { value: 'custom' }, 'Personalizado…')
    );

    const filtersRow = el('div', { class: 'audit-filters-row' },
      userSelect,
      actionSelect,
      dateSelect,
      customDateWrap
    );

    const chipsRow = el('div', { class: 'audit-active-chips' });

    function renderActiveChips() {
      chipsRow.innerHTML = '';
      if (!hasActiveFilters()) {
        chipsRow.style.display = 'none';
        return;
      }
      chipsRow.style.display = 'flex';

      if (state.q) {
        chipsRow.append(createChip(`Texto: "${state.q}"`, () => {
          state.q = '';
          searchInput.value = '';
          reloadPage();
        }));
      }

      if (state.userId) {
        const u = state.users.find(x => String(x.user_id) === state.userId);
        const name = u ? u.user_name : state.userId;
        chipsRow.append(createChip(`Usuario: ${name}`, () => {
          state.userId = '';
          userSelect.value = '';
          reloadPage();
        }));
      }

      if (state.action) {
        const opt = actionSelect.querySelector(`option[value="${state.action}"]`);
        const label = opt ? opt.textContent : state.action;
        chipsRow.append(createChip(`Acción: ${label}`, () => {
          state.action = '';
          actionSelect.value = '';
          reloadPage();
        }));
      }

      if (state.datePreset !== 'all') {
        const opt = dateSelect.querySelector(`option[value="${state.datePreset}"]`);
        const label = opt ? opt.textContent : state.datePreset;
        chipsRow.append(createChip(`Fecha: ${label}`, () => {
          state.datePreset = 'all';
          dateSelect.value = 'all';
          state.dateFrom = '';
          state.dateTo = '';
          fromInput.value = '';
          toInput.value = '';
          customDateWrap.style.display = 'none';
          reloadPage();
        }));
      }

      const clearAllBtn = el('button', {
        type: 'button',
        class: 'audit-clear-btn',
        onclick: resetAllFilters,
      }, 'Limpiar filtros');
      chipsRow.append(clearAllBtn);
    }

    function createChip(text, onRemove) {
      return el('span', { class: 'audit-chip' },
        el('span', {}, text),
        el('button', {
          type: 'button',
          class: 'audit-chip-x',
          'aria-label': `Quitar filtro ${text}`,
          onclick: onRemove,
        }, icon('x'))
      );
    }

    function resetAllFilters() {
      state.q = '';
      state.userId = '';
      state.action = '';
      state.datePreset = 'all';
      state.dateFrom = '';
      state.dateTo = '';
      searchInput.value = '';
      userSelect.value = '';
      actionSelect.value = '';
      dateSelect.value = 'all';
      fromInput.value = '';
      toInput.value = '';
      customDateWrap.style.display = 'none';
      reloadPage();
    }

    const toolbar = el('div', { class: 'audit-toolbar' },
      searchWrap,
      filtersRow,
      chipsRow
    );

    const listWrap = el('div', { class: 'audit-list-wrap' });
    const list = el('ul', { class: 'item-list' });
    const footer = el('div', { class: 'gif-more-wrap' });

    listWrap.append(list, footer);
    container.append(toolbar, listWrap);
    box.append(formGroup('Historial de cambios', container));

    function renderEntries(entries, append = false) {
      if (!append) list.innerHTML = '';
      for (const entry of entries) {
        list.append(entryRow(entry));
      }
    }

    function renderFooter() {
      footer.innerHTML = '';
      if (!state.hasMore) {
        footer.append(el('span', { class: 'dim' }, 'No hay más acciones'));
        return;
      }
      const btn = el('button', {
        class: 'btn btn-secondary',
        onclick: () => loadMore(btn),
      }, 'Cargar más');
      footer.append(btn);
    }

    async function loadMore(btn) {
      btn.disabled = true;
      btn.textContent = 'Cargando…';
      try {
        const more = await fetchAudit(true);
        renderEntries(more.entries, true);
        if (more.entries.length) {
          state.cursor = more.entries[more.entries.length - 1].id;
        }
        state.hasMore = more.has_more;
        renderFooter();
      } catch (e) {
        toast(e.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Cargar más';
      }
    }

    async function reloadPage() {
      renderActiveChips();
      list.innerHTML = '';
      footer.innerHTML = '';
      list.append(spinner());

      try {
        state.cursor = null;
        const data = await fetchAudit(false);
        list.innerHTML = '';

        if (data.users && data.users.length && !state.users.length) {
          state.users = data.users;
          updateUserOptions();
        }

        if (!data.entries.length) {
          if (hasActiveFilters()) {
            list.append(
              el('div', { class: 'audit-empty-filtered' },
                el('p', { class: 'dim' }, 'No hay cambios que coincidan con estos filtros.'),
                el('button', {
                  type: 'button',
                  class: 'btn btn-secondary btn-sm',
                  onclick: resetAllFilters,
                }, 'Limpiar filtros')
              )
            );
          } else {
            list.append(emptyState('Todavía no hay cambios registrados en este servidor.'));
          }
          return;
        }

        renderEntries(data.entries, false);
        state.cursor = data.entries[data.entries.length - 1].id;
        state.hasMore = data.has_more;
        renderFooter();
      } catch (e) {
        list.innerHTML = '';
        renderError(list, e);
      }
    }

    // Renderizado de la carga inicial
    renderActiveChips();
    renderEntries(initialData.entries, false);
    if (initialData.entries.length) {
      state.cursor = initialData.entries[initialData.entries.length - 1].id;
      state.hasMore = initialData.has_more;
    }
    renderFooter();
  } catch (e) {
    renderError(box, e);
  }
}
