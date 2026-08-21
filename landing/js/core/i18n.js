// Localización del dashboard: una tabla de strings por módulo, registrada
// con addStrings() en cada archivo que la necesita, y una única función de
// lookup (t) que todos comparten. No hay un archivo gigante con todos los
// strings del sitio -- cada módulo (dash.js, tabs/gifs.js, etc.) registra
// los suyos junto al código que los usa, igual que ya está organizado el
// resto de landing/js/. Fallback en runtime: en -> es -> la key misma.
//
// Las keys son strings planos con puntos por legibilidad/namespacing
// (ej. "dash.chat.save") pero NO se recorren como objeto anidado -- son
// una sola propiedad literal. Eso hace que registrar strings de dos
// módulos distintos sea un merge plano sin riesgo de que uno pise el
// namespace del otro.
//
// El idioma sale de currentLocale() (core/config.js), la misma fuente que
// ya usan formatNumber/formatDate -- no una segunda resolución de idioma.

import { currentLocale } from './config.js';

const STRINGS = { es: {}, en: {} };

/** Registra strings de un módulo. Se puede llamar varias veces: cada
 * llamada mezcla sus keys en la tabla ya existente, no la reemplaza. */
export function addStrings(partial) {
  for (const lang of Object.keys(partial)) {
    Object.assign((STRINGS[lang] ??= {}), partial[lang]);
  }
}

/** Traduce `key` (ej. "dash.chat.save") al idioma de la URL. `vars`
 * interpola `{nombre}` dentro del string resuelto. Si la key no existe en
 * el idioma activo cae a español, y si tampoco existe ahí devuelve la key
 * tal cual -- nunca revienta la UI por una key faltante. */
export function t(key, vars) {
  let val = STRINGS[currentLocale()]?.[key];
  if (val === undefined) val = STRINGS.es[key];
  if (val === undefined) return key;
  if (vars) {
    for (const [name, v] of Object.entries(vars)) {
      val = val.replaceAll(`{${name}}`, v);
    }
  }
  return val;
}

/** Keys que existen en un idioma y no en el otro. Usado solo por el test
 * de cobertura (landing/test_lang.mjs) -- no se llama en runtime, así que
 * una traducción incompleta nunca rompe la UI en producción, pero sí hace
 * fallar el test. */
export function missingKeys() {
  const missing = [];
  for (const k of Object.keys(STRINGS.es)) if (!(k in STRINGS.en)) missing.push({ lang: 'en', key: k });
  for (const k of Object.keys(STRINGS.en)) if (!(k in STRINGS.es)) missing.push({ lang: 'es', key: k });
  return missing;
}
