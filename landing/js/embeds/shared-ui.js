// Helpers de UI compartidos por ambos editores de embeds + el ruteo del tab
// Embeds (loadEmbeds / renderEmbedEditor / renderEmbedTemplates) y la carga de
// un link compartido. Es el módulo más acoplado del bloque de embeds.

import {
  GUILD_ID, emojiCache, setEmojiCache, uploadedImagesCache, setUploadedImagesCache,
} from '/js/core/config.js';
import { apiFetch, humanError } from '/js/core/api.js';
import { el, spinner, emptyState, icon, toast, embedImg, renderError, helpIcon } from '/js/core/dom.js';
import { discordTimestampText } from '/js/core/markdown.js';
import {
  detectGif, docFromLayout, docFromEmbeds, templateSnippet, layoutSnippet, colorToHex,
  MAX_WEBHOOK_USERNAME,
} from '/js/embeds/state.js';
import {
  _embedTab, _embedMode, setEmbedTab, setEmbedMode, setLayoutDoc, setEmbedDoc,
} from '/js/embeds/session.js';
import { getRoles, getChannels, content } from '/js/panel-shell.js';
import { saveHistorySnapshot } from '/js/embeds/persistence.js';
import { renderClassicEditor } from '/js/embeds/classic-editor.js';
import { renderLayoutEditor } from '/js/embeds/layout-editor.js';
// Alias `tr` (no `t`): este módulo ya usa `t` como nombre de variable de
// loop/template en varios lugares (ver renderEmbedTemplates), así que
// importar la función de traducción como `t` colisionaría con eso.
import { t, addStrings } from '../core/i18n.js';

