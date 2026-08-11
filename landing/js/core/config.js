// Estado global compartido del dashboard: el guild activo, el idioma del sitio
// y los caches de roles/canales/emojis que varios módulos leen.
//
// GUILD_ID sale de la URL (/es/dashboard/<id>/<tab>) y no de un atributo que
// inyecte el servidor: las páginas son HTML estático, nadie las renderiza por
// request. Es constante desde el primer import, así que cualquier módulo puede
// usarla sin esperar a una inicialización.
//
// Los caches viven acá (y no en panel-shell.js, que es quien los llena vía
// getChannels/getRoles) para que core/markdown.js pueda leer roleCache/
// channelCache sin importar de panel-shell y armar un ciclo innecesario.
// Se exponen como `export let` (binding vivo de lectura) + un setter, porque
// un módulo importador no puede reasignar un binding importado.

export const LANGS = ['es', 'en', 'ru', 'ja', 'de'];

/** Idioma del prefijo de ruta; español si la URL no trae uno conocido. */
export function currentLocale() {
  const seg = location.pathname.split('/')[1];
  return LANGS.includes(seg) ? seg : 'es';
}

/** Número formateado según el idioma de la URL, no fijo a 'es'. */
export function formatNumber(n) {
  return n.toLocaleString(currentLocale());
}

/** Fecha formateada según el idioma de la URL. `opts` pasa directo a
 * Intl.DateTimeFormat (mismos options que Date.toLocaleDateString/String). */
export function formatDate(date, opts) {
  return date.toLocaleDateString(currentLocale(), opts);
}

/** Igual que formatDate pero con hora — para timestamps de eventos/historial. */
export function formatDateTime(date) {
  return date.toLocaleString(currentLocale());
}

// Solo dígitos: un id inventado a mano en la barra de direcciones muere acá y
// no llega a armar URLs de API.
const rawGuild = location.pathname.split('/')[3] || '';
export const GUILD_ID = /^\d{1,25}$/.test(rawGuild) ? rawGuild : '';

export let channelCache = null;
export let roleCache = null;
export let emojiCache = null;
export let uploadedImagesCache = null;
export function setChannelCache(v) { channelCache = v; }
export function setRoleCache(v) { roleCache = v; }
export function setEmojiCache(v) { emojiCache = v; }
export function setUploadedImagesCache(v) { uploadedImagesCache = v; }
