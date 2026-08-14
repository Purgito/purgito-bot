import { apiFetch } from '/js/core/api.js';
import { el, spinner, emptyState, renderError, formGroup, toast } from '/js/core/dom.js';
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

// created_at llega como timestamp de SQLite en UTC sin sufijo de zona
// ("YYYY-MM-DD HH:MM:SS"); hay que marcarlo como tal antes de pasarlo a
// Date, si no el navegador lo toma como hora local y corre el horario.
function formatWhen(createdAt) {
  return formatDateTime(new Date(createdAt.replace(' ', 'T') + 'Z'));
}

function entryRow(entry) {
  return el('li', {},
    el('div', { style: 'flex:1' },
      el('div', {}, el('strong', {}, entry.user_name), ' — ' + actionLabel(entry.action)),
      entry.detail ? el('div', { class: 'dim' }, entry.detail) : null),
    el('span', { class: 'dim' }, formatWhen(entry.created_at)));
}

// Ruta en su propio literal, sin la query pegada: test_dashboard_routes.py
// (tests/, no landing/) extrae los strings que arrancan con "/api/" tal
// cual para chequear que la API los registre, y una query pegada ahí la
// haría no matchear con la forma real de la ruta.
const AUDIT_PATH = (guildId) => `/api/guilds/${guildId}/audit`;

export async function loadHistorial() {
  const box = content();
  box.append(spinner());
  try {
    const data = await apiFetch(`${AUDIT_PATH(GUILD_ID)}?limit=${PAGE_SIZE}`);
    box.innerHTML = '';

    if (!data.entries.length) {
      box.append(emptyState('Todavía no hay cambios registrados en este servidor.'));
      return;
    }

    const list = el('ul', { class: 'item-list' });
    for (const entry of data.entries) list.append(entryRow(entry));
    box.append(formGroup('Historial de cambios', list));

    // Cursor por id (no offset): la tabla crece todo el tiempo, así que
    // paginar por offset podría duplicar o saltear filas si se inserta una
    // nueva mientras el admin sigue clickeando "Cargar más".
    let cursor = data.entries[data.entries.length - 1].id;
    let hasMore = data.has_more;

    // Clase reutilizada de tabs/gifs.js (mismo estilo "botón centrado
    // debajo de una lista paginada"), no hace falta una nueva regla en
    // dash.css para esto.
    const footer = el('div', { class: 'gif-more-wrap' });
    box.append(footer);

    const renderFooter = () => {
      footer.innerHTML = '';
      if (!hasMore) {
        footer.append(el('span', { class: 'dim' }, 'No hay más acciones'));
        return;
      }
      const btn = el('button', { class: 'btn btn-secondary', onclick: () => loadMore(btn) }, 'Cargar más');
      footer.append(btn);
    };

    const loadMore = async (btn) => {
      btn.disabled = true;
      btn.textContent = 'Cargando…';
      try {
        const more = await apiFetch(`${AUDIT_PATH(GUILD_ID)}?limit=${PAGE_SIZE}&before_id=${cursor}`);
        for (const entry of more.entries) list.append(entryRow(entry));
        if (more.entries.length) cursor = more.entries[more.entries.length - 1].id;
        hasMore = more.has_more;
        renderFooter();
      } catch (e) {
        toast(e.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Cargar más';
      }
    };

    renderFooter();
  } catch (e) { renderError(box, e); }
}