addStrings({
  es: {
    'embedsShared.tabMenciones': 'Menciones',
    'embedsShared.tabFecha': 'Fecha',
    'embedsShared.tabEmoji': 'Emoji',
    'embedsShared.searchRoleChannel': 'Buscar rol o canal…',
    'embedsShared.noResults': 'Sin resultados',
    'embedsShared.styleShortTime': 'Hora corta',
    'embedsShared.styleLongTime': 'Hora con segundos',
    'embedsShared.styleShortDate': 'Fecha corta',
    'embedsShared.styleLongDate': 'Fecha larga',
    'embedsShared.styleShortDateTime': 'Fecha y hora',
    'embedsShared.styleLongDateTime': 'Fecha y hora completa',
    'embedsShared.styleRelative': 'Relativo (hace / en…)',
    'embedsShared.searchEmoji': 'Buscar emoji…',
    'embedsShared.insertTitle': 'Insertar mención, fecha o emoji',
    'embedsShared.connectionError': 'No se pudo conectar con el servidor.',
    'embedsShared.uploadedImagesTitle': 'Imágenes subidas antes',
    'embedsShared.noImagesYet': 'Todavía no subiste ninguna imagen en este servidor.',
    'embedsShared.uploadingImage': 'Subiendo imagen…',
    'embedsShared.imageUploaded': 'Imagen subida',
    'embedsShared.uploadFailed': 'No se pudo subir: {error}',
    'embedsShared.pasteImageUrl': '…o pega un enlace de imagen',
    'embedsShared.resolvingTenorGif': 'Resolviendo GIF de Tenor…',
    'embedsShared.uploadImage': 'Subir imagen',
    'embedsShared.imageFormatHint': 'PNG, JPG, GIF o WEBP, hasta 8 MB.',
    'embedsShared.pasteHintTitle': 'También puedes pegar con {hint} con el campo enfocado',
    'embedsShared.noImageInClipboard': 'No hay imagen en el portapapeles',
    'embedsShared.useHintPaste': 'Usa {hint} con el campo de URL enfocado',
    'embedsShared.pasteButton': 'Pegar ({hint})',
    'embedsShared.chooseFromUploads': 'Elegir de subidas anteriores',
    'embedsShared.colorPurgito': 'Purgito',
    'embedsShared.colorRed': 'Rojo',
    'embedsShared.colorYellow': 'Amarillo',
    'embedsShared.colorGreen': 'Verde',
    'embedsShared.colorBlurple': 'Blurple',
    'embedsShared.colorPink': 'Rosa',
    'embedsShared.colorPurple': 'Violeta',
    'embedsShared.colorWhite': 'Blanco',
    'embedsShared.colorBlack': 'Negro',
    'embedsShared.rolesPingLabel': 'Roles que SÍ pueden ser pingueados (vacío = nadie; Ctrl+click para varios)',
    'embedsShared.identityWarn': 'El bot no tiene permiso de "Gestionar webhooks" en este canal, así que nombre/avatar personalizado no va a funcionar acá — revisa los permisos del canal o vuelve a invitar al bot.',
    'embedsShared.customIdentityLabel': 'Nombre y avatar personalizado',
    'embedsShared.customIdentityHint': 'Si completas alguno, el mensaje se manda con un webhook propio del canal en vez de como Purgito — los botones siguen funcionando igual.',
    'embedsShared.nameLabel': 'Nombre',
    'embedsShared.avatarLabel': 'Avatar',
    'embedsShared.sendOptionsSummary': 'Opciones de envío',
    'embedsShared.silentSend': 'Envío silencioso (sin notificación push)',
    'embedsShared.restrictMentions': 'No mencionar a nadie salvo lo explícito',
    'embedsShared.tabEditor': 'Crear / Enviar',
    'embedsShared.tabTemplates': 'Mis plantillas',
    'embedsShared.tabVariables': 'Variables',
    'embedsShared.varsSectionTitle': 'Variables disponibles',
    'embedsShared.varsSectionDesc': 'Utiliza estas variables dentro de tus mensajes o embeds. Purgito las reemplazará automáticamente con la información del servidor o usuario correspondiente al momento de enviar el mensaje.',
    'embedsShared.varsGeneralGroup': 'Variables generales',
    'embedsShared.varsGeneralDesc': 'Disponibles en cualquier mensaje, embed o evento del servidor.',
    'embedsShared.varsBoostGroup': 'Variables de Boosts',
    'embedsShared.varsBoostDesc': 'Solo disponibles cuando el mensaje se envía como respuesta a un Boost al servidor.',
    'embedsShared.varsCatUser': 'Usuario',
    'embedsShared.varsCatServer': 'Servidor',
    'embedsShared.varsCatChannel': 'Canal',
    'embedsShared.varsCatDate': 'Fecha',
    'embedsShared.varsCopy': 'Copiar',
    'embedsShared.varsCopied': '¡Copiado!',
    'embedsShared.varsSearchPlaceholder': 'Buscar variables… (ej: user, server, member_count)',
    'embedsShared.varsNoResults': 'No se encontraron variables con esa búsqueda',
    'embedsShared.varsBadgeGeneral': 'General',
    'embedsShared.varsBadgeBoost': 'Solo Boosts',
    'embedsShared.modeClassic': 'Embeds clásicos',
    'embedsShared.modeLayout': 'Layout V2',
    'embedsShared.templatesUsedSuffix': ' / {limit} plantillas usadas',
    'embedsShared.noTemplatesYet': 'Todavía no hay plantillas guardadas — crea una desde "Crear / Enviar".',
    'embedsShared.badgeLayout': 'LAYOUT',
    'embedsShared.embedsCountBadge': '{count} embeds',
    'embedsShared.loadInEditor': 'Cargar en el editor',
    'embedsShared.renamePromptLabel': 'Nuevo nombre:',
    'embedsShared.rename': 'Renombrar',
    'embedsShared.confirmDeleteTemplate': '¿Eliminar la plantilla "{name}"?',
    'embedsShared.templateDeleted': 'Plantilla eliminada',
    'embedsShared.delete': 'Eliminar',
    'embedsShared.editTemplate': 'Editar',
    'embedsShared.createTemplate': '+ Crear plantilla',
    'embedsShared.usedByPrefix': 'Usada por: ',
    'embedsShared.embedLoadedFromShare': 'Embed cargado desde un link compartido',
    'embedsShared.shareExpiredOrMissing': 'Este link ya expiró o no existe',
  },
  en: {
    'embedsShared.tabMenciones': 'Mentions',
    'embedsShared.tabFecha': 'Date',
    'embedsShared.tabEmoji': 'Emoji',
    'embedsShared.searchRoleChannel': 'Search role or channel…',
    'embedsShared.noResults': 'No results',
    'embedsShared.styleShortTime': 'Short time',
    'embedsShared.styleLongTime': 'Long time',
    'embedsShared.styleShortDate': 'Short date',
    'embedsShared.styleLongDate': 'Long date',
    'embedsShared.styleShortDateTime': 'Short date/time',
    'embedsShared.styleLongDateTime': 'Long date/time',
    'embedsShared.styleRelative': 'Relative (in / ago…)',
    'embedsShared.searchEmoji': 'Search emoji…',
    'embedsShared.insertTitle': 'Insert mention, date, or emoji',
    'embedsShared.connectionError': 'Could not connect to the server.',
    'embedsShared.uploadedImagesTitle': 'Previously uploaded images',
    'embedsShared.noImagesYet': "You haven't uploaded any images in this server yet.",
    'embedsShared.uploadingImage': 'Uploading image…',
    'embedsShared.imageUploaded': 'Image uploaded',
    'embedsShared.uploadFailed': 'Upload failed: {error}',
    'embedsShared.pasteImageUrl': '…or paste an image link',
    'embedsShared.resolvingTenorGif': 'Resolving Tenor GIF…',
    'embedsShared.uploadImage': 'Upload image',
    'embedsShared.imageFormatHint': 'PNG, JPG, GIF, or WEBP, up to 8 MB.',
    'embedsShared.pasteHintTitle': 'You can also paste with {hint} while the field is focused',
    'embedsShared.noImageInClipboard': 'No image in clipboard',
    'embedsShared.useHintPaste': 'Use {hint} while the URL field is focused',
    'embedsShared.pasteButton': 'Paste ({hint})',
    'embedsShared.chooseFromUploads': 'Choose from previous uploads',
    'embedsShared.colorPurgito': 'Purgito',
    'embedsShared.colorRed': 'Red',
    'embedsShared.colorYellow': 'Yellow',
    'embedsShared.colorGreen': 'Green',
    'embedsShared.colorBlurple': 'Blurple',
    'embedsShared.colorPink': 'Pink',
    'embedsShared.colorPurple': 'Purple',
    'embedsShared.colorWhite': 'White',
    'embedsShared.colorBlack': 'Black',
    'embedsShared.rolesPingLabel': 'Roles that CAN be pinged (empty = none; Ctrl+click for multiple)',
    'embedsShared.identityWarn': 'The bot doesn\'t have "Manage Webhooks" permission in this channel, so a custom name/avatar won\'t work here — check the channel permissions or reinvite the bot.',
    'embedsShared.customIdentityLabel': 'Custom name and avatar',
    'embedsShared.customIdentityHint': "If you fill in either one, the message is sent with the channel's own webhook instead of as Purgito — buttons keep working the same.",
    'embedsShared.nameLabel': 'Name',
    'embedsShared.avatarLabel': 'Avatar',
    'embedsShared.sendOptionsSummary': 'Send options',
    'embedsShared.silentSend': 'Silent send (no push notification)',
    'embedsShared.restrictMentions': "Only mention what's explicitly set",
    'embedsShared.tabEditor': 'Create / Send',
    'embedsShared.tabTemplates': 'My templates',
    'embedsShared.tabVariables': 'Variables',
    'embedsShared.varsSectionTitle': 'Available variables',
    'embedsShared.varsSectionDesc': 'Use these variables inside your messages or embeds. Purgito will automatically replace them with the server or user info when sending the message.',
    'embedsShared.varsGeneralGroup': 'General variables',
    'embedsShared.varsGeneralDesc': 'Available in any message, embed, or server event.',
    'embedsShared.varsBoostGroup': 'Boost variables',
    'embedsShared.varsBoostDesc': 'Only available when the message is sent in response to a server Boost.',
    'embedsShared.varsCatUser': 'User',
    'embedsShared.varsCatServer': 'Server',
    'embedsShared.varsCatChannel': 'Channel',
    'embedsShared.varsCatDate': 'Date',
    'embedsShared.varsCopy': 'Copy',
    'embedsShared.varsCopied': 'Copied!',
    'embedsShared.varsSearchPlaceholder': 'Search variables… (e.g. user, server, member_count)',
    'embedsShared.varsNoResults': 'No variables found matching your search',
    'embedsShared.varsBadgeGeneral': 'General',
    'embedsShared.varsBadgeBoost': 'Boosts only',
    'embedsShared.modeClassic': 'Classic embeds',
    'embedsShared.modeLayout': 'Layout V2',
    'embedsShared.templatesUsedSuffix': ' / {limit} templates used',
    'embedsShared.noTemplatesYet': 'No templates saved yet — create one from "Create / Send".',
    'embedsShared.badgeLayout': 'LAYOUT',
    'embedsShared.embedsCountBadge': '{count} embeds',
    'embedsShared.loadInEditor': 'Load in editor',
    'embedsShared.renamePromptLabel': 'New name:',
    'embedsShared.rename': 'Rename',
    'embedsShared.confirmDeleteTemplate': 'Delete the template "{name}"?',
    'embedsShared.templateDeleted': 'Template deleted',
    'embedsShared.delete': 'Delete',
    'embedsShared.editTemplate': 'Edit',
    'embedsShared.createTemplate': '+ Create template',
    'embedsShared.usedByPrefix': 'Used by: ',
    'embedsShared.embedLoadedFromShare': 'Embed loaded from a shared link',
    'embedsShared.shareExpiredOrMissing': "This link expired or doesn't exist",
  },
});

// Modal genérico del panel (historial, JSON). Cierra con ✗, click afuera o Escape.
export function panelModal(title, body) {
  const overlay = el('div', {
    class: 'modal-overlay',
    onclick: (e) => { if (e.target === overlay) overlay.remove(); },
  },
    el('div', { class: 'modal-box' },
      el('div', { class: 'modal-head' },
        el('strong', {}, title),
        el('button', { class: 'btn btn-secondary btn-sm', onclick: () => overlay.remove() }, '✗')),
      body));
  overlay.tabIndex = -1;
  overlay.onkeydown = (e) => { if (e.key === 'Escape') overlay.remove(); };
  document.body.append(overlay);
  overlay.focus();
  return overlay;
}

export async function getEmojis() {
  if (!emojiCache) setEmojiCache((await apiFetch(`/api/server/${GUILD_ID}/emojis`)).emojis);
  return emojiCache;
}

// Galería de imágenes ya subidas por este guild (persistente entre sesiones y
// plantillas — R2 dedupe por contenido, esto solo lista qué URLs subió el
// guild). Cache en config.js, igual criterio que getEmojis.
export async function getUploadedImages() {
  if (!uploadedImagesCache) setUploadedImagesCache((await apiFetch(`/api/server/${GUILD_ID}/embeds/uploads`)).urls);
  return uploadedImagesCache;
}

// Emojis unicode comunes con palabras clave en español para el buscador.
// Lista curada a propósito (un índice completo de unicode pesa cientos de KB).
const EMOJI_LIST = [
  ['😀', 'sonrisa feliz'], ['😂', 'risa llorar'], ['🤣', 'carcajada risa'], ['😊', 'sonrisa tierna'],
  ['😍', 'enamorado corazones'], ['🥰', 'amor carino'], ['😎', 'lentes cool'], ['🤔', 'pensando duda'],
  ['😅', 'risa nervios'], ['😭', 'llorar triste'], ['😢', 'lagrima triste'], ['😡', 'enojado furia'],
  ['🥺', 'ojitos porfa'], ['😴', 'dormir sueno'], ['🤯', 'explota mente'], ['😱', 'grito susto'],
  ['🙄', 'ojos vueltos'], ['😉', 'guino'], ['🤗', 'abrazo'], ['🤫', 'silencio secreto'],
  ['👍', 'pulgar arriba ok'], ['👎', 'pulgar abajo'], ['👏', 'aplausos'], ['🙌', 'manos celebrar'],
  ['🙏', 'gracias rezar porfa'], ['💪', 'fuerza musculo'], ['🤝', 'apreton trato'], ['👋', 'hola chau saludo'],
  ['✌️', 'paz victoria'], ['🤞', 'suerte dedos'], ['👀', 'ojos mirando'], ['🧠', 'cerebro'],
  ['❤️', 'corazon rojo amor'], ['🧡', 'corazon naranja'], ['💛', 'corazon amarillo'], ['💚', 'corazon verde'],
  ['💙', 'corazon azul'], ['💜', 'corazon violeta'], ['🖤', 'corazon negro'], ['💔', 'corazon roto'],
  ['✨', 'brillos destellos'], ['⭐', 'estrella'], ['🌟', 'estrella brillante'], ['🔥', 'fuego'],
  ['💥', 'explosion boom'], ['🎉', 'fiesta confeti festejo'], ['🎊', 'festejo bola confeti'], ['🎈', 'globo'],
  ['🎁', 'regalo'], ['🏆', 'trofeo campeon'], ['🥇', 'medalla oro primero'], ['🎮', 'juego gamer control'],
  ['🎵', 'musica nota'], ['🎶', 'musica notas'], ['🎤', 'microfono cantar'], ['🎬', 'cine claqueta'],
  ['📢', 'anuncio megafono'], ['📣', 'megafono aviso'], ['🔔', 'campana notificacion'], ['🔕', 'campana silencio'],
  ['📌', 'pin fijado'], ['📍', 'ubicacion pin'], ['📎', 'clip adjunto'], ['🔗', 'link enlace'],
  ['📅', 'calendario fecha'], ['⏰', 'reloj alarma'], ['⏳', 'reloj arena espera'], ['🕐', 'reloj hora'],
  ['✅', 'check listo verde'], ['❌', 'cruz error rojo'], ['⚠️', 'advertencia cuidado'], ['🚫', 'prohibido'],
  ['❓', 'pregunta duda'], ['❗', 'exclamacion importante'], ['💡', 'idea foco'], ['🔒', 'candado bloqueado'],
  ['🔓', 'candado abierto'], ['🔑', 'llave'], ['⚙️', 'engranaje config'], ['🛠️', 'herramientas'],
  ['📝', 'nota escribir'], ['📖', 'libro leer'], ['📊', 'grafico estadisticas'], ['💰', 'dinero bolsa'],
  ['💎', 'diamante gema'], ['🚀', 'cohete lanzamiento'], ['🌈', 'arcoiris'], ['☀️', 'sol'],
  ['🌙', 'luna noche'], ['⛈️', 'tormenta lluvia'], ['❄️', 'nieve copo'], ['🌊', 'ola mar'],
  ['🍕', 'pizza'], ['🍔', 'hamburguesa'], ['🌮', 'taco'], ['🍦', 'helado'],
  ['☕', 'cafe'], ['🍺', 'cerveza'], ['🐱', 'gato'], ['🐶', 'perro'],
  ['🦊', 'zorro'], ['🐸', 'rana'], ['🐢', 'tortuga'], ['🦆', 'pato'],
];

// Inserta texto en la posición del cursor del input/textarea activo y dispara
// 'input' para que los handlers existentes actualicen estado + preview.
export function insertAtCursor(input, text) {
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  input.value = input.value.slice(0, start) + text + input.value.slice(end);
  const pos = start + text.length;
  input.selectionStart = input.selectionEnd = pos;
  input.focus();
  input.dispatchEvent(new Event('input'));
}

// --- Popover unificado de inserción (menciones / fecha / emoji) ---

let _insPop = null;
let _insPopAnchor = null;
let _insPopFrame = null;

export function closeInsertPopover() {
  if (_insPop) { _insPop.remove(); _insPop = null; }
  _insPopAnchor = null;
  if (_insPopFrame !== null) {
    cancelAnimationFrame(_insPopFrame);
    _insPopFrame = null;
  }
  document.removeEventListener('pointerdown', _insPopOutside);
  document.removeEventListener('mousedown', _insPopOutside);
  document.removeEventListener('scroll', _insPopScroll, true);
  window.removeEventListener('resize', _scheduleInsertPopoverPosition);
  window.removeEventListener('orientationchange', _scheduleInsertPopoverPosition);
  window.visualViewport?.removeEventListener('resize', _scheduleInsertPopoverPosition);
  window.visualViewport?.removeEventListener('scroll', _scheduleInsertPopoverPosition);
}
function _insPopOutside(e) {
  if (_insPop && !_insPop.contains(e.target) && (!_insPopAnchor || !_insPopAnchor.contains(e.target))) {
    closeInsertPopover();
  }
}
// El popover es position:fixed anclado a su campo; si el formulario o contenedor
// se mueve por debajo, el popover se reposiciona o cierra si el campo sale de vista.
function _insPopScroll(e) {
  if (_insPop && !_insPop.contains(e.target)) {
    _scheduleInsertPopoverPosition();
  }
}

// Los `position: fixed` se calculan contra el viewport visible. En Safari
// móvil ese viewport cambia al abrir el teclado, contraer la barra URL o rotar
// el dispositivo; requestAnimationFrame agrupa los eventos de resize/scroll en
// una sola lectura y escritura por frame.
function _positionInsertPopover() {
  _insPopFrame = null;
  if (!_insPop || !_insPopAnchor || !_insPopAnchor.isConnected) {
    closeInsertPopover();
    return;
  }
  const margin = 8;
  const anchor = _insPopAnchor.getBoundingClientRect();
  const pop = _insPop.getBoundingClientRect();
  const viewport = window.visualViewport;
  const left = viewport ? viewport.offsetLeft : 0;
  const top = viewport ? viewport.offsetTop : 0;
  const width = viewport ? viewport.width : window.innerWidth;
  const height = viewport ? viewport.height : window.innerHeight;

  // Si el anchor quedó completamente fuera de la vista visible, cerrar.
  if (anchor.bottom < top || anchor.top > top + height) {
    closeInsertPopover();
    return;
  }

  // Decidir si abrir hacia abajo o hacia arriba según el espacio libre en el viewport
  const spaceBelow = top + height - anchor.bottom - 4;
  const spaceAbove = anchor.top - top - 4;
  const fitsBelow = spaceBelow >= pop.height;

  let calculatedTop;
  if (fitsBelow || spaceBelow >= spaceAbove) {
    calculatedTop = anchor.bottom + 4;
  } else {
    calculatedTop = anchor.top - pop.height - 4;
  }

  const maxLeft = Math.max(left + margin, left + width - pop.width - margin);
  const maxTop = Math.max(top + margin, top + height - pop.height - margin);

  _insPop.style.left = Math.max(left + margin, Math.min(anchor.left, maxLeft)) + 'px';
  _insPop.style.top = Math.max(top + margin, Math.min(calculatedTop, maxTop)) + 'px';
}

function _scheduleInsertPopoverPosition() {
  if (_insPopFrame !== null) cancelAnimationFrame(_insPopFrame);
  _insPopFrame = requestAnimationFrame(_positionInsertPopover);
}

const INS_TAB_LABELS = {
  get menciones() { return t('embedsShared.tabMenciones'); },
  get fecha() { return t('embedsShared.tabFecha'); },
  get emoji() { return t('embedsShared.tabEmoji'); },
};

export function openInsertPopover(anchor, input, tabs, initialTab) {
  closeInsertPopover();
  const pop = el('div', { class: 'ins-pop' });
  const body = el('div', { class: 'ins-pop-body' });
  let active = initialTab && tabs.includes(initialTab) ? initialTab : tabs[0];
  const tabBar = el('div', { class: 'ins-pop-tabs' });

  function renderTabs() {
    tabBar.innerHTML = '';
    for (const tabKey of tabs) {
      tabBar.append(el('div', {
        class: 'ins-pop-tab' + (tabKey === active ? ' active' : ''),
        onclick: () => {
          active = tabKey;
          renderTabs();
          renderBody().finally(_scheduleInsertPopoverPosition);
        },
      }, INS_TAB_LABELS[tabKey]));
    }
  }

  function insert(text, ev) {
    insertAtCursor(input, text);
    // Shift+click mantiene el popover abierto para insertar varios seguidos.
    if (!ev || !ev.shiftKey) closeInsertPopover();
  }

  async function renderBody() {
    body.innerHTML = '';
    if (active === 'menciones') {
      body.append(spinner());
      let roles, channels;
      try { [roles, channels] = await Promise.all([getRoles(), getChannels()]); }
      catch (e) { body.innerHTML = ''; body.append(el('p', { class: 'error' }, e.message)); _scheduleInsertPopoverPosition(); return; }
      body.innerHTML = '';
      const search = el('input', { type: 'text', placeholder: t('embedsShared.searchRoleChannel') });
      const list = el('div', { class: 'ins-pop-list' });
      function renderList() {
        const q = search.value.trim().toLowerCase();
        list.innerHTML = '';
        for (const r of roles) {
          if (q && !r.name.toLowerCase().includes(q)) continue;
          list.append(el('div', { class: 'ins-pop-item', onclick: (ev) => insert(`<@&${r.id}>`, ev) },
            el('span', { class: 'ins-dot', style: 'background:' + (r.color !== '#000000' ? r.color : 'var(--text-muted)') }),
            '@' + r.name));
        }
        for (const c of channels) {
          if (q && !c.name.toLowerCase().includes(q)) continue;
          list.append(el('div', { class: 'ins-pop-item', onclick: (ev) => insert(`<#${c.id}>`, ev) }, '#' + c.name));
        }
        if (!list.children.length) list.append(el('p', { class: 'dim', style: 'padding:8px' }, t('embedsShared.noResults')));
        _scheduleInsertPopoverPosition();
      }
      search.oninput = renderList;
      body.append(search, list);
      renderList();
      search.focus();
    } else if (active === 'fecha') {
      // datetime-local nativo, redondeado al minuto actual.
      const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      const dt = el('input', { type: 'datetime-local', value: now });
      const list = el('div', { class: 'ins-pop-list' });
      const STYLES = [
        ['t', t('embedsShared.styleShortTime')], ['T', t('embedsShared.styleLongTime')], ['d', t('embedsShared.styleShortDate')],
        ['D', t('embedsShared.styleLongDate')], ['f', t('embedsShared.styleShortDateTime')], ['F', t('embedsShared.styleLongDateTime')],
        ['R', t('embedsShared.styleRelative')],
      ];
      // El formato en sí (Intl.DateTimeFormat/RelativeTimeFormat) vive en
      // discordTimestampText, compartido con el renderer del Preview.
      function renderStyles() {
        const date = dt.value ? new Date(dt.value) : new Date();
        list.innerHTML = '';
        for (const [code, label] of STYLES) {
          list.append(el('div', {
            class: 'ins-pop-item',
            onclick: (ev) => insert(`<t:${Math.floor(date.getTime() / 1000)}:${code}>`, ev),
          },
            el('span', { class: 'ins-item-label' }, label),
            el('span', { class: 'dim' }, discordTimestampText(date, code))));
        }
        _scheduleInsertPopoverPosition();
      }
      dt.onchange = renderStyles;
      body.append(el('div', { class: 'field' }, dt), list);
      renderStyles();
    } else {
      // emoji
      const search = el('input', { type: 'text', placeholder: t('embedsShared.searchEmoji') });
      const grid = el('div', { class: 'ins-emoji-grid' });
      let custom = [];
      try { custom = await getEmojis(); } catch (e) { /* sin custom, unicode igual sirve */ }
      function renderGrid() {
        const q = search.value.trim().toLowerCase();
        grid.innerHTML = '';
        for (const em of custom) {
          if (q && !em.name.toLowerCase().includes(q)) continue;
          const code = `<${em.animated ? 'a' : ''}:${em.name}:${em.id}>`;
          grid.append(el('button', {
            class: 'ins-emoji', title: ':' + em.name + ':',
            onclick: (ev) => insert(code, ev),
          }, embedImg({ src: em.url, alt: em.name, class: 'ins-emoji-img' })));
        }
        for (const [ch, keywords] of EMOJI_LIST) {
          if (q && !keywords.includes(q)) continue;
          grid.append(el('button', { class: 'ins-emoji', onclick: (ev) => insert(ch, ev) }, ch));
        }
        if (!grid.children.length) grid.append(el('p', { class: 'dim', style: 'padding:8px' }, 'Sin resultados'));
        _scheduleInsertPopoverPosition();
      }
      search.oninput = renderGrid;
      body.append(search, grid);
      renderGrid();
      search.focus();
    }
  }

  pop.append(tabBar, body);
  pop.onkeydown = (e) => { if (e.key === 'Escape') { closeInsertPopover(); input.focus(); } };
  document.body.append(pop);
  _insPop = pop;
  _insPopAnchor = anchor;
  document.addEventListener('pointerdown', _insPopOutside);
  document.addEventListener('mousedown', _insPopOutside);
  document.addEventListener('scroll', _insPopScroll, true);
  window.addEventListener('resize', _scheduleInsertPopoverPosition);
  window.addEventListener('orientationchange', _scheduleInsertPopoverPosition);
  window.visualViewport?.addEventListener('resize', _scheduleInsertPopoverPosition);
  window.visualViewport?.addEventListener('scroll', _scheduleInsertPopoverPosition);
  renderTabs();
  _scheduleInsertPopoverPosition();
  renderBody().finally(_scheduleInsertPopoverPosition);
}

// Envuelve un input/textarea con el botón de inserción asistida + atajos
// Ctrl/Cmd+M (menciones), Ctrl/Cmd+P (fecha), Ctrl/Cmd+E (emoji).
export function insertWrap(input, tabs) {
  const btn = el('button', {
    type: 'button', class: 'ins-btn', title: t('embedsShared.insertTitle'),
    onclick: () => openInsertPopover(btn, input, tabs),
  });
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>';
  const SHORTCUTS = { m: 'menciones', p: 'fecha', e: 'emoji' };
  input.addEventListener('keydown', (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || ev.shiftKey) return;
    const tab = SHORTCUTS[ev.key.toLowerCase()];
    // preventDefault SOLO para las combinaciones propias (no pisar otras del navegador).
    if (tab && tabs.includes(tab)) { ev.preventDefault(); openInsertPopover(btn, input, tabs, tab); }
  });
  return el('div', { class: 'ins-wrap' }, input, btn);
}

// --- Subida directa de imágenes (5.2) ---

export async function uploadImageBlob(blob) {
  let r;
  try {
    r = await fetch(`/api/server/${GUILD_ID}/embeds/upload`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': blob.type || 'application/octet-stream' },
      body: blob,
    });
  } catch (e) {
    throw new Error(t('embedsShared.connectionError'));
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || humanError(r.status));
  // El backend ya la indexó en la galería persistente del guild; si el cache
  // local ya está cargado, adelantamos el resultado sin esperar un refetch.
  if (uploadedImagesCache && !uploadedImagesCache.includes(data.url)) {
    setUploadedImagesCache([data.url, ...uploadedImagesCache]);
  }
  return data.url;
}

// Resuelve un link de tenor.com/view/... al .gif animado real (Fase 4) —
// corre del lado del servidor porque CORS no deja pegarle a tenor.com desde
// acá. null si no se pudo (el caller cae al aviso manual de siempre).
export async function resolveTenorUrl(url) {
  try {
    const resp = await apiFetch(`/api/server/${GUILD_ID}/embeds/resolve-gif`, {
      method: 'POST', body: { url },
    });
    return resp.url || null;
  } catch (e) {
    return null;
  }
}

// --- Subida de archivos para bloques File de Layout V2 (Fase 2 ronda 2) ---
// A diferencia de uploadImageBlob, esto NO persiste en R2: el backend lo
// guarda en memoria del proceso con un TTL corto (ver _pending_layout_files
// en webapi.py), solo hasta que se manda con "Enviar ahora" — por eso este
// tipo de bloque no se puede programar ni guardar en plantillas. Devuelve
// { id, filename } para guardar en el bloque; el id es lo único que el envío
// necesita para encontrar los bytes reales.
export async function uploadLayoutFile(file) {
  let r;
  try {
    r = await fetch(`/api/server/${GUILD_ID}/embeds/upload-file/${encodeURIComponent(file.name)}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
  } catch (e) {
    throw new Error(t('embedsShared.connectionError'));
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || humanError(r.status));
  return { id: data.upload_id, filename: data.filename };
}

// Modal con la galería de imágenes ya subidas por el guild; clickear una la
// elige. Carga perezosa (solo al abrir), no en cada render del campo.
function openImageLibrary(onPick) {
  const body = el('div', { class: 'img-library' }, spinner());
  panelModal(t('embedsShared.uploadedImagesTitle'), body);
  getUploadedImages().then((urls) => {
    body.innerHTML = '';
    if (!urls.length) {
      body.append(emptyState(t('embedsShared.noImagesYet')));
      return;
    }
    const grid = el('div', { class: 'img-library-grid' });
    for (const u of urls) {
      grid.append(el('button', {
        type: 'button', class: 'img-library-item', title: u,
        onclick: () => { onPick(u); document.querySelector('.modal-overlay')?.remove(); },
      }, embedImg({ src: u, alt: '' })));
    }
    body.append(grid);
  }).catch((e) => { body.innerHTML = ''; body.append(el('p', { class: 'error' }, e.message)); });
}

const _PASTE_HINT = /mac/i.test(navigator.platform || '') ? '⌘V' : 'Ctrl+V';

// Widget combinado de imagen: URL manual + subir archivo + pegar del
// portapapeles + reusar ya subida. Guarda la URL final en obj[key].
export function imageField(obj, key, onChange, opts = {}) {
  const wrap = el('div', { class: 'img-field' });

  function set(url) { obj[key] = url; onChange(); render(); }

  async function handleUpload(file) {
    // Estado de carga claro dentro del widget (no dejar el botón inerte).
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'img-uploading' }, spinner(), el('span', {}, t('embedsShared.uploadingImage'))));
    try {
      const url = await uploadImageBlob(file);
      set(url);
      toast(t('embedsShared.imageUploaded'), 'ok');
    } catch (e) {
      // El error queda visible en el campo (además del toast), no solo un toast
      // que desaparece.
      render();
      wrap.prepend(el('div', { class: 'img-error' }, t('embedsShared.uploadFailed', { error: e.message })));
      toast(e.message, e.status === 429 ? 'warn' : 'err');
    }
  }

  function render() {
    wrap.innerHTML = '';
    const val = (obj[key] || '').trim();
    if (val) {
      wrap.append(el('div', { class: 'img-chip' },
        embedImg({ src: val, class: 'img-chip-thumb', alt: '' }),
        el('span', { class: 'img-chip-name', title: val }, val.length > 42 ? val.slice(0, 42) + '…' : val),
        el('button', { class: 'btn btn-danger btn-sm', onclick: () => set('') }, '✗')));
      return;
    }

    const url = el('input', { type: 'url', placeholder: t('embedsShared.pasteImageUrl') });
    const gifNote = el('div', { class: 'embed-gif-note' });
    url.oninput = () => {
      if (!opts.gif) return;
      const d = detectGif(url.value);
      gifNote.className = 'embed-gif-note' + (d ? (d.warn ? ' warn' : ' ok') : '');
      gifNote.textContent = d ? d.note : '';
    };
    url.onchange = async () => {
      let v = url.value.trim();
      if (!v) return;
      if (opts.gif) {
        const d = detectGif(v);
        if (d && !d.warn) {
          v = d.url; // Giphy: se deriva del lado del cliente, sin ir al backend.
        } else if (d && d.warn) {
          // Tenor: la página no expone el .gif directo en la URL misma (a
          // diferencia de Giphy), así que hay que resolverla del lado del
          // servidor (CORS no deja pegarle a tenor.com desde el navegador).
          // Si falla, se manda igual la URL de la página como antes de esto
          // — queda como chip roto con el mismo aviso manual de siempre.
          gifNote.className = 'embed-gif-note';
          gifNote.textContent = t('embedsShared.resolvingTenorGif');
          const resolved = await resolveTenorUrl(v);
          if (resolved) v = resolved;
        }
      }
      set(v);
    };

    const fileInput = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/gif,image/webp', style: 'display:none' });
    fileInput.onchange = () => { if (fileInput.files[0]) handleUpload(fileInput.files[0]); };
    // Ajuste 5.2: "Subir" es la acción primaria (visual y funcionalmente), el
    // campo de URL pasa a secundario para que el usuario no-técnico no vea
    // "esto empieza con una URL".
    const uploadBtn = el('button', { type: 'button', class: 'btn btn-primary', onclick: () => fileInput.click() },
      icon('image'), t('embedsShared.uploadImage'));
    const uploadHint = helpIcon(t('embedsShared.imageFormatHint'));
    const pasteBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm', title: t('embedsShared.pasteHintTitle', { hint: _PASTE_HINT }),
      onclick: async () => {
        // clipboard.read() solo anda en Chromium con permiso; el paste con
        // teclado (listener de abajo) es el camino universal.
        try {
          const items = await navigator.clipboard.read();
          for (const item of items) {
            const type = item.types.find(mime => mime.startsWith('image/'));
            if (type) { handleUpload(await item.getType(type)); return; }
          }
          toast(t('embedsShared.noImageInClipboard'), 'warn');
        } catch (e) {
          toast(t('embedsShared.useHintPaste', { hint: _PASTE_HINT }), 'warn');
        }
      },
    }, t('embedsShared.pasteButton', { hint: _PASTE_HINT }));
    url.addEventListener('paste', (ev) => {
      const file = [...(ev.clipboardData?.files || [])].find(f => f.type.startsWith('image/'));
      if (file) { ev.preventDefault(); handleUpload(file); }
    });

    const libraryBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm',
      onclick: () => openImageLibrary(set),
    }, t('embedsShared.chooseFromUploads'));
    const secondary = el('div', { class: 'img-field-secondary' }, url, pasteBtn, libraryBtn);
    wrap.append(
      el('div', { class: 'img-field-primary' }, uploadBtn, fileInput, uploadHint),
      secondary, gifNote);
  }

  render();
  return wrap;
}

// Presets rápidos: el acento propio de Purgito primero, después un puñado de
// colores reconocibles (paleta de Discord + básicos) — mismo criterio que los
// swatches de rol de Discohook, sin pretender cubrir cada hue posible.
const COLOR_PRESETS = [
  ['#13C4D8', 'Purgito'], ['#ED4245', 'Rojo'], ['#FEE75C', 'Amarillo'],
  ['#57F287', 'Verde'], ['#5865F2', 'Blurple'], ['#EB459E', 'Rosa'],
  ['#9B59B6', 'Violeta'], ['#FFFFFF', 'Blanco'], ['#2B2D31', 'Negro'],
];

// Swatch nativo + input de texto para hex, sincronizados en ambos sentidos,
// más una fila de presets rápidos.
export function colorField(obj, key, onChange) {
  const swatch = el('input', { type: 'color', value: /^#[0-9a-fA-F]{6}$/.test(obj[key]) ? obj[key] : '#8B6EF5' });
  const text = el('input', {
    type: 'text',
    class: 'color-hex-input',
    value: obj[key] || '',
    placeholder: '#8B6EF5',
    maxlength: '7',
    spellcheck: 'false',
  });

  swatch.oninput = () => {
    obj[key] = swatch.value;
    text.value = swatch.value;
    text.classList.remove('invalid');
    onChange();
  };

  text.oninput = () => {
    let v = text.value.trim();
    if (v && !v.startsWith('#')) v = '#' + v;
    if (v === '') {
      obj[key] = '';
      text.classList.remove('invalid');
      onChange();
      return;
    }
    if (/^#[0-9a-fA-F]{6}$/.test(v)) {
      obj[key] = v;
      swatch.value = v;
      text.classList.remove('invalid');
      onChange();
    } else {
      // Se deja escribir libremente (por si está a medio pegar/tipear), pero
      // no se guarda en `obj` ni se dispara onChange hasta que sea un hex
      // válido de 6 dígitos.
      text.classList.add('invalid');
    }
  };

  text.onblur = () => { text.value = obj[key] || ''; text.classList.remove('invalid'); };

  const presets = el('div', { class: 'color-presets' });
  for (const [hex, name] of COLOR_PRESETS) {
    presets.append(el('button', {
      type: 'button', class: 'color-preset', style: 'background:' + hex, title: name,
      onclick: () => { obj[key] = hex; swatch.value = hex; text.value = hex; text.classList.remove('invalid'); onChange(); },
    }));
  }

  return el('div', { class: 'color-field-wrap' }, el('div', { class: 'color-field' }, swatch, text), presets);
}

// Panel colapsable (details/summary nativo) con las opciones de envío.
// `channels` (con can_manage_webhooks por canal, ver _api_channels) y `chSel`
// (el <select> de canal destino ya armado por el caller) son opcionales —
// sin ellos simplemente no se muestra el aviso de permisos de Fase 4.
export function sendOptionsPanel(o, roles, channels, chSel) {
  const silent = el('input', { type: 'checkbox', checked: o.silent });
  silent.onchange = () => { o.silent = silent.checked; };
  const restrict = el('input', { type: 'checkbox', checked: o.restrict });
  const roleSel = el('select', { multiple: 'multiple', size: '5', class: 'send-opts-roles' });
  for (const r of roles) {
    const opt = el('option', { value: r.id }, '@' + r.name);
    opt.selected = o.roleIds.includes(r.id);
    roleSel.append(opt);
  }
  roleSel.onchange = () => { o.roleIds = [...roleSel.selectedOptions].map(x => x.value); };
  const roleBlock = el('div', { class: 'field', style: o.restrict ? '' : 'display:none' },
    el('label', {}, t('embedsShared.rolesPingLabel')),
    roleSel);
  restrict.onchange = () => { o.restrict = restrict.checked; roleBlock.style.display = o.restrict ? '' : 'none'; };

  // Identidad personalizada (Fase 3): completar cualquiera de los dos hace
  // que el envío pase de channel.send() a un webhook propio del canal (ver
  // wants_custom_identity en message_options.py) — los botones de rol siguen
  // funcionando igual, el webhook sigue siendo de la app de Purgito.
  const username = el('input', {
    type: 'text', maxlength: String(MAX_WEBHOOK_USERNAME), placeholder: 'Purgito', value: o.username,
  });
  username.oninput = () => { o.username = username.value; };
  const avatarField = imageField(o, 'avatarUrl', () => {});

  // Aviso proactivo (Fase 4): un permiso de canal faltante recién se
  // enteraba al enviar y llevarse el error del webhook — esto lo anticipa
  // apenas se elige el canal. No bloqueante: el resto del formulario sigue
  // usable, el aviso solo dice que ESTOS DOS campos no van a funcionar ahí.
  const identityWarn = el('div', { class: 'embed-warn', style: 'display:none' });
  function refreshIdentityWarn() {
    if (!channels || !chSel) return;
    const ch = channels.find(c => c.id === chSel.value);
    const blocked = !!ch && ch.can_manage_webhooks === false;
    identityWarn.style.display = blocked ? '' : 'none';
    identityWarn.textContent = blocked ? t('embedsShared.identityWarn') : '';
  }
  if (chSel) chSel.addEventListener('change', refreshIdentityWarn);
  refreshIdentityWarn();

  const identityBlock = el('div', { class: 'field' },
    el('label', {}, t('embedsShared.customIdentityLabel')),
    el('p', { class: 'dim' }, t('embedsShared.customIdentityHint')),
    identityWarn,
    el('div', { class: 'embed-two' },
      el('div', {}, el('label', {}, t('embedsShared.nameLabel')), username),
      el('div', {}, el('label', {}, t('embedsShared.avatarLabel')), avatarField)));

  const details = el('details', { class: 'send-opts' },
    el('summary', {}, t('embedsShared.sendOptionsSummary')),
    el('div', { class: 'field' }, el('label', { class: 'toggle' }, silent, t('embedsShared.silentSend'))),
    el('div', { class: 'field' }, el('label', { class: 'toggle' }, restrict, t('embedsShared.restrictMentions'))),
    roleBlock,
    identityBlock);
  if (o.silent || o.restrict || o.username || o.avatarUrl) details.open = true;
  return details;
}

export async function loadEmbeds() {
  closeInsertPopover();
  // Cambiar de tab/bloque/modo también persiste una versión en el historial.
  saveHistorySnapshot();
  const box = content();
  const tabs = el('div', { class: 'embed-tabs' },
    el('div', { class: 'embed-tab' + (_embedTab === 'editor' ? ' active' : ''), onclick: () => { setEmbedTab('editor'); loadEmbeds(); } }, t('embedsShared.tabEditor')),
    el('div', { class: 'embed-tab' + (_embedTab === 'templates' ? ' active' : ''), onclick: () => { setEmbedTab('templates'); loadEmbeds(); } }, t('embedsShared.tabTemplates')),
    el('div', { class: 'embed-tab' + (_embedTab === 'variables' ? ' active' : ''), onclick: () => { setEmbedTab('variables'); loadEmbeds(); } }, t('embedsShared.tabVariables')));
  const view = el('div', {});
  box.append(tabs, view);
  if (_embedTab === 'editor') await renderEmbedEditor(view);
  else if (_embedTab === 'templates') await renderEmbedTemplates(view);
  else if (_embedTab === 'variables') await renderEmbedVariables(view);
}

function modeRadio(mode, label) {
  return el('label', { class: 'toggle' },
    el('input', {
      type: 'radio', name: 'contentMode', checked: _embedMode === mode,
      onchange: () => { setEmbedMode(mode); loadEmbeds(); },
    }), label);
}

export async function renderEmbedEditor(box) {
  box.append(spinner());
  let channels, roles;
  // roles solo lo usa el modo Layout (botones de "asignar rol"), pero
  // getChannels/getRoles cachean tras la primera visita, así que pedirlo
  // siempre es barato y evita otro roundtrip al cambiar de modo.
  try { [channels, roles] = await Promise.all([getChannels(), getRoles()]); }
  catch (e) { renderError(box, e); return; }
  box.innerHTML = '';

  // Selector de modo: embeds clásicos vs Layout V2 (excluyentes en Discord).
  box.append(el('div', { class: 'embed-mode-sel' },
    modeRadio('classic', t('embedsShared.modeClassic')),
    modeRadio('layout', t('embedsShared.modeLayout'))));
  const inner = el('div', {});
  box.append(inner);
  if (_embedMode === 'layout') renderLayoutEditor(inner, channels, roles);
  else renderClassicEditor(inner, channels, roles);
}

const EVENT_TYPE_LABEL_KEYS = {
  welcome: 'dash.mod.welcome.label',
  goodbye: 'dash.mod.goodbye.label',
  boost: 'dash.mod.boost.label',
};

export async function renderEmbedTemplates(box) {
  box.append(spinner());
  let data;
  try { data = await apiFetch(`/api/server/${GUILD_ID}/embeds/templates`); }
  catch (e) { renderError(box, e); return; }
  box.innerHTML = '';

  const createBtn = el('button', {
    class: 'btn btn-primary btn-sm',
    style: 'margin-bottom: 12px;',
    onclick: () => {
      import('/js/tabs/plantillas.js').then(({ loadTemplateEditor }) => loadTemplateEditor(null));
    },
  }, t('embedsShared.createTemplate'));
  box.append(createBtn);

  box.append(el('p', { class: 'dim gif-stats' },
    el('strong', { class: 'stat-num' }, String(data.total)), t('embedsShared.templatesUsedSuffix', { limit: data.limit })));

  if (!data.templates.length) {
    box.append(emptyState(t('embedsShared.noTemplatesYet')));
    return;
  }

  const list = el('ul', { class: 'item-list' });
  for (const tpl of data.templates) {
    const isLayout = tpl.content_mode === 'layout_v2';
    const embeds = tpl.embeds || [];
    const first = embeds.find(x => x && Object.keys(x).length) || {};
    const color = colorToHex(first.color) || '#8B6EF5';
    const modeBadge = isLayout
      ? el('span', { class: 'badge badge-premium' }, t('embedsShared.badgeLayout'))
      : (embeds.length > 1 ? el('span', { class: 'badge' }, t('embedsShared.embedsCountBadge', { count: embeds.length })) : null);
    const usedBy = tpl.used_by || [];
    const usedByBadge = usedBy.length
      ? el('span', { class: 'badge badge-ok' }, t('embedsShared.usedByPrefix') + usedBy.map(et => t(EVENT_TYPE_LABEL_KEYS[et] || et)).join(', '))
      : null;
    const snippet = isLayout ? layoutSnippet(tpl.layout) : (tpl.content_mode === 'plain_text' ? (tpl.message || '') : templateSnippet(embeds));
    // Payload que reusa el "Renombrar" (PUT exige revalidar todo el contenido;
    // hay que preservar el resto del contenido tal cual, sin importar el modo).
    const renameBody = (name) => {
      if (isLayout) return { name, content_mode: 'layout_v2', layout: tpl.layout, send_options: tpl.send_options || undefined };
      if (tpl.content_mode === 'plain_text') return { name, content_mode: 'plain_text', message: tpl.message };
      if (tpl.content_mode === 'composite') return { name, content_mode: 'composite', message: tpl.message, embeds, buttons: tpl.buttons, send_options: tpl.send_options || undefined };
      return { name, content_mode: 'classic_embed', embeds, send_options: tpl.send_options || undefined };
    };
    const editAction = isLayout
      ? el('button', {
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            setEmbedMode('layout'); setLayoutDoc(docFromLayout(tpl.layout, tpl.id, tpl.name, tpl.send_options));
            setEmbedTab('editor'); loadEmbeds();
          },
        }, t('embedsShared.loadInEditor'))
      : el('button', {
          class: 'btn btn-secondary btn-sm',
          onclick: () => {
            import('/js/tabs/plantillas.js').then(({ loadTemplateEditor }) => loadTemplateEditor(tpl.id));
          },
        }, t('embedsShared.editTemplate'));
    list.append(el('li', {},
      el('span', {},
        el('span', { class: 'tpl-dot', style: 'background:' + color }), ' ',
        el('strong', {}, tpl.name),
        modeBadge,
        usedByBadge,
        ' — ',
        el('span', { class: 'dim' }, snippet.slice(0, 60))),
      editAction,
      el('button', {
        class: 'btn btn-secondary btn-sm',
        onclick: async () => {
          const name = (prompt(t('embedsShared.renamePromptLabel'), tpl.name) || '').trim();
          if (!name || name === tpl.name) return;
          try {
            await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${tpl.id}`, { method: 'PUT', body: renameBody(name) });
            loadEmbeds();
          } catch (err) { toast(err.message, 'err'); }
        },
      }, t('embedsShared.rename')),
      el('button', {
        class: 'btn btn-danger btn-sm',
        onclick: async () => {
          if (!confirm(t('embedsShared.confirmDeleteTemplate', { name: tpl.name }))) return;
          try {
            await apiFetch(`/api/server/${GUILD_ID}/embeds/templates/${tpl.id}`, { method: 'DELETE' });
            toast(t('embedsShared.templateDeleted'), 'ok');
            loadEmbeds();
          } catch (err) { toast(err.message, 'err'); }
        },
      }, t('embedsShared.delete'))));
  }
  box.append(list);
}

// Carga el payload de un link compartido en el editor clásico ANTES del primer
// render (activate corre en el .finally del caller). El ?share= se limpia de
// la URL para que un refresh no re-dispare la carga; el id queda en
// sessionStorage para sobrevivir un cambio de servidor vía selector.
export async function loadSharedEmbed(shareId) {
  try {
    const data = await apiFetch(`/api/embeds/share/${encodeURIComponent(shareId)}`);
    setEmbedTab('editor');
    setEmbedMode('classic');
    setEmbedDoc(docFromEmbeds(data.embeds, null, '', data.send_options));
    sessionStorage.setItem('purgito_share_id', shareId);
    toast(t('embedsShared.embedLoadedFromShare'), 'ok');
  } catch (e) {
    sessionStorage.removeItem('purgito_share_id');
    toast(e.message || t('embedsShared.shareExpiredOrMissing'), 'err');
  }
  history.replaceState({}, '', location.pathname);
}

export async function renderEmbedVariables(box) {
  box.append(spinner());
  let data;
  try {
    data = await apiFetch(`/api/server/${GUILD_ID}/events`);
  } catch (e) {
    renderError(box, e);
    return;
  }
  box.innerHTML = '';

  const allVars = data.variables || [];

  const header = el('div', { class: 'embed-vars-header' },
    el('h2', { class: 'cfg-field-label', style: 'font-size: 16px; margin: 0 0 4px 0;' },
      icon('sparkle'), t('embedsShared.varsSectionTitle')
    ),
    el('p', { class: 'dim text-sm', style: 'margin: 0 0 16px 0;' }, t('embedsShared.varsSectionDesc'))
  );

  const searchInput = el('input', {
    type: 'search',
    class: 'form-control form-control-sm var-modal-search',
    placeholder: t('embedsShared.varsSearchPlaceholder'),
  });

  const searchWrap = el('div', { class: 'embed-vars-search-wrap' }, searchInput);

  const container = el('div', { class: 'embed-vars-container' });

  function renderList() {
    container.innerHTML = '';
    const q = searchInput.value.toLowerCase().trim();

    const filtered = allVars.filter(v =>
      !q ||
      v.name.toLowerCase().includes(q) ||
      (v.description || '').toLowerCase().includes(q) ||
      (v.category || '').toLowerCase().includes(q) ||
      (v.example || '').toLowerCase().includes(q)
    );

    if (!filtered.length) {
      container.append(emptyState(t('embedsShared.varsNoResults')));
      return;
    }

    const generalVars = filtered.filter(v => (v.allowed_events || []).length >= 3 || v.category !== 'boost');
    const boostVars = filtered.filter(v => (v.allowed_events || []).length < 3 && v.category === 'boost');

    function createVarCard(v, isBoost = false) {
      const varTag = `{${v.name}}`;
      const copyBtn = el('button', {
        type: 'button',
        class: 'btn btn-secondary btn-xs',
        onclick: async () => {
          if (navigator.clipboard) {
            try {
              await navigator.clipboard.writeText(varTag);
            } catch (_) {}
          }
          toast(t('tabsEventos.varsCopied', { var: varTag }) || `Variable ${varTag} copiada`, 'ok');
          copyBtn.textContent = t('embedsShared.varsCopied');
          setTimeout(() => { copyBtn.textContent = t('embedsShared.varsCopy'); }, 1500);
        },
      }, t('embedsShared.varsCopy'));

      const badge = isBoost
        ? el('span', { class: 'badge badge-dim' }, t('embedsShared.varsBadgeBoost'))
        : el('span', { class: 'badge badge-ok' }, t('embedsShared.varsBadgeGeneral'));

      const topRow = el('div', { class: 'embed-var-top' },
        el('code', { class: 'embed-var-tag' }, varTag),
        badge
      );

      const bodyChildren = [
        el('p', { class: 'embed-var-desc' }, v.description || '')
      ];
      if (v.example) {
        bodyChildren.push(el('p', { class: 'embed-var-example' }, `${t('tabsEventos.varExample')} `, el('code', {}, v.example)));
      }

      const bodyCol = el('div', { class: 'embed-var-body' }, ...bodyChildren);

      const footerRow = el('div', { class: 'embed-var-footer' },
        el('span', { class: 'dim text-xs' }, v.category ? v.category.toUpperCase() : ''),
        copyBtn
      );

      return el('div', { class: 'embed-var-card' }, topRow, bodyCol, footerRow);
    }

    if (generalVars.length) {
      const generalGrid = el('div', { class: 'embed-vars-grid' }, ...generalVars.map(v => createVarCard(v, false)));
      const generalSection = el('div', { class: 'embed-vars-group' },
        el('h3', { class: 'embed-vars-group-title' }, icon('sparkle'), t('embedsShared.varsGeneralGroup')),
        el('p', { class: 'embed-vars-group-desc' }, t('embedsShared.varsGeneralDesc')),
        generalGrid
      );
      container.append(generalSection);
    }

    if (boostVars.length) {
      const boostGrid = el('div', { class: 'embed-vars-grid' }, ...boostVars.map(v => createVarCard(v, true)));
      const boostSection = el('div', { class: 'embed-vars-group' },
        el('h3', { class: 'embed-vars-group-title' }, icon('star'), t('embedsShared.varsBoostGroup')),
        el('p', { class: 'embed-vars-group-desc' }, t('embedsShared.varsBoostDesc')),
        boostGrid
      );
      container.append(boostSection);
    }
  }

  searchInput.oninput = renderList;
  renderList();

  box.append(header, searchWrap, container);
}
